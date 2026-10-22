from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import numpy as np

from ..models import Decision
from .rl_env import ResearchMARLEnv, ResearchObservationEncoder


def _torch():
    try:
        import torch
        import torch.nn as nn
        return torch, nn
    except ImportError as exc:
        raise ImportError("MAPPO baselines require PyTorch; install requirements_research.txt") from exc


class SharedActorCritic:
    """Thin wrapper so importing the research package does not require torch."""

    def __init__(self, obs_dim, state_dim, action_dim=3, hidden=192, safe=False, device="cpu"):
        torch, nn = _torch()

        class Net(nn.Module):
            def __init__(self):
                super().__init__()
                self.actor = nn.Sequential(nn.Linear(obs_dim, hidden), nn.Tanh(),
                                           nn.Linear(hidden, hidden), nn.Tanh(),
                                           nn.Linear(hidden, action_dim))
                self.log_std = nn.Parameter(torch.full((action_dim,), -0.5))
                self.critic = nn.Sequential(nn.Linear(state_dim, hidden), nn.Tanh(),
                                            nn.Linear(hidden, hidden), nn.Tanh(), nn.Linear(hidden, 1))
                self.cost_critic = (nn.Sequential(nn.Linear(state_dim, hidden), nn.Tanh(),
                                                   nn.Linear(hidden, hidden), nn.Tanh(), nn.Linear(hidden, 1))
                                    if safe else None)

            def distribution(self, obs):
                mean = self.actor(obs)
                std = self.log_std.exp().expand_as(mean)
                return torch.distributions.Normal(mean, std)

            def value(self, state):
                return self.critic(state).squeeze(-1)

            def cost_value(self, state):
                if self.cost_critic is None:
                    return torch.zeros(state.shape[:-1], device=state.device)
                return self.cost_critic(state).squeeze(-1)

        self.torch = torch
        self.device = torch.device(device)
        self.safe = bool(safe)
        self.model = Net().to(self.device)

    def state_dict(self):
        return self.model.state_dict()

    def load_state_dict(self, state):
        return self.model.load_state_dict(state)

    def deterministic(self, obs):
        torch = self.torch
        with torch.no_grad():
            tensor = torch.as_tensor(obs, dtype=torch.float32, device=self.device)
            mean = self.model.actor(tensor)
            return torch.tanh(mean).cpu().numpy()

    def sample(self, obs, state):
        torch = self.torch
        obs_t = torch.as_tensor(obs, dtype=torch.float32, device=self.device)
        state_t = torch.as_tensor(state, dtype=torch.float32, device=self.device)
        dist = self.model.distribution(obs_t)
        raw = dist.rsample()
        action = torch.tanh(raw)
        logp = (dist.log_prob(raw) - torch.log(1 - action.pow(2) + 1e-6)).sum()
        return (action.detach().cpu().numpy(), raw.detach().cpu().numpy(), float(logp.detach().cpu()),
                float(self.model.value(state_t).detach().cpu()),
                float(self.model.cost_value(state_t).detach().cpu()))


@dataclass
class MAPPOTrainConfig:
    updates: int = 300
    rollout_steps: int = 256
    epochs: int = 8
    minibatch: int = 64
    gamma: float = 0.99
    gae_lambda: float = 0.95
    clip_ratio: float = 0.2
    lr: float = 3e-4
    value_coef: float = 0.5
    entropy_coef: float = 0.01
    max_grad_norm: float = 0.5
    cost_limit: float = 0.02
    lagrange_lr: float = 0.05


def _gae(rewards, values, dones, bootstrap, gamma, lam):
    advantages = np.zeros_like(rewards, dtype=np.float32)
    last = 0.0
    next_value = float(bootstrap)
    for t in reversed(range(len(rewards))):
        nonterminal = 1.0 - float(dones[t])
        delta = rewards[t] + gamma * next_value * nonterminal - values[t]
        last = delta + gamma * lam * nonterminal * last
        advantages[t] = last
        next_value = values[t]
    return advantages, advantages + values


def train_mappo(cfg, output_path, *, safe=False, seed=0, train: MAPPOTrainConfig | None = None,
                device="cpu", progress=None):
    """Train the homogeneous CTDE baseline on the paper task.

    The implementation is intentionally self-contained and saves all optimizer
    hyperparameters.  `safe=True` adds a Lagrangian constraint on observed target
    visibility loss; this is the constrained-learning baseline, not part of ECP-RH.
    """
    torch, _ = _torch()
    settings = train or MAPPOTrainConfig()
    np.random.seed(int(seed)); torch.manual_seed(int(seed))
    env = ResearchMARLEnv(cfg, seed=seed)
    obs, state = env.reset(seed=seed)
    net = SharedActorCritic(env.obs_dim, len(state), env.action_dim, safe=safe, device=device)
    optimizer = torch.optim.Adam(net.model.parameters(), lr=settings.lr)
    lagrange = 0.0
    history = []
    for update in range(settings.updates):
        O=[]; S=[]; U=[]; LP=[]; V=[]; CV=[]; R=[]; C=[]; D=[]
        for _ in range(settings.rollout_steps):
            action, raw, logp, value, cost_value = net.sample(obs, state)
            next_obs, next_state, reward, cost, done, info = env.step(action)
            O.append(obs.copy()); S.append(state.copy()); U.append(raw.copy()); LP.append(logp)
            V.append(value); CV.append(cost_value); R.append(reward); C.append(cost); D.append(done)
            obs, state = next_obs, next_state
            if done:
                obs, state = env.reset(seed=seed + update + len(R) + 1)
        with torch.no_grad():
            state_t = torch.as_tensor(state, dtype=torch.float32, device=net.device)
            bootstrap = float(net.model.value(state_t).cpu())
            cost_bootstrap = float(net.model.cost_value(state_t).cpu()) if safe else 0.0
        adv, returns = _gae(np.asarray(R,np.float32), np.asarray(V,np.float32), np.asarray(D,bool),
                            bootstrap, settings.gamma, settings.gae_lambda)
        cadv, creturns = _gae(np.asarray(C,np.float32), np.asarray(CV,np.float32), np.asarray(D,bool),
                              cost_bootstrap, settings.gamma, settings.gae_lambda)
        adv = (adv - adv.mean()) / (adv.std() + 1e-8)
        if safe:
            cadv = (cadv - cadv.mean()) / (cadv.std() + 1e-8)
        combined = adv - float(lagrange) * cadv if safe else adv
        obs_batch = torch.as_tensor(np.asarray(O), dtype=torch.float32, device=net.device)
        state_batch = torch.as_tensor(np.asarray(S), dtype=torch.float32, device=net.device)
        raw_batch = torch.as_tensor(np.asarray(U), dtype=torch.float32, device=net.device)
        old_logp = torch.as_tensor(np.asarray(LP), dtype=torch.float32, device=net.device)
        adv_batch = torch.as_tensor(combined, dtype=torch.float32, device=net.device)
        return_batch = torch.as_tensor(returns, dtype=torch.float32, device=net.device)
        cost_return_batch = torch.as_tensor(creturns, dtype=torch.float32, device=net.device)
        indices = np.arange(settings.rollout_steps)
        losses = []
        for _ in range(settings.epochs):
            np.random.shuffle(indices)
            for start in range(0, len(indices), settings.minibatch):
                idx = indices[start:start+settings.minibatch]
                ob = obs_batch[idx]              # B x N x D
                st = state_batch[idx]            # B x state_dim
                raw = raw_batch[idx]             # B x N x A
                dist = net.model.distribution(ob)
                action = torch.tanh(raw)
                logp = (dist.log_prob(raw) - torch.log(1 - action.pow(2) + 1e-6)).sum(dim=(-1,-2))
                ratio = torch.exp(logp - old_logp[idx])
                a = adv_batch[idx]
                clipped = torch.clamp(ratio, 1-settings.clip_ratio, 1+settings.clip_ratio)
                policy_loss = -torch.minimum(ratio*a, clipped*a).mean()
                value_loss = (net.model.value(st) - return_batch[idx]).pow(2).mean()
                cost_value_loss = ((net.model.cost_value(st) - cost_return_batch[idx]).pow(2).mean()
                                   if safe else torch.tensor(0.0, device=net.device))
                entropy = dist.entropy().sum(dim=(-1,-2)).mean()
                loss = policy_loss + settings.value_coef*(value_loss + cost_value_loss) - settings.entropy_coef*entropy
                optimizer.zero_grad(); loss.backward()
                torch.nn.utils.clip_grad_norm_(net.model.parameters(), settings.max_grad_norm)
                optimizer.step()
                losses.append(float(loss.detach().cpu()))
        mean_cost = float(np.mean(C))
        if safe:
            lagrange = max(0.0, lagrange + settings.lagrange_lr * (mean_cost - settings.cost_limit))
        row = {"update": update, "reward_mean": float(np.mean(R)), "cost_mean": mean_cost,
               "loss_mean": float(np.mean(losses)) if losses else 0.0, "lagrange": float(lagrange)}
        history.append(row)
        if progress:
            progress(row)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = {
        "state_dict": net.state_dict(), "safe": bool(safe), "seed": int(seed),
        "obs_dim": env.obs_dim, "state_dim": env.n_agents*env.obs_dim,
        "action_dim": env.action_dim, "n_agents": env.n_agents,
        "train_config": settings.__dict__, "history": history,
    }
    torch.save(checkpoint, output)
    output.with_suffix(output.suffix + ".json").write_text(json.dumps({k:v for k,v in checkpoint.items() if k != "state_dict"},
        ensure_ascii=False, indent=2), encoding="utf-8")
    return output


class MAPPOPolicy:
    """Control-center inference wrapper for a trained MAPPO/Safe-MAPPO checkpoint."""

    def __init__(self, cfg):
        self.cfg = cfg
        options = cfg.policy.get("research", {}).get("baselines", {}).get("mappo", {})
        path = options.get("model_path")
        if not path:
            raise ValueError("MAPPO baseline requires research.baselines.mappo.model_path")
        self.encoder = ResearchObservationEncoder(cfg,
            max_targets=int(options.get("max_targets", 6)), top_search_cells=int(options.get("top_search_cells", 8)))
        torch, _ = _torch()
        checkpoint = torch.load(path, map_location=options.get("device", "cpu"), weights_only=False)
        self.net = SharedActorCritic(self.encoder.obs_dim, len(cfg.active_devices)*self.encoder.obs_dim,
                                     safe=bool(checkpoint.get("safe", False)), device=options.get("device", "cpu"))
        self.net.load_state_dict(checkpoint["state_dict"])
        self.replan_s = float(cfg.policy.get("research", {}).get("planning", {}).get("replan_period_s", 0.5))
        self.reset()

    def reset(self):
        self.last_t = -float("inf")
        self.cached = {}

    def decide(self, context):
        if context.research.get("mission") != "search_monitor":
            raise ValueError("MAPPO research policy requires search_monitor mission")
        if self.cached and context.t - self.last_t < self.replan_s - 1e-9:
            from dataclasses import replace
            return Decision({k: replace(v, issued_t=context.t) for k,v in self.cached.items()},
                            {"algorithm":"safe_mappo" if self.net.safe else "mappo", "cached_plan":True})
        obs = self.encoder.encode(context)
        action = self.net.deterministic(obs)
        actions = self.encoder.decode(action, context, "safe_mappo" if self.net.safe else "mappo")
        self.cached = dict(actions); self.last_t = float(context.t)
        return Decision(actions, {"algorithm":"safe_mappo" if self.net.safe else "mappo", "cached_plan":False})


class SafeMAPPOPolicy(MAPPOPolicy):
    def __init__(self, cfg):
        # Keep separate config path while reusing the exact inference architecture.
        local = cfg.policy.setdefault("research", {}).setdefault("baselines", {})
        safe_options = dict(local.get("safe_mappo", {}))
        if "model_path" not in safe_options:
            raise ValueError("Safe MAPPO baseline requires research.baselines.safe_mappo.model_path")
        original = local.get("mappo")
        local["mappo"] = safe_options
        try:
            super().__init__(cfg)
        finally:
            if original is None:
                local.pop("mappo", None)
            else:
                local["mappo"] = original
        if not self.net.safe:
            raise ValueError("safe_mappo checkpoint was not trained with safe=True")

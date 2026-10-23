from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np

from ..config import load_config
from ..models import Decision
from .batch import _last_cycle_metrics, _write_table
from .mappo import MAPPOTrainConfig, _gae, _torch
from .provenance import runtime_provenance
from .risk_planning import RiskAwarePrimitiveFactory
from .rl_env import ResearchMARLEnv, ResearchObservationEncoder
from .runner import run_research_simulation
from .types import SolverDiagnostics


SELECTION_METRICS = (
    "research_missed_target_rate",
    "research_detection_delay_censored_p95_s",
    "research_total_loss_s",
    "research_max_loss_gap_s",
    "research_revisit_age_p95_s",
)


def _mappo_options(cfg, *, safe=False) -> dict:
    baselines = cfg.policy.get("research", {}).get("baselines", {})
    key = "safe_mappo" if safe else "mappo"
    options = dict(baselines.get(key, {}))
    fallback = dict(baselines.get("mappo", {}))
    merged = {**fallback, **options}
    return merged


def _capacity(cfg, *, safe=False) -> tuple[int, int, int]:
    options = _mappo_options(cfg, safe=safe)
    max_targets = int(options.get("max_targets", 8))
    top_search_cells = int(options.get("top_search_cells", 65))
    max_candidates = int(options.get("max_candidates", 512))
    if min(max_targets, top_search_cells, max_candidates) < 1:
        raise ValueError("candidate MAPPO capacities must be positive")
    return max_targets, top_search_cells, max_candidates


class CandidateActionView:
    """Deterministic padded view of the common physically executable primitives."""

    def __init__(self, factory: RiskAwarePrimitiveFactory, device_ids, max_candidates: int):
        self.factory = factory
        self.device_ids = tuple(device_ids)
        self.max_candidates = int(max_candidates)

    def generate(self, context):
        primitive_set = self.factory.generate(context)
        candidates = []
        mask = np.zeros((len(self.device_ids), self.max_candidates), dtype=bool)
        for agent, device_id in enumerate(self.device_ids):
            rows = tuple(primitive_set.by_device.get(device_id, ()))
            if len(rows) > self.max_candidates:
                raise RuntimeError(
                    f"candidate MAPPO received {len(rows)} primitives for {device_id}, "
                    f"exceeding frozen max_candidates={self.max_candidates}; refusing to truncate"
                )
            if not rows:
                raise RuntimeError(f"candidate MAPPO has no executable primitive for connected device {device_id}")
            candidates.append(rows)
            mask[agent, :len(rows)] = True
        return primitive_set, tuple(candidates), mask


class CandidateResearchMARLEnv(ResearchMARLEnv):
    """Paper task with discrete actions over the same RiskAwarePrimitiveFactory.

    Reward/cost, perception, event cadence and hidden-truth training supervision are
    inherited conceptually from ``ResearchMARLEnv``. Only the action interface is
    replaced: an agent selects one physically executable primitive instead of
    emitting an unconstrained absolute A/E/zoom command.
    """

    def __init__(self, cfg, seed=0, max_targets=8, top_search_cells=65,
                 max_candidates=512):
        super().__init__(cfg, seed=seed, max_targets=max_targets,
                         top_search_cells=top_search_cells)
        self.factory = RiskAwarePrimitiveFactory(self.cfg)
        self.action_view = CandidateActionView(
            self.factory, [d.id for d in self.cfg.active_devices], max_candidates)
        self.max_candidates = int(max_candidates)
        self._primitive_set = None
        self._candidates = None
        self._action_mask = None

    @property
    def action_dim(self):
        return self.max_candidates

    def _refresh_candidates(self):
        self._primitive_set, self._candidates, self._action_mask = self.action_view.generate(self._context)

    def reset(self, seed=None):
        obs, state = super().reset(seed=seed)
        self._refresh_candidates()
        return obs, state, self._action_mask.copy()

    def step(self, indices: np.ndarray):
        if self._context is None or self._candidates is None or self._action_mask is None:
            raise RuntimeError("reset() must be called before step()")
        indices = np.asarray(indices, dtype=int)
        if indices.shape != (self.n_agents,):
            raise ValueError(f"candidate MAPPO action must have shape {(self.n_agents,)}")
        selected = []
        commands = {}
        for agent, (device, index) in enumerate(zip(self.cfg.active_devices, indices)):
            if index < 0 or index >= self.max_candidates or not self._action_mask[agent, index]:
                raise ValueError(f"invalid masked candidate index {index} for {device.id}")
            primitive = self._candidates[agent][int(index)]
            selected.append(primitive)
            commands[device.id] = primitive.action(self._context.t, self.factory.ttl_s)

        reward_total = 0.0
        cost_total = 0.0
        frames = 0
        event_triggered = False
        for _ in range(self.frame_skip):
            self._world.advance(commands, self.dt)
            states = self._world.states()
            self._mission.step(self._world.t, self.dt, states)
            status = self._mission.last_perception.target_status
            active_count = len(status)
            discovered = [x for x in status if x.discovered]
            lost = sum(not bool(x.visible_devices) for x in discovered)
            undiscovered = active_count - len(discovered)
            new_discovered = max(
                0, self._mission.last_perception.discovered_active_count - self._previous_discovered)
            self._previous_discovered = self._mission.last_perception.discovered_active_count
            age_mean = float(np.mean(self._mission.last_search.ages_s))
            age_cap = float(self.cfg.policy.get("research", {}).get("search", {}).get("age_cap_s", 120.0))
            task_denominator = max(active_count, 1)
            lost_rate = lost / task_denominator
            undiscovered_rate = undiscovered / task_denominator
            reward_total += (
                self.discovery_bonus * new_discovered
                - self.loss_penalty * lost_rate
                - self.missed_active_penalty * undiscovered_rate
                - self.search_age_weight * age_mean / max(age_cap, 1e-9)
            )
            cost_total += (lost + undiscovered) / task_denominator
            frames += 1
            provisional = self._context_from(states, self._decision_step + 1)
            signature = self._event_signature(provisional)
            if self.event_replan and signature != self._last_event_signature:
                event_triggered = True
                self._context = provisional
                self._last_event_signature = signature
                break
            self._context = provisional
            self._last_event_signature = signature
            if self._world.t >= self.duration_s - 1e-12:
                break

        # The common primitive execution cost is a physically meaningful motion
        # regularizer and replaces the continuous-action difference used by the old
        # unconstrained learning interface.
        motion = float(np.mean([p.execution_cost for p in selected])) if selected else 0.0
        reward_total -= self.motion_weight * motion
        self._decision_step += 1
        obs = self.encoder.encode(self._context)
        done = self._world.t >= self.duration_s - 1e-12
        denominator = max(frames, 1)
        self._refresh_candidates()
        info = {
            "metrics": dict(self._mission.last_metrics),
            "time_s": self._world.t,
            "cost": float(cost_total / denominator),
            "frames_executed": frames,
            "event_triggered": bool(event_triggered),
            "reward_uses_privileged_truth": True,
            "selected_kinds": [p.kind for p in selected],
            "candidate_counts": [len(x) for x in self._candidates],
        }
        return (obs, obs.reshape(-1).copy(), self._action_mask.copy(),
                float(reward_total / denominator), float(cost_total / denominator), done, info)


class MultiScenarioCandidateEnv:
    """Cycle over frozen training scenario x environment-seed realizations."""

    def __init__(self, configs, network_seed=0, *, safe=False, episode_seeds=None):
        if not configs:
            raise ValueError("candidate MAPPO training requires scenarios")
        self.configs = [copy.deepcopy(cfg) for cfg in configs]
        self.network_seed = int(network_seed)
        self.safe = bool(safe)
        self.episode_seeds = tuple(int(x) for x in (episode_seeds or [network_seed]))
        self.episode_specs = [
            (cfg_index, env_seed)
            for env_seed in self.episode_seeds
            for cfg_index in range(len(self.configs))
        ]
        if not self.episode_specs:
            raise ValueError("candidate MAPPO training requires environment seeds")
        capacities = [_capacity(cfg, safe=self.safe) for cfg in self.configs]
        if len(set(capacities)) != 1:
            raise ValueError("all candidate MAPPO scenarios must share observation/action capacities")
        self.max_targets, self.top_search_cells, self.max_candidates = capacities[0]
        self.episode = 0
        self.episode_usage: dict[str, int] = {}
        self.env = self._make_env(*self.episode_specs[0])
        signature = (self.env.n_agents, self.env.obs_dim, self.env.action_dim)
        for cfg_index in range(1, len(self.configs)):
            probe = self._make_env(cfg_index, self.episode_seeds[0])
            if (probe.n_agents, probe.obs_dim, probe.action_dim) != signature:
                raise ValueError("candidate MAPPO scenario dimensions differ")

    def _make_env(self, cfg_index: int, env_seed: int):
        return CandidateResearchMARLEnv(
            self.configs[int(cfg_index)], seed=int(env_seed),
            max_targets=self.max_targets, top_search_cells=self.top_search_cells,
            max_candidates=self.max_candidates)

    @property
    def n_agents(self): return self.env.n_agents
    @property
    def obs_dim(self): return self.env.obs_dim
    @property
    def action_dim(self): return self.env.action_dim

    def reset(self):
        cfg_index, env_seed = self.episode_specs[self.episode % len(self.episode_specs)]
        self.env = self._make_env(cfg_index, env_seed)
        scenario_id = str(self.configs[cfg_index].policy.get("research", {}).get("scenario", {}).get("id", cfg_index))
        key = f"{scenario_id}|{int(env_seed)}"
        self.episode_usage[key] = self.episode_usage.get(key, 0) + 1
        self.episode += 1
        return self.env.reset(seed=env_seed)

    def step(self, action):
        return self.env.step(action)


class CandidateActorCritic:
    """Shared categorical actor with centralized critic and action masking."""

    def __init__(self, obs_dim, state_dim, max_candidates=512, hidden=192,
                 safe=False, device="cpu"):
        torch, nn = _torch()

        class Net(nn.Module):
            def __init__(self):
                super().__init__()
                self.actor = nn.Sequential(
                    nn.Linear(obs_dim, hidden), nn.Tanh(),
                    nn.Linear(hidden, hidden), nn.Tanh(),
                    nn.Linear(hidden, max_candidates),
                )
                self.critic = nn.Sequential(
                    nn.Linear(state_dim, hidden), nn.Tanh(),
                    nn.Linear(hidden, hidden), nn.Tanh(), nn.Linear(hidden, 1),
                )
                self.cost_critic = (nn.Sequential(
                    nn.Linear(state_dim, hidden), nn.Tanh(),
                    nn.Linear(hidden, hidden), nn.Tanh(), nn.Linear(hidden, 1),
                ) if safe else None)
                self._initialize()

            def _initialize(self):
                for module in self.modules():
                    if isinstance(module, nn.Linear):
                        nn.init.orthogonal_(module.weight, gain=math.sqrt(2.0))
                        nn.init.zeros_(module.bias)
                nn.init.orthogonal_(self.actor[-1].weight, gain=0.01)
                nn.init.orthogonal_(self.critic[-1].weight, gain=1.0)
                if self.cost_critic is not None:
                    nn.init.orthogonal_(self.cost_critic[-1].weight, gain=1.0)

            def distribution(self, obs, mask):
                logits = self.actor(obs)
                masked = logits.masked_fill(~mask, torch.finfo(logits.dtype).min)
                return torch.distributions.Categorical(logits=masked)

            def value(self, state):
                return self.critic(state).squeeze(-1)

            def cost_value(self, state):
                if self.cost_critic is None:
                    return torch.zeros(state.shape[:-1], device=state.device)
                return self.cost_critic(state).squeeze(-1)

        self.torch = torch
        self.device = torch.device(device)
        self.safe = bool(safe)
        self.max_candidates = int(max_candidates)
        self.model = Net().to(self.device)

    def state_dict(self): return self.model.state_dict()
    def load_state_dict(self, state): return self.model.load_state_dict(state)

    def sample(self, obs, state, mask):
        torch = self.torch
        obs_t = torch.as_tensor(obs, dtype=torch.float32, device=self.device)
        state_t = torch.as_tensor(state, dtype=torch.float32, device=self.device)
        mask_t = torch.as_tensor(mask, dtype=torch.bool, device=self.device)
        dist = self.model.distribution(obs_t, mask_t)
        action = dist.sample()
        logp = dist.log_prob(action).sum()
        return (action.detach().cpu().numpy(), float(logp.detach().cpu()),
                float(self.model.value(state_t).detach().cpu()),
                float(self.model.cost_value(state_t).detach().cpu()))

    def deterministic(self, obs, mask):
        torch = self.torch
        with torch.no_grad():
            obs_t = torch.as_tensor(obs, dtype=torch.float32, device=self.device)
            mask_t = torch.as_tensor(mask, dtype=torch.bool, device=self.device)
            logits = self.model.actor(obs_t).masked_fill(~mask_t, torch.finfo(torch.float32).min)
            return torch.argmax(logits, dim=-1).cpu().numpy()


class CandidateMAPPOPolicy:
    """Inference wrapper for the strong shared-candidate MAPPO baseline."""

    def __init__(self, cfg, *, safe=False):
        self.cfg = cfg
        self.safe = bool(safe)
        options = _mappo_options(cfg, safe=safe)
        path = options.get("model_path")
        if not path:
            raise ValueError("candidate MAPPO requires a frozen model_path")
        max_targets, top_search_cells, max_candidates = _capacity(cfg, safe=safe)
        self.encoder = ResearchObservationEncoder(cfg, max_targets, top_search_cells)
        self.factory = RiskAwarePrimitiveFactory(cfg)
        self.action_view = CandidateActionView(
            self.factory, [d.id for d in cfg.active_devices], max_candidates)
        self.max_candidates = max_candidates
        torch, _ = _torch()
        checkpoint = torch.load(path, map_location=str(options.get("device", "cpu")), weights_only=False)
        if checkpoint.get("implementation") != "candidate_categorical_v1":
            raise ValueError("checkpoint is not a candidate-action MAPPO model")
        expected = (self.encoder.obs_dim, len(cfg.active_devices) * self.encoder.obs_dim, max_candidates)
        actual = (int(checkpoint["obs_dim"]), int(checkpoint["state_dim"]), int(checkpoint["max_candidates"]))
        if actual != expected:
            raise ValueError(f"candidate MAPPO checkpoint dimensions {actual} != {expected}")
        self.net = CandidateActorCritic(
            expected[0], expected[1], max_candidates=max_candidates,
            safe=safe, device=str(options.get("device", "cpu")))
        self.net.load_state_dict(checkpoint["state_dict"])

    def reset(self):
        pass

    def decide(self, context) -> Decision:
        if context.research.get("mission") != "search_monitor":
            raise ValueError("candidate MAPPO requires search_monitor mission")
        obs = self.encoder.encode(context)
        primitive_set, candidates, mask = self.action_view.generate(context)
        indices = self.net.deterministic(obs, mask)
        actions = {}
        selected_kinds = []
        for agent, (device, index) in enumerate(zip(self.cfg.active_devices, indices)):
            primitive = candidates[agent][int(index)]
            actions[device.id] = primitive.action(context.t, self.factory.ttl_s)
            selected_kinds.append(primitive.kind)
        diagnostics = {
            "algorithm": "safe_mappo" if self.safe else "mappo",
            "implementation": "candidate_categorical_v1",
            "candidate_count": len(primitive_set.flat),
            "candidate_counts_by_device": [len(x) for x in candidates],
            "selected_kinds": selected_kinds,
        }
        return Decision(actions, diagnostics)


class CandidateSafeMAPPOPolicy(CandidateMAPPOPolicy):
    def __init__(self, cfg):
        super().__init__(cfg, safe=True)


def _save_checkpoint(net, path: Path, *, safe, seed, settings, history, env,
                     update, training_scenarios, training_env_seeds):
    torch, _ = _torch()
    path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = {
        "implementation": "candidate_categorical_v1",
        "state_dict": net.state_dict(), "safe": bool(safe), "seed": int(seed),
        "obs_dim": env.obs_dim, "state_dim": env.n_agents * env.obs_dim,
        "max_candidates": env.max_candidates, "n_agents": env.n_agents,
        "max_targets": env.max_targets, "top_search_cells": env.top_search_cells,
        "train_config": settings.__dict__, "history": list(history),
        "training_update": int(update),
        "training_scenarios": list(training_scenarios),
        "training_env_seeds": [int(x) for x in training_env_seeds],
        "episodes_started": int(env.episode),
        "episode_usage": dict(env.episode_usage),
    }
    torch.save(checkpoint, path)
    metadata = {k: v for k, v in checkpoint.items() if k != "state_dict"}
    metadata["runtime_provenance"] = runtime_provenance()
    path.with_suffix(path.suffix + ".json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def train_candidate_mappo(train_configs: Iterable[str | Path], output_dir: str | Path,
                          *, safe=False, seed=0, training_env_seeds=None,
                          settings: MAPPOTrainConfig | None=None, device="cpu",
                          checkpoint_every=25):
    torch, _ = _torch()
    cfg_paths = [Path(p).resolve() for p in train_configs]
    cfgs = [load_config(p) for p in cfg_paths]
    settings = settings or MAPPOTrainConfig()
    env_seeds = tuple(int(x) for x in (training_env_seeds or [seed]))
    np.random.seed(int(seed)); torch.manual_seed(int(seed))
    env = MultiScenarioCandidateEnv(cfgs, network_seed=seed, safe=safe, episode_seeds=env_seeds)
    obs, state, mask = env.reset()
    net = CandidateActorCritic(
        env.obs_dim, len(state), max_candidates=env.max_candidates,
        safe=safe, device=device)
    optimizer = torch.optim.Adam(net.model.parameters(), lr=settings.lr)
    lagrange = 0.0
    history = []
    checkpoints = []
    for update in range(settings.updates):
        O=[]; S=[]; M=[]; A=[]; LP=[]; V=[]; CV=[]; R=[]; C=[]; D=[]
        for _ in range(settings.rollout_steps):
            action, logp, value, cost_value = net.sample(obs, state, mask)
            next_obs, next_state, next_mask, reward, cost, done, info = env.step(action)
            O.append(obs.copy()); S.append(state.copy()); M.append(mask.copy()); A.append(action.copy())
            LP.append(logp); V.append(value); CV.append(cost_value); R.append(reward); C.append(cost); D.append(done)
            obs, state, mask = next_obs, next_state, next_mask
            if done:
                obs, state, mask = env.reset()
        with torch.no_grad():
            state_t = torch.as_tensor(state, dtype=torch.float32, device=net.device)
            bootstrap = float(net.model.value(state_t).cpu())
            cost_bootstrap = float(net.model.cost_value(state_t).cpu()) if safe else 0.0
        adv, returns = _gae(np.asarray(R,np.float32), np.asarray(V,np.float32), np.asarray(D,bool),
                            bootstrap, settings.gamma, settings.gae_lambda)
        cadv, creturns = _gae(np.asarray(C,np.float32), np.asarray(CV,np.float32), np.asarray(D,bool),
                              cost_bootstrap, settings.gamma, settings.gae_lambda)
        adv = (adv-adv.mean())/(adv.std()+1e-8)
        if safe:
            cadv = (cadv-cadv.mean())/(cadv.std()+1e-8)
        combined = adv-float(lagrange)*cadv if safe else adv
        obs_batch=torch.as_tensor(np.asarray(O),dtype=torch.float32,device=net.device)
        state_batch=torch.as_tensor(np.asarray(S),dtype=torch.float32,device=net.device)
        mask_batch=torch.as_tensor(np.asarray(M),dtype=torch.bool,device=net.device)
        action_batch=torch.as_tensor(np.asarray(A),dtype=torch.long,device=net.device)
        old_logp=torch.as_tensor(np.asarray(LP),dtype=torch.float32,device=net.device)
        adv_batch=torch.as_tensor(combined,dtype=torch.float32,device=net.device)
        return_batch=torch.as_tensor(returns,dtype=torch.float32,device=net.device)
        cost_return_batch=torch.as_tensor(creturns,dtype=torch.float32,device=net.device)
        indices=np.arange(settings.rollout_steps); losses=[]
        for _ in range(settings.epochs):
            np.random.shuffle(indices)
            for start in range(0,len(indices),settings.minibatch):
                idx=indices[start:start+settings.minibatch]
                ob=obs_batch[idx]; st=state_batch[idx]; mk=mask_batch[idx]; act=action_batch[idx]
                dist=net.model.distribution(ob,mk)
                logp=dist.log_prob(act).sum(dim=-1)
                ratio=torch.exp(logp-old_logp[idx]); a=adv_batch[idx]
                clipped=torch.clamp(ratio,1-settings.clip_ratio,1+settings.clip_ratio)
                policy_loss=-torch.minimum(ratio*a,clipped*a).mean()
                value_loss=(net.model.value(st)-return_batch[idx]).pow(2).mean()
                cost_value_loss=((net.model.cost_value(st)-cost_return_batch[idx]).pow(2).mean()
                                 if safe else torch.tensor(0.0,device=net.device))
                entropy=dist.entropy().sum(dim=-1).mean()
                loss=policy_loss+settings.value_coef*(value_loss+cost_value_loss)-settings.entropy_coef*entropy
                optimizer.zero_grad(); loss.backward()
                torch.nn.utils.clip_grad_norm_(net.model.parameters(),settings.max_grad_norm)
                optimizer.step(); losses.append(float(loss.detach().cpu()))
        mean_cost=float(np.mean(C))
        if safe:
            lagrange=max(0.0,lagrange+settings.lagrange_lr*(mean_cost-settings.cost_limit))
        history.append({"update":update+1,"reward_mean":float(np.mean(R)),"cost_mean":mean_cost,
                        "loss_mean":float(np.mean(losses)) if losses else 0.0,"lagrange":float(lagrange),
                        "episodes_started":int(env.episode)})
        if checkpoint_every and ((update+1)%int(checkpoint_every)==0 or update+1==settings.updates):
            name=("safe_candidate_mappo" if safe else "candidate_mappo")+f"_seed{int(seed)}_u{update+1:04d}.pt"
            checkpoints.append(str(_save_checkpoint(
                net,Path(output_dir)/name,safe=safe,seed=seed,settings=settings,history=history,
                env=env,update=update+1,training_scenarios=[str(p) for p in cfg_paths],
                training_env_seeds=env_seeds)))
    Path(output_dir).mkdir(parents=True,exist_ok=True)
    index = {
        "implementation": "candidate_categorical_v1",
        "safe":bool(safe),"seed":int(seed),"training_scenarios":[str(p) for p in cfg_paths],
        "training_env_seeds":[int(x) for x in env_seeds],"max_targets":env.max_targets,
        "top_search_cells":env.top_search_cells,"max_candidates":env.max_candidates,
        "episodes_started":int(env.episode),"episode_usage":dict(env.episode_usage),
        "checkpoints":checkpoints,"train_config":settings.__dict__,
    }
    (Path(output_dir)/f"{'safe_' if safe else ''}candidate_mappo_seed{seed}_training_index.json").write_text(
        json.dumps(index,ensure_ascii=False,indent=2),encoding="utf-8")
    return checkpoints


def _score(metrics):
    values=[]
    for key in SELECTION_METRICS:
        value=metrics.get(key)
        values.append(float(value) if isinstance(value,(int,float)) and np.isfinite(value) else float("inf"))
    return tuple(values)


def select_candidate_checkpoint(checkpoints, validation_configs, seeds, output_dir,
                                *, safe=False, device="cpu"):
    rows=[]; aggregate=[]
    for checkpoint in checkpoints:
        per=[]
        for config_path in validation_configs:
            for seed in seeds:
                cfg=load_config(config_path)
                key="safe_mappo" if safe else "mappo"
                baseline=cfg.policy.setdefault("research",{}).setdefault("baselines",{})
                baseline.setdefault(key,{})["model_path"]=str(Path(checkpoint).resolve())
                baseline[key]["device"]=device
                run_dir=run_research_simulation(cfg,key,Path(output_dir)/"validation_runs",int(seed))
                metrics=_last_cycle_metrics(Path(run_dir)); per.append(metrics)
                rows.append({"checkpoint":str(checkpoint),"config":str(config_path),"seed":int(seed),**metrics})
        summary={"checkpoint":str(checkpoint),"n":len(per)}
        for metric in SELECTION_METRICS:
            vals=[float(x[metric]) for x in per if isinstance(x.get(metric),(int,float)) and np.isfinite(x[metric])]
            summary[metric]=float(np.mean(vals)) if vals else None
        aggregate.append(summary)
    if not aggregate:
        raise ValueError("no candidate MAPPO checkpoints to select")
    chosen=min(aggregate,key=_score)
    out=Path(output_dir); out.mkdir(parents=True,exist_ok=True)
    _write_table(out/"validation_checkpoint_runs.csv",rows)
    _write_table(out/"validation_checkpoint_summary.csv",aggregate)
    document={
        "implementation":"candidate_categorical_v1",
        "selection_rule":(
            "lexicographic validation means: missed-target rate, censored detection-delay P95, "
            "post-discovery total loss, maximum loss gap, revisit-age P95"),
        "selection_metrics":list(SELECTION_METRICS),"safe":bool(safe),
        "validation_configs":[str(Path(x).resolve()) for x in validation_configs],
        "validation_seeds":[int(x) for x in seeds],"selected":chosen,
    }
    (out/"selected_checkpoint.json").write_text(
        json.dumps(document,ensure_ascii=False,indent=2),encoding="utf-8")
    return chosen


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description="Candidate-action MAPPO train/validation protocol")
    sub=parser.add_subparsers(dest="command",required=True)
    p=sub.add_parser("train"); p.add_argument("configs",nargs="+"); p.add_argument("--output",required=True)
    p.add_argument("--seed",type=int,default=0); p.add_argument("--env-seeds",nargs="+",type=int)
    p.add_argument("--safe",action="store_true"); p.add_argument("--updates",type=int,default=300)
    p.add_argument("--rollout-steps",type=int,default=256); p.add_argument("--checkpoint-every",type=int,default=25)
    p.add_argument("--device",default="cpu")
    p=sub.add_parser("select"); p.add_argument("checkpoints",nargs="+"); p.add_argument("--configs",nargs="+",required=True)
    p.add_argument("--seeds",nargs="+",type=int,required=True); p.add_argument("--output",required=True)
    p.add_argument("--safe",action="store_true"); p.add_argument("--device",default="cpu")
    args=parser.parse_args(argv)
    if args.command=="train":
        settings=MAPPOTrainConfig(updates=args.updates,rollout_steps=args.rollout_steps)
        print("\n".join(train_candidate_mappo(
            args.configs,args.output,safe=args.safe,seed=args.seed,training_env_seeds=args.env_seeds,
            settings=settings,device=args.device,checkpoint_every=args.checkpoint_every)))
    else:
        print(json.dumps(select_candidate_checkpoint(
            args.checkpoints,args.configs,args.seeds,args.output,safe=args.safe,device=args.device),
            ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()

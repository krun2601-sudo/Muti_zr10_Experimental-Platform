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
from .candidate_mappo import (
    SELECTION_METRICS,
    CandidateActionView,
    CandidateResearchMARLEnv,
    MultiScenarioCandidateEnv,
    _capacity,
    _mappo_options,
)
from .mappo import MAPPOTrainConfig, _gae, _torch
from .planning import angle_delta_deg
from .provenance import runtime_provenance
from .risk_planning import RiskAwarePrimitiveFactory
from .rl_env import ResearchObservationEncoder
from .runner import run_research_simulation


IMPLEMENTATION = "candidate_feature_v2"
_KIND_ORDER = ("hold", "search", "track", "shared_track")


def _scale_unit(value: float, limits) -> float:
    lo, hi = map(float, limits)
    if hi <= lo:
        return 0.0
    return float(np.clip(2.0 * (float(value) - lo) / (hi - lo) - 1.0, -1.0, 1.0))


class CandidateFeatureEncoder:
    """Permutation-compatible public features for each executable primitive.

    Every feature is derived from the same policy-visible belief/search state and
    the common RiskAwarePrimitiveFactory output. No hidden target truth enters the
    actor input. Padding rows are zero and excluded by the action mask.
    """

    def __init__(self, cfg, max_targets: int, max_candidates: int):
        self.cfg = cfg
        self.devices = tuple(cfg.active_devices)
        self.max_targets = int(max_targets)
        self.max_candidates = int(max_candidates)
        self.device_by_id = {d.id: d for d in self.devices}
        self.feature_dim = 13 + 2 * self.max_targets

    def encode(self, context, primitive_set, candidates) -> np.ndarray:
        features = np.zeros(
            (len(self.devices), self.max_candidates, self.feature_dim), dtype=np.float32)
        target_index = {tid: i for i, tid in enumerate(primitive_set.target_ids[:self.max_targets])}
        search_ages = np.asarray(primitive_set.search_ages_s, dtype=float)
        age_den = max(float(np.sum(np.maximum(search_ages, 0.0))), 1e-9)
        horizon_s = max(float(primitive_set.horizon_steps * primitive_set.slot_s), 1e-9)
        horizon_steps = max(int(primitive_set.horizon_steps), 1)
        search_n = max(len(primitive_set.search_positions), 1)

        for agent, (device, rows) in enumerate(zip(self.devices, candidates)):
            state = context.devices[device.id]
            for index, primitive in enumerate(rows):
                if index >= self.max_candidates:
                    raise RuntimeError("candidate feature encoder received more rows than max_candidates")
                row = []
                row.extend(1.0 if primitive.kind == kind else 0.0 for kind in _KIND_ORDER)
                row.extend([
                    float(np.clip(angle_delta_deg(primitive.yaw_deg, state.yaw_deg) / 180.0, -1.0, 1.0)),
                    float(np.clip((primitive.pitch_deg - state.pitch_deg) / 90.0, -1.0, 1.0)),
                    _scale_unit(primitive.zoom, device.zoom_limits),
                    float(np.clip(primitive.transition_s / horizon_s, 0.0, 2.0)),
                    float(np.clip(primitive.ready_slot / horizon_steps, 0.0, 2.0)),
                    float(np.clip(primitive.execution_cost / horizon_s, 0.0, 2.0)),
                    float(np.clip(len(primitive.target_ids) / max(self.max_targets, 1), 0.0, 1.0)),
                ])

                intended = np.zeros(self.max_targets, dtype=np.float32)
                for target_id in primitive.target_ids:
                    j = target_index.get(target_id)
                    if j is not None:
                        intended[j] = 1.0
                row.extend(intended.tolist())

                vis = np.zeros(self.max_targets, dtype=np.float32)
                visibility = np.asarray(primitive.visibility, dtype=bool)
                for j in range(min(self.max_targets, visibility.shape[0] if visibility.ndim == 2 else 0)):
                    vis[j] = float(np.mean(visibility[j]))
                row.extend(vis.tolist())

                coverage = np.asarray(primitive.search_coverage, dtype=bool)
                if coverage.ndim == 2 and coverage.shape[0] == len(search_ages) and len(search_ages):
                    covered = np.any(coverage, axis=1)
                    coverage_fraction = float(np.count_nonzero(covered) / search_n)
                    age_gain = float(np.sum(np.maximum(search_ages[covered], 0.0)) / age_den)
                else:
                    coverage_fraction = 0.0
                    age_gain = 0.0
                row.extend([coverage_fraction, age_gain])

                array = np.asarray(row, dtype=np.float32)
                if array.shape != (self.feature_dim,):
                    raise RuntimeError(
                        f"candidate feature shape mismatch {array.shape} != {(self.feature_dim,)}")
                features[agent, index] = array
        return features


class FeatureCandidateResearchMARLEnv(CandidateResearchMARLEnv):
    """Candidate-action environment augmented only with policy-visible primitive features."""

    def __init__(self, cfg, seed=0, max_targets=8, top_search_cells=65, max_candidates=512):
        self.feature_encoder = CandidateFeatureEncoder(cfg, max_targets, max_candidates)
        self._candidate_features = None
        super().__init__(cfg, seed=seed, max_targets=max_targets,
                         top_search_cells=top_search_cells, max_candidates=max_candidates)

    @property
    def candidate_feature_dim(self):
        return self.feature_encoder.feature_dim

    def _refresh_candidates(self):
        super()._refresh_candidates()
        self._candidate_features = self.feature_encoder.encode(
            self._context, self._primitive_set, self._candidates)

    def reset(self, seed=None):
        obs, state, mask = super().reset(seed=seed)
        return obs, state, mask, self._candidate_features.copy()

    def step(self, indices: np.ndarray):
        obs, state, mask, reward, cost, done, info = super().step(indices)
        return (obs, state, mask, self._candidate_features.copy(),
                reward, cost, done, info)


class MultiScenarioFeatureEnv(MultiScenarioCandidateEnv):
    def _make_env(self, cfg_index: int, env_seed: int):
        return FeatureCandidateResearchMARLEnv(
            self.configs[int(cfg_index)], seed=int(env_seed),
            max_targets=self.max_targets, top_search_cells=self.top_search_cells,
            max_candidates=self.max_candidates)

    @property
    def candidate_feature_dim(self):
        return self.env.candidate_feature_dim


class FeatureCandidateActorCritic:
    """Shared MAPPO actor scoring candidates from observation + primitive features.

    The same scoring function is applied independently to every candidate. Hence
    permuting candidate rows (and the mask) permutes logits in the same way instead
    of changing the meaning of a learned output neuron.
    """

    def __init__(self, obs_dim, state_dim, candidate_feature_dim,
                 max_candidates=512, hidden=192, safe=False, device="cpu"):
        torch, nn = _torch()

        class Net(nn.Module):
            def __init__(self):
                super().__init__()
                self.obs_encoder = nn.Sequential(
                    nn.Linear(obs_dim, hidden), nn.Tanh(),
                    nn.Linear(hidden, hidden), nn.Tanh(),
                )
                self.candidate_encoder = nn.Sequential(
                    nn.Linear(candidate_feature_dim, hidden), nn.Tanh(),
                    nn.Linear(hidden, hidden), nn.Tanh(),
                )
                self.score = nn.Linear(hidden, 1)
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
                nn.init.orthogonal_(self.score.weight, gain=0.01)
                nn.init.orthogonal_(self.critic[-1].weight, gain=1.0)
                if self.cost_critic is not None:
                    nn.init.orthogonal_(self.cost_critic[-1].weight, gain=1.0)

            def logits(self, obs, candidate_features):
                obs_embedding = self.obs_encoder(obs).unsqueeze(-2)
                candidate_embedding = self.candidate_encoder(candidate_features)
                return self.score(torch.tanh(obs_embedding + candidate_embedding)).squeeze(-1)

            def distribution(self, obs, candidate_features, mask):
                logits = self.logits(obs, candidate_features)
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
        self.candidate_feature_dim = int(candidate_feature_dim)
        self.model = Net().to(self.device)

    def state_dict(self):
        return self.model.state_dict()

    def load_state_dict(self, state):
        return self.model.load_state_dict(state)

    def sample(self, obs, state, mask, candidate_features):
        torch = self.torch
        obs_t = torch.as_tensor(obs, dtype=torch.float32, device=self.device)
        state_t = torch.as_tensor(state, dtype=torch.float32, device=self.device)
        mask_t = torch.as_tensor(mask, dtype=torch.bool, device=self.device)
        feat_t = torch.as_tensor(candidate_features, dtype=torch.float32, device=self.device)
        dist = self.model.distribution(obs_t, feat_t, mask_t)
        action = dist.sample()
        logp = dist.log_prob(action).sum()
        return (action.detach().cpu().numpy(), float(logp.detach().cpu()),
                float(self.model.value(state_t).detach().cpu()),
                float(self.model.cost_value(state_t).detach().cpu()))

    def deterministic(self, obs, mask, candidate_features):
        torch = self.torch
        with torch.no_grad():
            obs_t = torch.as_tensor(obs, dtype=torch.float32, device=self.device)
            mask_t = torch.as_tensor(mask, dtype=torch.bool, device=self.device)
            feat_t = torch.as_tensor(candidate_features, dtype=torch.float32, device=self.device)
            logits = self.model.logits(obs_t, feat_t).masked_fill(
                ~mask_t, torch.finfo(torch.float32).min)
            return torch.argmax(logits, dim=-1).cpu().numpy()


class FeatureCandidateMAPPOPolicy:
    """Inference wrapper for the feature-scored candidate MAPPO baseline."""

    def __init__(self, cfg, *, safe=False):
        self.cfg = cfg
        self.safe = bool(safe)
        options = _mappo_options(cfg, safe=safe)
        path = options.get("model_path")
        if not path:
            raise ValueError("feature candidate MAPPO requires a frozen model_path")
        max_targets, top_search_cells, max_candidates = _capacity(cfg, safe=safe)
        self.encoder = ResearchObservationEncoder(cfg, max_targets, top_search_cells)
        self.factory = RiskAwarePrimitiveFactory(cfg)
        self.action_view = CandidateActionView(
            self.factory, [d.id for d in cfg.active_devices], max_candidates)
        self.feature_encoder = CandidateFeatureEncoder(cfg, max_targets, max_candidates)
        self.max_candidates = max_candidates
        torch, _ = _torch()
        checkpoint = torch.load(
            path, map_location=str(options.get("device", "cpu")), weights_only=False)
        if checkpoint.get("implementation") != IMPLEMENTATION:
            raise ValueError("checkpoint is not a feature-scored candidate MAPPO model")
        if bool(checkpoint.get("safe", False)) != self.safe:
            raise ValueError("checkpoint safe flag does not match requested MAPPO method")
        expected = (
            self.encoder.obs_dim,
            len(cfg.active_devices) * self.encoder.obs_dim,
            max_candidates,
            self.feature_encoder.feature_dim,
        )
        actual = (
            int(checkpoint["obs_dim"]), int(checkpoint["state_dim"]),
            int(checkpoint["max_candidates"]), int(checkpoint["candidate_feature_dim"]),
        )
        if actual != expected:
            raise ValueError(f"feature MAPPO checkpoint dimensions {actual} != {expected}")
        self.net = FeatureCandidateActorCritic(
            expected[0], expected[1], expected[3], max_candidates=max_candidates,
            safe=safe, device=str(options.get("device", "cpu")))
        self.net.load_state_dict(checkpoint["state_dict"])

    def reset(self):
        pass

    def decide(self, context) -> Decision:
        if context.research.get("mission") != "search_monitor":
            raise ValueError("feature candidate MAPPO requires search_monitor mission")
        obs = self.encoder.encode(context)
        primitive_set, candidates, mask = self.action_view.generate(context)
        features = self.feature_encoder.encode(context, primitive_set, candidates)
        indices = self.net.deterministic(obs, mask, features)
        actions = {}
        selected_kinds = []
        selected_indices = []
        for agent, (device, index) in enumerate(zip(self.cfg.active_devices, indices)):
            primitive = candidates[agent][int(index)]
            actions[device.id] = primitive.action(context.t, self.factory.ttl_s)
            selected_kinds.append(primitive.kind)
            selected_indices.append(int(index))
        diagnostics = {
            "algorithm": "safe_mappo" if self.safe else "mappo",
            "implementation": IMPLEMENTATION,
            "candidate_count": len(primitive_set.flat),
            "candidate_counts_by_device": [len(x) for x in candidates],
            "selected_kinds": selected_kinds,
            "selected_indices": selected_indices,
        }
        return Decision(actions, diagnostics)


class FeatureCandidateSafeMAPPOPolicy(FeatureCandidateMAPPOPolicy):
    def __init__(self, cfg):
        super().__init__(cfg, safe=True)


def _save_checkpoint(net, path: Path, *, safe, seed, settings, history, env,
                     update, training_scenarios, training_env_seeds):
    torch, _ = _torch()
    path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = {
        "implementation": IMPLEMENTATION,
        "state_dict": net.state_dict(),
        "safe": bool(safe),
        "seed": int(seed),
        "obs_dim": env.obs_dim,
        "state_dim": env.n_agents * env.obs_dim,
        "max_candidates": env.max_candidates,
        "candidate_feature_dim": env.candidate_feature_dim,
        "n_agents": env.n_agents,
        "max_targets": env.max_targets,
        "top_search_cells": env.top_search_cells,
        "train_config": settings.__dict__,
        "history": list(history),
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


def train_feature_candidate_mappo(train_configs: Iterable[str | Path], output_dir: str | Path,
                                  *, safe=False, seed=0, training_env_seeds=None,
                                  settings: MAPPOTrainConfig | None=None, device="cpu",
                                  checkpoint_every=25):
    torch, _ = _torch()
    cfg_paths = [Path(p).resolve() for p in train_configs]
    cfgs = [load_config(p) for p in cfg_paths]
    settings = settings or MAPPOTrainConfig()
    env_seeds = tuple(int(x) for x in (training_env_seeds or [seed]))
    np.random.seed(int(seed))
    torch.manual_seed(int(seed))
    env = MultiScenarioFeatureEnv(
        cfgs, network_seed=seed, safe=safe, episode_seeds=env_seeds)
    obs, state, mask, features = env.reset()
    net = FeatureCandidateActorCritic(
        env.obs_dim, len(state), env.candidate_feature_dim,
        max_candidates=env.max_candidates, safe=safe, device=device)
    optimizer = torch.optim.Adam(net.model.parameters(), lr=settings.lr)
    lagrange = 0.0
    history = []
    checkpoints = []
    for update in range(settings.updates):
        O=[]; S=[]; M=[]; F=[]; A=[]; LP=[]; V=[]; CV=[]; R=[]; C=[]; D=[]
        kind_counts = {kind: 0 for kind in _KIND_ORDER}
        for _ in range(settings.rollout_steps):
            action, logp, value, cost_value = net.sample(obs, state, mask, features)
            next_obs, next_state, next_mask, next_features, reward, cost, done, info = env.step(action)
            O.append(obs.copy()); S.append(state.copy()); M.append(mask.copy()); F.append(features.copy())
            A.append(action.copy()); LP.append(logp); V.append(value); CV.append(cost_value)
            R.append(reward); C.append(cost); D.append(done)
            for kind in info.get("selected_kinds", []):
                if kind in kind_counts:
                    kind_counts[kind] += 1
            obs, state, mask, features = next_obs, next_state, next_mask, next_features
            if done:
                obs, state, mask, features = env.reset()
        with torch.no_grad():
            state_t = torch.as_tensor(state, dtype=torch.float32, device=net.device)
            bootstrap = float(net.model.value(state_t).cpu())
            cost_bootstrap = float(net.model.cost_value(state_t).cpu()) if safe else 0.0
        adv, returns = _gae(
            np.asarray(R, np.float32), np.asarray(V, np.float32), np.asarray(D, bool),
            bootstrap, settings.gamma, settings.gae_lambda)
        cadv, creturns = _gae(
            np.asarray(C, np.float32), np.asarray(CV, np.float32), np.asarray(D, bool),
            cost_bootstrap, settings.gamma, settings.gae_lambda)
        adv = (adv - adv.mean()) / (adv.std() + 1e-8)
        if safe:
            cadv = (cadv - cadv.mean()) / (cadv.std() + 1e-8)
        combined = adv - float(lagrange) * cadv if safe else adv

        obs_batch = torch.as_tensor(np.asarray(O), dtype=torch.float32, device=net.device)
        state_batch = torch.as_tensor(np.asarray(S), dtype=torch.float32, device=net.device)
        mask_batch = torch.as_tensor(np.asarray(M), dtype=torch.bool, device=net.device)
        feat_batch = torch.as_tensor(np.asarray(F), dtype=torch.float32, device=net.device)
        action_batch = torch.as_tensor(np.asarray(A), dtype=torch.long, device=net.device)
        old_logp = torch.as_tensor(np.asarray(LP), dtype=torch.float32, device=net.device)
        adv_batch = torch.as_tensor(combined, dtype=torch.float32, device=net.device)
        return_batch = torch.as_tensor(returns, dtype=torch.float32, device=net.device)
        cost_return_batch = torch.as_tensor(creturns, dtype=torch.float32, device=net.device)
        indices = np.arange(settings.rollout_steps)
        losses = []
        for _ in range(settings.epochs):
            np.random.shuffle(indices)
            for start in range(0, len(indices), settings.minibatch):
                idx = indices[start:start + settings.minibatch]
                ob=obs_batch[idx]; st=state_batch[idx]; mk=mask_batch[idx]
                ft=feat_batch[idx]; act=action_batch[idx]
                dist = net.model.distribution(ob, ft, mk)
                logp = dist.log_prob(act).sum(dim=-1)
                ratio = torch.exp(logp - old_logp[idx])
                a = adv_batch[idx]
                clipped = torch.clamp(ratio, 1-settings.clip_ratio, 1+settings.clip_ratio)
                policy_loss = -torch.minimum(ratio*a, clipped*a).mean()
                value_loss = (net.model.value(st)-return_batch[idx]).pow(2).mean()
                cost_value_loss = (
                    (net.model.cost_value(st)-cost_return_batch[idx]).pow(2).mean()
                    if safe else torch.tensor(0.0, device=net.device))
                entropy = dist.entropy().sum(dim=-1).mean()
                loss = (policy_loss + settings.value_coef*(value_loss+cost_value_loss)
                        - settings.entropy_coef*entropy)
                optimizer.zero_grad(); loss.backward()
                torch.nn.utils.clip_grad_norm_(net.model.parameters(), settings.max_grad_norm)
                optimizer.step(); losses.append(float(loss.detach().cpu()))
        mean_cost = float(np.mean(C))
        if safe:
            lagrange = max(0.0, lagrange + settings.lagrange_lr*(mean_cost-settings.cost_limit))
        total_actions = max(sum(kind_counts.values()), 1)
        history.append({
            "update": update+1,
            "reward_mean": float(np.mean(R)),
            "cost_mean": mean_cost,
            "loss_mean": float(np.mean(losses)) if losses else 0.0,
            "lagrange": float(lagrange),
            "episodes_started": int(env.episode),
            "action_kind_fraction": {
                key: float(value / total_actions) for key, value in kind_counts.items()
            },
        })
        if checkpoint_every and ((update+1) % int(checkpoint_every) == 0 or update+1 == settings.updates):
            stem = "safe_feature_mappo" if safe else "feature_mappo"
            name = f"{stem}_seed{int(seed)}_u{update+1:04d}.pt"
            checkpoints.append(str(_save_checkpoint(
                net, Path(output_dir)/name, safe=safe, seed=seed, settings=settings,
                history=history, env=env, update=update+1,
                training_scenarios=[str(p) for p in cfg_paths],
                training_env_seeds=env_seeds)))

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    index = {
        "implementation": IMPLEMENTATION,
        "safe": bool(safe),
        "seed": int(seed),
        "training_scenarios": [str(p) for p in cfg_paths],
        "training_env_seeds": [int(x) for x in env_seeds],
        "max_targets": env.max_targets,
        "top_search_cells": env.top_search_cells,
        "max_candidates": env.max_candidates,
        "candidate_feature_dim": env.candidate_feature_dim,
        "episodes_started": int(env.episode),
        "episode_usage": dict(env.episode_usage),
        "checkpoints": checkpoints,
        "train_config": settings.__dict__,
    }
    prefix = "safe_" if safe else ""
    (Path(output_dir)/f"{prefix}feature_mappo_seed{seed}_training_index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return checkpoints


def _score(metrics):
    values = []
    for key in SELECTION_METRICS:
        value = metrics.get(key)
        values.append(float(value) if isinstance(value, (int, float)) and np.isfinite(value)
                      else float("inf"))
    return tuple(values)


def select_feature_checkpoint(checkpoints, validation_configs, seeds, output_dir,
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
                run_dir=run_research_simulation(
                    cfg,key,Path(output_dir)/"validation_runs",int(seed))
                metrics=_last_cycle_metrics(Path(run_dir)); per.append(metrics)
                rows.append({"checkpoint":str(checkpoint),"config":str(config_path),
                             "seed":int(seed),**metrics})
        summary={"checkpoint":str(checkpoint),"n":len(per)}
        for metric in SELECTION_METRICS:
            vals=[float(x[metric]) for x in per
                  if isinstance(x.get(metric),(int,float)) and np.isfinite(x[metric])]
            summary[metric]=float(np.mean(vals)) if vals else None
        aggregate.append(summary)
    if not aggregate:
        raise ValueError("no feature candidate MAPPO checkpoints to select")
    chosen=min(aggregate,key=_score)
    out=Path(output_dir); out.mkdir(parents=True,exist_ok=True)
    _write_table(out/"validation_checkpoint_runs.csv",rows)
    _write_table(out/"validation_checkpoint_summary.csv",aggregate)
    document={
        "implementation":IMPLEMENTATION,
        "selection_rule":(
            "lexicographic validation means: missed-target rate, censored detection-delay P95, "
            "post-discovery total loss, maximum loss gap, revisit-age P95"),
        "selection_metrics":list(SELECTION_METRICS),
        "safe":bool(safe),
        "validation_configs":[str(Path(x).resolve()) for x in validation_configs],
        "validation_seeds":[int(x) for x in seeds],
        "selected":chosen,
    }
    (out/"selected_checkpoint.json").write_text(
        json.dumps(document,ensure_ascii=False,indent=2),encoding="utf-8")
    return chosen


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description="Feature-scored candidate MAPPO protocol")
    sub=parser.add_subparsers(dest="command",required=True)
    p=sub.add_parser("train")
    p.add_argument("configs",nargs="+"); p.add_argument("--output",required=True)
    p.add_argument("--seed",type=int,default=0); p.add_argument("--env-seeds",nargs="+",type=int)
    p.add_argument("--safe",action="store_true"); p.add_argument("--updates",type=int,default=300)
    p.add_argument("--rollout-steps",type=int,default=128); p.add_argument("--checkpoint-every",type=int,default=25)
    p.add_argument("--device",default="cpu")
    p=sub.add_parser("select")
    p.add_argument("checkpoints",nargs="+"); p.add_argument("--configs",nargs="+",required=True)
    p.add_argument("--seeds",nargs="+",type=int,required=True); p.add_argument("--output",required=True)
    p.add_argument("--safe",action="store_true"); p.add_argument("--device",default="cpu")
    args=parser.parse_args(argv)
    if args.command=="train":
        settings=MAPPOTrainConfig(updates=args.updates,rollout_steps=args.rollout_steps)
        print("\n".join(train_feature_candidate_mappo(
            args.configs,args.output,safe=args.safe,seed=args.seed,
            training_env_seeds=args.env_seeds,settings=settings,device=args.device,
            checkpoint_every=args.checkpoint_every)))
    else:
        print(json.dumps(select_feature_checkpoint(
            args.checkpoints,args.configs,args.seeds,args.output,
            safe=args.safe,device=args.device),ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import numpy as np

from ..config import load_config
from . import candidate_feature_mappo as base
from . import candidate_feature_runtime as sparse
from .candidate_feature_reward_v3 import (
    FRESHNESS_RECOVERY_WEIGHT,
    TRAINING_OBJECTIVE,
    FreshnessMultiScenarioFeatureEnv,
)
from .mappo import MAPPOTrainConfig, _gae, _torch


IMPLEMENTATION = "candidate_feature_v4_agentwise"
ACTOR_UPDATE = "per_agent_clipped_ratio_v1"


def numpy_clipped_surrogate(ratio, advantage, clip_ratio: float):
    """Reference PPO surrogate used by tests.

    ``ratio`` may contain one value per agent while ``advantage`` is the shared
    team advantage with a singleton/compatible agent dimension. The operation is
    elementwise before averaging, which is the intended parameter-shared MAPPO
    actor update. It deliberately differs from clipping a product of agent ratios.
    """
    ratio = np.asarray(ratio, dtype=float)
    advantage = np.asarray(advantage, dtype=float)
    clipped = np.clip(ratio, 1.0 - float(clip_ratio), 1.0 + float(clip_ratio))
    return np.minimum(ratio * advantage, clipped * advantage)


class AgentwiseFeatureCandidateMAPPOPolicy(sparse.SparseFeatureCandidateMAPPOPolicy):
    """Inference wrapper; architecture/action semantics are identical to v3."""

    def __init__(self, cfg, *, safe=False):
        old = base.IMPLEMENTATION
        base.IMPLEMENTATION = IMPLEMENTATION
        try:
            super().__init__(cfg, safe=safe)
        finally:
            base.IMPLEMENTATION = old


class AgentwiseFeatureCandidateSafeMAPPOPolicy(AgentwiseFeatureCandidateMAPPOPolicy):
    def __init__(self, cfg):
        super().__init__(cfg, safe=True)


def _sample_agentwise(net, obs, state, mask, candidate_features):
    torch = net.torch
    obs_t = torch.as_tensor(obs, dtype=torch.float32, device=net.device)
    state_t = torch.as_tensor(state, dtype=torch.float32, device=net.device)
    mask_t = torch.as_tensor(mask, dtype=torch.bool, device=net.device)
    feat_t = torch.as_tensor(candidate_features, dtype=torch.float32, device=net.device)
    dist = net.model.distribution(obs_t, feat_t, mask_t)
    action = dist.sample()
    logp = dist.log_prob(action)  # [n_agents], not a joint-product scalar.
    return (
        action.detach().cpu().numpy(),
        logp.detach().cpu().numpy(),
        float(net.model.value(state_t).detach().cpu()),
        float(net.model.cost_value(state_t).detach().cpu()),
    )


def _annotate_checkpoint(path: str | Path) -> None:
    torch, _ = _torch()
    path = Path(path)
    checkpoint = torch.load(path, map_location="cpu", weights_only=False)
    checkpoint["training_objective"] = TRAINING_OBJECTIVE
    checkpoint["freshness_recovery_weight"] = FRESHNESS_RECOVERY_WEIGHT
    checkpoint["actor_update"] = ACTOR_UPDATE
    torch.save(checkpoint, path)
    sidecar = Path(str(path) + ".json")
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    metadata["training_objective"] = TRAINING_OBJECTIVE
    metadata["freshness_recovery_weight"] = FRESHNESS_RECOVERY_WEIGHT
    metadata["actor_update"] = ACTOR_UPDATE
    sidecar.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")


def train_agentwise_feature_mappo(
    train_configs: Iterable[str | Path], output_dir: str | Path, *,
    safe=False, seed=0, training_env_seeds=None,
    settings: MAPPOTrainConfig | None=None, device="cpu", checkpoint_every=25,
):
    """Train feature-candidate MAPPO with agent-wise PPO ratios.

    The team reward and centralized value remain scalar. The resulting GAE is
    replicated across homogeneous agents, while each agent's categorical ratio is
    clipped independently before averaging. This is the only actor-optimization
    change relative to v3; environment, reward shaping, candidate set and critic
    remain unchanged.
    """
    torch, _ = _torch()
    cfg_paths = [Path(p).resolve() for p in train_configs]
    cfgs = [load_config(p) for p in cfg_paths]
    settings = settings or MAPPOTrainConfig()
    env_seeds = tuple(int(x) for x in (training_env_seeds or [seed]))
    np.random.seed(int(seed)); torch.manual_seed(int(seed))

    env = FreshnessMultiScenarioFeatureEnv(
        cfgs, network_seed=seed, safe=safe, episode_seeds=env_seeds)
    obs, state, mask, features = env.reset()
    net = sparse.SparseFeatureCandidateActorCritic(
        env.obs_dim, len(state), env.candidate_feature_dim,
        max_candidates=env.max_candidates, safe=safe, device=device)
    optimizer = torch.optim.Adam(net.model.parameters(), lr=settings.lr)
    lagrange = 0.0
    history = []
    checkpoints = []

    for update in range(settings.updates):
        O=[]; S=[]; M=[]; F=[]; A=[]; LP=[]; V=[]; CV=[]; R=[]; C=[]; D=[]
        kind_counts = {kind: 0 for kind in base._KIND_ORDER}
        for _ in range(settings.rollout_steps):
            action, logp, value, cost_value = _sample_agentwise(
                net, obs, state, mask, features)
            next_obs, next_state, next_mask, next_features, reward, cost, done, info = env.step(action)
            O.append(obs.copy()); S.append(state.copy()); M.append(mask.copy()); F.append(features.copy())
            A.append(action.copy()); LP.append(logp.copy()); V.append(value); CV.append(cost_value)
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

        obs_batch=torch.as_tensor(np.asarray(O),dtype=torch.float32,device=net.device)
        state_batch=torch.as_tensor(np.asarray(S),dtype=torch.float32,device=net.device)
        mask_batch=torch.as_tensor(np.asarray(M),dtype=torch.bool,device=net.device)
        feat_batch=torch.as_tensor(np.asarray(F),dtype=torch.float32,device=net.device)
        action_batch=torch.as_tensor(np.asarray(A),dtype=torch.long,device=net.device)
        old_logp=torch.as_tensor(np.asarray(LP),dtype=torch.float32,device=net.device)
        adv_batch=torch.as_tensor(combined,dtype=torch.float32,device=net.device)
        return_batch=torch.as_tensor(returns,dtype=torch.float32,device=net.device)
        cost_return_batch=torch.as_tensor(creturns,dtype=torch.float32,device=net.device)
        indices=np.arange(settings.rollout_steps)
        losses=[]; policy_losses=[]; clip_fractions=[]; ratio_means=[]

        for _ in range(settings.epochs):
            np.random.shuffle(indices)
            for start in range(0,len(indices),settings.minibatch):
                idx=indices[start:start+settings.minibatch]
                ob=obs_batch[idx]; st=state_batch[idx]; mk=mask_batch[idx]
                ft=feat_batch[idx]; act=action_batch[idx]
                dist=net.model.distribution(ob,ft,mk)
                logp=dist.log_prob(act)  # [batch, n_agents]
                ratio=torch.exp(logp-old_logp[idx])
                a=adv_batch[idx].unsqueeze(-1)
                clipped=torch.clamp(ratio,1-settings.clip_ratio,1+settings.clip_ratio)
                policy_loss=-torch.minimum(ratio*a,clipped*a).mean()
                value_loss=(net.model.value(st)-return_batch[idx]).pow(2).mean()
                cost_value_loss=(
                    (net.model.cost_value(st)-cost_return_batch[idx]).pow(2).mean()
                    if safe else torch.tensor(0.0,device=net.device))
                # Preserve the previous total-entropy scale so ratio factorization is
                # the only exploration-related change in this diagnostic version.
                entropy=dist.entropy().sum(dim=-1).mean()
                loss=(policy_loss+settings.value_coef*(value_loss+cost_value_loss)
                      -settings.entropy_coef*entropy)
                optimizer.zero_grad(); loss.backward()
                torch.nn.utils.clip_grad_norm_(net.model.parameters(),settings.max_grad_norm)
                optimizer.step()
                losses.append(float(loss.detach().cpu()))
                policy_losses.append(float(policy_loss.detach().cpu()))
                ratio_means.append(float(ratio.detach().mean().cpu()))
                clip_fractions.append(float(
                    ((ratio.detach() < 1-settings.clip_ratio) |
                     (ratio.detach() > 1+settings.clip_ratio)).float().mean().cpu()))

        mean_cost=float(np.mean(C))
        if safe:
            lagrange=max(0.0,lagrange+settings.lagrange_lr*(mean_cost-settings.cost_limit))
        total_actions=max(sum(kind_counts.values()),1)
        history.append({
            "update":update+1,
            "reward_mean":float(np.mean(R)),
            "cost_mean":mean_cost,
            "loss_mean":float(np.mean(losses)) if losses else 0.0,
            "policy_loss_mean":float(np.mean(policy_losses)) if policy_losses else 0.0,
            "ratio_mean":float(np.mean(ratio_means)) if ratio_means else 1.0,
            "clip_fraction":float(np.mean(clip_fractions)) if clip_fractions else 0.0,
            "lagrange":float(lagrange),
            "episodes_started":int(env.episode),
            "actor_update":ACTOR_UPDATE,
            "action_kind_fraction":{
                key:float(value/total_actions) for key,value in kind_counts.items()
            },
        })

        if checkpoint_every and ((update+1)%int(checkpoint_every)==0 or update+1==settings.updates):
            name=("safe_feature_mappo" if safe else "feature_mappo")+f"_seed{int(seed)}_u{update+1:04d}.pt"
            old_impl=base.IMPLEMENTATION
            base.IMPLEMENTATION=IMPLEMENTATION
            try:
                path=base._save_checkpoint(
                    net,Path(output_dir)/name,safe=safe,seed=seed,settings=settings,
                    history=history,env=env,update=update+1,
                    training_scenarios=[str(p) for p in cfg_paths],
                    training_env_seeds=env_seeds)
            finally:
                base.IMPLEMENTATION=old_impl
            _annotate_checkpoint(path)
            checkpoints.append(str(path))

    Path(output_dir).mkdir(parents=True,exist_ok=True)
    index={
        "implementation":IMPLEMENTATION,
        "training_objective":TRAINING_OBJECTIVE,
        "freshness_recovery_weight":FRESHNESS_RECOVERY_WEIGHT,
        "actor_update":ACTOR_UPDATE,
        "safe":bool(safe),"seed":int(seed),
        "training_scenarios":[str(p) for p in cfg_paths],
        "training_env_seeds":[int(x) for x in env_seeds],
        "max_targets":env.max_targets,"top_search_cells":env.top_search_cells,
        "max_candidates":env.max_candidates,"candidate_feature_dim":env.candidate_feature_dim,
        "episodes_started":int(env.episode),"episode_usage":dict(env.episode_usage),
        "checkpoints":checkpoints,"train_config":settings.__dict__,
    }
    prefix="safe_" if safe else ""
    (Path(output_dir)/f"{prefix}feature_mappo_seed{seed}_training_index.json").write_text(
        json.dumps(index,ensure_ascii=False,indent=2),encoding="utf-8")
    return checkpoints


def select_agentwise_checkpoint(checkpoints, validation_configs, seeds, output_dir,
                                *, safe=False, device="cpu"):
    old=base.IMPLEMENTATION
    base.IMPLEMENTATION=IMPLEMENTATION
    try:
        chosen=base.select_feature_checkpoint(
            checkpoints,validation_configs,seeds,output_dir,safe=safe,device=device)
    finally:
        base.IMPLEMENTATION=old
    path=Path(output_dir)/"selected_checkpoint.json"
    document=json.loads(path.read_text(encoding="utf-8"))
    document["implementation"]=IMPLEMENTATION
    document["training_objective"]=TRAINING_OBJECTIVE
    document["freshness_recovery_weight"]=FRESHNESS_RECOVERY_WEIGHT
    document["actor_update"]=ACTOR_UPDATE
    path.write_text(json.dumps(document,ensure_ascii=False,indent=2),encoding="utf-8")
    return chosen


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description="Agent-wise clipped-ratio feature MAPPO")
    sub=parser.add_subparsers(dest="command",required=True)
    p=sub.add_parser("train")
    p.add_argument("configs",nargs="+"); p.add_argument("--output",required=True)
    p.add_argument("--seed",type=int,default=0); p.add_argument("--env-seeds",nargs="+",type=int)
    p.add_argument("--safe",action="store_true"); p.add_argument("--updates",type=int,default=30)
    p.add_argument("--rollout-steps",type=int,default=128); p.add_argument("--checkpoint-every",type=int,default=10)
    p.add_argument("--device",default="cpu")
    p=sub.add_parser("select")
    p.add_argument("checkpoints",nargs="+"); p.add_argument("--configs",nargs="+",required=True)
    p.add_argument("--seeds",nargs="+",type=int,required=True); p.add_argument("--output",required=True)
    p.add_argument("--safe",action="store_true"); p.add_argument("--device",default="cpu")
    args=parser.parse_args(argv)
    if args.command=="train":
        settings=MAPPOTrainConfig(updates=args.updates,rollout_steps=args.rollout_steps)
        print("\n".join(train_agentwise_feature_mappo(
            args.configs,args.output,safe=args.safe,seed=args.seed,
            training_env_seeds=args.env_seeds,settings=settings,device=args.device,
            checkpoint_every=args.checkpoint_every)))
    else:
        print(json.dumps(select_agentwise_checkpoint(
            args.checkpoints,args.configs,args.seeds,args.output,
            safe=args.safe,device=args.device),ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()

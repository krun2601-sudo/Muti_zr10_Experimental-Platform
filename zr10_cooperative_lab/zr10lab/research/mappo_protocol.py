from __future__ import annotations

import argparse
import copy
import csv
import json
from pathlib import Path
from typing import Iterable

import numpy as np

from ..config import load_config
from .batch import _last_cycle_metrics, _write_table
from .mappo import MAPPOTrainConfig, SharedActorCritic, _gae, _torch
from .provenance import runtime_provenance
from .rl_env import ResearchMARLEnv
from .runner import run_research_simulation


class MultiScenarioResearchEnv:
    """Cycle deterministically across frozen training scenarios at episode reset."""

    def __init__(self, configs, seed=0):
        if not configs:
            raise ValueError("MAPPO training requires at least one scenario")
        self.configs = [copy.deepcopy(cfg) for cfg in configs]
        self.base_seed = int(seed)
        self.episode = 0
        self.env = ResearchMARLEnv(self.configs[0], seed=self.base_seed)
        signature = (self.env.n_agents, self.env.obs_dim, self.env.action_dim)
        for cfg in self.configs[1:]:
            probe = ResearchMARLEnv(cfg, seed=self.base_seed)
            if (probe.n_agents, probe.obs_dim, probe.action_dim) != signature:
                raise ValueError("all MAPPO training scenarios must share agent/observation/action dimensions")

    @property
    def n_agents(self): return self.env.n_agents
    @property
    def obs_dim(self): return self.env.obs_dim
    @property
    def action_dim(self): return self.env.action_dim

    def reset(self, seed=None):
        index = self.episode % len(self.configs)
        episode_seed = self.base_seed + self.episode if seed is None else int(seed)
        self.env = ResearchMARLEnv(self.configs[index], seed=episode_seed)
        self.episode += 1
        return self.env.reset(seed=episode_seed)

    def step(self, action):
        return self.env.step(action)


def _save_checkpoint(net, path: Path, *, safe, seed, settings, history, env,
                     update, training_scenarios):
    torch, _ = _torch()
    path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = {
        "state_dict": net.state_dict(), "safe": bool(safe), "seed": int(seed),
        "obs_dim": env.obs_dim, "state_dim": env.n_agents * env.obs_dim,
        "action_dim": env.action_dim, "n_agents": env.n_agents,
        "train_config": settings.__dict__, "history": list(history),
        "training_update": int(update),
        "training_scenarios": list(training_scenarios),
    }
    torch.save(checkpoint, path)
    metadata = {k:v for k,v in checkpoint.items() if k != "state_dict"}
    metadata["runtime_provenance"] = runtime_provenance()
    path.with_suffix(path.suffix + ".json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def train_mappo_protocol(train_configs: Iterable[str | Path], output_dir: str | Path,
                         *, safe=False, seed=0, settings: MAPPOTrainConfig | None=None,
                         device="cpu", checkpoint_every=25):
    """Train MAPPO only on an explicit frozen training scenario list.

    Scenarios rotate at episode boundaries. Periodic checkpoints are intended for
    *validation-only* selection; the held-out test split must never be passed here.
    """
    torch, _ = _torch()
    cfg_paths = [Path(p).resolve() for p in train_configs]
    cfgs = [load_config(p) for p in cfg_paths]
    settings = settings or MAPPOTrainConfig()
    np.random.seed(int(seed)); torch.manual_seed(int(seed))
    env = MultiScenarioResearchEnv(cfgs, seed=seed)
    obs, state = env.reset(seed=seed)
    net = SharedActorCritic(env.obs_dim, len(state), env.action_dim, safe=safe, device=device)
    optimizer = torch.optim.Adam(net.model.parameters(), lr=settings.lr)
    lagrange = 0.0; history = []; checkpoints = []
    for update in range(settings.updates):
        O=[]; S=[]; U=[]; LP=[]; V=[]; CV=[]; R=[]; C=[]; D=[]
        for _ in range(settings.rollout_steps):
            action, raw, logp, value, cost_value = net.sample(obs, state)
            next_obs, next_state, reward, cost, done, info = env.step(action)
            O.append(obs.copy()); S.append(state.copy()); U.append(raw.copy()); LP.append(logp)
            V.append(value); CV.append(cost_value); R.append(reward); C.append(cost); D.append(done)
            obs, state = next_obs, next_state
            if done:
                obs, state = env.reset()
        with torch.no_grad():
            state_t = torch.as_tensor(state, dtype=torch.float32, device=net.device)
            bootstrap = float(net.model.value(state_t).cpu())
            cost_bootstrap = float(net.model.cost_value(state_t).cpu()) if safe else 0.0
        adv, returns = _gae(np.asarray(R,np.float32), np.asarray(V,np.float32), np.asarray(D,bool),
                            bootstrap, settings.gamma, settings.gae_lambda)
        cadv, creturns = _gae(np.asarray(C,np.float32), np.asarray(CV,np.float32), np.asarray(D,bool),
                              cost_bootstrap, settings.gamma, settings.gae_lambda)
        adv = (adv-adv.mean())/(adv.std()+1e-8)
        if safe: cadv = (cadv-cadv.mean())/(cadv.std()+1e-8)
        combined = adv-float(lagrange)*cadv if safe else adv
        obs_batch=torch.as_tensor(np.asarray(O),dtype=torch.float32,device=net.device)
        state_batch=torch.as_tensor(np.asarray(S),dtype=torch.float32,device=net.device)
        raw_batch=torch.as_tensor(np.asarray(U),dtype=torch.float32,device=net.device)
        old_logp=torch.as_tensor(np.asarray(LP),dtype=torch.float32,device=net.device)
        adv_batch=torch.as_tensor(combined,dtype=torch.float32,device=net.device)
        return_batch=torch.as_tensor(returns,dtype=torch.float32,device=net.device)
        cost_return_batch=torch.as_tensor(creturns,dtype=torch.float32,device=net.device)
        indices=np.arange(settings.rollout_steps); losses=[]
        for _ in range(settings.epochs):
            np.random.shuffle(indices)
            for start in range(0,len(indices),settings.minibatch):
                idx=indices[start:start+settings.minibatch]
                ob=obs_batch[idx]; st=state_batch[idx]; raw=raw_batch[idx]
                dist=net.model.distribution(ob); action=torch.tanh(raw)
                logp=(dist.log_prob(raw)-torch.log(1-action.pow(2)+1e-6)).sum(dim=(-1,-2))
                ratio=torch.exp(logp-old_logp[idx]); a=adv_batch[idx]
                clipped=torch.clamp(ratio,1-settings.clip_ratio,1+settings.clip_ratio)
                policy_loss=-torch.minimum(ratio*a,clipped*a).mean()
                value_loss=(net.model.value(st)-return_batch[idx]).pow(2).mean()
                cost_value_loss=((net.model.cost_value(st)-cost_return_batch[idx]).pow(2).mean()
                                 if safe else torch.tensor(0.0,device=net.device))
                entropy=dist.entropy().sum(dim=(-1,-2)).mean()
                loss=policy_loss+settings.value_coef*(value_loss+cost_value_loss)-settings.entropy_coef*entropy
                optimizer.zero_grad(); loss.backward()
                torch.nn.utils.clip_grad_norm_(net.model.parameters(),settings.max_grad_norm)
                optimizer.step(); losses.append(float(loss.detach().cpu()))
        mean_cost=float(np.mean(C))
        if safe:
            lagrange=max(0.0,lagrange+settings.lagrange_lr*(mean_cost-settings.cost_limit))
        history.append({"update":update+1,"reward_mean":float(np.mean(R)),"cost_mean":mean_cost,
                        "loss_mean":float(np.mean(losses)) if losses else 0.0,"lagrange":float(lagrange)})
        if checkpoint_every and ((update+1)%int(checkpoint_every)==0 or update+1==settings.updates):
            name=("safe_mappo" if safe else "mappo")+f"_seed{int(seed)}_u{update+1:04d}.pt"
            checkpoints.append(str(_save_checkpoint(net,Path(output_dir)/name,safe=safe,seed=seed,
                settings=settings,history=history,env=env,update=update+1,
                training_scenarios=[str(p) for p in cfg_paths])))
    Path(output_dir).mkdir(parents=True,exist_ok=True)
    (Path(output_dir)/f"{'safe_mappo' if safe else 'mappo'}_seed{seed}_training_index.json").write_text(
        json.dumps({"safe":bool(safe),"seed":int(seed),"training_scenarios":[str(p) for p in cfg_paths],
                    "checkpoints":checkpoints,"train_config":settings.__dict__},ensure_ascii=False,indent=2),
        encoding="utf-8")
    return checkpoints


def _score(metrics):
    # Validation selection follows task priority, not a hidden weighted reward:
    # loss -> max gap -> revisit P95 -> detection delay. None is worst.
    def value(key):
        v=metrics.get(key)
        return float(v) if isinstance(v,(int,float)) and np.isfinite(v) else float("inf")
    return (value("research_total_loss_s"), value("research_max_loss_gap_s"),
            value("research_revisit_age_p95_s"), value("research_detection_delay_p95_s"))


def select_checkpoint(checkpoints, validation_configs, seeds, output_dir,
                      *, safe=False, device="cpu"):
    """Select checkpoint on validation scenarios only using lexicographic task metrics."""
    rows=[]; aggregate=[]
    for checkpoint in checkpoints:
        per=[]
        for config_path in validation_configs:
            for seed in seeds:
                cfg=load_config(config_path)
                baseline=cfg.policy.setdefault("research",{}).setdefault("baselines",{})
                key="safe_mappo" if safe else "mappo"
                baseline.setdefault(key,{})["model_path"]=str(Path(checkpoint).resolve())
                baseline[key]["device"]=device
                run_dir=run_research_simulation(cfg,key,Path(output_dir)/"validation_runs",int(seed))
                metrics=_last_cycle_metrics(Path(run_dir)); per.append(metrics)
                rows.append({"checkpoint":str(checkpoint),"config":str(config_path),"seed":int(seed),**metrics})
        summary={"checkpoint":str(checkpoint),"n":len(per)}
        for metric in ("research_total_loss_s","research_max_loss_gap_s",
                       "research_revisit_age_p95_s","research_detection_delay_p95_s"):
            values=[float(x[metric]) for x in per if isinstance(x.get(metric),(int,float)) and np.isfinite(x[metric])]
            summary[metric]=float(np.mean(values)) if values else None
        aggregate.append(summary)
    if not aggregate: raise ValueError("no MAPPO checkpoints to select")
    chosen=min(aggregate,key=_score)
    out=Path(output_dir); out.mkdir(parents=True,exist_ok=True)
    _write_table(out/"validation_checkpoint_runs.csv",rows)
    _write_table(out/"validation_checkpoint_summary.csv",aggregate)
    (out/"selected_checkpoint.json").write_text(json.dumps({
        "selection_rule":"lexicographic validation metrics: total loss, max gap, revisit P95, detection delay P95",
        "safe":bool(safe),"validation_configs":[str(Path(x).resolve()) for x in validation_configs],
        "validation_seeds":[int(x) for x in seeds],"selected":chosen,
    },ensure_ascii=False,indent=2),encoding="utf-8")
    return chosen


def main(argv=None):
    parser=argparse.ArgumentParser(description="Frozen multi-scenario MAPPO training/validation protocol")
    sub=parser.add_subparsers(dest="command",required=True)
    p=sub.add_parser("train"); p.add_argument("configs",nargs="+"); p.add_argument("--output",required=True)
    p.add_argument("--seed",type=int,default=0); p.add_argument("--safe",action="store_true")
    p.add_argument("--updates",type=int,default=300); p.add_argument("--rollout-steps",type=int,default=256)
    p.add_argument("--checkpoint-every",type=int,default=25); p.add_argument("--device",default="cpu")
    p=sub.add_parser("select"); p.add_argument("checkpoints",nargs="+"); p.add_argument("--configs",nargs="+",required=True)
    p.add_argument("--seeds",nargs="+",type=int,required=True); p.add_argument("--output",required=True)
    p.add_argument("--safe",action="store_true"); p.add_argument("--device",default="cpu")
    args=parser.parse_args(argv)
    if args.command=="train":
        settings=MAPPOTrainConfig(updates=args.updates,rollout_steps=args.rollout_steps)
        print("\n".join(train_mappo_protocol(args.configs,args.output,safe=args.safe,seed=args.seed,
              settings=settings,device=args.device,checkpoint_every=args.checkpoint_every)))
    else:
        print(json.dumps(select_checkpoint(args.checkpoints,args.configs,args.seeds,args.output,
              safe=args.safe,device=args.device),ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()

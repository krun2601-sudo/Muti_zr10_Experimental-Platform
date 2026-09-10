"""随机策略/协同基线的 Gym 接口演示，包含必要的终止与掩码处理。

在项目根目录运行：python -m examples.train_random --config configs/four_zr10.yaml --steps 100
随机动作只用于检验接口，不应被解释为训练完成的算法。
"""
from __future__ import annotations

import argparse

import numpy as np

from zr10lab.config import load_config
from zr10lab.learning import CooperativeObservationEnv
from zr10lab.policies import build_policy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="实验 YAML 路径")
    parser.add_argument("--steps", type=int, default=100)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--policy", choices=["random", "baseline"], default="random")
    args = parser.parse_args()
    cfg = load_config(args.config)
    env = CooperativeObservationEnv(cfg, max_steps=args.steps, render_mode="ansi")
    baseline = build_policy(cfg)
    baseline.reset()
    observation, info = env.reset(seed=args.seed)
    total_reward = 0.0
    try:
        for _ in range(args.steps):
            if args.policy == "baseline":
                action = env.encode_actions(baseline.decide(env.context).actions)
            else:
                # mask=0 的位置在 decode_action 中会再次强制冻结。这里乘
                # mask 是给训练代码的显式提示，不能取代控制层的参数白名单。
                action = env.action_space.sample() * observation["action_mask"]
            observation, reward, terminated, truncated, info = env.step(np.asarray(action, np.float32))
            total_reward += reward
            if terminated or truncated:
                break
        print(env.render())
        print(f"回合累计奖励 {total_reward:.4f}；最后一步指标 {info}")
    finally:
        env.close()


if __name__ == "__main__":
    main()

"""可选 Gymnasium 学习接口；动作、观测契约独立于具体强化学习库。

安装 ``pip install -e .[learning]`` 后可创建环境。真值只在私有奖励函数
中使用，不进入 observation、PolicyContext 或 info 中的原始状态。
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment

from .config import LabConfig, config_from_dict
from .fusion import FusionEngine
from .geometry import intrinsics_at_zoom, pixel_to_world_ray
from .models import Action, PolicyContext

try:
    import gymnasium as gym
    from gymnasium import spaces
except ImportError:
    gym = None
    spaces = None


class CooperativeObservationEnv(gym.Env if gym is not None else object):
    """四站或任意 N 站的集中训练环境，支持外部多智能体包装器。

    设备顺序固定为 ``cfg.active_devices`` 的顺序。动作按设备逐行展开：
    ``[yaw_0,pitch_0,(zoom_0),yaw_1,pitch_1,(zoom_1),...]``，均在 [-1,1]，
    线性映射到该设备配置的绝对角度/倍率范围。冻结维度依然保留位置，
    但 action_mask=0，解码结果为 None，任何输入均不能改变冻结参数。

    监视任务通常没有自然终点，默认 terminated=False，达到 max_steps 时
    truncated=True；这样价值学习算法能够正确区分时间截断和任务终止。
    """

    metadata = {"render_modes": ["ansi"], "render_fps": 10}

    def __init__(self, cfg: LabConfig, max_steps: int | None = None,
                 max_targets: int = 8, max_detections_per_device: int = 16,
                 include_zoom: bool | None = None, render_mode: str | None = None,
                 seed: int | None = None):
        if gym is None:
            raise ImportError("学习环境需要可选依赖：pip install -e .[learning]")
        if render_mode not in (None, "ansi"):
            raise ValueError("render_mode 只支持 None 或 ansi")
        # 深拷贝防止训练时修改配置污染外部实验；学习模块始终只创建仿真器。
        self.cfg = config_from_dict(cfg.to_dict())
        self.device_configs = tuple(self.cfg.active_devices)
        self.device_ids = tuple(d.id for d in self.device_configs)
        self.enabled = frozenset(self.cfg.action_space.get("enabled", ["yaw_deg", "pitch_deg"]))
        self.include_zoom = "zoom" in self.enabled if include_zoom is None else bool(include_zoom)
        self.columns = ("yaw_deg", "pitch_deg", "zoom") if self.include_zoom else ("yaw_deg", "pitch_deg")
        self.dt = 1.0 / float(self.cfg.system.get("rate_hz", 10))
        self.max_steps = int(max_steps if max_steps is not None else math.ceil(float(self.cfg.system.get("duration_s", 60)) / self.dt))
        self.max_targets = int(max_targets)
        self.max_detections = int(max_detections_per_device)
        if min(self.max_steps, self.max_targets, self.max_detections) <= 0:
            raise ValueError("max_steps、max_targets 和 max_detections_per_device 必须为正整数")
        self.render_mode = render_mode
        self._initial_seed = seed
        self.position_scale = float(self.cfg.policy.get("learning_position_scale_m", 200.0))
        self.velocity_scale = float(self.cfg.policy.get("learning_velocity_scale_mps", 20.0))
        if min(self.position_scale, self.velocity_scale) <= 0:
            raise ValueError("学习归一化尺度必须为正")
        n, m, k = len(self.device_ids), self.max_detections, self.max_targets
        self._action_mask = np.tile(np.asarray([float(c in self.enabled) for c in self.columns], np.float32), n)
        self.action_space = spaces.Box(-1.0, 1.0, shape=(n * len(self.columns),), dtype=np.float32)
        # 给训练器有限范围并截断极端离群特征，避免无穷 Box 采样和失控
        # 协方差造成数值问题。位置/速度上限为各自归一化尺度的 1000 倍；
        # 这只是学习特征边界，不修改融合原始估计与日志。
        device_low = np.asarray([-1, -1, -1, -1, -1, 0, 0, -1000, -1000, -1000,
                                 -1, -1, -1, 0, 0, -1], np.float32)
        device_high = np.asarray([1, 1, 1, 1, 1, 1, 1000, 1000, 1000, 1000,
                                  1, 1, 1, 1000, 1000, 1], np.float32)
        detection_low = np.asarray([-1, -1, 0, 0, 0, 0, 0, 0], np.float32)
        detection_high = np.asarray([1, 1, 2, 2, 1, 1000, 1_000_000, 1000], np.float32)
        track_low = np.asarray([-1000] * 6 + [0] * 4 + [-1, 0, 0, 0], np.float32)
        track_high = np.asarray([1000] * 6 + [1_000_000] * 3 + [1000, 1, 1, 1, 1], np.float32)
        self.observation_space = spaces.Dict({
            "devices": spaces.Box(np.tile(device_low, (n, 1)), np.tile(device_high, (n, 1)), dtype=np.float32),
            "detections": spaces.Box(np.tile(detection_low, (n, m, 1)), np.tile(detection_high, (n, m, 1)), dtype=np.float32),
            "detection_mask": spaces.MultiBinary((n, m)),
            "tracks": spaces.Box(np.tile(track_low, (k, 1)), np.tile(track_high, (k, 1)), dtype=np.float32),
            "track_mask": spaces.MultiBinary(k),
            "action_mask": spaces.Box(0.0, 1.0, shape=self.action_space.shape, dtype=np.float32),
        })
        self._world = None
        self._fusion = None
        self._context = None
        self._step = 0
        self._finished = False
        self._slots: dict[str, int] = {}
        self._last_localizations = []

    @property
    def context(self) -> PolicyContext:
        """提供同硬件运行器一致的算法输入，便于评估内置/自定义策略。"""
        if self._context is None:
            raise RuntimeError("必须先调用 reset()")
        return self._context

    def _sense(self) -> None:
        states = self._world.states()
        detections = tuple(self._world.observe())
        configs = {d.id: d for d in self.device_configs}
        rays = tuple(pixel_to_world_ray(d, states[d.device_id], configs[d.device_id]) for d in detections)
        tracks, localizations, _ = self._fusion.update(rays, self._world.t)
        self._last_localizations = localizations
        self._context = PolicyContext(t=float(self._world.t), dt=self.dt, step=self._step,
                                      devices=states, detections=detections, rays=rays, tracks=tuple(tracks))

    @staticmethod
    def _normalize(value: float, limits: tuple[float, float]) -> float:
        return 2 * (value - limits[0]) / (limits[1] - limits[0]) - 1

    def _observation(self) -> dict[str, np.ndarray]:
        context = self.context
        n = len(self.device_ids)
        devices = np.zeros((n, 16), dtype=np.float32)
        detections = np.zeros((n, self.max_detections, 8), dtype=np.float32)
        detection_mask = np.zeros((n, self.max_detections), dtype=np.int8)
        tracks = np.zeros((self.max_targets, 14), dtype=np.float32)
        track_mask = np.zeros(self.max_targets, dtype=np.int8)
        for i, config in enumerate(self.device_configs):
            state = context.devices[config.id]
            camera = intrinsics_at_zoom(config, state.zoom)
            devices[i] = [self._normalize(state.yaw_deg, config.yaw_limits_deg),
                          self._normalize(state.pitch_deg, config.pitch_limits_deg),
                          self._normalize(state.zoom, config.zoom_limits),
                          state.yaw_rate_dps / config.max_slew_dps,
                          state.pitch_rate_dps / config.max_slew_dps,
                          float(state.connected), max(0, context.t - state.t),
                          *[v / self.position_scale for v in config.position_m],
                          *[v / 180.0 for v in config.mount_rpy_deg],
                          camera.fx / camera.width, camera.fy / camera.height, state.roll_deg / 180.0]
            local = sorted((d for d in context.detections if d.device_id == config.id),
                           key=lambda d: (-d.confidence, d.local_id, d.frame_id))[:self.max_detections]
            for j, detection in enumerate(local):
                x1, y1, x2, y2 = detection.bbox_xyxy
                width, height = detection.image_size
                u, v = detection.center
                detections[i, j] = [2 * u / width - 1, 2 * v / height - 1,
                                    (x2 - x1) / width, (y2 - y1) / height,
                                    detection.confidence, max(0, context.t - detection.t),
                                    float(detection.class_id), detection.time_uncertainty_s]
                detection_mask[i, j] = 1
        # 轨迹 ID 只用来保持槽位稳定，字符串/真值 ID 不会编码给学习策略。
        current = {tr.track_id: tr for tr in context.tracks}
        self._slots = {key: slot for key, slot in self._slots.items() if key in current}
        empty = [i for i in range(self.max_targets) if i not in self._slots.values()]
        newcomers = sorted((tr for key, tr in current.items() if key not in self._slots),
                           key=lambda tr: (tr.status != "confirmed", -tr.hits, tr.track_id))
        for track, slot in zip(newcomers, empty):
            self._slots[track.track_id] = slot
        for key, slot in self._slots.items():
            track = current[key]
            covariance = np.asarray(track.covariance, dtype=float)
            uncertainty = np.diag(covariance)[:3] / self.position_scale ** 2
            tracks[slot] = [*[v / self.position_scale for v in track.position],
                            *[v / self.velocity_scale for v in track.velocity],
                            *uncertainty, max(0, context.t - track.last_seen_t),
                            {"tentative": 0.0, "confirmed": 1.0, "coasting": -1.0}.get(track.status, 0.0),
                            min(track.hits, 100) / 100.0, float(track.measured),
                            len(set(track.device_ids)) / max(n, 1)]
            track_mask[slot] = 1
        observation = {"devices": devices, "detections": detections, "detection_mask": detection_mask,
                       "tracks": tracks, "track_mask": track_mask, "action_mask": self._action_mask.copy()}
        self._clipped_feature_count = 0
        for name in ("devices", "detections", "tracks"):
            box = self.observation_space[name]
            self._clipped_feature_count += int(np.count_nonzero(
                (observation[name] < box.low) | (observation[name] > box.high)))
            np.clip(observation[name], box.low, box.high, out=observation[name])
        return observation

    def reset(self, *, seed: int | None = None, options: dict[str, Any] | None = None):
        """相同 seed/config/action 序列产生相同回合；重置融合和轨迹槽位。"""
        if seed is None and self._world is None:
            seed = self._initial_seed
        super().reset(seed=seed)
        # 未传 seed 时从环境 RNG 派生子种子，既允许重复训练又可复现。
        simulation_seed = int(seed if seed is not None else self.np_random.integers(0, 2 ** 31 - 1))
        self.action_space.seed(simulation_seed)
        from .simulation import SimulationWorld
        self._world = SimulationWorld(self.cfg)
        self._world.reset(seed=simulation_seed)
        self._fusion = FusionEngine(self.cfg.fusion)
        self._fusion.reset()
        self._step = 0
        self._finished = False
        self._slots = {}
        self._sense()
        observation = self._observation()
        return observation, {"time_s": self.context.t, "step": 0,
                             "device_ids": self.device_ids, "action_columns": self.columns,
                             "observation_clipped_features": self._clipped_feature_count}

    def decode_action(self, action: np.ndarray) -> dict[str, Action]:
        """公开解码器便于测试和多智能体包装器复用；冻结参数始终为 None。"""
        array = np.asarray(action, dtype=float)
        if array.shape != self.action_space.shape or not np.isfinite(array).all():
            raise ValueError(f"动作必须是有限数组，形状 {self.action_space.shape}")
        rows = np.clip(array, -1, 1).reshape(len(self.device_ids), len(self.columns))
        result = {}
        for config, row in zip(self.device_configs, rows):
            bounds = {"yaw_deg": config.yaw_limits_deg, "pitch_deg": config.pitch_limits_deg, "zoom": config.zoom_limits}
            values = {}
            for name, value in zip(self.columns, row):
                if name in self.enabled:
                    lo, hi = bounds[name]
                    values[name] = float(lo + (value + 1) * .5 * (hi - lo))
            result[config.id] = Action(config.id, **values, reason="learning",
                                       issued_t=self.context.t, ttl_s=max(self.dt * 2, .5))
        return result

    def encode_actions(self, actions: dict[str, Action]) -> np.ndarray:
        """把普通 Policy 动作变成环境向量，方便同一场景比较基线与学习算法。"""
        values = []
        for config in self.device_configs:
            action = actions.get(config.id)
            state = self.context.devices[config.id]
            bounds = {"yaw_deg": config.yaw_limits_deg, "pitch_deg": config.pitch_limits_deg, "zoom": config.zoom_limits}
            for name in self.columns:
                value = getattr(action, name, None) if action is not None else None
                values.append(self._normalize(getattr(state, name) if value is None else value, bounds[name]))
        return np.clip(np.asarray(values, dtype=np.float32), -1, 1)

    def _reward(self, previous_states) -> tuple[float, dict[str, float]]:
        """训练可用特权监督信号；该函数不修改任何算法观测。

        使用匈牙利匹配防止多个错误重复轨迹对同一真目标反复领取覆盖奖励。
        只奖励当前时刻有双站测量支持的轨迹，纯预测轨迹不能伪装成定位成功。
        """
        truth = list(self._world.truth().values())
        estimates = [tr for tr in self.context.tracks if tr.measured and len(set(tr.device_ids)) >= 2]
        coverage, accuracy = 0.0, 0.0
        if truth and estimates:
            distances = np.linalg.norm(np.asarray([tr.position for tr in estimates])[:, None, :] - np.asarray(truth)[None, :, :], axis=2)
            row, col = linear_sum_assignment(distances)
            errors = distances[row, col]
            gate = float(self.cfg.policy.get("learning_reward_gate_m", 20))
            good = errors <= gate
            coverage = float(np.count_nonzero(good) / len(truth))
            accuracy = float(np.sum(np.exp(-errors[good] / max(gate / 3, 1e-6))) / len(truth))
        motion = np.mean([math.hypot(self.context.devices[d.id].yaw_deg - previous_states[d.id].yaw_deg,
                                    self.context.devices[d.id].pitch_deg - previous_states[d.id].pitch_deg)
                          / (d.max_slew_dps * self.dt) for d in self.device_configs])
        penalty = float(self.cfg.policy.get("learning_motion_penalty", .02)) * float(motion)
        reward = coverage + .25 * accuracy - penalty
        return float(reward), {"reward_coverage": coverage, "reward_accuracy": accuracy,
                               "reward_motion_penalty": penalty}

    def step(self, action):
        if self._world is None:
            raise RuntimeError("必须先调用 reset()")
        if self._finished:
            raise RuntimeError("本回合已经结束，请调用 reset()")
        previous = self.context.devices
        actions = self.decode_action(action)
        self._world.advance(actions, self.dt)
        self._step += 1
        self._sense()
        reward, parts = self._reward(previous)
        terminated = False
        truncated = self._step >= self.max_steps
        self._finished = terminated or truncated
        observation = self._observation()
        info = {"time_s": self.context.t, "step": self._step,
                "estimated_track_count": len(self.context.tracks),
                "localization_count": len(self._last_localizations),
                "observation_clipped_features": self._clipped_feature_count, **parts}
        return observation, reward, terminated, truncated, info

    def render(self):
        if self.render_mode == "ansi":
            return f"t={self.context.t:.2f}s step={self._step} detections={len(self.context.detections)} tracks={len(self.context.tracks)}"
        return None

    def close(self):
        # 仿真环境没有网络、摄像头或文件句柄，保留标准接口方便 vector env。
        self._world = None
        self._context = None


# 简短别名方便 notebook；不自动注册全局环境，避免导入副作用。
ZR10Env = CooperativeObservationEnv

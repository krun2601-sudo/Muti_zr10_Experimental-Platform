"""总控中心的模式注册表与可替换算法入口。

界面只负责传递模式 ID，算法仍接收标准 PolicyContext、返回 Decision。
本模块不连接设备，也不依赖 GUI；新增模式不必修改界面的按钮和分支。
自定义算法的构造函数接收 LabConfig，并实现 reset()/decide(context)。
"""
from __future__ import annotations

import copy
import importlib
import math
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np

from .config import LabConfig
from .geometry import intrinsics_at_zoom, pixel_to_world_ray, world_to_gimbal_angles
from .models import Action, Decision, Detection, PolicyContext
from .policies import CooperativePolicy, HoldPolicy, Policy, ScanPolicy


_BUILTINS = {
    "manual": dict(label="手动控制", description="通过设备控制面板发出动作，自动算法保持空动作。", requires_detection=False, requires_calibration=False),
    "hold": dict(label="保持观测", description="保持当前指向，继续记录与处理已启用的观测。", requires_detection=False, requires_calibration=False),
    "localize": dict(label="固定姿态定位", description="保持各站当前指向，启用检测与多站定位，用于静态已知目标的标定和误差验证。", requires_detection=True, requires_calibration=True),
    "scan": dict(label="区域覆盖扫描", description="按照空间扫描点组织设备共同扫描，发现目标后继续扫描。", requires_detection=False, requires_calibration=True),
    "track": dict(label="单站图像跟踪", description="每台相机独立居中跟踪；不要求多站外参，但需正确内参、角度方向及已知稳定倍率。", requires_detection=True, requires_calibration=False),
    "center": dict(label="中心跟踪定位", description="为目标安排多站中心观测，每台相机中心跟踪一个目标，持续形成定位条件。", requires_detection=True, requires_calibration=True),
    "multi": dict(label="多目标协同定位", description="分配多站共同视场，同时覆盖和定位多个目标。", requires_detection=True, requires_calibration=True),
}
_MODE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_POLICY_PATH = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*$")


def _registry(cfg: LabConfig) -> dict[str, dict[str, Any]]:
    """只校验/展开配置，不导入用户插件，不在列出模式时执行用户算法。"""
    registry = {key: {"id": key, **copy.deepcopy(value), "settings": {}} for key, value in _BUILTINS.items()}
    center = getattr(cfg, "control_center", {})
    if not isinstance(center, dict):
        raise ValueError("control_center 必须是映射")
    rows = center.get("modes", [])
    if not isinstance(rows, list):
        raise ValueError("control_center.modes 必须是列表")
    # 兼容原CLI策略配置：开启界面不应把既有自定义算法替换成manual或multi。
    # 原build_policy的custom、class_path优先级保持一致；entrypoint是兼容别名。
    # 自定义构造器稍后仍接收整个cfg.policy，原算法参数不会被重写。
    legacy_name = str(cfg.policy.get("name", cfg.policy.get("type", "cooperative")))
    legacy_path = None
    if legacy_name == "custom":
        legacy_path = cfg.policy.get("custom", cfg.policy.get("class_path", cfg.policy.get("entrypoint")))
        explicit_custom = any(isinstance(row, dict) and row.get("id") == "custom" and row.get("policy") for row in rows)
        if legacy_path is None and not explicit_custom:
            raise ValueError("旧custom策略需配置 policy.custom、class_path 或 entrypoint: module:Class")
    elif ":" in legacy_name:
        legacy_path = legacy_name
    if legacy_path is not None:
        if not isinstance(legacy_path, str) or not _POLICY_PATH.fullmatch(legacy_path):
            raise ValueError("旧自定义策略入口必须为 module:Class")
        registry["custom"] = dict(id="custom", label="既有自定义算法", description="沿用原policy配置中的算法入口与参数。",
                                  settings={}, policy=legacy_path, requires_detection=True, requires_calibration=True)
    seen = set()
    allowed = {"id", "label", "description", "policy", "settings", "requires_detection", "requires_calibration"}
    for row in rows:
        if not isinstance(row, dict) or set(row) - allowed:
            raise ValueError("每个模式必须是映射，且只能包含 id/label/description/policy/settings/requires_detection/requires_calibration")
        key = row.get("id")
        if not isinstance(key, str) or not _MODE_ID.fullmatch(key) or key in seen:
            raise ValueError(f"模式 ID 无效或重复: {key!r}")
        seen.add(key)
        custom = key not in registry
        if custom and "policy" not in row:
            raise ValueError(f"新模式 {key!r} 必须显式指定 policy: module:Class")
        if "policy" in row and (not isinstance(row["policy"], str) or not _POLICY_PATH.fullmatch(row["policy"])):
            raise ValueError(f"模式 {key!r} 的 policy 必须为 module:Class")
        if not isinstance(row.get("settings", {}), dict):
            raise ValueError(f"模式 {key!r} 的 settings 必须是映射")
        for field in ("requires_detection", "requires_calibration"):
            if field in row and type(row[field]) is not bool:
                raise ValueError(f"模式 {key!r} 的 {field} 必须是布尔值")
        for field in ("label", "description"):
            if field in row and (not isinstance(row[field], str) or not row[field].strip()):
                raise ValueError(f"模式 {key!r} 的 {field} 必须是非空文本")
        base = registry.get(key, dict(id=key, label=key, description="本地自定义算法", settings={},
                                      requires_detection=True, requires_calibration=True))
        registry[key] = {**base, **copy.deepcopy(row)}
    return registry


def mode_catalog(cfg: LabConfig) -> list[dict[str, Any]]:
    """返回可以直接序列化给界面的模式列表；未知模式绝不退回到其他算法。"""
    return list(_registry(cfg).values())


def _merge(target: dict, updates: dict) -> None:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def _load_module(name: str, reload: bool):
    """重载入口源文件，包括同一秒内、同文件大小的修改。

    Python 的默认 pyc 可能只比较整秒修改时间和大小。显式重载时删除的
    仅是入口源文件对应的派生字节码缓存，不修改任何用户算法源文件。
    """
    if reload:
        importlib.invalidate_caches()
    was_loaded = name in sys.modules
    module = importlib.import_module(name)
    if reload and was_loaded:
        source = getattr(module, "__file__", "")
        if source and source.endswith(".py"):
            cached = Path(importlib.util.cache_from_source(source))
            try:
                cached.unlink(missing_ok=True)
            except OSError as exc:
                # 无法刷新就明确报错，不能向用户声称已运行修改后的算法。
                raise RuntimeError(f"不能刷新策略入口字节码缓存 {cached}: {exc}") from exc
        module = importlib.reload(module)
    return module


def create_mode_policy(cfg: LabConfig, mode_id: str, reload: bool = False) -> Policy:
    """创建独立策略实例，不污染当前配置；新会话和明确重载应传reload=True。

    settings 合并到副本的 cfg.policy，自定义插件仍然只需要一个 cfg 参数。
    reload=True 会刷新导入缓存并重载入口模块；插件依赖模块的重载由插件
    自己管理。运行中的实例不被原地修改，调用方应先停旧动作再原子切换。
    """
    registry = _registry(cfg)
    if not isinstance(mode_id, str) or mode_id not in registry:
        raise ValueError(f"未知控制模式 {mode_id!r}；可选项: {', '.join(registry)}")
    entry = registry[mode_id]
    local = copy.deepcopy(cfg)
    _merge(local.policy, entry["settings"])
    local.policy["control_mode"] = mode_id
    if "policy" in entry:
        module_name, class_name = entry["policy"].split(":")
        module = _load_module(module_name, reload)
        factory = getattr(module, class_name, None)
        if not callable(factory):
            raise TypeError(f"策略入口 {entry['policy']} 不存在或不可调用")
        instance = factory(local)
    else:
        if mode_id in ("manual", "hold", "localize"):
            local.policy["name"] = "hold"
            instance = _load_module("zr10lab.policies", reload).HoldPolicy(local)
        elif mode_id == "scan":
            local.policy["name"] = "scan"
            instance = _load_module("zr10lab.policies", reload).ScanPolicy(local)
        elif mode_id == "track":
            local.policy["name"] = "track"
            instance = _load_module(__name__, reload).ImageCenterTrackPolicy(local)
        else:
            local.policy.update(name="cooperative", mode=mode_id)
            instance = _load_module("zr10lab.policies", reload).CooperativePolicy(local)
    if not callable(getattr(instance, "reset", None)) or not callable(getattr(instance, "decide", None)):
        raise TypeError("模式算法必须实现 reset() 和 decide(context)")
    instance.reset()
    return instance


class ImageCenterTrackPolicy(HoldPolicy):
    """单站图像闭环基线：去畸变射线 → 世界方向 → 云台完整角度逆解。

    不读取空间轨迹或仿真真值，不要求第二站发现目标。目标连续性使用本机
    世界射线最近邻门限，因此能补偿云台自己的转动。这里是方向关联基线，
    相交/遮挡时不能保证身份；需要更强关联时可替换为外观/视觉跟踪算法。
    Detection.local_id 仅为本帧编号，不能被误当作跨帧身份。
    """

    def __init__(self, cfg: LabConfig):
        super().__init__(cfg)
        self.max_age = float(cfg.policy.get("track_detection_max_age_s", cfg.system.get("max_frame_age_s", .6)))
        self.keep_s = float(cfg.policy.get("track_memory_s", 1.0))
        self.gate_deg = float(cfg.policy.get("track_association_gate_deg", 8.0))
        self.min_confidence = float(cfg.policy.get("track_min_confidence", .25))
        self.ttl = float(cfg.system.get("action_ttl_s", .5))
        if not all(math.isfinite(v) and v > 0 for v in (self.max_age, self.keep_s, self.gate_deg, self.ttl)) or self.gate_deg > 180:
            raise ValueError("跟踪的时效、记忆时长、关联角门限和动作租约必须为正，角门限不大于 180°")
        if not math.isfinite(self.min_confidence) or not 0 <= self.min_confidence <= 1:
            raise ValueError("track_min_confidence 必须在 0..1")
        # 初次选择规则不暗示持久身份。默认置信度最高；也可优先图像中心。
        self.selection = cfg.policy.get("track_selection", "confidence")
        if self.selection not in ("confidence", "nearest_center"):
            raise ValueError("track_selection 只支持 confidence / nearest_center")
        if cfg.policy.get("track_lost_behavior", "hold") != "hold":
            raise ValueError("内置图像跟踪丢失目标时仅支持 hold；搜索行为请注册自定义策略")
        self.reset()

    def reset(self) -> None:
        self._memory: dict[str, tuple[np.ndarray, int, float]] = {}

    def _ray(self, detection: Detection, context: PolicyContext) -> np.ndarray:
        # runtime 中的 rays 已用曝光时刻插值姿态计算，优先使用这一时间对齐结果。
        for ray in context.rays:
            if ray.device_id == detection.device_id and ray.detection_id == detection.key and abs(ray.t - detection.t) < 1e-6:
                vector = np.asarray(ray.direction, dtype=float)
                if vector.shape != (3,) or not np.isfinite(vector).all() or np.linalg.norm(vector) < 1e-9:
                    raise ValueError("无效观测射线")
                return vector / np.linalg.norm(vector)
        # 无射线时只在 geometry 允许的姿态/检测时差内转换，不把新姿态强套给旧视频。
        ray = pixel_to_world_ray(detection, context.devices[detection.device_id], self.devices[detection.device_id])
        return np.asarray(ray.direction, dtype=float)

    def decide(self, context: PolicyContext) -> Decision:
        available = set(self._available_ids(context))
        actions = {key: Action(key, issued_t=context.t, ttl_s=self.ttl, reason="track_no_detection") for key in self.devices}
        diagnostics: dict[str, Any] = {"mode": "track", "targets": {}, "rejections": {}, "identity_method": "single_camera_direction_nearest_neighbor"}
        for key, device in self.devices.items():
            state = context.devices.get(key)
            if key not in available:
                diagnostics["rejections"][key] = "unavailable_or_stale"
                continue
            simulated = state.source == "simulation"
            # 单站居中不依赖世界坐标外参：同一 mount 的正变换与逆变换会抵消。
            # 但真实相机倍率必须已知且稳定；内参与角度方向仍由实验者验证。
            if not simulated and (not state.raw.get("zoom_known", False) or not state.raw.get("zoom_stable", False)):
                diagnostics["rejections"][key] = "unknown_or_unstable_zoom"
                continue
            detections = [d for d in context.detections if d.device_id == key and
                          0 <= context.t - d.t <= self.max_age and d.confidence >= self.min_confidence]
            # 不将积压的旧帧重复作为新观测；同一周期只从最新曝光帧选择。
            if detections:
                newest = max(d.t for d in detections)
                detections = [d for d in detections if abs(d.t - newest) < 1e-6]
            candidates = []
            for detection in detections:
                try:
                    direction = self._ray(detection, context)
                    candidates.append((detection, direction))
                except (ValueError, TypeError, KeyError) as exc:
                    diagnostics["rejections"][key] = str(exc)
            previous = self._memory.get(key)
            if previous and 0 <= context.t - previous[2] <= self.keep_s:
                choices = [(math.degrees(math.acos(float(np.clip(direction @ previous[0], -1, 1)))), det, direction)
                           for det, direction in candidates if det.class_id == previous[1]]
                choices = [row for row in choices if row[0] <= self.gate_deg]
                if not choices:
                    diagnostics["rejections"][key] = "target_lost_hold"
                    continue
                _, detection, direction = min(choices, key=lambda row: (row[0], -row[1].confidence, row[1].key))
            else:
                self._memory.pop(key, None)
                if not candidates:
                    continue
                if self.selection == "nearest_center":
                    intrinsics = intrinsics_at_zoom(device, state.zoom)
                    detection, direction = min(candidates, key=lambda pair: (
                        math.hypot((pair[0].center[0] - intrinsics.cx) / intrinsics.fx,
                                   (pair[0].center[1] - intrinsics.cy) / intrinsics.fy), -pair[0].confidence))
                else:
                    detection, direction = min(candidates, key=lambda pair: (-pair[0].confidence, pair[0].key))
            self._memory[key] = (direction, detection.class_id, detection.t)
            yaw, pitch = world_to_gimbal_angles(np.asarray(device.position_m) + direction, device)
            # 只检查实际要控制的轴；被冻结的轴保留当前状态，不伪装为已居中。
            desired = {"yaw_deg": yaw, "pitch_deg": pitch}
            limits = {"yaw_deg": device.yaw_limits_deg, "pitch_deg": device.pitch_limits_deg}
            if any(name in self.enabled and not limits[name][0] <= value <= limits[name][1] for name, value in desired.items()):
                diagnostics["rejections"][key] = "target_outside_gimbal_limits"
                continue
            actions[key] = Action(key, yaw_deg=yaw if "yaw_deg" in self.enabled else None,
                                  pitch_deg=pitch if "pitch_deg" in self.enabled else None,
                                  # 此 ID 是观测 ID，不是假定已获得空间 Track ID。
                                  target_ids=(detection.key,), reason="image_center_track", issued_t=context.t, ttl_s=self.ttl)
            diagnostics["targets"][key] = {"detection_id": detection.key, "target_direction": direction.tolist(),
                                            "center_axes_enabled": all(name in self.enabled for name in desired),
                                            "is_localization": False}
        return Decision(actions, diagnostics)

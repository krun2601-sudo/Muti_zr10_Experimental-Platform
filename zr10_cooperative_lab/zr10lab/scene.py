"""由遥测/标定构造可视化场景，不把指令值或显示距离伪装成测量。

坐标沿用全项目 ENU（东、北、上），前端应设置 z 轴向上。矩形图像对应
四棱锥；有畸变时另外采样图像边界，得到更准确的视场边缘。截断深度仅
为绘图参数，不能代表能识别无人机的距离或无遮挡的有效观测空间。
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from .config import DeviceConfig, LabConfig
from .geometry import camera_rotation, intrinsics_at_zoom, pixel_to_camera_ray
from .models import Telemetry, Track


def _numbers(values) -> list[float]:
    values = np.asarray(values, dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("场景数据包含非有限数值")
    return values.tolist()


def _focal_length(device: DeviceConfig, zoom: float) -> float | None:
    """只能由实测焦距表推导毫米值，不能把 fx 像素或倍率误写成毫米。"""
    rows = device.camera.get("focal_length_table", [])
    if not rows:
        return None
    try:
        zz = np.asarray([row["zoom"] for row in rows], dtype=float)
        mm = np.asarray([row["focal_length_mm"] for row in rows], dtype=float)
        if not np.isfinite(zz).all() or not np.isfinite(mm).all() or np.any(mm <= 0) or np.any(np.diff(zz) <= 0) or not zz[0] <= zoom <= zz[-1]:
            return None
        return float(np.interp(zoom, zz, mm))
    except (ValueError, KeyError, TypeError):
        return None


def _frustum(device: DeviceConfig, state: Telemetry, depth: float, preview: bool) -> dict[str, Any]:
    intrinsics = intrinsics_at_zoom(device, state.zoom)
    rotation = camera_rotation(state, device)
    origin = np.asarray(device.position_m, dtype=float)
    # 使用真实像素中心范围 [0,width-1] × [0,height-1]，不是模型输入尺寸。
    pixels = np.asarray([(0, 0), (intrinsics.width - 1, 0),
                         (intrinsics.width - 1, intrinsics.height - 1), (0, intrinsics.height - 1)], dtype=float)

    def endpoint(pixel):
        ray = pixel_to_camera_ray(pixel, intrinsics)
        if not np.isfinite(ray).all() or ray[0] <= 1e-6:
            raise ValueError("图像边缘无法转换为前向射线，请检查畸变标定")
        # 所有角点落在与光轴垂直、轴向距离为 depth 的截断平面上。
        # 不将每条射线都裁成等长，否则四角会落到球面而非四棱锥底面。
        return _numbers(origin + rotation @ (ray * (depth / ray[0])))

    boundary = [endpoint((1 - alpha) * pixels[i] + alpha * pixels[(i + 1) % 4])
                for i in range(4) for alpha in np.linspace(0., 1., 9, endpoint=False)]

    def angular_span(first, second):
        a, b = pixel_to_camera_ray(first, intrinsics), pixel_to_camera_ray(second, intrinsics)
        return float(np.degrees(np.arccos(np.clip(a @ b, -1, 1))))

    return {"origin": _numbers(origin), "center_direction": _numbers(rotation @ [1., 0., 0.]),
            "corners": [endpoint(pixel) for pixel in pixels], "boundary": boundary,
            "range_m": depth, "range_definition": "optical_axis_depth", "range_is_visualization_only": True,
            "hfov_deg": angular_span((0, intrinsics.cy), (intrinsics.width - 1, intrinsics.cy)),
            "vfov_deg": angular_span((intrinsics.cx, 0), (intrinsics.cx, intrinsics.height - 1)),
            "image_size": [intrinsics.width, intrinsics.height], "zoom": float(state.zoom),
            "intrinsics": {"fx": intrinsics.fx, "fy": intrinsics.fy, "cx": intrinsics.cx, "cy": intrinsics.cy},
            "is_preview": preview, "shape": "calibrated_rectangular_camera_frustum"}


def build_scene(cfg: LabConfig, states: dict[str, Telemetry], tracks: list[Track] | tuple[Track, ...],
                now: float, *, range_m: float = 200.0, preview: bool = False) -> dict[str, Any]:
    """生成纯 JSON 数据；失联/过期/未知倍率时只显示站点及原因。

    preview=True 只允许在缺少遥测时使用配置的初始姿态，source 明确标成
    configuration_preview、valid=False，不会把无反馈设备画成有效实机。
    实机标定未验证时始终 valid=False；普通实时模式不绘制其视场。
    """
    if not math.isfinite(now) or not math.isfinite(range_m) or range_m <= 0:
        raise ValueError("场景时间必须有限，显示截断距离必须为有限正数")
    stale_s = float(cfg.system.get("telemetry_stale_s", .5))
    zoom_stale_s = float(cfg.system.get("zoom_stale_s", 2.0))
    points = []
    devices = []
    roi = cfg.policy.get("roi", {"x": [80, 180], "y": [-50, 50], "z": [20, 60]})
    roi = {axis: _numbers(roi[axis]) for axis in ("x", "y", "z")}
    if any(len(values) != 2 or values[0] >= values[1] for values in roi.values()):
        raise ValueError("区域 roi 需要 x/y/z 三个递增的有限范围")
    for x in roi["x"]:
        for y in roi["y"]:
            for z in roi["z"]:
                points.append([x, y, z])
    for device in cfg.devices:
        position = _numbers(device.position_m)
        points.append(position)
        state = states.get(device.id)
        is_preview = bool(preview and state is None and device.enabled)
        if is_preview:
            state = Telemetry(device.id, now, device.initial_yaw_deg, device.initial_pitch_deg,
                              zoom=device.initial_zoom, connected=False, source="configuration_preview")
        item: dict[str, Any] = dict(id=device.id, position_m=position, enabled=device.enabled,
            connected=bool(state and state.connected), source=state.source if state else "unavailable",
            valid=False, reason="unavailable", calibration_verified=bool(device.calibration_verified),
            frustum=None, focal_length_mm=None, focal_length_source="unknown", is_preview=is_preview)
        devices.append(item)
        if not device.enabled:
            item["reason"] = "disabled"
            continue
        if state is None:
            continue
        item["age_s"] = float(now - state.t) if math.isfinite(state.t) else None
        if not is_preview:
            if state.device_id != device.id:
                item["reason"] = "device_id_mismatch"
                continue
            if not state.connected:
                item["reason"] = "offline"
                continue
            if not math.isfinite(state.t) or not 0 <= now - state.t <= stale_s:
                item.update(reason="telemetry_stale", connected=False)
                continue
            simulated = state.source == "simulation"
            if not simulated and not device.calibration_verified:
                item["reason"] = "calibration_unverified"
                continue
            if not state.raw.get("zoom_known", simulated):
                item["reason"] = "zoom_unknown"
                continue
            if not state.raw.get("zoom_stable", simulated):
                item["reason"] = "zoom_unstable"
                continue
            zoom_t = state.raw.get("zoom_t")
            if zoom_t is not None and (not isinstance(zoom_t, (int, float)) or not math.isfinite(zoom_t) or not 0 <= now - zoom_t <= zoom_stale_s):
                item["reason"] = "zoom_stale"
                continue
        try:
            item["frustum"] = _frustum(device, state, float(range_m), is_preview)
            item["valid"] = not is_preview
            item["reason"] = "configuration_preview" if is_preview else "simulation" if state.source == "simulation" else "measured_pose_calibrated_intrinsics"
            item["focal_length_mm"] = _focal_length(device, state.zoom)
            if item["focal_length_mm"] is not None:
                item["focal_length_source"] = "calibration_table_interpolation"
            item.update(yaw_deg=float(state.yaw_deg), pitch_deg=float(state.pitch_deg), roll_deg=float(state.roll_deg), zoom=float(state.zoom))
            points.extend(item["frustum"]["boundary"])
        except (ValueError, KeyError, TypeError) as exc:
            item.update(valid=False, frustum=None, reason=f"invalid_geometry: {exc}")
    track_rows = []
    track_ttl = float(cfg.policy.get("coast_timeout_s", 2.0))
    known_devices = {device.id: device for device in cfg.devices}
    hardware_data = any(state.source not in ("simulation", "configuration_preview", "unavailable") for state in states.values())
    for track in tracks:
        try:
            position, velocity = _numbers(track.position), _numbers(track.velocity)
            if len(position) != 3 or len(velocity) != 3:
                continue
            times = _numbers([track.t, track.last_seen_t])
            valid = 0 <= now - times[1] <= track_ttl
            reason = "fresh_estimate" if valid else "track_stale"
            # 防御性校验：单站图像跟踪可不验证世界外参，但这不能变成一个
            # 可展示的世界定位结果。正常运行器已在融合入口过滤未标定站。
            invalid_measurement = track.measured and (len(set(track.device_ids)) < 2 or any(
                key not in known_devices or not known_devices[key].calibration_verified for key in track.device_ids))
            # coasting 时 device_ids 通常为空，意思是本周期没有新观测；仍可
            # 显示此前已验证融合链路产生的预测，但不可称为正在双站测量。
            invalid_prediction = not track.measured and sum(d.calibration_verified for d in cfg.active_devices) < 2
            if hardware_data and (invalid_measurement or invalid_prediction):
                valid, reason = False, "unverified_localization_stations"
            row = dict(track_id=track.track_id, position_m=position, velocity_mps=velocity,
                       t=times[0], last_seen_t=times[1], measured=bool(track.measured), status=track.status,
                       device_ids=list(track.device_ids), class_id=track.class_id, valid=valid,
                       source="localization_update" if track.measured else "prediction", age_s=now - times[1], reason=reason)
            track_rows.append(row)
            if valid:
                points.append(position)
        except (ValueError, TypeError):
            continue
    array = np.asarray(points, dtype=float)
    low, high = np.min(array, axis=0), np.max(array, axis=0)
    padding = np.maximum((high - low) * .06, 1.)
    low, high = low - padding, high + padding
    return {"coordinate_system": "ENU", "up_axis": "z", "time": float(now), "roi": roi,
            "bounds": {"min": low.tolist(), "max": high.tolist(),
                       **{axis: [float(low[i]), float(high[i])] for i, axis in enumerate(("x", "y", "z"))}},
            "devices": devices, "tracks": track_rows, "range_m": float(range_m),
            "range_is_visualization_only": True, "preview": bool(preview)}

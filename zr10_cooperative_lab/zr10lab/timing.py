"""帧时刻的遥测插值。接收时刻估计不等于硬件曝光同步。"""
from __future__ import annotations

from dataclasses import replace
from .models import Telemetry


def interpolate_telemetry(history: tuple[Telemetry, ...] | list[Telemetry], t: float,
                          max_gap_s: float = 0.15) -> Telemetry:
    if not history:
        raise ValueError("没有姿态历史")
    def stable(sample):
        if not sample.connected or sample.raw.get("zoom_known") is False or sample.raw.get("zoom_stable") is False:
            raise ValueError("姿态不可用或曝光时处于变焦过渡")
    samples = sorted(history, key=lambda s: s.t)
    if t < samples[0].t or t > samples[-1].t:
        nearest = min(samples, key=lambda s: abs(s.t - t))
        if abs(nearest.t - t) > max_gap_s:
            raise ValueError("图像时刻超出姿态历史有效范围")
        stable(nearest)
        return replace(nearest, t=t, source="nearest_estimate",
                       raw={**nearest.raw, "pose_time_error_s": abs(nearest.t - t)})
    for a, b in zip(samples, samples[1:]):
        if a.t <= t <= b.t:
            stable(a); stable(b)
            if b.t - a.t > max_gap_s:
                raise ValueError("相邻姿态样本间隔过大")
            # 连续变焦或跳变时，镜头模型不能假定已经到位。
            if abs(b.zoom - a.zoom) > 0.02:
                raise ValueError("曝光时刻处于变焦过渡，暂停定位")
            alpha = (t - a.t) / max(b.t - a.t, 1e-12)
            def blend(x: float, y: float) -> float:
                return x + alpha * (y - x)
            # 本设备不是连续360度云台，限位内直接插值，禁止走跨端点捷径。
            return replace(a, t=t, yaw_deg=blend(a.yaw_deg,b.yaw_deg),
                           pitch_deg=blend(a.pitch_deg,b.pitch_deg),
                           roll_deg=blend(a.roll_deg,b.roll_deg),
                           yaw_rate_dps=blend(a.yaw_rate_dps,b.yaw_rate_dps),
                           pitch_rate_dps=blend(a.pitch_rate_dps,b.pitch_rate_dps),
                           source="interpolated", raw={**a.raw, "pose_time_error_s": b.t-a.t})
    return replace(samples[-1], t=t)

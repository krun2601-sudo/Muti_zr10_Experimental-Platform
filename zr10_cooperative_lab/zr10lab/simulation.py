"""可复现的设备/目标/检测仿真；真值与算法观测严格分开。

这是几何与调度实验仿真器，不是光学成像/空气动力学数字孪生。
包含机械转动速度限制、视场遮挡、检测概率和像素噪声；目标身份不进入检测。
"""
from __future__ import annotations

from dataclasses import replace
import math
import numpy as np

from .actions import ActionValidator
from .config import LabConfig
from .geometry import project_world_point
from .models import Action, Detection, Telemetry


class SimulationWorld:
    def __init__(self, cfg: LabConfig):
        self.cfg = cfg
        self.validator = ActionValidator(cfg)
        self.reset()

    def reset(self, seed: int | None = None) -> None:
        self.rng = np.random.default_rng(self.cfg.simulation.get("seed", 7) if seed is None else seed)
        self.t = 0.0
        self.frame_id = 0
        self._states = {d.id: Telemetry(d.id, 0, d.initial_yaw_deg, d.initial_pitch_deg,
            zoom=d.initial_zoom, connected=not any(x.get("device_id")==d.id and x["start_s"]<=0<x["end_s"]
                for x in self.cfg.simulation.get("outages",[]))) for d in self.cfg.active_devices}
        self._actions: dict[str, Action] = {}

    def states(self) -> dict[str, Telemetry]:
        return dict(self._states)

    def truth(self) -> dict[str, tuple[float, float, float]]:
        result = {}
        for i, target in enumerate(self.cfg.simulation.get("targets", [])):
            if self.t < target.get("start_s", 0) or self.t > target.get("end_s", math.inf):
                continue
            p = np.asarray(target.get("position_m", [100, 0, 60]), dtype=float)
            velocity = np.asarray(target.get("velocity_mps", [0, 0, 0]), dtype=float)
            p = p + velocity * self.t
            amplitude = np.asarray(target.get("amplitude_m", [0, 0, 0]), dtype=float)
            period = max(float(target.get("period_s", 30)), 0.001)
            # 相位可为标量，也可为[x,y,z]三个值，后者生成椭圆/空间曲线轨迹。
            phase = np.asarray(target.get("phase_rad", 0),dtype=float)
            p = p + amplitude * np.sin(2 * np.pi * self.t / period + phase)
            result[str(target.get("id", f"uav_{i+1}"))] = tuple(float(v) for v in p)
        return result

    def observe(self) -> list[Detection]:
        self.frame_id += 1
        output: list[Detection] = []
        probability = float(self.cfg.simulation.get("detection_probability", .96))
        noise = float(self.cfg.simulation.get("pixel_noise_std", 0.7))
        truth = self.truth()
        for d in self.cfg.active_devices:
            if not self._states[d.id].connected:
                continue
            pixels = []
            for point in truth.values():
                projected = project_world_point(point, self._states[d.id], d)
                if projected is None or self.rng.random() > probability:
                    continue
                u, v = np.asarray(projected) + self.rng.normal(0, noise, 2)
                width, height = d.camera.get("image_size", [1920,1080])
                if 0 <= u < width and 0 <= v < height:
                    pixels.append((float(u), float(v)))
            # 打乱顺序，防止检测列表序号暗中成为跨站点的真值身份。
            self.rng.shuffle(pixels)
            for j, (u,v) in enumerate(pixels):
                w,h = d.camera.get("image_size", [1920,1080])
                output.append(Detection(d.id, self.frame_id, self.t,
                    (max(0,u-5),max(0,v-4),min(w,u+5),min(h,v+4)), .95, 0,
                    str(j), (w,h), self.t, 0.0))
        return output

    def advance(self, actions: dict[str, Action], dt: float) -> None:
        if not math.isfinite(dt) or dt <= 0:
            raise ValueError("仿真步长必须为正数")
        # 先全部校验，再推进，避免一个不合法动作导致半个系统已前进。
        checked = {key:self.validator.resolve(self.validator.validate(a,self._states[key],self.t,dt))
                   for key,a in actions.items()}
        if any("encoding" in action.parameters for action in checked.values()):
            raise ValueError("几何仿真不模拟视频编码切换；该参数仅用于硬件实验")
        self._actions.update(checked)
        new_states = {}
        next_t = self.t + dt
        for d in self.cfg.active_devices:
            s = self._states[d.id]
            a = self._actions.get(d.id)
            offline = any(x.get("device_id") == d.id and x["start_s"] <= next_t < x["end_s"]
                          for x in self.cfg.simulation.get("outages", []))
            yaw,pitch,zoom = s.yaw_deg,s.pitch_deg,s.zoom
            # 在步长内部到期也立即停止；dt较大时不能整步执行过期动作。
            active_dt = max(0,min(dt,a.issued_t+a.ttl_s-self.t)) if a else 0
            for outage in self.cfg.simulation.get("outages",[]):
                if outage.get("device_id") != d.id:
                    continue
                if outage["start_s"] <= self.t < outage["end_s"]:
                    active_dt = 0
                elif self.t < outage["start_s"] < self.t+active_dt:
                    active_dt = outage["start_s"]-self.t
                if self.t < outage["end_s"] and next_t >= outage["start_s"]:
                    self._actions.pop(d.id,None)  # 掉线/重连不重放旧动作。
            raw = dict(s.raw)
            if a and active_dt>0:
                if a.yaw_deg is not None:
                    yaw += float(np.clip(a.yaw_deg-yaw,-d.max_slew_dps*active_dt,d.max_slew_dps*active_dt))
                if a.pitch_deg is not None:
                    pitch += float(np.clip(a.pitch_deg-pitch,-d.max_slew_dps*active_dt,d.max_slew_dps*active_dt))
                speed = float(self.cfg.simulation.get("zoom_rate_per_s",3))
                if a.zoom is not None:
                    zoom += float(np.clip(a.zoom-zoom,-speed*active_dt,speed*active_dt))
                if "zoom_direction" in a.parameters:
                    zoom = float(np.clip(zoom+a.parameters["zoom_direction"]*speed*active_dt,*d.zoom_limits))
                # 其余相机参数保留状态用于策略研究；不把它们伪装成光学成像仿真。
                raw["simulated_camera_parameters"] = {**raw.get("simulated_camera_parameters",{}),**a.parameters}
                raw["camera_effect_model"] = "metadata_only_except_zoom"
            new_states[d.id] = replace(s,t=next_t,yaw_deg=yaw,pitch_deg=pitch,zoom=zoom,
                yaw_rate_dps=(yaw-s.yaw_deg)/dt,pitch_rate_dps=(pitch-s.pitch_deg)/dt,
                connected=not offline,sequence=s.sequence+1,raw=raw)
        self.t = next_t
        self._states = new_states

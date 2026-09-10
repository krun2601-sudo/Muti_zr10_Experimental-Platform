"""运行编排：检测→射线→融合→统一覆盖状态→策略→动作→记录。

覆盖算法从 PolicyContext 读取由 Experiment 维护的 CoverageSnapshot，不能自行维护
另一套覆盖判定。仿真真值仅供既有评估指标使用，永远不进入策略上下文。
"""
from __future__ import annotations
import asyncio
import time
from .actions import ActionValidator
from .coverage import CoverageProblem, CoverageTracker
from .fusion import FusionEngine
from .geometry import pixel_to_world_ray
from .metrics import Metrics
from .models import CoverageSnapshot, PolicyContext
from .policies import build_policy
from .recording import CSVRecorder,dumps
from .simulation import SimulationWorld
from .timing import interpolate_telemetry


class Experiment:
    def __init__(self,cfg,recorder,policy=None):
        self.cfg,self.recorder = cfg,recorder
        self.fusion = FusionEngine(cfg.fusion)
        self.policy = policy if policy is not None else build_policy(cfg)
        self.policy.reset()
        self.metrics = Metrics(cfg)
        self.validator = ActionValidator(cfg)
        self.by_id = {d.id:d for d in cfg.active_devices}
        self.step = 0
        self.latest = {}
        coverage_cfg = cfg.policy.get("coverage", {})
        self.coverage_problem = CoverageProblem(cfg) if coverage_cfg.get("enabled", False) else None
        self.coverage_tracker = CoverageTracker(self.coverage_problem) if self.coverage_problem else None
        algorithm_id = str(cfg.policy.get("algorithm_id", getattr(self.policy, "algorithm_id", cfg.policy.get("name", "unknown"))))
        algorithm_version = str(getattr(self.policy, "algorithm_version", "legacy"))
        metadata = {
            "algorithm_id": algorithm_id,
            "algorithm_version": algorithm_version,
            "scenario_id": cfg.policy.get("scenario_id", coverage_cfg.get("scenario_id", "default")),
            "environment_seed": cfg.simulation.get("seed"),
            "policy_seed": cfg.policy.get("policy_seed"),
            "problem_hash": self.coverage_problem.problem_hash if self.coverage_problem else None,
        }
        if self.coverage_problem:
            metadata["coverage_assumptions"] = {
                "occlusion_model": coverage_cfg.get("occlusion_model", "none"),
                "detection_model": coverage_cfg.get("detection_model", "ideal_geometry"),
                "fixed_zoom": self.coverage_problem.fixed_zoom,
                "open_path": self.coverage_problem.open_path,
                "required_views": self.coverage_problem.required_views,
            }
        if hasattr(recorder, "set_metadata"):
            recorder.set_metadata(**metadata)

    @property
    def coverage_enabled(self):
        return self.coverage_tracker is not None

    def process(self,t,dt,states,detections,history=None,truth=None,action_transform=None,
                fusion_device_ids=None,coverage_enabled=True):
        begin = time.perf_counter()
        rays,valid_detections = [],[]
        for detection in detections:
            try:
                if not 0 <= t-detection.t <= self.cfg.system.get("max_frame_age_s",.6):
                    raise ValueError("旧帧或未来帧")
                device = self.by_id[detection.device_id]
                current = states[detection.device_id]
                if not current.connected or t-current.t > self.cfg.system.get("telemetry_stale_s",.5):
                    raise ValueError("无新鲜设备姿态")
                state = interpolate_telemetry(history(detection.device_id),detection.t,
                    self.cfg.system.get("pose_max_gap_s",.2)) if history else current
                if state.raw.get("zoom_known") is False or state.raw.get("zoom_stable") is False:
                    raise ValueError("倍率尚未读回确认或仍处于变焦过渡")
                rays.append(pixel_to_world_ray(detection,state,device))
                valid_detections.append(detection)
            except (ValueError,KeyError) as exc:
                self.recorder.event("observation_rejected",{"detection":detection.key,"reason":str(exc)},t)
        fusion_rays = rays if fusion_device_ids is None else [ray for ray in rays if ray.device_id in fusion_device_ids]
        tracks,localizations,diagnostics = self.fusion.update(fusion_rays,t)
        if len(fusion_rays) != len(rays):
            diagnostics["uncalibrated_rays_excluded"] = len(rays)-len(fusion_rays)

        measured_metrics = self.metrics.update(t,states,tracks,truth)
        if not coverage_enabled:
            measured_metrics = {key: (None if key.startswith("roi_") else value) for key,value in measured_metrics.items()}

        coverage_snapshot = CoverageSnapshot()
        if self.coverage_tracker:
            coverage_snapshot = self.coverage_tracker.update(t, states)
            measured_metrics.update(self.coverage_tracker.metrics())
            for record in self.coverage_tracker.new_records:
                x,y,z = record.position_m
                self.recorder.write("coverage_cells",t,cell_id=record.cell_id,x_m=x,y_m=y,z_m=z,
                    first_covered_t_s=record.first_covered_t_s,device_ids_json=dumps(record.device_ids),
                    viewpoint_ids_json=dumps(record.viewpoint_ids),required_views=record.required_views)

        # 真值派生指标禁止泄漏到决策上下文。严格 coverage_* 完全由遥测/已知几何产生，可公开。
        public_metrics = {k:v for k,v in measured_metrics.items()
                          if (k.startswith("roi_") or k.startswith("coverage_")) and v is not None}
        context = PolicyContext(t=t,dt=dt,step=self.step,devices=states,
            detections=tuple(valid_detections),rays=tuple(rays),tracks=tuple(tracks),
            metrics=public_metrics,coverage=coverage_snapshot)
        decision = self.policy.decide(context)
        requested = action_transform(decision.actions) if action_transform else decision.actions
        actions = {}
        for key, action in requested.items():
            try:
                if key != action.device_id:
                    raise ValueError("策略 actions 键与动作 device_id 不一致")
                if not states[key].connected:
                    continue
                actions[key] = self.validator.validate(action,states[key],t,dt)
            except (ValueError,KeyError) as exc:
                self.recorder.event("action_rejected",{"device_id":key,"error":str(exc)},t)
                raise
        self._record(t,states,detections,rays,tracks,localizations,actions,truth)
        elapsed_ms = (time.perf_counter()-begin)*1000
        policy_diag = {**decision.diagnostics,"done":decision.done,
                       "termination_reason":decision.termination_reason}
        self.recorder.write("cycles",t,step=self.step,dt_s=dt,work_ms=elapsed_ms,
            deadline_miss=elapsed_ms>dt*1000,detections=len(detections),rays=len(rays),
            localizations=len(localizations),tracks=len(tracks),measured_tracks=sum(x.measured for x in tracks),
            metrics_json=dumps(measured_metrics),diagnostics_json=dumps({"fusion":diagnostics,"policy":policy_diag}))
        self.latest = {"t":t,"step":self.step,"devices":states,"tracks":tracks,"metrics":measured_metrics,
                       "actions":actions,"detections":detections,"coverage":coverage_snapshot,
                       "done":bool(decision.done),"termination_reason":decision.termination_reason,
                       "diagnostics":{"fusion":diagnostics,"policy":policy_diag}}
        self.step += 1
        return actions

    def _record(self,t,states,detections,rays,tracks,locations,actions,truth):
        r = self.recorder
        for s in states.values():
            r.write("telemetry",t,device_id=s.device_id,sample_t=s.t,yaw_deg=s.yaw_deg,pitch_deg=s.pitch_deg,
                roll_deg=s.roll_deg,zoom=s.zoom,yaw_rate_dps=s.yaw_rate_dps,pitch_rate_dps=s.pitch_rate_dps,
                connected=s.connected,sequence=s.sequence,source=s.source,age_s=t-s.t,raw_json=dumps(s.raw))
        for d in detections:
            x1,y1,x2,y2 = d.bbox_xyxy
            r.write("detections",t,device_id=d.device_id,frame_id=d.frame_id,detection_id=d.key,
                capture_t=d.t,received_t=d.received_t,time_uncertainty_s=d.time_uncertainty_s,class_id=d.class_id,
                confidence=d.confidence,x1=x1,y1=y1,x2=x2,y2=y2,width=d.image_size[0],height=d.image_size[1])
        for ray in rays:
            ox,oy,oz = ray.origin; dx,dy,dz = ray.direction
            r.write("rays",t,device_id=ray.device_id,detection_id=ray.detection_id,capture_t=ray.t,
                ox=ox,oy=oy,oz=oz,dx=dx,dy=dy,dz=dz,angular_std_deg=ray.angular_std_deg,confidence=ray.confidence,
                class_id=ray.class_id,time_uncertainty_s=ray.time_uncertainty_s,embedding_json=dumps(ray.embedding))
        for i,l in enumerate(locations):
            x,y,z = l.position
            r.write("localizations",t,localization_id=f"{self.step}:{i}",measurement_t=l.t,x_m=x,y_m=y,z_m=z,
                device_ids_json=dumps(l.device_ids),detection_ids_json=dumps(l.detection_ids),residual_m=l.residual_m,
                min_angle_deg=l.min_angle_deg,condition_number=l.condition_number,time_span_s=l.time_span_s,
                covariance_json=dumps(l.covariance))
        for tr in tracks:
            x,y,z = tr.position; vx,vy,vz = tr.velocity
            r.write("tracks",t,track_id=tr.track_id,estimate_t=tr.t,x_m=x,y_m=y,z_m=z,vx_mps=vx,vy_mps=vy,vz_mps=vz,
                last_seen_t=tr.last_seen_t,hits=tr.hits,status=tr.status,measured=tr.measured,
                device_ids_json=dumps(tr.device_ids),covariance_json=dumps(tr.covariance))
        for a in actions.values():
            r.write("actions",t,device_id=a.device_id,issued_t=a.issued_t,ttl_s=a.ttl_s,yaw_deg=a.yaw_deg,
                pitch_deg=a.pitch_deg,zoom=a.zoom,target_ids_json=dumps(a.target_ids),reason=a.reason,parameters_json=dumps(a.parameters))
        if truth:
            for key,(x,y,z) in truth.items():
                r.write("truth",t,truth_id=key,x_m=x,y_m=y,z_m=z)


def run_simulation(cfg,output=None,realtime=False,progress=None):
    world = SimulationWorld(cfg)
    recorder = CSVRecorder(output or cfg.logging.get("root","runs"),cfg.to_dict(),"sim")
    dt = 1/float(cfg.system.get("rate_hz",10))
    steps = int(round(float(cfg.system.get("duration_s",60))/dt))
    completed = False
    reason = "duration_elapsed"
    try:
        experiment = Experiment(cfg,recorder)
        for _ in range(steps):
            begin = time.perf_counter()
            actions = experiment.process(world.t,dt,world.states(),world.observe(),truth=world.truth())
            if progress:
                progress(experiment.latest)
            if experiment.latest.get("done"):
                completed = True
                reason = experiment.latest.get("termination_reason") or "policy_done"
                break
            world.advance(actions,dt)
            if realtime:
                time.sleep(max(0,dt-(time.perf_counter()-begin)))
        if not experiment.coverage_enabled:
            completed = True
        recorder.set_metadata(termination_reason=reason,
            coverage_completion_time_s=(experiment.coverage_tracker.completion_time_s if experiment.coverage_tracker else None))
    finally:
        recorder.close(completed)
    return recorder.path


async def run_hardware(cfg,output=None,armed=False,progress=None):
    if not armed:
        raise ValueError("实机闭环需要 --arm；先运行 probe 和完成标定")
    coverage_mode = bool(cfg.policy.get("coverage", {}).get("enabled", False))
    if len(cfg.active_devices) < (1 if coverage_mode else 2):
        raise ValueError("覆盖模式至少需要一台启用设备；协同定位模式至少需要两台")
    missing = [d.id for d in cfg.active_devices if not d.calibration_verified]
    if missing:
        raise ValueError(f"以下站点尚未完成实测标定: {missing}；填写标定值后设置 calibration_verified: true")
    from .hardware import HardwareFleet
    from .vision import VisionPipeline
    start = time.monotonic()
    recorder = CSVRecorder(output or cfg.logging.get("root","runs"),cfg.to_dict(),"hardware",start)
    def result_sink(result):
        recorder.write("commands",result.t,device_id=result.device_id,command_t=result.t,status=result.status,
            sent=result.sent,ack=result.ack,latency_ms=result.latency_ms,applied_json=dumps(result.applied),
            error=result.error,action_json=dumps(result.action))
    def telemetry_sink(s):
        recorder.write("telemetry_stream",s.t,device_id=s.device_id,sample_t=s.t,yaw_deg=s.yaw_deg,
            pitch_deg=s.pitch_deg,roll_deg=s.roll_deg,zoom=s.zoom,yaw_rate_dps=s.yaw_rate_dps,
            pitch_rate_dps=s.pitch_rate_dps,connected=s.connected,sequence=s.sequence,source=s.source,
            age_s=0,raw_json=dumps(s.raw))
    fleet = HardwareFleet(cfg,event_sink=recorder.event,result_sink=result_sink,telemetry_sink=telemetry_sink)
    vision = VisionPipeline(cfg,event_sink=recorder.event)
    completed = False
    reason = "duration_elapsed"
    dt = 1/float(cfg.system.get("rate_hz",10))
    experiment = None
    try:
        experiment = Experiment(cfg,recorder)
        await vision.start(); await fleet.start()
        startup_end = time.monotonic()+float(cfg.system.get("startup_timeout_s",8))
        required = len(cfg.active_devices) if cfg.system.get("require_all_devices",True) else (1 if coverage_mode else 2)
        while sum(s.connected for s in fleet.states().values()) < required:
            if time.monotonic()>startup_end:
                raise RuntimeError("启动时未连接到要求数量的设备，请先运行 probe 检查网络与 SDK")
            await asyncio.sleep(.05)
        deadline = time.monotonic(); end = deadline+float(cfg.system.get("duration_s",60))
        while time.monotonic()<end:
            now = time.monotonic()
            histories = {d.id:fleet.history(d.id) for d in cfg.active_devices}
            actions = await asyncio.to_thread(experiment.process,now,dt,fleet.states(),vision.collect(),histories.get)
            if progress:
                progress(experiment.latest)
            if experiment.latest.get("done"):
                completed = True
                reason = experiment.latest.get("termination_reason") or "policy_done"
                break
            fleet.submit(actions)
            recorder.check()
            deadline += dt
            if deadline < time.monotonic():
                recorder.event("deadline_overrun",{"late_s":time.monotonic()-deadline})
                deadline = time.monotonic()
            await asyncio.sleep(max(0,deadline-time.monotonic()))
        if not experiment.coverage_enabled:
            completed = True
        recorder.set_metadata(termination_reason=reason,
            coverage_completion_time_s=(experiment.coverage_tracker.completion_time_s if experiment.coverage_tracker else None))
    finally:
        errors = await asyncio.gather(fleet.close(),vision.close(),return_exceptions=True)
        for error in errors:
            if isinstance(error,BaseException):
                completed = False
                recorder.event("shutdown_error",{"error":repr(error)})
        recorder.close(completed)
        if any(isinstance(e,BaseException) for e in errors):
            raise RuntimeError("实机关闭未全部成功，详见 events.csv")
    return recorder.path

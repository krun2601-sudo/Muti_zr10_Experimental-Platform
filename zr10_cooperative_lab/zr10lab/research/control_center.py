from __future__ import annotations

import asyncio
import contextlib
import copy
from dataclasses import replace
import time

from ..control_center import ControlCenter, _PolicyWorker, _SessionRecorder
from ..models import CommandResult
from ..recording import CSVRecorder, jsonable
from ..simulation import SimulationWorld
from .mission import SearchMonitorMission
from .runtime import ResearchExperiment


class ResearchControlCenter(ControlCenter):
    """Control-center backend for the virtual search/monitor mission.

    `mirror` keeps the virtual world authoritative and sends exactly the same
    A/E/Zoom actions to the physical HardwareFleet. Real RTSP/detections never
    enter the paper task loop in this mode.

    The stock browser UI only knows ``sim`` and ``hardware``.  A mirror session is
    therefore *locked* when this backend is constructed with
    ``environment='mirror', armed=True``.  The browser continues to display the
    virtual/simulation task world; any subsequent UI ``sim`` start is mapped back
    to the already armed mirror backend.  This avoids invasive edits to the stable
    UI and, more importantly, prevents a page click from silently arming hardware.
    """

    def __init__(self, cfg, *, environment="sim", armed=False, output=None):
        if environment == "mirror" and armed is not True:
            raise ValueError("mirror 会驱动真实 ZR10，启动研究控制中心时必须显式 --arm")
        self._mirror_locked = environment == "mirror"
        super().__init__(cfg, environment=environment, armed=armed, output=output)

    @staticmethod
    def _environment(value):
        if value not in ("sim", "mirror", "hardware"):
            raise ValueError("environment 只能为 sim / mirror / hardware")
        return value

    def snapshot(self):
        snap = super().snapshot()
        if self._mirror_locked:
            # The browser intentionally sees the virtual task environment.  The
            # additional explicit flags remain available to diagnostics/tests.
            snap["research_environment"] = "mirror"
            snap["mirror_hardware"] = True
            snap["environment"] = "sim"
            snap["armed"] = True
        return snap

    async def _operation(self, action, payload):
        if action == "start" and self._mirror_locked:
            request = copy.deepcopy(payload)
            requested = request.get("environment", "sim") or "sim"
            if requested not in ("sim", "mirror"):
                raise ValueError("mirror 研究控制中心不能切换到真实视频 hardware 任务；请另启标准控制中心")
            # Only a process that was itself launched with mirror+--arm can reach
            # this path.  The browser can neither create nor revoke that authority.
            request["environment"] = "mirror"
            request["armed"] = True
            return await super()._operation(action, request)
        if action == "start":
            requested_environment = self._environment(payload.get("environment", self.environment) or self.environment)
            requested_armed = payload.get("armed", self.armed)
            if requested_environment == "mirror" and requested_armed is not True:
                raise ValueError("mirror 会驱动真实 ZR10，必须明确启用 armed")
        return await super()._operation(action, payload)

    async def _update_vision(self):
        if self.environment == "mirror":
            if self._vision is not None:
                vision, self._vision = self._vision, None
                await vision.close()
            return
        await super()._update_vision()

    def _current_states(self):
        if self.environment == "mirror" and self._world is not None:
            states = self._world.states()
            return {key: replace(s, connected=False) if key in self._disconnected else s
                    for key, s in states.items()}
        return super()._current_states()

    def _require_motion(self):
        super()._require_motion()
        if self.environment == "mirror" and not self.armed:
            raise ValueError("mirror 实机镜像尚未 armed")

    async def _run_session(self):
        if self.environment == "hardware" or not SearchMonitorMission.enabled(self.cfg):
            return await super()._run_session()

        recorder = gate = worker = None
        completed = False
        try:
            from ..control_modes import create_mode_policy
            self._world = SimulationWorld(self.cfg)
            mission = SearchMonitorMission(self.cfg)
            recorder = CSVRecorder(self.output or self.cfg.logging.get("root", "runs"),
                                   self.cfg.to_dict(), self.environment, 0.0)
            self._recorder = recorder
            self._session_path = str(recorder.path)
            gate = _SessionRecorder(recorder)
            worker = _PolicyWorker()
            policy = await worker.call(lambda: create_mode_policy(self.cfg, self.mode, reload=True))
            self._experiment = ResearchExperiment(self.cfg, gate, mission, policy=policy)

            if self.environment == "mirror":
                from ..hardware import HardwareFleet
                self._fleet = HardwareFleet(self.cfg, event_sink=self._event,
                                            result_sink=self._result, telemetry_sink=self._telemetry)
                await self._fleet.start()
            self._states = self._current_states()
            if self.status == "starting":
                self.status = "running"
            self._event("research_session_started", {
                "environment": self.environment,
                "mode": self.mode,
                "virtual_truth_authoritative": True,
                "hardware_mirror_only": self.environment == "mirror",
            })
            previous_wall = time.monotonic()
            while True:
                begin = time.monotonic()
                if self.status != "running":
                    previous_wall = begin
                    await asyncio.sleep(.05)
                    continue
                self.elapsed_s += begin - previous_wall
                previous_wall = begin
                if self.duration_s and self.elapsed_s >= self.duration_s:
                    completed = True
                    self.status = "stopped"
                    break
                epoch = self._epoch
                states = self._current_states()
                self._states = states
                t = self._world.t
                mission_step = mission.step(t, self._dt, states)
                manual = dict(self._manual)
                stopped = self._stopped_devices | self._disconnected

                def arbitrate(actions):
                    if epoch != self._epoch or self.status != "running":
                        return {}
                    selected = {key: a for key, a in actions.items()
                                if key not in stopped and key not in manual}
                    selected.update({key: replace(a, issued_t=t) for key, a in manual.items()
                                     if key not in stopped and states.get(key) is not None and states[key].connected})
                    return selected

                experiment = self._experiment
                actions = await worker.call(lambda: experiment.process_research(
                    t, self._dt, states, mission_step, arbitrate))
                if epoch != self._epoch or self.status != "running":
                    continue
                self._tracks = experiment.latest["tracks"]
                self._detections = experiment.latest["detections"]
                self._metrics = experiment.latest["metrics"]
                self._diagnostics = experiment.latest["diagnostics"]
                if self._fleet is not None:
                    hardware_states = self._fleet.states()
                    self._diagnostics["mirror_hardware_feedback"] = {
                        key: jsonable(value) for key, value in hardware_states.items()
                    }
                self._remember_tracks()
                self._targets.update(actions)

                self._world.advance(actions, self._dt)
                if self._fleet is not None:
                    self._fleet.submit(actions)
                else:
                    for a in actions.values():
                        self._result(CommandResult(a.device_id, t, a, "simulated", sent=False, ack=False,
                                                   applied={"simulation": True}))
                recorder.check()
                delay = self._dt - (time.monotonic() - begin)
                if delay < 0:
                    self._event("deadline_overrun", {"late_s": -delay})
                await asyncio.sleep(max(.001, delay))
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            self.status = "error"
            with contextlib.suppress(Exception):
                self._event("session_error", {"error": self.error})
        finally:
            self._epoch += 1
            self._manual.clear(); self._stopped_devices.clear(); self._targets.clear()
            await self._revoke("research_session_end")
            if gate is not None:
                gate.detach()
            if worker is not None:
                worker.close()
            fleet = self._fleet
            errors = await asyncio.gather(*(obj.close() for obj in (fleet,) if obj is not None),
                                          return_exceptions=True)
            for error in errors:
                if isinstance(error, BaseException):
                    completed = False
                    self.error = str(error)
                    self.status = "error"
            self._fleet = self._vision = None
            self._data_t = self._clock()
            self._states = {key: replace(state, connected=False) for key, state in self._states.items()}
            if recorder is not None:
                with contextlib.suppress(Exception):
                    self._event("research_session_stopped", {"completed": completed, "error": self.error})
                try:
                    await asyncio.to_thread(recorder.close, completed)
                except Exception as exc:
                    self.error, self.status = f"CSV关闭失败: {exc}", "error"
            self._recorder = self._experiment = self._world = None
            self._publish()

    def frame(self, device_id):
        if self.environment != "mirror":
            return super().frame(device_id)
        snap = super().snapshot()  # internal snapshot retains the true mirror label
        if not snap["video_enabled"] or device_id not in {d["id"] for d in snap["devices"] if d["enabled"]}:
            return None
        import cv2
        import numpy as np
        image = np.full((360, 640, 3), (35, 26, 20), dtype=np.uint8)
        cv2.line(image, (320, 0), (320, 360), (80, 90, 90), 1)
        cv2.line(image, (0, 180), (640, 180), (80, 90, 90), 1)
        cv2.putText(image, f"VIRTUAL TARGETS + HARDWARE MIRROR  {device_id}", (12, 26),
                    cv2.FONT_HERSHEY_SIMPLEX, .46, (70, 210, 250), 1)
        for d in snap["detections"]:
            if d["device_id"] != device_id:
                continue
            w, h = d["image_size"]
            x1, y1, x2, y2 = d["bbox_xyxy"]
            center = (int((x1 + x2) / 2 * 640 / w), int((y1 + y2) / 2 * 360 / h))
            cv2.circle(image, center, 7, (90, 240, 100), 2)
        cv2.putText(image, "Synthetic task view - real ZR10 only mirrors A/E/Zoom", (12, 344),
                    cv2.FONT_HERSHEY_SIMPLEX, .42, (190, 190, 190), 1)
        ok, data = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 78])
        return data.tobytes() if ok else None

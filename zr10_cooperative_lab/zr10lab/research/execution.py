from __future__ import annotations

from dataclasses import dataclass


def _angle_delta_deg(a: float, b: float) -> float:
    return (float(a) - float(b) + 180.0) % 360.0 - 180.0


def _task_kind(reason: str) -> str:
    text = str(reason or "")
    if "shared_track" in text:
        return "shared_track"
    if "track" in text:
        return "track"
    if "search" in text or "scan" in text:
        return "search"
    if "hold" in text:
        return "hold"
    return text


@dataclass
class ExecutionSnapshot:
    ready_count: int
    connected_count: int
    moving_count: int
    settling_count: int
    total_yaw_motion_deg: float
    total_pitch_motion_deg: float
    total_zoom_change: float
    ready_device_s: float
    connected_device_s: float
    moving_device_s: float
    settling_device_s: float
    command_update_count: int
    assignment_switch_count: int

    @property
    def sensing_duty_cycle(self) -> float | None:
        if self.connected_device_s <= 0:
            return None
        return self.ready_device_s / self.connected_device_s

    def metrics(self) -> dict[str, float | int | None]:
        return {
            "research_total_yaw_motion_deg": float(self.total_yaw_motion_deg),
            "research_total_pitch_motion_deg": float(self.total_pitch_motion_deg),
            "research_total_zoom_change": float(self.total_zoom_change),
            "research_ready_device_s": float(self.ready_device_s),
            "research_connected_device_s": float(self.connected_device_s),
            "research_moving_device_s": float(self.moving_device_s),
            "research_settling_device_s": float(self.settling_device_s),
            "research_sensing_duty_cycle": self.sensing_duty_cycle,
            "research_command_update_count": int(self.command_update_count),
            "research_assignment_switch_count": int(self.assignment_switch_count),
        }


class ExecutionEvaluator:
    """Evaluate physical effort from executed virtual PTZ states and planned tasks.

    Motion totals use the virtual actuator feedback, not requested set-points, so a
    large command that has not yet been reached is not counted as completed motion.
    Sensor-time categories use the shared ReadinessTracker state. Assignment switch
    count is intentionally coarser than command-update count: normal tracking
    set-point corrections do not become a new task assignment.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self._previous_states = None
        self._previous_commands = {}
        self._previous_assignments = {}
        self.total_yaw_motion_deg = 0.0
        self.total_pitch_motion_deg = 0.0
        self.total_zoom_change = 0.0
        self.ready_device_s = 0.0
        self.connected_device_s = 0.0
        self.moving_device_s = 0.0
        self.settling_device_s = 0.0
        self.command_update_count = 0
        self.assignment_switch_count = 0

    @staticmethod
    def _command_signature(action):
        return (round(float(action.yaw_deg), 6) if action.yaw_deg is not None else None,
                round(float(action.pitch_deg), 6) if action.pitch_deg is not None else None,
                round(float(action.zoom), 6) if action.zoom is not None else None)

    @staticmethod
    def _assignment_signature(action):
        return (_task_kind(action.reason), tuple(sorted(action.target_ids)))

    def update(self, dt: float, states: dict, readiness: dict, actions: dict, replanned: bool) -> ExecutionSnapshot:
        dt = max(0.0, float(dt))
        if self._previous_states is not None:
            for key, state in states.items():
                previous = self._previous_states.get(key)
                if previous is None:
                    continue
                self.total_yaw_motion_deg += abs(_angle_delta_deg(state.yaw_deg, previous.yaw_deg))
                self.total_pitch_motion_deg += abs(float(state.pitch_deg) - float(previous.pitch_deg))
                self.total_zoom_change += abs(float(state.zoom) - float(previous.zoom))

        ready_count = connected_count = moving_count = settling_count = 0
        for key, state in states.items():
            if not state.connected:
                continue
            connected_count += 1
            self.connected_device_s += dt
            item = readiness.get(key)
            if item is None:
                continue
            if item.sensing_valid:
                ready_count += 1
                self.ready_device_s += dt
            elif item.reason == "moving_or_zooming":
                moving_count += 1
                self.moving_device_s += dt
            elif item.reason == "settling":
                settling_count += 1
                self.settling_device_s += dt

        if replanned:
            for key, action in actions.items():
                command = self._command_signature(action)
                assignment = self._assignment_signature(action)
                if key in self._previous_commands and command != self._previous_commands[key]:
                    self.command_update_count += 1
                if key in self._previous_assignments and assignment != self._previous_assignments[key]:
                    self.assignment_switch_count += 1
                self._previous_commands[key] = command
                self._previous_assignments[key] = assignment

        self._previous_states = dict(states)
        return ExecutionSnapshot(
            ready_count=ready_count, connected_count=connected_count,
            moving_count=moving_count, settling_count=settling_count,
            total_yaw_motion_deg=self.total_yaw_motion_deg,
            total_pitch_motion_deg=self.total_pitch_motion_deg,
            total_zoom_change=self.total_zoom_change,
            ready_device_s=self.ready_device_s,
            connected_device_s=self.connected_device_s,
            moving_device_s=self.moving_device_s,
            settling_device_s=self.settling_device_s,
            command_update_count=self.command_update_count,
            assignment_switch_count=self.assignment_switch_count,
        )

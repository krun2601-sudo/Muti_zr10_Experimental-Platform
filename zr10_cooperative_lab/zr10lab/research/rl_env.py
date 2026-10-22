from __future__ import annotations

import copy
import math
from typing import Any

import numpy as np

from ..geometry import world_to_gimbal_angles
from ..models import Action, PolicyContext
from ..simulation import SimulationWorld
from .mission import SearchMonitorMission


def _norm(value, limits):
    lo, hi = map(float, limits)
    return float(np.clip(2 * (float(value) - lo) / max(hi - lo, 1e-9) - 1, -1, 1))


def _angle_norm(value):
    return float(np.clip(value / 180.0, -1.0, 1.0))


class ResearchObservationEncoder:
    """Fixed-size per-agent observation used by MAPPO and safe MAPPO.

    The observation contains only policy-available anonymous beliefs and search
    state. Hidden target truth may be used by the training reward, never here.
    """

    def __init__(self, cfg, max_targets=6, top_search_cells=8):
        self.cfg = cfg
        self.devices = tuple(cfg.active_devices)
        self.max_targets = int(max_targets)
        self.top_search_cells = int(top_search_cells)
        research = cfg.policy.get("research", {})
        self.age_cap = float(research.get("search", {}).get("age_cap_s", 120.0))
        self.position_scale = float(research.get("learning", {}).get("position_scale_m", 200.0))
        self.velocity_scale = float(research.get("learning", {}).get("velocity_scale_mps", 10.0))
        self.obs_dim = 7 + self.max_targets * 10 + self.top_search_cells * 3 + 3

    def encode(self, context: PolicyContext) -> np.ndarray:
        search = context.research.get("search", {})
        positions = np.asarray(search.get("positions_m", []), dtype=float)
        ages = np.asarray(search.get("ages_s", []), dtype=float)
        top = np.argsort(-ages, kind="stable")[:self.top_search_cells] if len(ages) else []
        tracks = sorted(context.tracks, key=lambda x: x.track_id)[:self.max_targets]
        readiness = context.research.get("readiness", {})
        rows = []
        for device in self.devices:
            state = context.devices[device.id]
            own = [
                _norm(state.yaw_deg, device.yaw_limits_deg),
                _norm(state.pitch_deg, device.pitch_limits_deg),
                _norm(state.zoom, device.zoom_limits),
                float(np.clip(state.yaw_rate_dps / max(device.max_slew_dps, 1e-9), -1, 1)),
                float(np.clip(state.pitch_rate_dps / max(device.max_slew_dps, 1e-9), -1, 1)),
                float(state.connected),
                float(bool(readiness.get(device.id, {}).get("sensing_valid", False))),
            ]
            target_features = []
            for track in tracks:
                try:
                    yaw, pitch = world_to_gimbal_angles(track.position, device)
                    yaw_err = _angle_norm((yaw - state.yaw_deg + 180) % 360 - 180)
                    pitch_err = _angle_norm(pitch - state.pitch_deg)
                except ValueError:
                    yaw_err = pitch_err = 0.0
                distance = np.linalg.norm(np.asarray(track.position) - np.asarray(device.position_m)) / self.position_scale
                covariance = np.asarray(track.covariance, dtype=float)
                uncertainty = math.sqrt(max(float(np.trace(covariance)), 0.0)) / self.position_scale
                velocity = np.asarray(track.velocity, dtype=float) / self.velocity_scale
                target_features.extend([
                    yaw_err, pitch_err, float(np.clip(distance, 0, 5)),
                    *np.clip(velocity, -5, 5).tolist(), float(np.clip(uncertainty, 0, 5)),
                    float(np.clip((context.t - track.last_seen_t) / 5.0, 0, 5)),
                    float(device.id in track.device_ids),
                    1.0 if track.status == "confirmed" else 0.0,
                ])
            target_features.extend([0.0] * ((self.max_targets - len(tracks)) * 10))
            search_features = []
            for index in top:
                try:
                    yaw, pitch = world_to_gimbal_angles(positions[int(index)], device)
                    search_features.extend([
                        _angle_norm((yaw - state.yaw_deg + 180) % 360 - 180),
                        _angle_norm(pitch - state.pitch_deg),
                        float(np.clip(ages[int(index)] / max(self.age_cap, 1e-9), 0, 2)),
                    ])
                except ValueError:
                    search_features.extend([0.0, 0.0, 0.0])
            search_features.extend([0.0] * ((self.top_search_cells - len(top)) * 3))
            global_features = [
                len(context.tracks) / max(self.max_targets, 1),
                float(np.mean(ages) / max(self.age_cap, 1e-9)) if len(ages) else 0.0,
                float(np.max(ages) / max(self.age_cap, 1e-9)) if len(ages) else 0.0,
            ]
            row = np.asarray([*own, *target_features, *search_features, *global_features], dtype=np.float32)
            if row.shape != (self.obs_dim,):
                raise RuntimeError(f"research RL observation shape mismatch: {row.shape} != {(self.obs_dim,)}")
            rows.append(row)
        return np.asarray(rows, dtype=np.float32)

    def decode(self, actions: np.ndarray, context: PolicyContext, reason="mappo") -> dict[str, Action]:
        array = np.asarray(actions, dtype=float)
        if array.shape != (len(self.devices), 3) or not np.all(np.isfinite(array)):
            raise ValueError(f"RL action must have shape {(len(self.devices), 3)}")
        array = np.clip(array, -1, 1)
        result = {}
        ttl = float(self.cfg.policy.get("research", {}).get("planning", {}).get("action_ttl_s", 0.8))
        for device, row in zip(self.devices, array):
            values = []
            for value, limits in zip(row, (device.yaw_limits_deg, device.pitch_limits_deg, device.zoom_limits)):
                lo, hi = map(float, limits)
                values.append(lo + (float(value) + 1) * 0.5 * (hi - lo))
            result[device.id] = Action(device.id, yaw_deg=values[0], pitch_deg=values[1], zoom=values[2],
                                       reason=reason, issued_t=context.t, ttl_s=ttl)
        return result


class ResearchMARLEnv:
    """CTDE environment sharing the paper task's execution and event semantics.

    One learning action is held for at most ``replan_period_s``. If the same
    discrete task event used by ResearchExperiment occurs earlier, ``step`` returns
    early so the learned policy receives the same opportunity to replan. The PPO
    implementation still uses a per-decision discount; this is an explicit learning
    approximation when event intervals are shorter than the nominal period.

    Training reward/cost may use hidden task truth as privileged supervision. This
    does not enter the actor observation. In particular, active-but-undiscovered
    targets incur cost, preventing a constrained policy from reducing its apparent
    monitoring risk by deliberately avoiding discovery.
    """

    def __init__(self, cfg, seed=0, max_targets=6, top_search_cells=8):
        self.cfg = copy.deepcopy(cfg)
        self.cfg.policy["mission"] = "search_monitor"
        self.seed = int(seed)
        self.encoder = ResearchObservationEncoder(self.cfg, max_targets, top_search_cells)
        self.dt = 1.0 / float(self.cfg.system.get("rate_hz", 10))
        planning = self.cfg.policy.get("research", {}).get("planning", {})
        replan = float(planning.get("replan_period_s", 0.5))
        self.event_replan = bool(planning.get("event_replan", True))
        self.frame_skip = max(1, int(round(replan / self.dt)))
        self.duration_s = float(self.cfg.system.get("duration_s", 60))
        learning = self.cfg.policy.get("research", {}).get("learning", {})
        self.loss_penalty = float(learning.get("loss_penalty", 8.0))
        self.missed_active_penalty = float(learning.get("missed_active_penalty", self.loss_penalty))
        self.search_age_weight = float(learning.get("search_age_weight", 1.0))
        self.discovery_bonus = float(learning.get("discovery_bonus", 2.0))
        self.motion_weight = float(learning.get("motion_weight", 0.05))
        if min(self.loss_penalty, self.missed_active_penalty, self.search_age_weight,
               self.discovery_bonus, self.motion_weight) < 0:
            raise ValueError("research learning reward weights must be nonnegative")
        self._world = None; self._mission = None; self._context = None
        self._decision_step = 0; self._previous_discovered = 0
        self._previous_actions = np.zeros((len(self.cfg.active_devices), 3), dtype=float)
        self._last_event_signature = None

    @property
    def n_agents(self): return len(self.cfg.active_devices)
    @property
    def obs_dim(self): return self.encoder.obs_dim
    @property
    def action_dim(self): return 3

    def _context_from(self, states, step):
        m = self._mission
        return PolicyContext(t=self._world.t, dt=self.dt, step=step, devices=states,
                             detections=tuple(m.last_perception.detections), tracks=tuple(m.last_perception.tracks),
                             research={
                                 "mission": "search_monitor",
                                 "search": m.last_search.policy_payload(),
                                 "readiness": {k: {"sensing_valid": v.sensing_valid, "stable_since": v.stable_since,
                                                    "reason": v.reason} for k, v in m.last_readiness.items()},
                                 "execution": dict(self.cfg.policy.get("research", {}).get("execution", {})),
                                 "planning": dict(self.cfg.policy.get("research", {}).get("planning", {})),
                             })

    @staticmethod
    def _event_signature(context):
        tracks = tuple(sorted((tr.track_id, tr.status, tuple(sorted(set(tr.device_ids)))) for tr in context.tracks))
        devices = tuple(sorted((key, bool(state.connected)) for key, state in context.devices.items()))
        return tracks, devices

    def reset(self, seed=None):
        if seed is not None: self.seed = int(seed)
        self.cfg.simulation["seed"] = self.seed
        self.cfg.policy.setdefault("research", {}).setdefault("perception", {})["seed"] = self.seed
        self._world = SimulationWorld(self.cfg); self._world.reset(seed=self.seed)
        self._mission = SearchMonitorMission(self.cfg)
        states = self._world.states(); self._mission.step(self._world.t, self.dt, states)
        self._context = self._context_from(states, 0)
        self._last_event_signature = self._event_signature(self._context)
        self._decision_step = 0
        self._previous_discovered = self._mission.last_perception.discovered_active_count
        self._previous_actions.fill(0.0)
        obs = self.encoder.encode(self._context)
        return obs, obs.reshape(-1).copy()

    def step(self, action: np.ndarray):
        if self._context is None:
            raise RuntimeError("reset() must be called before step()")
        action = np.asarray(action, dtype=float)
        commands = self.encoder.decode(action, self._context, "mappo_training")
        reward_total = 0.0; cost_total = 0.0; frames = 0; event_triggered = False
        for _ in range(self.frame_skip):
            self._world.advance(commands, self.dt)
            states = self._world.states(); self._mission.step(self._world.t, self.dt, states)
            status = self._mission.last_perception.target_status
            active_count = len(status)
            discovered = [x for x in status if x.discovered]
            lost = sum(not bool(x.visible_devices) for x in discovered)
            undiscovered = active_count - len(discovered)
            new_discovered = max(0, self._mission.last_perception.discovered_active_count - self._previous_discovered)
            self._previous_discovered = self._mission.last_perception.discovered_active_count
            age_mean = float(np.mean(self._mission.last_search.ages_s))
            age_cap = float(self.cfg.policy.get("research", {}).get("search", {}).get("age_cap_s", 120.0))
            task_denominator = max(active_count, 1)
            lost_rate = lost / task_denominator
            undiscovered_rate = undiscovered / task_denominator
            reward_total += (
                self.discovery_bonus * new_discovered
                - self.loss_penalty * lost_rate
                - self.missed_active_penalty * undiscovered_rate
                - self.search_age_weight * age_mean / max(age_cap, 1e-9)
            )
            # Safe-MAPPO cost represents current task failure fraction: either an
            # active target has not yet been discovered, or a discovered target has
            # no valid geometric view. This closes the avoid-discovery loophole.
            cost_total += (lost + undiscovered) / task_denominator
            frames += 1
            provisional = self._context_from(states, self._decision_step + 1)
            signature = self._event_signature(provisional)
            if self.event_replan and signature != self._last_event_signature:
                event_triggered = True
                self._context = provisional
                self._last_event_signature = signature
                break
            self._context = provisional
            self._last_event_signature = signature
            if self._world.t >= self.duration_s - 1e-12:
                break
        motion = float(np.mean(np.abs(action - self._previous_actions)))
        reward_total -= self.motion_weight * motion
        self._previous_actions = action.copy(); self._decision_step += 1
        obs = self.encoder.encode(self._context)
        done = self._world.t >= self.duration_s - 1e-12
        denominator = max(frames, 1)
        info = {"metrics": dict(self._mission.last_metrics), "time_s": self._world.t,
                "cost": float(cost_total / denominator), "frames_executed": frames,
                "event_triggered": bool(event_triggered),
                "reward_uses_privileged_truth": True}
        return obs, obs.reshape(-1).copy(), float(reward_total / denominator), float(cost_total / denominator), done, info

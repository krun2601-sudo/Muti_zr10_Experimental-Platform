from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

import numpy as np

from ..geometry import project_world_point
from ..models import Detection, Track
from .sensing_quality import SensingQualityModel
from .types import PerceptionSnapshot, ResearchTargetStatus, TruthTarget


def _uniform(seed: int, *tokens: object) -> float:
    payload = "|".join([str(seed), *(str(x) for x in tokens)]).encode("utf-8")
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    return int.from_bytes(digest, "little") / float(2**64)


def _normal3(seed: int, *tokens: object) -> np.ndarray:
    payload = "|".join([str(seed), *(str(x) for x in tokens)]).encode("utf-8")
    digest = hashlib.blake2b(payload, digest_size=16).digest()
    rng = np.random.default_rng(int.from_bytes(digest[:8], "little"))
    return rng.normal(0.0, 1.0, 3)


@dataclass
class _Belief:
    track_id: str
    position: np.ndarray
    velocity: np.ndarray
    covariance: np.ndarray
    last_t: float
    last_seen_t: float
    discovery_t: float
    hits: int = 1
    longest_gap_s: float = 0.0


class VirtualPerception:
    """Controlled synthetic discovery/tracking layer for scheduler experiments.

    Truth IDs are kept only inside this class. Policies receive anonymous Track
    objects. The layer is intentionally an abstract target tracker, not a claim
    that a single optical bearing can uniquely recover range in a real system.

    Importantly, geometric FOV inclusion is not enough. ``discovery_visible`` uses
    the public virtual discovery-quality threshold, while ``monitor_visible`` uses
    the stricter continuous-monitoring threshold. This creates an auditable
    wide-FOV/search versus narrow-FOV/reliable-monitoring tradeoff without claiming
    measured detector performance for the physical ZR10.
    """

    def __init__(self, cfg):
        self.cfg = cfg
        research = cfg.policy.get("research", {})
        options = research.get("perception", {})
        self.seed = int(options.get("seed", cfg.simulation.get("seed", 7)))
        self.detection_probability = float(options.get("detection_probability", cfg.simulation.get("detection_probability", 0.96)))
        self.position_noise_std_m = float(options.get("position_noise_std_m", 1.0))
        self.velocity_noise_std_mps = float(options.get("velocity_noise_std_mps", 0.25))
        self.process_noise_m2ps = float(options.get("process_noise_m2ps", 0.25))
        self.initial_covariance_m2 = float(options.get("initial_covariance_m2", max(self.position_noise_std_m**2, 1e-4)))
        self.coast_timeout_s = float(options.get("coast_timeout_s", 3.0))
        self.min_zoom = float(options.get("minimum_detection_zoom", 0.0))
        self.time_bin_s = float(options.get("random_time_bin_s", 0.1))
        if not 0 <= self.detection_probability <= 1:
            raise ValueError("research detection_probability must lie in [0,1]")
        if min(self.position_noise_std_m, self.velocity_noise_std_mps, self.process_noise_m2ps,
               self.initial_covariance_m2, self.coast_timeout_s, self.time_bin_s) < 0 or self.time_bin_s <= 0:
            raise ValueError("research perception noise/timing parameters are invalid")
        self.devices = {d.id: d for d in cfg.active_devices}
        self.quality = SensingQualityModel(cfg)
        self.reset()

    def reset(self) -> None:
        self._beliefs: dict[str, _Belief] = {}
        self._truth_to_track: dict[str, str] = {}
        self._track_serial = 0
        self._last_active: set[str] = set()

    def _new_track_id(self) -> str:
        self._track_serial += 1
        return f"vtrack-{self._track_serial:04d}"

    def _effective_devices(self, target: TruthTarget, states: dict, readiness: dict,
                           mode: str) -> tuple[str, ...]:
        visible = []
        predicate = self.quality.discovery_valid if mode == "discovery" else self.quality.monitor_valid
        for key, state in states.items():
            ready = readiness.get(key)
            if ready is None or not ready.sensing_valid or float(state.zoom) + 1e-9 < self.min_zoom:
                continue
            config = self.devices.get(key)
            if config is None:
                continue
            try:
                geometric = project_world_point(target.position, state, config) is not None
            except ValueError:
                continue
            if geometric and predicate(target.position, config, float(state.zoom)):
                visible.append(key)
        return tuple(sorted(visible))

    def _detected_devices(self, t: float, truth_id: str, visible: tuple[str, ...]) -> tuple[str, ...]:
        time_bin = int(math.floor(t / self.time_bin_s + 1e-9))
        return tuple(key for key in visible
                     if _uniform(self.seed, "detect", truth_id, time_bin, key) < self.detection_probability)

    def _measurement(self, target: TruthTarget, t: float) -> tuple[np.ndarray, np.ndarray]:
        time_bin = int(math.floor(t / self.time_bin_s + 1e-9))
        p_noise = _normal3(self.seed, "position", target.truth_id, time_bin) * self.position_noise_std_m
        v_noise = _normal3(self.seed, "velocity", target.truth_id, time_bin) * self.velocity_noise_std_mps
        return np.asarray(target.position, dtype=float) + p_noise, np.asarray(target.velocity, dtype=float) + v_noise

    def _update_belief(self, target: TruthTarget, t: float, observed: bool) -> _Belief | None:
        belief = self._beliefs.get(target.truth_id)
        if belief is None:
            if not observed:
                return None
            position, velocity = self._measurement(target, t)
            track_id = self._new_track_id()
            belief = _Belief(track_id, position, velocity, np.eye(3) * self.initial_covariance_m2,
                             t, t, t, hits=1)
            self._beliefs[target.truth_id] = belief
            self._truth_to_track[target.truth_id] = track_id
            return belief
        dt = max(0.0, float(t) - belief.last_t)
        belief.position = belief.position + belief.velocity * dt
        belief.covariance = belief.covariance + np.eye(3) * self.process_noise_m2ps * dt
        belief.last_t = float(t)
        if observed:
            measured_position, measured_velocity = self._measurement(target, t)
            r = max(self.position_noise_std_m**2, 1e-6)
            p = np.maximum(np.diag(belief.covariance), 1e-9)
            gain = p / (p + r)
            belief.position = belief.position + gain * (measured_position - belief.position)
            belief.velocity = 0.65 * belief.velocity + 0.35 * measured_velocity
            belief.covariance = np.diag((1.0 - gain) * p)
            belief.last_seen_t = float(t)
            belief.hits += 1
        belief.longest_gap_s = max(belief.longest_gap_s, float(t) - belief.last_seen_t)
        return belief

    def step(self, t: float, truth: dict[str, TruthTarget], states: dict, readiness: dict) -> PerceptionSnapshot:
        detections: list[Detection] = []
        tracks: list[Track] = []
        status: list[ResearchTargetStatus] = []
        active_ids = set(truth)
        for truth_id in set(self._beliefs) - active_ids:
            self._beliefs.pop(truth_id, None)
            self._truth_to_track.pop(truth_id, None)
        for truth_id in sorted(truth):
            target = truth[truth_id]
            discovery_visible = self._effective_devices(target, states, readiness, "discovery")
            monitor_visible = self._effective_devices(target, states, readiness, "monitor")
            detected = self._detected_devices(t, truth_id, discovery_visible)
            belief = self._update_belief(target, t, bool(detected))
            discovered = belief is not None
            if belief is not None:
                coasting = t - belief.last_seen_t > 1e-9
                status_name = "coasting" if coasting else "confirmed"
                measured = not coasting
                tracks.append(Track(
                    belief.track_id, float(t), tuple(float(x) for x in belief.position),
                    tuple(float(x) for x in belief.velocity),
                    tuple(tuple(float(v) for v in row) for row in belief.covariance),
                    float(belief.last_seen_t), belief.hits, status_name,
                    tuple(detected), 0, measured,
                ))
            for device_id in detected:
                device = self.devices[device_id]
                point = project_world_point(target.position, states[device_id], device)
                if point is None:
                    continue
                u, v = point
                w, h = device.camera.get("image_size", [1920, 1080])
                local = f"d{len(detections)}"
                detections.append(Detection(device_id, int(round(t / max(self.time_bin_s, 1e-9))), float(t),
                                             (max(0.0, u - 5), max(0.0, v - 4), min(float(w), u + 5), min(float(h), v + 4)),
                                             0.95, 0, local, (int(w), int(h)), float(t), 0.0))
            current_gap = 0.0 if belief is None else max(0.0, t - belief.last_seen_t)
            status.append(ResearchTargetStatus(
                truth_id=truth_id,
                track_id=None if belief is None else belief.track_id,
                active=True,
                discovered=discovered,
                visible_devices=monitor_visible,
                sensing_devices=detected,
                discovery_t=None if belief is None else belief.discovery_t,
                current_loss_gap_s=float(current_gap),
                longest_loss_gap_s=0.0 if belief is None else float(belief.longest_gap_s),
            ))
        self._last_active = active_ids
        return PerceptionSnapshot(tuple(tracks), tuple(detections), tuple(status), len(truth),
                                  sum(x.discovered for x in status))

    def private_truth_to_track(self) -> dict[str, str]:
        """Evaluation/testing hook. Never place this mapping in a policy context."""
        return dict(self._truth_to_track)

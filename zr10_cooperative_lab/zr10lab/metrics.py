"""在线任务指标。真值仅进入评估器，永远不写回算法观测。"""
from __future__ import annotations
from itertools import product
import numpy as np
from scipy.optimize import linear_sum_assignment
from .geometry import camera_rotation,intrinsics_at_zoom


class Metrics:
    def __init__(self,cfg):
        self.cfg = cfg
        roi = cfg.policy.get("roi",{"x":[60,160],"y":[-70,70],"z":[35,90]})
        self.grid = np.asarray(list(product(*(np.linspace(*roi[k],5) for k in ("x","y","z")))))
        self.visited = np.zeros(len(self.grid),dtype=bool)
        self.last_visit = np.full(len(self.grid),np.nan)
        self.identity_map = {}
        self.id_switches = 0
        self.sum_squared_error = 0.0
        self.matches = 0
        self.target_cycles = 0
        self.localized_cycles = 0
        self.longest_gap_s = 0.0
        self.last_localized = {}

    def update(self,t,states,tracks,truth=None):
        counts = np.zeros(len(self.grid),dtype=int)
        for d in self.cfg.active_devices:
            s = states.get(d.id)
            if s is None or not s.connected or t-s.t>self.cfg.system.get("telemetry_stale_s",.5) or s.raw.get("zoom_known") is False or s.raw.get("zoom_stable") is False:
                continue
            try:
                k = intrinsics_at_zoom(d,s.zoom)
                local = (self.grid-np.asarray(d.position_m)) @ camera_rotation(s,d)
                front = local[:,0]>1e-6
                depth = np.maximum(local[:,0],1e-6)
                if any(k.dist):
                    import cv2
                    points = np.column_stack((-local[:,1],-local[:,2],depth))
                    uv,_ = cv2.projectPoints(points,np.zeros(3),np.zeros(3),k.K,np.asarray(k.dist))
                    u,v = uv.reshape(-1,2).T
                else:
                    u,v = k.cx-k.fx*local[:,1]/depth,k.cy-k.fy*local[:,2]/depth
                counts += (front & (u>=0) & (u<k.width) & (v>=0) & (v<k.height)).astype(int)
            except ValueError:
                # 变焦未经标定时不能把视场覆盖率算成已知。
                continue
        self.visited |= counts>0
        self.last_visit[counts>0] = t
        values = {"roi_instant_coverage":float(np.mean(counts>0)),
                  "roi_cumulative_coverage":float(np.mean(self.visited)),
                  "roi_multiview_fraction":float(np.mean(counts>=2)),
                  "measured_track_count":sum(bool(x.measured) for x in tracks),
                  "predicted_track_count":sum(not x.measured for x in tracks)}
        if truth is None:
            return values
        ids = list(truth)
        measured = [x for x in tracks if x.measured]
        self.target_cycles += len(ids)
        matched_truth = set()
        if ids and measured:
            dist = np.linalg.norm(np.asarray(list(truth.values()))[:,None,:] -
                                  np.asarray([x.position for x in measured])[None,:,:],axis=2)
            rows,cols = linear_sum_assignment(dist)
            for i,j in zip(rows,cols):
                if dist[i,j] > self.cfg.simulation.get("evaluation_gate_m",10):
                    continue
                tid,track = ids[i],measured[j]
                matched_truth.add(tid)
                old = self.identity_map.get(tid)
                if old is not None and old != track.track_id:
                    self.id_switches += 1
                self.identity_map[tid] = track.track_id
                self.sum_squared_error += float(dist[i,j]**2)
                self.matches += 1
                self.last_localized[tid] = t
        for tid in ids:
            if tid not in matched_truth:
                last = self.last_localized.setdefault(tid,t)
                self.longest_gap_s = max(self.longest_gap_s,t-last)
        self.localized_cycles += len(matched_truth)
        values.update(localization_recall=len(matched_truth)/max(len(ids),1),
            cumulative_localization_recall=self.localized_cycles/max(self.target_cycles,1),
            position_rmse_m=(self.sum_squared_error/self.matches)**.5 if self.matches else None,
            evaluation_match_count=self.matches,
            id_switches=self.id_switches,longest_localization_gap_s=self.longest_gap_s,
            truth_count=len(ids))
        return values

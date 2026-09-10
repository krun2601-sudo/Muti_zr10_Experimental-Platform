"""相机几何与空间交会：全项目统一采用 ENU 世界坐标。

世界轴为 x 东、y 北、z 上；方位角 A=atan2(y,x)，从东逆时针转向北。
相机/云台局部轴为 x 前、y 左、z 上，正俯仰使光轴抬高。所有角度
接口用度，三维位置用米。SDK 原始角度的正负号由设备适配层负责。
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Any, Sequence

import numpy as np

from .config import DeviceConfig
from .models import Detection, Localization, Ray, Telemetry


@dataclass(frozen=True)
class CameraIntrinsics:
    """固定分辨率、给定变焦档位的针孔内参及 OpenCV 畸变系数。"""

    fx: float
    fy: float
    cx: float
    cy: float
    width: int
    height: int
    dist: tuple[float, ...] = (0.0, 0.0, 0.0, 0.0, 0.0)

    @property
    def K(self) -> np.ndarray:
        return np.array([[self.fx, 0., self.cx], [0., self.fy, self.cy], [0., 0., 1.]])


def rotation_matrix(yaw_deg: float, pitch_deg: float, roll_deg: float = 0.) -> np.ndarray:
    """返回 Rz(yaw) @ Ry(-pitch) @ Rx(roll)，把局部向量转入父坐标系。"""
    if not np.all(np.isfinite([yaw_deg, pitch_deg, roll_deg])):
        raise ValueError("姿态角必须是有限数值")
    yaw, pitch, roll = np.deg2rad([yaw_deg, pitch_deg, roll_deg])
    cy, sy, cp, sp, cr, sr = np.cos(yaw), np.sin(yaw), np.cos(pitch), np.sin(pitch), np.cos(roll), np.sin(roll)
    rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]])
    ry = np.array([[cp, 0, -sp], [0, 1, 0], [sp, 0, cp]])
    rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
    return rz @ ry @ rx


def mount_rotation(config: DeviceConfig) -> np.ndarray:
    """配置顺序是 roll,pitch,yaw；旋转函数顺序是 yaw,pitch,roll。"""
    roll, pitch, yaw = config.mount_rpy_deg
    return rotation_matrix(yaw, pitch, roll)


def camera_rotation(state: Telemetry, config: DeviceConfig) -> np.ndarray:
    """相机前左上方向到 ENU 的旋转：安装外参乘以实时云台姿态。"""
    return mount_rotation(config) @ rotation_matrix(state.yaw_deg, state.pitch_deg, state.roll_deg)


def intrinsics_at_zoom(config_or_camera: DeviceConfig | dict[str, Any], zoom: float) -> CameraIntrinsics:
    """按实测倍率表线性插值，不用“焦距正比倍率”替代实际标定。

    变焦超出标定表范围直接拒绝；固定倍率实验可只提供一行内参。表中
    所有行对应同一 image_size。若视频被裁剪、电子变焦或改变分辨率，
    必须提供相匹配的内参，不能把旧内参直接套在新图像上。
    """
    camera = config_or_camera.camera if isinstance(config_or_camera, DeviceConfig) else config_or_camera
    rows = camera.get("intrinsics", [])
    if not rows or not np.isfinite(zoom):
        raise ValueError("缺少相机内参表，或 zoom 不是有限数值")
    zooms = np.array([float(row["zoom"]) for row in rows])
    if not np.all(np.isfinite(zooms)) or np.any(np.diff(zooms) <= 0):
        raise ValueError("内参表倍率必须严格递增")
    if zoom < zooms[0] - 1e-6 or zoom > zooms[-1] + 1e-6:
        raise ValueError(f"倍率 {zoom:g} 超出已标定范围 [{zooms[0]:g}, {zooms[-1]:g}]")
    index = min(int(np.searchsorted(zooms, zoom, side="right")), len(rows) - 1)
    low, high = rows[max(0, index - 1)], rows[index]
    alpha = 0. if float(high["zoom"]) == float(low["zoom"]) else (zoom - float(low["zoom"])) / (float(high["zoom"]) - float(low["zoom"]))
    alpha = float(np.clip(alpha, 0, 1))
    values = [(1 - alpha) * float(low[k]) + alpha * float(high[k]) for k in ("fx", "fy", "cx", "cy")]
    low_dist = np.asarray(low.get("dist", low.get("distortion", [0.] * 5)), dtype=float)
    high_dist = np.asarray(high.get("dist", high.get("distortion", [0.] * 5)), dtype=float)
    if low_dist.shape != high_dist.shape or low_dist.size not in (4, 5, 8, 12, 14):
        raise ValueError("相邻倍率的畸变系数个数必须一致，且符合 OpenCV 模型")
    distortion = (1 - alpha) * low_dist + alpha * high_dist
    if min(values[:2]) <= 0 or not np.all(np.isfinite([*values, *distortion])):
        raise ValueError("相机内参非法：焦距须为正且全部参数须有限")
    width, height = camera.get("image_size", [1920, 1080])
    if int(width) != width or int(height) != height or min(width, height) <= 0:
        raise ValueError("标定图像分辨率须为正整数")
    return CameraIntrinsics(*values, int(width), int(height), tuple(float(x) for x in distortion))


def pixel_to_camera_ray(pixel_xy: Sequence[float], intrinsics: CameraIntrinsics) -> np.ndarray:
    """把原图像素还原为单位射线，支持目标不处于画面中心的定位。

    OpenCV 坐标是右、下、前，故归一化像素 (x,y) 映射为本项目的
    [1,-x,-y]。切勿直接给云台方位/俯仰加线性像素角，尤其在边缘和
    非零横滚时；应先去畸变，再做完整三维旋转。
    """
    import cv2

    pixel = np.asarray(pixel_xy, dtype=float)
    if pixel.shape != (2,) or not np.all(np.isfinite(pixel)):
        raise ValueError("像素必须是两个有限数值")
    xy = cv2.undistortPoints(pixel.reshape(1, 1, 2), intrinsics.K,
                             np.asarray(intrinsics.dist)).reshape(2)
    ray = np.array([1., -xy[0], -xy[1]])
    return ray / np.linalg.norm(ray)


def pixel_to_world_ray(detection: Detection, state: Telemetry, config: DeviceConfig) -> Ray:
    """检测框中心 → 去畸变相机射线 → 云台姿态 → 安装外参 → ENU 射线。

    state 应是视频曝光时刻的插值遥测，不能简单套用处理结束时的角度。
    一个框中心只是目标角度代理；无人机较近或轮廓变化时需提高角度噪声。
    """
    if detection.device_id != config.id or state.device_id != config.id:
        raise ValueError("检测、姿态和站点配置的设备 ID 不一致")
    intrinsics = intrinsics_at_zoom(config, state.zoom)
    if tuple(detection.image_size) != (intrinsics.width, intrinsics.height):
        raise ValueError("检测原图分辨率与相机标定不一致，需提供对应分辨率内参")
    if not np.isfinite(state.t) or not np.isfinite(detection.t):
        raise ValueError("姿态和检测时间戳须有限")
    if abs(detection.t - state.t) > float(config.camera.get("max_pose_skew_s", 0.2)):
        raise ValueError("检测时刻与姿态时刻相差过大")
    direction = camera_rotation(state, config) @ pixel_to_camera_ray(detection.center, intrinsics)
    base_angular_std = float(config.camera.get("angular_std_deg", 0.15))
    pose_time_error = float(state.raw.get("pose_time_error_s", 0.0))
    if not np.all(np.isfinite([base_angular_std, pose_time_error, detection.time_uncertainty_s])) or base_angular_std <= 0 or min(pose_time_error, detection.time_uncertainty_s) < 0:
        raise ValueError("角度标准差和姿态/曝光时间不确定度非法")
    # 曝光时间不确定时，运动中的云台朝向也不确定；不能只考虑目标
    # 移动引起的米制误差。nearest/interpolated 的时序误差由 timing
    # 模块提供，曝光估计误差由视频模块提供，此处保守合并其影响。
    angular_speed = float(np.hypot(state.yaw_rate_dps, state.pitch_rate_dps))
    angular_std = float(np.hypot(base_angular_std, angular_speed * (pose_time_error + detection.time_uncertainty_s)))
    return Ray(config.id, detection.key, detection.t, tuple(config.position_m),
               tuple(float(x) for x in direction), detection.confidence, angular_std,
               detection.class_id, detection.time_uncertainty_s, detection.embedding)


def project_world_point(point: Sequence[float], state: Telemetry, config: DeviceConfig) -> tuple[float, float] | None:
    """投影 ENU 点到原始图像；位于相机后方或画面外时返回 None。"""
    return project_world_points([point], state, config)[0]


def project_world_points(points: Sequence[Sequence[float]], state: Telemetry, config: DeviceConfig) -> list[tuple[float, float] | None]:
    """批量投影多个点，共享内参、旋转和 OpenCV 调用以降低策略开销。

    返回顺序与输入一致；单个点在后方/画面外时对应元素为 None。
    空输入返回空列表，不执行标定读取。该函数不保存跨周期缓存。
    """
    import cv2

    if len(points) == 0:
        return []
    intrinsics = intrinsics_at_zoom(config, state.zoom)
    point_array = np.asarray(points, dtype=float)
    if point_array.ndim != 2 or point_array.shape[1] != 3 or not np.all(np.isfinite(point_array)):
        raise ValueError("三维点必须是 N×3 个有限数值")
    delta = point_array - np.asarray(config.position_m, dtype=float)
    body = delta @ camera_rotation(state, config)
    valid_indices = np.flatnonzero(body[:, 0] > 1e-6)
    results: list[tuple[float, float] | None] = [None] * len(points)
    if not len(valid_indices):
        return results
    # OpenCV projectPoints 输入的光学坐标为右、下、前。
    optical = body[valid_indices][:, [1, 2, 0]] * np.array([-1, -1, 1])
    pixels, _ = cv2.projectPoints(optical, np.zeros(3),
                                  np.zeros(3), intrinsics.K, np.asarray(intrinsics.dist))
    for index, (u, v) in zip(valid_indices, pixels.reshape(-1, 2)):
        if 0 <= u < intrinsics.width and 0 <= v < intrinsics.height:
            results[int(index)] = (float(u), float(v))
    return results


def world_to_gimbal_angles(point: Sequence[float], config: DeviceConfig) -> tuple[float, float]:
    """给定目标 ENU 坐标，求将光轴中心指向目标的云台本地方位/俯仰。

    此处不裁剪机械限位；动作安全层应检查能否达到。Rx(roll) 不改变
    中心光轴方向，因此中心指向的逆解不需要当前横滚值。
    """
    delta = np.asarray(point, dtype=float) - np.asarray(config.position_m, dtype=float)
    if delta.shape != (3,) or not np.all(np.isfinite(delta)) or np.linalg.norm(delta) < 1e-9:
        raise ValueError("目标点不能与站点重合且坐标必须有限")
    x, y, z = mount_rotation(config).T @ delta
    return float(np.rad2deg(np.arctan2(y, x))), float(np.rad2deg(np.arctan2(z, np.hypot(x, y))))


def triangulate_rays(rays: Sequence[Ray], options: dict[str, Any] | None = None) -> Localization:
    """用异站射线加权最小二乘交会，失败时抛出带原因的 ValueError。

    每条射线的垂直投影算子 P=I-ddᵀ；最小化 Σ w||P(X-o)||²。
    角度噪声在距离 r 处对应约 r*σ 米，因此先求初值，再按距离更新
    权重。协方差来自信息矩阵逆，并在观测不一致时按残差放大。
    该协方差不包含未经建模的站点测量/安装系统误差，不能当绝对精度保证。
    """
    opt = options or {}
    if len(rays) < 2:
        raise ValueError("insufficient_stations: 空间定位至少需要两站")
    if len({ray.device_id for ray in rays}) != len(rays):
        raise ValueError("duplicate_station: 同一站只能贡献一条目标射线")
    origins = np.asarray([r.origin for r in rays], dtype=float)
    directions = np.asarray([r.direction for r in rays], dtype=float)
    times = np.asarray([r.t for r in rays], dtype=float)
    uncertainty = np.asarray([r.time_uncertainty_s for r in rays], dtype=float)
    angular = np.deg2rad([r.angular_std_deg for r in rays])
    confidence = np.asarray([r.confidence for r in rays], dtype=float)
    if origins.shape != (len(rays), 3) or directions.shape != origins.shape:
        raise ValueError("invalid_ray: 射线必须含三维原点和方向")
    if not all(np.all(np.isfinite(x)) for x in (origins, directions, times, uncertainty, angular, confidence)):
        raise ValueError("nonfinite_ray: 射线包含 NaN/无穷值")
    norms = np.linalg.norm(directions, axis=1)
    if np.any(norms < 1e-9) or np.any(angular <= 0) or np.any(uncertainty < 0):
        raise ValueError("invalid_uncertainty: 射线方向/不确定度非法")
    if np.any(confidence <= 0) or np.any(confidence > 1):
        raise ValueError("invalid_confidence: 置信度应在 (0,1] 内")
    directions = directions / norms[:, None]
    time_span = float(np.max(times) - np.min(times))
    if time_span > float(opt.get("max_time_skew_s", .08)):
        raise ValueError("time_skew: 多站估计曝光时间跨度超过门限")
    if np.max(uncertainty) > float(opt.get("max_time_uncertainty_s", .2)):
        raise ValueError("time_uncertainty: 单站曝光时间估计不确定度超过门限")
    timestamp = float(np.average(times, weights=confidence))
    max_speed = float(opt.get("max_target_speed_mps", 20.))
    if not np.isfinite(max_speed) or max_speed < 0:
        raise ValueError("max_target_speed_mps 必须是有限非负值")
    # 接收时刻/延迟补偿只能估计曝光时刻，不能创造硬件同步。把目标
    # 在这段不确定时间内可能移动的距离保守加入每条射线的横向噪声。
    # 这是一阶统计近似，不等同于对动态射线做精确运动补偿。
    temporal_std_m = max_speed * (uncertainty + np.abs(times - timestamp))
    pair_angles = [np.rad2deg(np.arccos(np.clip(abs(np.dot(directions[i], directions[j])), 0, 1)))
                   for i, j in combinations(range(len(rays)), 2)]
    min_angle = float(min(pair_angles))
    if min_angle < float(opt.get("min_ray_angle_deg", 1.0)):
        raise ValueError("weak_geometry: 射线交会夹角过小或近乎反平行")
    projectors = np.eye(3)[None] - directions[:, :, None] * directions[:, None, :]
    weights = confidence / angular ** 2
    floor = float(opt.get("measurement_floor_m", .05))
    if floor <= 0 or not np.isfinite(floor):
        raise ValueError("measurement_floor_m 必须为有限正数")
    for _ in range(3):
        information = np.einsum("n,nij->ij", weights, projectors)
        condition = float(np.linalg.cond(information))
        if not np.isfinite(condition) or condition > float(opt.get("max_condition_number", 1e6)):
            raise ValueError("ill_conditioned: 三角化信息矩阵病态")
        rhs = np.einsum("n,nij,nj->i", weights, projectors, origins)
        position = np.linalg.solve(information, rhs)
        distances = np.linalg.norm(position[None] - origins, axis=1)
        weights = confidence / (np.maximum((distances * angular) ** 2, floor ** 2) + temporal_std_m ** 2)
    vectors = position[None] - origins
    depths = np.einsum("ni,ni->n", vectors, directions)
    if np.any(depths <= float(opt.get("min_depth_m", .1))):
        raise ValueError("behind_camera: 交点处于相机后方或距站点过近")
    if np.any(distances > float(opt.get("max_range_m", 5000))):
        raise ValueError("range_limit: 交点距离超过实验工作范围")
    errors = np.einsum("nij,nj->ni", projectors, vectors)
    residuals = np.linalg.norm(errors, axis=1)
    residual = float(np.sqrt(np.mean(residuals ** 2)))
    if residual > float(opt.get("max_residual_m", 3.0)):
        raise ValueError("ray_residual: 多站射线残差过大")
    residual_angles = np.rad2deg(np.arctan2(residuals, depths))
    if np.max(residual_angles) > float(opt.get("max_angular_residual_deg", 1.5)):
        raise ValueError("angular_residual: 多站角度残差过大")
    information = np.einsum("n,nij->ij", weights, projectors)
    inflation = max(1., float(np.sum(weights * residuals ** 2)) / max(2 * len(rays) - 3, 1))
    covariance = np.linalg.inv(information) * inflation
    return Localization(timestamp, tuple(float(x) for x in position),
                        tuple(tuple(float(x) for x in row) for row in covariance),
                        tuple(r.device_id for r in rays), tuple(r.detection_id for r in rays),
                        residual, min_angle, float(np.linalg.cond(information)), time_span,
                        rays[0].class_id)

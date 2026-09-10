"""相机标定工具：内参棋盘格标定，以及已知控制点的安装外参拟合。

本模块不控制设备，也不把标定结果偷偷写入配置。调用者应检查残差、
几何退化和独立验证点，再把返回的参数填入实验配置并保存标定记录。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
from scipy.optimize import least_squares


@dataclass(frozen=True)
class MountFitResult:
    """安装外参拟合结果；协方差参数顺序为 yaw,pitch,roll,[dx,dy,dz]。"""

    mount_ypr_deg: tuple[float, float, float]
    position_enu_m: tuple[float, float, float]
    position_offset_m: tuple[float, float, float]
    rms_angle_deg: float
    max_angle_deg: float
    jacobian_condition: float
    parameter_covariance: list[list[float]]
    per_point_angle_deg: list[float]
    success: bool
    message: str


def calibrate_chessboard(
    image_paths: Iterable[str | Path],
    pattern_size: tuple[int, int],
    square_size_m: float,
    min_views: int = 8,
) -> dict:
    """对一个固定变焦档位做棋盘格标定，返回可审查的内参和逐图误差。

    ``pattern_size`` 是棋盘格的 **内角点列数、行数**，不是方格数。
    每个 zoom 档位、每种分辨率/裁剪方式应分别调用一次；标定时保持
    对焦方式和实际实验一致。图像要覆盖画面中心、四角和不同倾角。
    至少八张有效照片只是最低数量要求，并不能代替姿态丰富性检查。
    """
    import cv2  # 无须在纯几何/离线融合时提前加载 OpenCV。

    cols, rows = pattern_size
    if cols < 3 or rows < 3 or not np.isfinite(square_size_m) or square_size_m <= 0:
        raise ValueError("棋盘格至少需要 3×3 个内角点，方格边长必须为正米数")
    if min_views < 3:
        raise ValueError("min_views 不得小于 3，建议至少 8～20 张丰富姿态照片")
    object_template = np.zeros((rows * cols, 3), np.float32)
    object_template[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2) * square_size_m
    object_points, image_points, accepted, rejected = [], [], [], []
    image_size = None
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 1e-5)
    for path in image_paths:
        path = str(path)
        # imdecode + fromfile 在 Windows 上支持中文路径。
        try:
            image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        except (OSError, ValueError):
            image = None
        if image is None:
            rejected.append({"path": path, "reason": "无法读取图像"})
            continue
        size = (image.shape[1], image.shape[0])
        if image_size is not None and size != image_size:
            raise ValueError(f"标定图片分辨率不同：{path} 为 {size}，此前为 {image_size}")
        image_size = size
        found, corners = cv2.findChessboardCorners(
            image, (cols, rows), cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE
        )
        if not found:
            rejected.append({"path": path, "reason": "未找到完整棋盘格"})
            continue
        corners = cv2.cornerSubPix(image, corners, (11, 11), (-1, -1), criteria)
        object_points.append(object_template.copy())
        image_points.append(corners)
        accepted.append(path)
    if len(accepted) < min_views:
        raise ValueError(f"有效棋盘格照片仅 {len(accepted)} 张，至少需要 {min_views} 张")
    rms, matrix, distortion, rvecs, tvecs = cv2.calibrateCamera(
        object_points, image_points, image_size, None, None
    )
    per_view = []
    for path, obj, pixels, rotation, translation in zip(
        accepted, object_points, image_points, rvecs, tvecs
    ):
        projected, _ = cv2.projectPoints(obj, rotation, translation, matrix, distortion)
        error = np.linalg.norm(projected.reshape(-1, 2) - pixels.reshape(-1, 2), axis=1)
        per_view.append({"path": path, "rms_px": float(np.sqrt(np.mean(error ** 2))),
                         "max_px": float(np.max(error))})
    return {
        "width": image_size[0], "height": image_size[1],
        "fx": float(matrix[0, 0]), "fy": float(matrix[1, 1]),
        "cx": float(matrix[0, 2]), "cy": float(matrix[1, 2]),
        "distortion": distortion.ravel().tolist(), "rms_px": float(rms),
        "camera_matrix": matrix.tolist(), "per_view": per_view, "rejected_images": rejected,
        "pattern_inner_corners": [cols, rows], "square_size_m": square_size_m,
    }


def fit_mount_pose(
    control_points_enu_m: Sequence[Sequence[float]],
    measured_camera_rays: Sequence[Sequence[float]],
    gimbal_ypr_deg: Sequence[Sequence[float]],
    nominal_position_enu_m: Sequence[float],
    initial_mount_ypr_deg: Sequence[float] = (0.0, 0.0, 0.0),
    fit_position: bool = False,
    max_position_offset_m: float = 10.0,
) -> MountFitResult:
    """用多个已测量 ENU 控制点，拟合底座安装旋转及可选站点坐标偏移。

    输入射线必须是去畸变后的相机 ``forward-left-up`` 单位方向，通常由
    ``pixel_to_camera_ray`` 得到。每行云台姿态为 yaw,pitch,roll（度）。
    模型为 ``world_ray = R_mount @ R_gimbal @ camera_ray``；输入姿态已由
    设备适配层处理 SDK 符号。不要同时在这里和配置中重复添加零位偏差。

    只拟合旋转至少需要三个方向分散的点。连位置一起拟合要求至少六个
    控制点；共线点或单一方向会使结果不可辨识，函数通过 Jacobian 秩和
    条件数报告失败。方位和高度分散、含近远距离的控制点更有利。
    """
    from .geometry import rotation_matrix

    points = np.asarray(control_points_enu_m, dtype=float)
    rays = np.asarray(measured_camera_rays, dtype=float)
    angles = np.asarray(gimbal_ypr_deg, dtype=float)
    origin = np.asarray(nominal_position_enu_m, dtype=float)
    initial_mount = np.asarray(initial_mount_ypr_deg, dtype=float)
    minimum = 6 if fit_position else 3
    if points.ndim != 2 or points.shape[1] != 3 or len(points) < minimum:
        raise ValueError(f"至少需要 {minimum} 个三维控制点")
    if rays.shape != points.shape or angles.shape != points.shape:
        raise ValueError("控制点、相机射线和云台姿态必须是相同长度的 N×3 数组")
    if origin.shape != (3,) or initial_mount.shape != (3,):
        raise ValueError("站点坐标和安装姿态必须分别包含三个数值")
    if not all(np.all(np.isfinite(x)) for x in (points, rays, angles, origin, initial_mount)):
        raise ValueError("标定输入不能含 NaN 或无穷值")
    norms = np.linalg.norm(rays, axis=1)
    if np.any(norms < 1e-9) or np.any(np.linalg.norm(points - origin, axis=1) < 1e-3):
        raise ValueError("射线不能为零，控制点不能与名义站点重合")
    rays = rays / norms[:, None]
    base_rays = np.array([rotation_matrix(*a) @ ray for a, ray in zip(angles, rays)])

    def residual(parameters: np.ndarray) -> np.ndarray:
        position = origin + parameters[3:] if fit_position else origin
        vectors = points - position
        distances = np.linalg.norm(vectors, axis=1)
        directions = vectors / np.maximum(distances[:, None], 1e-9)
        predicted = (rotation_matrix(*parameters[:3]) @ base_rays.T).T
        # 用方向差而非 cross：后者会把 180°反向射线误认为零残差。
        return (predicted - directions).ravel()

    x0 = np.r_[initial_mount, np.zeros(3)] if fit_position else initial_mount.copy()
    bounds = (-np.inf, np.inf)
    if fit_position:
        if not np.isfinite(max_position_offset_m) or max_position_offset_m <= 0:
            raise ValueError("位置偏移上限必须为正数")
        bounds = (np.r_[[-np.inf] * 3, [-max_position_offset_m] * 3],
                  np.r_[[np.inf] * 3, [max_position_offset_m] * 3])
    result = least_squares(residual, x0, bounds=bounds, loss="soft_l1",
                           f_scale=np.deg2rad(0.1), max_nfev=3000,
                           xtol=1e-12, ftol=1e-12, gtol=1e-12)
    offset = result.x[3:] if fit_position else np.zeros(3)
    position = origin + offset
    expected = points - position
    expected /= np.linalg.norm(expected, axis=1, keepdims=True)
    predicted = (rotation_matrix(*result.x[:3]) @ base_rays.T).T
    angular = np.rad2deg(np.arccos(np.clip(np.sum(expected * predicted, axis=1), -1, 1)))
    singular = np.linalg.svd(result.jac, compute_uv=False)
    condition = float(singular[0] / singular[-1]) if singular[-1] > 1e-12 else float("inf")
    rank = int(np.linalg.matrix_rank(result.jac, tol=1e-9))
    # 单位方向虽然写为三个分量，但只有两个独立角自由度。
    dof = max(2 * len(points) - len(result.x), 1)
    variance = max(float(np.dot(result.fun, result.fun) / dof), 1e-14)
    covariance = np.linalg.pinv(result.jac.T @ result.jac) * variance
    success = bool(result.success and rank == len(result.x) and condition < 1e8)
    message = str(result.message) if success else "拟合失败或控制点几何退化；请增加不同方向与距离的控制点"
    return MountFitResult(
        tuple(float(v) for v in result.x[:3]), tuple(float(v) for v in position),
        tuple(float(v) for v in offset), float(np.sqrt(np.mean(angular ** 2))),
        float(np.max(angular)), condition, covariance.tolist(), angular.tolist(), success, message,
    )


def main(argv: list[str] | None = None) -> int:
    """标定命令行入口；只生成结果文件，不修改实验配置/连接设备。"""
    import argparse
    import csv
    import glob
    import json
    from dataclasses import asdict
    from datetime import datetime, timezone

    parser = argparse.ArgumentParser(description="ZR10 离线相机与安装外参标定")
    commands = parser.add_subparsers(dest="command", required=True)
    chessboard = commands.add_parser("chessboard", help="固定倍率棋盘格内参标定")
    chessboard.add_argument("--images", required=True, nargs="+", help="图片路径或带引号的通配符")
    chessboard.add_argument("--pattern", type=int, nargs=2, required=True, metavar=("COLS", "ROWS"), help="内角点列数、行数")
    chessboard.add_argument("--square-m", type=float, required=True, help="方格边长，单位米")
    chessboard.add_argument("--zoom", type=float, required=True, help="拍摄时固定的光学倍率")
    chessboard.add_argument("--min-views", type=int, default=8)
    chessboard.add_argument("--output", required=True, help="结果 JSON 路径")
    mount = commands.add_parser("mount", help="已知控制点拟合安装姿态/站点偏移")
    mount.add_argument("--config", required=True, help="实验 YAML，读取站点和内参")
    mount.add_argument("--device", required=True, help="配置中的完整设备 ID，例如 zr10_25")
    mount.add_argument("--csv", required=True, help="控制点 CSV；字段见中文标定文档")
    mount.add_argument("--fit-position", action="store_true", help="同时估计站点位置偏移")
    mount.add_argument("--max-offset-m", type=float, default=10.0)
    mount.add_argument("--output", required=True, help="结果 JSON 路径")
    args = parser.parse_args(argv)
    try:
        if args.command == "chessboard":
            if not np.isfinite(args.zoom) or args.zoom < 1:
                raise ValueError("zoom 必须是不小于 1 的有限倍率")
            paths = sorted({path for pattern in args.images for path in glob.glob(pattern)})
            result = calibrate_chessboard(paths, tuple(args.pattern), args.square_m, args.min_views)
            result["zoom"] = args.zoom
            result["config_intrinsics_row"] = {
                "zoom": args.zoom, **{k: result[k] for k in ("fx", "fy", "cx", "cy")},
                "dist": result["distortion"],
            }
            success = True
        else:
            from .config import load_config
            from .geometry import intrinsics_at_zoom, pixel_to_camera_ray

            cfg = load_config(args.config)
            device = next((device for device in cfg.devices if device.id == args.device), None)
            if device is None:
                raise ValueError(f"配置中不存在设备 {args.device}")
            points, rays, angles = [], [], []
            required = {"x_m", "y_m", "z_m", "u_px", "v_px", "yaw_deg", "pitch_deg", "roll_deg", "zoom"}
            with Path(args.csv).open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                if not required <= set(reader.fieldnames or []):
                    raise ValueError("控制点 CSV 缺少字段：" + ",".join(sorted(required - set(reader.fieldnames or []))))
                for line, row in enumerate(reader, start=2):
                    try:
                        values = {name: float(row[name]) for name in required}
                        points.append([values[name] for name in ("x_m", "y_m", "z_m")])
                        angles.append([values[name] for name in ("yaw_deg", "pitch_deg", "roll_deg")])
                        rays.append(pixel_to_camera_ray([values["u_px"], values["v_px"]],
                                                         intrinsics_at_zoom(device, values["zoom"])))
                    except (ValueError, TypeError, KeyError) as exc:
                        raise ValueError(f"控制点 CSV 第 {line} 行：{exc}") from exc
            roll, pitch, yaw = device.mount_rpy_deg
            fitted = fit_mount_pose(points, rays, angles, device.position_m, (yaw, pitch, roll),
                                    args.fit_position, args.max_offset_m)
            result = asdict(fitted)
            yaw, pitch, roll = fitted.mount_ypr_deg
            result["config_device_patch"] = {
                "id": device.id, "position_m": list(fitted.position_enu_m),
                "mount_rpy_deg": [roll, pitch, yaw], "calibration_verified": False,
            }
            result["source_control_csv"] = str(Path(args.csv).resolve())
            success = fitted.success
        result["created_utc"] = datetime.now(timezone.utc).isoformat()
        result["review_required"] = "请用独立验证数据检查结果后，手动更新实验配置；本命令不确认实机标定状态"

        def json_safe(value):
            # 标定退化时 condition 可以是 inf，JSON 用 null 表示不可用。
            if isinstance(value, float) and not np.isfinite(value):
                return None
            if isinstance(value, dict):
                return {key: json_safe(item) for key, item in value.items()}
            if isinstance(value, (list, tuple)):
                return [json_safe(item) for item in value]
            return value

        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(json_safe(result), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        print(f"标定结果已保存：{output.resolve()}")
        if not success:
            print("拟合失败或几何退化，请查看结果中的 message；不要应用该外参。")
            return 2
        return 0
    except (ValueError, OSError) as exc:
        parser.exit(2, f"标定失败：{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())

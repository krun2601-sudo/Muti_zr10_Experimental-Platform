# ZR10 Cooperative Observation v2.1

> v2.1 separates AE coordinate signs from SDK velocity-command signs.  The supplied three-ZR10 configuration uses `pitch_velocity_sign: -1.0`, matching the observed hardware behavior where negative pitch speed drove all units toward the +25 degree limit.

面向多台 SIYI ZR10 的可扩展协同观测控制框架。当前示例配置包含：

- `gimbal_01`: `192.168.144.25`
- `gimbal_02`: `192.168.144.26`
- `gimbal_03`: `192.168.144.27`

高层策略只输出每台吊舱的目标局部 AE：

```python
{
    "gimbal_01": AETarget(azimuth_deg=15.0, elevation_deg=-10.0),
    "gimbal_02": AETarget(azimuth_deg=15.0, elevation_deg=-10.0),
    "gimbal_03": AETarget(azimuth_deg=15.0, elevation_deg=-10.0),
}
```

设备层负责角度转换、限幅、闭环控制、姿态反馈和日志记录。

## v2.0 解决的关键问题

用户实测日志显示：

1. 三台设备同时连接时，固件查询曾集中超时。
2. 后续三台均能连接并读取姿态，但连续 12 秒无法到达初始 AE。
3. 旧代码运动阶段只使用 `rotate_nowait()`，即使吊舱未执行也不会报错。
4. 退出时也用无应答停止命令，不能确认设备已停。
5. `tools/*.py` 可能导入旧版本的可编辑安装，而不是当前目录代码。

v2.0 改为：

- 设备逐台连接、独立重试并设置连接间隔；
- 默认使用带 ACK 的 `rotate()` 速度命令；
- ACK 超时后才降级到 `rotate_nowait()`，并在日志中标记；
- 停止命令默认带 ACK，并重复发送；
- 启动时每秒显示实际角度、目标角度、速度命令和 ACK 状态；
- 反馈过期时立即停止，不继续使用旧姿态闭环；
- 策略阶段切换时强制发送新命令；
- 工具脚本强制优先导入当前项目目录；
- 主程序打印版本和实际导入路径；
- CSV 增加 `ack_received`、`fallback_used`、`feedback_source`、
  `consecutive_command_errors` 等诊断字段。

## 1. 安装

进入项目目录：

```bash
cd ~/zr10/test/zr10_cooperative_observation_v2_0
conda activate zr10
```

先确保 SIYI SDK v2 已安装：

```bash
python -m pip install -e ~/zr10/test/siyi_sdk-siyi-sdk-v2
```

清理旧版项目的可编辑安装，再安装当前版本：

```bash
python -m pip uninstall -y zr10-cooperative-observation
python -m pip install --no-deps -e .
```

确认实际导入位置：

```bash
python -c "import zr10_coop; print(zr10_coop.__version__); print(zr10_coop.__file__)"
```

必须显示：

```text
0.4.0
.../zr10_cooperative_observation_v2_0/zr10_coop/__init__.py
```

## 2. 软件自检

```bash
python tools/smoke_test.py
python -m unittest discover -s tests -v
```

这两项不控制真实吊舱。

## 3. 网络与通信检查

```bash
python tools/network_check.py --config config/three_zr10.yaml
```

三台设备均应显示：

- `ping=True`
- `SDK:37260=OK`

RTSP 只影响视频，不影响 AE 控制。

## 4. 清理遗留状态

```bash
python tools/recover_devices.py --config config/three_zr10.yaml
```

该工具会逐台执行：

- 固件查询；
- 带 ACK 的零速度停止；
- 关闭旧姿态推流；
- 读取当前姿态。

## 5. 真实硬件运动诊断

确认吊舱周围无障碍、线缆不会缠绕，然后运行：

```bash
python tools/hardware_diagnose.py --config config/three_zr10.yaml
```

它会逐台进行很小的 yaw 和 pitch 速度脉冲，并读取前后角度变化。正常结果：

```text
RESULT: yaw_motion=True, pitch_motion=True
```

只有三台都通过后，再运行协同策略。

## 6. 三吊舱协同验证

```bash
python run_cooperative_observation.py \
  --config config/three_zr10.yaml \
  --sdk-log-level INFO
```

初始化时应看到：

```text
[INIT] gimbal_01 ... speed=... status=velocity_acknowledged
```

正式策略运行时应看到：

```text
status=velocity_acknowledged, ack=True, fallback=False
```

如果显示：

```text
status=velocity_fallback_nowait
```

表示运动命令 ACK 超时，但程序已发送无应答降级命令。偶发一次可以继续观察；持续出现则需要检查交换机、网线、供电和设备响应。

## 7. 三路视频

另开一个终端：

```bash
cd ~/zr10/test/zr10_cooperative_observation_v2_0
conda activate zr10
python tools/multi_video_viewer.py --config config/three_zr10.yaml
```

视频程序与控制程序分进程运行，避免 RTSP 解码阻塞控制循环。

## 8. 关键配置

每台设备默认：

```yaml
control_mode: velocity_p
velocity_use_ack: true
velocity_ack_fallback_nowait: true
yaw_kp: 2.0
pitch_kp: 2.0
minimum_speed: 10
yaw_speed_limit: 30
pitch_speed_limit: 30
```

首次调试不要提高速度上限。

如果某台左右方向相反：

```yaml
azimuth_to_yaw_sign: -1.0
```

如果上下方向相反：

```yaml
elevation_to_pitch_sign: -1.0
```

如果仅想跳过“必须到达初始 AE”的检查以观察后续策略，可临时设置：

```yaml
startup_initial_required: false
```

这只用于调试，正式实验建议恢复为 `true`。

## 9. 日志

每次运行生成独立目录：

```text
logs/<session_id>/
├── telemetry.csv
├── events.csv
├── session_metadata.json
└── logger_summary.json
```

`telemetry.csv` 包含：

- 策略目标 AE；
- 实际 AE、yaw、pitch、roll；
- 角速度；
- P 控制误差与速度命令；
- 命令是否发送；
- 是否收到 ACK；
- 是否使用无应答降级；
- 命令耗时与多设备批次时间偏移；
- 反馈来源、反馈延迟和过期状态；
- 连续命令错误次数；
- 目标跟踪误差和是否进入容差。

## 10. 扩展策略

新策略继承：

```python
from zr10_coop.policies.base import CooperativePolicy
```

并实现：

```python
def compute(self, context: PolicyContext) -> PolicyDecision:
    ...
```

策略只负责产生每台设备的 `AETarget`。不得直接调用 SDK，以保证算法层与硬件层解耦。
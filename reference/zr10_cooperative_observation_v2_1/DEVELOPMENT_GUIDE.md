# 开发指导：多 ZR10 协同观测框架 v2.0

## 1. 分层结构

```text
策略层 Policy
    输出 {gimbal_id: AETarget}
        ↓
调度层 CooperativeObservationSystem
    并发下发、健康检查、节拍、日志
        ↓
设备层 ZR10Device
    AE转换、限幅、反馈缓存、控制器、可靠发送
        ↓
SIYI SDK v2 / UDP 37260
```

视频检测、目标跟踪与多站融合通过 `ObservationProvider` 接入，不应直接写入设备层。

## 2. 目标 AE 与设备角度

当前 frame 为：

```text
gimbal_local_ae
```

策略的 azimuth/elevation 经过：

```python
LocalAETransformer.to_gimbal()
```

转换为 yaw/pitch。每台设备可独立设置：

```yaml
azimuth_to_yaw_sign:
elevation_to_pitch_sign:
yaw_offset_deg:
pitch_offset_deg:
```

未来使用全局 ENU AE 时，应新增标定变换类，不修改策略接口。

## 3. 可靠速度闭环

`velocity_p` 控制律为：

```text
yaw_speed   = quantize(saturate(Kp_yaw × yaw_error))
pitch_speed = quantize(saturate(Kp_pitch × pitch_error))
```

死区内速度为 0；死区外设置最小速度，避免指令过小无法克服静摩擦。

v2.0 默认调用：

```python
await client.rotate(yaw=..., pitch=...)
```

该命令等待 ACK。只有 ACK 超时时才调用：

```python
await client.rotate_nowait(...)
```

降级状态会写入：

```text
command_status
ack_received
fallback_used
last_error
```

## 4. 添加新设备

在 YAML 的 `gimbals` 中添加一项即可。设备 ID 与 IP 必须唯一。所有设备可以使用相同端口 37260 和 8554，因为 IP 不同。

## 5. 添加新策略

新建：

```text
zr10_coop/policies/my_policy.py
```

实现：

```python
class MyPolicy(CooperativePolicy):
    name = "my_policy"

    async def initialize(self, device_ids):
        self.device_ids = tuple(device_ids)

    def compute(self, context):
        targets = {
            device_id: AETarget(
                azimuth_deg=...,
                elevation_deg=...,
                source=self.name,
            )
            for device_id in self.device_ids
        }
        return PolicyDecision(
            targets=targets,
            phase="...",
            diagnostics={
                "reward": ...,
                "fim_logdet": ...,
            },
        )
```

然后在 `policies/factory.py` 注册。

## 6. 接入视频与估计

建议每台视频流使用独立读取线程，只保留最新帧。检测、关联、三维估计和融合结果由 `ObservationProvider.collect()` 返回，策略从 `context.observations` 读取。

控制循环中不要执行阻塞式模型加载、视频解码或磁盘写入。

## 7. 标准调试顺序

```text
网络检查
→ recover_devices
→ hardware_diagnose
→ 单次主程序
→ 连续运行两次
→ 同时开启三路视频
→ 再修改策略
```

每次故障先检查终端中的：

```text
actual
speed
status
ack
fallback
```

再查看最新会话的 `events.csv` 和 `telemetry.csv`。

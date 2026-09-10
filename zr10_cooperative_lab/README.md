# ZR10 协同观测实验平台 v3.0

这是一个面向多智能体决策研究的 Python 实验项目。默认配置四台设备 `192.168.144.25～28`，支持先离线仿真，再把同一策略接到 ZR10 实机。核心任务是通过设备分工、方位/俯仰调整及可选镜头控制，持续构造同一目标至少被两台设备有效观测的几何条件。

**建议先运行仿真，再阅读 `docs/算法开发.md`。你主要修改策略模块和 YAML，而不必修改网络、视频、定位或记录器。**

## 1. 十分钟跑通

建议使用 Python 3.11 或 3.12；核心代码兼容 Python 3.10+。本次验收环境详见 `samples/validation/VERIFICATION.json`。YOLO/PyTorch/CUDA 是否支持你选用的 Python 和显卡版本，需按其对应安装包匹配；仿真不依赖 YOLO、CUDA 或设备。

在本 README 所在目录打开 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[analysis,learning]"
.\.venv\Scripts\python.exe -m zr10lab validate
.\.venv\Scripts\python.exe -m zr10lab run --duration 60
```

终端输出本次 `runs/sim_时间戳` 目录。复制它作为后续命令的 `会话目录`：

```powershell
.\.venv\Scripts\python.exe -m zr10lab analyze "会话目录"
.\.venv\Scripts\python.exe -m zr10lab monitor "会话目录"
```

双击会话目录的 `report.html` 可看统计与三维轨迹；PNG/PDF 图表可用于分析报告。也可以双击 `run_demo.cmd`（需要先安装项目）。

同时查看运行状态：一个终端运行 `run --realtime --duration 120`，另一个运行 `monitor runs`。桌面监视器只读取日志，显示站点、轨迹、实测/预测状态、实时角度与指标，不占用控制连接。

## 2. 你提出的任务如何落到代码

| 研究需求 | 实现位置/选择方式 |
|---|---|
| 一台设备一个智能体，可增减台数 | `DeviceConfig`、`Telemetry`、`Action`，修改 `devices` 列表 |
| 设备位置可按现场输入 | 每台 `position_m`，以及不可省略的 `mount_rpy_deg` 安装姿态 |
| 算法独立接收输入、生成动作 | `PolicyContext → Policy.decide → Decision`，`policies.py` 或自定义插件 |
| 方位、俯仰、变焦、聚焦及其他参数 | `actions.py` 能力注册表；算法掩码与固件能力双层检查 |
| 只研究方位/俯仰 | `action_space.enabled: [yaw_deg, pitch_deg]`，其余维度保持 |
| 协同覆盖扫描 | `configs/scan.yaml`；设备成对观测同一空间扫描点 |
| 单目标多站居中跟踪定位 | `configs/single_target.yaml`；`policy.mode: center` |
| 多目标共享视场，不要求居中 | `policy.mode: multi`；校准后的检测像素独立转世界射线 |
| 动目标连续三维定位 | 时间门控、射线交会、几何互斥关联、CV Kalman 轨迹与失联预测 |
| YOLO 无人机识别 | `vision.py`，自有 `.pt`；另有 ONNX 和自定义 Detector 接口 |
| 后续学习算法 | `learning.py` Gymnasium 环境，固定槽位、掩码、种子与奖励 |
| 全过程规范 CSV | `recording.py`，11 张表、元数据、配置快照和 SHA-256 校验 |
| 后处理与复现 | `analyze`、`replay`、`samples/validation`、完整测试 |

`roll_deg` 会参与定位变换，但没有冒充 ZR10 已支持的独立滚转动作。自动光圈、自动白平衡以及当前 SDK 未核实的曝光/增益接口，也在注册表中明确标为只读或不支持。软件建模覆盖可讨论的参数边界，实际发送只使用经过核验且在设备上启用的接口。

## 3. 接入四台实机

1. 四台设备分别配置为 `.25、.26、.27、.28`，控制端口默认 `37260`。电脑有线网卡使用同网段、未占用的静态地址，例如 `192.168.144.100/24`。交换机无需特殊路由；避免网卡或其他设备地址冲突。
2. 解压随附的固定 SDK 快照并安装；这样实验不会因分支自动更新而改变行为。
3. 将你的 YOLO 权重放到 `models/drone.pt`，修改 `detector.classes` 为你模型的无人机类别编号。仿真不会加载这个文件。

```powershell
Expand-Archive -LiteralPath vendor/siyi_sdk_v2_snapshot.zip -DestinationPath vendor/sdk
.\.venv\Scripts\python.exe -m pip install ./vendor/sdk/siyi_sdk
.\.venv\Scripts\python.exe -m pip install -e ".[vision,analysis,learning]"
.\.venv\Scripts\python.exe -m zr10lab probe --config configs/four_zr10.yaml
.\.venv\Scripts\python.exe -m zr10lab.viewer --config configs/four_zr10.yaml
.\.venv\Scripts\python.exe -m zr10lab.viewer --config configs/four_zr10.yaml --detect
```

`probe` 只查询固件和姿态，保存 `probe_result.json`；它不转动设备。`viewer` 仅接视频，`--detect` 用你的模型在后台推理。ZR10 示例视频地址为 `rtsp://192.168.144.25:8554/main.264`，可逐台改成实际地址。

`viewer` 需要带 GUI 的 `opencv-python`；不要在同一虚拟环境同时安装它与 `opencv-python-headless`。无图形桌面的服务器可只运行控制/融合与CSV，不启动viewer。

4. 测量并填写每台站点坐标、安装姿态、角度正负与偏置；标定每个拟用倍率的内参、畸变、视频时延及不确定度。示例里这些值用于仿真，**不代表你的真实设备**。
5. 用独立控制点验证标定误差和上空区域可达性，随后为已完成的设备设置 `calibration_verified: true`。
6. 启动实机闭环：

```powershell
.\.venv\Scripts\python.exe -m zr10lab run --mode hardware --config configs/four_zr10.yaml --duration 60 --arm
```

`Ctrl+C` 会结束任务、尝试停止云台及连续聚焦/变焦、关闭视频进程并刷新日志。实机启动默认要求全部配置设备连接；运行中失去设备后基线会使用可用设备重新分配。单个设备失联不会阻塞其他设备。设置 `require_all_devices: false` 时启动至少需要两台。

**上空观测不能仅输入站点坐标。** 云台本地正俯仰范围可能无法直接覆盖天顶。要结合实际支持的安装方式与现场姿态标定做可达性检查；示例安装俯仰 `25°` 只是几何仿真外参，不是对真实安装方式的保证。

旧版中的 `pitch_velocity_sign: -1` 已作为示例保留。速度指令正负和姿态角正负分别配置；请通过实测核验，不能只修改其中一个。`yaw_speed_limit/pitch_speed_limit` 是 SDK 速度等级，不是度/秒。`max_slew_dps` 用于仿真与策略转动代价估计，需要用实测曲线更新。

## 4. 从哪里开始设计算法

```python
from zr10lab.models import Action, Decision

class MyPolicy:
    def __init__(self, cfg):
        self.cfg = cfg

    def reset(self):
        pass

    def decide(self, context):
        # context.devices: 实测设备状态；context.detections: 检测框；
        # context.rays: 世界射线；context.tracks: 已估计的三维轨迹。
        # 这里是最简单保持策略，实际可替换为优化、博弈、MPC、MARL 等。
        actions = {
            key: Action(key, yaw_deg=s.yaw_deg, pitch_deg=s.pitch_deg,
                        issued_t=context.t, ttl_s=0.5, reason="my_policy")
            for key, s in context.devices.items() if s.connected
        }
        return Decision(actions)
```

完整模板见 `examples/my_policy.py`。将 `policy.name` 改为 `custom` 并设置文档中的工厂路径即可接入。所有动作都要遵守 `enabled` 掩码；`None` 表示保持当前参数。`ActionValidator.validate()` 不改变原请求，`resolve()` 只在执行层把实测焦距映射为倍率，因此日志保留你算法原本输出的参数。

```powershell
.\.venv\Scripts\python.exe -m examples.train_random --config configs/four_zr10.yaml --steps 50
```

这是接口示例，不是已训练好的决策模型。学习环境是一个集中式联合动作 Gym 环境，设备槽位可供你自行封装分布式 actor；不是已经训练或声称完整实现某个 MARL 框架。

## 5. 定位与连续性的含义

单个目标必须至少拥有两个不同站点、时间兼容、几何条件合格的观测。单站搜索时策略可用一个假设距离引导其他站点；这只是搜索点，不写成定位结果。

多目标共视场模式对每个检测中心去畸变后生成独立射线，利用设备位置及实测姿态转换到 ENU；不把像素差简单当成固定度数，也不把两站设备光轴当成所有目标的视线。

`tracks.csv` 的 `measured=True` 表示该周期由新的多站定位结果更新；`measured=False` / `status=coasting` 表示暂失后的预测。预测超过阈值删除。基线没有使用仿真真值 ID 做关联；检测类别只用于兼容性筛选。同类目标发生遮挡、交叉或近似共面时，纯几何可能歧义，诊断会记录，实际可接外观特征提高身份连续性。

普通 RTSP 接收时刻不是相机曝光时刻。平台使用 `接收单调时刻－实测视频延迟` 作为估计，保存不确定度，并匹配姿态历史。目标运动和云台运动引起的时间误差会进入协方差。严要求高速测量应进一步改用能提供可信采集时间戳的采集链路；仅同接一台交换机不等于硬件同步。

## 6. 数据、回放和其他场景

```powershell
# 单目标居中
.\.venv\Scripts\python.exe -m zr10lab run --config configs/single_target.yaml
# 扫描覆盖
.\.venv\Scripts\python.exe -m zr10lab run --config configs/scan.yaml
# 设备掉线后重分配
.\.venv\Scripts\python.exe -m zr10lab run --config configs/outage.yaml
# 按原射线与周期重新融合，不访问设备
.\.venv\Scripts\python.exe -m zr10lab replay "会话目录"
```

`replay` 用于更换关联/定位/轨迹融合参数后重处理已记录射线。它不重新执行过去的云台动作，不代表评估另一个策略改变相机视场后的反事实结果。比较不同控制策略请用相同种子仿真或重新进行现场实验。

记录表：`telemetry`、`telemetry_stream`、`detections`、`rays`、`localizations`、`tracks`、`actions`、`commands`、`events`、`cycles`、`truth`。共 11 张业务表；其中 `truth` 仅仿真有值，`telemetry_stream` 保存实机原始姿态回调。完整字段解释见 `docs/数据字典.md`。相机原始视频不是 CSV 数据，不默认长期保存图像；需要识别模型重训数据时可扩展 Detector/FrameSource 保存抽样帧。

记录器使用有界队列和独立写盘线程。磁盘失败或队列满会使实验失败，不静默丢弃关键数据。每个会话保存配置快照、平台版本、时钟定义、完成状态与每张 CSV 的 SHA-256。掉电时尚未 flush 的部分仍可能丢失；异常终止的会话由 `completed: false` 标识。

## 7. 项目导航

```text
configs/                  四站、多目标、单目标、扫描和掉线场景
zr10lab/models.py         学习数据接口的第一站
zr10lab/config.py         配置/继承/校验
zr10lab/actions.py        参数注册、动作掩码、实测焦距换算
zr10lab/policies.py       可替换决策算法和协同基线
zr10lab/learning.py       Gymnasium 联合动作环境
zr10lab/hardware.py       每台独立 SDK 连接、反馈、控制与看门狗
zr10lab/vision.py         YOLO/ONNX/自定义模型、最新帧管线
zr10lab/geometry.py       内参、像素射线、坐标变换与三角定位
zr10lab/fusion.py         多目标关联、轨迹管理和预测
zr10lab/calibration.py    棋盘格/控制点标定命令
zr10lab/timing.py         帧时刻姿态插值和有效性检查
zr10lab/simulation.py     可复现目标/设备/检测仿真
zr10lab/runtime.py        实验闭环编排
zr10lab/recording.py      CSV 写入及数据校验
zr10lab/metrics.py        覆盖率、定位连续性、RMSE与ID切换
zr10lab/analysis.py       离线统计/绘图/射线重放
zr10lab/monitor.py        只读桌面状态面板
zr10lab/viewer.py         只读四路视频预览
docs/                     中文专题教程与需求设计说明
examples/                 策略/学习/标定示例
tests/                    数值、接口、异常与闭环测试
vendor/                   已核验SDK源码快照、许可证及来源哈希
samples/validation/       实际生成的仿真CSV、图表和验收结果
```

## 8. 验证与已知边界

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,analysis]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe tools/verify_release.py
```

提供的是完成软件集成验证的研究平台；此交付没有接触你的真实设备，也没有你的 YOLO 权重，因此现场连接、固件动作范围、识别效果、端到端视频延迟与定位精度需要按手册验收。实机适配使用指定 SDK 的真实 API，测试用模拟客户端验证控制语义、异常停机与多设备独立性。

仿真模拟几何视场、像素噪声、检测丢失、机械转速/倍率变化、掉线及目标运动。聚焦/HDR/录像等非几何参数保留为仿真状态元数据，不模拟其真实光学或传感器效果；编码切换明确拒绝用于几何仿真。它不替代设备动力学辨识或真实识别模型评估。

参考资料与旧版审计见 `docs/需求与架构.md`。官方中英文 ZR10 参数存在差异，因此没有将产品宣传数值直接当成可靠的实测内参或固件能力。

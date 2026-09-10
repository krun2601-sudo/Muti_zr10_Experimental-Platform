# ZR10 协同观测实验平台 v4.0 · 总控制中心

在现有 v3 平台上增加可选的本机监视与控制界面，保留原有无界面实验、算法、SDK、检测、定位、日志和分析接口。

## 开始使用

请在 `zr10_cooperative_lab` 项目根目录打开 PowerShell。已有项目 `.venv` 时，打开界面：

```powershell
.\.venv\Scripts\python.exe -m zr10lab console --config configs/control_center.yaml
```

也可双击 `启动控制中心.cmd`。默认打开仿真待机界面，在页面选择模式并开始；仿真不连接真实设备或加载 YOLO。

首次安装：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

如果只使用仿真和界面，可安装较小的依赖集合：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[analysis]"
```

总控制中心不增加 Python GUI/Web 框架依赖，也不需要 Node.js 或 npm。Three.js r180 和 MIT 许可证随项目打包，运行时没有 CDN 请求。

## 逐次选择是否打开界面

```powershell
# 按原配置启动实验并弹出界面。
.\.venv\Scripts\python.exe -m zr10lab run --duration 60 --ui

# 明确不打开界面。
.\.venv\Scripts\python.exe -m zr10lab run --duration 60 --no-ui

# 打开实机控制中心，等待在页面开始实验。
.\.venv\Scripts\python.exe -m zr10lab console --mode hardware --config configs/control_center.yaml
```

实验结束后窗口保留，方便检查和再次运行。终端 `Ctrl+C` 关闭后台并尝试停机。页面关闭或心跳丢失时暂停界面控制的实验，页面重连后需要显式恢复。

## 功能

- 设备实时 A/E、横滚、倍率、反馈年龄、连接状态，以及与目标指令分开的执行反馈。
- 单台手动控制、初始化至配置姿态、接管/交回算法、停止本台、暂停、恢复和急停锁存。
- 可选四路视频预览，复用算法视频源；仿真视图明确标记来源。
- 手动、保持、固定姿态定位、覆盖扫描、单站图像跟踪、中心跟踪定位、多目标协同定位，以及配置注册的自定义模式。
- 从安装姿态、实际反馈角度、实际倍率内参和畸变计算的三维矩形视场；ROI、设备和测量/预测轨迹。
- 停止状态下编辑连接、位置、安装姿态、初始化、限位、相机和算法配置，另存 YAML，重载算法。
- 沿用原有 CSV 数据格式，记录界面操作和完整实验数据。

真实有效视场需要正确标定与新鲜反馈。图中截断距离只用于显示，不是设备实测识别距离；毫米焦距只有在实测焦距表存在时才可推导。未支持或未启用的硬件参数不会被伪装成可执行操作。

## 文档和算法入口

- [总控制中心完整教程](docs/总控制中心.md)：操作、模式、配置、视场含义和自定义算法。
- [原平台使用说明](README.md)：安装、CSV、算法、校准和无界面运行。
- [坐标标定与定位](docs/坐标标定与定位.md)。
- [硬件与模型接入](docs/硬件与模型接入.md)。
- [算法开发](docs/算法开发.md)。

算法仍通过 `PolicyContext → decide() → Decision(actions)` 接入。界面不读取仿真真值决定动作，自定义模式注册在 `control_center.modes` 中；修改源代码后暂停并重新加载，或重新开始实验即可使用。

## 版本与验证

完整离线测试和验收结果保存在 `samples/validation`。实机、现场标定与用户 YOLO 权重需要在实验台验证；离线软件验证不代表现场精度。

本次保留了修改前的 `configs/four_zr10.yaml.pre_console.bak`，并纠正了原配置中 `calibration_verified: ture` 的布尔拼写。`true` 只是操作者的配置标记，不自动产生标定结果。

原 `README.md` 被外部程序占用时不会强行关闭该程序或覆盖未保存内容，v4 的新增说明以本文件和 `docs/总控制中心.md` 为准。

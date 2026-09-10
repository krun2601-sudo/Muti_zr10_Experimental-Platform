"""自定义算法最小示例：以“最久未获得新测量”的轨迹优先调度。

配置 ``policy.name: custom`` 和 ``policy.custom: examples.my_policy:MyPolicy``。
在项目根目录运行以使 examples 可以导入。也可把自己的模块安装成包。
"""
from __future__ import annotations

from dataclasses import replace

from zr10lab.models import Decision, PolicyContext
from zr10lab.policies import CooperativePolicy


class MyPolicy(CooperativePolicy):
    """复用设备可达性、共同视场、成对扫描，仅替换目标优先级。

    这段代码展示输入/算法/输出的边界。正式研究可直接实现 Policy，
    使用 context.detections/rays/tracks 构造特征，再返回 Decision(actions)。
    不应在 decide 中阻塞视频采集、不直接调用 SDK、不读取仿真真值。
    """

    def decide(self, context: PolicyContext) -> Decision:
        # 用估计轨迹最近一次真实测量时间排序；最多处理两个久未更新目标。
        # 切片只修改本轮输入视图，不修改共享 Track 对象或融合器内部状态。
        prioritized = sorted(context.tracks, key=lambda tr: (tr.last_seen_t, tr.track_id))[:2]
        decision = super().decide(replace(context, tracks=tuple(prioritized)))
        return Decision(decision.actions,
                        {**decision.diagnostics, "custom_priority": [tr.track_id for tr in prioritized]})

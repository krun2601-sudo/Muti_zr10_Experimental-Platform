# Results and Discussion：证据驱动草稿

> 用途：作为论文正式 Results & Discussion 的内容骨架。所有结论均来自冻结实验，不允许依据写作需要重新调算法或重跑 held-out 主测试。最终英文稿应保持同等证据强度。

## 1. Overall performance: discovery–continuity trade-off

正式 held-out 主测试包括 S0、S10、S11 和 S7，每个场景 20 个随机种子，共 560 个有效运行。所有方法使用相同目标真值、感知模型、执行模型和决策机会；参数化基线均在独立 validation split 上完成调参并冻结。

总体结果表明，不同方法在“尽快发现目标”和“发现后维持连续可见”之间形成了明显不同的取舍。`info_planner` 获得最低 missed-target rate 和最短 detection delay，但其 total monitoring loss 和 maximum loss gap 明显高于其他强方法。这说明仅以发现/信息价值为中心的调度并不能自然保证发现后的连续监视。

ECP-RH 的 missed-target rate 为 0.0177，同时将 total loss 和 max gap 控制在 9.00 s 和 1.49 s。与 `info_planner` 相比，ECP-RH 的 total loss 平均降低约 156.8 s，max gap 降低约 40.3 s；与 `ssm_belief` 相比，相应降低约 21.6 s 和 2.86 s。上述连续监视优势在 paired tests 中均显著。相反，`info_planner` 和 `ssm_belief` 在 detection delay 上优于 ECP-RH。因此，主结果支持的不是“ECP-RH 在所有指标上最优”，而是：**显式保护已发现目标的连续可见性能够显著减少监视中断，同时维持较低的漏检率。**

建议英文核心句：

> The results reveal a clear discovery–continuity trade-off. Information-driven planners detect targets earlier, whereas ECP-RH substantially reduces post-discovery visibility loss and long monitoring gaps while retaining a low missed-target rate.

## 2. Comparison with tuned weighted receding-horizon planning

`weighted_rh` 与 ECP-RH 共享候选原语、预测模型、执行约束、soft-overlap 变量和 decision opportunities，仅将词典序优先级替换为有限加权和，因此是检验 priority formulation 的最直接结构对照。

总体上，两者性能接近：ECP-RH 的 miss rate 和 max gap 更低，而 weighted-RH 在 detection delay、total loss 和 revisit-age P95 上略有优势。五个总体主指标的 paired tests 均未显示 ECP-RH 对 tuned weighted-RH 的全面显著优势。

在 S7 overload 中，ECP-RH 的 miss rate 为 0.0583、max gap 为 2.84 s，而 weighted-RH 分别为 0.0917 和 6.11 s；另一方面 weighted-RH 的平均 total loss 和 revisit 仍略低。该现象与 priority formulation 的设计动机一致：当资源不足以同时优化全部目标时，词典序结构倾向于首先保护高优先级可见性指标，而不是依赖固定权重进行尺度折中。不过由于 paired significance 不充分，这里应解释为 **design-consistent trend**，不能宣称统计意义上的全面 superiority。

建议英文核心句：

> Compared with a validation-tuned weighted receding-horizon baseline using the same physical action model, ECP-RH delivers comparable overall performance. Its main advantage is therefore not a universal numerical gain, but an explicit task hierarchy that avoids finite-weight trade-offs and exhibits a continuity-oriented trend under overload.

## 3. Why execution-aware sensor-time modeling matters

`no_execution_model` 消融提供了最清晰的机制证据。去掉 slew/zoom/settle transition 后，规划器将尚未到位的设备错误地视为可立即执行 sensing，从而破坏 search、discovery 和 monitoring 之间的时间一致性。

在 S9a 中，去掉 execution model 后 miss rate 增加 0.133，detection-delay P95 增加约 17.7 s，total loss 增加约 29.3 s，revisit-age P95 增加约 42.2 s。S9b 下影响更强：miss rate 增加 0.300，detection delay 增加约 14.0 s，total loss 增加约 23.8 s，max gap 增加约 13.7 s，revisit P95 增加约 73.6 s，并且五个主指标均出现显著退化。

该结果直接支持本文的 execution-level sensor-time formulation：对窄视场 PTZ/EO 设备而言，slew、zoom 和 settling 不是低层控制细节，而是决定 sensor availability 的任务资源。

建议英文核心句：

> Removing the execution model causes the planner to allocate sensing utility before a device can physically become measurement-ready. The resulting degradation across discovery, continuity, and revisit metrics confirms that slew, zoom, and settling time must be modeled as part of the scheduling resource rather than treated as negligible low-level dynamics.

## 4. Look-ahead horizon and zoom-dependent sensing quality

### 4.1 Prediction horizon

`short_horizon` 消融和 horizon sensitivity 给出了高度一致的结果。1–2 s horizon 在 S4 和 S8 上均产生 100% missed-target rate；3 s 及以上恢复正常发现。S4/S6 的正式消融中，short horizon 同样导致严重 discovery failure。

这里需要特别解释：由于 post-discovery loss 只在目标被发现后计算，完全漏检会让 loss/gap 产生虚假的“小值”。因此本文必须同时报告 missed-target rate 和 censored detection delay；这正是 anti-cheat evaluation design 的意义。

建议英文核心句：

> A short horizon can appear deceptively favorable in post-discovery loss because targets are never acquired. Once discovery failure is explicitly accounted for, the experiments show that sufficient look-ahead is necessary to form executable search-to-monitor transitions.

### 4.2 Zoom

固定 zoom 在 S2/S6 中显著提高 missed-target rate 和 detection delay，在 S5 中则显著增加 monitoring loss 和 max gap。这表明 zoom 不是独立的“视觉质量旋钮”，而是同时改变 FOV 和有效目标像素尺度，从而影响 discovery 与 monitoring 两类 sensing validity。

因此，论文应将 zoom-dependent FOV 和 quality threshold 作为 execution/sensing coupling 的一部分，而不是简单强调“联合优化 pan/tilt/zoom”。

## 5. Uncertainty-aware visibility: reliability rather than universal performance gain

去掉 uncertainty envelope 后，平均主指标并没有在所有场景统一恶化，因此不能把 uncertainty awareness 表述成“全面提高性能”。其更可靠的证据来自 risk-specific metrics。

在 S9b delay/noise 场景中，完整 ECP-RH 的 empirical risk-violation rate 约为 0.24%，而 no-uncertainty 约为 0.85%；handover success rate 分别约为 98.75% 和 92.92%。这说明 covariance-aware A/E margins 的主要作用是降低预测可见性失效风险并提高交接可靠性，而不是保证平均 detection/loss 指标单调改善。

建议英文核心句：

> The uncertainty envelope should be interpreted as a reliability mechanism rather than a generic performance booster: it reduces empirical visibility-risk violations and improves handover reliability under delayed/noisy beliefs, although average task metrics are not uniformly improved.

## 6. Mechanisms with limited empirical support

### 6.1 Soft handover overlap

`no_overlap` 在 S4/S11 上没有呈现一致的 primary-metric 或 handover-metric 改善；S11 中部分 handover 指标甚至略有反向变化。因此 soft overlap 不应单独作为主要创新贡献。它可以保留为避免硬 overlap 造成 infeasibility 的辅助建模工具。

### 6.2 Event-triggered replanning

`no_event_replan` 在 S2/S4/S11 上总体中性，部分指标略优。当前数据不足以支持“event replanning 显著改善连续跟踪/交接”的声明。正文应将其描述为 implementation option，而不是 contribution。

### 6.3 Shared-FOV primitive

`no_shared_fov` 在 S5/S6 的影响较小且方向混合。可以保留该 primitive 以允许一个设备在同一 FOV 中服务多个目标，但不应把它作为独立实验结论。

## 7. Sensitivity and timing interpretation

### 7.1 Replanning period

更快重规划不等于更好。0.25 s replan period 在 S4/S8 中分别产生约 30.5 s 和 37.5 s total loss，而 nominal 0.5 s 分别约 1.12 s 和 7.18 s。原因是当转动和 settling 需要非零时间时，过快重规划会频繁改变目标指向，使设备难以形成稳定 sensing interval。

该结果是 execution-aware scheduling 的重要补充：调度器不仅要“算得快”，还必须尊重动作完成与观测驻留的时间尺度。

### 7.2 Perception / uncertainty parameters

在 S4/S8 panel 中，Pd=0.8–1.0、position noise=0.25–4 m、visibility risk=0.01–0.2 均维持 0 missed targets。可以据此说明 discovery outcome 在测试范围内具有一定参数容忍度；但 loss/revisit 等指标仍有非单调变化，因此不使用“globally robust”表述。

## 8. OOD results and method boundary

OOD 实验给出一个重要负面边界。S9a fast-target 场景下 ECP-RH 仍保持低 miss 和较小 monitoring loss；但 S9b delay/noise 中，weighted-RH 在 detection delay、total loss 和 max gap 等指标上整体更强。

这意味着当前 ECP-RH 的主要弱点不是 MILP 求解，而是预测 belief 与候选 visibility 依赖输入状态质量。当 delay/noise shift 使预测误差增加时，严格的 priority hierarchy 可能为不准确的 predicted visibility 分配过多资源，而 tuned weighted-RH 的有限折中有时更宽容。

建议英文核心句：

> The delayed/noisy OOD condition exposes an important limitation: ECP-RH relies on the quality of the predicted belief used to construct executable visibility primitives. Under this shift, the tuned weighted baseline can outperform the strict priority policy on several aggregate metrics.

该结果应保留在 Discussion，而不是隐藏；它为后续研究提供了明确方向：delay-aware belief propagation、candidate robustness、adaptive priority relaxation 或 uncertainty-calibrated horizon design。

## 9. Computational behavior and scalability

正式主测试中，ECP-RH visibility-level certification 为 100%，solver timeout 为 0%，完整 priority certification 平均约 93.3%；OOD 中分别为 100%、0% 和约 93.5%。因此最高优先级监视目标在测试范围内始终获得 solver certification，但不能声称每次决策都完成全部四级词典序最优认证。

规模实验进一步表明，MILP solve 并不是当前主要瓶颈。即使 8 个目标、约 1500 个候选时，solver P95 仍约 82–99 ms，且无 timeout；相反，candidate generation 已增加到约 1.33–1.44 s，超过 nominal 0.5 s replan period。

建议英文核心句：

> The dominant scaling bottleneck is candidate construction rather than MILP optimization. This points to vectorized geometry evaluation, candidate pruning, caching, and parallel prediction as the most effective directions for real-time scaling.

需要透明说明一个 synthetic edge case：0 targets + 4 search candidates/device 时，execution-level lexicographic lock 出现数值 infeasibility，因此该点完整 priority certification 为 0；增加到 8/12 search candidates 后恢复正常。基础问题仍存在可行 incumbent，但该现象说明完整 priority certification 并非理论/数值上自动等于 100%。

## 10. Discussion synthesis

综合正式结果，本文最稳固的主线应为：

1. **任务层面**：未知目标到达使 persistent search 与 post-discovery continuous monitoring 同时竞争有限 sensor-time，单纯优化发现/信息价值不足以保证连续可见。
2. **方法层面**：ECP-RH 将 slew、zoom、settling 和 sensing-ready interval 纳入显式执行模型，以 lexicographic hierarchy 首先保护已发现目标的可见性，再利用剩余资源进行 persistent search。
3. **证据层面**：execution-model、horizon 和 zoom 消融提供强支持；uncertainty envelope 在 risk-specific reliability 指标上得到支持；priority formulation 相对 tuned weighted-RH 的优势主要是任务语义与 overload 下的方向性趋势，而不是全面统计优势。
4. **边界层面**：OOD delay/noise 下 weighted-RH 更具竞争力；高目标数时 candidate generation 成为实时瓶颈；event replanning、soft overlap 和 shared-FOV 当前没有足够证据作为独立贡献。

如果按照这一结构写作，论文的论证会比“本文方法所有表格都最好”更可信，也更符合正式实验实际支持的结论。

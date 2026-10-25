# 方法与实验口径核查清单

核查基线：研究分支归档提交 `94b30f4d100532779d2d25158b8a2e2fd607e05f`。本次仅阅读源码/配置和撰写报告，未修改源代码、配置、冻结输入或Git状态，未运行正式实验。路径未特别说明时相对于 `zr10_cooperative_lab/`。

## 已按实际代码修正的报告口径

1. **正式策略入口**：`runner.py`使用`paper_policies.build_paper_policy`。不能依据旧`policies.py`父类写固定扫描1×、跟踪5×；正式值是3×/6×。SSM正式包装层读取`ssm_belief`，旧父类`ssm`键不代表正式参数未生效。
2. **ECP-RH是四级词典序**：失观→软交接满足→搜索→执行成本；`optimization.py`而不是`planning.py`中旧`HorizonMILP`才是正式求解器。0.12 s是整次MILP预算，非每级各0.12 s；没有认证前级最优时不会继续锁定它优化低级。
3. **动作序列范围**：每次从各设备候选中选择一个终端视轴/倍率，预测其时域可见结果。不是联合优化六个独立未来动作。默认预测指向使用索引3，即2.0 s处位置。
4. **首可用槽**：代码`ceil(transition/slot)`直接成为从零起算槽索引；例如transition=0.25 s得到索引1，对应预测1.0 s。这比按“0.5 s已稳定”直接判索引0更保守。报告忠实说明索引规则，不悄悄修正并重算。
5. **软交接非二值**：q∈[0,1]且`views≥2q`，单视角可得q=0.5。不能把q的总和称为“完成的交接次数”。真实交接评价另由采样事件计算。
6. **搜索龄P95**：`batch._last_cycle_metrics`提取最后周期的63位置龄P95，不是整个试验所有时空采样的P95。搜索龄积分才覆盖整个运行。
7. **误检/失观区别**：监视失观依据设备就绪、投影和监视质量，不按随机检测是否成功判定。漏检目标没有发现后监视义务，必须联合报告漏检率和删失发现延迟。
8. **交接成功阈值**：`evaluation.py`把采样重叠后源视角退出且其他视角仍在计为成功，未强制重叠持续≥0.5 s。也不把所有失观后重捕获纳入交接分母。
9. **风险率支持范围**：仅ECP-RH/Weighted RH登记第一未来槽的匿名可见预测；空值不是0。旧预测会被事件重规划替换，出区不计违例，不能称整个轨迹的累计违约概率。
10. **感知超时字段未生效**：`VirtualPerception`读取`coast_timeout_s`，但目前没有据此删轨；仅出区时从belief中删除。不能写成3 s无观测后自动移除。
11. **敏感性含义**：position_noise只变测量噪声，不同步初始协方差/过程噪声；settle同时变物理就绪与规划转换模型。它们不是所有感知因素统一缩放的实验。
12. **消融不完全禁用行为**：`no_shared_fov`仅去掉共享指向候选，单目标动作可偶然覆盖多个目标；`fixed_zoom`改变搜索/跟踪候选为5×，保持候选仍可取初始1×或当前倍率；`no_uncertainty`保留固定和槽间运动裕量。
13. **Holm族与置信区间**：Holm按(scope,scenario,metric)校正该指标的六方法比较，不跨全部指标。summary_long为正态近似单方法均值CI；paired_comparisons为10,000次配对bootstrap的均值优势CI，两者不可混称。
14. **计时可比性**：启发式方法构造`SolverDiagnostics`时未显式写耗时，默认solve_ms=0；固定扫描没有同类solver对象。因此表中的0或空白不能说明实际免费。ECP-RH/Weighted的solve_ms主要对应MILP，完整决策耗时记录在extras/cycles中。
15. **扩展性不是闭环240任务**：固定四设备和同一合成状态，24组合×10计时重复。需要报告候选生成+完整决策耗时，不能只凭MILP预算或timeout_rate判断整体实时。
16. **随机种子不是随机轨迹**：VirtualTargetField轨迹由固定YAML决定。不同种子主要改变虚拟感知随机性；统计只覆盖固定场景面板内的噪声重复。

## 应保留在正文限制中的事项

- 三维匿名位置/速度是虚拟感知提供的受控观测，不是实机单目定位、真实检测或完整身份关联系统；`calibration_verified=false`。100 m与6/12像素阈值均为公开仿真假设，不能宣称实测性能。
- 63点搜索龄是离散采样指标；17,056点审计是距离/机械角可达性抽样，不证明连续区域始终双视角可见。
- 统计中S0无目标时漏检/删失延迟/失观为0，纳入总体指标会稀释有目标场景，因此分场景表不可省略。
- ECP-RH强优先可能牺牲搜索新鲜度，也可能在预算内只取得可行解。不能写所有场景所有指标全面优于各基线、所有消融都产生一致退化。
- 原始数据另显示：`no_execution_model`全部45个case漏检率1而post-discovery loss=0；必须解释条件指标陷阱。S9b的no_uncertainty总失观比full低16.82 s且显著；具体数字由结果章节的数据复算负责，本章节不重算。
- 正式基线中的classical_ptz/info_planner/ssm_belief属于思想适配。当前报告没有核实某篇论文与某实现的一一对应文献链，不能声称官方复现。
- 6/12像素阈值、参考目标尺寸、100 m上限不在已完成六项敏感性中。可在未来研究补充，但此次不新增任务或改动冻结设计。

## 复现和资料来源仍需区分的边界

| 项目 | 证据/当前判断 | 处理建议 |
|---|---|---|
| 历史24组调参的完全回放 | `baseline_tuning._budgeted_combinations`强制纳入“当前默认”；基础配置后来已同步获选参数 | 使用归档shard中的明确参数元组或历史验证提交；不要仅靠同一抽样seed声称最新配置重抽与历史必定相同 |
| geometry配置提交字段不一致 | manifest/runbook/configuration_audit写`2fdde56...`；selected JSON provenance写`5622315...` | 都保留，分别作为文档记录的配置修订链节点；若需认定哪个是“唯一配置提交”，必须查询Git历史和配置diff，不能擅自改哈希 |
| 严格环境重现 | Actions使用Python3.11，但依赖安装命令未逐版本锁定 | 用逐运行provenance记录环境；新电脑计时和限时MILP可行解可能不同 |
| 原始日志完整性 | 库中主要为指标、汇总、索引；大量逐周期日志曾在Actions Artifact | 53个正式原始ZIP已下载并通过SHA-256、字节数与全成员CRC校验，见raw_artifacts/manifest.json |
| ROI再次进入 | target_field按每步位置判断是否活动；perception出区删belief，但evaluator按truth_id保留累计记录 | 当前报告按代码定义写首次/最后活动差；若做离区再入的新实验，应额外定义一次目标/一次进入的统计单位 |
| 图形UI固定扫描已确认不一致 | 基础YAML fixed_scan策略字符串写`paper_policies:FixedScanReactivePolicy`（导入旧父类）；`ResearchControlCenter`调用`control_modes.create_mode_policy`直接加载指定类；console不覆写。runner才使用PAPER_POLICIES映射的PaperFixedScanReactivePolicy | UI旧类1×/5×，正式批跑3×/6×。报告限定正式protocol/runner入口；保留并披露此问题，不修改已冻结配置，不声称所有UI基线100%一致 |

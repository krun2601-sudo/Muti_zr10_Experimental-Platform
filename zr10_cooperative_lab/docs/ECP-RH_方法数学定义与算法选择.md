# ECP-RH 方法数学定义与算法选择（论文冻结版）

> 分支：`research/ecp-rh-experiments`  
> 冻结实现入口：`zr10lab.research.paper_policies:build_paper_policy`  
> 本文档按照“输入→状态→可观测信息→决策变量→约束→目标→数学性质→算法选择”的顺序定义方法。文中的理论结论只在明确的模型条件和求解状态下成立。

## 1. 任务定义与研究边界

考虑 \(N\) 台固定式 PTZ/EO 设备对三维任务区域进行持续搜索。目标数量、进入时刻和运动轨迹未知。设备同时承担两类任务：

1. **persistent search**：反复观测任务区域，控制网格重访年龄并尽早发现新目标；
2. **continuous monitoring**：目标一旦被发现，在其离开 ROI 前尽可能保证至少一台设备具有有效视场。

本文不要求双站同时观测，也不把三维交会定位作为任务成功条件。真实 ZR10 在 `mirror` 模式下仅执行与虚拟设备相同的 A/E/Zoom 指令；目标、检测、匿名跟踪、搜索 freshness 和论文指标均由虚拟任务世界产生。

---

## 2. 系统输入

调度器已知的固定输入包括：

- 设备位置 \(p_i^s\)、安装姿态、A/E/Zoom 限位；
- 标定的倍率—内参关系与 FOV；
- 仿真/标称最大转动速度、Zoom 变化速率和到位稳定时间；
- 任务 ROI 与持续搜索网格 \(\{g\}_{g=1}^{G}\)；
- 预测时域 \(T_H\)、预测步长 \(\Delta_H\)、重规划周期 \(T_R\)；
- 风险预算 \(\epsilon\)、期望交接重叠时间 \(T_O\)；
- 候选搜索倍率、跟踪倍率、每设备搜索候选数量和共享 FOV 最大目标数。

上述输入均属于公开任务模型，不含虚拟目标真值。

---

## 3. 系统状态

### 3.1 设备状态

设备 \(i\) 的状态表示为

\[
s_i(t)=\left[A_i,E_i,z_i,\dot A_i,\dot E_i,r_iight],
\]

其中 \(r_i\) 表示连接与感知就绪状态。执行层进一步区分 `moving_or_zooming`、`settling` 和 `ready`。

### 3.2 匿名目标信念

对已发现目标 \(j\)，策略仅获得匿名信念

\[
b_j(t)=\left[\hat p_j,\hat v_j,P_j,t_j^{\rm last},\chi_j,\mathcal S_j\right],
\]

其中 \(P_j\) 为位置协方差，\(\chi_j\) 为 confirmed/coasting 状态，\(\mathcal S_j\) 为最近有效观测设备集合。真实目标 ID、真实状态和未来轨迹不进入策略。

### 3.3 持续搜索状态

搜索单元 \(g\) 的状态采用重访年龄

\[
a_g(t)=t-t_g^{\rm last}.
\]

只有稳定且有效的 FOV 覆盖才会刷新该单元。该定义使“搜索”天然成为持续任务，而不是一次性覆盖。

---

## 4. 可观测信息

在线策略可以读取：设备反馈、匿名目标 belief、搜索网格 age、设备/FOV/执行模型与任务参数。策略不能读取：

- 虚拟目标真实 ID；
- 真实位置和真实轨迹参数；
- 未来真值；
- 真值派生的发现率、失视时间或其他评价指标。

真值只进入虚拟感知生成器、`ResearchEvaluator` 和实验日志。

---

## 5. 控制与候选决策变量

底层动作是绝对 A/E/Zoom 指令

\[
u_i=[A_i^{\rm cmd},E_i^{\rm cmd},z_i^{\rm cmd}].
\]

为在实时约束下联合处理连续视角与离散任务分配，每个重规划时刻为设备 \(i\) 生成有限候选原语集合 \(\mathcal C_i\)：

- `hold`：保持当前视角；
- `search`：指向高重访年龄单元；
- `track`：指向单目标预测位置；
- `shared_track`：以一个 FOV 同时覆盖多个接近目标。

候选 \(c\) 固定 A/E/Zoom，并预计算

\[
V_{cjh}\in\{0,1\},\qquad C_{cgh}\in\{0,1\},
\]

分别表示候选在未来时隙 \(h\) 是否可靠覆盖目标 \(j\)，以及是否覆盖搜索单元 \(g\)。优化变量

\[
x_c\in\{0,1\}
\]

表示本次滚动窗口选择候选 \(c\)。当前实现每次只下发当前目标视角，预测时域用于评价当前选择的未来后果；周期或离散事件发生后重新规划。

---

## 6. 执行约束

### 6.1 转动、变焦与稳定

与当前虚拟设备模型一致，A、E 和 Zoom 可并行变化，候选名义 transition time 为

\[
T_c^{\rm tr}=\max\left(
\frac{|\Delta A_c|}{\omega_i^{\max}},
\frac{|\Delta E_c|}{\omega_i^{\max}},
\frac{|\Delta z_c|}{\nu_i^z}
\right)+T_i^{\rm settle}.
\]

ready slot 为

\[
h_c^{\rm ready}=\left\lceil T_c^{\rm tr}/\Delta_H\right\rceil.
\]

ready 之前不计有效观测。该模型是论文仿真的公开执行模型，不冒充 ZR10 实测动力学；实机镜像实验额外保存实际反馈用于执行偏差诊断。

### 6.2 每设备一个当前原语

\[
\sum_{c\in\mathcal C_i}x_c=1,\qquad \forall i.
\]

### 6.3 连续监视短缺变量

引入

\[
\ell_{jh}\in[0,1],
\]

并要求

\[
\sum_cV_{cjh}x_c+\ell_{jh}\ge1.
\]

因此系统超载、目标不可达或候选集受限时仍能得到定义良好的最小短缺解，而不是把问题直接变成 infeasible。

### 6.4 搜索观测变量

\[
y_{gh}\in[0,1],\qquad
y_{gh}\le\sum_c C_{cgh}x_c.
\]

由于搜索目标对 \(y_{gh}\) 给正收益，可覆盖时最优解会把它推向 1。

### 6.5 软交接重叠

对预测需要交接的目标—时隙需求 \(r\)，定义满足度 \(q_r\in[0,1]\)：

\[
\sum_c V_{c,j_r,h_r}x_c\ge m_rq_r,
\]

当前 \(m_r=2\)。\(q_r=1\) 表示两台设备同时满足重叠；若容量或几何不允许，\(q_r<1\) 显式量化 overlap shortfall。**交接重叠是监视连续性之后的第二级优化目标，不是会导致整个问题不可行的硬约束。**

---

## 7. A/E 风险感知可见性

对预测位置

\[
p_{jh}\sim\mathcal N(\hat p_{jh},P_{jh}),
\]

先转换到设备安装坐标系

\[
q=R_{m,i}^{\mathsf T}(p-p_i^s)=[x,y,z]^{\mathsf T}.
\]

定义

\[
A=\operatorname{atan2}(y,x),\qquad
E=\operatorname{atan2}(z,\rho),\quad \rho=\sqrt{x^2+y^2}.
\]

局部角度雅可比为

\[
J_q=
\begin{bmatrix}
-y/\rho^2 & x/\rho^2 & 0\\
-zx/(\rho r^2) & -zy/(\rho r^2) & \rho/r^2
\end{bmatrix},
\quad r^2=\rho^2+z^2.
\]

对世界坐标位置的雅可比

\[
J_p=J_qR_{m,i}^{\mathsf T}.
\]

采用一阶误差传播

\[
\Sigma_{AE}=J_pP_{jh}J_p^{\mathsf T},
\]

得到

\[
\sigma_A=\sqrt{[\Sigma_{AE}]_{11}},\qquad
\sigma_E=\sqrt{[\Sigma_{AE}]_{22}}.
\]

总风险预算 \(\epsilon\) 通过 union bound 分配到所有目标、预测时隙、A/E 两轴及双侧尾部，对应标准正态分位数 \(\kappa\)。于是

\[
m_A=\kappa\sigma_A+m_{\rm inter}+m_0,
\]
\[
m_E=\kappa\sigma_E+m_{\rm inter}+m_0,
\]

其中 \(m_{\rm inter}\) 是预测采样间的目标角运动裕量，\(m_0\) 是固定 FOV 安全边缘。只有

\[
|A_{jh}-A_c|+m_A\le \alpha_A(z_c),
\]
\[
|E_{jh}-E_c|+m_E\le \alpha_E(z_c)
\]

同时成立时，才置 \(V_{cjh}=1\)。

**理论边界**：这是“高斯 belief + 一阶角度线性化 + union bound”下的保守 chance-envelope 近似，不是原非线性投影分布的精确概率解析保证。接近垂直奇异方向时实现将角度不确定性视为不可用，而不强行套用线性化。风险预算的有效性必须通过 Monte Carlo 经验违规率检查。

---

## 8. 词典序优化目标

### Level 1：最小化预测失视

\[
J_1=\Delta_H\sum_{j,h}\ell_{jh}.
\]

### Level 2：最大化交接重叠满足度

等价最小化

\[
J_O=\Delta_H\sum_r(1-q_r).
\]

### Level 3：最大化 persistent-search freshness utility

\[
w_{gh}=a_g(t)+(h+1)\Delta_H,
\]

\[
J_S=\sum_{g,h}w_{gh}y_{gh}.
\]

实现中对 \(w_{gh}\) 做尺度归一化，只改善数值条件，不改变同一次求解中的排序。

### Level 4：最小化执行成本

\[
J_E=\sum_c\kappa_cx_c,
\]

\(\kappa_c\) 由 transition time 及小的 Zoom 变化惩罚构成。

ECP-RH 依次求解上述四级，并只在上一等级**被求解器认证为 optimal**时才进入下一等级。上一等级通过数值容差锁定其最优值，而不是用人为大权重近似优先级。

Weighted RH-MPC baseline 使用相同候选、变量和约束，但将各项写成有限权重和；其权重只允许在 validation split 上调节。

---

## 9. 总求解预算与最优性表述

配置项 `solver_time_limit_s` 表示**一次重规划调用的总 MILP 墙钟预算**。四个词典序等级共享这一预算，而不是每一级重新获得完整预算。

实现记录：

- `visibility_level_certified`：Level 1 是否 optimal；
- `overlap_level_certified`；
- `search_level_certified`；
- `execution_level_certified`；
- `priority_certified`：全部相关等级是否均认证 optimal；
- `solver_timeout_rate`、`mip_gap`、求解耗时。

因此论文表述必须区分：

- 当 `visibility_level_certified=true`：可以说“在当前有限候选集合与离散预测模型下，Level-1 监视短缺目标被认证最优”；
- 当 `priority_certified=true`：可以说“当前候选集合上的完整词典序问题被认证最优”；
- 若达到计算预算但已有 incumbent：只能说“获得预算内可行解”，不能声称最优。

---

## 10. 数学问题性质

候选生成后，\(V_{cjh}\)、\(C_{cgh}\)、执行成本和 overlap 需求均为常数。在线问题包含二元候选变量和连续短缺/满足度变量，属于小规模混合整数线性规划（MILP）。

非凸性和非线性主要在候选生成阶段被显式处理：

- PTZ 几何与 Zoom-dependent FOV；
- 执行 transition time；
- belief covariance 到 A/E 风险包络；
- 单目标和共享 FOV 候选构造。

这种分解保留了物理可执行性，同时把在线组合决策转成可验证求解状态的 MILP。

---

## 11. 为什么选择 ECP-RH，而不是其他候选方法

### 11.1 为什么不是单步贪心

困难来自 slew/zoom/settle 导致的延迟效应和 handover 的前置准备。单步收益看不到“现在预瞄、未来避免失视”的价值。因此保留 execution-aware greedy 作为 baseline，而不作为主方法。

### 11.2 为什么不是单一加权 MPC

搜索 freshness、连续监视和执行代价量纲不同，而且任务语义中存在明确优先级。有限权重不能保证搜索收益不会交换掉监视连续性。因此采用词典序结构，并以同模型 weighted RH-MPC 作为最直接对照。

### 11.3 为什么不是 MCTS

当前候选动作已经离散，但四设备联合分支会随设备数、候选数和目标数快速增长。对于当前短预测时域，MILP 能利用线性覆盖结构并提供求解状态/Gap；MCTS 更适合需要长时随机 rollout、难以线性化的信念动态，这里不是主要数学瓶颈。

### 11.4 为什么不是直接用 POMDP

目标出现确实具有部分可观测性，但本文主贡献聚焦于“已形成匿名 belief 后的执行约束资源调度 + persistent search”。完整 POMDP 需要对目标 birth、motion、detection 和多设备联合动作维护大规模 belief，四 PTZ 联合动作使精确求解代价很高。故以 SSM belief-lookahead 适配作为相关 baseline，而主方法使用显式 belief 摘要和滚动优化。

### 11.5 为什么不是 MARL 作为主方法

只有 4 台设备，中央控制中心可获取统一状态，并要求结果可解释、可审计、可直接做约束消融。MARL 的主要优势是大规模/分布式/策略泛化，而这里不是第一需求；训练成本、约束满足和可重复性反而增加。MAPPO / Safe-MAPPO 作为学习 baseline 保留，训练/验证/测试严格分离。

### 11.6 为什么不是分布式优化

真实平台由一个控制中心统一下发 A/E/Zoom，不存在必须分布式求解的硬约束。强行分布式化会新增通信一致性问题，却不解决当前核心数学困难。因此当前论文采用集中式滚动优化；未来扩展到大规模异构站网时再研究分布式近似更合理。

---

## 12. 算法流程

每个控制周期执行：

1. 虚拟任务世界推进目标与设备状态；
2. 根据稳定 FOV 和检测概率生成匿名 belief；
3. 更新搜索网格重访年龄；
4. 若达到周期重规划时刻，或发生新目标/目标状态/设备连接等离散事件：
   1. 预测匿名目标状态与协方差；
   2. 生成 hold/search/track/shared-track 原语；
   3. 计算执行 ready slot；
   4. 用 A/E 雅可比构造风险感知 \(V_{cjh}\)；
   5. 构造 search coverage 和 soft overlap；
   6. 在共享总时间预算内按词典序求解；
   7. 下发当前 A/E/Zoom 指令；
5. 非重规划周期继续刷新同一动作租约；
6. evaluator 用隐藏真值统计发现、失视、handover、revisit 和经验风险违规率。

---

## 13. 理论主张的允许范围

建议论文只主张以下可被代码和实验直接支撑的结论：

1. **有限候选集上的优先级性质**：当 Level 1 被认证 optimal 时，低优先级搜索/执行目标不会牺牲该候选集内的 Level-1 最优值；完整 `priority_certified=true` 时成立完整词典序最优性。
2. **执行模型一致性**：候选只有在预计 slew/zoom/settle 完成后才提供有效覆盖；去掉执行模型的消融应在 handoff/高速场景表现出更高失视风险。
3. **风险包络的条件性性质**：在高斯 belief 与局部线性化近似下，减小风险预算会提高标准正态裕量，从而单调收缩可靠可见候选集合；经验违规率用于检查该近似在测试范围内是否符合预期。
4. **soft-overlap 的可行性性质**：overlap 不会单独造成 MILP infeasible；容量不足时通过 \(q_r<1\) 显式暴露短缺。
5. **持续搜索语义**：优化对象是 revisit/freshness，而非一次性覆盖时间。

不得把有限候选集最优说成连续 A/E/Zoom 空间的全局最优，也不得把经验 Monte Carlo 趋势写成“实验证明了定理”。

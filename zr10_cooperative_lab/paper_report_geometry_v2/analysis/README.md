# 实验结果分析材料

本目录只对冻结实验结果作离线分析，不运行仿真实验、不修改算法或测试集。

## 运行

在完整材料包中，默认输入为相邻的 `../results/geometry_v2`，默认输出为本目录。

```text
python -m pip install -r requirements.txt
python build_analysis.py
```

也可以显式指定：

```text
python build_analysis.py --data ../results/geometry_v2 --out ./reproduced
python build_analysis.py --help
```

`--source` 与 `--output` 分别是 `--data` 与 `--out` 的别名。运行环境实际版本记录在 `analysis_audit.json`。跨平台绘图像素或库版本造成的数值末位差异不改变原始配对统计；使用相同版本可获得更严格的再现性。

## 文件

- `tables/`：14 个机器可读统计表，所有主指标与条件性次指标保留有效样本量。
- `figures/`：7 张科学图。
- `analysis_audit.json`：源 CSV 的 SHA-256、数量、去重及分析环境。
- `numeric_evidence.md`：全场景和全参数的辅助数值索引。

原始源数据不在此覆盖。总体主表保留预设 S0 无目标场景；`main_target_present_summary.csv` 只是有目标子集的描述性补充。配对统计取自原文件，未重新选择种子或调整参数。

新增均值区间采用10000次百分位bootstrap，固定种子20261025。原配对检验的bootstrap种子为20261022；Holm校正按scope、scenario、metric分族。消融合并文件含分片局部overall行，所以本目录仅以scope=scenario行生成消融统计表。

科学图的时间指标沿用代码含义：发现后累计丢失、运行内目标发现延迟P95、运行结束时网格龄P95。扩展性生成和求解分别绘制；均值可以相加，边缘P95不能相加冒充端到端P95。

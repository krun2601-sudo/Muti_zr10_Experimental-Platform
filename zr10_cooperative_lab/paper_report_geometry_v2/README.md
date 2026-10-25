# Geometry v2 完整实验报告与复现材料

[阅读完整报告](report/完整实验报告.md) · [PDF](report/完整实验报告.pdf) · [HTML](report/完整实验报告.html)

## 一次下载全部材料

[完整材料下载页面](https://github.com/krun2601-sudo/Muti_zr10_Experimental-Platform/releases/tag/geometry-v2-complete-report-20261025)提供 `geometry_v2_complete_package.zip`，解压后只有一个材料文件夹：包含22页报告、96个原始紧凑结果文件、14张派生表、7张新图、823个源码文件以及全部53个正式原始数据包。原始ZIP展开后约16.30 GB。

本目录保留报告与派生分析；大型日志在下载附件内持久归档。原有实验结果仍位于[experiment_results/geometry_v2](../experiment_results/geometry_v2)，未重复改写。

完整包 SHA-256：`2c3d5f8f8eb4d20a7c134b01735caa30febd4dcadf3de7ae16fa6accd31293b4`。完整包大小：1,221,960,327 字节。包内 `verify_package.py` 可逐文件核验 `SHA256SUMS.json`。

## 分析复现

在本目录执行：

```text
python -m pip install -r analysis/requirements.txt
python analysis/build_analysis.py --source ../experiment_results/geometry_v2 --output analysis_reproduced
```

报告以冻结源提交 `94b30f4d100532779d2d25158b8a2e2fd607e05f` 为依据。本次只整理报告和分析材料，没有修改算法、场景配置、冻结参数或正式实验结果，没有重跑实验。统计脚本已从完整包中的源CSV独立重建，14张表与交付表逐字节一致；53个原始ZIP的源SHA-256、字节数及全部成员CRC均通过。

报告保留发现延迟劣势、不利消融、条件指标和候选生成耗时等限制。它支持固定仿真面板中的持续监视与失观控制分析，不把求解器预算写成整个闭环实时性或实机验证结论。

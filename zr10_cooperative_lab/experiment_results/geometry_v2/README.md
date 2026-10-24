# Geometry-v2 experiment results

This directory contains the compact, analysis-ready outputs for revision
`geometry-v2-central-roi-20261024`. Large per-cycle GitHub Actions artifacts are
not committed here; the statistical source table `run_metrics.csv`, summaries,
paired comparisons, plot data, figures, completion audits, and workflow
provenance are retained after each formal phase.

Directory layout:

- `validation/`: all 20 validation tuning shards, the 24-tuple summaries, and
  source-artifact identities used to freeze the four parameterized baselines;
- `main/`: held-out main-test metrics and statistics (created after completion);
- `ood/`: held-out distribution-shift metrics (created after completion);
- `ablations/`, `sensitivity/`, `scalability/`: supporting study outputs.

The frozen protocol and phase status are recorded in
`configs/research/paper_experiment_manifest.yaml` and
`configs/research/experiment_runs/geometry_v2_runbook.yaml`.

# Geometry-v2 experiment results

This directory contains the compact, analysis-ready outputs for revision
`geometry-v2-central-roi-20261024`. Large per-cycle GitHub Actions artifacts are
not committed here; the statistical source table `run_metrics.csv`, summaries,
paired comparisons, plot data, figures, completion audits, and workflow
provenance are retained after each formal phase.

Directory layout:

- `validation/`: all 20 validation tuning shards, the 24-tuple summaries, and
  source-artifact identities used to freeze the four parameterized baselines;
- `main/`: 560 held-out main-test rows, summaries, paired statistics, figures,
  an integrity audit, and source-artifact identities;
- `ood/`: 280 held-out distribution-shift rows and the matching analyses;
- `ablations/`: 415 completed ablation rows;
- `sensitivity/`: 250 completed sensitivity rows;
- `scalability/`: 24 parameter points with 10 repetitions per point.

Start with `RESULTS_SUMMARY.md` for the analysis map and qualified preliminary
interpretation. `completion_audit.json` records row counts, duplicate checks,
workflow provenance, and SHA-256 identities for the statistical source files.
The full per-cycle traces remain in the indexed GitHub Actions artifacts; the
compact files required to reproduce tables and figures are committed here.

The frozen protocol and phase status are recorded in
`configs/research/paper_experiment_manifest.yaml` and
`configs/research/experiment_runs/geometry_v2_runbook.yaml`.

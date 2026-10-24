# Geometry-v2 frozen baseline selections

These four files were selected only from `S4_boundary_handoff` and
`S8_maneuver`, using environment seeds 2001–2005. Each method evaluated the
same deterministic budget of 24 parameter tuples and 10 runs per tuple. No
`test_main` or `test_ood` result was generated or inspected before this freeze.

| Method | Frozen parameters |
|---|---|
| `weighted_rh` | `loss_weight=3`, `overlap_weight=3`, `search_weight=1`, `motion_weight=0.03` |
| `classical_ptz` | `track_weight=2`, `search_weight=1`, `risk_weight=1`, `motion_weight=0.15` |
| `info_planner` | `track_information_weight=0.5`, `discovery_weight=1`, `motion_weight=0.1` |
| `ssm_belief` | `gamma=0.98`, `monitor_weight=2`, `search_weight=2`, `motion_weight=0.04` |

The authoritative SHA-256 identities are pinned in
`configs/research/paper_experiment_manifest.yaml`. Full per-seed tuning rows,
24-tuple summaries, and GitHub Actions artifact provenance are retained under
`experiment_results/geometry_v2/validation/`.

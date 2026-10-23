# Frozen full-validation run — 2026-10-23

This marker records the first full validation-only baseline tuning run after the
SSM parameter-namespace wiring fix.

- Validation scenarios: `S4_boundary_handoff.yaml`, `S8_maneuver.yaml`
- Validation seeds: `2001, 2002, 2003, 2004, 2005`
- Parameterized baselines: `weighted_rh`, `classical_ptz`, `info_planner`, `ssm_belief`
- Candidate parameter budget: 24 deterministic combinations per method
- Parameter-sampling seed: `20261022`
- Selection order: missed-target rate; censored detection-delay P95; total post-discovery loss; maximum loss gap; revisit-age P95
- `test_main` and `test_ood` are not used during tuning.

The workflow shards by method and validation seed to keep each CI job within its
runtime budget. Final parameters must be selected only after aggregating all five
validation seeds for each identical parameter tuple.

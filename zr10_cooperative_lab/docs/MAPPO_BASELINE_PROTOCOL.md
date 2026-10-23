# MAPPO Baseline Protocol for the Search–Monitor Paper

Status: **development protocol; held-out test remains locked**.

This document separates engineering pilots from paper results and records the rules that must hold before MAPPO is admitted to `test_main` or `test_ood`.

## 1. Task and information fairness

MAPPO is a CTDE baseline for the same four-device persistent-search / continuous-monitoring task used by the model-based methods. The actor receives only policy-available anonymous target beliefs, device state/readiness, and the complete 65-cell persistent-search state. Hidden target truth may be used only by the training reward/cost, never by the actor observation.

The paper MAPPO baseline uses the same `RiskAwarePrimitiveFactory` as the model-based methods. Each device therefore chooses among the same physically executable A/E/Zoom primitives, including the same slew, zoom, settling, visibility-risk, sensing-quality, search-candidate, target-candidate, and shared-FOV assumptions. Candidate padding is explicit (`max_candidates=512`) and a larger candidate set must raise an error rather than be silently truncated.

## 2. Deprecated development baseline

The original continuous MAPPO interface directly mapped three normalized actor outputs to absolute yaw, pitch, and zoom over the full mechanical ranges. A 100-update development pilot did not learn a useful policy: the validation missed-target rate remained 1.0 and the policy repeatedly issued large absolute re-pointing commands, yielding very low sensing duty cycle.

This implementation is retained only as an engineering diagnostic. It must not be used as the paper MAPPO comparator because its action interface is structurally mismatched to the executable-primitive formulation used by the other methods.

## 3. Current candidate-action MAPPO

The current development implementation is `candidate_categorical_v1` in `zr10lab.research.candidate_mappo`.

- shared actor across the four devices;
- centralized critic;
- masked categorical action for each device;
- joint log-probability used by PPO;
- full-grid observation (`max_targets=8`, `top_search_cells=65`);
- common executable primitive action set;
- deterministic actor argmax for evaluation;
- training environment seed is independent of the network initialization seed.

The reward retains the task terms used by the earlier learning environment: discovery bonus, discovered-target loss penalty, active-but-undiscovered penalty, persistent-search age penalty, and a motion/execution penalty. For the candidate action representation, the motion term uses primitive `execution_cost` instead of normalized continuous-action change.

## 4. Data split (frozen)

Training only:

- scenarios: S1, S2, S3, S5, S6;
- environment seeds: 1001–1020.

Validation only:

- scenarios: S4 and S8;
- environment seeds: 2001–2005.

Held-out paper test:

- `test_main`: S0, S10, S11, S7 with seeds 3001–3020;
- `test_ood`: S9a and S9b with seeds 4001–4020.

No learning hyperparameter, checkpoint, architecture choice, reward choice, or training duration may be changed after inspecting a held-out test result.

## 5. Development pilots are not paper results

The short candidate-action smoke pilot used one network seed, only two training environment seeds, and 10×64 decisions. It verified engineering correctness only. It started four episodes, so it did not cover the frozen training product. Its validation metrics must not be reported as paper performance.

The 100×128 medium pilot is also a learning diagnostic. Its purpose is to determine whether the current candidate-action formulation exhibits a genuine learning trend. It is not a formal training run because, based on the observed episode length, it may still fail to visit all 100 scenario×environment-seed combinations.

## 6. Formal training gate

Formal MAPPO training may begin only after the medium pilot shows that the learning formulation is viable. The formal run must satisfy all of the following.

1. Use multiple independent network initialization / sampling seeds. Five network seeds are the current target unless an explicit pre-test protocol change documents a different number.
2. Every network seed trains on the same frozen training scenarios and environment seeds.
3. `episode_usage` must prove that every one of the 100 scenario×environment-seed pairs was started at least once. A stronger target is at least two complete product cycles before final checkpoint selection.
4. Training update / checkpoint candidates are fixed before validation aggregation.
5. The same learning hyperparameters are used for every network seed.
6. No failed seed is silently dropped. Failure remains part of the experiment record.

## 7. Validation model selection across network seeds

Do **not** select the best network seed.

Checkpoint selection must use a common training update across all network seeds. For each candidate update, pool the S4/S8 × validation-seed results across all trained network replicas and apply the same lexicographic task rule used for non-learning baselines:

1. missed-target rate;
2. censored detection-delay P95;
3. post-discovery total loss;
4. maximum loss gap;
5. revisit-age P95.

After one common update is selected, freeze the checkpoint from every network seed at that update. Each frozen checkpoint and its metadata must receive a SHA-256 identity.

## 8. Candidate representation strength check

The current categorical policy uses an index into the per-device candidate list. Candidate counts and valid search ranks can change with geometry, limits, de-duplication, and target state. If the medium pilot remains weak, the next admissible strengthening is a **per-candidate feature scorer** rather than simply increasing training steps.

Such a scorer may use only quantities already available from the common primitive model, e.g. relative A/E, zoom, transition/ready time, primitive type, target count, predicted visibility summary, and persistent-search coverage/age value. Scoring candidates independently with shared weights makes the actor equivariant to candidate ordering and removes an avoidable index-semantics handicap. Any such architecture change must be made and validated before held-out testing.

## 9. Test statistics with multiple network seeds

Network-seed replicates create an additional randomness dimension and must not be treated as independent paired environment seeds.

For paired comparisons against deterministic/model-based methods, first average MAPPO performance across network seeds **within each scenario×environment seed**, then perform paired statistics across the held-out environment seeds. Separately report variability attributable to network seed (and, where useful, the full training-seed × environment-seed distribution).

This avoids pseudo-replication while still exposing learning instability.

## 10. Freeze and held-out gate

`paper_experiment_manifest.yaml` currently has `frozen_inputs.paper_test_unlocked: false`. Therefore all held-out paper runs are globally blocked.

Before changing that flag to true, the repository must contain:

- the already frozen non-learning baseline selection JSONs and their manifest-pinned SHA-256 values;
- a frozen learning-selection directory;
- the common validation-selected MAPPO update;
- all required network-seed checkpoint replicas;
- SHA-256 identities for the learning selection, checkpoints, and checkpoint metadata;
- provenance proving training used only S1/S2/S3/S5/S6 with seeds 1001–1020 and model selection used only S4/S8 with seeds 2001–2005;
- no reference to S7/S9/S10/S11 outcomes in any tuning or model-selection artifact.

Only after these checks pass may the global test gate be unlocked in a dedicated, auditable commit.

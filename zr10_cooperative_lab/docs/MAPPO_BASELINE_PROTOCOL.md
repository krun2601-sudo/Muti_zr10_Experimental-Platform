# MAPPO Baseline Protocol for the Search–Monitor Paper

Status: **development protocol; held-out test remains locked**.

This document separates engineering pilots from paper results and records the rules that must hold before MAPPO is admitted to `test_main` or `test_ood`.

## 1. Task and information fairness

MAPPO is a CTDE baseline for the same four-device persistent-search / continuous-monitoring task used by the model-based methods. The actor receives only policy-available anonymous target beliefs, device state/readiness, and the complete 65-cell persistent-search state. Hidden target truth may be used only by the training reward/cost, never by the actor observation.

The paper MAPPO baseline uses the same `RiskAwarePrimitiveFactory` as the model-based methods. Each device therefore chooses among the same physically executable A/E/Zoom primitives, including the same slew, zoom, settling, visibility-risk, sensing-quality, search-candidate, target-candidate, and shared-FOV assumptions. Candidate padding is explicit (`max_candidates=512`) and a larger candidate set must raise an error rather than be silently truncated.

## 2. Deprecated development baseline

The original continuous MAPPO interface directly mapped three normalized actor outputs to absolute yaw, pitch, and zoom over the full mechanical ranges. A development pilot did not learn a useful policy and repeatedly issued large absolute re-pointing commands, yielding very low sensing duty cycle.

This implementation is retained only as an engineering diagnostic. It must not be used as the paper MAPPO comparator because its action interface is structurally mismatched to the executable-primitive formulation used by the other methods.

## 3. Candidate-action v1 diagnostic

`candidate_categorical_v1` in `zr10lab.research.candidate_mappo` uses a shared actor, centralized critic, masked categorical action, the complete search-grid observation, and the common executable primitive action set.

Its 100×128 medium pilot established an important but incomplete learning result. At update 100 it reduced validation missed-target rate to 0.25, so the executable candidate interface can learn discovery. However, post-discovery monitoring remained poor: the policy showed very low continuous-visible ratio together with excessive motion and frequent assignment switching. The run had started only 74 of the 100 frozen training scenario×environment-seed combinations.

The v1 actor maps observations directly to fixed candidate-index logits. That representation is structurally weak because candidate list semantics change with search-age ordering, target state, geometry, de-duplication, and feasibility. The same output neuron can therefore refer to different physical primitives at different decision times. For this reason v1 is retained for reproducibility and diagnosis but is not the preferred formal MAPPO comparator.

## 4. Feature-scored candidate MAPPO v2

The current strengthened implementation is `candidate_feature_v2` in `zr10lab.research.candidate_feature_mappo`.

The actor applies one shared scoring function independently to every valid executable primitive. Candidate features use only policy-visible quantities from the common primitive model: primitive kind, relative A/E, zoom, transition/ready/execution cost, intended-target membership, predicted target visibility, and persistent-search coverage/age gain. No hidden target truth is added to the actor input.

This construction is permutation equivariant with respect to candidate ordering: permuting candidate rows and the mask permutes the corresponding logits rather than changing the learned meaning of an output neuron. Unit tests explicitly verify this property.

The training reward is otherwise unchanged from v1: discovery bonus, discovered-target visibility-loss penalty, active-but-undiscovered penalty, persistent-search age penalty, and execution/motion penalty. PPO hyperparameters, training/validation splits, observation information, and the executable primitive factory are also unchanged. Thus v2 changes the action representation, not the task definition or information advantage.

## 5. Sparse-equivalent v2 runtime

A dense implementation of v2 would evaluate all 512 padded candidate slots even though only a few dozen are normally valid. This is computationally wasteful and does not add information because padded candidates are masked from the categorical distribution.

`zr10lab.research.candidate_feature_runtime` therefore evaluates the candidate encoder only for `mask=True` primitive rows and scatters the resulting scores back into the masked logit tensor. It uses the same network parameters and the same `candidate_feature_v2` checkpoint format. Invalid padded logits remain masked and never become legal actions.

This optimization is admissible only if it is numerically equivalent to the dense scorer on all valid candidates. The regression suite checks:

1. equality of valid candidate logits;
2. equality of masked categorical loss for identical actions;
3. equality of actor parameter gradients within numerical tolerance.

Failure of any equivalence check blocks training. Sparse scoring is therefore an execution optimization, not a new learning method.

## 6. Data split (frozen)

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

## 7. Development pilots are not paper results

Short smoke runs use reduced update counts and may use subsets of training/validation seeds. They verify engineering correctness, action semantics, learning viability, computational cost, and split provenance only. Their metrics must not be reported as paper performance.

The v2 sparse smoke is accepted only if all of the following hold:

1. feature/mask and permutation-equivariance tests pass;
2. dense-vs-sparse logit, loss, and actor-gradient equivalence tests pass;
3. checkpoints can be loaded through the versioned dispatcher;
4. validation produces nonzero effective search observations;
5. the actor does not collapse to all-hold behavior;
6. no held-out scenario or seed appears in the training/model-selection artifacts.

After smoke acceptance, the next learning diagnostic is a full-product v2 medium run. The current target is 125×128 decisions with checkpoints at 25/50/75/100/125, using all five training scenarios and environment seeds 1001–1020, followed by the complete S4/S8 × seeds 2001–2005 validation split. This remains a pre-test development experiment.

## 8. Formal training gate

Formal MAPPO training may begin only after the v2 medium run shows plausible discovery and sustained monitoring behavior. The formal run must satisfy all of the following.

1. Use multiple independent network initialization / sampling seeds. Five network seeds are the current target unless an explicit pre-test protocol change documents a different number.
2. Every network seed trains on the same frozen training scenarios and environment seeds.
3. `episode_usage` must prove that every one of the 100 scenario×environment-seed pairs was started at least once. A stronger target is at least two complete product cycles before final checkpoint selection.
4. Training update / checkpoint candidates are fixed before validation aggregation.
5. The same learning hyperparameters are used for every network seed.
6. No failed seed is silently dropped. Failure remains part of the experiment record.

The present formal-budget target is approximately 300×128 decisions per network seed, but actual `episode_usage` rather than nominal update count is the governing coverage criterion.

## 9. Validation model selection across network seeds

Do **not** select the best network seed.

Checkpoint selection must use a common training update across all network seeds. For each candidate update, pool the S4/S8 × validation-seed results across all trained network replicas and apply the same lexicographic task rule used for non-learning baselines:

1. missed-target rate;
2. censored detection-delay P95;
3. post-discovery total loss;
4. maximum loss gap;
5. revisit-age P95.

After one common update is selected, freeze the checkpoint from every network seed at that update. Each frozen checkpoint and its metadata must receive a SHA-256 identity.

## 10. Test statistics with multiple network seeds

Network-seed replicates create an additional randomness dimension and must not be treated as independent paired environment seeds.

For paired comparisons against deterministic/model-based methods, first average MAPPO performance across network seeds **within each scenario×environment seed**, then perform paired statistics across the held-out environment seeds. Separately report variability attributable to network seed and, where useful, the full training-seed × environment-seed distribution.

This avoids pseudo-replication while still exposing learning instability.

## 11. Freeze and held-out gate

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

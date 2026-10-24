# MAPPO Baseline Protocol for the Search–Monitor Paper

Status: **pre-test development record; optional learning baselines omitted from the primary table before any held-out run**.

This document separates engineering pilots from paper results and records the rules applied to the learning baselines before `test_main` or `test_ood` is inspected.

## 1. Task and information fairness

MAPPO is a CTDE baseline for the same four-device persistent-search / continuous-monitoring task used by the model-based methods. In geometry-v2 the actor receives only policy-available anonymous target beliefs, device state/readiness, and the complete 63-cell persistent-search state. Hidden target truth may be used only by the training reward/cost, never by the actor observation.

The paper MAPPO development baseline uses the same `RiskAwarePrimitiveFactory` as the model-based methods. Each device therefore chooses among the same physically executable A/E/Zoom primitives, including the same slew, zoom, settling, visibility-risk, sensing-quality, search-candidate, target-candidate, and shared-FOV assumptions. Candidate padding is explicit (`max_candidates=512`) and a larger candidate set must raise an error rather than be silently truncated.

## 2. Deprecated continuous-action diagnostic

The original continuous MAPPO interface directly mapped three normalized actor outputs to absolute yaw, pitch, and zoom over the full mechanical ranges. A development pilot did not learn a useful policy and repeatedly issued large absolute re-pointing commands, yielding very low sensing duty cycle.

This implementation is retained only as an engineering diagnostic. It is not used as the paper comparator because its action interface is structurally mismatched to the executable-primitive formulation used by the other methods.

## 3. Candidate-action v1 diagnostic

`candidate_categorical_v1` in `zr10lab.research.candidate_mappo` uses a shared actor, centralized critic, masked categorical action, the complete search-grid observation, and the common executable primitive action set.

Its 100×128 medium pilot established an important but incomplete learning result. At update 100 it reduced validation missed-target rate to 0.25, so the executable candidate interface can learn discovery. However, post-discovery monitoring remained poor: the policy showed very low continuous-visible ratio together with excessive motion and frequent assignment switching. The run had started only 74 of the 100 frozen training scenario×environment-seed combinations.

The v1 actor maps observations directly to fixed candidate-index logits. That representation is structurally weak because candidate-list semantics change with search-age ordering, target state, geometry, de-duplication, and feasibility. The same output neuron can therefore refer to different physical primitives at different decision times. For this reason v1 is retained for reproducibility and diagnosis but is not a formal paper comparator.

## 4. Feature-scored candidate MAPPO v2

`candidate_feature_v2` in `zr10lab.research.candidate_feature_mappo` applies one shared scoring function independently to every valid executable primitive. Candidate features use only policy-visible quantities from the common primitive model: primitive kind, relative A/E, zoom, transition/ready/execution cost, intended-target membership, predicted target visibility, and persistent-search coverage/age gain. No hidden target truth is added to the actor input.

This construction is permutation equivariant with respect to candidate ordering: permuting candidate rows and the mask permutes the corresponding logits rather than changing the learned meaning of an output neuron. Unit tests explicitly verify this property.

The full-product v2 medium run (`workflow run 39925446648`) used S1/S2/S3/S5/S6 with training seeds 1001–1020 and S4/S8 with validation seeds 2001–2005. All validation checkpoints at updates 25/50/75/100/125 had missed-target rate 1.0. Deterministic behavior collapsed from all/near-all `hold` at early checkpoints to all `search` at update 125. The final checkpoint had started 89 of 100 frozen training scenario×seed pairs. These results are development diagnostics, not paper performance results.

## 5. Sparse-equivalent v2 runtime

`zr10lab.research.candidate_feature_runtime` evaluates the candidate encoder only for `mask=True` primitive rows and scatters the resulting scores back into the masked logit tensor. It uses the same network parameters and the same candidate semantics as the dense scorer. Invalid padded logits remain masked and never become legal actions.

Regression tests check equality of valid candidate logits, equality of masked categorical loss for identical actions, and equality of actor parameter gradients within numerical tolerance. Sparse scoring is therefore an execution optimization, not a new learning method.

## 6. Frozen data split

Training only:

- scenarios: S1, S2, S3, S5, S6;
- environment seeds: 1001–1020.

Validation only:

- scenarios: S4 and S8;
- environment seeds: 2001–2005.

Held-out paper test:

- `test_main`: S0, S10, S11, S7 with seeds 3001–3020;
- `test_ood`: S9a and S9b with seeds 4001–4020.

No learning architecture, reward, checkpoint, training duration, or inclusion/exclusion decision may be changed in response to a held-out test result.

## 7. v3 freshness-recovery diagnostic

The original search component `-mean_age/age_cap` provided a weak immediate credit signal relative to execution cost. The v3 diagnostic therefore used a freshness-recovery potential term based only on valid search-state changes:

\[
r_{\mathrm{fresh}}(k)=\frac{1}{a_{\max}}\sum_g [a_g(k)-a_g(k+1)]_+ .
\]

This reward is target-truth independent and is positive only when stale search cells are actually refreshed by valid sensing. The task, candidate factory, actor information and held-out split remained unchanged.

## 8. v4 agent-wise PPO diagnostic

The final pre-test learning diagnostic is `candidate_feature_v4_agentwise` at commit `2f2fc6b59eb3f8c31182c9f6c88e5e24e4b2adfe` and workflow run `39962169263`.

It retains the v3 freshness-recovery reward, public candidate features, common executable primitives, and centralized critic. The actor update alone changes from a product/joint action probability ratio to per-agent categorical PPO ratios with independent clipping before averaging. Unit tests verify this factorization.

The short gate trained on the frozen training-only product and evaluated only S4/S8 with validation seed 2001. Updates 10, 20 and 30 all had missed-target rate 1.0. The deterministic behaviors were:

- update 10: 24 `search`, 1256 `hold`, maximum observed search cells 8;
- update 20: 34 `search`, 1246 `hold`, maximum observed search cells 4;
- update 30: 1280 `search`, 0 `hold`, maximum observed search cells 0.

No checkpoint produced a valid discovery in this gate. The implementation tests and workflow completed successfully, so the observed failure is not being treated as an execution crash or an intentionally weakened action-space baseline.

## 9. Formal multi-seed protocol retained but not executed

A stricter formal protocol was precommitted before any held-out run: five network seeds 5101–5105, 300×128 decisions per seed, common validation-eligible updates 150/200/250/300, complete 100-pair training coverage, no best-seed selection, and a common update selected across every network seed × validation case.

The corresponding manual workflow and aggregation tools remain in the repository for reproducibility/future work. **That formal five-seed workflow has not been started.** It is not run after the pre-test omission decision below because doing so after inspecting held-out results could create test-informed learning development.

## 10. Multiple-network-seed statistics rule

If this learning baseline is revisited in future work, network-seed replicas must not be treated as independent paired environment samples. MAPPO performance must first be averaged across network seeds within each scenario×environment seed, with training-seed variability reported separately; paired bootstrap/Wilcoxon analysis is then performed across held-out environment seeds.

## 11. Pre-test primary-table decision

**Decision point: before any `test_main` or `test_ood` run.**

The learning baseline progressed through four principled pre-test diagnostics: continuous absolute actions, common executable candidate actions, permutation-compatible candidate-feature scoring with freshness-recovery shaping, and agent-wise PPO clipping. The final v4 gate still failed the minimum discovery criterion on the frozen validation-only data and again collapsed between hold-dominated and search-dominated deterministic behavior.

At this point, continuing to create v5/v6 variants in response to validation behavior would turn the optional comparator into an open-ended method-development project and would materially increase the risk of post-hoc baseline engineering. The paper manifest has always classified MAPPO/Safe-MAPPO as `learning_optional_after_training`, while the seven primary methods are the six non-learning comparators plus ECP-RH.

Therefore the primary main table is frozen **without MAPPO or Safe-MAPPO**. The learning implementations, checkpoints, failed/partial validation diagnostics and formal multi-seed protocol are retained as transparent development records and may be discussed in an appendix/future-work note, but no held-out MAPPO performance is generated for this frozen paper evaluation.

This decision satisfies the following provenance constraints:

- final diagnostic implementation: `candidate_feature_v4_agentwise`;
- final diagnostic commit: `2f2fc6b59eb3f8c31182c9f6c88e5e24e4b2adfe`;
- final diagnostic workflow run: `39962169263`;
- validation scenarios used in the final gate: S4 and S8 only;
- final-gate validation seed: 2001;
- final-gate checkpoints: 10, 20, 30;
- missed-target rate at all three checkpoints: 1.0;
- `test_main` and `test_ood` outcomes used in this decision: **none**;
- formal five-network-seed learning workflow started: **no**.

After this decision is recorded in the manifest, the held-out gate may be unlocked for the already frozen seven primary methods only. No learning baseline may be retroactively added to this paper's held-out comparison after those results are inspected.

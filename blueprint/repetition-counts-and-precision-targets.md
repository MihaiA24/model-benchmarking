# Set repetition counts and precision targets

**Status:** Final decision

**Map:** [Design a real-world CLI benchmark for coding-agent harnesses](https://github.com/MihaiA24/model-benchmarking/issues/13)

**Ticket:** [Set repetition counts and precision targets](https://github.com/MihaiA24/model-benchmarking/issues/26)

## Accepted decisions

### Smallest worthwhile strict-success advantage

Set the Smallest Worthwhile Difference for the primary `task_success` endpoint to an absolute **10 percentage points** for every pairwise Harness contrast within each Public or Private Suite × Workload Family × exact-model Analysis Stratum.

This margin represents the minimum quality advantage that can change the organizational Harness-routing decision. It is not enlarged to make a cheaper experiment appear decisive. An observed difference below 10 percentage points remains reportable evidence but cannot support the claim `supported superior`; if the frozen design cannot distinguish a 10-point advantage with its declared precision and assurance, the result is `inconclusive` rather than a retrospectively weakened decision rule.

This value and its natural absolute-probability unit are frozen in the applicable Suite Release and referenced by the Production Experiment Manifest and analysis manifest. Public and Private Suite evidence remains separate.

### Practical equivalence on strict success

Use the same 10-point threshold symmetrically as the practical-equivalence region for `task_success`. A pairwise contrast is `supported practically equivalent` only when its complete 95% uncertainty interval lies inside **−10 to +10 percentage points**. A non-significant contrast or a point estimate inside that region is not sufficient; any interval crossing either boundary remains `inconclusive`.

### Material regression harm

Set the material-harm margin for the equal-scenario mean `regression_score` to an absolute **−5 percentage points**. Regression preservation uses a tighter tolerance than feature gain, while every required regression failure continues to force `task_success=false` through the accepted verifier contract. A Harness cannot receive the workload-level `supported strongest` claim when the paired 95% interval supports a regression-score loss worse than five points against an alternative.

### Secondary bounded quality

Use an absolute **+10 percentage-point** Smallest Worthwhile Difference for `acceptance_score` and predeclared bounded domain scores. A Score Contract may declare a different domain-specific threshold only with written justification before qualification and Suite sealing. These dimensions remain explanatory secondary outcomes and cannot compensate for or override strict `task_success`.

### Operational tradeoffs

Treat a **20% paired relative reduction** in unconditional expected cost or Harness elapsed time as worthwhile, and always show the corresponding absolute difference. Provider usage, host-resource measures, and limit incidence remain descriptive unless the Production Experiment Manifest predeclares a concrete hard constraint; v1 does not assign generic practical margins to them. Operational gains may guide routing only after the accepted quality non-inferiority or minimum-quality gate and never compensate for unsupported quality.

### Separate matched pilot

Run exactly **three matched pilot blocks per Scenario × exact-model profile**, covering all three eligible Harnesses in every Public and Private Suite cell under the production-intent controls. Across the 24-Scenario portfolio this is 216 planned pilot Trials per exact model profile and yields nine paired block vectors in each Suite × Workload Family × model stratum.

The pilot is a separately labelled diagnostic experiment. Its observations estimate paired strict-success discordance, bounded-score covariance, operational tails, heterogeneity, and complete-block loss; they never enter production estimates or claims. Freeze the three-block pilot before execution rather than extending it because an outcome looks promising or unstable. Accepted eligibility, disposition, and one-replacement rules still govern pilot cells.

The pilot itself is usable for production sizing only when every Scenario retains at least two analysis-complete Matched Blocks and each pilot Analysis Stratum retains at least 90% of its planned blocks after permitted replacements. Otherwise the pilot fails design qualification, no production count is selected from it, and the pilot must be explicitly redesigned and resealed rather than topped up selectively.

### Primary precision and simulation assurance

For each Suite × Workload Family × exact-model Analysis Stratum, select the smallest candidate production repetition count for which at least **80%** of pilot-based simulations yield a **95% paired `task_success` interval with half-width no greater than 20 percentage points** for all three pairwise Harness contrasts in that stratum.

The ±20-point target is deliberately an initial-benchmark precision bound, not a redefinition of the accepted 10-point Smallest Worthwhile Difference. It supports clear workload-level gaps without pretending the 24-Scenario portfolio can reliably resolve every 10-point effect at MVP-scale. A +10-point effect that the frozen design cannot resolve remains `inconclusive`.

Run **50,000 deterministic outer simulations per candidate and Analysis Stratum**. Within each Scenario, resample pilot Matched Block records while preserving the full three-Harness outcome vector for complete blocks and the terminal loss state for incomplete blocks, then execute the same frozen interval, eligibility, and completeness code used for production. For primary `task_success`, that interval code is the exact conditional paired stratified-bootstrap enumeration frozen by the scoring protocol, so there is no nested 50,000-resample inner bootstrap. Never resample Harness conditions independently. Derive every outer draw from the frozen counter-based SHA-256 sampler and publish golden vectors. Record the root seed, simulation and analysis implementation digests, environment and dependency identities, candidate pass rates, and selected count in the analysis manifest and sealed Production Design Selection.

A simulated contrast satisfies the precision target when `(upper − lower) / 2 <= 0.20` using the exact equal-tailed endpoint convention. A candidate satisfies one Analysis Stratum only when at least 40,000 of the 50,000 simulations satisfy that rule for each of all three pairwise Harness contrasts after applying the accepted completeness code. Boundary equality passes; any unavailable or invalid interval fails that simulation.

### Candidate production repetitions

Freeze the candidate set at **4, 6, 8, 10, or 12 repetitions per Scenario × exact-model profile**. Four is the smallest production design and exceeds the separate three-block pilot; 12 is the hard candidate maximum. Across 24 Scenarios and three Harnesses, this bounds production at 288–864 planned Trials per exact model profile, or 504–1,080 including the fixed pilot, before policy-compliant replacements.

The precision simulation selects only among these candidates before the Production Experiment Manifest is sealed. It may not interpolate an unlisted count or increase the count after production outcomes become visible.

If no candidate through 12 repetitions satisfies the precision and assurance rule for both Suite strata, that Workload Family × exact-model profile **fails production-design qualification** and no measured production Trial for that stratum starts. The project must explicitly redesign the candidate bound or precision policy, or remove the affected model profile from the pre-production roster, before sealing a new manifest. Running 12 repetitions and merely labelling the design underpowered is not permitted.

### Count-sharing boundary

Select **one fixed production repetition count per Workload Family × exact-model profile**. Apply it identically to that workload's three Public and three Private Scenarios and to all three eligible Harnesses. Simulate Public and Private Analysis Strata separately, then choose the smallest candidate that satisfies the precision target in both—equivalently, the larger of their candidate requirements.

This preserves Public/Private non-pooling while giving both Suite views equal evidence depth for the same workload and model. Do not reduce the count for an apparently stable Scenario, Harness, or Suite after seeing pilot or production outcome direction.

### Aggregate provider-spend ceiling

Cap provider spend for the complete initial campaign at **$5,000 USD**: at most **$1,000** for the separately labelled pilot and **$4,000** for production, aggregated across every exact model profile. These are hard coordinator and Credential Proxy ceilings backed by the applicable immutable Pricing Records; per-Trial limits remain separately frozen controls.

Before sealing the Production Experiment Manifest, use full pilot request/usage/cost vectors, the candidate repetition schedule, and applicable immutable Pricing Records to run 50,000 deterministic aggregate-spend simulations under the frozen model roster. Use the same counter-based sampler and define the empirical 95th percentile as the smallest sorted simulated spend whose cumulative proportion is at least `0.95`. The complete design qualifies only when that value is at or below $4,000. Boundary equality passes; unavailable usage or pricing fails qualification. If no qualifying complete design fits, reduce the pre-production model roster or obtain explicit budget reauthorization and seal a new Production Design Selection and manifest. Do not weaken margins, selectively omit expensive cells, begin an unaffordable design, or treat an aggregate-spend stop as publishable evidence. Reaching the ceiling before the locked design completes leaves the comparison incomplete and non-publishable under the accepted protocol.

### Incomplete blocks and frozen execution

Do not add post-freeze repetitions to replace inconvenient, high-variance, or missing outcomes. The accepted single replacement remains available only for a Planned Trial Cell whose effective prior attempt is `not_started` or `invalid_infrastructure`, under the identical Condition Fingerprint.

A claim-bearing workload/model result must retain both:

- at least **`r−1` analysis-complete Matched Blocks for every Scenario**, where `r` is that workload/model's frozen repetition count; and
- at least **90% of all planned Matched Blocks** in each Public or Private Suite × Workload Family × exact-model Analysis Stratum.

Failure of either evidence-completeness gate yields `unsupported comparison`. When both gates pass but the realized 95% interval misses the ±20-point precision target, the claim state is `inconclusive`. Reports always retain the planned, attempted, replacement, complete, and incomplete denominators.

## Constraints carried from accepted dependencies

- [Define the scoring and statistical analysis protocol](https://github.com/MihaiA24/model-benchmarking/issues/16) fixes the randomized Matched Block, paired estimands, 95% uncertainty, multiplicity family, disposition handling, fixed pre-production repetition selection, and rejection of outcome-triggered early stopping.
- [Select the initial scenario portfolio](https://github.com/MihaiA24/model-benchmarking/issues/20) fixes three independently authored Scenarios per Workload Family in each Public or Private Suite and permits only fixed-suite canonical claims.
- [Validate the blueprint and set the implementation handoff](https://github.com/MihaiA24/model-benchmarking/issues/25) remains blocked until this decision record and the parallel architecture decision are final.

## Dependency reconciliation and downstream boundary

- [Define the run ledger and provenance schema](https://github.com/MihaiA24/model-benchmarking/issues/21) records the selected repetition ordinal, analysis-manifest identity, Pricing Records, Planned Trial Cells, replacement lineage, effective complete-block denominators, and a reference to the sealed Production Design Selection without storing report-only simulations as Trial facts.
- [Prototype the generated benchmark report](https://github.com/MihaiA24/model-benchmarking/issues/22) renders these frozen margins, target, assurance, selected counts, spend qualification, and realized completeness without choosing or revising them.
- [Define suite versioning and refresh policy](https://github.com/MihaiA24/model-benchmarking/issues/23) seals practical margins and analysis semantics in Suite Releases while the Production Experiment Manifest pins model-specific selected counts and exact analysis implementation identities.
- [Set the benchmark architecture and reuse boundary](https://github.com/MihaiA24/model-benchmarking/issues/24) owns the minimal implementation seam for paired pilot simulation, count selection, aggregate-spend qualification, manifest sealing, and fail-closed preflight; it must consume this policy rather than re-decide it.
- [Validate the blueprint and set the implementation handoff](https://github.com/MihaiA24/model-benchmarking/issues/25) must prove the implementation plan can reproduce the 50,000-simulation selection, exact candidate and count-sharing rules, 95th-percentile spend gate, completeness states, and no-top-up boundary before implementation starts.

## Decision completeness

The pilot size, practical margins, precision and assurance targets, simulation count, candidate repetition bounds, count-sharing boundary, provider-spend ceilings, incomplete-block gates, and no-outcome-triggered-stopping behavior are fully specified. No background investigation was dispatched and no evidence remains outstanding.

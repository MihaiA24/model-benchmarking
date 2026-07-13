# Define the scoring and statistical analysis protocol

**Status:** Final research decision\
**Decision date:** 2026-07-11\
**Map:** [Design a real-world CLI benchmark for coding-agent harnesses](https://github.com/MihaiA24/model-benchmarking/issues/13)\
**Ticket:** [Define the scoring and statistical analysis protocol](https://github.com/MihaiA24/model-benchmarking/issues/16)

## Decision

Use a **predeclared randomized matched-block design** and analyze paired differences, not independent leaderboard averages. One matched block contains one trial for every eligible harness under the same suite visibility, workload, scenario version, exact provider/model profile, worker profile, budgets, and repetition ordinal. Randomize and balance harness execution order inside blocks, preserve the complete outcome vector for each trial, and make the block—not an individual unpaired trial—the comparative unit.

Report a **multi-dimensional result by workload and model stratum**. The sole primary quality endpoint is `task_success`, a strict all-required-acceptance-and-regression boolean. Also preserve bounded partial acceptance and regression scores, every scenario-specific verifier component, cost, elapsed time, provider usage, resource use, disposition, and integrity evidence. Never collapse them into a mandatory weighted overall score or universal winner.

Use paired effect estimates with 95% uncertainty intervals, exact paired binary analysis for `task_success`, paired stratified bootstrap intervals for bounded and operational outcomes, performance profiles, and pairwise probability of improvement. Make superiority claims only when both statistical and predeclared practical-effect criteria are met after multiplicity control. If quality, cost, or time trade off, report the nondominated set rather than forcing a winner.

Include valid crashes, malformed/no submissions, and budget-exhausted attempts in the harness estimand. Exclude and classify preflight/infrastructure invalidation, integrity invalidation, operator aborts, and unsupported combinations according to the accepted lifecycle contract; never convert structural missingness into a zero or silently replace a valid harness outcome.

Production uses a **fixed repetition count selected before measured execution** from a separate pilot and precision simulation. Do not stop early because one harness appears ahead or because an ordinary pointwise confidence interval happens to cross a threshold. Operational integrity/safety halts remain mandatory but are not statistical stopping rules. [Set repetition counts and precision targets](https://github.com/MihaiA24/model-benchmarking/issues/26) owns the remaining human choices about pilot size, smallest worthwhile effects, precision, repetition bounds, and spend.

## Estimands and analysis strata

### What is being estimated

For each declared analysis stratum, estimate how changing the **harness stock profile** changes outcomes while the scenario, provider/model route and effective settings, worker profile, budgets, instruction, verifier, and all other matched inputs remain fixed.

The canonical fixed-suite estimand is:

> The equal-scenario expected paired effect of one eligible harness versus another on the released scenario portfolio, under the declared provider/model and worker profile.

This is a finite-suite claim. It does not imply that the selected scenarios are a random sample of all professional development work. A second scenario-generalization analysis may be shown as exploratory once a workload contains enough independent scenarios, but it must not replace the fixed-suite result.

### Mandatory strata

Never pool across these boundaries in a primary result:

- public versus private suite;
- workload family;
- materially different provider/model profile;
- materially different worker profile;
- incompatible Scenario, Verifier, or Score Contract Version; or
- qualification profile with different effective settings or tool availability.

Report each exact model profile separately. A cross-model workload summary is allowed only when model profiles and weights were predeclared and every compared harness is eligible in every included cell. Preserve harness-by-model interaction instead of hiding it behind a single average.

Public and private suites remain separate evidence. They may be shown side by side as a robustness comparison, never merged into one score or used to tune each other after results are visible.

## Matched-block construction and randomization

A complete matched block contains exactly one planned trial for each eligible harness and fixes:

- Suite Release plus independent Scenario, Verifier, and Score Contract Version identities and package digests;
- workload label;
- provider, exact model identifier or declared alias limitation, endpoint, and effective supported settings;
- instruction, verifier, score-contract, budget, image, adapter, Worker Profile, and Worker Qualification identities;
- repetition ordinal and block identifier; and
- a predeclared randomized harness order.

Use a balanced cyclic or Latin-square order schedule across successive blocks so each harness appears equally often early, middle, and late. Random order controls temporal/provider drift; it does not make provider behavior deterministic. Run one measured trial at a time per worker as already accepted.

Create the complete block manifest before execution. Do not derive pair identity from timestamps, file order, or Harbor attempt order. Preserve paired observations together during every resample and test.

A block is analysis-complete when every planned condition has an analysis-eligible terminal record. A valid harness or budget outcome is analysis-eligible. `not_started` and `invalid_infrastructure` may receive a linked replacement under the accepted policy; the final replacement occupies the original block cell while every superseded record remains auditable. `invalid_integrity` and `aborted_operator` receive no automatic replacement, make the block incomplete for paired quality inference, and remain visible in the disposition report.

## Verifier score contract

### Common mandatory quality fields

Every scenario verifier must emit the following common fields in addition to its raw named checks:

| Field | Contract |
|---|---|
| `task_success` | Boolean. True only when every required acceptance group and every required regression group passes and the submission is valid. This is the primary quality endpoint. |
| `acceptance_score` | Bounded `[0,1]`. Predeclared weighted fraction of acceptance groups passed. Group weights are fixed in the scenario package and sum to one. |
| `regression_score` | Bounded `[0,1]`. Predeclared weighted fraction of baseline/regression groups passed. Group weights are fixed in the scenario package and sum to one. |
| `required_check_status` | Raw pass/fail/error/not-evaluable record for every required group, with verifier evidence references. |
| `domain_scores` | Optional named bounded dimensions such as data validity, security behavior, API compatibility, or performance correctness. Their direction and interpretation are versioned per scenario. |

Preserve raw check counts and logs. Aggregation uses equal scenario weight within a workload, not raw test count, so a scenario with hundreds of unit tests does not dominate one with a small but complete verifier. Scenario authors may weight check groups only before trials and must justify the weights; they may not tune them after seeing harness output.

`task_success` is a strict gate, not a weighted quality score. Partial scores explain near misses and support sensitivity analysis; they do not turn regressions into acceptable success.

### Total scoring for unsuccessful attempts

The scenario package must define a total, deterministic scoring path for every valid terminal harness outcome:

- A safe partial patch is verified normally, including after a budget limit.
- After a complete trusted Final Repository Capture, a missing Harness-produced Submission materializes as the Score Contract's declared no-op/rejected input: `task_success=false`, acceptance is scored against the unchanged baseline where applicable, and regression behavior remains measurable. An incomplete trusted capture or failed collector is `invalid_infrastructure` and never fabricates a baseline Submission or quality score.
- An empty, malformed, oversized, unsafe, or otherwise rejected handoff has `task_success=false` and a predeclared score mapping that cannot reward an unusable artifact. Preserve the rejection reason and raw artifact evidence.
- A harness crash or non-zero exit does not by itself assign quality. The verifier/no-submission rule assigns quality; the process outcome remains a separate dimension.
- A verifier failure caused by submitted code is a valid harness outcome. A verifier infrastructure failure independent of the submission is `invalid_infrastructure` and not a quality score.

This avoids success-only analysis and prevents crashes or limits from disappearing from the comparison.

## Disposition and missingness rules

| Disposition or eligibility state | Quality analysis | Operational analysis | Replacement and reporting |
|---|---|---|---|
| `valid_completed` | Include complete verifier vector. | Include all observed cost, time, usage, and resources. | Never replace. |
| `valid_harness_outcome` | Include `task_success=false` when required and the scenario's total verifier/no-submission vector. | Include consumption through terminal exit. | Never replace; report reason distribution. |
| `valid_limit_outcome` | Verify the safe partial submission; include resulting vector, or the declared no-submission mapping. | Include consumption to the enforced limit and name the exhausted budget. | Never replace; limit incidence is a primary operational fact. |
| `not_started` | No observation. | Preflight evidence only. | May receive one policy-compliant linked replacement; exclude the original from outcome estimates. |
| `invalid_infrastructure` | No benchmark-quality observation. | Report failed phase, evidence completeness, and replacement lineage. | May receive a linked replacement; never erase the invalid record. |
| `invalid_integrity` | Exclude from task-quality estimation because the experimental boundary is invalid. | Report integrity event and affected condition separately. | No automatic replacement; pause and investigate. A breach can disqualify publication. |
| `aborted_operator` | Exclude from comparative estimation. | Report elapsed/usage to abort and reason. | No replacement; never relabel as a timeout or harness loss. |
| Unsupported/unqualified combination | Structural missingness, not zero. | Report failed capability and qualification evidence. | Exclude from common-support comparison. Do not publish the intended three-way claim while any required harness is ineligible. |

Always publish planned, started, valid, invalid, replaced, incomplete-block, integrity, and operator-abort counts before outcome summaries. Show the analysis denominator for every statistic.

## Statistical summaries

### Per scenario and per harness

For every scenario/model stratum, report:

- all trial dispositions and `task_success` count/denominator;
- mean and distribution of `acceptance_score`, `regression_score`, and domain scores;
- cost, provider requests/tokens, elapsed time, CPU time, peak memory, storage/IO, process-limit and provider-limit events where available;
- median, interquartile range, arithmetic mean, and an empirical distribution/performance profile for skewed operational measures; and
- raw trial links and the host-derived patch/artifact for drill-down.

The arithmetic mean remains necessary for expected spend and expected resource demand. Medians and quantiles describe typical and tail behavior; none substitutes for the other. Do not report high quantiles when the sample is too small to support them without showing the raw observations.

### Workload aggregates

Use equal released-scenario weights unless the suite manifest predeclares different business weights before execution. For each common quality dimension, report:

1. equal-scenario mean and 95% paired stratified-bootstrap interval;
2. paired harness difference and interval;
3. interquartile mean as a robust supplementary aggregate;
4. a performance profile over meaningful score thresholds; and
5. pairwise probability of improvement with an interval.

For `task_success`, also report the paired discordance table and exact McNemar analysis. Use the two-sided exact binomial McNemar p-value on discordant counts, capped at one; when there are no discordant pairs, set `p = 1`. The effect estimate and interval remain primary; a p-value is corroborating evidence, never the conclusion by itself.

For cost, elapsed time, and positive resource measures, report paired absolute differences and ratios where defined. Keep failed and limited valid attempts in the unconditional expected-consumption estimand. Conditional “cost per success” may be shown only as a clearly labelled secondary ratio with both numerator and success denominator; never use it to hide expensive failures or divide by a near-zero success rate.

### Bootstrap structure

Freeze one executable interval specification in the Suite-owned analysis semantics and record its implementation/environment identity in every experiment. Preserve the complete Harness vector whenever a Matched Block is resampled.

For the primary pairwise `task_success` effect, orient each difference as first-named Harness minus second-named Harness and compute the equal-Scenario mean of complete-block values in `{-1, 0, 1}`. Use the exact conditional paired stratified-bootstrap distribution: within each Scenario, raise the empirical three-point block-difference distribution to that Scenario's number of complete blocks; convolve the three Scenario distributions; and apply equal Scenario weights. Compute probabilities with integer counts or exact rationals, not binary floating-point comparisons. The 95% interval is the equal-tailed percentile interval whose lower and upper endpoints are the smallest support values with cumulative probability at least `0.025` and `0.975`. Define interval half-width as `(upper − lower) / 2`. This exact enumeration is the production interval code used inside repetition sizing and avoids a nested Monte Carlo bootstrap.

For bounded secondary scores and any non-enumerable paired endpoint, use exactly 50,000 paired stratified-bootstrap resamples for a published interval. Derive every draw from a recorded root seed through a counter-based SHA-256 rejection sampler keyed by purpose, Analysis Stratum digest, contrast, resample index, Scenario identity, and draw index; publish golden vectors so dependency upgrades cannot change the stream silently. Use the same equal-tailed quantile rule. Degenerate samples produce their point-mass interval; unknown, non-finite, or empty inputs fail closed rather than inventing an interval.

- **Fixed-suite interval:** keep released Scenarios fixed; within each Scenario/model cell, resample Matched Blocks with replacement, then apply equal Scenario weights.
- **Scenario-generalization interval:** resample scenarios within a workload, then matched blocks within each sampled scenario. Label this exploratory and do not show it when too few independent scenarios make the result unstable.
- **Model-pooled interval:** only for a predeclared model mixture; resample within scenario/model cells and apply fixed model weights. Always retain per-model results.

Paired resampling is mandatory. Independently bootstrapping each harness destroys covariance and overstates uncertainty or invents comparisons that were never matched.

## Multiplicity and claim language

Predeclare one primary quality family per `suite visibility × workload × model profile`: the three pairwise harness contrasts on `task_success`. Use exact paired tests and Holm's sequential correction to control family-wise error at `0.05`. Keep partial quality, regression, cost, time, and resources as multi-dimensional secondary endpoints with effect estimates and intervals; label exploratory tests and do not mine them for an overall winner.

Before production, declare a smallest worthwhile difference for each decision-relevant dimension in its natural units. Use this claim vocabulary:

- **Supported superior:** in the named direction, the paired point estimate is at least the predeclared worthwhile margin, the lower 95% interval endpoint is strictly greater than zero, and the corresponding exact paired test passes Holm multiplicity control at family-wise `0.05`.
- **Supported practically equivalent:** the full 95% interval lies inside or exactly on the predeclared symmetric equivalence boundaries.
- **Inconclusive:** the interval crosses zero, the worthwhile margin, or both; absence of significance is not equivalence.
- **Unsupported comparison:** common support, qualification, integrity, or evidence completeness is missing.

A harness is “strongest” for a workload only when it is supported superior to both alternatives on `task_success`, has no supported material regression harm, and remains eligible under the integrity contract. Cost, time, and resource results then describe the operational tradeoff.

If no harness satisfies that rule, publish **no unique winner**. Show the Pareto/nondominated set across quality and operational dimensions. A cheaper or faster harness may be preferred only after a predeclared quality non-inferiority or minimum-quality rule is satisfied; do not compensate quality failure with an arbitrary weighted cost score.

Never announce a universal winner by averaging workloads, public/private evidence, and model profiles. A routing recommendation by workload or difficulty is a valid result when supported by the strata.

## Repetition sizing and stopping

### Separate pilot

After scenario and harness qualification but before production, run a separately labelled pilot using the same matched-block structure. Do not include pilot observations in publishable production estimates. Use them only to estimate:

- paired `task_success` discordance rates;
- within-scenario paired variance and covariance for bounded scores;
- cost, elapsed-time, and resource distributions, including limit incidence;
- scenario/model heterogeneity; and
- expected complete-block loss from infrastructure or integrity invalidation.

For candidate repetition counts, simulate the full predeclared paired analysis from pilot block vectors. Choose the smallest fixed count that meets the declared interval-width or decision-error target for every primary workload/model family with the declared simulation assurance, while remaining under the spend ceiling. Apply the same chosen count to every harness in a scenario/model cell. Freeze the count and analysis manifest before production.

[Set repetition counts and precision targets](https://github.com/MihaiA24/model-benchmarking/issues/26) decides the pilot count, smallest worthwhile effects, precision targets, candidate minimum/maximum repetitions, simulation assurance, and maximum spend after the initial portfolio is known.

### No outcome-triggered early stopping

The initial benchmark rejects outcome-triggered early stopping. Do not inspect accumulating winners, ordinary confidence intervals, p-values, success rates, or cost rankings to stop a condition early. Ordinary pointwise intervals are not time-uniform; repeatedly peeking and stopping requires a separately designed sequential method such as a confidence sequence.

The following are not statistical early stopping:

- fail-closed preflight;
- integrity pause or boundary-breach quarantine;
- hard safety, resource, request, token, or spend limit attached to one trial;
- operator abort of a suspected hang; or
- stopping the whole experiment because the approved aggregate spend ceiling has been reached.

These events retain their accepted dispositions. Reaching aggregate spend before the locked design completes yields an incomplete, non-publishable comparison rather than a result based on whichever cells finished first.

## Sensitivity and robustness analysis

Every published report includes these predeclared sensitivity views without changing the canonical estimand:

- strict `task_success` versus bounded partial acceptance;
- equal-scenario weights versus any predeclared business-weighted view;
- all exact model strata versus any predeclared model mixture;
- fixed-suite versus exploratory scenario-generalization intervals;
- results with and without any scenario whose verifier is later proven defective, with the affected suite version explicitly invalidated or amended; and
- impact of incomplete blocks and infrastructure replacement rates, without imputing unsupported or invalid outcomes.

Do not invent best/worst-case scores for unsupported combinations. If conclusions depend on an arbitrary weighting, margin, or missing-data assumption, show that dependency and report the decision as inconclusive.

## Required downstream contracts

- [Define the scenario package and authoring protocol](https://github.com/MihaiA24/model-benchmarking/issues/19) must encode mandatory score fields, check-group weights, total no-submission/rejected-handoff scoring, workload labels, public/private identity, and verifier evidence.
- [Select the initial scenario portfolio](https://github.com/MihaiA24/model-benchmarking/issues/20) must provide enough independent scenarios per workload for meaningful fixed-suite reporting and decide whether scenario-generalization claims are supportable.
- [Set repetition counts and precision targets](https://github.com/MihaiA24/model-benchmarking/issues/26) must lock the pilot, practical margins, precision, fixed repetition counts, and spend policy after the portfolio is known.
- [Define the run ledger and provenance schema](https://github.com/MihaiA24/model-benchmarking/issues/21) must represent block identity, planned condition, eligibility, replacement lineage, score vectors, analysis denominators, pricing provenance, resource evidence, and analysis-manifest version.
- [Prototype the generated benchmark report](https://github.com/MihaiA24/model-benchmarking/issues/22) must show paired effects and uncertainty, raw denominators/dispositions, performance profiles, model/workload/public-private strata, Pareto tradeoffs, and “no unique winner” without visual ranking sleight of hand.
- [Define suite versioning and refresh policy](https://github.com/MihaiA24/model-benchmarking/issues/23) must version verifier/score semantics and forbid cross-version pooling when an estimand changes.
- [Validate the blueprint and set the implementation handoff](https://github.com/MihaiA24/model-benchmarking/issues/25) must verify that every claimed comparison has common support, a locked repetition policy, complete block joins, and an executable analysis specification.

## Primary-source basis

The protocol adapts the following primary sources rather than copying a leaderboard convention:

1. The U.S. NIST/SEMATECH handbook's [randomized block design](https://www.itl.nist.gov/div898/handbook/pri/section3/pri332.htm) treats the block as a way to account for nuisance variation while estimating the treatment effect. Here, scenario/model/repetition/worker context is the block and harness is the treatment condition.
2. Agarwal et al., [“Deep Reinforcement Learning at the Edge of the Statistical Precipice”](https://proceedings.neurips.cc/paper/2021/hash/f514cec81cb148559cf475e7426eed5e-Abstract.html), demonstrates that few runs and point estimates can reverse benchmark conclusions. Its official [`rliable` implementation](https://github.com/google-research/rliable) supplies stratified bootstrap intervals, interquartile means, performance profiles, and probability-of-improvement summaries. The coding benchmark adopts those uncertainty and profile tools but does not copy a normalized scalar score.
3. Demšar, [“Statistical Comparisons of Classifiers over Multiple Data Sets”](https://www.jmlr.org/papers/v7/demsar06a.html), supports treating datasets/tasks as repeated comparison units and using paired nonparametric methods rather than independent per-run tests. This protocol preserves richer paired trial blocks and reports effect sizes rather than relying on ranks alone.
4. The American Statistical Association's [statement on p-values](https://www.tandfonline.com/doi/full/10.1080/00031305.2016.1154108) states that scientific or policy decisions should not rest only on crossing a p-value threshold. The benchmark therefore leads with effects, intervals, practical margins, and denominators.
5. R's official [`p.adjust` documentation](https://stat.ethz.ch/R-manual/R-devel/library/stats/html/p.adjust.html) documents Holm's sequentially rejective family-wise correction and its dependence advantages over less general procedures. The benchmark applies it only to the small predeclared primary contrast family.
6. SciPy's official [`bootstrap`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html) and [`permutation_test`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.permutation_test.html) contracts explicitly support paired resampling and exact/approximate paired randomization implementations. The implementation must pin the analysis environment and record its seed and resample count.
7. Howard et al., [“Time-uniform, nonparametric, nonasymptotic confidence sequences”](https://arxiv.org/abs/1810.08240), distinguishes time-uniform confidence sequences from ordinary pointwise intervals under repeated looks. The initial protocol avoids that extra sequential design by locking production repetitions and rejecting outcome-triggered stopping.
8. The ICH E9(R1) [estimand guideline](https://database.ich.org/sites/default/files/E9-R1_Step4_Guideline_2019_1203.pdf) requires alignment between the target estimand, intercurrent-event handling, estimation, and sensitivity analysis. Although written for clinical trials, that principle directly motivates declaring how crashes, limits, invalid infrastructure, integrity events, aborts, and unsupported conditions enter—or do not enter—the harness estimand.

## Evidence limits

- These sources establish statistical design and reporting principles; they do not determine the organization's smallest worthwhile quality gain, acceptable uncertainty, or spend ceiling. Those are explicit human decisions routed to [Set repetition counts and precision targets](https://github.com/MihaiA24/model-benchmarking/issues/26).
- Bootstrap intervals cannot compensate for too few independent scenarios or systematically unrepresentative tasks. The portfolio decision remains substantive evidence, not a statistical afterthought.
- Provider model aliases may remain mutable and provider behavior may drift within a block. Balanced order and exact request evidence reduce and reveal this risk; they do not remove it.
- No background research agents were dispatched. All cited consequential claims were checked against the linked primary paper, official documentation, or first-party source repository before this decision was written.

# Define suite versioning and refresh policy

**Status:** Final decision
**Decision date:** 2026-07-12
**Map:** [Design a real-world CLI benchmark for coding-agent harnesses](https://github.com/MihaiA24/model-benchmarking/issues/13)
**Ticket:** [Define suite versioning and refresh policy](https://github.com/MihaiA24/model-benchmarking/issues/23)

## Accepted decisions

### Canonical Suite Release identity and namespaces

Define each sealed **Suite Release** by the tuple `(suite_namespace, suite_version, suite_manifest_sha256)`. The Suite Version is a human-facing, monotonically increasing SemVer label within its namespace; the manifest SHA-256 digest is the immutable byte identity. Both remain explicit wherever a release is declared or referenced.

Use exactly three Suite namespaces with independent version streams:

- `public` contains releasable measured Scenario Packages and Public Suite evidence;
- `private` contains access-controlled measured Scenario Packages and Private Suite evidence; and
- `calibration` contains non-measured diagnostic fixtures from the Legacy Calibration Suite.

A frozen production experiment pins exactly one Public Suite Release and one Private Suite Release. It may also pin a Calibration Suite Release for pre-production or diagnostic use, but Calibration Scenarios never enter production Planned Trial Cells, Matched Blocks, workload aggregates, uncertainty analyses, or comparative claims.

Public and Private releases do not share a version counter. Rotating or correcting one namespace does not force an unchanged release in another namespace to be reissued. Reports preserve both exact release identities and keep their evidence in separate Analysis Strata as already accepted.

### Sealed-release immutability boundary

Sealing a Suite Release makes its canonical manifest and every transitively referenced suite-owned input immutable. The sealed identity covers:

- the namespace, Suite Version, canonical manifest bytes, and manifest digest;
- the exact Scenario roster and portfolio-cell assignments;
- each Scenario ID plus independent Scenario Version, Verifier Version, and Score Contract Version identities; package payload and lock; Scenario Baseline; Developer Brief; and Check Group identities;
- ecosystem, Workload Family, difficulty, visibility, Evaluated Repository lineage, eligibility, disclosure, and supported-claim metadata;
- content-addressed Package Qualification Records and every approved `standard-v1` exception; and
- for a Private Suite Release, the access-controlled Private Roster Manifest identity and the published Private Suite Commitment created from it before the outer release manifest is sealed.

The manifest uses deterministic canonical serialization and a deterministic Scenario order so regenerating it from unchanged inputs reproduces the same digest. Transitive identity is strict: changing a referenced byte or semantic declaration changes the release even when a top-level locator or friendly name is unchanged.

Never rebuild, edit, or republish a sealed release under the same identity. A roster, classification, package, brief, verifier, scoring, weight, qualification, disclosure, or other referenced change creates a new Suite Release in that namespace. Preserve the prior release and its manifest permanently while any evidence or claim references it.

Keep experiment-varying Harness, Stock Profile, provider/model, Worker Profile, repetition, pricing, and analysis-execution choices outside the Suite Release. They are pinned separately by the experiment and Run Ledger so multiple explicitly declared conditions can evaluate the same immutable release without changing what the suite means.

### Independent Scenario, verifier, and score versions

Keep three independent SemVer-plus-digest component identities in every applicable Scenario Package, Suite manifest, Planned Trial Cell, Trial Attempt Record, and Result Bundle:

- **Scenario Version** identifies the Scenario Baseline, Developer Brief, declared resources, Submission boundary, and observable task meaning.
- **Verifier Version** identifies the executable checks, fixtures, environment, and verifier behavior.
- **Score Contract Version** identifies Check Groups, requiredness, total-scoring rules, score directions, weights, and missingness semantics.

Apply the same conservative component bump classes:

- **PATCH** permits only non-semantic metadata or canonicalization changes and code refactors proven equivalent through sealed conformance replay.
- **MINOR** permits a compatible additive or refresh change that preserves every existing required behavior and core score meaning but requires qualification and release-specific evidence. Examples include a trial-visible baseline or toolchain refresh that preserves the Developer Brief's observable contract, or a new optional diagnostic dimension that cannot affect existing scores or claims.
- **MAJOR** covers any changed observable requirement, required check, Submission semantic, `task_success` rule, weight, direction, or missingness meaning.

A substantively different replacement Scenario receives a new Scenario ID rather than reusing a major version. Every component change regenerates `scenario.lock.json` and creates a Suite Release; any component MAJOR forces a Suite MAJOR.

### Suite Version bump rules

Use SemVer to communicate the class of Suite change, not to grant automatic pooling compatibility:

- **PATCH** records a correction or enrichment that changes no trial-visible input, verifier behavior, score, weight, roster, eligibility rule, estimand, practical margin, or analysis semantic. Examples include a corrected provenance citation, license metadata, or non-authoritative storage locator. The correction still produces a new sealed Suite Release; never relabel evidence collected under the prior release.
- **MINOR** records compatible portfolio maintenance that preserves the namespace's frozen portfolio contract and every analysis semantic. Examples include rotating or replacing one measured Scenario within the same ecosystem × Workload Family × difficulty cell, or adding or removing Calibration fixtures. A changed measured Scenario requires fresh evidence and release-specific reporting.
- **MAJOR** records any incompatible change to portfolio shape, Scenario meaning, verifier or score semantics, Check Groups or Scenario weights, workload taxonomy, eligibility or supported-claim rules, fixed-suite estimand, practical margins, multiplicity or analysis rules, or Suite namespace meaning.

Adding, removing, or moving a measured portfolio cell is a MAJOR change. Replacing its Scenario while preserving the accepted cell contract is MINOR. A change with uncertain semantic effect takes the more conservative bump until compatibility is proven; never classify it downward merely to preserve a version number.

### Dimension-by-dimension compatibility

Never infer compatibility from SemVer alone. A separately sealed, content-addressed **Suite Compatibility Record** identifies one source and one target Suite Release and assesses each of these dimensions:

- Scenario inputs and required observable behavior;
- verifier checks, total-scoring rules, score directions, and missingness meanings;
- Check Group and Scenario weights;
- portfolio roster, cell mapping, and fixed-suite estimand;
- practical margins, multiplicity, and claim-state rules; and
- analysis strata, formulas, resampling, and sensitivity semantics.

Use the closed status set `identical`, `proven_equivalent`, `incompatible`, and `unassessed` for every dimension. Only `identical` and `proven_equivalent` are compatible. An absent, uncertain, or unassessed mapping fails closed.

A code-only verifier or analysis refactor may be `proven_equivalent` only through pinned conformance evidence. If the mapping proposes reuse of historical evidence, replay every retained analysis-eligible Submission in a fresh qualified verifier environment and require identical raw Check Group statuses and derived score vectors; seal the replay inputs, implementation identity, outputs, and comparison report as derivative evidence without rewriting the original Run Ledger.

Any roster change changes the finite-suite estimand even when it is a valid MINOR rotation. Any changed practical margin, weight, missingness meaning, or claim-state rule is incompatible for the affected claim. Compatibility is therefore dimension- and claim-specific; sharing a MAJOR version is never sufficient permission to pool.

### Cross-version comparison modes

Permit cross-version use only through one of three explicit modes:

1. **Equivalent carry-forward** applies only to PATCH releases when every trial- and claim-relevant compatibility dimension is `identical` or `proven_equivalent`. Existing records retain their original Suite Release identity. A target-release report references the source evidence and Suite Compatibility Record rather than copying, migrating, or relabelling the observations.
2. **Side-by-side reporting** may show any releases as separate fixed-suite Analysis Strata with separate denominators, estimates, and claim states. It never pools observations, computes a shared winner, or presents an unqualified longitudinal trend.
3. A **Bridge Study** may compare MINOR or MAJOR releases through a predeclared set of unchanged anchor Scenarios rerun contemporaneously under otherwise identical declared conditions. It has its own diagnostic estimand, Planned Trial Cells, Matched Blocks, analysis manifest, and report stratum; it never replaces either release's fixed-suite result.

Never splice historical Trials for unchanged Scenarios together with new Trials for rotated or corrected Scenarios to manufacture a target-release aggregate. Such a mixture breaks the accepted matched design and hides temporal or provider drift. A new measured MINOR or MAJOR release requires a complete new production experiment for its own fixed-suite claim.

When any compatibility dimension required by a proposed claim is `incompatible` or `unassessed`, label the cross-version comparison `unsupported comparison`. Show only separate release history, provenance, invalidation state, and the exact failed dimensions.

### Private Suite rotation

Never rotate a Private Scenario during a sealed production experiment. After every completed production experiment, perform and record an exposure, contamination, provenance, and verifier-defect review before approving further measured use.

Before the next production experiment, rotate four of the 12 Private Scenarios when either 12 months have elapsed since the Private Suite Release was sealed or that release has supported two completed production experiments, whichever comes first. Select exactly one Scenario from each Workload Family and preserve every selected ecosystem × Workload Family × difficulty cell. Balance the selected ecosystems across successive rotations so one ecosystem is not refreshed systematically more or less often.

Rotate affected cells before any further measured use after confirmed unauthorized disclosure, answer leakage, benchmark-targeted tuning or training, or material contamination. A credible unresolved suspicion pauses affected use and publication pending investigation. Use targeted cell-preserving rotation by default; replace the complete Private Suite only when compromise or provenance failure is systemic.

Never choose rotation targets or replacements from observed Harness success, rank, post-trial difficulty, or whether a Scenario changes a conclusion. Predeclare the cells selected for scheduled rotation, apply the original qualification and independent-review gates, retain every rejection and rotation reason, seal a new MINOR Private Suite Release, and publish its new Private Suite Commitment before measured Trials.

### Leakage, contamination, defects, and corrections

Use one append-only incident workflow: pause affected use and publication; identify the affected assets, conditions, and earliest plausible exposure or defect time; seal the investigation evidence; then record the outcome through Ledger Amendments, report supersession, and a replacement Suite Release where required. Never rewrite or delete original Suite, Trial, bundle, or report records.

Apply these responses:

- Confirmed unauthorized Private disclosure or answer-bearing Public leakage before or during measured use invalidates affected Scenario evidence from the earliest affected time. Retire and rotate the cell and supersede every dependent aggregate and report.
- Leakage proven to have occurred only after completed Trials preserves earlier evidence with an explicit validity cutoff but prohibits future measured use. If timing cannot be bounded, invalidate all evidence that could be affected.
- Suspected model contamination is disclosed and investigated. Canary strings, output similarity, or public availability alone do not prove model training. Confirmed benchmark-targeted training or tuning invalidates the affected model × Scenario evidence and retires the Scenario from further measured use.
- A verifier implementation refactor that reproduces identical raw statuses and score vectors under the sealed replay contract may create a PATCH release and Suite Compatibility Record without invalidation.
- A verifier defect that changes any raw Check Group status, derived score, total-scoring behavior, or required observable behavior invalidates affected evidence. Publish a MAJOR Verifier Version and Suite Version and run a fresh complete production experiment. Historical re-verification is diagnostic sensitivity evidence only and never becomes the original observation or the corrected release's canonical fixed-suite result.
- A non-semantic provenance correction creates a PATCH release and applicable Ledger Amendment without invalidation. An unverifiable source or digest, licensing or redistribution failure, wrong Scenario Baseline identity, or other provenance error that breaks reproducibility invalidates affected evidence and blocks affected distribution until a qualified replacement exists.

An invalidation names its exact Scenario, model or condition where applicable, Trial Attempt and report scope, reason, evidence, decision author, decision time, and effective cutoff. Preserve original dispositions and scores as historical facts; the effective view marks them excluded rather than mutating them.

### Suite and production-experiment pinning boundary

The Suite Release pins the suite-owned comparison contract: every Scenario and package identity, accepted Execution Profile requirement and exception, portfolio and Scenario weights, fixed-suite estimand, practical margins, multiplicity and claim-state rules, and analysis semantics. These identities complete the release's transitive immutability boundary.

A separately sealed **Production Experiment Manifest** pins:

- the exact Public and Private Suite Release identities;
- pinned Harbor release, commit, task checksums, and job configuration;
- every Harness release or commit, Stock Profile, CLI artifact, adapter declaration, and launch-shim digest;
- Provider Route, requested model identity, effective supported settings, and explicit alias limitation;
- resolved Execution Profile, Worker Profile, Worker Qualification Record, budgets, Provisioning Manifest, and applicable Qualification Bundles;
- accepted Production Design Selection, Matched Block construction, repetition count, randomized order schedule, and Planned Trial Cells; and
- analysis-manifest, implementation, environment, dependency, seed, and resample-count or exact-enumeration identities.

Pricing remains a separately versioned observation-time Pricing Record and does not change either the Suite Release or declared experimental condition.

Enforce this field-ownership matrix rather than mirroring mutable values across artifacts:

| Authority | Owns | May only reference |
| --- | --- | --- |
| Scenario Package and Package Qualification Record | Scenario, Verifier, Score Contract, package, baseline, brief, resource, provenance, and package-qualification identities | required Execution Profile version |
| Suite Release | exact roster, package/component identities, Suite weights, fixed-suite estimand, practical margins, multiplicity, claim semantics, analysis semantics, disclosure, lifecycle, and compatibility | Package Qualification Records |
| Production Design Selection | frozen pilot ledger, exact sizing/interval implementation, candidate pass rates, selected repetitions, model roster, Pricing Records, and spend qualification | Suite Releases and analysis semantics |
| Production Experiment Manifest | Harness/Stock Profile/adapter, Provider Route/model/settings, Worker and Worker Qualification, resolved Execution Profile, budgets, randomized schedule, Planned Trial Cells, exact analysis implementation/environment/seed, and accepted Production Design Selection | Suite-owned semantics without copying or overriding them |
| Trial Attempt Record and Result Bundle | observed lifecycle, controls, usage, evidence, outcomes, dispositions, and artifact availability | every governing declaration by typed identity |

A validator rejects a field owned by another artifact when it is duplicated as a second authority, and rejects a cross-reference whose identity or semantic version does not match the owner. Experiment-varying Qualification Bundles never enter Suite identity; Suite-owned Package Qualification Records never prove an exact Harness/model/worker condition.

Changing a Harness, Stock Profile, adapter, Provider Route, requested model or effective setting, Worker Profile, or analysis implementation does not by itself bump the Suite Version. It creates a new Production Experiment Manifest and Condition Fingerprint, requires every applicable qualification to run again, and remains a separate Analysis Stratum wherever effective settings, worker behavior, or analysis semantics differ.

Seal the Production Experiment Manifest before the first measured Trial. After that boundary, never mutate only the remaining cells: a changed pin creates a new experiment. If a provider-reported model revision changes, pause and split the condition rather than pooling it. When the provider exposes no immutable revision, preserve the accepted alias limitation, execute blocks in a balanced contiguous schedule, and never claim identical hidden weights.

### Deprecation, retirement, and evidence retention

Track Suite Release lifecycle through append-only registry events rather than manifest edits. Use the closed lifecycle set `active`, `deprecated`, and `retired`; keep evidence `invalidated` state orthogonal because lifecycle eligibility and scientific validity are different facts.

- An `active` release may be selected for a new Production Experiment Manifest.
- A `deprecated` release may not be selected for an experiment sealed after its announced sunset. An experiment sealed before the sunset may finish only when no integrity, leakage, defect, or provenance pause applies.
- A `retired` release may produce no new measured Trial or Bridge Study. Prior evidence and claims remain historical only to the extent that their effective invalidation state permits.

A replacement release, scheduled Private rotation, unsupported immutable dependency, or policy supersession may deprecate a release. Leakage, verifier or provenance failure, or systemic compromise may cause immediate retirement and a separately scoped evidence invalidation.

Retirement never deletes, mutates, or aliases evidence. Retain canonical Suite manifests, Scenario Package locks and bytes, source snapshots, verifier and Reference Solution assets, qualification evidence, commitments, Run Ledgers and Amendments, Result Bundles, Suite Compatibility Records, incident records, and sealed reports without automatic expiry while any published claim or organizational decision depends on them. Preserve release identities, manifests, artifact descriptors and digests, ledger history, amendments, and report provenance indefinitely.

Keep retired Private assets under their original access controls. Retirement does not automatically disclose them; any later release requires a separate licensing, confidentiality, secret-scan, and integrity review and produces a disclosure-safe sealed derivative without changing the canonical private evidence.

### Report behavior for incompatible or invalidated evidence

Every report page and export displays the exact Suite namespace, Suite Version, Suite manifest digest, lifecycle state, effective validity state, Production Experiment Manifest digest, and analysis-manifest digest for its evidence.

Without a Suite Compatibility Record that supports the proposed claim, a cross-version view uses separate release panels headed `unsupported comparison`, lists every incompatible or unassessed dimension, and emits no pooled chart, shared effect, winner, or longitudinal trend.

When evidence is invalidated, mark every affected workload × model claim `unsupported comparison` and remove it from routing and supported-winner headlines. Display planned, original, and effective denominators; excluded cells; effective cutoff; reason; incident and Ledger Amendment identities; and links to both original and effective records. Unaffected strata remain publishable only when their complete common-support and multiplicity families remain intact. A view with a defective Scenario removed is diagnostic sensitivity analysis, not a replacement fixed-suite claim.

Never edit a sealed report. Publish a separately sealed superseding report or withdrawal notice that references the original report digest and effective amendments. An append-only report registry identifies the effective derivative while retaining the original bytes for audit. Deprecated or retired evidence receives a visible historical-status banner; invalidated evidence receives the stronger banner `must not support decisions`.

## Dependency reconciliation

- [Define the scenario package and authoring protocol](scenario-package-and-authoring-protocol.md): preserves whole-package payload and lock identity, immutable briefs, baselines, separate verifiers, score declarations, qualification, `standard-v1`, visibility, and non-circular Suite sealing while adding the independently versioned Scenario, Verifier, and Score Contract identities required by the ledger.
- [Select the initial scenario portfolio](initial-scenario-portfolio.md): preserves the 12-Public/12-Private matrix, fixed cells and difficulty bands, qualification-only pre-trial replacement, Private commitment, contamination limits, non-pooled Calibration namespace, and prohibition on outcome-selected rotation.
- [Define the scoring and statistical analysis protocol](../research/scoring-and-statistical-analysis-protocol.md): preserves fixed-suite estimands, exact strata, paired blocks, frozen weights and practical margins, no silent cross-version pooling, diagnostic-only sensitivity analysis, and `unsupported comparison` when common support or semantics fail.
- [Define the run ledger and provenance schema](run-ledger-and-provenance-schema.md): preserves independent typed identities, strict schema compatibility, immutable Planned Trial Cells and Trial Attempt Records, append-only Amendments and invalidation, Condition Fingerprints, Qualification Bundles, Pricing Records, content-addressed evidence, and original-versus-effective views.
- [Prototype the generated benchmark report](generated-benchmark-report.md): preserves separate Public and Private views, exact version strata, denominator-first claims, immutable static derivatives, neutral no-winner behavior, and typed evidence drill-down while adding fail-closed compatibility and supersession display rules.
- [Coding-Agent Harness Benchmarking](../CONTEXT.md): defines the canonical Suite Release, Suite Version, compatibility, Bridge Study, Production Experiment Manifest, and component-version terminology used here.

No accepted dependency is reopened. Where this policy is stricter, it specializes an ownership boundary those decisions explicitly routed here.

## Downstream contracts

- [Set repetition counts and precision targets](https://github.com/MihaiA24/model-benchmarking/issues/26) supplied the final practical margins, candidate repetitions, precision targets, completeness rules, and spend gates now consumed by Suite Releases, Production Design Selections, and Production Experiment Manifests.
- [Set the benchmark architecture and reuse boundary](https://github.com/MihaiA24/model-benchmarking/issues/24) implements canonical Suite manifests, component identities, compatibility and incident records, experiment manifests, lifecycle registries, validators, sealing, qualification replay, retention, and report supersession without introducing a second runner.
- [Validate the blueprint and set the implementation handoff](https://github.com/MihaiA24/model-benchmarking/issues/25) verifies that Suite, experiment, ledger, analysis, and report identities join; that invalidation and compatibility fail closed; and that the implementation sequence preserves every accepted boundary.

## Decision completeness

All versioning, sealing, component-version, compatibility, cross-version comparison, rotation, incident-response, pinning, lifecycle, retention, and report-supersession branches are resolved. No investigation was delegated for this ticket and no evidence remains outstanding. This record is the complete decision contract; implementation consumes the final repetition values and the final validation handoff named above.

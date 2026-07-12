# Define the run ledger and provenance schema

**Status:** Final decision
**Decision date:** 2026-07-12
**Map:** [Design a real-world CLI benchmark for coding-agent harnesses](https://github.com/MihaiA24/model-benchmarking/issues/13)
**Ticket:** [Define the run ledger and provenance schema](https://github.com/MihaiA24/model-benchmarking/issues/21)

## Accepted decisions

### Canonical ledger shape and immutability boundary

Use one versioned, append-only **Run Ledger** as the canonical structured record. Its initial schema has exactly three immutable record families:

1. **Planned Trial Cells** are frozen before execution. They preserve the predeclared matched-block design, including cells that never produce a started Trial.
2. **Trial Attempt Records** represent coordinator attempts to fulfill Planned Trial Cells, including attempts that never reach measured execution. Each links to exactly one Planned Trial Cell and becomes authoritative after reaching a terminal disposition and being independently schema-validated and sealed. It references a sealed content-addressed Result Bundle when bundle sealing succeeds; otherwise it preserves the accepted explicit missing or quarantine state and applicable invalid disposition.
3. **Ledger Amendments** record later correction, supersession, or invalidation by pointing to prior records. They never rewrite or delete those records.

Mutable coordinator state may exist while a Trial is in progress, but it is explicitly non-authoritative and outside the canonical ledger. If execution or evidence collection fails, the coordinator must still produce the applicable terminal Trial Attempt Record rather than leaving a partially authoritative row.

Keep raw Harbor outputs, process and proxy evidence, verifier evidence, submissions, and other declared artifacts in the content-addressed Result Bundle. Canonical ledger records reference those artifacts instead of duplicating them. SQL tables, CSV exports, dashboards, and reports are derived projections that may be regenerated; none is authoritative benchmark evidence.

This boundary preserves the frozen comparison design, records every physical attempt and replacement, and supports append-only correction without introducing a generalized event-sourcing system.

### Typed identities and condition fingerprint

Keep every independently versioned boundary as a separate typed identity rather than hiding provenance inside one composite identifier. A Planned Trial Cell and its Trial Attempt Records preserve:

- Suite Release identity and its Public or Private namespace, plus the Private Suite Commitment and access-controlled Private Roster Manifest identity where applicable;
- Scenario ID and independent Scenario Version, Verifier Version, and Score Contract Version identities; Scenario Package payload and lock digests; Package Qualification Record; Developer Brief digest; and resolved Scenario Baseline tree digest;
- pinned Harbor release and commit, Harbor task checksum, lock and job-configuration digests, and Harbor-native job and Trial UUIDs;
- Harness identity, pinned Stock Profile, CLI artifact, adapter declaration, and launch-shim digests;
- provider identity, endpoint and route identity, requested model identifier, provider-reported model or revision when exposed, and effective supported settings; and
- resolved Execution Profile and Worker Profile identities, Worker Qualification Record, budgets, Production Design Selection for production cells, planned and actual execution order, repetition ordinal, workload and analysis-stratum labels, and frozen analysis-manifest identity.

The typed identities are authoritative. Derive one **Condition Fingerprint** deterministically from their canonical serialization to prove equality and support joins, but never use it as a substitute for the component identities.

Treat a provider model alias as an explicit provenance limitation when the provider exposes no immutable model revision. A Condition Fingerprint proves that the benchmark requested the same recorded condition; it does not prove that a mutable alias resolved to identical model weights or provider internals.

### Trial Attempt identity and lifecycle timing

Assign a globally unique Trial Attempt identity when the coordinator begins an attempt to fulfill a Planned Trial Cell, before preflight. Every such attempt produces exactly one terminal Trial Attempt Record, including an attempt whose disposition is `not_started` because measured execution never began.

If preflight succeeds, bind the Trial Attempt identity explicitly to Harbor's job and Trial UUIDs and to exactly one measured Trial. A replacement receives a new Trial Attempt identity, links to the same Planned Trial Cell, and never reuses or overwrites the identity of the attempt it replaces.

Preserve this closed lifecycle projection in the terminal record:

1. attempt created;
2. preflight started and ended;
3. agent environment ready;
4. Harness launched;
5. root process exited;
6. complete process tree stopped;
7. Submission capture ended;
8. verification started and ended;
9. teardown ended; and
10. Result Bundle sealed.

Record UTC time for cross-system correlation and monotonic elapsed measurement for durations at every applicable boundary. The canonical Harness latency is the monotonic interval from Harness launch until the complete process tree stops. Represent an inapplicable or unobserved boundary explicitly with its reason; never infer or synthesize a timestamp.

Keep raw lifecycle events and clock-source evidence in the Result Bundle. The Run Ledger stores this fixed lifecycle projection rather than introducing a generalized event stream.

### Declared, qualified, and observed controls

Represent model and configuration controls through three distinct evidence layers:

1. The **Declared Control Profile** is authoritative and frozen in each Planned Trial Cell. A strict allowlist preserves every comparison-relevant value and explicit omission or default state: Provider Route, requested model, supported sampling, context and tool controls, provider ceilings, Execution Profile, Stock Profile, adapter mapping, and configuration digests. It contains no secret values.
2. The **Qualification Bundle** is an immutable content-addressed artifact produced before measured Trials and referenced by the Planned Trial Cell. It includes or links both adapter/model and worker-enforcement evidence. Configuration introspection, Credential Proxy observations, and worker capability probes must prove that the exact Harness, Stock Profile, adapter, Provider Route, Execution Profile, and Worker Profile combination launches headlessly, maps every declared control correctly, and enforces and observes the required runtime controls. Any changed identity, mapping, profile, or declared control requires requalification.
3. The **Observed Control Projection** is stored in every Trial Attempt Record and backed by raw redacted evidence in its Result Bundle. It records what the launch shim, Harness, and Credential Proxy actually observed and whether those observations matched the declared profile.

Fail closed on control drift. A mismatch discovered before Harness launch yields `not_started`; one discovered only after measured execution begins yields `invalid_infrastructure`. An ignored, overridden, or unsupported declared setting makes the combination unqualified. A provider-opaque immutable model revision remains an explicit limitation, rather than a mismatch, when the exact requested alias and Provider Route were verified as declared.

The Condition Fingerprint covers the declared condition, not the Qualification Bundle digest. Repeating qualification for an unchanged condition may create new provenance evidence without creating a false new experimental condition.

### Eligibility, termination, and disposition

Keep planned-cell eligibility, Trial Attempt disposition, and termination mechanism orthogonal.

Planned-cell eligibility uses the closed set `eligible`, `unsupported`, and `unqualified`. An unsupported or unqualified cell preserves its reason and Qualification Bundle evidence but produces no Trial Attempt unless a diagnostic preflight is explicitly attempted. It is structural missingness, never a zero score or failed Trial.

Every Trial Attempt has exactly one top-level disposition from the already accepted closed set:

- `not_started`;
- `valid_completed`;
- `valid_harness_outcome`;
- `valid_limit_outcome`;
- `invalid_infrastructure`;
- `invalid_integrity`; or
- `aborted_operator`.

Record termination separately with exactly one mechanism: `not_launched`, `process_exit`, `enforced_limit`, `integrity_stop`, `infrastructure_stop`, or `operator_abort`. Also preserve the terminal lifecycle phase, a namespaced reason code, the responsible boundary, and raw evidence references. Exit code, signal, exhausted budget dimension, policy event, and verifier outcome remain separate facts.

The trusted coordinator assigns disposition from the recorded facts; neither the Harness nor Harbor's generic success or error field is authoritative. A zero exit does not imply task success, and a non-zero exit may remain a valid scored Harness outcome. There is no generic `timeout`: elapsed time is observational, while an enforced token, request, spend, CPU, memory, process, storage, handoff, or verifier limit names its exact exhausted dimension.

Correct a disposition only through a Ledger Amendment; never mutate the original Trial Attempt Record.

### Retries, replacements, supersession, and invalidation

Freeze one narrow lineage policy for the initial benchmark.

Harness-native model or request retries remain inside the same Trial Attempt, and every resulting request, usage quantity, and cost is counted. The Credential Proxy and adapter add no retries, fallback, cache, or response repair.

Only a Trial Attempt with effective disposition `not_started` or `invalid_infrastructure` may receive an experimental replacement. Permit at most one replacement per Planned Trial Cell. The replacement receives a new Trial Attempt identity, references the original, preserves the same Condition Fingerprint, and records its actual later execution order. Any changed declared condition creates a new Planned Trial Cell or experiment manifest rather than a replacement. If the replacement also ends before producing an eligible observation, the cell remains incomplete.

Never replace `valid_completed`, `valid_harness_outcome`, `valid_limit_outcome`, `invalid_integrity`, or `aborted_operator`. An integrity invalidation pauses the affected batch for investigation; an operator abort remains an incomplete cell. Neither creates another opportunity for the Harness condition.

Use exactly one closed Ledger Amendment operation for every post-seal lineage change. Reject unknown operations, multiple operations in one Amendment, cycles, a second replacement designation for one Planned Trial Cell, and any chain that yields more than one analysis-active attempt:

- `replacement_designation` identifies the one allowed replacement as the cell's analysis-active attempt;
- `correction` supplies a corrected projection, reason, evidence, author, and timestamp while preserving the original facts;
- `supersession` points from an earlier record to its authoritative successor; and
- `invalidation` preserves the record and artifacts while naming the affected scope and exclusion reason.

Later verifier defects, contamination, or Scenario Package errors invalidate the affected evidence and normally require a new Suite Version rather than retroactive replacement. Reports resolve the append-only amendment chain into an effective view while still publishing original, replaced, superseded, corrected, and invalidated counts.

### Usage, cost, timing, and resources

Use a small externally measured envelope with an explicit authority hierarchy.

The Credential Proxy is authoritative for provider-request count, timing, status, declared Provider Route, and provider-reported usage. Preserve one redacted raw evidence record per request, including failed requests and Harness-native retries. Normalize only input, output, total, cached-input, and reasoning tokens when the provider reports them, while preserving additional provider-native components in raw evidence. An unreported component is unavailable, never zero or inferred. Harness-native usage is corroborating evidence; preserve discrepancies without averaging or silently selecting a value.

Derive cost from proxy-observed provider usage and an immutable versioned **Pricing Record** that identifies provider and route or model applicability, currency, units, rates, effective interval, source, retrieval time, and content digest. Use exact decimals or integer sub-currency units, never binary floating point. Preserve per-request cost components and derive the Trial total from them. If usage or applicable pricing is unavailable, cost is unavailable with a reason rather than zero. Later invoice totals may be retained as reconciliation evidence but do not rewrite Trial records.

Host monotonic clocks are authoritative for lifecycle timing and Harness latency. The Credential Proxy is authoritative for per-request duration and time to first byte only when it observes them directly. UTC remains correlation metadata. Derive phase and Trial durations from recorded monotonic boundaries.

Record only this common host-resource vector: CPU time, peak memory, peak process count, peak writable storage, storage and block-I/O bytes where exposed by the qualified runtime, enforced limit events, and allowed or denied network and provider-request counts. Runtime, cgroup, and host-side collectors are authoritative; Harbor-native summaries are corroborating evidence; Harness self-reports are diagnostic only.

Every aggregate identifies its source and completeness. Preserve source conflicts as reconciliation findings and never invent a blended value.

### Repository, Submission, verification, and integrity outcomes

Keep four outcome projections orthogonal and assign a distinct trusted authority to each.

The trusted host owns the **Final Repository Capture**: Scenario Baseline tree digest, final normalized repository-tree digest, capture completeness, changed, added and deleted path inventory, normalized host-derived patch digest and reference, and repository-policy violations found during capture. A captured repository with no changes is an explicit no-op, not a missing Submission.

The trusted handoff validator owns the Submission outcome: accepted normalized patch, accepted no-op, accepted declared non-patch artifact, or rejected handoff with its exact reason and safe evidence reference. Never transfer the final workspace wholesale. A rejected handoff remains a valid Harness outcome and follows the Scenario Package's deterministic rejected or no-submission scoring rule.

Use one total capture-to-verification state machine; do not infer disposition from a missing path alone:

| Trusted observed state | Verifier materialization | Disposition authority |
| --- | --- | --- |
| Complete Final Repository Capture with no changed bytes | accepted no-op | verifier-derived valid outcome scored against the unchanged baseline |
| Complete capture with a valid normalized patch | accepted patch only | verifier-derived valid outcome |
| Complete capture but absent/malformed declared Harness-produced non-patch artifact | declared deterministic no-submission/rejected input | `valid_harness_outcome` unless a declared limit caused it |
| Complete capture with an unsafe or policy-rejected handoff | declared deterministic rejected input | `valid_harness_outcome` or `invalid_integrity` only when separate integrity evidence proves tampering/breach |
| Incomplete Final Repository Capture or failed trusted collector/handoff machinery independent of Harness output | no verifier observation | `invalid_infrastructure` |
| Complete accepted Submission but verifier infrastructure fails independently of submitted code | no authoritative score vector | `invalid_infrastructure` |

The Scenario Score Contract specifies deterministic scoring for accepted no-op, missing Harness-produced output, and rejected handoff. Infrastructure-invalid rows never materialize the baseline as a synthetic Harness Submission and never receive task-quality scores.

The project verifier owns the verification outcome: every predeclared Check Group with `pass`, `fail`, `error`, or `not_evaluable`; evidence references for every group; the complete `task_success`, acceptance, regression, and domain-score vector; and verifier execution and completeness status. Derive `task_success` and numeric scores from the named Check Groups and frozen weights. The structured verifier result is authoritative, while Harbor's numeric reward is a required projection that must agree exactly. A projection mismatch or verifier failure independent of submitted code is `invalid_infrastructure`, not a failed Check Group.

External host-side monitoring owns the integrity outcome: every `policy_denial`, `tampering_attempt`, and `boundary_breach`; the targeted boundary, whether the control held, evidence reference, and monitoring completeness; and a derived highest-severity summary. A routine `policy_denial` may coexist with a valid Trial. A tampering attempt, successful breach, or hidden-evidence exposure yields `invalid_integrity`; incomplete mandatory monitoring yields `invalid_infrastructure`, independently of functional quality.

Assign the Trial Attempt disposition only after reconciling these four projections. Preserve available functional scores for diagnostic inspection, but exclude them from comparative quality analysis when integrity or infrastructure invalidates the observation.

### Artifact identity, sealing, absence, and retention

Use one fixed **Artifact Descriptor** for every declared or collected artifact. It records logical role, producing phase, required, optional or outcome-dependent status, media type, sensitivity class, bundle-relative path, byte length, SHA-256 content digest, capture and redaction state, and an optional non-authoritative storage locator. The bundle-relative path and digest are canonical; local paths, workdirs, URLs and bucket keys are resolver hints only.

Inventory every persisted file independently. Compute one deterministic bundle payload digest over the ordered artifact manifest while excluding the seal itself to avoid circular hashing. Use SHA-256 throughout the initial schema without digest-algorithm negotiation. Verify every declared byte length and digest during sealing and read-back.

Represent artifact availability with the closed set `present`, `not_produced`, `collection_failed`, `not_applicable`, `withheld_from_derivative`, `quarantined`, and `removed_by_redaction`. An absent artifact has no placeholder file or fake digest.

Missing mandatory benchmark-collected evidence yields `invalid_infrastructure`. A Harness producing no Submission is an outcome rather than an evidence-collection failure. An absent optional native trajectory or session file is `not_produced` and does not invalidate the Trial. A private artifact omitted from a public derivative remains `present` in the canonical private bundle and is `withheld_from_derivative` only in the derivative manifest.

Retain the append-only Run Ledger and every sealed canonical Result Bundle without automatic expiry for as long as any published benchmark result or claim depends on them. Public and private canonical bundles retain separate access controls. Derived SQL stores, CSVs, caches and reports may be regenerated or deleted. Defer configurable retention tiers until actual storage pressure establishes a use case.

### Secret-safe provenance and redaction

Apply a fixed two-stage secret boundary before any persistent write.

First, structurally omit secrets at their source. Persist only allowlisted environment-variable names, never unrestricted environment dumps. Strip authentication headers, credential-bearing query parameters, URL userinfo, signed locator parameters, and secret-valued configuration fields. Record only each secret's logical name, purpose, scope, injection method, issuing boundary, and whether a disposable credential was exposed to the Harness. Never persist secret values, access-granting provider token identifiers, or reusable hashes of secrets. Storage locators are unsigned stable references. The Credential Proxy records metadata and usage rather than request or response payloads solely for surveillance.

Second, register every injected secret value in memory with a versioned redaction ruleset before launch. Stream-redact exact values from stdout, stderr, native artifacts, errors, proxy metadata, and configuration evidence before persistence, then run a post-capture secret scan before bundle sealing. Record the redaction-ruleset digest, artifacts scanned, per-artifact redaction counts, scan completeness, and pass or fail without preserving matched secret material. Use one neutral replacement marker that does not encode secret identity, and preserve all non-secret bytes verbatim.

If unredacted credential material reaches persistent storage, assign `invalid_infrastructure`, quarantine the bundle, revoke the affected credential, and require investigation before resuming. A quarantined bundle is not canonical evidence.

Private-suite source, hidden checks, and benchmark-private evidence are sensitivity-controlled content rather than credentials. Keep them in secret-free access-controlled canonical bundles. A public or further-redacted export is a separately sealed derivative that references but cannot reveal its canonical private bundle.

### Schema versioning and compatibility

Freeze one strict `v1` Run Ledger schema across all three record families. Every record identifies the schema name, integer version `1`, and SHA-256 digest of the exact published schema and canonicalization contract. Publish one machine-readable schema with canonical serialization rules and conformance examples.

The initial schema has no arbitrary extension maps, producer-defined fields, open-ended top-level statuses, or minor-version compatibility framework. Producers and validators fail closed on unknown fields, missing required fields, unknown enum values, schema-digest mismatch, or an unsupported schema version. Any structural or semantic schema change creates `v2`.

Never rewrite canonical records during migration. A migration produces a separately sealed derived ledger projection that references source record digests, migration-tool identity and digest, source and target schema versions, and a migration report. Factual corrections remain Ledger Amendments rather than schema migrations.

Cross-version reports may combine records only through an explicit versioned compatibility mapping proving that identities, dispositions, score semantics, units, and missingness meanings remain equivalent. Otherwise the records remain in separate Analysis Strata.

Keep ledger-schema version, Suite Version, Scenario Package version, verifier and score version, Pricing Record version, and analysis-manifest version independent. A schema change that alters experimental or scoring meaning also triggers the Suite-versioning consequences owned by [Define suite versioning and refresh policy](https://github.com/MihaiA24/model-benchmarking/issues/23); a representation-only migration does not invent a new experimental observation.

### Authoritative facts and derived values

Classify every field into one of three authority classes.

**Authoritative declarations and observations** are the canonical source facts: frozen experiment, Suite, Matched Block, Planned Trial Cell, randomized-order, repetition, eligibility, control, budget, and analysis-manifest identities; all typed package, Harbor, Harness, adapter, provider, model, Execution Profile, Worker Profile, Qualification Bundle, and Pricing Record identities; lifecycle clock readings; process exits and signals; Credential Proxy requests and provider-reported usage; host resources and limit events; Final Repository Capture and handoff-validation facts; raw Check Group statuses; integrity events and monitoring completeness; Artifact Descriptors and redaction evidence; coordinator-assigned disposition and reason; and Ledger Amendment contents. A provider-reported quantity is authoritative evidence of what the provider reported, not proof of hidden provider internals.

**Canonical derived projections** are stored with their input references and derivation-rule identity: Condition Fingerprint; lifecycle and Harness durations; request and token totals; calculated cost; `task_success`, acceptance, regression, and domain scores; highest integrity severity; analysis eligibility and exclusion reason under the frozen analysis manifest; the analysis-active attempt after replacement and amendment resolution; and the effective corrected record projection. Validators recompute these during sealing. A disagreement with authoritative inputs fails sealing or produces `invalid_infrastructure` as applicable; source facts always win.

**Report-only derivations** never flow back into canonical Trial records: cross-cell denominators and disposition counts; scenario, workload and model aggregates; paired differences and ratios; uncertainty intervals; bootstrap and exact-test results; multiplicity adjustments; probability of improvement; performance profiles; Pareto sets; winner, no-winner and routing conclusions; quality-per-cost summaries; and anonymized presentation labels.

Seal every report as a derivative that records its input ledger and bundle-set digest, analysis-manifest identity and digest, analysis code and environment identity, random seed and resample count or exact-enumeration identity, sealed deterministic generation epoch, and formula or column provenance. Actual publication time is a separate append-only report-registry event outside the reproducible payload digest. A report may filter only according to the frozen analysis manifest and effective amendment chain; it cannot invent eligibility or overwrite canonical outcomes.

## Dependency reconciliation

- [Choose the benchmark substrate](https://github.com/MihaiA24/model-benchmarking/issues/14): preserves Harbor's native task, job and Trial identities and raw files while adding only project-owned planned-cell, exact-condition, and sealing contracts. The Run Ledger does not replace Harbor's lifecycle or verifier.
- [Define the scoring and statistical analysis protocol](https://github.com/MihaiA24/model-benchmarking/issues/16): preserves predeclared Matched Blocks, planned and actual order, repetition, eligibility, replacement lineage, complete score vectors, multi-dimensional operational evidence, analysis-manifest identity, and disposition-aware denominators without storing report aggregates as Trial facts.
- [Define the hermetic execution and integrity model](https://github.com/MihaiA24/model-benchmarking/issues/17): preserves fail-closed phases, worker qualification, monotonic timing, exact limit causes, external integrity evidence, fresh-state and teardown outcomes, secret-safe collection, sidecar exports, dispositions, and restricted replacement lineage. Elapsed time remains observational.
- [Define the harness adapter and launch contract](https://github.com/MihaiA24/model-benchmarking/issues/18): preserves Stock Profile, CLI, adapter and launch-shim identity; exact declared and observed provider/model controls; redacted invocation and process evidence; transparent proxy accounting; and native Harness artifacts as corroborating rather than normalized authority.
- [Define the scenario package and authoring protocol](https://github.com/MihaiA24/model-benchmarking/issues/19): preserves Scenario and package identities, payload and lock digests, Developer Brief and Scenario Baseline identity, resolved `standard-v1` controls, Submission boundary, structured Check Group result, Harbor reward projection, and package-declared artifact requirements.
- [Select the initial scenario portfolio](https://github.com/MihaiA24/model-benchmarking/issues/20): preserves Public and Private Suite separation, the Private Suite Commitment, workload and difficulty declarations, portfolio freeze identity, and non-pooling of the Legacy Calibration Suite.

No accepted dependency is reopened or contradicted. This schema specializes their required evidence joins and explicitly leaves execution, verification, and statistical computation with their established owners.

## Downstream contracts

- [Prototype the generated benchmark report](https://github.com/MihaiA24/model-benchmarking/issues/22) consumes the effective append-only view, exposes raw denominators and dispositions, and keeps every aggregate report-only.
- [Define suite versioning and refresh policy](https://github.com/MihaiA24/model-benchmarking/issues/23) owns Suite bump, rotation, retirement, and cross-Suite compatibility rules while using the immutable identities and invalidation records defined here.
- [Set the benchmark architecture and reuse boundary](https://github.com/MihaiA24/model-benchmarking/issues/24) implements the strict `v1` schemas, canonicalization, validators, Harbor joins, evidence collectors, redaction, sealing, and derived projections without creating a second runner.
- [Set repetition counts and precision targets](https://github.com/MihaiA24/model-benchmarking/issues/26) supplies the frozen repetition and analysis-manifest values recorded by Planned Trial Cells.
- [Validate the blueprint and set the implementation handoff](https://github.com/MihaiA24/model-benchmarking/issues/25) verifies that planned cells, effective attempts, bundles, analysis eligibility, and report inputs join without missing or contradictory authority.

## Decision completeness

All required Run Ledger and provenance decisions are accepted and reconciled. No investigation was delegated, and no evidence remains outstanding. This record is the complete decision contract; implementation remains with the named downstream tickets.

# Validate the blueprint and set the implementation handoff

**Status:** Final decision
**Decision date:** 2026-07-13
**Map:** [Design a real-world CLI benchmark for coding-agent harnesses](https://github.com/MihaiA24/model-benchmarking/issues/13)
**Ticket:** [Validate the blueprint and set the implementation handoff](https://github.com/MihaiA24/model-benchmarking/issues/25)

## Validation scope

This final gate checks the integrated blueprint as one contract. It does not implement or operate the benchmark and does not reopen accepted product choices merely because implementation is substantial.

The review covers:

- the pinned Harbor substrate and legacy-scenario inventory;
- hermetic execution, Stock Profile launch, and Scenario Package boundaries;
- the 24-Scenario portfolio and Public/Private disclosure split;
- the append-only Run Ledger, Suite Releases, compatibility, and report derivatives;
- randomized Matched Blocks, fixed-suite estimands, repetition selection, precision, completeness, and spend qualification; and
- the four-module architecture, canonical handoffs, proof gates, operator interface, and implementation order.

## Confirmed integrated invariants

The accepted records agree on these validity-critical boundaries:

- Harbor v0.18.0 at commit `527d50deb63a5d279e8c20593c18a2cbc7f61f9e` owns the task, isolated Trial, separate-verifier, teardown, and native evidence lifecycle; project code does not fork or duplicate it.
- OMP, OpenCode, and Hermes remain pinned Stock Profiles behind three small supported Adapters. The common comparison varies the Harness while holding the effective provider/model, Scenario, worker, instruction, verifier, and limits fixed.
- Every measured Trial starts from immutable provisioned inputs and fresh writable state, uses proxy-only provider access, stops the complete Harness process tree before trusted Submission capture, and verifies only a declared safe handoff in a fresh verifier environment.
- Public and Private Suite evidence remains disjoint at package, release, Trial, bundle, analysis, and report boundaries. The Legacy Calibration Suite is diagnostic and never pooled into production claims.
- Planned Trial Cells, terminal Trial Attempt Records, and Ledger Amendments form the strict append-only evidence spine. Typed identities remain authoritative; digests and effective views are recomputable projections.
- The primary endpoint is strict `task_success`. Analysis uses randomized Matched Blocks, equal Scenario weight within each fixed workload, paired uncertainty, explicit dispositions and denominators, multiplicity-aware claim states, and neutral no-winner semantics.
- Production repetitions are selected before production from the separate three-block pilot by 50,000 paired simulations over candidates `{4, 6, 8, 10, 12}`. The ±20-point/80%-assurance precision gate, 95th-percentile production-spend gate, `r−1`/90% completeness gate, and no-top-up rule fail closed.
- Sealed Suite Releases, Production Experiment Manifests, Result Bundles, Run Ledger records, analysis projections, and static report derivatives remain independently identifiable and append-only. Compatibility or invalidation never silently pools or rewrites evidence.

## Invariant traceability matrix

The matrix below is the implementation handoff contract. An issue may split an invariant into smaller tests, but it may not change the named authority, move policy into another module, weaken the acceptance criterion, substitute a prose-only review for the executable gate, or improvise a different failure treatment.

| Validity invariant | Authoritative decision | Owning module | Observable acceptance criterion | Executable proof gate | Failure disposition |
| --- | --- | --- | --- | --- | --- |
| Pinned substrate and supported extension seams | [Choose the benchmark substrate](../research/benchmark-substrate.md); [Benchmark architecture and reuse boundary](benchmark-architecture-and-reuse-boundary.md) | `runtime` | Harbor resolves to v0.18.0 commit `527d50d`; project code uses only qualified public Adapter, task, job, environment, verifier, and artifact seams and contains no fork, monkeypatch, or Harbor-internal lifecycle import | [#27](https://github.com/MihaiA24/model-benchmarking/issues/27): `uv run --project proofs/harbor-submission-capture --frozen pytest -q proofs/harbor-submission-capture/tests`; [#36](https://github.com/MihaiA24/model-benchmarking/issues/36): `uv run --frozen pytest -q tests/acceptance/issue_36 --run-live --require-docker` | Stop all dependent implementation. Reopen only the bounded substrate fallback; do not weaken the trust boundary or create a second lifecycle |
| One comparable Harness condition through pinned Stock Profiles | [Harness adapter and launch contract](harness-adapter-and-launch-contract.md); [Benchmark architecture and reuse boundary](benchmark-architecture-and-reuse-boundary.md) | `runtime` | OMP, OpenCode, and Hermes each qualify from fresh state through the same proxy-only provider/model condition, exact Developer Brief bytes, limits, worker controls, and external evidence, with no undeclared normalization | [#32](https://github.com/MihaiA24/model-benchmarking/issues/32)–[#35](https://github.com/MihaiA24/model-benchmarking/issues/35): `uv run --frozen pytest -q tests/acceptance/issue_32 tests/acceptance/issue_33 tests/acceptance/issue_34 tests/acceptance/issue_35 --run-live --require-docker` | Mark the exact condition unsupported or unqualified, preserve Structural Missingness, and start no measured cell for it until a new Qualification Bundle passes |
| Fresh hermetic Trial and trusted post-stop Submission | [Hermetic execution and integrity](hermetic-execution-and-integrity.md); [Scenario Package and authoring protocol](scenario-package-and-authoring-protocol.md); [Benchmark architecture and reuse boundary](benchmark-architecture-and-reuse-boundary.md) | `runtime` → `evidence` | Every Trial uses immutable provisioned inputs and fresh writable state; the complete Harness tree stops before trusted capture; only a validated Submission or no-op reaches a fresh Verifier; hidden assets, secrets, caches, and whole workspaces never cross | [#27](https://github.com/MihaiA24/model-benchmarking/issues/27), [#36](https://github.com/MihaiA24/model-benchmarking/issues/36), and [#37](https://github.com/MihaiA24/model-benchmarking/issues/37): `uv run --frozen pytest -q tests/acceptance/issue_36 tests/acceptance/issue_37 --run-live --require-docker` after the standalone #27 proof | Trusted-capture proof failure reopens the substrate seam. Trial-time capture, isolation, or independent-verifier failure yields `invalid_infrastructure`, quarantine, and only policy-permitted replacement lineage—never a score |
| Public, Private, and Calibration evidence separation | [Initial Scenario portfolio](initial-scenario-portfolio.md); [Suite versioning and refresh policy](suite-versioning-and-refresh-policy.md) | `declarations` → `evidence` → `analysis` | Package, release, cache, Trial, bundle, analysis, and report identities remain visibility-scoped; Calibration never enters production claims; releasable outputs contain no Private identity or bytes | [#30](https://github.com/MihaiA24/model-benchmarking/issues/30), [#39](https://github.com/MihaiA24/model-benchmarking/issues/39), [#40](https://github.com/MihaiA24/model-benchmarking/issues/40), and [#47](https://github.com/MihaiA24/model-benchmarking/issues/47): `uv run --frozen pytest -q tests/acceptance/issue_30 tests/acceptance/issue_39 tests/acceptance/issue_40 tests/acceptance/issue_47 --run-live --require-docker` | Reject the seal or derivative and quarantine leaked output. Pause affected use/publication; invalidate and rotate compromised Private cells under the accepted lifecycle; never pool strata |
| Typed immutable identities and append-only evidence spine | [Run Ledger and provenance schema](run-ledger-and-provenance-schema.md); [Suite versioning and refresh policy](suite-versioning-and-refresh-policy.md) | `declarations` → `evidence` | Independent Scenario, Verifier, Score Contract, Suite, experiment, cell, attempt, bundle, and artifact identities round-trip canonically; every effective change is a valid Ledger Amendment; derived projections are reproducible | [#28](https://github.com/MihaiA24/model-benchmarking/issues/28), [#30](https://github.com/MihaiA24/model-benchmarking/issues/30), [#31](https://github.com/MihaiA24/model-benchmarking/issues/31), and [#37](https://github.com/MihaiA24/model-benchmarking/issues/37): `uv run --frozen pytest -q tests/acceptance/issue_28 tests/acceptance/issue_30 tests/acceptance/issue_31 tests/acceptance/issue_37` | Reject schema load, append, seal, or read-back; preserve original bytes; record only a valid append-only correction, supersession, invalidation, or replacement designation |
| Disposition-aware paired fixed-suite inference | [Scoring and statistical analysis protocol](../research/scoring-and-statistical-analysis-protocol.md); [Generated benchmark report](generated-benchmark-report.md) | `analysis` | Strict `task_success` and secondary dimensions join complete randomized Matched Blocks at equal Scenario weight within exact strata; intervals, practical margins, multiplicity, denominators, and claim precedence reproduce golden vectors; no universal winner can be manufactured | [#39](https://github.com/MihaiA24/model-benchmarking/issues/39): `uv run --frozen pytest -q tests/acceptance/issue_39` | Emit `unsupported` for absent common support or incompatible evidence and `inconclusive` when uncertainty/claims do not qualify; fail report sealing on semantic or provenance mismatch |
| Fixed pre-production repetition, completeness, and spend qualification | [Repetition counts and precision targets](repetition-counts-and-precision-targets.md); [Benchmark architecture and reuse boundary](benchmark-architecture-and-reuse-boundary.md) | `analysis` → `declarations` and `runtime` | The three-block pilot, 50,000 deterministic simulations, candidates `4/6/8/10/12`, Suite-stratified sharing, ±20-point/80% precision, 95th-percentile spend, `r−1`/90% completeness, and no-top-up rules reproduce exactly before experiment sealing | [#38](https://github.com/MihaiA24/model-benchmarking/issues/38): `uv run --frozen pytest -q tests/acceptance/issue_38`; campaign enforcement in [#36](https://github.com/MihaiA24/model-benchmarking/issues/36): `uv run --frozen pytest -q tests/acceptance/issue_36 --run-live --require-docker` | Seal no Production Design Selection or Production Experiment Manifest and start no affected measured Trial; reduce the pre-production roster or explicitly reopen the bounded design policy rather than top up outcomes |
| Independently sealed declarations, evidence, analysis, and reports | [Suite versioning and refresh policy](suite-versioning-and-refresh-policy.md); [Run Ledger and provenance schema](run-ledger-and-provenance-schema.md); [Generated benchmark report](generated-benchmark-report.md) | `declarations` → `evidence` → `analysis` | Suite Releases, Production Manifest, Result Bundles, effective ledger, `analysis-result.json`, and internal/releasable static sites verify by canonical bytes and digest; incompatible or invalidated inputs fail closed; publication time does not alter generated bytes | [#47](https://github.com/MihaiA24/model-benchmarking/issues/47): `uv run --frozen pytest -q tests/acceptance/issue_47 --require-docker` after all predecessor gates | Reject or quarantine the affected release, bundle, projection, or derivative and publish no claim; supersede only through the accepted append-only lifecycle |

## Cross-contract audit closure

Three independent audits checked identity/scenario/suite/ledger, execution/integrity/architecture, and statistics/repetition/reporting contracts. They confirmed the core design and exposed the following implementation-blocking seams. This ticket resolves each in the named authoritative contract rather than leaving it to implementation convention:

| Finding | Final closure | Owning implementation slice |
| --- | --- | --- |
| Scenario, Verifier, and Score Contract identities were not propagated uniformly | All three independent identities now appear in package, lock, Suite, cell, attempt, bundle, stratum, and compatibility contracts | canonical foundation; Scenario tooling; Suite declarations; ledger |
| Portfolio targets/slots could be mistaken for released Scenarios | Closed `authoring_target/private_slot → candidate → package_qualified → roster_selected → suite_sealed` flow with durable rejection/replacement evidence | Scenario tooling; six portfolio slices; final sealing |
| Suite package qualification and experiment condition qualification were conflated | Suite-owned Package Qualification Records and experiment-owned Qualification Bundles are distinct and may only cross-reference | Scenario tooling; Suite declarations; runtime |
| Private commitment graph could be circular | Canonical Private Roster Manifest → commitment → outer Private Suite Release hash order | Suite declarations; final sealing |
| Submission/no-submission and collector failure lacked one total state machine | Complete no-op/missing/rejected Harness output remains scoreable; incomplete trusted capture or independent verifier failure is infrastructure-invalid | trusted-capture proof; evidence sealing; ledger |
| Ledger Amendment enum omitted replacement designation | Closed four-operation enum with cycle, cardinality, and one-active-attempt rules | ledger |
| Suite-owned and experiment-owned analysis fields could mirror each other | Explicit authority matrix rejects duplicate authority and incompatible references | Suite declarations; sizing; analysis/report |
| Stock Harbor did not expose an obvious trusted pre-verifier Submission transformation | Mandatory real-Docker post-stop capture-sidecar proof, with fail-closed substrate reopen | issue 1; runtime/evidence |
| Wall-clock prohibition, operator abort, and worker eligibility lacked executable proof | Long-running no-deadline fixture, authenticated abort protocol, Worker Qualification Record, and unavoidable `development_only` exclusion | runtime; Calibration qualification |
| Image/cache production and privacy boundaries lacked an owner | `experiment provision` emits a sealed Provisioning Manifest; preflight is read-only and cache roots are visibility-separated | runtime |
| Pilot sizing and spend qualification lacked an owner and command | `analysis` owns `experiment qualify-design` and the sealed Production Design Selection required by `experiment seal` | sizing |
| Campaign spend could not be enforced by isolated per-Trial proxies alone | Sequential coordinator derives sealed cumulative spend before each launch and passes the lesser cell/remaining ceiling to the proxy | runtime; sizing |
| Statistical interval and RNG behavior were not executable and implied a nested 2.5-billion-resample loop | Exact conditional paired stratified-bootstrap enumeration for primary binary effects; 50,000 deterministic outer simulations; explicit quantiles, boundaries, McNemar, and counter-based SHA-256 sampling | sizing; analysis/report |
| Report claim precedence, drill-down, and generation time conflicted | `unsupported` precedes strongest/no-winner; Planned Trial Cell restored; v1 operational routing disabled; deterministic generation epoch separated from publication time | analysis/report |
| Historical direct-model instructions conflicted with the accepted handoff | Historical banners now route implementers to `CONTEXT.md` and the accepted blueprint | final validation ticket |

No unresolved product or statistical decision remains inside the blueprint. Implementation proof obligations still fail closed, most importantly the trusted capture-sidecar seam; failing a proof gate reopens only its named bounded decision rather than weakening the contract.

## Validity-critical implementation risk

**Accepted treatment:** make the trusted post-stop capture-sidecar proof the first implementation gate. If the supported seam fails, stop implementation and reopen the bounded substrate fallback review. Do not weaken the Submission boundary.

### Trusted Submission interposition in pinned Harbor

The accepted contract requires the complete Harness process tree to stop before a trusted collector derives and validates the normalized patch, and requires only that validated Submission to enter the verifier environment. Pinned Harbor's stock single-step lifecycle collects declared artifacts, stops the agent environment, and then starts the separate verifier ([`single_step.py` lines 37–55](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/trial/single_step.py#L37-L55)). Its separate-verifier path re-materializes the already collected artifacts directly before verification ([`trial.py` lines 531–599](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/trial/trial.py#L531-L599)); the standard artifact handler performs no transformation between collection and upload ([`artifact_handler.py` lines 23–42](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/trial/artifact_handler.py#L23-L42)).

Pinned Harbor does provide one potentially compatible seam: in separate-verifier mode, it can stop the main service before running sidecar collect hooks and collecting sidecar artifacts ([`trial.py` lines 918–979](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/trial/trial.py#L918-L979)). The recommended implementation therefore begins with a real-Docker proof that a trusted, immutable capture sidecar can observe a fresh Trial-local repository volume only after the main Harness service stops, derive and validate the normalized Submission, and expose only that Submission to Harbor's separate verifier. The sidecar must not expose verifier assets, remain writable by the Harness, or become a second lifecycle.

If this proof fails, implementation stops and reopens the already bounded substrate fallback review. It must not transfer the whole final workspace, trust a Harness-generated patch, import Harbor internals, monkeypatch Harbor, or continue on an invalid architecture.

## Documentation handoff

`README.md`, `CLAUDE.md`, and `CONTEXT_PROMPT.md` describe the historical direct-model PoC. They remain useful for reproducing that evidence, but implementation must not mistake them for the accepted autonomous-CLI/Harbor architecture. Each now carries an explicit historical banner and points implementers to `CONTEXT.md`, this handoff, and the accepted `blueprint/` contracts. The per-stack direct-API runners and local baselines remain historical source material rather than an implementation seam.

## Acceptance gates

**Accepted handoff destination:** implementation ends with a qualified evaluator and sealed first Public, Private, and Calibration Suite Releases. Pilot and production execution require separate authorization and are not part of this implementation backlog.

The blueprint is ready to leave Wayfinder only when the implementation backlog and its final qualification issue require all of the following:

1. **Contract consistency:** machine checks cover local links, live issue title/link identity, fixed Harbor identity, public/private separation, portfolio cardinality, Matched Block semantics, repetition policy, closed enums, authority boundaries, and no-winner claim rules.
2. **Validity seam first:** the post-stop trusted Submission-capture proof passes against pinned Harbor and Docker before broad runtime implementation.
3. **Declaration closure:** strict schemas, canonical serialization, digest golden vectors, non-circular locks and seals, `standard-v1` expansion, Suite and experiment identities, and fail-closed unknown-field behavior are executable.
4. **Runtime closure:** all three Stock Profiles qualify against one effective provider/model condition; measured execution downloads nothing; every Trial is one single-cell Harbor job; policy, limits, process-tree stop, and proxy evidence are proven externally.
5. **Evidence closure:** repository capture, handoff validation, verifier projection, disposition reconciliation, redaction, bundle sealing, ledger append, replacement lineage, Amendment resolution, read-back verification, and quarantine paths pass fault injection.
6. **Analysis closure:** deterministic pilot sizing reproduces every accepted candidate, sharing, precision, assurance, completeness, spend, and no-top-up rule; production analysis preserves paired blocks, exact strata, effective denominators, practical margins, multiplicity, and unsupported/inconclusive distinctions.
7. **Disclosure closure:** internal and releasable report derivatives are built independently, use neutral ordering and no-winner semantics, retain typed drill-down, fail closed on incompatibility or invalidation, and contain no Private identities or bytes when public.
8. **Cross-ecosystem closure:** one qualified Legacy Calibration Scenario per ecosystem runs through every Harness and the complete Trial-to-report evidence join before measured portfolio authoring is accepted.
9. **Portfolio closure:** all 12 Public and 12 access-controlled Private Scenario Packages pass the common authoring, independent-review, provenance, leakage, solvability, and repeatability gates before Suite sealing.
10. **No operation by implication:** qualification proves readiness; pilot and production operation remain separately authorized work using sealed inputs and budget approval.

## Published implementation frontier

The 21 implementation issues live outside the Wayfinder hierarchy. Each is open with exactly the `enhancement` category and `ready-for-agent` readiness labels, title-wrapped parent/evidence/blocker links, and matching native `blocked by` edges. This linked graph is the sequencing source of truth.

**Accepted granularity:** create 21 focused, independently claimable implementation issues. Keep the three Harness Adapters and the six Suite-visibility × ecosystem authoring slices separate so they can proceed in parallel after their shared gates.

**Accepted dependency policy:** the trusted Submission proof is a hard gate. After the canonical foundation, declaration, ledger, and proxy lanes may proceed in parallel; the three Harness Adapters may then qualify in parallel. Measured-portfolio authoring waits for full Legacy Calibration qualification so the project does not build 24 expensive packages on an unproven path. Pilot and production execution are absent from this graph.

Priorities use `P0` for the validity gate that can reopen the substrate, `P1` for the evaluator's critical path and final readiness gate, and `P2` for the six parallel measured-portfolio authoring slices. Every issue is an implementation issue labelled `enhancement` and `ready-for-agent`, not a Wayfinder child.

### Wave 0 — retire the validity risk

- **P0, unblocked:** [#27 Prove trusted post-stop Submission capture with pinned Harbor](https://github.com/MihaiA24/model-benchmarking/issues/27).

### Wave 1 — establish the canonical foundation

- **P1, blocked by #27:** [#28 Establish the Python project, canonical serialization, and strict schema foundation](https://github.com/MihaiA24/model-benchmarking/issues/28).

### Wave 2 — build four parallel contract lanes

- **P1, blocked by #28:** [#29 Implement Scenario Package and `standard-v1` authoring tooling](https://github.com/MihaiA24/model-benchmarking/issues/29).
- **P1, blocked by #28:** [#30 Implement Suite and experiment declaration lifecycles](https://github.com/MihaiA24/model-benchmarking/issues/30).
- **P1, blocked by #28:** [#31 Implement the append-only Run Ledger and effective record projection](https://github.com/MihaiA24/model-benchmarking/issues/31).
- **P1, blocked by #28:** [#32 Implement the transparent Credential Proxy and common Adapter runtime](https://github.com/MihaiA24/model-benchmarking/issues/32).

### Wave 3 — qualify adapters and production design in parallel

- **P1, blocked by #32:** [#33 Qualify the OMP Stock Profile Adapter](https://github.com/MihaiA24/model-benchmarking/issues/33).
- **P1, blocked by #32:** [#34 Qualify the OpenCode Stock Profile Adapter](https://github.com/MihaiA24/model-benchmarking/issues/34).
- **P1, blocked by #32:** [#35 Qualify the Hermes Stock Profile Adapter](https://github.com/MihaiA24/model-benchmarking/issues/35).
- **P1, blocked by #30 and #31:** [#38 Implement repetition selection and aggregate-spend qualification](https://github.com/MihaiA24/model-benchmarking/issues/38).

### Wave 4 — implement the measured Trial runtime

- **P1, blocked by #29–#35:** [#36 Implement single-cell Harbor execution, preflight, scheduling, and monitoring](https://github.com/MihaiA24/model-benchmarking/issues/36).

### Wave 5 — seal canonical Trial evidence

- **P1, blocked by #27, #31, and #36:** [#37 Implement trusted repository capture, Submission validation, and Result Bundle sealing](https://github.com/MihaiA24/model-benchmarking/issues/37).

### Wave 6 — build decision evidence and reports

- **P1, blocked by #30, #31, #37, and #38:** [#39 Implement disposition-aware paired analysis and sealed static reports](https://github.com/MihaiA24/model-benchmarking/issues/39).

### Wave 7 — qualify the complete production interface

- **P1, blocked by #29 and #33–#39 as wired:** [#40 Qualify the Legacy Calibration Suite end to end](https://github.com/MihaiA24/model-benchmarking/issues/40).

### Wave 8 — author the measured portfolio in parallel

- **P2, blocked by #40:** [#41 Author and qualify the Public Angular/TypeScript Scenario slice](https://github.com/MihaiA24/model-benchmarking/issues/41).
- **P2, blocked by #40:** [#42 Author and qualify the Public Spring Boot/Java Scenario slice](https://github.com/MihaiA24/model-benchmarking/issues/42).
- **P2, blocked by #40:** [#43 Author and qualify the Public Python data-engineering Scenario slice](https://github.com/MihaiA24/model-benchmarking/issues/43).
- **P2, blocked by #40:** [#44 Author and qualify the access-controlled Private Angular/TypeScript Scenario slice](https://github.com/MihaiA24/model-benchmarking/issues/44).
- **P2, blocked by #40:** [#45 Author and qualify the access-controlled Private Spring Boot/Java Scenario slice](https://github.com/MihaiA24/model-benchmarking/issues/45).
- **P2, blocked by #40:** [#46 Author and qualify the access-controlled Private Python data-engineering Scenario slice](https://github.com/MihaiA24/model-benchmarking/issues/46).

### Wave 9 — seal implementation readiness

- **P1, blocked by #30, #38–#40, and #41–#46:** [#47 Seal the initial Suite Releases and validate implementation readiness](https://github.com/MihaiA24/model-benchmarking/issues/47).

## Deduplication and ownership decisions

- Keep canonical serialization/schema foundation separate because every module imports it and its golden vectors can land before domain declarations.
- Combine Suite and experiment declaration lifecycles in one `declarations` slice because their transitive seals, compatibility gates, Qualification Bundles, analysis manifests, and Planned Trial Cells share one immutable authority boundary.
- Keep Run Ledger and Result Bundle work separate: the ledger owns immutable structured facts and effective lineage; the evidence slice owns repository capture, redaction, handoff validation, bytes, sealing, and quarantine.
- Keep the common Credential Proxy/Adapter runtime separate from OMP, OpenCode, and Hermes qualification. The proxy is one auditable control boundary; each Stock Profile can fail independently without rewriting it.
- Combine paired analysis and static reporting because the renderer consumes only the sealed analytical projection and cannot make an independent semantic decision. Preserve the analytical projection as the independently testable intermediate artifact inside that issue.
- Split Public and Private authoring by ecosystem. Each four-Scenario slice is independently reviewable and resumable; Private issues expose only slot contracts and status, never held-out package details.
- Keep Suite sealing and final readiness separate from package authoring so no partial portfolio or unqualified interface can be mistaken for a release.

## Human and access boundaries

- A human must provide or authorize the dedicated worker, provider credentials, exact model roster, Private source root, access-control policy, independent Scenario reviewers, and final pilot budget. Implementation must not fabricate or persist any of these.
- Private Scenario selection, authoring detail, review evidence, and package bytes occur only in the access-controlled source and artifact roots. Public issues contain non-disclosing slot contracts and completion evidence only.
- The first trusted Submission proof and every real Harness qualification may need operator provisioning, but their pass/fail evidence is objective and must use the production interfaces.
- Independent Scenario review is a human gate owned by a benchmark-owner-designated reviewer who is independent of that Scenario's author and implementation. The sealed `scenario-review.json` records the reviewer identity/attestation, exact package identities, checklist version, signed approve/reject decision, per-axis reasons, and timestamp. Missing, conflicted, unavailable, unsigned, or rejected review blocks qualification; the implementation cannot approve professional realism, implementation neutrality, licensing, or undisclosed-answer risk on the reviewer's behalf.
- `blocked` means an implementation issue is specified but not claimable because a native dependency or declared human/access prerequisite is open. `ready-for-agent` means every native blocker is closed and the issue's non-secret prerequisite attestation is present. The closing workflow for each issue must recompute downstream readiness and change exactly one readiness label; labels never override native dependencies.
- Live Harness qualification requires a benchmark-owner-authorized dedicated worker, exact pinned Harness artifact, Provider Route and model roster, scoped proxy-held credentials, and applicable budget. The issue remains `blocked` when any prerequisite is absent; unavailable access is a visible blocked state, not permission to inject direct credentials, use a personal machine for claim-bearing evidence, skip a mandatory case, or fabricate a Qualification Bundle.
- Final Suite sealing verifies current-head identities and the sealed live Qualification Bundles produced by predecessor issues. It does not repeat model-calling qualification or invoke pilot/production Trials; an implementation-identity mismatch blocks sealing and returns the affected predecessor to qualification.
- Pilot and production execution require a later explicit authorization after sealed Suite Releases, model roster, immutable Pricing Records, worker qualification, credentials, and budget are available.

## Explicitly excluded implementation

- No direct-model-API runner migration, per-stack lifecycle, or pooling of historical pilot evidence.
- No Harbor fork, monkeypatch, internal lifecycle import, second verifier, or whole-workspace handoff.
- No distributed queue, worker pool, outcome-driven scheduler, hosted control plane, REST API, TUI, live dashboard, or JavaScript report application.
- No generic Harness plugin system, generalized command-template language, protocol-translating model gateway, profile inheritance, arbitrary extension map, digest negotiation, or storage-provider abstraction.
- No confidential company source or data, unresolved external datasets, subjective trace scoring, universal weighted winner, or pilot/production campaign operation.

## Completion state

The handoff destination, 21-issue granularity, and dependency policy are accepted. All three dispatched audits are accounted for. Issues #27–#47 were fetched individually and verified open with the required sections, parent/evidence links, labels, title-wrapped blocker links, and 48 matching native dependency edges. The recommended starting frontier is issue #27 only; no downstream issue should be claimed before its blockers close. Pilot and production execution remain outside this implementation backlog.

# Validate the blueprint and set the implementation handoff

**Status:** Working decision record — not yet accepted
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

## Draft implementation frontier

The implementation issues will live outside the Wayfinder hierarchy. They will be linked here by verified title and URL after human acceptance and creation.

**Accepted granularity:** create 21 focused, independently claimable implementation issues. Keep the three Harness Adapters and the six Suite-visibility × ecosystem authoring slices separate so they can proceed in parallel after their shared gates.

**Accepted dependency policy:** the trusted Submission proof is a hard gate. After the canonical foundation, declaration, ledger, and proxy lanes may proceed in parallel; the three Harness Adapters may then qualify in parallel. Measured-portfolio authoring waits for full Legacy Calibration qualification so the project does not build 24 expensive packages on an unproven path. Pilot and production execution are absent from this graph.

Priorities use `P0` for the validity gate that can reopen the substrate, `P1` for the evaluator's critical path and final readiness gate, and `P2` for the six parallel measured-portfolio authoring slices. Every issue is an implementation issue labelled `enhancement` and `ready-for-agent`, not a Wayfinder child.

### Wave 0 — retire the validity risk

- Prove trusted post-stop Submission capture with pinned Harbor.

### Wave 1 — establish immutable contracts

- Establish the Python project, canonical serialization, and strict schema foundation.
- Implement Scenario Package and `standard-v1` authoring tooling.
- Implement Suite and experiment declaration lifecycles.
- Implement the append-only Run Ledger and effective record projection.

### Wave 2 — build the measured Trial path

- Implement the transparent Credential Proxy and common Adapter runtime.
- Qualify the OMP Stock Profile Adapter.
- Qualify the OpenCode Stock Profile Adapter.
- Qualify the Hermes Stock Profile Adapter.
- Implement single-cell Harbor execution, preflight, scheduling, and monitoring.
- Implement trusted repository capture, Submission validation, and Result Bundle sealing.

### Wave 3 — build decision evidence

- Implement repetition selection and aggregate-spend qualification.
- Implement disposition-aware paired analysis and sealed static reports.

### Wave 4 — qualify the production interfaces

- Qualify the Legacy Calibration Suite end to end.

### Wave 5 — author the measured portfolio in parallel

- Author and qualify the Public Angular/TypeScript Scenario slice.
- Author and qualify the Public Spring Boot/Java Scenario slice.
- Author and qualify the Public Python data-engineering Scenario slice.
- Author and qualify the access-controlled Private Angular/TypeScript Scenario slice.
- Author and qualify the access-controlled Private Spring Boot/Java Scenario slice.
- Author and qualify the access-controlled Private Python data-engineering Scenario slice.

### Wave 6 — seal implementation readiness

- Seal the initial Suite Releases and validate implementation readiness.

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
- Independent Scenario review is a human gate. The implementation may generate checklists and evidence but cannot approve professional realism, implementation neutrality, licensing, or undisclosed-answer risk on the reviewer's behalf.
- Pilot and production execution require a later explicit authorization after sealed Suite Releases, model roster, immutable Pricing Records, worker qualification, credentials, and budget are available.

## Explicitly excluded implementation

- No direct-model-API runner migration, per-stack lifecycle, or pooling of historical pilot evidence.
- No Harbor fork, monkeypatch, internal lifecycle import, second verifier, or whole-workspace handoff.
- No distributed queue, worker pool, outcome-driven scheduler, hosted control plane, REST API, TUI, live dashboard, or JavaScript report application.
- No generic Harness plugin system, generalized command-template language, protocol-translating model gateway, profile inheritance, arbitrary extension map, digest negotiation, or storage-provider abstraction.
- No confidential company source or data, unresolved external datasets, subjective trace scoring, universal weighted winner, or pilot/production campaign operation.

## Decisions pending

The handoff destination, 21-issue granularity, and dependency policy are accepted. This record remains working and the Wayfinder ticket remains open until every dispatched audit is accounted for, each implementation issue and dependency is published, and the tracker graph is verified.

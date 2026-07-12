# Set the benchmark architecture and reuse boundary

**Status:** Final decision
**Map:** [Design a real-world CLI benchmark for coding-agent harnesses](https://github.com/MihaiA24/model-benchmarking/issues/13)
**Ticket:** [Set the benchmark architecture and reuse boundary](https://github.com/MihaiA24/model-benchmarking/issues/24)

## Accepted decisions

### Harbor integration seam

Adopt pinned Harbor v0.18.0 at commit `527d50deb63a5d279e8c20593c18a2cbc7f61f9e` unchanged. Treat Harbor's documented CLI, job and task configuration, lock files, result files, and artifact layout as the experiment coordinator's external execution seam.

The coordinator generates a single-cell Harbor job configuration for one predeclared Planned Trial Cell, invokes Harbor as a child process, and validates Harbor's native lock, Trial result, verifier output, and artifact manifest after execution. It does not import Harbor's internal `Job`, `Trial`, queue, lifecycle, or result-aggregation implementations.

Extend Harbor only through its supported custom installed-agent import-path interface. Project-owned OMP, OpenCode, and Hermes adapters implement the pinned `BaseInstalledAgent` contract and remain limited to the already accepted launch responsibilities. This is the only required Python-level coupling to Harbor.

Do not fork, patch, monkeypatch, vendor modified Harbor source, or build a parallel task, Trial, verifier, retry, teardown, or artifact lifecycle. If a validity-critical requirement cannot be satisfied through pinned configuration or a small upstream-compatible supported extension, fail the applicable qualification gate and trigger the accepted substrate fallback review rather than hiding the gap in coordinator code.

Harbor's built-in Hermes, OpenCode, and Pi adapters are pinned reference implementations and evidence sources, not the production benchmark adapters. At the selected revision they perform installation during agent setup and assume direct provider credential routing; those behaviors conflict with the accepted prebuilt-image, no-download, and Credential Proxy contracts. Reuse documented invocation and native-output knowledge only after independently expressing and qualifying it through the project-owned declarative adapter contract.

### Immutable image composition and reuse

Compose each agent environment from two independently content-addressed immutable inputs instead of building a Scenario-by-Harness image matrix:

1. One Scenario runtime image contains the exact Scenario Baseline and its pinned ecosystem toolchain and dependencies. Its digest is identical across every Harness condition for that Scenario.
2. One Harness artifact image contains exactly one pinned Stock Profile's CLI artifact and immutable launch inputs. The coordinator selects that image by digest for the Planned Trial Cell and mounts it read-only at one fixed path through Harbor's supported job-level image-mount configuration.

The project-owned Adapter verifies the selected mounted artifact and executes it in place. It performs no package installation, self-update, registry access, or external download. Do not place all three Harness artifacts in the Scenario runtime image: only the selected Harness artifact is visible inside a Trial. Do not bake credentials or generated per-Trial Stock Profile configuration into either image.

The Planned Trial Cell, Production Experiment Manifest, Harbor job lock, Qualification Bundle, and Result Bundle preserve both image identities and their composition. Preflight requires both digests to exist in the host-controlled Provisioning Cache and fails before measured execution rather than pulling or rebuilding them.

Reuse stops at immutable image bytes and content-addressed host cache entries. Every Trial still receives a fresh writable container layer, evaluated-repository materialization, home, scratch and cache paths, volumes, network, sidecars, and generated Harness configuration. No writable state crosses Trial boundaries.

Use a distinct digest-pinned verifier image owned by each Scenario Package. It contains the hidden checks and verifier-only dependencies and is never mounted into the agent environment. Qualification must prove that the selected Harbor and Docker worker profile supports the read-only image mount and keeps unselected Harness artifacts absent. Failure of that capability is a failed runtime qualification, not permission to expose all Harnesses or install during a measured Trial.

### `standard-v1` representation and expansion

Represent the initial Execution Profile in one canonical project-owned `profiles/standard-v1.yaml`. Do not introduce profile inheritance, layered profiles, arbitrary override maps, or Harness-specific profile variants.

Every profile field has one of two explicit ownership classes:

- **Scenario-static Harbor controls** include the unprivileged user, separate-verifier requirement, baseline network policy, standard resource vector, and writable-storage limits. The Scenario scaffolder writes their Harbor-native values into `task.toml`; package validation requires exact agreement with the pinned profile. The profile does not replace or become a second executable task schema.
- **Experiment and worker controls** include the selected Harness artifact mount, Credential Proxy route, Docker enforcement policy, single-Trial worker concurrency, host-side evidence collectors, output roots, and provider ceilings. The coordinator writes them directly into the single-cell Harbor job configuration; they do not enter the Scenario Package.

For each Planned Trial Cell, derive one canonical `ResolvedExecutionProfile` projection containing the `standard-v1` identity and digest, Scenario Package profile reference, every resolved static and runtime value, any approved exception and its separate Analysis Stratum, and the resulting Harbor task and job configuration digests. Store this projection with its authoritative input references in the Production Experiment Manifest and Run Ledger evidence. It is recomputable validation evidence and never outranks those inputs.

A Scenario may declare only a typed, explicitly approved exception through the Scenario Package's existing profile-exception boundary. Validation rejects undeclared drift, silent defaults, weaker controls, and per-Harness exceptions. An accepted exception creates a separately labelled comparison stratum rather than changing `standard-v1` or weakening a matched comparison.

### Project module topology

Implement the project as one Python 3.12 distribution with one operator CLI and four deep top-level modules:

1. **`declarations`** owns Scenario Package validation and locks, `standard-v1` expansion, Suite Releases, compatibility and lifecycle records, Production Experiment Manifests, Planned Trial Cells, canonical serialization, and typed digests. It emits immutable declarations for later modules.
2. **`runtime`** owns the three Harbor Adapters, single-cell Harbor job compilation, Credential Proxy process, preflight, launch, external monitoring, and Harbor child-process execution. It consumes one sealed Planned Trial Cell and freezes one completed raw attempt workspace against further runtime writes, containing Harbor-native and host-side evidence. It does not classify task quality, amend the Run Ledger, or calculate report statistics.
3. **`evidence`** owns Final Repository Capture, Submission derivation and validation, redaction, Artifact Descriptors, Result Bundle sealing, Trial Attempt disposition reconciliation, append-only Run Ledger writes and Amendments, and read-back verification. It converts a Planned Trial Cell plus raw attempt workspace into sealed canonical evidence.
4. **`analysis`** owns effective Amendment and replacement projections, disposition-aware analysis datasets, paired statistics, compatibility gates, and generation and sealing of the static report. It has read-only access to canonical Trial evidence.

Module handoffs are immutable typed artifacts rather than a shared mutable database or cross-module callbacks. The operator CLI invokes the modules through their public interfaces. Qualification commands exercise those same interfaces with qualification fixtures; they do not create a second execution path.

Keep Angular and TypeScript, Spring Boot and Java, and Python data-engineering support as declarative templates and data under `scaffolds/`, not executable stack-specific modules. The Credential Proxy is the only separately running project process, scoped to the provider route used by a Trial. Private implementation submodules are allowed, but they do not enlarge the four public module interfaces.

### Credential Proxy boundary

Build one narrow project-owned transparent reverse proxy inside `runtime`; do not adopt LiteLLM or another model gateway. Start one proxy instance per Trial, configured for exactly one Planned Trial Cell, Provider Route and upstream endpoint, requested model identifier, opaque Trial token, real upstream credential, request/token/spend ceilings, and secret-safe evidence destination.

The proxy has one small interface: authenticate the opaque Trial token; allow only declared upstream paths; replace local authentication with the real credential; reject a model or supported-setting mismatch; stream the provider's compatible protocol without semantic transformation; enforce declared ceilings without silently changing model parameters; and record request timing, status, provider-reported model and usage, and budget events. It must not persist prompt or response content solely for surveillance.

The proxy performs no protocol translation, prompt rewriting, parameter substitution, fallback, retry, caching, response repair, provider discovery, load balancing, billing, multi-tenancy, model aliasing, or agent/model orchestration. A Stock Profile that cannot target the declared compatible endpoint is unqualified rather than receiving a behavior-changing bridge.

Reuse pinned HTTP server and client libraries, TLS primitives, and the project's canonical redaction utilities. Keep routing, control validation, budget enforcement, and evidence emission project-owned and small enough to audit. The real credential remains host-side; only the opaque Trial token and proxy route enter the agent environment.

### Evidence collection and canonical storage

Use a local content-addressed filesystem store as the initial evaluator's only canonical backend. The `runtime` module writes one isolated raw attempt workspace on a dedicated non-retained tmpfs or equivalently disposable encrypted volume. That workspace is not canonical evidence. It captures Harbor's native configuration, lock, result, verifier, timing, log, trajectory, and artifact files without semantic normalization; all non-secret bytes remain verbatim after required redaction.

Add thin host-side collectors only for demonstrated gaps: Docker and cgroup resource and termination evidence, Credential Proxy metadata and usage, network-policy events, Scenario Baseline and Final Repository Captures, Submission validation, redaction evidence, and teardown status. Do not duplicate Harbor-native lifecycle collection or add agent-internal surveillance.

Register secrets and structural omission rules before launch. Stream-redact host logs and proxy evidence before any durable write; keep Harbor's unprocessed temporary output only inside the disposable raw workspace. Before any canonical write, `evidence` applies the complete redaction rules and post-capture scan, inventories every retained file, computes the Result Bundle payload digest, writes through a temporary directory, atomically renames the complete bundle to its digest-addressed path, then reads every file back and verifies its byte length and digest. Append the terminal Run Ledger record only after that verification. When sealing fails, append the applicable explicit missing or quarantined terminal record rather than leaving a partially authoritative row.

Destroy the raw attempt workspace only after successful bundle and ledger read-back. On integrity, redaction, sealing, or teardown failure, prevent reuse, revoke any exposed credential, and move only secret-safe diagnostic evidence into the access-controlled quarantine store; never retain unredacted workspace bytes as a canonical or diagnostic bundle.

Do not require a canonical SQL database, dashboard store, object store, event bus, or mutable latest-result table. Keep canonical Private evidence in a separate access-controlled root. Public exports and reports are separately sealed derivatives. CSV, SQLite, analytical tables, and caches are disposable projections regenerated from the effective Run Ledger.

Canonical Artifact identity remains its bundle-relative path and digest, so moving retained bytes later changes only a non-authoritative storage locator. Do not introduce a generalized storage-provider seam until a real second backend is required.

### Harness Adapter implementation

Keep exactly three versioned declarative Adapter records and three small project-owned `BaseInstalledAgent` subclasses: OMP, OpenCode, and Hermes. They satisfy one common internal interface without creating a generic command-template language or third-party Adapter plugin system.

Share only safe mechanics: verify the read-only mounted Harness artifact and version; create a fresh home and deterministic Stock Profile configuration; validate the Credential Proxy route and declared model mapping; deliver the exact Developer Brief bytes once; start one process; capture raw output, exit facts, and declared native artifacts; and complete the Harness-specific shutdown contract. OMP alone starts a fresh local RPC process, sends one no-session request, and stops that process after capture.

Keep Harness-specific implementation limited to deterministic configuration materialization, safe argv, standard-input or RPC transport, and native artifact locations. The classes perform no lifecycle retries, task interpretation, verification, evidence sealing, or common trace normalization.

Do not subclass Harbor's built-in Hermes, OpenCode, or Pi classes. Their selected-revision installation, credential routing, configuration, launch, and trajectory behavior are coupled in ways that conflict with the accepted runtime profile and would make upgrades fragile. Preserve native Harness records opaquely; common usage, timing, process, and control evidence comes from the Credential Proxy and trusted host collectors.

First-party invocation knowledge and narrowly reusable parsing tests may be adapted only with pinned provenance and independent qualification against the selected Stock Profile. Reuse of an idea or fixture does not make Harbor's built-in Adapter implementation part of the production execution path.

### Execution granularity and scheduling

Compile every Trial Attempt into one Harbor job containing exactly one Scenario Package, one Harness Adapter, one model condition, `n_attempts = 1`, and `n_concurrent_trials = 1`. The Harbor job is the physical execution unit; the Planned Trial Cell remains the experimental design unit.

Disable Harbor's retry mechanism for measured execution. Harness-native retries remain within one Trial and every request is observed by the Credential Proxy. An allowed experimental Replacement Trial is a new single-cell Harbor job with a new Trial Attempt identity, the same Condition Fingerprint, and explicit lineage to the prior attempt; it is never a Harbor retry or resumed Trial.

The coordinator consumes the frozen randomized schedule from the Production Experiment Manifest and executes it sequentially on one qualified worker. Resume only from sealed Run Ledger state: skip a cell with an effective completed attempt, create the single permitted replacement only when the recorded disposition allows it, and fail closed on ambiguous, unsealed, or partially authoritative state.

Never infer Matched Block, repetition, ordering, or replacement identity from Harbor directory order, timestamps, `n_attempts`, or concurrency behavior. Do not build an execution daemon, distributed queue, dynamic scheduler, worker pool, or outcome-driven stopping mechanism for the initial evaluator. Parallel execution across multiple workers remains deferred until a concrete scale need justifies a separately qualified design that preserves Worker Profile strata and matched ordering.

### Analysis and report generation

Implement a deterministic two-stage batch pipeline inside `analysis`.

The analytical stage reads the effective append-only Run Ledger and authorized Result Bundle manifests; applies compatibility, eligibility, replacement, Amendment, disposition, and common-support rules; computes the frozen paired statistics and operational tradeoffs; and emits one canonical sealed `analysis-result.json`. That projection contains every displayed value, denominator, claim state, provenance reference, and drill-down identity. It is inspectable and testable independently of presentation.

The rendering stage consumes only the sealed analytical projection and disclosure-authorized artifact views. Use pinned Jinja2 templates, static CSS, and precomputed SVG charts. Generate the internal and releasable derivatives independently from their authorized projections; never render the internal site and then delete private material. Inventory and seal every generated page, stylesheet, SVG, and included disclosure-safe artifact.

The renderer performs no live database query, client-side statistical calculation, mutable filtering, or reinterpretation of strata, exclusions, weights, margins, or claims. Do not build an application server or JavaScript framework. Record the pinned analysis implementation, dependency lock and environment identities, random seed, and resampling count in the report manifest.

### Dependency and upgrade boundary

Use one `uv`-managed Python 3.12 project with `pyproject.toml` and a committed `uv.lock`. Pin Harbor as a direct Git dependency at commit `527d50deb63a5d279e8c20593c18a2cbc7f61f9e`, not only by its `v0.18.0` label, and pin every direct and transitive Python dependency through the lock.

Build immutable project and Harbor wheels and coordinator images during trusted provisioning. Qualification and production use those built artifacts without editable installs or network dependency resolution. Pin every OCI base, Scenario, verifier, and Harness artifact image by digest.

Record source revision, license, digest, and adaptation provenance for externally reused code and test fixtures. Source-material reuse does not confer benchmark-evidence authority and must remain independently qualified through the project's contracts.

Support exactly one Harbor revision at a time; do not build cross-version compatibility shims. A Harbor upgrade updates the commit pin and dependency lock, regenerates affected declarations and locks, runs schema and configuration conformance, and reruns every applicable Harness, isolation, verifier, artifact, and sealing qualification gate. Accept the revision only when the new Qualification Bundles pass.

Reject an upgrade that requires internal Harbor imports, monkeypatches, or duplicated lifecycle behavior, or reopen the substrate decision if the validity-critical gap warrants it. Do not enlarge the project seam merely to preserve an upgrade.

### Operator interface

Expose one non-interactive CLI, `model-benchmark`, aligned with the four module interfaces. Keep this initial command surface:

- `scenario scaffold`, `scenario check`, `scenario qualify`, and `scenario lock`;
- `suite seal`, `suite verify`, and `suite compatibility`;
- `experiment seal`, `experiment preflight`, and `experiment run`;
- `ledger verify` and `ledger amend`; and
- `report build` and `report verify`.

`experiment run` is idempotent and resumes only from verified sealed Run Ledger state; do not add a separate mutable resume mechanism. Harbor job construction remains an implementation detail behind that command.

Commands accept explicit manifest and path arguments and emit a machine-readable JSON summary beside concise human output. A validation or qualification failure returns nonzero and writes no authoritative partial artifact. Automated qualification and execution never prompt. Secrets enter only through declared runtime injection seams and never through command arguments, generated configuration values, or printed output.

Do not build a REST control plane, interactive TUI, notebook-only workflow, web operator application, or plugin command registry for the initial evaluator.

### Repository and source ownership

Keep implementation code, schemas, `standard-v1`, report templates, ecosystem scaffolds, Public Scenario Packages, and Legacy Calibration fixtures in this repository. Use this top-level layout:

```text
src/model_benchmark/{declarations,runtime,evidence,analysis}/
schemas/
profiles/
scaffolds/
scenarios/public/
scenarios/calibration/
templates/report/
tests/
```

Keep Private Scenario Packages in a separate access-controlled repository or checkout using the same Scenario Package layout and validation workflow. A Production Experiment receives that Private source root explicitly and records its repository identity and package digests.

Never place Private Developer Briefs, seeds, verifiers, Reference Solutions, manifests, expected outputs, or package bytes in this repository's working tree, Git history, build context, public Provisioning Cache, or release artifacts. Do not use Git submodules or duplicate implementation code in the Private source repository.

Both source roots remain inputs to the same `declarations`, qualification, execution, `evidence`, and `analysis` modules. Suite manifests reference immutable package identities; filesystem placement and repository URL remain provenance and locator facts rather than package identity.

### Architectural proof gates

Require four verification layers before this architecture may produce measured evidence:

1. **Unit and schema conformance** proves canonical serialization and digest golden vectors; strict schema rejection; profile expansion and exceptions; identity joins; Amendment and replacement resolution; redaction; and deterministic analytical projections without Docker or provider access.
2. **Harbor contract tests** load generated Scenario and single-cell job configurations with pinned Harbor and prove custom Adapter import paths, one-Trial expansion, lock contents, separate-verifier configuration, read-only Harness image mounts, native result ingestion, and artifact-manifest handling. A static architecture test rejects project imports of Harbor's internal `Job`, `Trial`, queue, and lifecycle modules.
3. **Runtime fault-injection qualification** exercises each Harness through the Credential Proxy and proves no measured download, exact model routing, fresh writable state, hidden-marker absence, complete process-tree termination, resource and spend limits, unsafe Submission rejection, missing-evidence invalidation, secret redaction, teardown quarantine, and digest read-back. It covers infrastructure, Harness, limit, integrity, malformed-output, and operator-abort paths.
4. **End-to-end Calibration qualification** runs one representative Legacy Calibration Scenario per ecosystem through all three Harnesses via `experiment run`; verifies the complete Planned Trial Cell → Harbor job and Trial → Result Bundle → Run Ledger → analytical projection → internal and releasable static report joins; repeats Reference Solutions and report generation to prove identical score vectors and deterministic output digests where applicable; and scans every releasable derivative for Private identities, paths, and bytes.

Mocks may support lower layers but never substitute for the real Docker, Credential Proxy, Harness, separate verifier, sealing, and report gates. [Validate the blueprint and set the implementation handoff](https://github.com/MihaiA24/model-benchmarking/issues/25) owns converting these obligations into an ordered implementation backlog; this decision owns the architectural requirement that every gate exists and uses the production interfaces.

### Reuse disposition

| Disposition | Scope |
| --- | --- |
| Adopt unchanged | Pinned Harbor task loading and locking, environment and Trial lifecycle, resource and network enforcement surfaces, separate verifier lifecycle, native result/timing/log/trajectory/artifact collection, and documented CLI/config/result contracts. |
| Wrap without replacing | Single-cell Harbor job generation and child-process invocation; `standard-v1` expansion into Harbor-native fields; native lock/result/artifact validation and retention; conversion of completed native evidence into project-owned typed records. |
| Extend through supported seams | Three custom `BaseInstalledAgent` implementations, read-only Harness artifact image mounts, thin host-side collectors for demonstrated gaps, and Scenario-specific logical sidecar export hooks. No extension duplicates execution, verification, teardown, or retry ownership. |
| Build project-owned | The four project modules, Credential Proxy, operator CLI, schemas and canonicalization, profile and package tooling, manifests and registries, repository capture and handoff validation, redaction and sealing, Run Ledger, paired analysis, static report generator, and qualification suites. |
| Reuse as source material only | Harbor's built-in Hermes, OpenCode, and Pi invocation knowledge and narrow fixtures; legacy task ideas, seed mutations, verifier intent, and selected reporting patterns; and the accepted report prototype hierarchy. Every retained idea is rebuilt and independently qualified before it can support execution or evidence. |
| Fork or vendor modified implementation | Nothing. |

If a core isolation, lifecycle, policy-enforcement, or artifact-handoff gate fails and cannot be satisfied through configuration or a small upstream-compatible supported extension, reopen the substrate decision and evaluate the already bounded custom-runner fallback. Never cross the reuse boundary incrementally through hidden patches.

## Evidence and dependency reconciliation

This architecture specializes rather than reopens the accepted [benchmark substrate](../research/benchmark-substrate.md), [hermetic execution and integrity](hermetic-execution-and-integrity.md), [Harness Adapter and launch](harness-adapter-and-launch-contract.md), [Scenario Package and authoring](scenario-package-and-authoring-protocol.md), [Run Ledger and provenance](run-ledger-and-provenance-schema.md), [generated benchmark report](generated-benchmark-report.md), and [Suite versioning and refresh](suite-versioning-and-refresh-policy.md) decisions.

Pinned Harbor v0.18.0 first-party source confirms the selected public seams: custom agents load through an import path and `BaseInstalledAgent`; job configuration exposes one-attempt and one-concurrent-Trial controls, custom-agent configuration, environment mounts, and local task inputs; task configuration exposes digest-pinnable prebuilt images, separate verifier environments, network/resource controls, and artifact declarations; and Harbor writes native job locks, Trial results, verifier outputs, and artifact manifests. The same pinned source also shows why the built-in Hermes, OpenCode, and Pi classes remain reference material: their installation and direct-provider behavior conflict with the accepted offline and Credential Proxy profile.

No background research, delegated investigation, or unresolved evidence request was dispatched for this ticket. All external source checks were synchronous against commit-pinned Harbor documentation and source.

## Qualification risks retained for implementation

The read-only image-mount capability, each Stock Profile's ability to target the transparent Credential Proxy, exact enforcement of provider ceilings, Docker network/resource behavior, mandatory collector completeness, and deterministic internal/public report generation remain proof obligations. They are not permission for alternate architecture paths: each fails closed through the specified contract or runtime qualification gate and is routed into the implementation sequence owned by [Validate the blueprint and set the implementation handoff](https://github.com/MihaiA24/model-benchmarking/issues/25).

## Decision completeness

This decision fixes what is adopted, wrapped, extended, built, reused only as source material, and explicitly not forked. It also fixes immutable-image reuse, fresh-state boundaries, `standard-v1` ownership and expansion, module interfaces, Credential Proxy scope, evidence storage, Adapter shape, execution granularity, analysis/report generation, dependency upgrades, operator commands, source ownership, and architectural proof gates. No architecture or reuse decision remains open within this ticket.

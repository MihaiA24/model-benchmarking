# Define the scenario package and authoring protocol

**Status:** Final decision
**Map:** [Design a real-world CLI benchmark for coding-agent harnesses](https://github.com/MihaiA24/model-benchmarking/issues/13)
**Ticket:** [Define the scenario package and authoring protocol](https://github.com/MihaiA24/model-benchmarking/issues/19)

## Accepted decisions

### Canonical package boundary

Define a **Scenario Package** as one versioned Harbor-native composite directory. The package is canonical as a whole; it is not compiled from a second substrate-neutral task format.

Keep Harbor-owned execution declarations directly consumable by pinned Harbor v0.18.0: `task.toml`, `instruction.md`, the agent environment, the separate verifier environment and tests, solution assets where retained for author validation, and Harbor artifact or sidecar declarations.

Add one project-owned `scenario.yaml` only for benchmark contracts that Harbor cannot represent. It must not mirror Harbor-owned fields. Cross-file validation checks the project declaration against the Harbor task rather than maintaining duplicate sources of truth.

Version and content-digest the complete canonical package payload. The immutable package identity therefore covers the developer brief, project metadata, Harbor task configuration, build inputs, verifier assets, and declared supporting files together. The generated lock is sealed by the suite release rather than included in its own payload digest, avoiding a circular self-hash.

Do not build a speculative substrate-neutral compiler. If the benchmark later replaces Harbor, perform an explicit package migration with preserved provenance rather than carrying two live execution schemas now.

### Evaluated-repository baseline

Define the evaluated repository through two independently verifiable identities:

1. The **Pristine Source Snapshot** records the repository origin, full commit, source or archive digest, normalized tree digest, and applicable license.
2. The **Scenario Baseline** is the exact tree presented to every harness after applying an optional canonical seed patch and any explicitly declared content-addressed seed assets to that pristine snapshot.

Record the seed inputs and expected resulting tree digest in `scenario.yaml`. Seed inputs may plant a bug, add a feature stub, or add public fixtures, but they must never contain hidden checks or expected private answers. Every byte that changes the pristine snapshot must be attributable to a declared seed input; arbitrary author setup scripts may not silently mutate the evaluated repository.

Measured trials perform no repository clone, package download, or mutable setup. Preflight reconstructs or materializes the Scenario Baseline from provisioned immutable inputs and fails closed unless its normalized tree digest matches the package declaration before the harness starts.

This contract does not select an OCI-layer or archive layout. The later architecture decision may choose any Harbor-compatible materialization that preserves both identities, uses only pre-provisioned immutable inputs during measured execution, and produces the declared Scenario Baseline exactly.

### Developer brief

Use `instruction.md` as the sole canonical **Developer Brief**. Store it as normalized UTF-8 text without template expansion or harness-specific variants, record its content digest in `scenario.yaml`, and deliver its exact bytes once through each harness's accepted native transport.

Write the brief like a professional development ticket. It states observable required behavior, legitimate constraints, allowed deliverables, and any declared local resources needed to do the work. It must not reveal the reference solution, the seed-mutation explanation, hidden-check names, private expected outputs, a prescribed implementation, or benchmark-specific hints.

Repository-visible tests and documentation remain ordinary evidence available to the harness. Verifier-only acceptance and regression checks remain absent from the Scenario Baseline. An adapter may not append guidance, clarification, or recovery instructions during a trial.

Any clarification that changes task meaning creates a new Scenario Package version and instruction digest. Editorial normalization that changes bytes is also recorded rather than silently substituted in an existing package.

### Verifier and score contract

Every benchmark Scenario Package uses Harbor's separate verifier environment. Shared verification is invalid for benchmark evidence because it does not preserve the accepted hidden-check and clean-materialization boundary.

Predeclare stable acceptance, regression, and optional domain Check Groups in `scenario.yaml`. Each group has an immutable identifier, class, required status, weight where applicable, score direction, and evidence key. Acceptance-group weights sum to one, regression-group weights sum to one, and raw test counts never determine a scenario's aggregate weight.

The verifier emits `/logs/verifier/verifier-result.json`, a project-owned structured result containing every raw named check with one of `pass`, `fail`, `error`, or `not_evaluable`, plus evidence references and the complete derived score vector. It also emits Harbor's `/logs/verifier/reward.json` as the numeric projection containing at least `task_success` encoded as `0` or `1`, `acceptance_score`, `regression_score`, and every declared numeric domain score. Validation must prove that the numeric projection agrees with the structured result's boolean `task_success` and scores.

Set `task_success` to true only when the submission handoff is valid and every required acceptance and regression group passes. Partial scores remain explanatory and cannot turn a required failure into success.

Declare a total deterministic scoring rule for safe partial, missing, malformed, oversized, unsafe, and otherwise rejected submissions. A verifier failure caused by submitted code remains a valid harness outcome; a failure of verifier infrastructure independent of the submission produces no quality score and is classified through the accepted infrastructure disposition instead.

### Submission boundary

Use a trusted host-derived normalized Git patch against the Scenario Baseline as the default Submission for coding scenarios. The harness never supplies the authoritative patch. After its complete process tree has stopped, the host captures final repository state and derives the patch, including explicitly permitted new files. No repository change materializes as the declared no-op Submission used by the total scoring contract.

Declare the repository root, allowed and protected paths, whether additions and deletions are permitted, file-count and byte limits, and policy for symlinks, executable bits, submodules, nested repositories, and binary files in `scenario.yaml`. Handoff validation fails closed before verifier materialization when the captured state violates that declaration.

Allow a non-patch Submission only when repository changes cannot faithfully represent the required deliverable, such as a database export or generated data artifact. Such a declaration requires an exact path allowlist, media type and schema, size limit, safe materialization procedure, and a digest captured from the produced artifact.

Sidecar state may cross the boundary only through declared Harbor collect hooks and content-addressed logical exports. Raw writable volumes, container layers, homes, and mutable caches never become Submissions.

### Initial execution-profile boundary

Keep the initial harness evaluator intentionally narrow. Define one frozen **Execution Profile**, `standard-v1`, that supplies the benchmark-wide defaults for a fresh unprivileged environment, fixed CPU, memory, writable-storage and provider-spend ceilings, credential-proxy-only network access, separate verification, standard evidence capture, and observational elapsed time without wall-clock termination.

Every initial Scenario Package references `standard-v1`. Scenario initialization writes the profile's Harbor-compatible defaults into `task.toml`, and package validation rejects an author edit that weakens them. Scenario authors declare only task-specific evaluated-repository and image inputs, the Developer Brief, Submission and Check Groups, required datasets, and optional sidecars or non-patch outputs.

Do not require per-scenario process limits, detailed integrity-signal lists, sensitivity taxonomies, custom network rules, or multiple resource profiles until a selected scenario demonstrates a concrete need. An approved exception is explicit and creates a separately labelled comparison stratum; it may not silently weaken a matched comparison.

This ticket owns the Scenario Package's profile reference and exception boundary. [Set the benchmark architecture and reuse boundary](https://github.com/MihaiA24/model-benchmarking/issues/24) owns how the profile is represented, expanded, and enforced without duplicating Harbor, while [Define the run ledger and provenance schema](https://github.com/MihaiA24/model-benchmarking/issues/21) owns recording the resolved profile and any exception in trial evidence.

### Public and private package boundary

Use the same Scenario Package schema, verifier contract, and validation gates for public and private suites. Declare exactly one visibility value, `public` or `private`, in `scenario.yaml`; visibility changes disclosure and access control, not scoring semantics or verifier strength.

During every agent phase, expose only the Developer Brief, Scenario Baseline, and explicitly declared local resources. Verifier code, hidden checks, expected outputs, and verifier-only data never enter the agent environment even when their source is publicly available elsewhere.

A released public package may publish its complete source and verifier assets for independent reproduction. A private package, its verifier assets and expected outputs, and its canonical Result Bundles remain in access-controlled source and artifact namespaces.

Keep public and private package identities, task sources, execution roots, credentials, and result namespaces disjoint. Cross-suite analysis may reference separately redacted identities, but no private asset may enter a public package or public canonical bundle.

### Minimal project schema and lock

Keep the human-authored `scenario.yaml` limited to seven sections:

1. `schema_version` identifies the project schema.
2. `scenario` declares a stable scenario ID, independent Scenario Version, visibility, ecosystem, workload, and `execution_profile: standard-v1`.
3. `repository` declares the Pristine Source Snapshot, seed inputs, and resulting Scenario Baseline identity.
4. `instruction` identifies `instruction.md` and its digest.
5. `submission` declares the patch or non-patch kind and its safe handoff boundary.
6. `verification` declares independent Verifier Version and Score Contract Version identities, Check Groups, weights, domain scores, and total scoring rules.
7. `provenance` records authorship, source references, licenses, and contamination disclosures.

Generate and commit `scenario.lock.json`; never edit it manually. The lock inventories every canonical package file except itself with byte length and digest, resolves seed inputs, OCI images, datasets, the Harbor task checksum and pinned Harbor identity, preserves the independent Scenario, Verifier, and Score Contract identities, and records one canonical payload digest over that manifest. The enclosing Suite Release records the digest of `scenario.lock.json`. Package validation must reproduce both the lock contents and payload digest exactly or fail.

Do not put harness, provider/model, repetition, worker, randomized order, trial outcome, or pricing fields in the Scenario Package. Those vary by experiment or observation and belong to the experiment and ledger contracts.

### Canonical directory layout

Use this common layout, omitting only optional seed and data directories:

```text
<scenario>/
├── scenario.yaml
├── scenario.lock.json
├── instruction.md
├── task.toml
├── seed/                 # optional patch and content-addressed seed assets
├── environment/          # Harbor agent-environment inputs
├── tests/                # separate verifier image, checks, and private fixtures
├── solution/             # author-only Reference Solution
└── data/                 # optional declared datasets or sidecar seeds
```

The resulting Scenario Baseline and explicitly declared local resources are agent-visible. The `seed/`, `tests/`, and `solution/` trees are provisioning-only, verifier-only, or author-only and must never be copied into the measured agent environment. Files from `environment/` are visible only when the trusted image recipe intentionally installs them as declared runtime resources. `task.toml` remains directly loadable by pinned Harbor; `scenario.yaml` and `scenario.lock.json` add project identity and validation without replacing it.

### Reference solution

Require one author-only **Reference Solution** under `solution/` for every Scenario Package. It exists only to prove that the Scenario is solvable and that the complete verifier can recognize at least one valid implementation. It is never exposed during measured agent execution.

The seeded or no-op Scenario Baseline must fail at least one required acceptance Check Group while passing every applicable regression Check Group. The Reference Solution must produce `task_success=true` repeatedly when applied to fresh verifier environments.

The verifier never compares a Submission with the Reference Solution or rewards patch similarity. Alternative implementations pass when they satisfy the declared behavior and Check Groups. Private-suite solutions remain access controlled; a public solution may be disclosed only as part of the released public package.

### Authoring and qualification workflow

Use one short workflow:

1. Scaffold a Scenario Package from the frozen `standard-v1` template.
2. Author the source snapshot, seed inputs, Developer Brief, verifier, Check Groups, and Reference Solution.
3. Run one package checker that performs project-schema validation, cross-file checks, and pinned-Harbor task loading.
4. Run qualification against fresh agent and verifier environments.
5. Obtain one independent review, generate `scenario.lock.json`, and seal one Suite-owned Package Qualification Record.

Qualification must prove all of the following before a package is eligible for suite selection:

- the Pristine Source Snapshot and Scenario Baseline reproduce their declared digests;
- pinned Harbor loads the task, and every OCI image and dataset resolves to an immutable digest;
- hidden checks, expected outputs, and the Reference Solution are absent from the agent environment;
- the no-op Scenario Baseline produces its declared failure or partial-score vector;
- the Reference Solution passes every required Check Group twice in fresh verifier environments with identical score vectors;
- representative malformed and unsafe handoffs are rejected according to the declared total scoring rules; and
- measured execution requires no download.

One independent reviewer confirms that the Developer Brief and verifier specify the same observable behavior, required checks do not encode an undisclosed implementation preference, provenance and licensing are complete, and the agent-visible package contains no answer leakage. Lock generation precedes the Package Qualification Record; any subsequent content or component-identity change invalidates both and requires qualification again. The Package Qualification Record is independent of Harness, adapter, Provider Route, model, Worker Profile, or Production Experiment Manifest. Those exact-condition controls are proven later by experiment-owned Qualification Bundles.

### Cross-ecosystem portability

Use one Scenario Package schema and one qualification workflow for Angular and TypeScript, Spring Boot and Java, and Python data workloads. Do not create stack-specific runners, schemas, score fields, or trial lifecycles.

Provide only thin ecosystem scaffolds containing a pinned toolchain and dependency-image starting point, conventional repository working directory, verifier-image starting point, and example build or test invocation. A Scenario Package declares its actual dependencies, Check Groups, and commands; the scaffold carries no stack-specific benchmark semantics.

Python and data scenarios may opt into the already-defined non-patch Submission or sidecar-export capabilities when repository changes cannot represent the deliverable. Those remain common Submission capabilities rather than a separate data runner.

Before implementation treats the format as qualified, one representative Scenario Package from each of the three ecosystems must pass the same package and environment qualification gates.

## Downstream contracts

- [Select the initial scenario portfolio](https://github.com/MihaiA24/model-benchmarking/issues/20) selects only scenarios that can be authored and qualified under this protocol; it owns workload coverage, realism, difficulty, and the actual public/private portfolio rather than changing the package format.
- [Define the run ledger and provenance schema](https://github.com/MihaiA24/model-benchmarking/issues/21) records the scenario ID and version, payload and lock digests, resolved `standard-v1` profile, Submission identity, structured verifier result, Harbor reward projection, and any explicit exception.
- [Define suite versioning and refresh policy](https://github.com/MihaiA24/model-benchmarking/issues/23) owns scenario-version bump rules, suite locks, compatibility, public release timing, and private rotation while preserving the immutable identities defined here.
- [Set the benchmark architecture and reuse boundary](https://github.com/MihaiA24/model-benchmarking/issues/24) implements the schema, lock generator, package checker, `standard-v1` expansion, Harbor wiring, and thin ecosystem scaffolds without introducing a second task lifecycle.
- [Validate the blueprint and set the implementation handoff](https://github.com/MihaiA24/model-benchmarking/issues/25) must verify that these contracts agree with the final ledger, suite, architecture, and report decisions and that the implementation sequence includes one qualified package per ecosystem.

## Evidence basis

This decision specializes the already accepted [benchmark-substrate](../research/benchmark-substrate.md), [hermetic execution and integrity](hermetic-execution-and-integrity.md), [harness adapter and launch](harness-adapter-and-launch-contract.md), [legacy scenario inventory](../research/master-scenario-inventory.md), and [scoring and statistical analysis](../research/scoring-and-statistical-analysis-protocol.md) contracts rather than reopening them.

Pinned Harbor v0.18.0 primary sources establish the executable surface used here: its [task structure and authoring contract](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/docs/content/docs/tasks/index.mdx) defines `task.toml`, `instruction.md`, environment, solution, tests, numeric rewards, separate verifier environments, declared artifacts, and sidecar collect hooks; its [authoritative task model](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/models/task/config.py) defines the schema and validation behavior. Project-owned files cover only identities and scoring semantics absent from that Harbor model.

No background research or delegated investigations were dispatched for this ticket. The Harbor claims above were checked synchronously against the pinned first-party documentation and source.

## Decision completeness

This decision fixes the canonical package boundary, minimum authored schema, immutable repository and instruction identities, submission and verification contracts, initial execution-profile reference, public/private disclosure boundary, reference-solution requirement, authoring workflow, and cross-ecosystem portability rule. Exact schema syntax, command names, profile expansion, and module layout are implementation details owned by the later architecture and handoff decisions.

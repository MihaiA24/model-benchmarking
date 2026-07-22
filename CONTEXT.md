# Coding-Agent Harness Benchmarking

This context compares autonomous coding-agent harnesses on reproducible real-code scenarios while preserving experimental identity and raw evidence.

## Language

**Harness**:
A system under evaluation that autonomously attempts a scenario through its own non-interactive CLI. OMP, OpenCode, and Hermes are harnesses.
_Avoid_: Agent, runner

**Raw API Baseline**:
A minimal single-request OpenAI-compatible control condition that receives the same Developer Brief and one declared target file, writes only the returned replacement for that file, and passes the resulting Submission to the same Verifier path. It is a qualified control rather than a Harness: failure before response materialization measures baseline protocol incompatibility rather than raw-model task capability, and it is not eligible for Harness ranking.
_Avoid_: Harness, autonomous agent, fourth harness

**Benchmark substrate**:
A reusable execution framework that owns task expansion, isolated environments, trial lifecycle, verification, and raw result capture without owning the experiment's comparison design.
_Avoid_: Harness, experiment coordinator

**Experiment coordinator**:
The project-owned layer that declares comparable conditions, binds harness adapters to scenarios, preserves paired-trial identity, and seals result evidence while delegating execution to the benchmark substrate.
_Avoid_: Runner, harness

**Functional V1**:
The diagnostic milestone in which one trusted local operator executes the fixed comparison conditions through the selected Legacy Calibration Suite slice and obtains verified Result Bundles without making a statistically defensible ranking claim.
_Avoid_: Production benchmark, decision-grade comparison, CLI smoke test

**Functional V1 Run Manifest**:
The versioned non-secret operator declaration that fixes one Functional V1 comparison by pinning its Provider Route, exact model, shared per-cell limits, Scenario Package locks, and Functional V1 Condition Locks.
_Avoid_: Production Experiment Manifest, mutable configuration, secret store

**Resolved Functional V1 Manifest**:
The canonical execution declaration produced by resolving a Functional V1 Run Manifest against verified immutable Functional V1 Home inputs and expanding its fixed envelope and 12 Functional V1 Trial Cells.
_Avoid_: Source YAML, mutable runtime configuration, Functional V1 Run Manifest

**Functional V1 Execution Envelope**:
The fixed diagnostic-only per-cell resource and provider limits shared by all 12 Functional V1 Trial Cells, including an enforced 30-minute wall-time limit that does not apply to production measured Trials.
_Avoid_: Execution Profile, production Trial limits, operator override

**Advisory Token Threshold**:
A non-enforcing cumulative provider-token level that produces an operator-visible warning while allowing the Trial to continue.
_Avoid_: Token limit, upper boundary

**Token Stop Threshold**:
A cumulative provider-token level evaluated after each complete provider response; once reached, the next provider request is rejected. Actual usage may exceed it by the final response and preserves that overshoot explicitly.
_Avoid_: Exact hard cap, absolute token boundary

**Functional V1 Condition Lock**:
A sealed platform-aware declaration binding one Functional V1 comparison condition to its exact executable or materializer, adapter behavior, native configuration, Provider Route and model mapping, evidence surfaces, and transitive common execution inputs.
_Avoid_: Harness Profile, shared run limits, ad hoc CLI arguments

**Condition Adapter**:
The project-owned binding that satisfies the common condition contract for exactly one Functional V1 comparison condition: loading its Condition Lock, provisioning its immutable inputs, sealing its launch, and evaluating its post-run qualification. Three Condition Adapters bind Harnesses and one binds the Raw API Baseline; being a Condition Adapter confers no Harness identity or ranking eligibility.
_Avoid_: Harness, fourth harness, launch shim

**Functional V1 Home**:
The operator-selected managed local root containing immutable provisioned inputs, Functional V1 Run Workspaces, sealed Functional V1 Run Records, and coordinator lease state for any number of Functional V1 invocations.
_Avoid_: Run home, Benchmark Home, Run Workspace

**Functional V1 Run Workspace**:
The write-once unsealed local state of one Functional V1 invocation, containing its immutable header and per-cell start and terminal artifacts until a terminal Functional V1 Run Record can be sealed.
_Avoid_: Run Ledger, mutable results database, reusable Trial workspace

**Functional V1 Run Record**:
The immutable index of one Functional V1 invocation, binding its resolved inputs, terminal Trial-cell records, Result Bundle identities, and complete or incomplete terminal state. It is complete only when all 12 cells have one durable start, one valid terminal outcome, and one verified Result Bundle identity.
_Avoid_: Run Ledger, mutable results database, statistical report

**Run ID**:
An opaque UUIDv7 locator assigned once to a Functional V1 invocation for managed-home lookup, resume, and inspection. It is not a benchmark-input or evidence identity.
_Avoid_: Run Record identity, manifest digest, Trial ID

**Functional V1 Trial Cell**:
One fixed slot in a Functional V1 Run, formed by one Scenario Package lock and one Functional V1 Condition Lock. A complete Functional V1 Run contains the fixed 12-cell cross product and does not create production Planned Trial Cells.
_Avoid_: Planned Trial Cell, Run Cell, retry

**Evaluated repository**:
The immutable codebase snapshot that a harness may modify while attempting a scenario.
_Avoid_: Repository under test, subject repository, repository being edited

**Pristine Source Snapshot**:
The provenance-bearing upstream code snapshot from which a Scenario Baseline is deterministically derived.
_Avoid_: Clean baseline, upstream repo

**Scenario Baseline**:
The exact initialized evaluated-repository tree presented identically to every Harness for a Scenario.
_Avoid_: Buggy baseline, task workspace

**Scenario**:
A versioned real-code challenge presented to every compared harness under the same evaluated-repository baseline, instruction, environment policy, and verification contract. Each scenario is materialized as one benchmark-substrate task while retaining its own substrate-independent identity.
_Avoid_: Prompt, test case

**Workload Family**:
The single primary category of professional change a Scenario asks a Harness to perform: Defect diagnosis and repair, Bounded feature implementation, Test generation and hardening, or Repository evolution. It is not a verifier category, and each Scenario belongs to exactly one family for analysis.
_Avoid_: Task type, secondary tag

**Defect diagnosis and repair**:
Locate and correct a seeded behavioral defect while preserving applicable regressions.

**Bounded feature implementation**:
Add observable behavior integrated into an existing Evaluated Repository, including repository-integrated creation of a new component, module, or pipeline.

**Test generation and hardening**:
Add executable tests for existing behavior, edge cases, and regression protection without changing production behavior except through explicitly permitted testability seams.

**Repository evolution**:
Perform a bounded dependency, framework, API, schema, or configuration migration while preserving declared behavior and compatibility.

**Initial Scenario Portfolio**:
The frozen 24-cell authoring and qualification design for the first benchmark: one Scenario in every ecosystem-by-Workload-Family cell of each 12-Scenario Public or Private Suite. A cell becomes a released Scenario only after its candidate package qualifies and the Suite roster seals.
_Avoid_: Task list, scenario pool

**Public Suite**:
The 12-Scenario disclosure namespace whose complete Scenario Packages may be released for independent reproduction. Its results remain a separate Analysis Stratum from the Private Suite.

**Private Suite**:
The 12-Scenario access-controlled namespace containing Scenarios substantively distinct from the Public Suite. Its packages, verifier assets, expected outputs, and canonical Result Bundles remain private; `private` describes benchmark disclosure, not proprietary production source.

**Private Suite Commitment**:
A pre-trial content-addressed commitment to the exact access-controlled Private Roster Manifest and Scenario Package digests, proving that the held-out portfolio was frozen before outcomes were observed without revealing its contents. The commitment is created before and referenced by the outer Private Suite Release manifest, so it never hashes a manifest that already contains itself.
_Avoid_: Private suite release, private package manifest

**Private Roster Manifest**:
The access-controlled canonical roster of exact Private Scenario, Verifier, Score Contract, package-lock, and package-payload identities that forms the Private Suite Commitment preimage before the outer Private Suite Release manifest is sealed.
_Avoid_: Private Suite Release, public commitment

**Legacy Calibration Suite**:
A non-measured collection of migrated historical tasks that exercises the real package, adapter, execution, and verifier path without entering production Matched Blocks, workload scores, Public or Private Suite reports, or comparative claims.
_Avoid_: Legacy benchmark, third benchmark suite

**Suite namespace**:
One of the closed `public`, `private`, or `calibration` release streams, each with independent version identity, disclosure, and evidence-use boundaries.
_Avoid_: Report tab, shared suite counter

**Suite Version**:
The human-facing monotonically increasing SemVer label of a Suite Release within one Suite namespace.
_Avoid_: Scenario version, manifest digest

**Suite Release**:
A sealed Suite manifest identified by its Suite namespace, Suite Version, and manifest SHA-256 digest. A production experiment pins one Public and one Private Suite Release without pooling their evidence.
_Avoid_: Mutable portfolio, benchmark result

**Package Qualification Record**:
A Suite-owned sealed record proving that one Scenario Package is authorable, reproducible, solvable, verifier-consistent, leak-reviewed, and eligible for a Suite roster independently of any experiment-varying Harness, Provider Route, model, Worker Profile, or Production Experiment Manifest.
_Avoid_: Qualification Bundle, Trial result

**Acceptance Verification Artifact**:
A checksum-bound issue-scoped record of a completed acceptance suite, binding its command, case outcomes, and reproducibility inputs. It is not a Proof Envelope or Fresh Proof Generation.
_Avoid_: Acceptance proof, acceptance artifact, Proof Envelope

**Acceptance Source Tree**:
The exact repository path closure whose normalized committed contents form the reproducibility identity of an Acceptance Verification Artifact. Publication is invalid when any non-committed file would contribute; changes outside the closure do not alter identity.
_Avoid_: Entire repository, working tree, source checkout

**Acceptance Artifact Freshness**:
The condition in which every recomputable input identity in an Acceptance Verification Artifact matches the candidate checkout. It proves source reproducibility, not reproduction of recorded launcher, Python, or Docker observations.
_Avoid_: Fresh Proof Generation, recent artifact, full-environment reproduction

**Fresh Authoritative Gate**:
A policy-declared complete ordered verification gate executed against one exact candidate source identity by an eligible Worker. Only its current Fresh Proof Generation may authorize fixed-head proof consumption.
_Avoid_: Development slice, cached integration, acceptance test

**Proof Envelope**:
An immutable runner-produced record binding one Fresh Authoritative Gate execution to its candidate, policy, schema, workflow, Worker, command outcomes, mandatory cases, and child evidence. It is evidence, not the authority for its own currentness.
_Avoid_: Acceptance artifact, child evidence, current proof

**Child Verification Artifact**:
A policy-declared, checksum-bound output produced by one ordered command of a Fresh Authoritative Gate and included in its Proof Envelope. It cannot authorize reuse independently of that envelope and its current Check Run.
_Avoid_: Discovered output, Proof Envelope, reusable proof

**Fresh Proof Generation**:
One attempt to publish a Proof Envelope for an exact repository, candidate SHA, gate, policy digest, and generation identity. Its currentness comes from the newest trusted Check Run, never artifact age or filename.
_Avoid_: Qualification Generation, workflow run, latest artifact

**Proof Revocation**:
An append-only newer failed trusted Check Run that supersedes the exact current successful Fresh Proof Generation after matching its candidate, gate, policy, and generation identities. It never changes or deletes the immutable Proof Envelope.
_Avoid_: Artifact deletion, proof mutation

**Suite Compatibility Record**:
A sealed dimension-by-dimension assessment of whether two Suite Releases have identical, proven-equivalent, incompatible, or unassessed Scenario, scoring, weighting, estimand, claim, and analysis semantics.
_Avoid_: SemVer inference, blanket compatibility flag

**Bridge Study**:
A separately planned diagnostic experiment that reruns unchanged anchor Scenarios contemporaneously under otherwise identical conditions to compare Suite Releases without pooling their fixed-suite results.
_Avoid_: Cross-version pooling, carried-forward Trial

**Production Experiment Manifest**:
A sealed declaration of the exact Suite Releases, Harness and model conditions, execution and worker controls, matched design, repetitions, and analysis implementation used by one production experiment.
_Avoid_: Suite Release, mutable coordinator state

**Production Design Selection**:
The sealed output of deterministic pre-production qualification that consumes the frozen pilot ledger, repetition policy, exact analysis implementation, Pricing Records, and model roster; records candidate pass rates and aggregate-spend qualification; and authorizes one fixed repetition schedule for a Production Experiment Manifest.
_Avoid_: Production result, mutable sizing worksheet

**Clean-room representative repository**:
A legally redistributable repository authored without copying confidential company source or data, designed to reproduce professionally relevant framework and maintenance characteristics for Private Suite Scenarios.

**Evaluated Repository lineage**:
A shared upstream repository or derivative history whose reuse can correlate Scenario familiarity, structure, dependencies, and contamination risk even when commits or seed mutations differ.

**Synthetic Data Fixture**:
A deterministic generated dataset whose versioned schema, generator, seed, distributions, invariants, and content digest reproduce professionally relevant data behavior without copying production or externally licensed records.
_Avoid_: Fake data, sample CSV

**Standard Scenario**:
A bounded professional Scenario requiring meaningful repository investigation and iterative verification without unusually broad cross-layer coordination.

**Challenging Scenario**:
A bounded professional Scenario requiring deeper investigation, a broader change surface, cross-layer coordination, or more involved build/test feedback than a Standard Scenario. The band is assigned before measured Trials and is not inferred from Harness success.

**Scenario Package**:
The canonical versioned collection that defines one Scenario's immutable inputs, developer-facing instruction, execution policy, verification contract, provenance, and supporting assets.
_Avoid_: Task file, prompt bundle

**Scenario Version**:
The SemVer-plus-digest identity of a Scenario's baseline, Developer Brief, declared resources, Submission boundary, and observable task meaning.
_Avoid_: Suite Version, package digest alone

**Verifier Version**:
The SemVer-plus-digest identity of a Scenario's executable checks, fixtures, verifier environment, and verification behavior.
_Avoid_: Score Contract Version, Harbor version

**Score Contract Version**:
The SemVer-plus-digest identity of a Scenario's Check Groups, requiredness, total-scoring rules, directions, weights, and missingness semantics.
_Avoid_: Verifier Version, report formula

**Developer Brief**:
The single immutable, harness-neutral statement of work presented to a Harness for a Scenario.
_Avoid_: Prompt, harness instructions

**Check Group**:
A stable verifier unit that combines one or more checks into a predeclared acceptance, regression, or domain outcome without giving extra weight to scenarios that contain more tests.
_Avoid_: Test count, reward component

**Submission**:
The host-derived repository patch or explicitly declared non-patch artifact transferred from a completed agent environment into a fresh verifier environment.
_Avoid_: Agent response, workspace snapshot

**Final Repository Capture**:
The trusted host's normalized, completeness-bearing identity of the evaluated repository after the Harness process tree stops, from which the Submission is derived.
_Avoid_: Submission, workspace archive

**Trusted Submission Capture**:
The fail-closed post-stop step that derives and validates the Final Repository Capture and Submission outside Harness control before Harbor materializes only the accepted handoff in the Verifier environment. The initial implementation must prove this with Harbor's supported main-stop-before-sidecar-collection seam or reopen the substrate fallback.
_Avoid_: Harness-generated patch, whole-workspace transfer

**Reference Solution**:
An author-only valid implementation used to prove that a Scenario is solvable and its verifier can recognize success, never as a similarity target.
_Avoid_: Golden patch, expected implementation

**Trial**:
One harness's single autonomous attempt at one scenario from a fresh baseline under one declared condition.
_Avoid_: Run, experiment

**Planned Trial Cell**:
One predeclared Harness-condition slot in the intended comparison design. An eligible cell may be fulfilled by an analysis-eligible Trial; an unsupported or unqualified cell remains structural missingness outside a complete Matched Block.
_Avoid_: Trial, result row

**Trial Attempt Record**:
The immutable terminal Run Ledger record for one coordinator attempt to fulfill a Planned Trial Cell, including an attempt that ends before a measured Trial starts. It links any started Trial and its Result Bundle.
_Avoid_: Mutable run row, report row

**Failure**:
An incomplete label that must be qualified by the affected projection: task quality, Submission handoff, Trial validity, or diagnostic completeness. It is not a Trial Attempt disposition.
_Avoid_: Failed run, benchmark failure

**Trial Attempt Disposition**:
The coordinator-assigned top-level classification of a Trial Attempt's validity and termination category, kept orthogonal to task score, Submission outcome, and diagnostic availability.
_Avoid_: Pass/fail, task result

**Task Failure**:
A valid Trial Attempt whose declared `task_success` outcome is false. It records task quality, not the cause of that outcome.
_Avoid_: Harness failure, infrastructure failure

**Comparison Contract Defect**:
A conflict or condition-specific behavior in shared Scenario, Submission, or cleanup rules that changes an observed outcome independently of the capability intended for comparison. Affected evidence is diagnostic rather than claim-bearing.
_Avoid_: Harness failure, task difficulty

**Rejected Handoff**:
A complete Final Repository Capture whose candidate changes cannot become an accepted Submission because they violate the Submission contract. It remains a scoreable Harness outcome unless separate integrity evidence proves a breach.
_Avoid_: Missing Submission, infrastructure failure

**Infrastructure-invalid Trial Attempt**:
A Trial Attempt with no authoritative task-quality observation because trusted benchmark machinery failed independently of Harness output.
_Avoid_: Task Failure, Rejected Handoff

**Diagnostic Limitation**:
Unavailable optional diagnostic evidence that does not invalidate the Trial Attempt or its task-quality score.
_Avoid_: Infrastructure-invalid Trial Attempt, Task Failure

**Replacement Trial**:
The single new Trial Attempt permitted for a Planned Trial Cell after its prior attempt ends `not_started` or `invalid_infrastructure`, under the identical Condition Fingerprint.
_Avoid_: Retry, rerun, second repetition

**Condition Fingerprint**:
A digest derived deterministically from the canonical typed identities fixed by a Planned Trial Cell. It proves equality of the recorded condition without replacing its component provenance.
_Avoid_: Opaque condition ID, proof of immutable model weights

**Declared Control Profile**:
The frozen allowlisted provider, model, Harness, adapter, and execution controls that define a Planned Trial Cell, including explicit omission or default states but no secret values.
_Avoid_: Environment dump, requested-model string

**Qualification Bundle**:
A content-addressed experiment-owned evidence artifact proving before measured Trials that one exact Harness, Stock Profile, adapter, Provider Route, Execution Profile, and Worker Profile combination honors its Declared Control Profile and required enforcement boundary. It never becomes part of Suite Release identity; package eligibility is proven by Package Qualification Records.
_Avoid_: Trial result, configuration claim

**Observed Control Projection**:
The terminal Trial Attempt Record's structured account of controls actually observed by the launch shim, Harness, and Credential Proxy, backed by redacted raw evidence in the Result Bundle.
_Avoid_: Requested configuration, raw environment

**Pricing Record**:
An immutable versioned statement of provider prices, units, currency, applicability, effective interval, source, and content digest used to derive Trial cost from provider-reported usage.
_Avoid_: Mutable price table, rounded cost

**Matched block**:
A predeclared set containing one trial per eligible harness under the same scenario, provider/model profile, worker profile, budgets, and repetition ordinal; the unit used for paired comparison.
_Avoid_: Batch, group of runs

**Analysis stratum**:
A result slice whose suite visibility, workload, provider/model profile, worker profile, and compatible Scenario, Verifier, and Score Contract Versions may be summarized without pooling materially different evidence.
_Avoid_: Leaderboard, overall result

**Smallest Worthwhile Difference**:
The predeclared minimum outcome difference large enough to change an organizational Harness-routing decision within one Analysis Stratum.
_Avoid_: Detectable effect, post-hoc threshold

**Structural Missingness**:
The absence of a Trial because a planned Harness condition is unsupported or unqualified. It is reported as missing common support, never converted to a score or Harness failure.
_Avoid_: Failed Trial, zero score

**Result bundle**:
A content-addressed, write-once collection of a trial's declared identities, raw outputs, verification evidence, operational records, and file digests.
_Avoid_: Report, score

**Artifact Descriptor**:
The canonical identity and availability record for one declared or collected Result Bundle artifact, based on its logical role, bundle-relative path, byte length, SHA-256 digest, sensitivity, and capture state.
_Avoid_: Absolute path, object-store URL, placeholder file

**Secret-safe Provenance**:
Evidence that identifies a credential's declared purpose, scope, injection boundary, and redaction treatment without retaining its value, access-granting identifier, or reusable hash.
_Avoid_: Secret dump, credential hash

**Run Ledger**:
The versioned, append-only canonical structured record of Planned Trial Cells, terminal Trial Attempt Records, and Ledger Amendments. Reports and query stores are derived from it.
_Avoid_: Metrics CSV, dashboard database, mutable results table

**Ledger Amendment**:
An immutable Run Ledger record using exactly one closed operation—`correction`, `supersession`, `invalidation`, or `replacement_designation`—to update the effective interpretation or lineage of earlier records by reference without rewriting or deleting them.
_Avoid_: In-place edit, silent correction

**Canonical Derived Projection**:
A deterministically recomputable value stored with its authoritative inputs and derivation-rule identity for validation and consumption, without outranking those inputs.
_Avoid_: Source fact, report aggregate

**Agent environment**:
The disposable trial boundary in which one harness and its model-controlled processes may inspect and modify the evaluated repository. Everything inside it is presumed visible and mutable to the harness.
_Avoid_: Sandbox, workspace

**Verifier environment**:
The separate post-trial boundary that holds acceptance evidence and receives only declared submission artifacts after the agent environment has stopped.
_Avoid_: Test container, grader workspace

**Integrity violation**:
An attempted or successful crossing of a declared benchmark boundary that invalidates the trial independently of task quality.
_Avoid_: Test failure, harness failure

**Provisioning cache**:
A host-controlled, content-addressed store of immutable trial inputs that may be reused without sharing writable state between trials.
_Avoid_: Shared trial cache, persistent workspace

**Stock profile**:
One pinned harness release or commit plus its versioned minimal configuration, preserving that harness's native autonomous behavior while varying only declared experimental controls.
_Avoid_: Shared agent profile, normalized harness

**Execution Profile**:
A frozen benchmark-wide set of environment, resource, network, verification, and evidence controls applied identically across a comparison stratum.
_Avoid_: Harness profile, task configuration

**Resolved Execution Profile**:
A deterministic projection of one Planned Trial Cell's applicable Execution Profile, Scenario requirements, experiment controls, Worker Profile, and approved exception, retained with its authoritative inputs for validation rather than treated as a new source of policy.
_Avoid_: Runtime defaults, merged configuration authority

**Worker Qualification Record**:
A sealed pre-execution assessment of one exact Worker Profile and host proving required isolation, control enforcement, private/public cache separation, cloud-metadata and personal-credential exclusion, time synchronization, capacity, and `development_only` versus claim-bearing eligibility.
_Avoid_: Worker Profile, operator attestation

**Provisioning Manifest**:
A sealed inventory of every trusted-provisioning input and produced project, coordinator, Scenario runtime, verifier, and Harness artifact image by source, recipe, visibility-scoped cache root, immutable digest, and qualification evidence. Measured preflight verifies it without pulling or building.
_Avoid_: Docker cache listing, mutable build log

**Credential proxy**:
A benchmark-controlled boundary that holds provider credentials and gives a trial only narrowly scoped access to its declared model route.
_Avoid_: Shared API key, secret mount

**Provider Route**:
The declared provider endpoint and routing boundary through which a Trial's model requests pass, recorded separately from the requested and provider-reported model identities.
_Avoid_: Model, Harness endpoint

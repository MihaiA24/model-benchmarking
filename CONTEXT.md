# Coding-Agent Harness Benchmarking

This context compares autonomous coding-agent harnesses on reproducible real-code scenarios while preserving experimental identity and raw evidence.

## Language

**Harness**:
A system under evaluation that autonomously attempts a scenario through its own non-interactive CLI. OMP, OpenCode, and Hermes are harnesses.
_Avoid_: Agent, runner

**Benchmark substrate**:
A reusable execution framework that owns task expansion, isolated environments, trial lifecycle, verification, and raw result capture without owning the experiment's comparison design.
_Avoid_: Harness, experiment coordinator

**Experiment coordinator**:
The project-owned layer that declares comparable conditions, binds harness adapters to scenarios, preserves paired-trial identity, and seals result evidence while delegating execution to the benchmark substrate.
_Avoid_: Runner, harness

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

**Scenario Package**:
The canonical versioned collection that defines one Scenario's immutable inputs, developer-facing instruction, execution policy, verification contract, provenance, and supporting assets.
_Avoid_: Task file, prompt bundle

**Developer Brief**:
The single immutable, harness-neutral statement of work presented to a Harness for a Scenario.
_Avoid_: Prompt, harness instructions

**Check Group**:
A stable verifier unit that combines one or more checks into a predeclared acceptance, regression, or domain outcome without giving extra weight to scenarios that contain more tests.
_Avoid_: Test count, reward component

**Submission**:
The host-derived repository patch or explicitly declared non-patch artifact transferred from a completed agent environment into a fresh verifier environment.
_Avoid_: Agent response, workspace snapshot

**Reference Solution**:
An author-only valid implementation used to prove that a Scenario is solvable and its verifier can recognize success, never as a similarity target.
_Avoid_: Golden patch, expected implementation

**Trial**:
One harness's single autonomous attempt at one scenario from a fresh baseline under one declared condition.
_Avoid_: Run, experiment

**Matched block**:
A predeclared set containing one trial per eligible harness under the same scenario, provider/model profile, worker profile, budgets, and repetition ordinal; the unit used for paired comparison.
_Avoid_: Batch, group of runs

**Analysis stratum**:
A result slice whose suite visibility, workload, provider/model profile, worker profile, and compatible scenario/verifier versions may be summarized without pooling materially different evidence.
_Avoid_: Leaderboard, overall result

**Result bundle**:
A content-addressed, write-once collection of a trial's declared identities, raw outputs, verification evidence, operational records, and file digests.
_Avoid_: Report, score

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

**Credential proxy**:
A benchmark-controlled boundary that holds provider credentials and gives a trial only narrowly scoped access to its declared model route.
_Avoid_: Shared API key, secret mount

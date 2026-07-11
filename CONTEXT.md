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

**Scenario**:
A versioned real-code challenge presented to every compared harness under the same evaluated-repository baseline, instruction, environment policy, and verification contract. Each scenario is materialized as one benchmark-substrate task while retaining its own substrate-independent identity.
_Avoid_: Prompt, test case

**Trial**:
One harness's single autonomous attempt at one scenario from a fresh baseline under one declared condition.
_Avoid_: Run, experiment

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

**Credential proxy**:
A benchmark-controlled boundary that holds provider credentials and gives a trial only narrowly scoped access to its declared model route.
_Avoid_: Shared API key, secret mount

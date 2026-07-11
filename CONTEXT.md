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

# Model Benchmarking

This context names the benchmark concepts used to compare model-plus-harness combinations on fixed software tasks.

## Language

**Benchmark Run**:
One attempt to solve one benchmark task with one model through one harness, producing one metrics row and one transcript.
_Avoid_: evaluation, job, trial

**Harness**:
The execution surface that invokes a model or coding agent for a benchmark run, such as raw API, OMP, OpenCode, or Hermes.
_Avoid_: provider, runner, CLI

**Canonical Model**:
The comparable model identifier used in benchmark CSVs and review material, independent of the selector syntax required by a harness.
_Avoid_: adapter model, provider slug

**Adapter Model Selector**:
The harness-specific model string passed to a CLI or API when it differs from the canonical model.
_Avoid_: canonical model, alias

**Telemetry Note**:
The CSV explanation for how a benchmark run's calls, tokens, or cost were measured or why they are unavailable.
_Avoid_: comment, warning, debug note

**Run Transcript**:
The per-run invocation log containing the harness command, CLI/API output, final answer, and errors needed to audit that benchmark run.
_Avoid_: full workdir copy, final answer

**Harness Queue**:
A concurrency lane for benchmark runs that share the same harness and therefore share rate limits, CLI state, or provider constraints.
_Avoid_: thread pool, multithreading, batch

**Task Failure**:
A benchmark run where the model or harness completed but the produced change did not satisfy build or test checks.
_Avoid_: crash, infrastructure error

**Infrastructure Failure**:
A benchmark run that could not be judged because prerequisites, credentials, CLI execution, timeout handling, or result recording failed.
_Avoid_: task failure, model quality failure


**Capability Mode**:
The measurement boundary that determines whether benchmark runs are comparable. `single_shot` runs use a frozen prompt with no tools and one model pass; `agent_iterated` runs give the harness tools, file access, and iteration. Runs are comparable within a capability mode, never across.
_Avoid_: prompt type, run type, harness mode

**Telemetry Trust**:
The recorded reliability of a benchmark run's cost and token fields: `exact` (single machine-read source such as an API usage object), `parsed` (extracted from a CLI JSON event stream), or `blank` (no machine-readable source available). Cost and tokens are comparable only within cohorts that share both capability mode and telemetry trust.
_Avoid_: confidence, accuracy, quality

**Benchmark Suite**:
The set of tasks used to probe model or model-plus-harness capability. The single-shot suite is the frozen 11-task set used for historical single-shot comparison; the agent suite is a separate, harder tier designed to discriminate among agent combinations on capability, not just efficiency.
_Avoid_: task list, test set, benchmark pack
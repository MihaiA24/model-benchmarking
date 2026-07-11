# Define the harness adapter and launch contract

**Status:** Final decision  
**Map:** [Design a real-world CLI benchmark for coding-agent harnesses](https://github.com/MihaiA24/model-benchmarking/issues/13)  
**Ticket:** [Define the harness adapter and launch contract](https://github.com/MihaiA24/model-benchmarking/issues/18)

## Accepted decisions

### Stock-profile boundary

Define each harness condition as an exact pinned CLI release or commit plus a versioned minimal configuration bundle, started with a fresh home directory and no user state.

The adapter may only:

- select the declared non-interactive mode and evaluated-repository working directory;
- deliver the frozen scenario instruction once;
- inject the common provider route, exact model identifier, and supported model settings;
- disable self-update and interactive approval;
- apply declared resource, provider, and credential-routing controls; and
- capture process output, exit status, timing, and declared artifacts.

Every override is explicit in the experiment manifest and included in the profile and adapter digests. The harness retains its own pinned system prompts, built-in tools, planning behavior, retries, compaction, memory behavior, and agent loop. The benchmark does not normalize those capabilities across harnesses.

If a harness cannot operate autonomously and safely under this boundary without a behavior-changing patch, treat that stock profile as infeasible. Do not silently modify it into a benchmark-specific agent.

### Responsibility split and lifecycle ownership

Keep the adapter too small to become a second benchmark runner:

- Provisioning installs and verifies the pinned CLI and stock profile before measured execution.
- The host-side experiment coordinator validates the adapter declaration and asks Harbor to start the trial.
- An immutable, non-writable launch shim inside the agent environment materializes only the declared configuration and then executes exactly one harness CLI.
- Harbor and the container runtime own external monitoring, budget enforcement, complete process-tree termination, teardown, and artifact collection.
- The shim performs no retries, prompt rewriting, tool mediation, model calls, task-success interpretation, or artifact sealing.

Provider calls, usage, and cost remain mandatory evidence, but accounting does not belong in the launch shim. The credential proxy records authoritative request counts and provider-reported usage outside the agent environment; the adapter preserves any native harness usage output as corroborating raw evidence. Cost is derived from authoritative usage using a versioned pricing record rather than trusted from harness output. [Define the run ledger and provenance schema](https://github.com/MihaiA24/model-benchmarking/issues/21) owns the exact accounting fields, provenance, reconciliation rules, and joins to trial identity.

### Completion semantics

The adapter reports process facts and never decides whether the scenario succeeded. Exit code zero means only that the harness CLI exited normally. A non-zero exit, crash, malformed or empty submission, or harness-initiated early exit is preserved as a valid harness outcome and is not automatically retried.

After every terminal outcome or enforced limit, Harbor terminates the complete process tree and captures the final evaluated-repository state and declared artifacts. Only the separate verifier determines functional correctness. Failures attributable to infrastructure before or outside harness execution retain the replacement-trial policy defined by the hermetic execution model; the adapter does not classify or retry them itself.

### Instruction delivery

Normalize the scenario instruction's content, not each CLI's transport. Store one canonical UTF-8 instruction and content digest per scenario, then give every harness exactly those bytes once through its documented native non-interactive mechanism: argument, standard input, or RPC request.

The adapter records the transport mode, effective redacted invocation, instruction digest, and successful-delivery event. It avoids shell interpolation and undeclared temporary paths. It adds no follow-up messages, synthetic tool responses, retries, or adapter-generated prompting. Any transformation performed internally by a stock harness remains harness behavior; record the limitation instead of compensating for it.

### Provider and model controls

Treat exact provider and model control as a preflight eligibility gate. The coordinator supplies one canonical provider/model configuration for each matched condition, and each adapter maps only explicitly supported fields into its harness. Before measured trials, qualification must demonstrate the effective provider endpoint, exact model identifier, and supported settings through configuration introspection plus credential-proxy observations.

A requested setting that is ignored, overridden, or remapped fails preflight. If every harness does not support a setting, remove it from the common comparison profile or place the compatible conditions in a separately labelled comparison stratum; never describe unequal effective configurations as paired identical conditions. When the provider exposes only a mutable model alias rather than an immutable model revision, record that limitation explicitly.

### Transparent credential proxy

The credential proxy is an accounting and control boundary, not an inference layer. It authenticates and routes only to the declared provider/model, enforces request, token, and spend ceilings, and records request timing, status, provider-reported usage, and the inputs needed for cost calculation.

It performs no retries, model fallback, response caching, prompt rewriting, parameter substitution, or response repair. Harness-native retries remain stock harness behavior and every resulting request and cost is counted. Record provider-internal retries or routing only when the provider exposes them; do not claim invisible behavior is known. Credential injection and any fail-closed compatibility exception retain the secret-handling rules from [Define the hermetic execution and integrity model](https://github.com/MihaiA24/model-benchmarking/issues/17).

### Common declarative adapter contract

Use one common Harbor integration driven by three versioned adapter declarations rather than three bespoke lifecycle implementations. Each declaration contains only:

- CLI, stock-profile, and adapter identities and digests;
- install and qualification evidence;
- invocation template, working directory, and instruction transport;
- allowlisted environment and configuration inputs;
- provider/model field mapping and authentication mode;
- native output and declared artifact locations;
- completion and shutdown characteristics; and
- supported and unsupported capability flags.

OMP, OpenCode, and Hermes may differ in these declarations and in their tiny immutable launch shims. They do not implement separate retry, monitoring, teardown, verification, or sealing behavior.

### Duration and termination

Elapsed time is observational only. The benchmark imposes no wall-clock deadline and does not terminate a harness for taking too long. Measure duration monotonically from launch until the complete process tree exits, retaining the relevant phase timestamps and provider-call timing for comparison.

Natural root-process exit ends the harness attempt; Harbor terminates any remaining descendants before capture. Hard host-safety, integrity, resource, or provider-spend controls may terminate the complete process group and record their specific cause. A suspected hang requires an explicit operator abort, is classified `aborted_operator`, is excluded from comparative analysis, and receives no automatic replacement. No adapter sends a harness-specific request to hurry, summarize, or finish.

### Adapter evidence envelope

Every adapter exposes the same mandatory raw process and proxy evidence:

- exact redacted invocation, working directory, allowlisted environment-variable names, and configuration digests;
- instruction-delivery event, transport, and content digest;
- raw standard output and standard error with timestamps;
- root exit code or signal and complete process-tree termination evidence;
- monotonic lifecycle and provider-call timings;
- credential-proxy request counts and provider-reported usage;
- final evaluated-repository capture and declared artifacts; and
- identities joining the evidence to its trial, adapter, stock profile, and provider/model condition.

Preserve native harness transcript, session, trajectory, and usage files opaquely when the stock CLI exposes them. These harness-specific files are optional because availability differs; record their absence without invalidating an otherwise complete trial. Missing mandatory common evidence is an infrastructure failure. Adapters do not translate native traces into a supposedly equivalent shared trace format during execution. [Define the run ledger and provenance schema](https://github.com/MihaiA24/model-benchmarking/issues/21) owns the field-level representation and reconciliation of this evidence.

### One process and fresh state per trial

Start one fresh harness process with a fresh home directory for every trial. OpenCode and Hermes use their native one-shot modes. OMP may use its documented RPC interface, but its adapter starts a fresh local RPC process, sends exactly one request with session persistence disabled, captures the response, and then shuts the process down.

No daemon, conversation, session database, warmed context, plugin state, mutable cache, or writable harness state crosses trial boundaries. Immutable installed binaries, package layers, and stock-profile inputs may be reused under their recorded digests; every writable materialization remains trial-local.

### Preparation and qualification

Each adapter supplies a reproducible trusted-build recipe and an unmeasured qualification probe. Before a stock profile becomes eligible, the resulting evidence must prove:

- the exact CLI artifact and dependency digests;
- the reported CLI version matches the declaration;
- the stock-profile configuration is generated deterministically and hashed;
- self-update and runtime installation are disabled;
- headless launch, workspace selection, credential proxying, exact model selection, and instruction delivery work;
- no measured trial requires package installation or external downloads; and
- one smoke scenario exits cleanly and produces the mandatory evidence envelope.

Image layering and cross-adapter reuse remain for [Set the benchmark architecture and reuse boundary](https://github.com/MihaiA24/model-benchmarking/issues/24). This contract defines the proof required from any chosen image layout rather than deciding that layout here.

### Non-interactive autonomy

When a stock CLI normally requests permission before using tools, use its native non-interactive approve-all behavior inside the disposable agent environment. External filesystem, network, credential, process, and resource boundaries provide safety; interactive prompts do not.

The adapter never answers approval prompts selectively or grants different scenario-level tool permissions by harness. If a CLI cannot autonomously use its normal coding capabilities without a human approval loop, that stock profile is ineligible.

### Tool-availability boundary

Give every harness the same scenario-declared operating-system toolchain and evaluated repository. Harness-native tools and orchestration remain part of the stock profile being compared; the adapters add no benchmark-specific plugins, MCP servers, skills, memories, system prompts, or convenience scripts to equalize those capabilities.

A scenario-required external service or tool must be declared at the scenario and environment level and exposed identically to all harnesses rather than injected by one adapter. [Define the scenario package and authoring protocol](https://github.com/MihaiA24/model-benchmarking/issues/19) owns that common declaration.

### Qualification failure

If one stock profile cannot pass the common qualification gate, do not substitute a different mode, patch its behavior, or weaken the matched condition. Mark the profile ineligible with the failed capability and its evidence. Diagnostic trials may continue only when clearly labelled and excluded from comparison.

Do not publish the intended three-way benchmark result until OMP, OpenCode, and Hermes each qualify for the same comparison profile. If an incompatibility is fundamental, amend the benchmark scope explicitly rather than quietly presenting a two-way result as the intended benchmark.

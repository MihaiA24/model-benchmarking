# Define the hermetic execution and integrity model

**Status:** Final decision
**Map:** [Design a real-world CLI benchmark for coding-agent harnesses](https://github.com/MihaiA24/model-benchmarking/issues/13)
**Ticket:** [Define the hermetic execution and integrity model](https://github.com/MihaiA24/model-benchmarking/issues/17)

## Accepted decisions

### Trust boundary

Treat the harness CLI and every model-controlled process as untrusted, potentially evaluator-aware code. They may act freely only inside the disposable agent environment.

Trust the benchmark host, experiment coordinator, pinned Harbor substrate, task package, and separate verifier environment. The benchmark does not claim to withstand a container or kernel escape from a malicious binary; host-runtime hardening is an infrastructure prerequisite rather than a measured harness capability.

The untrusted side receives no host Docker socket, writable host mounts, verifier assets, private checks, verifier credentials, or persistent cross-trial state. Targeted attempts against benchmark control boundaries and successful crossings are integrity violations that invalidate the trial rather than task-quality failures; ordinary operations denied by policy are recorded without automatically invalidating the observation.

### Runtime privilege

Install the pinned harness CLI and scenario dependencies while constructing the trusted image. Run every harness under the same unprivileged user, with write access limited to the evaluated repository and explicitly declared scratch and cache paths.

The measured profile grants no `sudo`, privileged container mode, additional Linux capabilities, host devices, host Docker socket, or writable host mount. A scenario that needs extra system software declares it as an image build input instead of installing it during a trial.

### Provisioning cache

Pre-pull and prebuild all required OCI images before measured trials. Resolve and record every image by digest; mutable tags are not valid trial inputs. Immutable image layers may be reused from the host's content-addressed cache, while each trial receives a fresh writable container layer and fresh declared volumes.

Launch fails before the trial starts if a required digest is unavailable. A measured trial performs no fallback image pull or package download, and the harness receives no access to the host image store or to a writable cache shared across trials.

### Network boundary

Default-deny network access during measured execution. The agent environment may reach only the declared model-provider route through a benchmark-controlled endpoint; it may not reach package registries, Git hosting, arbitrary web destinations, or undeclared DNS destinations.

External documentation, APIs, and datasets required by a scenario are either included as immutable scenario inputs or exposed through a versioned, read-only local mirror or sidecar. The verifier environment also defaults to no network. A remote verifier is an explicit scenario capability with its own isolated route and is never reachable from the agent environment.

### Secret injection

Keep provider credentials outside the agent environment. A benchmark-controlled credential proxy injects provider authentication, restricts traffic to the declared provider and model route, and gives each trial only an opaque short-lived token that is valid at that proxy.

If a stock harness cannot use the proxy, the scenario may declare a fail-closed exception for a least-privilege disposable credential. Inject it only at launch through ephemeral storage, scope it to one trial, suppress its value from logs and result bundles, and destroy it during teardown. Mark the trial `credential_exposed_to_harness`; never inject a long-lived personal credential. Because the harness controls processes inside its environment, an injected exception credential is not considered secret from the harness itself.

### Trial lifecycle and reset

Each trial follows one fail-closed, one-way lifecycle:

1. Preflight validates every declared digest, required runtime capability, resource limit, network rule, credential route, and output destination before creating measured state.
2. Harbor creates a unique agent environment and network, then materializes fresh writable copies of the evaluated repository and declared scratch volumes from immutable inputs.
3. The coordinator verifies the repository baseline and clean-state assertion before launching exactly one harness.
4. On normal exit or a limit, terminate the harness's complete process tree and stop the agent environment.
5. After the agent environment has stopped, capture the final repository state and declared submission artifacts.
6. Create a fresh verifier environment from immutable inputs, transfer only declared submission artifacts, and execute verification.
7. Collect lifecycle, agent, artifact, integrity, and verifier evidence; tear down all trial resources; then seal the result bundle.
8. Quarantine resources after incomplete teardown and prevent their reuse.

No container, writable volume, home directory, process, network namespace, or mutable cache survives into another trial. A failed preflight does not count as an experimental observation because measured execution never began.

### Resource controls

Each scenario declares one hard budget vector that applies unchanged to every harness condition: wall-clock deadline, CPU quota and core count, memory, process count, writable storage, and provider request, token, and monetary ceilings. Enforce provider-side ceilings at the credential proxy and environment limits through runtime capabilities qualified during preflight.

Do not oversubscribe a worker host during measured execution; run one measured trial at a time per worker in the initial benchmark. Crossing a limit terminates the complete process tree and records the specific exhausted budget as a valid experimental outcome, not as an infrastructure retry. Reject a configuration before launch when the selected runtime cannot enforce a declared limit rather than silently weakening the policy.

### Submission handoff and hidden checks

For coding scenarios, the canonical submission is a normalized Git patch derived by the trusted host after the agent environment stops. Generate it against the immutable evaluated-repository baseline, including tracked edits and explicitly allowed new files. Do not accept a patch supplied by the harness as authoritative.

Validate the handoff before verification. Reject path escapes, special files, unsafe symlinks, nested repositories or submodules, setuid or setgid bits, undeclared paths, and artifacts exceeding declared size limits. Apply the validated patch to a fresh baseline checkout inside the verifier environment. Transfer no agent home, cache, process state, container layer, or unrelated workspace content.

Keep hidden checks, expected outputs, private data, and verifier-only services exclusively in the verifier environment. Add them only after the submission is materialized. Execute submitted code as untrusted and unprivileged, with no secrets, default-deny networking, and independent verifier limits.

A scenario may declare a non-patch submission only when its required output cannot be represented faithfully as repository changes. It must define an explicit artifact allowlist, media type, size limit, digest, and safe materialization procedure that preserves the same isolation boundary.

### Mutation policy

Limit writable locations to the evaluated repository and declared scratch or cache paths. Keep the pinned harness executable and stock profile, experiment manifest, scenario instruction, image and runtime configuration, host clocks and monitors, credential proxy, verifier assets, and network policy outside the writable trial surface. Disable harness self-update, runtime plugin installation, and undeclared configuration drift; pin executable capabilities before launch.

A scenario may declare protected repository paths when modifying them would invalidate the task contract. Visible tests are not protected by default: changing them is realistic developer behavior, remains explicit in the host-derived patch, and cannot replace hidden acceptance and regression checks.

Record operations denied by filesystem, process, or network controls as integrity events. A successful mutation outside the declared writable surface invalidates the trial and quarantines affected resources.

### Integrity event levels

Classify integrity evidence by the boundary targeted and whether the control held:

- `policy_denial`: a routine undeclared operation such as package telemetry, a download, or a system-cache write was blocked. Preserve the event while allowing the trial to remain valid.
- `tampering_attempt`: an operation targeted verifier assets, host runtime, Docker control, credential-proxy internals, monitors, or benchmark policy. Terminate the trial and mark it `invalid_integrity` even when the control blocked it.
- `boundary_breach`: a protected boundary was crossed or mutated. Mark the trial `invalid_integrity`, quarantine affected resources, and pause the affected experiment batch for investigation.

### Trial dispositions and retries

Assign every planned trial exactly one top-level disposition:

- `not_started`: preflight rejected missing inputs, an unsupported enforcement capability, a baseline mismatch, or unavailable credentials or images. No experimental observation exists.
- `valid_completed`: the verifier ran and produced its declared score vector.
- `valid_harness_outcome`: the harness crashed or exited unsuccessfully, produced no or malformed submission, or caused a verifier-phase failure through its submission.
- `valid_limit_outcome`: a declared agent, provider, handoff, or verifier budget was exhausted.
- `invalid_infrastructure`: the host, Harbor, credential proxy, verifier infrastructure, evidence collection, teardown, or sealing failed independently of the submission.
- `invalid_integrity`: tampering, a boundary breach, hidden-evidence exposure, or contaminated inputs invalidated the observation.
- `aborted_operator`: an operator stopped the trial for an external reason.

Every disposition records the terminal phase, precise reason code, timestamps, raw supporting evidence, analysis eligibility, and retry disposition. Only `not_started` and `invalid_infrastructure` may receive a new linked replacement trial under a predeclared retry policy. Never silently replace a valid harness or limit outcome. Preserve every original record. Pause the affected batch after `invalid_integrity` and require investigation before resuming.

### Reproducibility normalization

Define and qualify worker profiles rather than claiming to eliminate external nondeterminism. Pin and validate CPU architecture and worker class; OS and kernel; container runtime; Harbor and image digests; locale, timezone, working directory, UID and GID, shell, and allowlisted environment; resource and network policy; and harness and model configuration. Do not pool results from materially different worker profiles.

Do not freeze wall-clock time because TLS, certificates, toolchains, and provider APIs depend on it. Record UTC timestamps instead. Record and set random seeds only where the stock harness or provider genuinely supports them; do not add behavior-changing wrappers that simulate determinism.

### Worker-host isolation

Run publishable benchmark trials only on a dedicated, disposable worker VM or an equivalent isolated worker. Do not colocate measured execution with a developer's repositories, personal credentials, SSH agent, cloud metadata access, or unrelated workloads and host mounts.

Provision the worker only with the pinned runtime, pre-cached immutable images, current experiment inputs, result destination, and network routes to declared control services such as the credential proxy. Mark developer-machine executions `development_only`; use them for smoke tests and proof gates but exclude them from benchmark analysis.

### Integrity monitoring and reuse

Collect required integrity evidence from outside the agent environment: lifecycle transitions and health checks; process exits, signals, and termination-tree outcomes; cgroup usage and limit events; allowed and denied network destinations plus credential-proxy usage totals; protected-boundary denials; repository baseline and final digests; submission validation; teardown; and bundle sealing. Use monotonic time for durations and UTC for event correlation. Do not capture network payloads, provider credentials, or additional model content solely for surveillance. Missing or interrupted mandatory monitoring makes the trial `invalid_infrastructure`.

Prefer Harbor v0.18.0's native lifecycle, result JSON, timings, errors, trajectory or recording, verifier logs, artifact collection, and artifact manifest. Add thin host-side collectors only for signals that the pinned Harbor release does not expose, using runtime-native Docker, cgroup, network, and credential-proxy evidence where appropriate.

Small monitoring components or patterns from other benchmark frameworks may be reused when their licenses are compatible, their revisions are pinned, they remain host-side and read-only, and proof gates validate them. Do not embed a second benchmark framework or duplicate Harbor's trial lifecycle merely to obtain telemetry.

### Secret-safe evidence capture

Register every injected token or credential value with a host-side streaming redactor before launch. Redact exact secret values from stdout, stderr, proxy headers, environment snapshots, errors, and collected artifacts before any persistent write. Record only secret names, scope, injection method, and redaction counts; do not persist credential values or reusable hashes of them. Preserve all non-secret evidence verbatim.

Keep canonical private-suite bundles access-controlled. Treat public or further-redacted exports as separately sealed derivatives that point back to the canonical bundle without exposing it. If unredacted secret material reaches persistent storage, classify the trial `invalid_infrastructure`, quarantine the bundle, revoke the affected credential, and investigate before continuing.

### Scenario sidecars and retained state

Pin every sidecar image and seed dataset by digest. Create a fresh sidecar and private network for each trial; never reuse writable database or service state. Expose only scenario-declared ports inside the trial network, never on the worker host. Complete health checks before measured execution begins; setup failure is `not_started`.

Stop agent-visible sidecars before verification. When verification needs a service, create a separate verifier-side instance from the same immutable seed or from a verifier-only seed when hidden data is required.

Always preserve host-captured sidecar logs. A scenario may also declare final-state exports collected after the agent stops and before teardown. Prefer logical exports such as SQL dumps, SQLite databases, schema snapshots, or declared query outputs over raw volume snapshots. Seal each export into the result bundle with its digest, byte length, media type, and sensitivity classification; never restore it into a later trial.

When sidecar state is the task submission, materialize the declared export in the separate verifier under the same safe-handoff rules. Failure to produce a mandatory export is `invalid_infrastructure`; preserve a missing-evidence marker for optional diagnostics without invalidating the trial. Harbor's declared and sidecar artifact facilities remain the storage lifecycle; add only scenario-specific export hooks.

## Qualification gates

Before this profile may produce publishable benchmark results, a qualification suite must prove all of the following:

1. Every required digest and clean-baseline assertion fails closed when mismatched.
2. Repeated trials receive fresh containers, volumes, networks, homes, and sidecars.
3. Harnesses run unprivileged and cannot reach host control surfaces or protected paths.
4. Only the credential proxy is reachable, and provider credentials never enter persisted evidence.
5. Wall-time, memory, storage, process, and provider-budget limits terminate and classify correctly.
6. A hidden marker is absent during the agent phase, the agent stops before verification, and only declared artifacts cross the boundary.
7. A normal patch verifies, while malicious paths, symlinks, special files, and oversized handoffs are rejected.
8. Sidecar state can be exported, sealed, verified, and destroyed without becoming future trial state.
9. Mandatory external monitoring detects policy denials, tampering attempts, and breaches; missing monitoring invalidates the trial.
10. Teardown failures quarantine resources, replacement trials retain lineage, and sealed bundles verify by digest.
11. At least one headless smoke trial for each of OMP, OpenCode, and Hermes passes every applicable gate.

Failure of core isolation, reset, policy enforcement, or artifact handoff triggers the Harbor fallback review established by the substrate decision. Failure isolated to one CLI adapter remains an adapter finding rather than a substrate failure.

## Downstream contracts

- [Define the harness adapter and launch contract](https://github.com/MihaiA24/model-benchmarking/issues/18) must express the unprivileged launch, proxy-first authentication, complete process-tree termination, and pinned stock-profile behavior for each CLI.
- [Define the scenario package and authoring protocol](https://github.com/MihaiA24/model-benchmarking/issues/19) must declare immutable images and seeds, writable and protected paths, sidecars, artifact handoffs, budgets, networks, and verifier capabilities.
- [Define the run ledger and provenance schema](https://github.com/MihaiA24/model-benchmarking/issues/21) must represent worker qualification, lifecycle phases, policy and integrity events, dispositions, replacement lineage, monitoring completeness, redaction, and sidecar exports.
- [Set the benchmark architecture and reuse boundary](https://github.com/MihaiA24/model-benchmarking/issues/24) must prefer Harbor-native evidence and introduce only thin host-side collectors and export hooks for demonstrated gaps.

No additional Wayfinder ticket is needed: these responsibilities already belong to the named downstream decisions, while implementing and executing the qualification suite remains outside this map's planning destination.

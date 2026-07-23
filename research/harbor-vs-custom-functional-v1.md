# Native Harbor vs. the custom Functional V1 coordinator

**Status:** Verified research note
**Reviewed:** 2026-07-22
**Purpose:** Decide what the repository's eight-line native Harbor job can replace, what the custom Functional V1 layer still guarantees, and what can responsibly be said about speed.

## Executive answer

Native Harbor and the custom Functional V1 coordinator share an execution kernel, but they are **not behaviorally equivalent**.

The custom path does not reimplement a Trial: for every Functional V1 cell it invokes pinned Harbor's `harbor trial start`, uses the same Scenario Package task, and consumes Harbor's Trial result (`src/model_benchmark/runtime/execution.py:1617-1872`). Native Harbor therefore remains the sandbox/agent/verifier runner. The custom layer adds a different benchmark contract around that runner: a fixed 12-cell matrix, one-attempt fixed-width scheduling, content-addressed condition and package locks, preflight and worker constraints, a per-Trial Credential Proxy, trusted capture interpretation, evidence redaction and sealing, benchmark-specific dispositions, immutable provenance, and narrow resume (`src/model_benchmark/runtime/functional_v1.py:36-61,240-405,655-795`; `src/model_benchmark/runtime/execution.py:1102-1187,2388-2709`).

The native job is the better minimal mechanism for ordinary Harbor evaluation and for proving that these tasks remain valid Harbor tasks. It is **not** currently a replacement for Functional V1 acceptance. In particular, direct native-agent execution is not yet live-model parity: the committed tasks default to `no-network`, the direct YAML does not add the Credential Proxy route, and its omitted agent resolves to Harbor's Oracle, not the four pinned Functional V1 conditions (`scenarios/calibration/*/task.toml`; `harbor-functional-v1.yaml:1-8`; pinned Harbor [`AgentConfig`](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/models/trial/config.py#L45-L149)).

No same-task live-agent A/B timing exists. The only measured native evidence is one Oracle smoke Trial; it cannot rank native Harbor against the custom coordinator for warm throughput or live-model speed.

## Compared systems and revision

- **Native Harbor:** the dependency pinned by this repository to commit [`527d50deb63a5d279e8c20593c18a2cbc7f61f9e`](https://github.com/harbor-framework/harbor/tree/527d50deb63a5d279e8c20593c18a2cbc7f61f9e) (`pyproject.toml:8-13`), driven directly by `harbor-functional-v1.yaml:1-8`.
- **Custom Functional V1:** the repository CLI/runtime that wraps one pinned Harbor Trial per cell. The fixed domain is three scenarios × four conditions with maximum width three (`src/model_benchmark/declarations/functional_v1.py:36-43`; `src/model_benchmark/runtime/functional_v1.py:50-61`).
- **Terminology:** “native” below means Harbor's own `Job`/`TrialQueue` behavior without the Functional V1 coordinator. “Custom” means the repository-owned protocol around Harbor, not a different sandbox runner.

## Capability matrix

| Concern | Native Harbor at the pin | Custom Functional V1 | Relationship |
|---|---|---|---|
| Task | A task supplies instruction, environment, and verifier/test configuration; local task paths are valid job inputs. `Job` resolves tasks, then expands them into Trial configs ([`Job.create` and `_resolve_task_configs`](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/job.py#L125-L163), [`TaskConfig`](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/models/trial/config.py)). | Uses those same task directories, but first resolves locked Scenario Packages, builds/checks pinned runtime images, and projects an execution package (`src/model_benchmark/runtime/execution.py:984-1019,2204-2340`). | **Same Harbor task kernel; stricter inputs before launch.** |
| Planned unit | Arbitrary tasks/datasets × agents × `n_attempts`; the nested expansion is explicit in pinned `Job._init_trial_configs` ([source](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/job.py#L368-L389)). | Operator execution is exactly 3 scenarios × OMP/OpenCode/Hermes/Raw API = 12 cells, one attempt each; partial schedules exist only for internal qualification (`src/model_benchmark/runtime/functional_v1.py:50-61`; `src/model_benchmark/runtime/execution.py:90-105`; `docs/functional-v1-runbook.md:64-67,143-152`). | **Different.** A Harbor job is general; a Functional V1 Run is a fixed acceptance unit. |
| Agent | Built-ins and custom `module:Class` import paths are supported by the pinned factory ([`AgentFactory`](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/agents/factory.py#L19-L184)). Omitted agent configuration defaults to Oracle ([`AgentConfig.set_default_name`](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/models/trial/config.py#L45-L149)). | Uses Harbor's supported installed-agent seam, but one repository adapter dispatches only a selected, image-mounted condition entrypoint and checks its artifact identity (`src/model_benchmark/runtime/adapters/functional_v1.py:15-118`; launch at `src/model_benchmark/runtime/execution.py:1681-1728`). | **Native extension seam, different agent payload and identity contract.** |
| Concurrency | `TrialQueue` has a job-wide semaphore and optional per-agent/shared-group semaphores; `n_concurrent_trials` defaults to four and is configurable ([job config](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/models/job/config.py#L287-L456), [queue](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/trial/queue.py#L21-L274)). | A `ThreadPoolExecutor` is fixed to `MAX_PARALLEL = 3`, preserves fixed submission order, and stops admitting work after a global fault (`src/model_benchmark/declarations/functional_v1.py:36-43`; `src/model_benchmark/runtime/execution.py:1102-1187`). A nonblocking coordinator lease permits only one coordinator in one managed home (`src/model_benchmark/runtime/functional_v1.py:251-287`). | **Different scheduling policy.** Same maximum width in the committed native YAML only because it sets three. |
| Retry | Native Harbor has configurable exception-filtered retries and exponential backoff; default `max_retries` is zero ([`RetryConfig`](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/models/job/config.py#L287-L319), [`TrialQueue._execute_trial_with_retries`](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/trial/queue.py#L194-L251)). | One attempt per cell; no transparent retry. A fresh repeat mints a fresh Run ID (`docs/functional-v1-runbook.md:157-164`). | **Different.** Functional V1 preserves the observed outcome rather than retrying it away. |
| Network policy | Harbor natively resolves phase-scoped `public`, `no-network`, and `allowlist` policies, with environment baselines and agent/verifier overrides ([task policy model](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/models/task/config.py#L36-L287), [resolution](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/trial/network_policy.py)). The three committed tasks declare no network for environment, agent, and verifier (`scenarios/calibration/*/task.toml`). | Reuses Harbor's allowlist primitive but adds an internal `proxy-only` network, a separate provider-egress network, Harbor's egress-control sidecar, and an explicit `--allow-agent-host credential-proxy`; only the proxy holds the real key (`src/model_benchmark/runtime/execution.py:1254-1333,1617-1761`). Preflight is run while the dedicated worker uplink is down (`docs/functional-v1-runbook.md:14-45,78-91`). | **Native primitive plus custom topology and operational policy.** Direct YAML does not create live-model reachability. |
| Credential and provider route | Harbor can pass agent environment and records whatever token/cost context the agent returns; it does not, by these core models, derive or enforce a provider budget ([`AgentContext`](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/models/agent/context.py), [`JobStats.increment`](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/models/job/result.py#L18-L235)). | Gives the condition an opaque per-Trial token, rejects wrong route/model/auth/request form, substitutes the real credential only at the proxy, serializes durable redacted events, and enforces request/token/cost stop conditions after a response (`src/model_benchmark/runtime/credential_proxy.py:62-212,354-399,491-765`; `docs/functional-v1-runbook.md:47-56,134-141`). | **Different trust and budget boundary.** |
| Locks/provenance | Harbor writes `config.json`, `lock.json`, and `result.json`; its lock covers resolved task digest, agent, skills, environment, verifier, extra compose, retry/concurrency, and Harbor version/commit ([pinned lock model](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/models/job/lock.py#L39-L246)). | Retains Harbor evidence and additionally stores immutable source/resolved manifests, typed Scenario and condition locks (including a separately loadable Raw API condition lock), preflight/provisioning provenance, per-cell records, Result Bundle identities, and a Run Record identity (`src/model_benchmark/runtime/raw_api_locks.py:27-60`; `src/model_benchmark/runtime/functional_v1.py:141-187,289-399,655-795`; `src/model_benchmark/runtime/execution.py:1952-1970`). | **Native lock retained; custom chain is broader and write-once.** |
| Qualification | A native job can run Oracle/NOP and verifiers, but ordinary `Job.run` does not impose this repository's qualification ceremony. | Before acceptance, package qualification executes named baseline, hidden-marker, two-reference-attempt, malformed, unsafe, and score-mismatch checks; it rejects downloads/drift and publishes a worker-signed canonical qualification record (`src/model_benchmark/runtime/scenario_qualification.py:1774-2165`). | **Project-owned gate, not native job behavior.** |
| Capture | Harbor collects task-declared artifacts. The official viewer can browse them ([official output/viewer docs](https://www.harborframework.com/docs/run-jobs/run-evals#analyzing-results)). The committed tasks themselves invoke the trusted capture sidecar, so both paths can produce its raw `capture.json` and patch (`scenarios/calibration/*/task.toml`). | Interprets capture status as a benchmark handoff, validates mandatory artifacts, scans/redacts secrets, quarantines leakage, inventories bytes/digests, and seals the bundle (`src/model_benchmark/evidence/capture.py:24-40,55-170,205-250,312-443`; `src/model_benchmark/runtime/bundles.py:60-162,396-600,647-755,758-943`). | **Same task-side capture can run; custom host-side acceptance and sealing are additional.** |
| Result semantics | Trial result contains rewards/error plus phase timestamps and nullable agent-reported token/cost fields; job result aggregates counts, metrics, pass@k, tokens, and cost ([trial model](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/models/trial/result.py), [job model](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/models/job/result.py)). | Maps Harbor/proxy/capture evidence into `valid_completed`, `valid_limit_outcome`, `valid_harness_outcome`, `invalid_infrastructure`, or `invalid_integrity`; a valid complete Run requires all 12 terminal cells, valid evidence, and Result Bundle identities (`src/model_benchmark/runtime/functional_v1.py:36-49,655-769`; `src/model_benchmark/runtime/bundles.py:647-755`). | **Different authority and validity semantics.** |
| Resume | Reopening a matching job directory loads parseable completed Trial results, removes directories with no result, rejects config mismatch/unmatched existing Trial config, and schedules only missing Trial configs ([`Job._maybe_init_existing_job` and `_init_remaining_trial_configs`](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/job.py#L210-L331)). | A sealed Run resumes as deterministic inspect. An unsealed Run cleans owned resources, seals recoverable evidence, permanently terminalizes any started cell missing a terminal record as infrastructure-invalid, and launches only never-started cells (`src/model_benchmark/runtime/execution.py:2649-2709`; `docs/functional-v1-runbook.md:157-166`). | **Different.** Native resume is missing-Trial completion; custom resume is deliberately narrower and never reruns a started cell. |
| Output | Standard mutable job/trial directories contain config, lock, results, agent files, verifier files, logs, and collected artifacts. Harbor's viewer exposes rewards, timings, tokens, errors, trajectories, artifacts, and comparisons ([official docs](https://www.harborframework.com/docs/run-jobs/run-evals#analyzing-results)). | Preserves selected Harbor outputs inside a content-addressed bundle, adds proxy/capture/coordinator evidence and immutable Run Record, then produces deterministic read-only JSON/Markdown/static-HTML reports with `authority: none` (`src/model_benchmark/runtime/bundles.py:60-162,556-600`; `docs/functional-v1-runbook.md:102-105,168-214`). | **Different output contract; complementary inspection surfaces.** |

## Behavioral differences that matter

### Fixed acceptance versus general evaluation

The native job compiler intentionally supports broad Cartesian evaluation. At the pin, `Job._init_trial_configs` loops attempts, tasks, then agents, while `TrialQueue` applies configured concurrency. Functional V1 instead fixes schedule identity and ordering in code and records that full schedule in an immutable workspace header (`src/model_benchmark/runtime/functional_v1.py:50-61,351-399`). This is why a nine-Trial native Oracle job and a 12-cell Functional V1 Run are not two serializations of the same experiment.

### Fault and retry semantics

Native Harbor can retry selected exceptions and replace a prior attempt's contribution to aggregate stats ([queue](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/trial/queue.py#L194-L251), [job update](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/job.py#L463-L520)). Functional V1 performs one attempt, cancels siblings and stops admission for a global infrastructure/integrity fault, terminalizes the remaining matrix with the shared cause, and seals an invalid/incomplete record rather than silently substituting a later attempt (`src/model_benchmark/runtime/execution.py:1102-1187,2421-2647`). Neither policy is universally “better”; they answer different experimental questions.

### Provider authority and cost

Harbor's core result models faithfully aggregate an agent's `AgentContext`, whose token and USD fields are optional. That is why an Oracle Trial correctly reports all four as null. This is result accounting, not a provider enforcement boundary ([`AgentContext`](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/models/agent/context.py), [`TrialResult.compute_token_cost_totals`](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/models/trial/result.py#L71-L111)).

Functional V1 derives exact Decimal input/output cost from sealed rates when possible, records provider-reported cost separately, and requires successful responses to supply the expected model, usage, and accountable cost. Request count is checked before forwarding; token and cost thresholds are necessarily checked after a response, and any overshoot is explicitly recorded (`src/model_benchmark/runtime/credential_proxy.py:62-89,541-592,683-765`). The run record then carries provider request/token/cost summaries rather than trusting only an adapter's self-report (`src/model_benchmark/runtime/execution.py:1428-1513`; `src/model_benchmark/runtime/functional_v1.py:703-726`).

### Network and secret boundary

The native mechanism already has the right phase-aware network vocabulary. The difference is the policy instance: these tasks are `no-network`, so a direct live agent cannot reach its provider. Functional V1 gives the main service only one allowed host—the per-Trial proxy—and splits the proxy across an internal agent-facing network and provider-egress network. The real key appears only in the proxy service environment; raw evidence is copied with both real key and opaque token redacted (`src/model_benchmark/runtime/execution.py:1254-1333,1388-1426,1617-1761`). Therefore “Harbor supports network allowlists” does not imply “the direct YAML reproduces Functional V1 isolation.”

### Capture and authority

Task-side capture is not unique to the coordinator: it is declared in each task and therefore ran in the Oracle smoke. The custom authority begins after that: it distinguishes missing/malformed/rejected/no-op/patch handoffs, verifies the patch digest and mandatory evidence, preserves diagnostics, redacts or quarantines secrets, seals a read-only inventory, and reconciles capture integrity ahead of ordinary outcome semantics (`src/model_benchmark/runtime/bundles.py:396-600,647-755,758-943`). A native reward of 1.0 proves verifier success for that Trial; a valid Functional V1 cell additionally proves the repository's evidence boundary was satisfied.

### Implementation surface is not runtime speed

For scale only, `wc -l` on the compared repository surfaces is 8 lines for `harbor-functional-v1.yaml`, versus 4,364 lines across `runtime/execution.py` (2,712), `runtime/credential_proxy.py` (813), `runtime/adapters/functional_v1.py` (118), and `declarations/functional_v1.py` (721), or 4,372 including the YAML. This is an **implementation-surface illustration**, not total-project LOC, maintainability scoring, or runtime-speed evidence. Much of the custom surface implements contracts absent from the eight-line job rather than a slower spelling of native Job orchestration.

## Speed, startup, throughput, and resume

### Independently confirmed local measurement

The local smoke artifact `/tmp/model-benchmark-harbor-smoke/spring-petvalidator/spring-petvalidator-whitespace__DZyDMLZ/result.json` was read directly on 2026-07-22. Its timestamps yield:

| Measured interval | Duration |
|---|---:|
| Trial `started_at` → `finished_at` | 48.794987 s |
| `environment_setup` | 7.904905 s |
| `agent_setup` | 0.000089 s |
| `agent_execution` | 0.558971 s |
| `verifier` | 17.725306 s |
| Time outside those four phase intervals | 22.605716 s |

The largest un-attributed interval is 22.416500 s between agent-execution finish and verifier start. The result does not label that interval, so this note does not rename it “capture,” “teardown,” or anything else. The Trial was Oracle (`model_info: null`), used no tokens/cost, had no exception, and produced `acceptance_score`, `regression_score`, `task_success`, and `validation_behavior` all equal to 1.0.

The job-level `result.json` is deliberately excluded from elapsed-time measurement: a later resume rewrote job `finished_at`, so subtracting job timestamps would include idle time. This is consistent with pinned `Job.run`, which preserves the original `started_at` but assigns a fresh `finished_at` at the end of each invocation ([source](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/job.py#L733-L859)).

### Phase-by-phase expectations, not measurements

| Phase | Expected qualitative effect | Evidence and limit |
|---|---|---|
| Config resolution / startup | Native Job should have less protocol startup work: it resolves tasks and creates Trial configs in one process. Custom `run` first checks pricing, takes leases, reruns preflight, verifies inventory, creates immutable workspace state, and writes provenance. | Architectural expectation from pinned [`Job.create`](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/job.py#L125-L163) versus `src/model_benchmark/runtime/execution.py:2388-2429`; no A/B time. |
| Provisioning / environment setup | Native can schedule Trials inside one Job and reuse Harbor/Docker caches. Functional V1 has an explicit idempotent provisioning phase, then starts a separate Harbor CLI process and per-cell proxy/overlay services for each cell. Warm content-addressed images avoid rebuilding, but process/service and validation work remain. | `docs/functional-v1-runbook.md:69-94`; `src/model_benchmark/runtime/execution.py:1617-1770`; no warm-run comparison. |
| Agent execution | The 0.559 s smoke interval is Oracle copying the reference solution, not a live model. Functional V1 conditions start pinned CLI/raw materializers, traverse the proxy, validate every request/response, and fsync evidence. Those controls add work, while actual provider and harness latency may dominate. | Measured Oracle artifact plus `src/model_benchmark/runtime/credential_proxy.py:354-399,491-765`; no live-agent native comparator. |
| Capture / verifier / sealing | Both paths run the task-declared capture and separate verifier. Custom then copies/redacts raw evidence, validates the handoff, constructs an inventory, hashes artifacts, makes them read-only, and seals cell and Run identities, so additional post-Trial work is expected. | Task manifests; `src/model_benchmark/runtime/bundles.py:758-943`; the smoke's un-attributed gap cannot isolate capture cost. |
| Scheduling throughput | Native Harbor uses one async queue with a global semaphore and can also limit only agent phases. Custom runs up to three independent Harbor child processes and halts the matrix on a global fault. The native architecture plausibly has less coordinator/process overhead; custom may overlap three full cells. | Pinned [`TrialQueue`](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/trial/queue.py) versus `src/model_benchmark/runtime/execution.py:1102-1187`; no numerical ranking. |
| Resume | Native efficiently omits completed matching Trial configs. Custom deliberately pays cleanup, evidence draining, input/pricing/preflight verification, and reruns only never-started cells; started cells become terminal invalid evidence. Sealed custom resume is cheap read-only inspect. | Pinned [`Job` resume loading](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/job.py#L210-L331); `src/model_benchmark/runtime/execution.py:2649-2709`. |

### Why aggregate wall times are not comparable

The committed native YAML describes three tasks × one default Oracle agent × three attempts = **nine planned Trials**, with concurrency three (`harbor-functional-v1.yaml:1-8`; pinned expansion in [`Job._init_trial_configs`](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/job.py#L368-L389)). The custom operator unit is three tasks × four live conditions × one attempt = **12 cells**, also width three (`src/model_benchmark/runtime/functional_v1.py:50-61`). Different work, agents, request paths, evidence, and resume policies make total job/run duration an invalid speed comparison even if both numbers become available.

## Output and cost consequences

### Native Harbor output

At the pinned revision, `Job` writes progress/final job `result.json` repeatedly and each Trial has its own result and agent/verifier directories ([`Job._write_job_result`](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/job.py#L476-L492)). Current first-party documentation describes the normal `jobs/<job>/config.json`, `lock.json`, `result.json`, and per-Trial result/agent/verifier/artifact layout and the viewer's reward, duration, token, trajectory, timing, and comparison views ([official Evals documentation](https://www.harborframework.com/docs/run-jobs/run-evals#analyzing-results)). These are operational evaluation artifacts. The core does not make them canonical write-once Functional V1 authority.

### Custom Functional V1 output

Each cell's bundle inventories the coordinator execution record, Harbor result/log/collect manifest, capture record/patch, verifier structured result/reward, proxy NDJSON, overlay, and eligible diagnostics (`src/model_benchmark/runtime/bundles.py:60-162,758-943`). The Run Record embeds typed identities, per-cell disposition, scores, cost, duration, token/request totals, provenance, and hashes of start/terminal records, then receives its own content identity (`src/model_benchmark/runtime/functional_v1.py:655-769`). `inspect` revalidates record identity on every read; downstream reports are deterministic and explicitly non-authoritative (`docs/functional-v1-runbook.md:157-173,181-214`).

### Cost interpretation

- **Native:** token/cost totals are nullable sums of what the selected agent returned in `AgentContext`; Oracle correctly yielded nulls ([source](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/models/job/result.py#L18-L235)).
- **Custom:** the proxy records input/output/provider tokens per response, derives Decimal USD at a sealed pricing identity, retains provider-reported USD separately, records explicit overshoot, and blocks later calls after request/token/cost limits (`src/model_benchmark/runtime/credential_proxy.py:62-89,683-765`). This evidence feeds cell and Run summaries (`src/model_benchmark/runtime/execution.py:1428-1513`; `docs/functional-v1-runbook.md:102-105,134-141`).

These figures may agree for an adapter that reports the same complete usage under the same rates, but agreement is not guaranteed and **behavioral equivalence is not claimed**: their authority, precision, missing-data behavior, and enforcement points differ.

## What the minimal branch proves

Only two claims are established:

1. `harbor-functional-v1.yaml:1-8` is a valid minimal native-job description of the three existing task paths, three attempts, and concurrency three. Under the pinned default single Oracle agent and Harbor's task × agent × attempt expansion, that is nine planned Trials.
2. A separate one-task/one-attempt native Harbor Oracle smoke completed `spring-petvalidator-whitespace` end to end. Its Trial result had no exception, all four rewards equal to 1.0, and total elapsed time 48.794987 s with the phase intervals reported above.

It does **not** prove:

- that the full nine-Trial YAML job completed;
- live OpenCode, Hermes, OMP, or Raw API execution;
- that a direct native agent can reach the provider under the tasks' `no-network` policy;
- the per-Trial proxy credential, exact-model route, token/request/cost enforcement, or pricing provenance;
- all-four-condition/full-12-cell parity;
- qualification, Result Bundle, Run Record, disposition, immutable-provenance, or narrow-resume parity; or
- any comparative speed ranking.

## Decision guidance

1. **Keep the custom Functional V1 path for benchmark acceptance and comparable Run Records.** Its extra work is the accepted protocol, not incidental orchestration.
2. **Use native Harbor jobs for task compatibility smoke, Oracle/reference checks, ordinary agent evaluation, Harbor viewer workflows, and experiments that do not claim Functional V1 authority.** The eight-line config is valuable precisely because it exposes the underlying Harbor capability with almost no project code.
3. **Do not publish native-agent results as Functional V1 cells yet.** Live-model parity requires, at minimum, the same pinned condition artifact, proxy-only route/credential boundary, fixed model and budgets, trusted handoff, evidence inventory/redaction, validity semantics, and provenance.
4. **Measure before optimizing.** A defensible performance study needs the same task, same live condition/model/provider route, warm/cold state declaration, equal attempt count/concurrency, and phase timestamps around custom preflight, Harbor Trial, proxy/capture, bundle sealing, and cleanup. Until then, retain only the qualitative expectations above.
5. **If simplification is pursued, migrate invariants one by one onto Harbor-supported seams rather than deleting the coordinator wholesale.** Harbor already supplies task execution, import-path agents, network policy, lock data, queueing, results, and viewer; the remaining question is whether the project-owned authority controls can be expressed without weakening them.

## Primary sources

### Official Harbor, exact pinned commit where possible

- [Harbor repository at `527d50d`](https://github.com/harbor-framework/harbor/tree/527d50deb63a5d279e8c20593c18a2cbc7f61f9e)
- [`Job`: Trial expansion, lifecycle, persistence, and resume](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/job.py)
- [`JobConfig` and `RetryConfig`](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/models/job/config.py)
- [`TrialQueue`: concurrency and retry](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/trial/queue.py)
- [`AgentConfig`](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/models/trial/config.py) and [`AgentFactory`](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/agents/factory.py)
- [Task network policy model](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/models/task/config.py) and [phase policy resolution](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/trial/network_policy.py)
- [`JobLock`](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/models/job/lock.py), [`TrialResult`](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/models/trial/result.py), [`JobResult`](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/models/job/result.py), and [`AgentContext`](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/models/agent/context.py)
- [Official Evals/output/viewer documentation](https://www.harborframework.com/docs/run-jobs/run-evals)

### Repository sources

- Harbor pin and native config: `pyproject.toml:8-13`; `harbor-functional-v1.yaml:1-8`
- Fixed declaration/operator contract: `src/model_benchmark/declarations/functional_v1.py:36-43`; `src/model_benchmark/runtime/functional_v1.py:36-61,240-795`; `docs/functional-v1-runbook.md:1-214`
- Coordinator/Harbor seam/provenance/resume: `src/model_benchmark/runtime/execution.py:447-508,1102-1187,1190-1970,2388-2709`
- Installed-agent seam: `src/model_benchmark/runtime/adapters/functional_v1.py:15-118`
- Credential and cost boundary: `src/model_benchmark/runtime/credential_proxy.py:62-212,354-765`
- Raw API lock: `src/model_benchmark/runtime/raw_api_locks.py:27-60`
- Qualification: `src/model_benchmark/runtime/scenario_qualification.py:1774-2165`
- Capture and sealed outputs: `src/model_benchmark/evidence/capture.py:24-443`; `src/model_benchmark/runtime/bundles.py:60-162,396-943`
- Task network/capture declaration: `scenarios/calibration/*/task.toml`
- Local measured smoke: `/tmp/model-benchmark-harbor-smoke/spring-petvalidator/result.json` and its child `spring-petvalidator-whitespace__DZyDMLZ/result.json` (observed 2026-07-22; not a committed artifact)

## Evidence limits

- The smoke is local, single-Trial, Oracle-only evidence. Its `/tmp` path is ephemeral and is not provenance suitable for a published benchmark result.
- No preserved custom-run wall-clock record was accessible, and no native live-agent Trial using the same task/model/provider/limits was measured. Consequently this note reports no speedup, slowdown, throughput ratio, or cost ratio.
- Harbor's exact-commit source is authoritative for pinned behavior. The official web documentation is first-party but may describe a newer deployment; it is used only for the stable output/viewer surface and is not allowed to override exact-commit source.
- The source-line count compares only the named coordinator subset with the native YAML. It excludes the rest of both Harbor and this repository and says nothing about runtime performance.
- Native Harbor is configurable enough to reproduce some individual controls. This note compares the committed direct YAML and current custom implementation; it does not claim those controls are impossible to build as future Harbor plugins, hooks, or agents.
- A successful Oracle reference application demonstrates task/environment/verifier compatibility, not that an autonomous live model can solve the task or that its trajectory, network, cost, capture, and failure behavior matches Functional V1.

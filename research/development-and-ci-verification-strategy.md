# Review and optimize development verification with caching, concurrency, and explicit fresh gates

**Status:** Accepted research resolution
**Decision date:** 2026-07-14
**Ticket:** [Review and optimize development verification with caching, concurrency, and explicit fresh gates](https://github.com/MihaiA24/model-benchmarking/issues/53)
**Implementation evidence:** [`011c29c37d55e2c19139f9e8b26b67135657fce8`](https://github.com/MihaiA24/model-benchmarking/commit/011c29c37d55e2c19139f9e8b26b67135657fce8)

## Decision

Adopt three explicit verification tiers and make the tier part of the command, CI job, output namespace, and result metadata:

1. **Development** is the default. Run only affected unit, schema, architecture, canonicalization, and pure contract tests. It must not require Docker, contact a provider, invoke a model, or publish an authoritative acceptance artifact.
2. **Cached integration** is opt-in for a changed Harbor, image, capture, verifier, or packaging boundary. Reuse only digest-verified immutable inputs; give every test fresh writable state and a unique output root. Its results are diagnostic and cannot satisfy an issue acceptance gate.
3. **Fresh authoritative qualification** runs the complete ordered issue gate—including its exact issue-owned acceptance command and every companion—in a clean checkout on an eligible worker. It executes every mandatory case, creates all required fresh Harbor environments, rejects skips and partial selection, and lets the trusted runner publish one sealed current-head envelope over every child outcome. Run it only for an explicit merge, deployment, release, manual qualification, or validity-critical change.

This policy changes development and CI orchestration only. It does **not** change measured benchmark execution: every measured Trial remains a single-cell Harbor job with `n_attempts = 1`, `n_concurrent_trials = 1`, fresh writable state, sequential scheduling on one qualified worker, no fallback pull/build/download, and canonical evidence sealed only after complete read-back.

## Evidence and observed cost

The accepted architecture already separates four proof layers: Docker-free unit/schema conformance, Harbor contract tests, runtime fault-injection qualification, and end-to-end Calibration qualification ([architecture, lines 176–185](../blueprint/benchmark-architecture-and-reuse-boundary.md#architectural-proof-gates)). It also permits reuse only for immutable image bytes while requiring fresh writable Trial state ([architecture, lines 21–36](../blueprint/benchmark-architecture-and-reuse-boundary.md#immutable-image-composition-and-reuse); [hermetic execution, lines 24–28](../blueprint/hermetic-execution-and-integrity.md#provisioning-cache)).

Current implementation evidence at `011c29c`:

- the exact [Implement Scenario Package and standard-v1 authoring tooling](https://github.com/MihaiA24/model-benchmarking/issues/29) gate recorded **19 passed in 356.10 s** and the root suite recorded **131 passed in 468.73 s** in its live handoff;
- a fresh local unit-only profile on 2026-07-14 recorded **83 passed in 27.66 s** (`28.02 s` wall, `53.3 MiB` maximum resident set);
- an independent clean archive added timing options to the complete Scenario Package issue path and recorded **19 passed in 357.61 s** (`360.19 s` wall, `71.7 MB` maximum resident set); because the outer invocation differed from the published gate, this is diagnostic rather than authoritative. One production-qualification case consumed **344.29 s**—`96.3%` of the run, or an average `49.18 s` across its seven required fresh environments—while every other case was below `2.35 s`; the generated child checksum verified before the temporary copy was removed;
- the clean archive's warm `uv sync --frozen` built the project wheel in `396 ms` and installed 86 locked packages in `342 ms`, confirming that dependency setup is not the dominant warm-cache cost;
- the authoritative artifact inventories all 19 mandatory cases and records the observed launcher plus source, lock, schema, Python, and Docker identities, but intentionally records no benchmark result or model call ([verification artifact](https://github.com/MihaiA24/model-benchmarking/blob/011c29c37d55e2c19139f9e8b26b67135657fce8/artifacts/acceptance/issue-29/verification.json));
- the acceptance plugin forbids partial issue-path selection, detects deselection/skips/xfail, removes stale authoritative outputs, and publishes only after the complete inventory passes ([plugin, lines 223–296](https://github.com/MihaiA24/model-benchmarking/blob/011c29c37d55e2c19139f9e8b26b67135657fce8/src/model_benchmark/evidence/pytest_acceptance.py#L223-L296), [lines 299–350](https://github.com/MihaiA24/model-benchmarking/blob/011c29c37d55e2c19139f9e8b26b67135657fce8/src/model_benchmark/evidence/pytest_acceptance.py#L299-L350), and [lines 436–469](https://github.com/MihaiA24/model-benchmarking/blob/011c29c37d55e2c19139f9e8b26b67135657fce8/src/model_benchmark/evidence/pytest_acceptance.py#L436-L469));
- Scenario Package provisioning unconditionally runs `docker pull` for every locked image before invoking Harbor, even when the digest already exists locally ([runtime, lines 157–204](https://github.com/MihaiA24/model-benchmarking/blob/011c29c37d55e2c19139f9e8b26b67135657fce8/src/model_benchmark/runtime/scenario_qualification.py#L157-L204));
- measurement first verifies local digest-pinned images, then starts baseline, hidden-marker, two Reference, malformed, unsafe, and score-mismatch phases in sequence and proves seven distinct environments ([runtime, lines 626–747](https://github.com/MihaiA24/model-benchmarking/blob/011c29c37d55e2c19139f9e8b26b67135657fce8/src/model_benchmark/runtime/scenario_qualification.py#L626-L747)); and
- every Harbor invocation is forced to `--n-concurrent 1`; this is correct inside one measured job but does not require unrelated development jobs or separate qualification phases to share one serial CI lane ([runtime, lines 125–154](https://github.com/MihaiA24/model-benchmarking/blob/011c29c37d55e2c19139f9e8b26b67135657fce8/src/model_benchmark/runtime/scenario_qualification.py#L125-L154)).

The normalized [diagnostic timing manifest](evidence/issue-53-verification-profile.json) retains the exact commands, environment identity, raw subprocess timers, Harbor nested Trial aggregates, formulas, and 30-sample publication/consumption microbenchmarks. Its [SHA-256 manifest](evidence/issue-53-verification-profile.sha256) is verified with the strategy.

The repository currently has no committed GitHub Actions workflow on `master` or `011c29c`. A missing CI check must not be described as green CI.

### Reproduced bottleneck decomposition

The accepted live handoff remains the authoritative literal-gate evidence. The complete-inventory rerun above was byte-verified but diagnostic because it added `/usr/bin/time` and pytest timing options. A second clean-archive run selected only the production-qualification case with the acceptance publisher disabled and added profiling around production subprocesses; it too was diagnostic and produced no accepted proof. Harbor's own nested Trial result timers supplied the lifecycle split.

| Observed slice at `011c29c` | Wall time | Share of the 344.44 s production case | Interpretation |
| --- | ---: | ---: | --- |
| Warm `uv sync --frozen` project-wheel build + 86-package install | `0.738 s` | Outside the case | Dependency reuse works and is not the current bottleneck |
| Unconditional exact-digest `docker pull` | `0.792 s` | `0.2%` | Still an unnecessary registry request and fail-closed risk, but not a material warm-cache speed win by itself |
| Harbor `--install-only` provisioning | `27.880 s` | `8.1%` | A sealed verified provision can avoid repeating this in cached integration; fresh authoritative policy decides when it must rerun |
| Seven Trial environment-setup intervals | `36.234 s` | `10.5%` | Fresh environments remain mandatory for the authoritative gate |
| Seven agent-execution intervals | `1.266 s` | `0.4%` | Nop/Oracle fixture work is negligible |
| Seven verifier intervals | `114.021 s` | `33.1%` | Verifier startup/execution is a major fresh-state cost |
| Harbor lifecycle not separately timed by the result schema | `155.585 s` | `45.2%` | Primarily stop, trusted capture, artifact transfer, separate-verifier preparation, and surrounding lifecycle; do not label it more narrowly without new instrumentation |
| Outer CLI, Python validation/signing, publication, and test overhead | `8.662 s` residual | `2.5%` | Residual after the listed subprocess/Harbor timers; do not attribute all of it to hashing |
| Canonical verification-artifact publication | `101.340 ms` median; `134.869 ms` p95 over 30 runs | Separate reproducible microbenchmark | Canonical JSON, schema validation, atomic writes, SHA-256 manifest, and read-back |
| Current computational proof consumption | `11.252 ms` median; `20.705 ms` p95 over 30 runs | Separate reproducible microbenchmark | Recomputed scoped source digest, checksum/schema validation, parse, and case-count check; current artifacts still lack the outer-gate/currentness identities required below |

The seven nested Trials totalled `307.105 s`; their median was `44.128 s`. The Reference phase grouped two serial attempts and took `89.351 s`; the other five measured phases each took `44.111–45.119 s`. The deterministic scaffold/check/lock replay test took `2.34 s`. Fixed-head *computational* proof consumption is measured above; human/agent semantic review remains process latency and is neither replaced nor disguised as verification execution.

Therefore the dominant gains come from tier selection and safe overlap of independent qualification lifecycle work. Digest-first caching is required primarily for network determinism, stale-byte rejection, and avoiding redundant provisioning—not as a claim that image pulling explains the six-minute gate.

## Command matrix

| Tier | Default command shape | Runs | Docker/provider | Output authority | Failure treatment |
| --- | --- | --- | --- | --- | --- |
| Development | `uv sync --frozen` then `uv run --frozen pytest -q <affected unit/schema/architecture paths> --maxfail=1` | Pure tests selected from the closed-world manifest; added/deleted/renamed/unclassified tracked paths select broad development plus every exact gate | Docker forbidden; provider/model forbidden | No `artifacts/acceptance/**` write | Ordinary red build; stale diagnostic output may be deleted |
| Development broad | `uv run --frozen pytest -q tests/unit tests/architecture --maxfail=1` plus `uv lock --check` and compile/lint checks | Entire Docker-free project surface | Docker/provider/model forbidden | Non-authoritative | Required before handing a branch to integration |
| Cached integration | `uv run --frozen pytest -q tests/integration/<affected-boundary> --maxfail=1` | Only changed Harbor/config/image/capture/verifier contracts; each case uses a unique temp/job root | Docker allowed only when mapped boundary requires it; provider/model forbidden by default | Diagnostic manifest under a run-specific non-authoritative root | Fail closed on missing/mismatched digest; never pull implicitly |
| Fresh issue qualification | The manifest's complete ordered issue gate, including exact `uv run --frozen pytest -q tests/acceptance/issue_N ... --maxfail=1` child command and every declared companion | Complete issue-owned mandatory inventory and ordered command outcomes | Docker/live prerequisites exactly as declared; model calls only when the issue explicitly owns a live qualification and a sealed prerequisite authorizes them | Child acceptance artifact plus runner proof envelope/currentness record after complete pass and read-back | Nonzero on skip, xfail, selection, missing command/prerequisite, stale input, failed case, publication/currentness failure, or read-back mismatch |
| Release/deployment qualification | Explicit workflow dispatch or release job invokes every required exact issue gate at the candidate SHA | Full declared release proof set | Dedicated eligible workers; no ambient developer state | One sealed proof set keyed to exact source and input identities | No release/deployment on absent, stale, mixed-head, or incomplete proofs |

### Current command classification

Every verification command must be one of the issue's four classes. Preparation and retired convenience commands are named separately so they cannot acquire evidence authority by accident.

| Current command | Four-way classification | Retained use |
| --- | --- | --- |
| `uv lock --check` | Development edit loop | Frozen-lock drift check |
| `python -m compileall src` (plus `scripts` once introduced) | Development edit loop | Syntax/import preparation check |
| `uv run --frozen model-benchmark --help` | Development edit loop | Exact human CLI smoke |
| `uv run --frozen model-benchmark --json` | Development edit loop | Exact machine-output smoke currently exercised by the foundation acceptance test |
| `git diff --check` or `git diff --check origin/master...HEAD` | Development edit loop alone; authoritative companion only when listed inside an issue's ordered gate | Whitespace/diff validation never proves an issue by itself |
| `uv run --frozen pytest -q <mapped tests/unit or tests/architecture paths> --maxfail=1` | Development edit loop | Smallest closed-world affected pure slice |
| `uv run --frozen pytest -q tests/unit tests/architecture --maxfail=1` | Development edit loop | Broad Docker-free fallback |
| `uv run --frozen pytest -q tests/unit/test_scenarios.py tests/unit/test_scenario_sources.py tests/unit/test_scenario_qualification.py --maxfail=1` | Affected integration | Deterministic Scenario scaffold/check/lock and qualification contracts without claiming issue evidence |
| `uv run --frozen pytest -q tests/unit/test_pytest_acceptance.py tests/unit/test_verification_artifacts.py tests/architecture/test_import_boundaries.py --maxfail=1` | Affected integration | Shared proof-harness and architecture regression slice |
| Ordered [Prove trusted post-stop Submission capture with pinned Harbor](https://github.com/MihaiA24/model-benchmarking/issues/27) gate below | Authoritative merge/release proof | Complete pinned-Harbor substrate proof |
| Ordered [Establish the Python project, canonical serialization, and strict schema foundation](https://github.com/MihaiA24/model-benchmarking/issues/28) gate below | Authoritative merge/release proof | Foundation issue proof; all companion commands must pass |
| Ordered [Harden shared acceptance proof harness and architecture guards](https://github.com/MihaiA24/model-benchmarking/issues/51) gate below | Authoritative merge/release proof | Shared proof authority; all companion commands must pass |
| `uv run --frozen pytest -q tests/acceptance/issue_29_scenario_authoring --maxfail=1` | Authoritative merge/release proof | Full 19-case/7-environment Scenario Package gate |
| `uv run --frozen model-benchmark --json scenario qualify ... --measure-output ...` | Live qualification | Fresh Docker technical qualification; package authority still requires complete review/seal |
| An owning issue's exact `--run-live --require-docker` command | Live qualification | Explicit prerequisite, worker, credentials/budget, and complete mandatory inventory |

The current ordered authoritative command sequences are:

```sh
# Prove trusted post-stop Submission capture with pinned Harbor
uv run --project proofs/harbor-submission-capture --frozen pytest -q proofs/harbor-submission-capture/tests --maxfail=1

# Establish the Python project, canonical serialization, and strict schema foundation
uv sync --frozen
uv run --frozen pytest -q tests/acceptance/issue_28_foundation_harness --maxfail=1
uv run --frozen model-benchmark --help
git diff --check origin/master...HEAD

# Harden shared acceptance proof harness and architecture guards
uv sync --frozen
uv run --frozen pytest -q tests/acceptance/issue_51_proof_hardening --maxfail=1 --require-docker --acceptance-input=tests/architecture
uv run --frozen pytest -q tests/unit/test_pytest_acceptance.py tests/unit/test_verification_artifacts.py tests/architecture/test_import_boundaries.py --maxfail=1
git diff --check origin/master...HEAD

# Implement Scenario Package and standard-v1 authoring tooling
uv run --frozen pytest -q tests/acceptance/issue_29_scenario_authoring --maxfail=1
```

`uv sync --frozen` and `model-benchmark scenario qualify ... --provision` are support operations, not a fifth verification class. The former realizes the immutable environment; the latter is the only network-enabled cache population path. Bare `uv run --frozen pytest -q` is retired as an authority-bearing command because it mixes classes; named jobs replace it, though developers may retain it as a non-authoritative convenience.

At `011c29c`, the exact CLI help/JSON smokes passed, the three-file Scenario affected slice passed `39` tests in `24.29 s`, and the shared proof/architecture affected slice passed `15` tests in `3.49 s`.

### Affected-selection rule

Keep one small repository-owned, closed-world dependency manifest rather than inferring behavior from filenames at runtime. **Every tracked path**, including tests, workflows, scripts, fixtures, generated inputs, and documentation, must map to one or more named test slices and a minimum tier or to an explicit `docs-only/non-normative` class. Added, deleted, renamed, or unclassified paths fail closed to the broad Docker-free suite **and every current exact authoritative gate**; there is no "unknown production path only" exception.

Rules are monotone: a change may add required slices but may not suppress an issue-owned gate. A change anywhere under `tests/acceptance/issue_N` or its declared mandatory inventory selects that issue's complete ordered exact gate, never the changed test alone. Changes to the selector/manifest, CI workflows, shared acceptance plugin, shared fixtures, architecture guards, schemas/catalog, `pyproject.toml`, `uv.lock`, Harbor pin, `profiles/`, or shared scaffolding select every exact gate whose proof envelope declares that input. Normative docs and generated contract docs map to their affected gates; only explicitly mapped non-normative prose may remain docs-only.

Do not put partial-selection support into `tests/acceptance/issue_N`. Cached integration cases live outside the authoritative issue directory so the acceptance plugin's complete-inventory contract remains unchanged. Selector tests must cover additions, deletions, renames, workflow edits, issue-owned acceptance edits, shared-input edits, explicit docs-only paths, and unclassified paths.

## Cache and invalidation matrix

| Cached input | Safe key / identity | Reuse | Invalidate or reject when |
| --- | --- | --- | --- |
| uv downloaded source archives and published wheels | Exact package/version/index origin and lock-recorded artifact hash, uv version, OS/architecture, Python ABI and compatible wheel tag | Development/CI dependency preparation; restore bytes before frozen sync | Artifact hash/origin/tag/ABI or lock changes; frozen sync cannot realize the lock; expected bytes are absent |
| Locally built third-party wheels | Exact source-archive digest, Python ABI, wheel tag, build backend/config, compiler/SDK/libc/system-library identities, complete qualified builder image digest, and resulting wheel digest | Same qualified builder class only; otherwise rebuild from the immutable source archive | Any source, builder, toolchain, system dependency, tag, configuration, or output digest differs; prohibit cross-worker reuse without qualified builder identity |
| Project wheel | Source-tree digest covering `src/`, packaged schemas/profiles/scaffolds, `pyproject.toml`, `uv.lock`, Python ABI/wheel tag, build backend/config, compiler/SDK/libc/system-library identities, and qualified builder image digest; record resulting wheel digest | Install the exact immutable wheel into clean integration/qualification environments on compatible workers | Any included byte, builder/platform identity, or resulting wheel digest changes; no cross-worker reuse from an unqualified local build |
| OCI base and locked images | Exact `repository@sha256:digest`, platform, and local image content identity | Trusted provisioning and all later preflights | Digest is absent, platform mismatches, local inspect does not prove the requested digest, or policy requires a different visibility cache root |
| Scenario runtime image | Scenario Package lock, runtime Dockerfile/build-context digest, platform, and build-tool identity | Across Harness conditions for the same Scenario | Package/runtime/build/platform identity changes |
| Verifier image | Verifier identity and payload digest, hidden-input commitment where applicable, Dockerfile/build context, platform | Only within the matching Scenario/visibility domain | Any verifier, hidden-input, build, platform, or visibility identity changes |
| Harness artifact image | Harness, CLI artifact, Stock Profile, Adapter, build recipe, and platform digests | Across eligible cells using that exact qualified condition | Any constituent identity or Qualification Bundle changes/revokes |
| Harbor wheel and coordinator image | Harbor commit/source digest, dependency lock, complete qualified builder identity, build recipe, platform, and resulting wheel/image digests | Trusted provisioning, cached integration, qualification | Pin/source, lock, builder, recipe, platform, output digest, or qualification changes |
| Generated fixtures and locks | Generator implementation digest plus every declared source/schema/profile/scaffold input digest | Deterministic development projection | Generator/input change or replay bytes differ; never treat mutable filesystem age as validity |
| Deterministic analysis/report projections | Complete sealed input-manifest digest, implementation/environment identity, seed, schema, and generation epoch | Non-authoritative preview or exact deterministic rebuild | Any authority/input/implementation/environment/seed change; preview never becomes canonical by rename |
| Runner-produced proof envelope | Exact commit and recomputed source-tree identity, selector/policy digest, complete ordered command sequence and outcomes, all child artifact checksums, CI workflow/run/attempt, requester/reason, worker/daemon class, generation ID, and live currentness record | Fixed-head review may consume one already-sealed matching generation | Any field is absent; head/input/policy/command/case/worker identity differs; child checksum fails; currentness lookup is unavailable; a later attempt/revocation supersedes it; or policy requires a new release/deployment qualification |

### Digest-first OCI behavior

Replace unconditional pull with an explicit two-step interface:

1. `provision` is the only network-enabled operation. For each `repository@sha256:digest`, inspect the local content store first. If the exact digest and platform are present, record a verified cache hit and do not contact the registry. Otherwise pull the exact digest, inspect it again, and seal the result in the Provisioning Manifest.
2. `preflight` and every measured or qualification execution are read-only. They inspect required digests and fail before creating measured state if bytes are absent or mismatched. They never fall back to pull, build, package resolution, or cache mutation.

Public/Calibration and Private inputs use physically separate cache roots. No host Docker socket, writable package cache, host image store, or mutable cache is mounted into an untrusted Trial.

## Concurrency and isolation matrix

| Work | Safe concurrency | Required isolation | Publication rule |
| --- | --- | --- | --- |
| Pure unit/schema/architecture tests | Parallel processes or CI shards are allowed | Read-only source; independent temp/home/cache/output roots for tests that write | Deterministic aggregation; no acceptance artifact |
| Independent implementation lanes | Parallel dedicated sessions/worktrees are allowed | One branch, worktree, claim, virtual environment, and output root per lane | Integrate focused commits sequentially; refresh tests after each integration |
| Cached integration modules | Parallel across independent modules, preferably one Docker worker/job per shard | Unique Harbor jobs directory, Compose/project namespace, ports/network/volumes, home/scratch, credentials, and diagnostic root | No shard writes a shared authoritative target |
| Seven Scenario Package qualification environments | Keep each Harbor job at `n_concurrent=1`; bounded orchestration across independent phases is allowed only after race/failure-cleanup tests prove package reads, Docker names, jobs roots, teardown, and aggregation are isolated | One phase root and fresh environment per case; immutable package input; no shared writable cache; bounded host resources | One coordinator aggregates only after every phase passes; any failure cancels/tears down siblings and publishes no authoritative record |
| Separate exact issue gates | Parallel only in separate clean worktrees and CI jobs/runners | Unique acceptance output roots/checkouts and immutable caches; dedicated Docker workers for expensive gates | Each issue owns one artifact; a later handoff consumes verified artifacts without rerunning unchanged gates |
| Measured benchmark Trials | **No new concurrency**: one Trial per single-cell Harbor job and one measured Trial at a time on the qualified worker | All accepted fresh-state, proxy, evidence, and teardown boundaries | Canonical Trial/Run Ledger rules remain unchanged |
| Canonical acceptance/report publication | Serial compare-and-publish step | Aggregate from immutable shard outputs into a fresh staging directory | Atomic publish + digest read-back; never concurrent writers to one target |

Local Docker parallelism is a convenience, not an authority. Default local concurrency must be conservative and resource-bounded. CI assigns separate exact issue gates to separate runners; phases that contribute to one signed Package Technical Qualification stay on one eligible worker identity and may overlap there only after isolation and resource proofs pass.

### Frozen initial parallelism and resource profile

Do not introduce a generalized scheduler. Freeze these two initial runner classes:

- **Local reference class:** the measured Apple arm64 host, 10 physical/logical CPUs, `32 GiB` RAM, at least `100 GiB` free writable disk, Docker `29.4.0`, and project Python `3.12.12`.
- **Dedicated CI Docker class:** at least 8 vCPU, `16 GiB` RAM, `80 GiB` writable disk with `50 GiB` reserved for Docker, one responding Docker daemon, no co-tenant benchmark job, and the same pinned Python/uv/Harbor inputs. Until such a runner exists and qualifies, Docker gates remain manual/local and CI must not claim them green.

| Work | Initial parallelism | Per-job/shard envelope | Time budget |
| --- | ---: | --- | ---: |
| Local/CI pure tests | Maximum 4 independent processes | 1 vCPU, `1 GiB` RAM, `2 GiB` writable temp per shard; no Docker/network/provider | affected ≤ 10 s; broad local ≤ 30 s |
| Local cached Docker integration | 1 | Up to 4 CPUs, `8 GiB` RAM, `25 GiB` writable/Docker delta; one unique Docker namespace | ≤ 90 s |
| Separate CI Docker issue gates | 1 per dedicated runner | Full dedicated CI Docker class; independent checkout and artifact generation | Gate-specific budget |
| Scenario Package phases within one qualification | `max_parallel = 3` on one eligible worker identity, only after qualification | Full dedicated CI Docker class shared under explicit CPU/memory/storage limits; unique writable/Docker state per phase | ≤ 240 s gate wall |
| Authoritative aggregation | 1 writer | Less than 1 CPU, `1 GiB` RAM, run-specific staging root | ≤ 2 s excluding child gates |
| Measured benchmark execution | 1 Trial | Accepted qualified-worker limits | Unchanged; no new concurrency |

The implementation records wall/CPU time, peak RSS, writable and Docker disk deltas, immutable-cache hits/misses, registry requests, environment count, and cleanup failures. Qualify a profile with two warmups followed by **20 measured runs**; compute p95 by nearest rank. Acceptance requires every run to stay within its resource/time envelope with zero swap, namespace/port collision, leaked resource, cache mutation, missing result, or cleanup failure. Any miss retains the serial fallback and blocks the parallel profile.

## CI trigger rules

| Event | Required tier | Notes |
| --- | --- | --- |
| Pull request opened/synchronized | Development affected + broad fallback where required | No Docker and no model spend by default; cache uv/wheels by immutable key |
| Pull request touches Harbor pin, acceptance plugin, architecture guards, schemas/profile/scaffold shared inputs, image/provision/preflight code, capture/verifier lifecycle, proof publication, or any unclassified tracked path | Development + affected cached integration; mark every mapped fresh gate required, or every current exact gate for an unclassified path | Closed-world manifest owns classification; no production-path or criticality exception |
| Merge candidate | Exact fresh issue gate(s) explicitly selected by required-check policy, label, merge queue, or manual dispatch at the candidate SHA | Dedicated clean worker; no merge on missing or stale proof. A fixed-head reviewer consumes the sealed proof rather than rerunning it |
| Push to `master` | Development regression; optional post-merge fresh gate only when policy requires defense in depth | A post-merge pass cannot retroactively authorize a merge |
| Deployment or release candidate | Required full fresh qualification at exact candidate SHA, unless a still-valid sealed proof with identical scope and every input identity is explicitly accepted by policy | Never reuse a branch-name/latest artifact or mixed-head proofs |
| Manual fresh qualification | Full explicitly named issue/release gate | Records requester, reason, exact SHA, worker identity, command, inputs, and output checksums |
| Ordinary docs-only change | Link/spell/format checks only unless docs are acceptance inputs | Changes to normative contract or generated schema/profile docs use mapped broader tier |

No workflow may send a provider request merely because a pull request exists. Live model qualifications require the owning issue's sealed non-secret prerequisite, explicit live invocation, budget authorization, and secret-safe eligible worker.

## Fixed-head review and proof reuse

One successful current-head proof should be produced once and consumed many times, but the existing issue artifacts are child evidence—not sufficient proof envelopes. They bind the observed child pytest launcher and scoped source inputs; they do not bind candidate Git SHA, the outer `uv run --frozen` command, a multi-command ordered gate, workflow/run/request identity, or authoritative supersession. Legacy artifacts therefore fail closed for proof reuse until a trusted runner executes the complete gate and wraps their checksums in the envelope below.

### Proof envelope and generation protocol

The verification runner—not the acceptance plugin—produces one immutable envelope per `(repository, candidate SHA, gate ID, policy digest, generation ID)`. It binds:

- exact candidate Git SHA plus a recomputed source-tree digest;
- selector/dependency-manifest and proof-envelope schema digests;
- the complete ordered command sequence declared by the issue, literal outer invocations, per-command start/end/outcome/exit status, and mandatory case inventory;
- every child diagnostic/acceptance artifact path and checksum;
- trusted workflow identity, run ID, run attempt, requester and reason;
- worker class, concrete worker and Docker-daemon identities, toolchain inputs, and qualification state; and
- the run-specific generation ID and envelope checksum.

Production is crash-safe and generation-scoped: create a fresh run-specific staging root; remove nothing from another generation; execute and capture every ordered command; verify child artifacts; write the envelope and checksum last; upload the immutable bundle; then mark the exact candidate-SHA check successful **last** with the uploaded artifact ID and envelope digest. Setup failure, timeout, cancellation, runner loss, staging/rename/upload/read-back failure, or forced termination cannot produce that success record. A fixed-path file from a prior generation is never consulted.

For the initial GitHub implementation, the authoritative currentness/supersession record is the live trusted Check Run history for the exact `(repository, SHA, gate ID, policy digest)`. The consumer selects the **newest attempt regardless of status** from the protected workflow app and requires that exact attempt to be completed successfully and point to the matching immutable envelope. Queued, pending, in-progress, failed, cancelled, successful replacement, or explicitly revoked newer attempts supersede every earlier generation; only a completed-successful newest attempt is reusable. If the Check Runs/artifact lookup is unavailable, ambiguous, deleted, or missing any required field, currentness fails closed. Local runs and copied artifacts are never reusable authoritative proofs.

Review, merge authorization, and handoff verify that currentness record, envelope checksum, candidate/source identities, complete ordered command sequence, mandatory inventory, worker/daemon identities, and child checksums. Corrective commits or declared input/policy changes require affected gates again. Cached development or integration results never promote into authoritative evidence.

## Timing baseline and targets

Targets are implementation budgets to prove, not relaxed pass criteria.

| Scope | Current evidence | Target after implementation |
| --- | --- | --- |
| Affected development slice | Not yet separately exposed | ≤ 10 s wall for a typical one-module edit |
| Broad Docker-free unit suite | 83 tests in 27.66 s (`28.02 s` wall) | ≤ 30 s local; ≤ 20 s CI wall through safe shards |
| Affected cached Docker integration | Not separately exposed | ≤ 90 s per changed Harbor boundary with warm immutable inputs and at most the minimum fresh environments needed by that contract |
| Exact Scenario Package authoritative gate | Accepted literal gate: 19 tests in 356.10 s; diagnostic complete-inventory profile: 357.61 s | ≤ 240 s CI wall with all seven fresh environments retained, after bounded same-worker phase concurrency is proved; ≤ 360 s serial fallback |
| Root suite | 131 tests in 468.73 s | ≤ 480 s local serial fallback; ≤ 300 s local bounded run; ≤ 240 s CI wall through independent jobs |
| Dependency/image preparation | Warm uv setup 0.738 s; exact-digest pull 0.792 s; Harbor install-only 27.880 s | Warm digest check ≤ 2 s with zero registry requests; cached integration skips already sealed install-only work; cold/fresh preparation is reported separately, never hidden inside measured time |

Track median and nearest-rank p95 wall time, CPU time, peak memory, cache hit/miss counts, registry requests, Docker environments created, and cleanup failures per job using the 2-warmup/20-measurement rule above. Timing metrics are diagnostic and never enter benchmark scoring.

## Failure and cleanup contract

- Every task receives a generation ID and run-specific staging/output root; no producer reads or overwrites a prior generation while deciding success.
- First failure stops new scheduling; in-flight Docker work is cancelled where safe, then all resources are enumerated and removed or quarantined before the job returns.
- Seeded stale diagnostic files, fixed-path canonical files, and prior-generation envelopes are ignored as inputs and cannot become current. The exact candidate-SHA success Check Run is written last, so setup failure or forced cancellation before plugin startup cannot preserve apparent success.
- Aggregation validates the expected shard/command/case set exactly once, rejects duplicates/missing results, and writes through fresh staging followed by atomic rename/upload and digest read-back.
- Cache corruption or absence is a cache miss during explicit provisioning and a hard preflight failure everywhere else.
- A timeout, cancelled job, denied prerequisite, or missing runner is not a pass and cannot leave a green authoritative artifact.
- Executable fault injection covers seeded stale diagnostic/canonical outputs, setup failure, timeout, cancellation, duplicate/missing shards, staging-write failure, atomic-rename failure, upload failure, checksum read-back failure, cleanup/quarantine failure, and explicit revocation. Every case must leave no current success record for that generation.

## Minimal implementation backlog

Deduplicate work by root seam rather than by each observed symptom:

1. **[Implement tiered verification selection and fail-closed proof consumption](https://github.com/MihaiA24/model-benchmarking/issues/54).** Add the closed-world dependency manifest and developer selector; separate Docker-free development, non-authoritative integration, and complete exact-gate selection; record diagnostic timing/resource/cache metadata; and consume only a live current trusted envelope while any missing field, identity drift, legacy artifact, unavailable currentness lookup, or supersession rejects it. This seam does not produce or publish authoritative envelopes.
2. **[Implement digest-first immutable provisioning and read-only preflight](https://github.com/MihaiA24/model-benchmarking/issues/55).** Replace unconditional digest pulls with verified local-hit behavior in network-enabled provisioning, seal cache evidence and visibility roots, and make all later integration/qualification/measured preflight fail closed without mutation.
3. **[Implement isolated qualification orchestration and proof publication](https://github.com/MihaiA24/model-benchmarking/issues/56).** Give phases/shards unique writable state and deterministic aggregation; prove race/failure cleanup and no shared authoritative writers; add bounded qualification concurrency without changing per-Harbor-job `n_concurrent=1`; produce the complete runner envelope and crash-safe currentness/supersession record; and publish explicit GitHub Actions triggers for development, affected integration, merge qualification, release/deployment, and manual fresh qualification.

These are implementation issues, not Wayfinder children. They should cite this resolution at an immutable commit, use native dependencies where available, and remain blocked where a predecessor has not yet proved the required seam.

### Invariant traceability into the backlog

| Invariant | Owning implementation seam | Observable proof | Fail-closed treatment |
| --- | --- | --- | --- |
| Default iteration has no Docker, provider/model call, or authoritative output | Tiered verification selection and fail-closed proof consumption | Closed-world path matrix plus denied Docker/network/provider probes | Unclassified path selects broad development + all exact gates; development leaves no acceptance artifact |
| Cached integration cannot impersonate issue evidence | Tiered verification selection and fail-closed proof consumption | Authority-type/schema and copy/rename/reference rejection tests | Reject result as non-authoritative; require the complete exact gate |
| Only exact matching current-head proofs are reusable | Tiered verification selection and fail-closed proof consumption | Legacy/missing-field/source/input/policy/ordered-command/case/worker/checksum/currentness drift matrix | Reject stale/mixed/superseded proof; require the affected exact gate |
| Warm immutable OCI reuse makes zero registry requests | Digest-first provisioning and read-only preflight | Registry-request counter with present/missing/poisoned/wrong-platform cases | Network-enabled provision pulls only absent exact digest; every later phase fails without mutation |
| Public/Calibration and Private cache bytes never share a root | Digest-first provisioning and read-only preflight | Visibility-root mismatch and manifest-tamper tests | Reject manifest/preflight; start no Harbor execution |
| Qualification concurrency shares no writable state or authoritative writer | Isolated qualification orchestration and proof publication | Race, duplicate/missing shard, cancellation, teardown, and deterministic aggregation tests | Cancel, clean/quarantine, publish no success Check Run, retain serial fallback |
| Proof production and currentness are crash-safe | Isolated qualification orchestration and proof publication | Seeded stale outputs plus setup/timeout/cancel/staging/rename/upload/read-back/revocation fault matrix | No current envelope or successful exact-SHA Check Run for the failed generation |
| Complete fresh qualification is not weakened | Isolated qualification orchestration and proof publication plus existing issue gates | Scenario Package gate still proves all 19 cases and seven distinct fresh environments | Nonzero on any absent/skip/xfail/stale case; no partial authoritative envelope |
| Measured Trial freshness and sequential scheduling remain unchanged | Existing [Implement single-cell Harbor execution, preflight, scheduling, and monitoring](https://github.com/MihaiA24/model-benchmarking/issues/36) lane | Its exact live acceptance gate and Run Ledger evidence | No measured launch; preserve accepted disposition/quarantine rules |

## Explicit invariants unchanged

- Measured Trials still receive fresh repositories, homes, scratch/cache paths, volumes, networks, sidecars, and verifier environments.
- Measured execution still performs no fallback registry pull, image build, package install, dependency download, or mutable cache write.
- The initial evaluator still runs one measured Trial at a time on one qualified worker.
- The exact issue acceptance command remains complete, skip-rejecting, selection-rejecting, fail-closed, and the sole publisher of its child issue artifact; only the trusted runner publishes the outer ordered-gate proof envelope/currentness record.
- No cached development/integration artifact can satisfy a merge/release proof by itself.
- No model call or provider spend occurs in the default development loop.
- Canonical benchmark evidence, Run Ledger lifecycle, analysis, and report semantics are unchanged.

## Caveats

- The implementation under review is still on the open [Implement Scenario Package and standard-v1 authoring tooling](https://github.com/MihaiA24/model-benchmarking/issues/29) branch at `011c29c`; final code may change after fixed-head review. Any correction that touches the cited paths requires this strategy's affected mappings and timing baseline to be refreshed.
- The 356.10 s and 468.73 s timings are accepted handoff observations rather than committed timing fields in the verification artifact. The same-commit diagnostic complete-inventory run recorded 357.61 s and localized 344.29 s to the production-qualification case; it does not replace the literal-gate authority. The checksum-addressed diagnostic manifest retains that profile. The root-suite total was not rerun because its accepted handoff evidence and the targeted profile were sufficient to identify the dominant seam.
- Existing issue acceptance artifacts remain valid child evidence under their issue contracts but are not reusable outer-gate proof envelopes. Until the trusted runner/currentness protocol is implemented, fixed-head proof reuse fails closed and reviewers rerun the affected complete ordered gate.
- Bounded concurrency for Scenario Package qualification is a recommendation contingent on executable isolation, resource-limit, cancellation, teardown, and deterministic-aggregation tests. Until they pass, retain the serial authoritative fallback.

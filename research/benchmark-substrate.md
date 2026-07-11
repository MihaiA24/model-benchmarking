# Choose the benchmark substrate

**Decision date:** 2026-07-10  
**Decision status:** Recommended substrate and retained boundary  
**Primary-source cutoff:** 2026-07-10

## Decision

Adapt **Harbor v0.18.0**, pinned to commit [`527d50deb63a5d279e8c20593c18a2cbc7f61f9e`](https://github.com/harbor-framework/harbor/tree/527d50deb63a5d279e8c20593c18a2cbc7f61f9e), rather than building a benchmark runner from scratch.

Harbor is the only reviewed candidate that currently combines all of the following in one locally runnable open-source substrate:

- a fresh container environment created for each trial and deleted during teardown ([agent-environment construction, lines 766–784](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/trial/trial.py#L766-L784), [startup, lines 1101–1108](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/trial/trial.py#L1101-L1108), and [teardown, lines 1140–1147](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/trial/trial.py#L1140-L1147));
- a **separate verifier environment** in which the agent container is stopped before hidden tests start and only declared artifacts cross the boundary ([task contract, lines 490–530](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/docs/content/docs/tasks/index.mdx#L490-L530) and [verifier lifecycle, lines 620–641](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/trial/trial.py#L620-L641));
- first-class task and dataset locking, repeat attempts, time/resource/network controls, and machine-readable trial results ([task controls, lines 103–159](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/docs/content/docs/tasks/index.mdx#L103-L159), [repeat expansion, lines 374–388](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/job.py#L374-L388), [dataset locking](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/docs/content/docs/datasets/git-repos.mdx), and [result contract](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/docs/content/docs/run-jobs/run-evals.mdx));
- installed-agent and external-agent extension points capable of wrapping an opaque headless CLI ([agent extension API, lines 24–88](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/docs/content/docs/agents/index.mdx#L24-L88)); and
- first-class result, trajectory, verifier-log, and filesystem-artifact collection ([result contract](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/docs/content/docs/run-jobs/run-evals.mdx) and [artifact manifest, lines 96–120](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/docs/content/docs/run-jobs/results-and-artifacts.mdx#L96-L120)).

Harbor does **not** natively define the complete experiment. Retain a small project-owned **experiment coordinator** for four missing contracts only:

1. immutable identity of the **evaluated repository** and its OCI image/build inputs;
2. exact CLI launch adapters for OMP, OpenCode, and Hermes;
3. repeated matched-pair assignment and exact-model metadata; and
4. content-addressed sealing of the complete result bundle.

Do not fork Harbor, build a second task lifecycle, replace its verifier, or put statistical analysis into the runner. Public and private suites remain separate inputs and output namespaces. Preserve dimensional scores and operational measures; do not make a single scalar leaderboard score part of the substrate contract.

## Question and non-negotiable criteria

The substrate must run locally against arbitrary immutable evaluated-repository snapshots. Every trial must start from the same hermetic baseline, execute one autonomous CLI as a black box, and end before hidden checks run outside the agent workspace. The experiment must repeat matched conditions using the exact same model configuration, enforce time/resource/network/secret policy, and leave immutable machine-readable evidence. Evaluated-repository language and agent implementation language must not be constrained by the substrate.

The comparison uses the following meanings:

- **Native (N):** a documented field or lifecycle implemented by the substrate.
- **Adaptable (A):** achievable through a documented extension point without changing substrate source.
- **Gap (G):** requires a project-owned contract or orchestration step.
- **Reject (R):** the candidate's intended abstraction conflicts with the requirement.

“Arbitrary evaluated-repository pinning” means pinning the codebase snapshot a harness may modify, not merely the Git repository containing benchmark tasks. “Hidden evaluator” means the evaluator and private assets are absent from the agent-visible filesystem for the entire agent phase; copying tests into that same writable container after the agent exits is weaker than a new verifier environment. “Offline” means no hosted control plane and no network after images, packages, model weights/endpoints, and task inputs have been provisioned locally.

All factual claims below cite first-party documentation, source, schemas, licenses, or release records. Commit-pinned links are frozen evidence. Rolling official documentation is identified as such. **Assessment** and **inference** denote conclusions drawn from that primary evidence rather than vendor claims.

## Candidates surveyed

### 1. Harbor — selected

Harbor describes itself as the official harness for Terminal-Bench 2.0; its migration guide says the Harbor format iterates on Terminal-Bench, so Terminal-Bench is not treated as a separate current candidate ([README](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/README.md), [migration guide](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/docs/content/docs/migration.mdx)). The reviewed release is [`v0.18.0`, published 2026-07-07](https://github.com/harbor-framework/harbor/releases/tag/v0.18.0). The repository is [Apache-2.0 licensed](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/LICENSE).

Native strengths:

- The task schema covers arbitrary environment files, agent/verifier/build timeouts, CPU, memory, storage, accelerator requirements, environment variables, phase-specific network policy, health checks, hidden tests, and declared artifacts ([task schema documentation](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/docs/content/docs/tasks/index.mdx), [authoritative task models](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/models/task/config.py)).
- Docker is the default environment provider and deletion defaults to true. A trial creates a unique environment and tears it down in `finally`; a separate verifier environment has its own creation and teardown path ([trial configuration](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/models/trial/config.py), [trial lifecycle](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/trial/trial.py)).
- In separate-verifier mode, the agent environment stops, verifier tests are built in a dedicated environment, and only explicitly configured artifacts are transferred. The normal single-step lifecycle invokes the verifier only after the agent phase ([trial lifecycle](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/trial/trial.py), [single-step ordering](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/trial/single_step.py), [verifier upload/run path](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/verifier/verifier.py)).
- Git-backed benchmark datasets resolve branch/tag/ref inputs to a commit, and published datasets can be pinned by revision or SHA-256 archive digest. `lock.json` records the Harbor revision and resolved task sources ([Git dataset documentation](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/docs/content/docs/datasets/git-repos.mdx), [publishing and digest pins](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/docs/content/docs/datasets/publishing.mdx), [lock model](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/models/job/lock.py)).
- `n_attempts` expands independent trials over tasks and agents; separate retry controls do not have to be confused with experimental repetitions ([job configuration](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/models/job/config.py), [expansion loop](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/job.py)).
- Network baselines include `public`, `no-network`, and allowlists, with phase-specific agent/verifier policy where the provider supports switching. Resource declarations cover CPU, memory, storage, GPU, and TPU, with provider capability validation ([task/network schema](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/docs/content/docs/tasks/index.mdx), [resource semantics](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/docs/content/docs/tasks/managing-resources.mdx)).
- Local results include configuration, per-trial result JSON, agent trajectory/recording, verifier reward/stdout/stderr, timings, errors, and usage. Artifact collection supports `/logs/artifacts`, declared paths, sidecars, and an artifact manifest ([run/results documentation](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/docs/content/docs/run-jobs/run-evals.mdx), [artifacts documentation](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/docs/content/docs/run-jobs/results-and-artifacts.mdx)).

Material gaps:

- Harbor pins the task package, not automatically the evaluated repository. **Assessment:** the benchmark must place a verified evaluated-repository snapshot into a digest-pinned task image or build context and record both repository commit and image digest. A mutable image tag or a `git clone` in an unpinned Dockerfile is insufficient.
- `BaseInstalledAgent` and `BaseAgent` are supported extension points, but there is no generic task field containing agent argv/stdin/stdout semantics ([agent integration documentation](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/docs/content/docs/agents/index.mdx), [agent configuration model](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/models/trial/config.py)). Each CLI therefore needs a thin adapter.
- Results preserve trial UUID, task checksum/source, agent/model/config, timing, and reward, but the result schema has no explicit `pair_id`, treatment arm, repetition ordinal, or randomization block ([trial result model](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/models/trial/result.py)). Pair assignment must be project-owned.
- Harbor's local files are rich and machine-readable but are not, solely by being written, an immutable evidence store. **Assessment:** seal them by content digest after completion.
- Environment substitution and sensitive-name redaction exist, but secrets are still delivered to processes/containers rather than through a general secret-manager abstraction ([environment resolution/redaction](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/utils/env.py)). Restrict credentials to the phase that needs them and keep model credentials host-side where an agent's protocol permits.

### 2. Inspect AI — strong runner, second choice

The reviewed Inspect AI revision is tag `0.3.245` at commit [`1dc850d88589d81473e1ccce3ca904a1c7980c4f`, dated 2026-07-08](https://github.com/UKGovernmentBEIS/inspect_ai/commit/1dc850d88589d81473e1ccce3ca904a1c7980c4f). It is [MIT licensed](https://github.com/UKGovernmentBEIS/inspect_ai/blob/1dc850d88589d81473e1ccce3ca904a1c7980c4f/LICENSE). Inspect Evals is a first-party benchmark collection; reviewed release [`v0.14.3` was published 2026-07-02](https://github.com/UKGovernmentBEIS/inspect_evals/releases/tag/v0.14.3), and its SWE-bench integration is relevant evidence, not a separate runner.

Inspect has excellent generic extension surfaces. Every sample/epoch gets a distinct Docker Compose project which is cleaned up after the sample ([Docker sandbox lifecycle](https://github.com/UKGovernmentBEIS/inspect_ai/blob/1dc850d88589d81473e1ccce3ca904a1c7980c4f/src/inspect_ai/util/_sandbox/docker/docker.py#L168-L273)). `sandbox_agent_bridge()` explicitly supports command-line agents written in any language and proxies supported OpenAI, Anthropic, Google/Gemini, and MCP protocols into Inspect's model/tool plumbing ([agent bridge documentation](https://github.com/UKGovernmentBEIS/inspect_ai/blob/1dc850d88589d81473e1ccce3ca904a1c7980c4f/docs/agent-bridge.qmd#L8-L20), [CLI bridge example](https://github.com/UKGovernmentBEIS/inspect_ai/blob/1dc850d88589d81473e1ccce3ca904a1c7980c4f/docs/agent-bridge.qmd#L69-L168)). `epochs` repeats samples; task and sample metadata plus sample UUID/epoch fields can carry an external pairing design ([Task API](https://github.com/UKGovernmentBEIS/inspect_ai/blob/1dc850d88589d81473e1ccce3ca904a1c7980c4f/src/inspect_ai/_eval/task/task.py#L72-L178), [log schemas](https://github.com/UKGovernmentBEIS/inspect_ai/blob/1dc850d88589d81473e1ccce3ca904a1c7980c4f/src/inspect_ai/log/_log.py#L378-L458)). Eval logs are serializable as `.eval` or JSON and preserve task, sample, transcript, score, timing, error, and usage records ([log format](https://github.com/UKGovernmentBEIS/inspect_ai/blob/1dc850d88589d81473e1ccce3ca904a1c7980c4f/docs/eval-logs.qmd#L73-L105), [EvalLog model](https://github.com/UKGovernmentBEIS/inspect_ai/blob/1dc850d88589d81473e1ccce3ca904a1c7980c4f/src/inspect_ai/log/_log.py#L1068-L1144)).

Inspect's first-party SWE-bench task demonstrates repository/base-commit metadata and host-side post-agent scoring, including test-patch injection only at scoring time ([task adapter](https://github.com/UKGovernmentBEIS/inspect_evals/blob/97c99f5f6507fc5d1449fe3247f267d591f64350/src/inspect_evals/swe_bench/swe_bench.py#L37-L123), [scorer](https://github.com/UKGovernmentBEIS/inspect_evals/blob/97c99f5f6507fc5d1449fe3247f267d591f64350/src/inspect_evals/swe_bench/scorers.py#L25-L85)). However, core `Sample` has no typed target-repository or image-digest identity ([Sample schema](https://github.com/UKGovernmentBEIS/inspect_ai/blob/1dc850d88589d81473e1ccce3ca904a1c7980c4f/src/inspect_ai/dataset/_dataset.py#L29-L88)); the SWE-bench adapter's default images use mutable `:latest` tags ([adapter defaults](https://github.com/UKGovernmentBEIS/inspect_evals/blob/97c99f5f6507fc5d1449fe3247f267d591f64350/src/inspect_evals/swe_bench/swe_bench.py#L46-L53)). More importantly for this decision, a scorer normally retains access to the live sample sandbox and there is no declarative separate-verifier-container/artifact-handoff contract ([scorer sandbox access](https://github.com/UKGovernmentBEIS/inspect_ai/blob/1dc850d88589d81473e1ccce3ca904a1c7980c4f/docs/multiple-scorers.qmd#L206-L240)). There is also no generic filesystem artifact collector; attachments optimize large log content rather than declaring sandbox output paths ([attachment documentation](https://github.com/UKGovernmentBEIS/inspect_ai/blob/1dc850d88589d81473e1ccce3ca904a1c7980c4f/docs/eval-logs.qmd#L330-L348)).

**Assessment:** Inspect can satisfy the benchmark, but recreating strong verifier separation and artifact handoff would be more project code than Harbor's CLI and experiment-manifest gaps. Keep Inspect as the fallback if model-proxy integration proves more important than Harbor's verifier boundary.

### 3. BenchFlow — strongest emerging alternative

The reviewed revision is commit [`0b41232cf02e9c4f22c01e284724dd2a02c3f468`, dated 2026-07-10](https://github.com/benchflow-ai/benchflow/commit/0b41232cf02e9c4f22c01e284724dd2a02c3f468); the latest reviewed stable release is [`v0.6.4`, published 2026-06-27](https://github.com/benchflow-ai/benchflow/releases/tag/v0.6.4). BenchFlow is [Apache-2.0 licensed](https://github.com/benchflow-ai/benchflow/blob/0b41232cf02e9c4f22c01e284724dd2a02c3f468/LICENSE).

BenchFlow deserves full comparison because it is a general environment/trajectory substrate rather than one benchmark's evaluator. Its first-party README documents Docker, Daytona, and Modal execution, native/translated/bespoke benchmark packages, custom agents, trajectories, per-task results, job summaries, reward/artifact directories, and publishable bundles ([README](https://github.com/benchflow-ai/benchflow/blob/0b41232cf02e9c4f22c01e284724dd2a02c3f468/README.md)). Registry datasets clone a pinned task-source commit, verify per-task SHA-256 digests, and stamp source/digest identity into results; rollouts own setup, container start, verification, and cleanup ([CLI source contract](https://github.com/benchflow-ai/benchflow/blob/0b41232cf02e9c4f22c01e284724dd2a02c3f468/docs/reference/cli.md#bench-eval-run), [rollout lifecycle](https://github.com/benchflow-ai/benchflow/blob/0b41232cf02e9c4f22c01e284724dd2a02c3f468/docs/concepts.md#rollout-lifecycle)). Its agent registry exposes install and launch commands plus plugin registration ([registry source](https://github.com/benchflow-ai/benchflow/blob/0b41232cf02e9c4f22c01e284724dd2a02c3f468/src/benchflow/agents/registry.py#L1-L48), [custom registration](https://github.com/benchflow-ai/benchflow/blob/0b41232cf02e9c4f22c01e284724dd2a02c3f468/src/benchflow/agents/registry.py#L1286-L1352)). Matrix trials provide repetitions, and the task schema includes time, CPU, memory, storage, and network declarations ([CLI matrix contract](https://github.com/benchflow-ai/benchflow/blob/0b41232cf02e9c4f22c01e284724dd2a02c3f468/docs/reference/cli.md#bench-eval-run), [task authoring contract](https://github.com/benchflow-ai/benchflow/blob/0b41232cf02e9c4f22c01e284724dd2a02c3f468/docs/task-authoring-task-md.md#minimal-native-task)).

The blocker is documented by BenchFlow itself. The current task-standard capability matrix marks a hosted/hidden external scorer as only partial/roadmap and separately identifies allowlists and separate verifier environments among incomplete primitives ([task-standard status and roadmap](https://github.com/benchflow-ai/benchflow/blob/0b41232cf02e9c4f22c01e284724dd2a02c3f468/docs/task-standard.md#open-primitives-and-roadmap)). BenchFlow does harden same-environment verification by killing agent processes, restoring configuration, purging injection paths, and pinning verifier environment values ([sandbox hardening](https://github.com/benchflow-ai/benchflow/blob/0b41232cf02e9c4f22c01e284724dd2a02c3f468/docs/sandbox-hardening.md)), but that is not equivalent to Harbor's implemented separate verifier environment. Its documented agent path also centers ACP/session factories; although the registry is extensible, a non-ACP stdin/argv/filesystem-only CLI contract is not established in current user-facing documentation.

**Assessment:** re-evaluate BenchFlow when separate-verifier execution is marked implemented and a plain non-ACP CLI is documented end to end. Today, selecting it would require custom work at the most security-sensitive boundary.

### 4. METR Vivaria + Task Standard — capable, not a greenfield dependency

The reviewed Vivaria revision is [`20a6c290c3c11f701af95a559d9d0c64dd6105d4`, dated 2026-02-15](https://github.com/METR/vivaria/commit/20a6c290c3c11f701af95a559d9d0c64dd6105d4); the reviewed Task Standard revision is [`03236e9a1a0d3c9f9d63f6c9e60a9278a59d22ff`](https://github.com/METR/task-standard/commit/03236e9a1a0d3c9f9d63f6c9e60a9278a59d22ff), standard version 0.5.0. Both are [MIT licensed](https://github.com/METR/vivaria/blob/20a6c290c3c11f701af95a559d9d0c64dd6105d4/LICENSE).

Task Standard requires a fresh primary machine or agent-indistinguishable VM/container and separates root-side task setup/scoring from a non-root agent user ([technical standard](https://github.com/METR/task-standard/blob/03236e9a1a0d3c9f9d63f6c9e60a9278a59d22ff/STANDARD.md#L30-L98)). It supports root-hidden files/processes, root-owned services, or auxiliary-VM data for opaque scoring ([hiding guidance](https://github.com/METR/task-standard/blob/03236e9a1a0d3c9f9d63f6c9e60a9278a59d22ff/README.md#L146-L157)). Vivaria resolves Git-backed task and agent refs to commits, creates a per-run container, provides wall-clock/token/action/cost limits, and records detailed database traces/results ([run route and ref resolution](https://github.com/METR/vivaria/blob/20a6c290c3c11f701af95a559d9d0c64dd6105d4/server/src/routes/general_routes.ts#L113-L223), [architecture](https://github.com/METR/vivaria/blob/20a6c290c3c11f701af95a559d9d0c64dd6105d4/docs/architecture.md#L5-L18), [usage limits](https://github.com/METR/vivaria/blob/20a6c290c3c11f701af95a559d9d0c64dd6105d4/shared/src/types.ts#L550-L570), [database schema](https://github.com/METR/vivaria/blob/20a6c290c3c11f701af95a559d9d0c64dd6105d4/server/src/migrations/schema.sql#L29-L88)).

The fit gaps are substantial. Task families are Python; Vivaria launches `python -u .agent_code/main.py`, so an opaque CLI requires a Python shim ([Task Standard scope](https://github.com/METR/task-standard/blob/03236e9a1a0d3c9f9d63f6c9e60a9278a59d22ff/README.md#L158-L166), [agent guide](https://github.com/METR/vivaria/blob/20a6c290c3c11f701af95a559d9d0c64dd6105d4/docs/tutorials/create-agent.md#L1-L18), [launcher](https://github.com/METR/vivaria/blob/20a6c290c3c11f701af95a559d9d0c64dd6105d4/server/src/docker/agents.ts#L887-L914)). There is no declarative separate verifier container, repeat count, pair identity, or artifact manifest. Local operation requires a server, PostgreSQL, background runner, UI, and Docker socket through the documented Compose stack ([local setup](https://github.com/METR/vivaria/blob/20a6c290c3c11f701af95a559d9d0c64dd6105d4/docs/tutorials/set-up-docker-compose.md#L1-L87), [Compose topology](https://github.com/METR/vivaria/blob/20a6c290c3c11f701af95a559d9d0c64dd6105d4/docker-compose.yml)). Most decisively, METR states that it is transitioning to Inspect, recommends Inspect for new projects, and is winding down Vivaria feature development ([Vivaria README](https://github.com/METR/vivaria/blob/20a6c290c3c11f701af95a559d9d0c64dd6105d4/README.md#L5-L20)).

**Assessment:** reject Vivaria for new work. Its task-isolation ideas remain useful evidence, but its operational footprint and explicit maintenance direction dominate the technical fit.

## Fit/gap matrix

This matrix is a comparative assessment of the cited current revisions, not a claim that unsupported extensions are impossible.

| Criterion | Harbor v0.18.0 | Inspect AI 0.3.245 | BenchFlow v0.6.4/current reviewed | Vivaria + Task Standard |
|---|---|---|---|---|
| Arbitrary evaluated repositories | **A** — arbitrary task environment; project pins the evaluated repository | **A** — generic sample/sandbox; project defines the evaluated repository | **A** — generic task package; project defines the evaluated repository | **A** — task assets/install step; project defines the evaluated repository |
| Immutable task-source pin | **N** — resolved Git commit, task digest, `lock.json` | **A** — eval-source revision and arbitrary metadata | **N** — source commit and task SHA-256 | **N** — task/agent commit or upload hash |
| Immutable evaluated-repository/image pin | **G** — must enforce commit + OCI digest | **G** — no typed evaluated-repository/image identity | **G** — task-source pin is not an evaluated-repository pin | **G** — no typed evaluated-repository identity |
| Fresh reset per trial | **N** — unique environment, delete in `finally` | **N** — distinct Compose project per sample/epoch | **N** — rollout lifecycle cleans container | **N** — fresh per-run container |
| Hidden checks outside agent workspace | **N** — separate verifier environment + declared handoff | **A** — host-side scorer can inject after agent; no declarative verifier container | **A/G** — same-environment hardening; separate environment incomplete | **A** — root/aux-VM hiding, not a verifier-container contract |
| Arbitrary black-box CLI | **A** — installed/external agent wrapper | **A** — documented any-language bridge + command wrapper | **A/G** — launch registry exists; non-ACP path under-documented | **A** — mandatory `main.py` shim |
| Network policy | **N** — public/no-network/allowlist, phase-specific where supported | **A** — no-network or Compose-defined networking; no generic allowlist schema | **A/G** — declarations exist; allowlist runtime partial | **A** — no/full internet; fine-grained policy external |
| Secret handling | **A** — phase env, approval, serialization redaction; no vault | **A** — host model keys/override hook; general secrets external | **A** — agent/verifier env scopes; verify provider behavior | **A** — declared task env and server model credentials; no vault |
| Independent repetitions | **N** — `n_attempts` | **N** — epochs | **N** — matrix trials | **G** — outer loop required |
| Explicit paired-trial design | **G** — no pair/arm/repeat fields | **G** — metadata can carry design, no typed pair | **G** — trials, no documented matched-pair key | **G** — arbitrary metadata/batches only |
| Time limits | **N** — phase timeouts | **N** — sample/working/token/turn/cost and exec limits | **N** — task and idle/setup limits | **N** — wall/token/action/cost limits |
| CPU/memory/storage limits | **N** — provider-validated policies | **A/N** — Compose CPU/memory; broader limits provider-owned | **N/A** — declared, provider support varies | **N/A** — configured CPU/RAM/disk/GPU; deployment-dependent |
| Logs and structured results | **N** — result/config JSON, trajectory, verifier logs | **N** — `.eval`/JSON log schemas and transcript | **N** — per-task/job results, ATIF/ADP trajectories | **N** — DB result/trace and JSON/JSONL query |
| Generic filesystem artifacts | **N** — declared paths, `/logs/artifacts`, manifest | **G** — custom collector required | **N** — reward/artifact directories and publishable bundle | **G** — explicit copy/export convention required |
| Local operation | **N** — local tasks + Docker + local viewer | **N** — local Python runner + Docker | **N** — local Docker backend | **N**, but multi-service Compose platform |
| Fully offline after provisioning | **A** — local tasks/images/CLI/model required; no bundle mode | **A** — local providers supported; assets must be cached | **A/G** — no explicit air-gap guarantee | **A/G** — build-time internet is assumed by standard/template |
| Workload language neutrality | **N** — arbitrary container and shell/batch verifier | **N** — any-language sandbox CLI; Python extensions | **N/A** — containerized commands; Python plugin layer | **A** — arbitrary binary behind Python task/agent seams |
| Extensibility | **N** — external/installed agents, custom environments/verifiers, dataset adapters | **N** — agents, solvers, scorers, sandboxes, models, hooks | **N** — agent/task/sandbox/benchmark plugin seams | **N/A** — arbitrary task lifecycle and driver, Python-defined seams |
| License | Apache-2.0 | MIT | Apache-2.0 | MIT |
| Maintenance posture | **Strong** — v0.18.0 on 2026-07-07 | **Strong** — 0.3.245 on 2026-07-08 | **Strong but pre-1.0** — v0.6.4 on 2026-06-27, active head | **Reject** — maintainer recommends Inspect for new work |

Evidence for the matrix is in the candidate sections above. The key discriminator is not generic Docker execution—every finalist has it—but the combination of an implemented separate verifier environment, repeat orchestration, network/resource policy, and artifact handoff. Harbor has that combination at the reviewed release.

## Candidate elimination boundary

| Candidate | Evidence | Decision |
|---|---|---|
| Terminal-Bench | Harbor's [migration guide](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/docs/content/docs/migration.mdx) identifies Harbor as the evolution of the task format; Harbor's [README](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/README.md) calls it the Terminal-Bench 2.0 harness. | Do not evaluate as a separate modern substrate; use Harbor. |
| Inspect Evals | It is a collection of evaluation tasks on Inspect. Its [SWE-bench task](https://github.com/UKGovernmentBEIS/inspect_evals/blob/97c99f5f6507fc5d1449fe3247f267d591f64350/src/inspect_evals/swe_bench/swe_bench.py) and [scorer](https://github.com/UKGovernmentBEIS/inspect_evals/blob/97c99f5f6507fc5d1449fe3247f267d591f64350/src/inspect_evals/swe_bench/scorers.py) are useful adapter examples. | Retain examples; compare/select Inspect AI, not Inspect Evals, as substrate. |
| SWE-bench harness | Its documented contract consumes JSONL predictions containing `model_patch`; the runner applies a patch and executes `/eval.sh` in an instance container rather than launching a general agent ([evaluation guide](https://github.com/SWE-bench/SWE-bench/blob/f7bbbb2ccdf479001d6467c9e34af59e44a840f9/docs/guides/evaluation.md), [runner](https://github.com/SWE-bench/SWE-bench/blob/f7bbbb2ccdf479001d6467c9e34af59e44a840f9/swebench/harness/run_evaluation.py#L123-L249)). Its test-spec builder selects known repository/version mappings ([test-spec source](https://github.com/SWE-bench/SWE-bench/blob/f7bbbb2ccdf479001d6467c9e34af59e44a840f9/swebench/harness/test_spec/test_spec.py#L183-L228)). It is [MIT licensed](https://github.com/SWE-bench/SWE-bench/blob/f7bbbb2ccdf479001d6467c9e34af59e44a840f9/LICENSE) and the reviewed head is [dated 2026-03-19](https://github.com/SWE-bench/SWE-bench/commit/f7bbbb2ccdf479001d6467c9e34af59e44a840f9). | Reject as orchestration substrate; retain only as an evaluator adapter for SWE-bench-format tasks. |
| OpenHands Benchmarks | The project says it is infrastructure for OpenHands agents ([README](https://github.com/OpenHands/benchmarks/blob/4e5469e0caaf54d1ad827d18b524bdfb79d58430/README.md)). The reviewed agent schema is a closed literal containing the default OpenHands agent and three ACP choices, and the ACP adapter hard-codes their commands/credentials ([schema](https://github.com/OpenHands/benchmarks/blob/4e5469e0caaf54d1ad827d18b524bdfb79d58430/benchmarks/utils/models.py#L17-L121), [ACP adapter](https://github.com/OpenHands/benchmarks/blob/4e5469e0caaf54d1ad827d18b524bdfb79d58430/benchmarks/utils/acp.py)). It is [MIT licensed](https://github.com/OpenHands/benchmarks/blob/4e5469e0caaf54d1ad827d18b524bdfb79d58430/LICENSE), with reviewed head [dated 2026-06-25](https://github.com/OpenHands/benchmarks/commit/4e5469e0caaf54d1ad827d18b524bdfb79d58430). | Reject as neutral substrate; retain lifecycle/archive patterns only. |
| Bespoke runner | Harbor already implements the difficult lifecycle and security-sensitive parts evidenced above. | Reject initially. Reconsider only if the proof gates below fail. |

No candidate was rejected merely for using Python internally. Language neutrality is required at the workload and black-box process boundary, not for substrate extension authors.

## Minimum Harbor adaptation boundary

The experiment coordinator is deliberately smaller than a new runner. It owns declarations and identity; Harbor owns execution.

### Project-owned manifest

Before a trial can run, one immutable manifest row must identify:

- experiment, suite visibility (`public` or `private`), scenario ID, pair/block, condition/CLI, and repetition ordinal;
- evaluated-repository origin, exact commit, source-tree/archive digest, checkout path, and clean-baseline assertion;
- OCI image digest or reproducible build-input digest; mutable tags are invalid as evidence;
- Harbor version/commit, Harbor task ID, task package digest/resolved commit, verifier revision/digest, and Harbor `lock.json` identity;
- CLI name, exact release/commit or binary/package digest, adapter revision, argv/cwd, non-interactive mode, configuration digest, and allowed environment variable names;
- provider, exact model identifier/version, endpoint identity, sampling/tool settings, context limits, and seed when the provider actually supports one;
- time/resource/network policy and the names—not values—of secrets granted to each phase; and
- expected artifact paths and dimensional score names.

This manifest is the experimental identity Harbor does not supply. A hosted model alias can change behind the same string; if the provider does not expose an immutable model revision, record that as an evidence limitation rather than calling the model exact.

### CLI adapters

Use Harbor's supported installed-agent extension point; do not add knowledge of OMP, OpenCode, or Hermes to tasks. Each adapter has one responsibility: install or verify one pinned CLI, start it non-interactively in the repository workspace with the task instruction, wait for completion, preserve stdout/stderr/exit/timing, and expose no extra evaluator data.

Feasibility is supported by the CLIs' first-party interfaces, but must be proven before production runs:

- OMP documents `omp --mode rpc --no-session` and JSON requests including prompt and model selection in its [`v16.4.0` README](https://github.com/can1357/oh-my-pi/blob/v16.4.0/README.md).
- OpenCode's rolling official CLI documentation, retrieved 2026-07-10, documents non-interactive `opencode run ...` and an ACP server ([CLI documentation](https://opencode.ai/docs/cli/)); the reviewed repository release is [`v1.17.18`, 2026-07-09](https://github.com/anomalyco/opencode/releases/tag/v1.17.18).
- Hermes' rolling official CLI guide, retrieved 2026-07-10, documents a single-query worktree invocation (`hermes -w -z "..."`) and model selection ([CLI guide](https://hermes-agent.nousresearch.com/docs/user-guide/cli/)); its [official source repository](https://github.com/NousResearch/hermes-agent) remains the version authority.

The adapters may normalize invocation and capture, but must not normalize agent behavior, prompts, tool availability, retries, or output into a shared agent loop. These agents remain black boxes.

### Repository materialization

One project scenario is materialized as one Harbor task whose package contains or builds exactly one verified evaluated-repository snapshot. The agent receives a writable copy at the declared checkout path. Trial setup must fail closed if the tree identity differs from the manifest. Build-time downloads, mutable base-image tags, named writable volumes, host bind mounts, and unversioned package installs are outside the reproducible profile unless separately digested and recorded.

This is a project policy implemented around Harbor task/image preparation, not a second sandbox lifecycle. Harbor remains responsible for creating and deleting the writable trial environment.

### Hidden evaluator boundary

Use `verifier.environment_mode = "separate"`. During the agent phase:

- no public or private verifier code, test data, credentials, expected outputs, or verifier-only services are present in the agent container;
- only the declared submission artifacts cross to the verifier container after the agent container stops; and
- verifier network and secrets are separate from agent network and secrets.

Do not use shared-verifier mode for private checks. It hides tests until scoring but executes them in a container the agent controlled, which is not the selected threat boundary. A remote grader protocol is unnecessary for the initial design because Harbor's separate verifier satisfies “mounted outside the agent workspace.” If private policy later requires checks never to exist on the benchmark host, a verifier script may call a remote service, but that is an additional policy requirement, not a reason to replace Harbor.

### Repeated paired trials

Harbor's `n_attempts` supplies repetitions but not pair identity. The project-owned experiment manifest must enumerate matched rows before execution. A valid matched block uses the same task snapshot, repository/image digest, prompt, verifier digest, exact model/provider/settings, and limits for every CLI condition. It records pair/block ID, CLI condition, repetition, randomized execution order, and a seed only where meaningful. Provider retries are operational retries, not replacement experimental observations.

Because Harbor currently discards the attempt-loop ordinal from `TrialResult`, do not infer pair identity from file order, concurrency order, or timestamps. Join every Harbor job/trial UUID back to its predeclared manifest row. If that join is absent, the trial may remain useful diagnostically but is excluded from paired analysis.

### Immutable result bundle

Retain Harbor's native files verbatim, then add one content-addressed seal containing:

- the experiment manifest row and Harbor lock/config/result JSON;
- stdout/stderr, trajectory/recording, verifier output, rewards and every dimensional score;
- repository/image/task/verifier/CLI/adapter/model identities;
- declared submission artifacts and Harbor artifact manifest;
- timing, usage, limit, network-policy, exit, retry, and error records; and
- SHA-256 plus byte length for every file in the bundle.

The seal is complete only after Harbor finishes collecting artifacts. Write the digest-addressed bundle once and reject overwrite; any redacted/public export is a separately digested derivative pointing to the private canonical bundle. This is the minimum additional immutability layer; a database, dashboard, hosted artifact service, or custom result schema is not required for the decision.

### Public/private and multi-dimensional reporting

Public and private suites must have distinct task sources, manifests, verifier assets, credentials, run roots, and published result namespaces. Never merge private test material into a public task digest or publish a canonical private bundle. A cross-suite analysis may reference redacted result digests, but the underlying suites remain independently reproducible and independently access-controlled.

The substrate records the complete score vector and operational observations. Aggregation and uncertainty analysis happen downstream. Do not collapse correctness dimensions, safety/policy outcomes, resource/time/usage, failure categories, or task strata into a substrate-defined scalar. Harbor supports named reward components and raw verifier artifacts; the project manifest declares their meaning, direction, and version ([verifier/reward task contract](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/docs/content/docs/tasks/index.mdx), [results/artifacts contract](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/docs/content/docs/run-jobs/results-and-artifacts.mdx)).

## Proof gates before retaining Harbor permanently

This is a substrate decision, not evidence that the integration already works. Retain Harbor only after one local smoke trial for each CLI proves all of these observable gates:

1. a digest-pinned repository snapshot starts clean and each repeat receives a new environment;
2. the CLI runs headlessly to completion with the exact declared model configuration and no harness-specific behavior injected into the task;
3. agent egress and secrets match policy;
4. private checks are unavailable during the agent phase;
5. the agent container stops before separate verification, and only declared artifacts arrive;
6. time/resource failure modes are recorded rather than silently retried into an experimental observation;
7. pair identity joins unambiguously from the predeclared manifest to Harbor trial UUID; and
8. the final sealed bundle verifies by digest and contains every required dimension and raw evidence.

Failure of a CLI adapter alone is not failure of Harbor; it is evidence that the CLI lacks the required black-box interface or needs a different supported adapter mode. Failure of separate-verifier isolation, clean reset, enforceable network/resource policy, or complete artifact handoff is a substrate failure.

If a substrate failure occurs and cannot be fixed by configuration or a small upstream-compatible extension, the fallback is the smallest custom runner with only five responsibilities: validate/expand the same immutable manifest, create one digest-pinned OCI container per trial, execute one opaque CLI under declared limits, transfer declared artifacts to an isolated verifier, and seal the resulting records. It must not grow a model client, agent loop, benchmark registry, dashboard, distributed scheduler, or statistical package. That fallback is a contingency, not the recommendation.

## Risks, evidence limits, and confidence

| Risk or limit | Consequence | Required treatment |
|---|---|---|
| Harbor is pre-1.0 and moving quickly. | Schema/API changes may break adapters or alter semantics. | Pin v0.18.0 by commit, pin adapter code, preserve `lock.json`, and upgrade only through the proof gates. |
| No reviewed substrate natively identifies arbitrary target repositories and paired experimental blocks together. | Reproducibility or pairing can be overstated if arbitrary metadata is incomplete. | Make the project manifest mandatory and fail closed on missing identities. |
| Provider model aliases may be mutable, and seed support differs. | “Exact model” may mean exact request configuration, not immutable weights/service revision. | Record provider-exposed immutable revision when available; otherwise label the limitation explicitly. |
| Network/resource behavior depends on the selected Harbor provider and host runtime. | A declared policy may not be enforced identically across Docker/cloud backends. | Qualify the local Docker profile once; reject unsupported capability combinations rather than silently degrading. |
| Secret-name redaction is not a secret vault or proof against agent exfiltration. | A credential visible to the agent is under agent control. | Prefer host-side model mediation; otherwise use minimum-scope disposable credentials and no private verifier secrets in the agent phase. |
| Artifact collection of arbitrary paths can fail without failing the trial. | A score could exist while required evidence is incomplete. | The sealing step must reject bundles missing mandatory artifacts even if Harbor reports a completed trial. |
| Current research is documentation/source review only; no candidate was executed. | CLI and provider interoperability remain unproven. | Run the narrow proof gates before benchmark production; do not reinterpret this document as integration certification. |
| BenchFlow is changing quickly and its roadmap may close the current verifier gap. | The relative decision can change. | Re-evaluate when its first-party capability matrix marks separate verifier execution implemented and documents non-ACP CLI operation. |
| Vivaria maintenance direction could change. | Its rejection is partly time-sensitive. | Reconsider only if METR reverses the published transition-to-Inspect guidance and stabilizes the runner interface. |

**Confidence: high** that Harbor v0.18.0 is the best fit among the reviewed current open-source candidates for clean local trials, external hidden checks, network/resource control, repetitions, and artifacts. That confidence rests on release-pinned implementation and schema evidence, especially the separate verifier path.

**Confidence: medium** that the minimum adaptation remains thin for all three CLIs. Their official interfaces show viable non-interactive entry points, but the exact container install path, model credential mediation, and termination behavior have not been exercised here.

**Confidence: medium** in fully offline operation. Every finalist can run locally, but none of the reviewed sources provides a complete air-gap bundle guaranteeing that base images, packages, model assets, task sources, and CLI installers are already local. Offline is therefore a qualified deployment profile, not a native product guarantee.

## Primary-source index

All sources were retrieved or checked on **2026-07-10**. The decision intentionally uses no third-party comparisons.

- Harbor: [v0.18.0 release](https://github.com/harbor-framework/harbor/releases/tag/v0.18.0), [commit-pinned tree](https://github.com/harbor-framework/harbor/tree/527d50deb63a5d279e8c20593c18a2cbc7f61f9e), [license](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/LICENSE), [task docs](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/docs/content/docs/tasks/index.mdx), [trial source](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/trial/trial.py), [agent docs](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/docs/content/docs/agents/index.mdx), [results/artifacts docs](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/docs/content/docs/run-jobs/results-and-artifacts.mdx).
- Inspect AI / Inspect Evals: [Inspect tag commit](https://github.com/UKGovernmentBEIS/inspect_ai/commit/1dc850d88589d81473e1ccce3ca904a1c7980c4f), [Inspect license](https://github.com/UKGovernmentBEIS/inspect_ai/blob/1dc850d88589d81473e1ccce3ca904a1c7980c4f/LICENSE), [agent bridge](https://github.com/UKGovernmentBEIS/inspect_ai/blob/1dc850d88589d81473e1ccce3ca904a1c7980c4f/docs/agent-bridge.qmd), [Docker sandbox source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/1dc850d88589d81473e1ccce3ca904a1c7980c4f/src/inspect_ai/util/_sandbox/docker/docker.py), [Inspect Evals v0.14.3](https://github.com/UKGovernmentBEIS/inspect_evals/releases/tag/v0.14.3), [SWE-bench adapter](https://github.com/UKGovernmentBEIS/inspect_evals/blob/97c99f5f6507fc5d1449fe3247f267d591f64350/src/inspect_evals/swe_bench/swe_bench.py).
- BenchFlow: [reviewed commit](https://github.com/benchflow-ai/benchflow/commit/0b41232cf02e9c4f22c01e284724dd2a02c3f468), [v0.6.4](https://github.com/benchflow-ai/benchflow/releases/tag/v0.6.4), [license](https://github.com/benchflow-ai/benchflow/blob/0b41232cf02e9c4f22c01e284724dd2a02c3f468/LICENSE), [task-standard status](https://github.com/benchflow-ai/benchflow/blob/0b41232cf02e9c4f22c01e284724dd2a02c3f468/docs/task-standard.md), [hardening](https://github.com/benchflow-ai/benchflow/blob/0b41232cf02e9c4f22c01e284724dd2a02c3f468/docs/sandbox-hardening.md), [agent registry](https://github.com/benchflow-ai/benchflow/blob/0b41232cf02e9c4f22c01e284724dd2a02c3f468/src/benchflow/agents/registry.py).
- METR: [Vivaria reviewed commit](https://github.com/METR/vivaria/commit/20a6c290c3c11f701af95a559d9d0c64dd6105d4), [Vivaria transition notice](https://github.com/METR/vivaria/blob/20a6c290c3c11f701af95a559d9d0c64dd6105d4/README.md#L5-L20), [Task Standard 0.5.0](https://github.com/METR/task-standard/blob/03236e9a1a0d3c9f9d63f6c9e60a9278a59d22ff/STANDARD.md), [licenses](https://github.com/METR/vivaria/blob/20a6c290c3c11f701af95a559d9d0c64dd6105d4/LICENSE).
- Eliminated harnesses: [SWE-bench reviewed source](https://github.com/SWE-bench/SWE-bench/tree/f7bbbb2ccdf479001d6467c9e34af59e44a840f9), [OpenHands Benchmarks reviewed source](https://github.com/OpenHands/benchmarks/tree/4e5469e0caaf54d1ad827d18b524bdfb79d58430).
- Target CLI interfaces: [OMP v16.4.0](https://github.com/can1357/oh-my-pi/blob/v16.4.0/README.md), [OpenCode CLI](https://opencode.ai/docs/cli/), [Hermes CLI](https://hermes-agent.nousresearch.com/docs/user-guide/cli/).

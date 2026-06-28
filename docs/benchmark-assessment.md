# Benchmark Assessment

Assessment of the model-benchmarking repository: the older single-shot benchmark on `master` (3 models, 11 tasks) and the harness redesign on `feat/agent-harness-impl`. Produced by a `grill-with-docs` session; decisions recorded in ADR-0001 through ADR-0004 and `CONTEXT.md`.

## 1. Research questions

The benchmark answers two distinct, explicitly separated research questions:

- **(a) Single-shot capability** — which model writes the best single-shot fix from a spec plus file contents, with no tools and one pass. This is what `master` built and what the 3-model historical dataset measures.
- **(b) Model-plus-harness combination** — which model+harness combination solves the most tasks end-to-end, where the harness provides tools, file access, and iteration. This is what `feat/agent-harness-impl` reaches for.

Runs are comparable within a capability mode, never across. A single-shot pass and an agent-iterated pass are not the same achievement, even when they share a task and model.

## 2. Assessment of the older benchmark (`master`)

### 2.1 What it did

Three models — `minimax/minimax-m3`, `deepseek/deepseek-v4-flash`, `z-ai/glm-4.7` — each run 3× across 11 tasks (99 evaluations), single-shot via OpenRouter chat-completions. Per task: the runner appends the current file content to a frozen prompt, the model returns a complete corrected file in a single code block, a regex extracts the code, the runner overwrites the file, then build and test checks run. `temperature=0.2`, no tools, no iteration, no file-system access. Prompts are frozen across all models for comparability. Human review: double-blind (Modelo A–K), 5-axis rubric, two-reviewer reconciliation.

### 2.2 Are the prompts correct? Yes — as single-shot instruments

The frozen prompts are spec-precise, name a single target file, and give an unambiguous correctness criterion. The Spanish/English mix (Spring Boot in Spanish, other stacks in English) is a stylistic inconsistency but not a validity threat — each prompt is self-contained and the models handled both languages. The "Return ONLY the complete corrected file in a single code block" contract is an **intentional format-discipline test**: a model that cannot follow output-format instructions is worse at single-shot coding tasks, because real single-shot use requires format discipline. The contract is correct for research question (a).

### 2.3 Is the automatic gate valid? Mostly — with two defects

**The gate is a gate, not a ranking instrument.** Eight of eleven tasks give zero automatic discrimination — every model passes build+test every time. The gate's role is coarse pass/fail filtering, not model ranking. This is by design: the 5-axis human rubric (correctness, idiomaticity, security, instruction-compliance, integration-effort) is where model ranking lives. The one task that discriminates automatically is `re-feat2-author-filter` (minimax 1/3, deepseek 2/3, glm-4.7 1/3).

**Defect 1 — extraction collapses format failures into capability failures.** The `extract_code` regex (`re.search(r"```(?:\w+)?\n(.*?)```", text, re.S)`) returns raw prose if no code block is found. A model that writes correct code but adds a preamble, or returns an empty response, looks identical to a model that writes wrong code. Direct evidence: `re-feat2-author-filter, z-ai/glm-4.7, r2` records `ERROR: "expected string or bytes-like object, got 'NoneType'"` — an empty response misrecorded as a capability failure. The glossary already defines `Task Failure` vs `Infrastructure Failure` as distinct; the code doesn't honor the distinction on the extraction path. Prescribed fix: separate `format_error` from `build_fail`/`test_fail`; empty responses become `Infrastructure Failure`.

**Defect 2 — Angular's build-only gate has no functional correctness signal.** Three tasks (`ng-bug1`, `ng-feat1`, `ng-feat2`) verify with `test_ok_equals_build = True`: a green `npm run build` is recorded as pass, with no functional test. The `instrucciones.md` acknowledges this and delegates Angular correctness to the human-review axis. The delegation would be sound if the human review ran — but it didn't (see 2.4). The "Vitest + zone.js incompatibilidad" is a solvable environment problem, not a fundamental one: `getReadingTime(body)` is a pure function, `ArticlesService.search()` is testable with `HttpTestingController`, and the `@Input()` bug is catchable by a template compile check. Prescribed fix: add isolated unit tests that don't depend on the full Vitest+zone.js runner, raising the Angular gate to match the other 8 tasks.

### 2.4 Was the human review run? No — scaffolded, not executed

The human-review apparatus was designed from the first commit — blind mapping, two-reviewer reconciliation, 5-axis rubric, combined-scoring prompt. But `plantilla_puntuacion.csv` is a blank template; no `plantilla_puntuacion_FINAL.csv` exists. On `master`, the 3 models were ranked on 1 discriminating automatic task + cost + latency, never on the 5-axis rubric the benchmark was designed around. The discrimination layer was designed but never run. The prompts were never validated against the human axis they were built for.

### 2.5 Is the older benchmark correct? Conditional yes

For research question (a), the older benchmark is correct in design but partially realized in execution:
- Prompts: correct (frozen, spec-precise, format-discipline contract intentional).
- Automatic gate: correct as a coarse filter; defective in extraction-error conflation and Angular build-only verification.
- Human review: correct in design; not executed.
- Net: the 3-model historical dataset is valid for cost/latency comparison and for the one discriminating automatic task. It is not valid for quality-axis ranking until the human review is run or the gate is hardened.

## 3. Assessment of the harness design (`feat/agent-harness-impl`)

### 3.1 Architecture: sound

The adapter layer is clean. `HarnessAdapter` protocol (`benchmark/adapters/base.py`) with `raw_api` control + `omp`/`opencode`/`hermes` agent adapters behind a shared `_CliAdapter` base. Canonical model in CSV, harness-specific adapter selector at invocation (`runner.py:176-189`). Resume by `(harness, task, model, run)` tuple. Preflight checks. Sequential CSV writer. ADR-0001 (accepted) defines the harness-queue architecture and per-harness caps. This is good work.

### 3.2 Should we make changes? Yes — six prescribed changes

#### Change 1 — Add `capability_mode` and `telemetry_trust` columns (ADR-0002)

The same CSV holds single-shot and agent-iterated runs with different prompts, capability surfaces, and telemetry reliability. A raw_api pass and an agent pass are not the same achievement; an exact single-request cost and a parsed multi-iteration cost are not comparable. The schema lets them look identical. Prescribed: add `capability_mode` (`single_shot` | `agent_iterated`) and `telemetry_trust` (`exact` | `parsed` | `blank`) as first-class columns. Cost and tokens are comparable only within cohorts that share both values. `migrate_csv_schema` must backfill legacy rows.

#### Change 2 — Withhold the test command from the agent prompt

`agent_prompt` (`benchmark/prompts.py`) currently tells the agent the exact build and test commands the runner will use to judge it, and allows it to run those commands. An agent can run the test, see it fail, edit, repeat until green. This makes the spec prose irrelevant — the agent can satisfy the named command without understanding the spec. The task becomes "follow a test command," not "write correct code from a spec." Prescribed: withhold the test command from the agent prompt; keep the build command so the agent can compile-check. The agent can still discover and run tests by reading the repo (e.g., `package.json`), but that discovery is a legitimate agent skill, not a gift from the benchmark.

#### Change 3 — Pin baseline commits and assert bugs pre-run

Spring Boot tasks use manually-edited baseline repos with no commit pin and no pre-run assertion that the seeded bugs are present. A `git pull` or a fresh clone at a different commit can unseed the bugs, producing false passes. Angular/React tasks already guard against this (`workdir.py:50-51` raises `ValueError` if the seed patch's `old_str` isn't found). Prescribed: record a `baseline_commit` field on each task; add preflight assertions that the known bug strings are present before the model runs. This closes the biggest reproducibility gap — 27 of 99 original evals rest on an unguarded manual setup.

#### Change 4 — Pin temperature and context isolation across agent harnesses (ADR-0003)

The three agent CLIs inherit different defaults for temperature, session/skills/rules, and tool surface. `raw_api` pins `temperature=0.2`; the agent adapters pass no temperature flag. Two harnesses running the same model at different temperatures are not running the same experiment — the 3-run consistency metric is partly a temperature artifact. OpenCode doesn't disable project rules/skills/extensions; OMP and Hermes do. An OpenCode pass could be helped by a rule file the operator forgot to clean. Prescribed: pin temperature to a single value across all agent harnesses; force clean-slate context isolation (no project rules, skills, or extensions) on all three. Let the tool surface differ by design — it's the harness identity. Record `tool_set` as a column.

#### Change 5 — Implement harness queues (ADR-0001, backlog)

ADR-0001 specifies per-harness concurrency lanes with caps `raw_api=2, omp=1, opencode=1, hermes=1`. The code has none — `runner.main` is a single sequential loop. `run_all.py` fans out across 4 stacks as subprocesses, so up to 4 raw_api runs can execute concurrently (double the cap) while agent harnesses run serially within each stack. Two stack processes reaching the same agent CLI share session state with no lock. The serial loop hides this by accident; a queue would prevent it by design. The design is good; the implementation is incomplete. Prescribed: implement per-harness lanes that enforce the caps; add to backlog (done — see `docs/backlog.md`).

#### Change 6 — Add an agent-specific task tier (ADR-0004)

The 11 tasks were designed for single-shot: small, single-file, spec-precise. In agent mode they ceiling — 8 of 11 already ceiling for single-shot, and tools+iteration can only make passing easier. The benchmark cannot rank agent combinations on capability, only on efficiency (cost/iteration count). Prescribed: keep the 11 tasks frozen as the single-shot suite for historical comparability; add a second tier of agent-specific tasks (multi-file, cross-module, requires reading existing tests to infer intent) designed to discriminate among agent combinations on pass/fail, not just on cost.

### 3.3 Adapt the human-review rubric for agents

The original rubric was designed for single-shot code blocks. Agent output is a multi-file workdir diff plus a JSON event stream. Three assumptions break:

1. **Blind comparability** — agent transcripts carry harness identity in their event format. Prescribed: normalize to a unified diff format for review; hide the raw event stream.
2. **Effort axis (axis 5)** — "effort to production" is degenerate for passing agents (the agent did the integration). Prescribed: replace with "economy of change" — did the agent make minimal, surgical edits or rewrite half the repo?
3. **Scale** — 1,287 artifacts vs 99. Prescribed: the two-reviewer reconciliation process must be scoped or sampled for the agent tier.

Single-shot rubric: unchanged, 5 original axes, reviewed on code blocks. Agent rubric: axes 1–4 retained, axis 5 redefined as economy of change, reviewed on normalized diffs. Both stay double-blind on model identity.

## 4. Summary of prescribed changes

| # | Change | ADR | Priority |
|---|---|---|---|
| 1 | Add `capability_mode` + `telemetry_trust` columns | 0002 | high — blocks valid cross-cohort analysis |
| 2 | Withhold test command from agent prompt | — | high — agent task validity |
| 3 | Pin baseline commits + assert bugs pre-run | — | high — 27 evals unguarded |
| 4 | Pin temperature + context isolation across agents | 0003 | high — agent-vs-agent comparability |
| 5 | Implement harness queues | 0001 | medium — hidden by serial loop today |
| 6 | Add agent-specific task tier | 0004 | medium — needed for agent capability ranking |
| 7 | Separate format errors from capability failures | — | medium — extraction-path defect |
| 8 | Add isolated Angular unit tests | — | medium — 3 tasks have no functional gate |
| 9 | Adapt human-review rubric for agents | — | low — needed when agent review runs |
| 10 | Run human review on the 3 originals (retroactive) | — | low — recovers missing historical signal |

## 5. Decisions recorded this session

- `CONTEXT.md`: added `Capability Mode`, `Telemetry Trust`, `Benchmark Suite` terms.
- `docs/adr/0002-comparability-columns.md`: `capability_mode` + `telemetry_trust` columns (accepted).
- `docs/adr/0003-pin-agent-harness-settings.md`: pin temperature + isolation, let tools differ (accepted).
- `docs/adr/0004-two-tier-task-suite.md`: single-shot suite frozen, agent tier to be designed (accepted).
- `docs/backlog.md`: added harness-queue implementation item with acceptance criteria.

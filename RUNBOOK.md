# Benchmark Runbook

## 1. Prerequisites

```bash
pip install requests pandas
```

Verify CLI tools you plan to use:

```bash
omp --version && opencode --version && hermes --version
```

Baselines (non-data stacks):

```text
baselines/petclinic/          # git clone spring-petclinic, apply bugs per README
baselines/petclinic-feat1/    # separate clone for feat1 task
baselines/angular-conduit/    # npm ci once
baselines/react-conduit/      # npm ci once
```

## 2. Secrets

Never commit keys. `.env`, `openrouter_key.txt`, `opencode_key.txt` are gitignored.

| Harness | Env var | Key file |
|---|---|---|
| `raw_api` | `OPENROUTER_API_KEY`; `OPENCODE_API_KEY` / `OPENCODE_GO_API_KEY` for `opencode-go/*` models | `openrouter_key.txt`; `opencode_key.txt` for `opencode-go/*` |
| `omp` / `opencode` | `OPENCODE_API_KEY` | `opencode_key.txt` |
| `hermes` | `OPENCODE_GO_API_KEY` | `opencode_key.txt` (maps to both) |

```bash
printf '%s' 'sk-or-...' > openrouter_key.txt
printf '%s' '...' > opencode_key.txt
# or export OPENROUTER_API_KEY / OPENCODE_API_KEY / OPENCODE_GO_API_KEY
```

## 3. Preflight

`run_benchmark.py` runs preflight automatically before invoking any harness. Use `--preflight` to run the same checks and exit before spending model calls. It checks baselines, clean-baseline build prerequisites, keys, CLI binaries, model/harness compatibility, seeded bugs (Spring Boot), and CSV schema:

```bash
python run_benchmark.py --stack all --harness agent --models opencode-go --runs 1 --preflight
```

If preflight reports legacy CSV schema:

```bash
python run_benchmark.py --stack all --migrate-csv
```

## 4. Full runs

### 4.1 Raw API — single-shot baseline

```bash
# All stacks, 8 new models, 3 runs each
python run_all.py --wait

# Single stack
python run_benchmark.py --stack data --harness raw_api --models new --runs 3

# All stacks, all 11 models
python run_benchmark.py --stack all --harness raw_api --models all --runs 3

# Raw API via OpenCode Go HTTP API when using opencode-go models
python run_benchmark.py --stack data --harness raw_api --models opencode-go/deepseek-v4-flash --runs 3
```

### 4.2 OMP — agent-iterated

```bash
# One model through OMP
python run_benchmark.py --stack all --harness omp --models opencode-go/glm-5.2 --runs 3

# All curated OpenCode Go models through OMP
python run_benchmark.py --stack all --harness omp --models opencode-go --runs 3
```

### 4.3 OpenCode — agent-iterated

```bash
# One model
python run_benchmark.py --stack all --harness opencode --models opencode-go/glm-5.2 --runs 3

# All curated models
python run_benchmark.py --stack all --harness opencode --models opencode-go --runs 3
```

### 4.4 Hermes — agent-iterated

```bash
# One model
python run_benchmark.py --stack all --harness hermes --models opencode-go/glm-5.2 --runs 3

# All curated models
python run_benchmark.py --stack all --harness hermes --models opencode-go --runs 3
```

### 4.5 All agent harnesses at once

```bash
# All 3 agent harnesses, all curated models, all stacks
python run_benchmark.py --stack all --harness agent --models opencode-go --runs 3

# All 4 harnesses (raw_api + agents)
python run_benchmark.py --stack all --harness all --models opencode-go --runs 3
```

### 4.6 Mixed providers (per-harness model override)

```bash
python run_benchmark.py --stack all --harness omp,opencode,hermes \
  --models qwen/qwen3.7-plus \
  --adapter-model omp=opencode-go/qwen3.7-plus \
  --adapter-model opencode=opencode-go/qwen3.7-plus \
  --adapter-model hermes=opencode-go/qwen3.7-plus \
  --runs 3
```

### 4.7 Env default

If `.env` has `BENCHMARK_MODELS=opencode-go/deepseek-v4-flash`, omit `--models`:

```bash
python run_benchmark.py --stack all --harness agent --runs 3
```

### 4.8 Workdir cache

Prepare seeded task snapshots once, then point `.env` at that cache:

```bash
python prepare_workdir_cache.py --stack all --cache-dir .benchmark-cache/task-snapshots --refresh
printf '\n# Reuse seeded task snapshots; per-run workdirs are cloned from this path.\nBENCHMARK_WORKDIR_CACHE=.benchmark-cache/task-snapshots\n' >> .env

python run_benchmark.py \
  --stack all \
  --harness agent \
  --models opencode-go \
  --runs 3
```

On APFS/macOS, cached snapshots are copied with copy-on-write file clones when available; other filesystems fall back to normal file copies. The cache only changes setup speed: each run still gets an isolated workdir.

## 5. Parallelism

`run_benchmark.py` runs sequentially. Two ways to parallelize:

**By harness (safe, recommended):** each harness has independent CLI state (`~/.omp`, `~/.hermes`, etc.) and rate limits. Run 4 terminals:

```bash
python run_benchmark.py --stack all --harness raw_api   --models opencode-go --runs 3 --results-dir results/raw_api
python run_benchmark.py --stack all --harness omp       --models opencode-go --runs 3 --results-dir results/omp
python run_benchmark.py --stack all --harness opencode  --models opencode-go --runs 3 --results-dir results/opencode
python run_benchmark.py --stack all --harness hermes    --models opencode-go --runs 3 --results-dir results/hermes
```

Use `--results-dir` per harness — two processes appending to the same per-stack CSV will interleave rows. Merge dirs after:

```bash
python merge_metrics.py --results-dir results/raw_api results/omp results/opencode results/hermes
```

**By stack (`run_all.py`, caution):** fans out 4 stack subprocesses, all using the same `--harness`. Same harness across stacks can collide on CLI session state. Only safe for `raw_api` (stateless HTTP). For agent harnesses, prefer harness-fanout above.

```bash
python run_all.py --harness raw_api --models new --wait   # safe: stateless
python run_all.py --harness omp --models opencode-go --wait  # unsafe: OMP session collision
```

Harness queues (ADR-0001) are **not implemented**. The backlog item tracks per-harness concurrency lanes with caps `raw_api=2`, `omp=1`, `opencode=1`, `hermes=1`.

## 6. Resume and rerun

Default: resume. Skips existing rows by `(harness, task, model, run)`.

```bash
# Force reruns
python run_benchmark.py ... --no-resume

# Clean rerun: delete rows/workdirs or use separate dir
python run_benchmark.py ... --results-dir results/v2
```

## 7. Outputs

Per run:

```text
results/<harness>__<task>__<model>__r<run>/
  _raw_response.txt     # response or CLI transcript + changed files
  _build_output.txt     # on build failure
  _test_output.txt      # on test failure
  _error.txt            # on exception
```

Per-stack CSVs: `results/metrics_{springboot,angular,react,data}.csv`

| Column | Description |
|---|---|
| `harness` | `raw_api`, `omp`, `opencode`, `hermes` |
| `model` | Canonical model used for comparison/anonymization. |
| `adapter_model` | Harness/API selector actually passed after model mapping/fallback. |
| `provider_backend` / `api_backend` | Provider family and invocation backend that actually served the run. |
| `pricing_model` | Price table key used for `cost_usd`; may differ from `model` when fallback is used. |
| `capability_mode` | `single_shot` (raw API) or `agent_iterated` (agents). Comparable only within mode (ADR-0002). |
| `telemetry_trust` | `exact` (raw API), `parsed` (OMP/OpenCode JSON), `blank` (Hermes). Cost comparable only within trust+mode cohort. |
| `tool_set` | Agent tools: `read,bash,edit,write,grep,find,lsp` (OMP), `terminal,file` (Hermes), empty (raw API). |
| `build_ok` / `test_ok` | `True`/`False`/`ERROR` |
| `in_tok`, `out_tok`, `cost_usd`, `model_calls` | Telemetry. Blank for Hermes (`telemetry_trust=blank`). |
| `telemetry_note` | How measured or why unavailable. |
| `latency_s`, `workdir`, `transcript_path`, `error` | Run metadata. |

## 8. Consolidate and review

```bash
# Merge one or more fanout result dirs into a clean review dir.
python merge_metrics.py \
  --results-dir results/full_raw_api results/full_omp results/full_opencode results/full_hermes \
  --out-dir results/full_combined_v3

# Add --copy-artifacts when the combined dir must contain per-run workdirs too.
# Generate human-review artifacts only after audit/rescore/fair comparison below.
```

Outputs after merge: `metrics_all.csv`, `metrics_anon.csv`, `model_mapping.csv`.

Outputs after audit/rescore/fair comparison: `evaluation_audit.csv`, `posthoc_rescore.csv`, `metrics_fair.csv`, `metrics_fair_summary.md`, `fair_comparison_summary.md`, `fair_comparison_by_harness_model.csv`, `fair_comparison_by_task.csv`, `fair_comparison_status_counts.csv`, `fair_comparison_telemetry_gaps.csv`, `fair_failure_evidence.md`, and `infra_remediation_report.md`.

When a saved run looks suspiciously low, audit and rescore from saved artifacts before interpreting model quality:

```bash
python audit_results.py --results-dir results/full_combined_v3
python rescore_results.py --results-dir results/full_combined_v3
```

These commands do not invoke models. `audit_results.py` classifies infrastructure and extraction failures; `rescore_results.py` locally rebuilds only `posthoc_rescore_candidate` rows from saved `_raw_response.txt` transcripts and writes `posthoc_rescore.csv`, `metrics_fair.csv`, and `metrics_fair_summary.md`.

Regenerate the fair automatic comparison from that table:

```bash
python generate_fair_comparison.py --results-dir results/full_combined_v3
jupyter nbconvert --to notebook --execute --inplace benchmark_comparison.ipynb
```

Use `metrics_fair.csv` / `fair_comparison_summary.md` for automatic % tests verdes. Keep `metrics_all.csv` as the raw merged audit artifact, not as the final quality table. Treat the Wilson intervals and `low_n` warnings in the fair summary as ranking uncertainty, not model failures.

Regenerate human-review artifacts from the fair table:

```bash
python gen_plantilla.py --results-dir results/full_combined_v3
python gen_form_data.py
```

`gen_plantilla.py` defaults to `metrics_fair.csv` when present, excludes `fair_included=False` rows unless `--include-excluded` is passed, and writes `fair_status`, `fair_included`, `fair_notes`, and `automatic_source` into `human_review/plantilla_puntuacion.csv`.

Use `fair_failure_evidence.md` to inspect scored failures. Use `infra_remediation_report.md` to fix baseline/setup issues before a future rerun. Use `fair_comparison_telemetry_gaps.csv` to exclude rows with missing exact token/cost telemetry from quality/cost calculations; current Hermes rows have pass-rate evidence but no exact cost/token telemetry.

Do not reveal `model_mapping.csv` until human review is complete.

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| `opencode` can't see Go models | `/connect` → OpenCode Go → paste key, or set `OPENCODE_API_KEY` |
| OpenCode Go usage limit | Wait for reset, enable balance fallback, or switch model |
| `raw_api` missing key | OpenRouter models need `OPENROUTER_API_KEY` / `openrouter_key.txt`; `opencode-go/*` models need `OPENCODE_API_KEY` / `OPENCODE_GO_API_KEY` / `opencode_key.txt` |
| React tests hang | Runner sets `CI=true`; don't remove |
| Missing `node_modules` | `npm ci` in the baseline repo |
| Missing Angular theme asset | Re-run the Angular RealWorld setup/submodule step; preflight should fail before model invocation if `realworld/assets/theme/styles.css` is absent. |
| Clean baseline build failure | Fix the baseline first. These are infrastructure failures, not model-quality failures. |
| Suspicious raw API snippet written as target file | Run `python audit_results.py --results-dir <dir>`; hardened extraction ignores reasoning/example snippets and records format errors separately. |
| CLI adapter fails | Inspect `_raw_response.txt` + `_error.txt`; rerun with `--no-resume` |
| Telemetry columns blank | Check `fair_comparison_telemetry_gaps.csv`. `blank` = expected for current Hermes oneshot CLI and means pass-rate rows are usable but quality/cost ranking must exclude Hermes until exact usage exists. Others: inspect CLI output. |
| Legacy CSV schema | `python run_benchmark.py --stack all --migrate-csv` |

## 10. Stop criteria

1. Every planned `(harness, task, model, run)` has one CSV row.
2. Preflight passes before any model invocation.
3. No `build_ok=ERROR` or `test_ok=ERROR` unless documented as infrastructure failure.
4. `metrics_all.csv` regenerated and, when audit/rescore was needed, `metrics_fair.csv`, `fair_comparison_summary.md`, `fair_failure_evidence.md`, `infra_remediation_report.md`, and `fair_comparison_telemetry_gaps.csv` regenerated.
5. Human-review artifacts regenerated from `metrics_fair.csv` if reviewers will score new runs; `plantilla_puntuacion.csv` should have `automatic_source=.../metrics_fair.csv` and no `fair_included=False` rows unless deliberately included.

## 11. Backlog

`docs/backlog.md` — open items include Hermes per-run telemetry from machine-readable source, per-harness concurrency queues (ADR-0001), and result-audit follow-ups from saved benchmark artifacts.

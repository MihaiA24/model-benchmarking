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
| `raw_api` | `OPENROUTER_API_KEY` | `openrouter_key.txt` |
| `omp` / `opencode` | `OPENCODE_API_KEY` | `opencode_key.txt` |
| `hermes` | `OPENCODE_GO_API_KEY` | `opencode_key.txt` (maps to both) |

```bash
printf '%s' 'sk-or-...' > openrouter_key.txt
printf '%s' '...' > opencode_key.txt
# or export OPENROUTER_API_KEY / OPENCODE_API_KEY / OPENCODE_GO_API_KEY
```

## 3. Preflight

Always run before a batch. Checks baselines, keys, CLI binaries, model/harness compatibility, seeded bugs (Spring Boot), and CSV schema:

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
| `capability_mode` | `single_shot` (raw API) or `agent_iterated` (agents). Comparable only within mode (ADR-0002). |
| `telemetry_trust` | `exact` (raw API), `parsed` (OMP/OpenCode JSON), `blank` (Hermes). Cost comparable only within trust+mode cohort. |
| `tool_set` | Agent tools: `read,bash,edit,write,grep,find,lsp` (OMP), `terminal,file` (Hermes), empty (raw API). |
| `build_ok` / `test_ok` | `True`/`False`/`ERROR` |
| `in_tok`, `out_tok`, `cost_usd`, `model_calls` | Telemetry. Blank for Hermes (`telemetry_trust=blank`). |
| `telemetry_note` | How measured or why unavailable. |
| `latency_s`, `workdir`, `transcript_path`, `error` | Run metadata. |

## 8. Consolidate and review

```bash
python merge_metrics.py && python gen_plantilla.py && python gen_form_data.py
```

Outputs: `metrics_all.csv`, `metrics_anon.csv`, `model_mapping.csv`, `human_review/plantilla_puntuacion.csv`, `human_review/form_data.json`

Do not reveal `model_mapping.csv` until human review is complete.

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| `opencode` can't see Go models | `/connect` → OpenCode Go → paste key, or set `OPENCODE_API_KEY` |
| OpenCode Go usage limit | Wait for reset, enable balance fallback, or switch model |
| `raw_api` missing key | `OPENROUTER_API_KEY` or `openrouter_key.txt` |
| React tests hang | Runner sets `CI=true`; don't remove |
| Missing `node_modules` | `npm ci` in the baseline repo |
| CLI adapter fails | Inspect `_raw_response.txt` + `_error.txt`; rerun with `--no-resume` |
| Telemetry columns blank | Check `telemetry_trust`. `blank` = expected for Hermes. Others: inspect CLI output. |
| Legacy CSV schema | `python run_benchmark.py --stack all --migrate-csv` |

## 10. Stop criteria

1. Every planned `(harness, task, model, run)` has one CSV row.
2. No `build_ok=ERROR` or `test_ok=ERROR` unless documented as infrastructure failure.
3. `metrics_all.csv` regenerated.
4. Human-review artifacts regenerated if reviewers will score new runs.

## 11. Backlog

`docs/backlog.md` — open items: (1) Hermes per-run telemetry from machine-readable source; (2) per-harness concurrency queues (ADR-0001).

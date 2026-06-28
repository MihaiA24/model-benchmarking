# Benchmark Runbook

Operational checklist for running the model + harness benchmark.

## 1. Scope

This repo can run the same 11 tasks through these harnesses:

- `raw_api` — direct OpenRouter chat-completions baseline.
- `omp` — Oh My Pi coding agent CLI.
- `opencode` — OpenCode CLI.
- `hermes` — Hermes Agent CLI.

The runner writes per-stack CSVs in `results/` and one transcript per run in the run workdir.

## 2. Prerequisites

From the repo root:

```bash
pip install requests pandas
```

Install and authenticate the agent CLIs you plan to use:

```bash
omp --version
opencode --version
hermes --version
```

Baseline repos must exist before running non-data stacks:

```text
baselines/petclinic/
baselines/petclinic-feat1/
baselines/angular-conduit/
baselines/react-conduit/
```

For Angular/React, run `npm ci` once inside each baseline. The runner copies the baseline without `node_modules` and links the baseline `node_modules` into each workdir.

## 3. Secrets

Never commit real keys. `.env`, `openrouter_key.txt`, and `opencode_key.txt` are ignored by git.

### OpenRouter / raw API

Either export:

```bash
export OPENROUTER_API_KEY='sk-or-...'
```

or put it in `.env` / the legacy key file:

```bash
printf 'OPENROUTER_API_KEY=%s\n' 'sk-or-...' >> .env
printf '%s' 'sk-or-...' > openrouter_key.txt
```

### OpenCode Go subscription

OpenCode Go uses `OPENCODE_API_KEY` for OMP/OpenCode, `OPENCODE_GO_API_KEY` for Hermes, and model IDs in the format `opencode-go/<model-id>`. The runner maps `opencode_key.txt` to both env vars.

Either connect through the OpenCode TUI:

```text
/connect -> OpenCode Go -> paste key
/models
```

or export / `.env` / file-load the key for non-interactive runs:

```bash
export OPENCODE_API_KEY='...'
export OPENCODE_GO_API_KEY="$OPENCODE_API_KEY"  # needed by Hermes if you do not use opencode_key.txt
printf 'OPENCODE_API_KEY=%s\n' '...' >> .env
printf 'BENCHMARK_MODELS=%s\n' 'opencode-go/deepseek-v4-flash' >> .env  # optional default for run_benchmark.py
# or, easiest for this repo:
printf '%s' '...' > opencode_key.txt
```

Official docs: <https://dev.opencode.ai/docs/go/>

## 4. Smoke checks

Check model slugs for raw API:

```bash
python test_slugs.py
```

Run preflight before any long batch. It checks baselines, keys, CLI binaries, model/harness compatibility, seeded bug presence (Spring Boot), and legacy CSV schema:

```bash
python run_benchmark.py \
  --stack all \
  --harness opencode \
  --models opencode-go/qwen3.7-plus \
  --runs 1 \
  --preflight
```

Check every OpenCode Go model planned by the preset:

```bash
python run_benchmark.py \
  --stack data \
  --task data-bug1-sales-genre \
  --harness opencode \
  --models opencode-go \
  --runs 1 \
  --dry-run
```

If preflight reports a legacy CSV schema, migrate explicitly once:

```bash
python run_benchmark.py --stack all --migrate-csv
```

`--dry-run` only prints the plan; it does not validate baselines or secrets.

## 5. Common run commands

### Legacy raw API run, all stacks

```bash
python run_all.py --wait
```

### One stack via raw API

```bash
python run_benchmark.py --stack data --harness raw_api --models new --runs 3
```

### OpenCode Go subscription run

Run one OpenCode Go model through all agent harnesses. If `.env` contains
`BENCHMARK_MODELS=opencode-go/deepseek-v4-flash`, omit `--models`; the CLI flag
still overrides `.env`:

```bash
python run_benchmark.py \
  --stack all \
  --harness agent \
  --runs 3
```

Run all curated OpenCode Go subscription models through all agent harnesses:

```bash
python run_benchmark.py \
  --stack all \
  --harness agent \
  --models opencode-go \
  --runs 3
```

### Compare mixed providers deliberately

Only use `--adapter-model` when you intentionally want a canonical reporting label but a different provider selector per harness:

```bash
python run_benchmark.py \
  --stack all \
  --harness omp,opencode,hermes \
  --models qwen/qwen3.7-plus \
  --adapter-model omp=opencode-go/qwen3.7-plus \
  --adapter-model opencode=opencode-go/qwen3.7-plus \
  --adapter-model hermes=opencode-go/qwen3.7-plus \
  --runs 3
```

## 6. Resume and rerun policy

Default behavior is resume. Existing completed rows are skipped by:

```text
(harness, task, model, run)
```

To force reruns:

```bash
python run_benchmark.py ... --no-resume
```

To rerun cleanly, delete the relevant CSV rows and workdirs first, or use a separate `--results-dir`.

## 7. Outputs

Per run workdir:

```text
results/<harness>__<task>__<model>__r<run>/
  _raw_response.txt     # raw API response or CLI transcript + changed files
  _build_output.txt     # only on build failure
  _test_output.txt      # only on test failure
  _error.txt            # only on adapter/runner exception
```

Per-stack CSVs:

```text
results/metrics_springboot.csv
results/metrics_angular.csv
results/metrics_react.csv
results/metrics_data.csv
```

Important columns:

- `harness`
- `task`
- `model`
- `run`
- `capability_mode` — `single_shot` (raw API, one pass, no tools) or `agent_iterated` (agent harness with tools and iteration). Runs are comparable only within a capability mode (ADR-0002).
- `telemetry_trust` — `exact` (raw API, machine-read usage), `parsed` (CLI JSON event stream), or `blank` (no machine-readable source; Hermes). Cost and tokens are comparable only within cohorts sharing both capability mode and telemetry trust.
- `tool_set` — tools available to the agent harness (`read,bash,edit,write,grep,find,lsp` for OMP, `terminal,file` for Hermes, empty for raw API).
- `build_ok`
- `test_ok`
- `in_tok`, `out_tok`, `cost_usd`, `model_calls`, `telemetry_note` — telemetry per run. `raw_api` is exact for one OpenRouter request; `omp`/`opencode` are filled when their JSON streams expose usage records; `hermes` currently marks telemetry unavailable because its oneshot CLI only prints final text.
- `latency_s`
- `workdir`
- `transcript_path`
- `error`

## 8. Consolidate and prepare review

```bash
python merge_metrics.py
python gen_plantilla.py
python gen_form_data.py
```

Outputs:

```text
results/metrics_all.csv
results/metrics_anon.csv
results/model_mapping.csv
human_review/plantilla_puntuacion.csv
human_review/form_data.json
human_review/respuestas_ciegas/
```

Do not reveal `results/model_mapping.csv` until human review is complete.

## 9. Troubleshooting

| Symptom | Check | Fix |
|---|---|---|
| `opencode` cannot see Go models | `opencode models` | Run `/connect`, select OpenCode Go, paste key; or set `OPENCODE_API_KEY`. |
| OpenCode Go hits usage limit | OpenCode Go console | Wait for reset, enable balance fallback, or switch model. |
| `raw_api` missing key | `OPENROUTER_API_KEY` / `openrouter_key.txt` | Export key or create the key file. |
| React tests hang | `CI=true` | Runner sets `CI=true`; do not remove it. |
| Angular/React workdir cannot find packages | baseline `node_modules` missing | Run `npm ci` in the baseline repo. |
| CLI adapter fails but code changed | inspect `_raw_response.txt` and `_error.txt` | Fix CLI auth/model selector, then rerun with `--no-resume` if needed. |
| `model_calls` / token columns are blank | inspect `telemetry_note` and `telemetry_trust` | `telemetry_trust=blank` means no machine-readable source (expected for Hermes). For Hermes use provider billing/logs; for `raw_api`/`omp`/`opencode` check CLI output in `_raw_response.txt`. |

## 10. Stop criteria

A benchmark batch is complete when:

1. Every planned `(harness, task, model, run)` has one CSV row.
2. No row has `build_ok=ERROR` or `test_ok=ERROR` unless documented as infrastructure failure.
3. `merge_metrics.py` has regenerated `metrics_all.csv`.
4. Human-review artifacts have been regenerated if reviewers will score the new runs.

## 11. Backlog

Open implementation tasks live in `docs/backlog.md`. Current open items: (1) make Hermes per-run telemetry (`model_calls`, tokens, cost) auditable from a machine-readable source instead of relying on the current `telemetry_note`; (2) implement per-harness concurrency queues (ADR-0001) — the current runner is sequential and `run_all.py` can exceed the `raw_api=2` cap.

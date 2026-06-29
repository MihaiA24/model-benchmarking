# Backlog

## Strict evaluator and preflight guards

Status: implemented

Goal: make the benchmark strict without turning harness defects into model-quality failures. The current implementation slice is to harden raw API extraction and setup checks, then audit the already-run `results/full_combined_v3` artifacts; do not invoke models or rerun benchmark evaluations for this slice.

Acceptance:
- Raw API extraction ignores reasoning/example snippets and writes the intended complete-file answer, with format errors recorded separately from build/test failures.
- Preflight catches missing/broken baseline prerequisites before a model is invoked, including build-tool dependencies and baseline build failures.
- Existing artifacts under `results/full_combined_v3` remain the evidence source for reporting; any post-hoc audit must be derived from saved transcripts/workdirs, not fresh model calls.

Implementation notes:
- `benchmark/adapters/raw_api.py` now strips `<think>` blocks and extracts the final visible fenced code block; missing/empty blocks raise `format_error`.
- `benchmark/runner.py` now runs preflight automatically before harness invocation and checks clean-baseline builds in temporary workdirs.
- `audit_results.py` audits saved artifacts without invoking models and writes `evaluation_audit.csv` plus `evaluation_audit_summary.md` under the selected results dir.

## Post-hoc local rescore from saved transcripts

Status: implemented

Goal: recover a fair automatic result table from `results/full_combined_v3` without invoking any model/API/agent harness. Only rows marked `posthoc_rescore_candidate` by `audit_results.py` are in scope; infrastructure exclusions stay excluded and true semantic/verifier failures stay failures.

Acceptance:
- Rebuild each candidate from the original seeded baseline plus the hardened final-code extraction from its saved `_raw_response.txt`.
- Run only local build/test checks for those candidates; do not call OpenRouter, OpenCode, OMP, Hermes, or any model CLI.
- Write auditable outputs under `results/full_combined_v3` that show original vs rescored status and an adjusted fair summary.

Implementation notes:
- `rescore_results.py` selects only `posthoc_rescore_candidate` rows from the saved audit, rebuilds them locally, and writes `posthoc_rescore.csv`, `metrics_fair.csv`, and `metrics_fair_summary.md`.
- Current `results/full_combined_v3` rescore: 13 candidates, 11 pass, 2 fail; fair scored pass rate is 250/275 after excluding 121 infrastructure rows.
- The 2 remaining post-hoc failures are React author-filter outputs that import a missing `FILTER_BY_AUTHOR` constant; they remain real local build failures.

## Fair automatic comparison refresh

Status: implemented

Goal: make `results/full_combined_v3/metrics_fair.csv` the source table for automatic pass-rate comparison and regenerate the comparison summary from that table. Raw `metrics_all.csv` remains the immutable merged-run artifact, but it must not drive model-quality summaries after audit/rescore.

Acceptance:
- `benchmark_comparison.ipynb` loads `metrics_fair.csv` when present and uses `fair_build_ok` / `fair_test_ok` / `fair_included` for pass-rate, failure, and infrastructure-exclusion calculations.
- A checked-in, human-readable summary is generated under `results/full_combined_v3` from `metrics_fair.csv`.
- Documentation points reviewers to the fair automatic table/summary before human scoring or final interpretation.

Implementation notes:
- `generate_fair_comparison.py` writes `fair_comparison_summary.md`, `fair_comparison_by_harness_model.csv`, `fair_comparison_by_task.csv`, and `fair_comparison_status_counts.csv` from `metrics_fair.csv`.
- `benchmark_comparison.ipynb` now loads `metrics_fair.csv` when present, keeps raw/excluded rows visible as `all_df`/`excluded_df`, and uses only fair-included rows for model-quality pass rates.
- Current fair comparison summary: 396 merged rows, 275 scored rows, 121 excluded rows, and 250/275 fair automatic passes.

## Human review and evidence hardening

Status: implemented

Goal: close the remaining mismatch between the fair automatic table and downstream human-review/final-comparison artifacts. `metrics_fair.csv` must be the default source wherever humans see automatic status, and comparison outputs must carry denominator uncertainty, failure evidence, infrastructure remediation, and telemetry completeness signals.

Acceptance:
- `gen_plantilla.py` defaults to `results/full_combined_v3/metrics_fair.csv` when present, excludes `fair_included=False` infrastructure rows unless explicitly requested, and writes fair status/source columns into `plantilla_puntuacion.csv`.
- `gen_form_data.py` propagates fair automatic status into `form_data.json` so reviewers see the same signal as the fair summary.
- `generate_fair_comparison.py` adds Wilson confidence intervals and low-denominator warnings, writes a scored-failure evidence index, writes an infrastructure remediation report, and marks missing Hermes cost/token telemetry as unavailable rather than silently blank.
- Documentation names these generated artifacts and keeps raw `metrics_all.csv` as audit input only.

Implementation notes:
- `gen_plantilla.py` now accepts `--results-dir`, prefers `metrics_fair.csv`, filters infrastructure rows by default, and emits `build_ok_auto`, `test_ok_auto`, `fair_status`, `fair_included`, `fair_notes`, and `automatic_source`.
- `gen_form_data.py` carries those fair automatic fields into the Google Forms JSON; the current fair review pack has 94 scored representative rows and no `fair_included=False` rows.
- `generate_fair_comparison.py` now writes `fair_comparison_telemetry_gaps.csv`, `fair_failure_evidence.csv/.md`, and `infra_remediation_report.csv/.md` in addition to the existing fair comparison outputs.
- Current telemetry gap is explicit: Hermes has pass-rate evidence but 0 exact cost/token rows, so Hermes rows must be excluded from quality/cost calculations until a trustworthy usage source is implemented.

## Hermes per-run telemetry

Status: open

Goal: make Hermes benchmark rows populate `model_calls`, `in_tok`, `out_tok`, and `cost_usd` from a trustworthy machine-readable source instead of leaving them blank with a `telemetry_note`.

Context:
- Current Hermes adapter uses `hermes -z` oneshot mode.
- That CLI path exposes final output but not per-run usage records.
- Do not infer cost/tokens from transcript text unless the row is explicitly marked as an estimate.

Design questions for a `grill-with-docs` session:
1. Source of truth: Hermes JSON/log export, provider billing API, or local OpenAI-compatible proxy?
2. Scope: exact `model_calls` only, exact tokens/cost too, or estimates accepted with a separate note?
3. Storage: keep usage only in CSV fields, or also persist raw usage events beside `_raw_response.txt`?
4. Failure mode: should missing Hermes telemetry fail preflight, warn, or keep current blank fields?

Recommended implementation path:
1. First verify whether Hermes can emit per-session usage through `hermes logs`, session export, or SDK hooks.
2. If Hermes cannot emit it, route Hermes provider traffic through a local logging proxy and parse proxy usage records.
3. Add Hermes-specific extraction in `benchmark/adapters/cli.py` without changing OMP/OpenCode parsing.
4. Add a smoke run for `data-bug1-sales-genre` proving Hermes telemetry fields are populated from the selected source.
5. Update `RUNBOOK.md`, `README.md`, and `CONTEXT_PROMPT.md` with the selected telemetry source and failure semantics.

Acceptance:
- Hermes CSV rows have non-empty `model_calls`, `in_tok`, `out_tok`, and `cost_usd`, or a deliberate `telemetry_note` explaining why a value is unavailable.
- The raw usage artifact can be audited after a run.
- OMP/OpenCode/raw API telemetry behavior remains unchanged.

## Harness queue implementation

Status: open

Goal: implement the per-harness concurrency lanes specified in ADR-0001, which the current sequential runner does not honor.

Context:
- `runner.main` runs all planned (harness, task, model, run) tuples in a single sequential `for` loop; no per-harness lane exists.
- `run_all.py` fans out across the 4 stacks as subprocesses, so up to 4 raw_api runs can execute concurrently (double the ADR-0001 cap of `raw_api=2`) while agent harnesses run serially within each stack.
- Two stack processes reaching the same agent CLI (e.g. OMP) at the same time share `~/.omp` session state with no lock, risking the CLI/session collisions ADR-0001 was written to prevent.
- The glossary term `Harness Queue` (CONTEXT.md) names a concept with no implementation referent.

Acceptance:
- A per-harness concurrency lane enforces the caps `raw_api=2`, `omp=1`, `opencode=1`, `hermes=1`.
- `run_all.py` stack-fanout cannot exceed a harness's lane cap (shared coordinator or cross-process semaphore).
- Two concurrent runs of the same agent CLI are prevented from colliding on shared session/config state.
- The serial single-stack path (`run_benchmark.py` without `run_all.py`) continues to work unchanged.

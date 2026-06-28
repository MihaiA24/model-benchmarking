# Backlog

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

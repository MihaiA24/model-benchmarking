# Use Harness Queues for Agent Benchmark Runs

Status: accepted

The benchmark runner will keep `raw_api` as a control harness and add OMP, OpenCode, and Hermes as agent harnesses behind per-harness queues. Runs keep a canonical model ID in CSVs, use harness-specific adapter model selectors only at invocation time, serialize metrics through a coordinator writer in planned order, and abort a harness queue only on preflight failure or repeated infrastructure failures. This preserves comparable historical metrics while avoiding CLI/session collisions and false precision in agent telemetry.

## Considered Options

- Stack-only parallelism: lower risk, but wastes capacity once agent harnesses are added.
- One global worker pool: faster, but hides harness-specific rate limits and session-state risks.
- Harness queues: chosen because OMP, OpenCode, Hermes, and raw API have different credentials, CLI behavior, and telemetry surfaces.

## Consequences

- Default caps are conservative: `raw_api=2`, `omp=1`, `opencode=1`, `hermes=1`.
- `--models opencode-go` means OpenCode Go provider selectors for agent harnesses only; raw API remains an explicit OpenRouter control path.
- Cost/call telemetry uses machine-readable usage when available and notes unavailable or price-table-derived values in `telemetry_note`.

# Record Capability Mode and Telemetry Trust as CSV Columns

Status: accepted

The harness work added agent harnesses (OMP, OpenCode, Hermes) with a different capability surface and different telemetry reliability to the same per-stack CSVs that hold the historical single-shot raw API data. A raw API pass and an agent-harness pass are not the same achievement, and an exact single-request cost is not comparable to a parsed multi-iteration cost, but the original schema let them look identical. We add `capability_mode` (`single_shot` | `agent_iterated`) and `telemetry_trust` (`exact` | `parsed` | `blank`) as first-class columns so the comparability boundary is a recorded field, not an implication of the `harness` column. Runs are comparable only within cohorts that share both values; cross-cohort comparisons are explicitly out of scope.

## Considered Options

- Accept the conflation and rely on the `harness` column: rejected because implying a boundary is not recording it, and a benchmark whose core validity claim rests on implication is not doing its job.
- Split agent-harness rows into a separate CSV: rejected because it fragments the historical comparison unnecessarily.
- Normalize the agent prompt to match raw API (no tools, one shot): rejected because it defeats the purpose of testing agent harnesses.

## Consequences

- `migrate_csv_schema` must add both columns to legacy CSVs; existing rows get `capability_mode=single_shot` and `telemetry_trust=exact` (raw API) or `blank` (pre-harness agent rows, if any).
- Hermes rows stay `telemetry_trust=blank` until a machine-readable usage source is found; the backlog task becomes raising Hermes from `blank` to `parsed`.
- Cost and token columns remain incomparable across cohorts; any cross-cohort cost chart must be explicitly labeled as such or omitted.

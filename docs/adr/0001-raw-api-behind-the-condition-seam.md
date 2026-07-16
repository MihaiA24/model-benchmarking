# Raw API Baseline sits behind the Condition seam

Functional V1 has four comparison conditions but only three Harnesses: the Raw API Baseline is deliberately not a Harness (see CONTEXT.md), yet it shares the Condition Lock shape, the 12-cell schedule, and the in-image launch dispatch. We decided the common Condition interface — the `ConditionDefinition` registry planned for the post-#75 deepening — covers all four conditions as Condition Adapters, with `kind: harness | baseline` carried as data and consulted only where Harness-ranking eligibility matters. The alternative, a Harness-only interface with raw-api bespoke at every dispatch site, preserved the glossary's "not a fourth harness" guard syntactically but froze `condition == "raw-api"` special cases into the coordinator, the image build, and every future test suite.

## Consequences

- `HARNESS_CONDITIONS` is derived from the registry, never hand-maintained.
- The condition conformance suite exercises all four adapters, including each digest-pinned launch module executed against the current runtime interfaces. The motivating incident: `raw_api_launch.py` drifted against `RawApiResult` (read a `status` field that does not exist) and the drift was digest-sealed into the raw-api Condition Lock unnoticed, because no test crossed that seam (found 2026-07-16).
- "Condition Adapter" in CONTEXT.md is the canonical term. Do not re-split the Raw API Baseline out of the Condition seam to "simplify" the interface — the split was considered and rejected here.

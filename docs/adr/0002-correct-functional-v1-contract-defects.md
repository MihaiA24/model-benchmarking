# Correct Functional V1 contract defects under new identities

Functional V1 Run `019f85a7-0637-77a4-a0a0-b79d3923fc15` was complete and evidence-valid, but it did not support a clean capability comparison: OMP and Hermes made the correct Python repair before Trusted Submission Capture rejected a repository-local generated CSV that OpenCode alone removed, while every Raw API Baseline cell failed response materialization on an SSE metadata trailer. We decided to preserve the sealed run as diagnostic evidence, classify these as Comparison Contract Defects rather than infrastructure-invalid attempts or unqualified Harness losses, correct the contracts under new identities, and rerun the full 12-cell cross-product rather than replace selected valid outcomes.

## Consequences

- The Python Scenario remains repair-only: its example output moves outside the Evaluated Repository, and OpenCode-specific post-run cleanup is removed rather than generalized.
- The Raw API Baseline accepts metadata-only SSE trailers after `[DONE]` while continuing to reject duplicate terminators and post-termination choice content.
- Provider-token usage warns above the 250,000-token Advisory Token Threshold in CLI inspect output, its JSON projection, the Markdown readout, and the HTML dashboard. The Token Stop Threshold is 375,000 tokens, enforced after complete provider responses with explicit overshoot; no duplicate warning flag enters the canonical Run Record.
- Provisioned OMP native binaries are excluded from native diagnostic collection and remain identified by their immutable Condition Lock inputs.
- Two complete corrected runs use MiMo v2.5 and DeepSeek v4 Flash separately. Their model strata are never pooled, and neither run replaces or rewrites the original evidence.

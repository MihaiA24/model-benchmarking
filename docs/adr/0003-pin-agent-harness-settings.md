# Pin Temperature and Context Isolation Across Agent Harnesses

Status: accepted

Within the `agent_iterated` capability mode, the three agent harnesses (OMP, OpenCode, Hermes) must be comparable to each other. Their CLIs inherit different defaults for temperature, session/skills/rules, and tool surface. Temperature and context isolation are nuisance variables — they affect model output but do not define what a harness is. The tool surface is the identity variable — it is what makes OMP different from Hermes. We pin temperature to a single value and force clean-slate context isolation (no project rules, skills, or extensions) on all three agent harnesses, while letting the tool surface differ by design. The `tool_set` column records which tools each harness used. Without this, an agent-vs-agent ranking conflates model behavior with CLI default noise.

## Considered Options

- Test harnesses as-shipped with CLI defaults: rejected because uncontrolled temperature makes the 3-run consistency metric partly a temperature artifact, and uncontrolled context isolation lets an OpenCode rule file silently help a pass.
- Pin everything including tools: rejected because the tool surface is the harness's identity — erasing it defeats research question (b), and CLIs do not all expose the same tool knobs.
- Record settings as columns without pinning: rejected because visibility is not control; the comparison remains noisy.

## Consequences

- All agent adapters must pass an explicit `temperature` flag to their CLI, overriding the CLI default.
- All agent adapters must disable project rules, skills, and extensions; OMP already does (`--no-session --no-skills --no-rules --no-extensions`), OpenCode and Hermes must match.
- Changing the pinned temperature in the future invalidates comparability with all prior agent runs at the old value.
- The `tool_set` column is added to the CSV schema alongside `capability_mode` and `telemetry_trust` (ADR-0002).

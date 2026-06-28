# Two-Tier Task Suite for Single-Shot and Agent Modes

Status: accepted

The 11-task suite was designed and calibrated for single-shot capability (research question a): small, single-file, spec-precise problems. In agent-iterated mode (research question b), where the harness has tools, file access, iteration, and the build command, these tasks ceiling — the discriminating power that was already low (8 of 11 tasks at zero automatic discrimination for single-shot) drops further. Reusing the same tasks and ranking agents on cost/iteration alone measures efficiency, not capability. We keep the 11 tasks frozen as the single-shot suite for historical comparability, and add a second tier of agent-specific tasks (multi-file, cross-module, requires reading existing tests to infer intent) designed to discriminate among agent combinations on capability. The single-shot suite is never modified; the agent suite is designed under the criterion that its tasks must separate agent combinations on pass/fail, not just on cost.

## Considered Options

- Reuse the 11 tasks as-is for agents: rejected because a suite that ceilings cannot rank on capability, only on efficiency.
- Reclassify the 11 tasks as smoke tests and abandon agent benchmarking: rejected because it leaves research question (b) with no discriminating instrument.
- Withhold the spec prose to harden the existing tasks for agents: rejected because it changes the task semantics while keeping the same file, muddying what "the same task" means across capability modes.

## Consequences

- The single-shot suite stays frozen; any change invalidates comparability with the 3-model historical dataset.
- The agent suite is new work; its tasks must be designed so that at least some discriminate among agent combinations on build/test pass/fail, not just on iteration count or cost.
- The two suites are disjoint: agent tasks are not run single-shot, and single-shot tasks are not used to rank agents (though they may serve as a regression smoke test for agent harnesses).

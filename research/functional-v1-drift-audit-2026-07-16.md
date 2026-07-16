# Functional V1 — implementation drift audit (handoff)

**Date:** 2026-07-16 · **Audited ref:** `origin/master` @ `486d45a` (merge of PR #82, pinned Hermes condition)
**Method:** detached read-only worktree + six parallel per-contract audits + the repo's own verification gate (`scripts/verify.py`) + full dev-tier pytest run.
**Audience:** a future agent session. Facts below were verified against code at `486d45a`; anything merged after that ref (notably issue #36) must be re-verified with the playbook at the bottom. Matching facts were also retained in agent long-term memory (query: "drift audit 486d45a").

## Context at audit time

- Map [Define a minimal local Functional V1 benchmark #66](https://github.com/MihaiA24/model-benchmarking/issues/66) is closed — destination reached, ten-ticket route.
- Merged & audited: [#73](https://github.com/MihaiA24/model-benchmarking/issues/73) (PR #77), [#74](https://github.com/MihaiA24/model-benchmarking/issues/74) (PR #76), [#40](https://github.com/MihaiA24/model-benchmarking/issues/40) (PR #78), [#32](https://github.com/MihaiA24/model-benchmarking/issues/32) (PR #79), [#33](https://github.com/MihaiA24/model-benchmarking/issues/33)/[#34](https://github.com/MihaiA24/model-benchmarking/issues/34)/[#35](https://github.com/MihaiA24/model-benchmarking/issues/35) (PRs #80–#82).
- Open route: [#36](https://github.com/MihaiA24/model-benchmarking/issues/36) (execution coordinator — **claimed, assigned 2026-07-15T22:49Z, expected merged by the time you read this**) → [#37](https://github.com/MihaiA24/model-benchmarking/issues/37) (capture/sealing) → [#75](https://github.com/MihaiA24/model-benchmarking/issues/75) (twelve-cell acceptance run).
- Tracker hygiene already done in this audit: removed stale `blocked` label from #36 (its only native blocker #32 was closed). #37/#75 `blocked` labels were accurate.

## Verified MET at 486d45a — do not re-audit unless these files changed

| Contract | Verdict | Key evidence |
|---|---|---|
| #73 hosted-authority removal | 4/4 MET | no `.github/`, no `fresh_authoritative`/CheckRun/publisher code; local gate retained (`verification/policy.py`, `scripts/verify.py` with `audit-policy`/`select`/`run-development`); runtime→verification import boundary enforced by `tests/architecture/test_import_boundaries.py` |
| #74/#70 operator contract & CLI | 20/20 MET | `cli.py:33-61` exactly `provision/preflight/run/inspect`; strict YAML loader rejects unknown fields/aliases/dupes (`declarations/functional_v1.py:76-144`); write-once records via `_immutable_write` (`runtime/functional_v1.py:117-162`); coordinator lease `:195-215`; exit codes 0/1/2/3 `cli.py:136-147`; 5 typed digest kinds (`declarations/identities.py:34-39`) |
| #32 proxy / Raw API / common runtime | MET | real key only host-side; `ConditionRunner` rejects `PROVIDER_API_KEY_ENV` in child env (`runtime/conditions.py:60`); exactly 3 sealed env names to harnesses; Raw API in common runtime (`runtime/raw_api.py`), not a 4th adapter; 21 acceptance tests, RecordingProvider deterministic |
| #33/#34/#35 pinned conditions | MET | pins match decision #67: OMP `v16.4.0` (`omp.py:31`), OpenCode `v1.17.18` (`opencode.py:32`), Hermes `9de9c25…` = v0.18.2 (`hermes.py:32-34`); locks at `profiles/functional-v1/*.condition.json` digest-sealed; shim sha256s recomputed and matching; 4 acceptance tests per condition; committed evidence at `artifacts/acceptance/issue-{33,34,35}/verification.json` |
| #40/#29 scenarios & authoring | MET | exactly 3 packages under `scenarios/calibration/` matching the fixed slice (python-sales-by-genre, spring-petvalidator-whitespace, angular-reading-time); 7 isolated qualification cases each in `artifacts/qualification/functional-v1/*.json`; lock↔qualification digests consistent; no reviewer/Suite-release ceremony |

Dev-tier suite at 486d45a: **132 passed, 1 deselected** (the one failure below).

## Drift found (open actions — CHECK WHETHER #36'S MERGE RESOLVED THEM)

### 1. Local verification gate RED on master (mechanical fix, was unowned)

`scripts/verify.py audit-policy` → exit 2: **111 tracked paths lack policy classification**. Identical failure as unit test `tests/unit/test_verification_policy.py::test_policy_classifies_every_tracked_and_issue_owned_path`.

Cause: PRs #78–#82 added tracked paths without extending `verification/policy.json` `path_rules`. Unclassified families:

- `artifacts/acceptance/issue-{32,33,34,35,40}/{verification.json,sha256sums.txt}`
- `artifacts/qualification/functional-v1/*.json`
- `scenarios/calibration/**` (all three packages)
- `src/model_benchmark/runtime/{conditions,credential_proxy,omp,omp_launch,opencode,opencode_launch,hermes,hermes_launch,raw_api}.py`
- `tests/acceptance/issue_{33,34,35}/**`, `tests/acceptance/issue_40/**`
- `profiles/functional-v1/*.condition.json`, `templates/functional-v1-manifest-v1.yaml` (verify against full list)

Systemic note: there is deliberately no CI (hosted authority removed per #69/#73); the gate is operator-run and no PR ritual runs it. If #36 merged without touching `verification/policy.json`, the gate is still red **plus** whatever paths #36 added.

### 2. Raw API condition lock missing

`profiles/functional-v1/` shipped only 3 locks (omp, opencode, hermes). `templates/functional-v1-manifest-v1.yaml` references `locks/raw-api.condition.json` — real provisioning from the template fails at manifest resolution. Test fixtures synthesize a lock on the fly, which masked it. #36's scope says "four condition artifacts", so the fix most plausibly landed there — **verify a committed `raw-api` condition lock exists and the template resolves against it**. Hard blocker for #75 otherwise.

## Watch-points for #37 (noted at 486d45a, not violations)

- `evidence/capture.py` is a shebang sidecar script, not an importable module — the coordinator/capture work needs a subprocess seam.
- `RunWorkspace.seal()` (`runtime/functional_v1.py:571`) was never called from any execution path; its completeness check (all 12 cells `evidence_valid` + bundle identity) needs deliberate handling for incomplete/aborted runs (terminals must be drained before sealing incomplete state).
- Seven `CELL_DISPOSITIONS` exist as a tuple but nothing assigned them from real execution; precedence rules (integrity > infrastructure > valid_*) unimplemented at audit time.
- `inspect` human table used `-` placeholders for scores (`runtime/functional_v1.py:762-781`) pending Result Bundles.
- Minor: OMP `_verify_lock_dependencies` (`omp.py:141-163`) uses weaker inline checks than OpenCode/Hermes `_locked_configuration()` dict comparison (bytewise lock validation still protects); `credential_proxy.py:609-612` `credential_fingerprint_forbidden` is dead/untested; `src/model_benchmark/analysis/__init__.py` is an empty stub; `runtime/__init__.py` docstring overpromises "measured Trial execution".

## Dismissed — do NOT re-flag these as drift

- **`FIXED_LIMITS` hardcoded** (`declarations/functional_v1.py:37`): correct per decision #71 — the envelope is fixed; the loader *rejects* deviating manifests (`fixed-envelope-mismatch`, `:507-510`). Not operator-tunable by design.
- **`scenario_cli.py` "not-implemented"**: all four registered commands (`scaffold/check/lock/qualify`) are handled (`:75-88`); the raise at `:209` is unreachable defense.
- **`OperatorContractRuntime.run/preflight` exit-3 stubs**: deliberate deferral to #36 (contract-consistent at the time; should be GONE after #36 merges — if still stubs, #36 is not actually done).
- **Legacy root files** (`run_*.py`, `poc_harness.py`, `gen_*.py`, `merge_metrics.py`, `presentacion.html`, `results/`, `human_review/`, `baselines/`): pre-wayfinder heritage; no decision mandates removal. Optional cleanup, never a V1 blocker.

## Workspace hygiene (as of audit)

Stale worktrees for closed work, all safe to prune (dirt = regenerated artifacts / untracked tool dirs only):
`../model-benchmarking-architecture-reuse`, `../model-benchmarking-issue-29` (2 modified regenerated acceptance files), `../model-benchmarking-issue-53`, `../model-benchmarking-wayfinder` (untracked `.kiro/`, `.serena/`), `.worktrees/issue-54`, `.worktrees/issue-55`.
Audit worktree from this session: `../model-benchmarking-audit` → `git worktree remove --force ../model-benchmarking-audit`.
Never commit: `.env`, `.benchmark-cache/`, `.serena/`.

## Re-verification playbook for the future session

```sh
# 1. Pin a fresh audit worktree (branch under active work — never audit the checkout)
git fetch origin && git worktree add --detach ../mb-audit origin/master

# 2. Gate status (drift item 1) — expect exit 0 if fixed
cd ../mb-audit && uv run python scripts/verify.py audit-policy

# 3. Full dev tier over all tracked paths
git ls-files > /tmp/paths.txt && uv run python scripts/verify.py run-development --changed-paths-file /tmp/paths.txt

# 4. Raw API lock present? (drift item 2)
ls profiles/functional-v1/            # expect 4 condition locks incl. raw-api

# 5. #36 actually done? (stubs must be gone, coordinator wired)
grep -n "execution-coordinator-unavailable\|execution-preflight-unavailable" -r src/  # expect no hits
ls artifacts/acceptance/issue-36/     # expect committed verification evidence

# 6. Tracker frontier
gh api repos/MihaiA24/model-benchmarking/issues/37/dependencies/blocked_by --jq '.[].state'  # closed => #37 frontier
```

After #36 merges: frontier moves to [#37 capture/Result Bundles/Run Record sealing](https://github.com/MihaiA24/model-benchmarking/issues/37) (remove its `blocked` label once edges say so), then [#75 acceptance run](https://github.com/MihaiA24/model-benchmarking/issues/75) — which additionally needs drift items 1–2 resolved and a qualified native Linux/amd64 worker.

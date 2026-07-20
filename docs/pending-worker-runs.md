# Pending qualified-worker runs — 2026-07-19

The qualified worker (`ssh mihai@192.168.1.212`) is offline. Everything
runnable off-worker is done and green on this branch (PR #114: unit,
architecture, conformance, `audit-policy`, `run-development`). The items
below are the complete backlog that only the worker can execute, in
dependency order. Nothing else is blocked on hardware.

Merging PR #114 first is safe and requires no reseal: it touches only
`tests/unit/**`, `verification/policy.json`, and `docs/**`, all outside
every `acceptance-source-tree` proof input.

## 1. Issue #113 forensics — name the stray file(s) (read-only)

The sealed `acceptance-source-tree` digests on master match **no
committed tree** (bisected on 2026-07-19 with the publisher's own
`_tree_digest`; merge drift, `.DS_Store`, filename normalization, and
case collisions all falsified). Expected cause: uncommitted file(s) in
the publishing worktree at the `eae63d3` republish.

In the worktree that published the proofs:

```sh
cd ~/code/nter/mb-issue99
git status --porcelain
git ls-files --others --exclude-standard src tests profiles scaffolds
uv run python scripts/verify.py check-acceptance-proofs   # expected: fresh HERE
```

`check-acceptance-proofs` reporting fresh in this (polluted) worktree
while a clean clone reports 13/13 stale confirms the mechanism and the
listing above names the culprit file(s). Quote them in #113.

## 2. Issue #113 fix — republish all 13 proofs from a verified-clean checkout

```sh
git clone <repo> mb-clean && cd mb-clean        # or a fresh worktree of merged master
git status --porcelain                          # must be empty
git ls-files --others --exclude-standard src tests profiles scaffolds   # must be empty
uv run python scripts/acceptance.py             # full ordered suite, Docker required
uv run python scripts/verify.py check-acceptance-proofs   # must be 13/13 fresh
```

Then re-verify freshness on an **independent** clean clone (e.g., the
macOS machine after pulling) before committing the
`chore: republish all 13 proofs` commit. Per #113 acceptance criteria,
the publisher dirty-tree refusal guard (a `src/` change) should ride
this same reseal ceremony.

## 3. Read sealed run `019f7b51-f559-7443-8892-2926af831bac` — why do raw-api and hermes cells fail their task tests? (read-only, no spend)

The run is `complete`/`valid` with all 12 cells issuing provider
requests; the open question is the per-cell *score* failures observed
for raw-api and hermes. The graded evidence is already paid for and
preserved:

```text
~/code/nter/mb-issue99/.model-benchmark/runs/019f7b51-f559-7443-8892-2926af831bac/
  cells/<cell>/raw/      # redacted condition stdout/stderr, native diagnostics
  cells/<cell>/bundle/   # sealed result bundle incl. verifier output
```

- Map cell numbers to conditions from the run manifest (`inspect`
  projection) rather than assuming ordering.
- Raw-api cells (04 python, 08 spring, 12 angular) made exactly one
  request each (4 505 / 2 561 / 1 629 tokens) — that is the post-#107
  design (single POST, whole-file generation, no tools), so weak scores
  there are plausibly legitimate baseline behavior, not a harness bug.
- Deliverable: per-cell failure reason quoted from the preserved
  verifier/test output. File a new issue only if the evidence shows a
  harness defect rather than model/baseline weakness.

## 4. Conditional — new twelve-cell run

Only justified if step 3 reveals a harness defect (the #99 pattern:
structural inability, not model weakness). A rerun for its own sake
adds no information: run `019f7b51…` is sealed and valid.

## Explicitly not pending

- Tonight's "raw api and hermes failed" local test failures — resolved
  (working-tree lock damage; see #112 / PR #114). No worker involvement.
- Any re-run of unit/architecture/conformance on the worker — already
  green off-worker; they prove nothing new there.

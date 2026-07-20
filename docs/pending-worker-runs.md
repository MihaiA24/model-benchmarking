# Pending qualified-worker runs — 2026-07-19

The remaining qualified-worker backlog is below in dependency order. Nothing
else is blocked on hardware.


## 1. Read sealed run `019f7b51-f559-7443-8892-2926af831bac` — why do raw-api and hermes cells fail their task tests? (read-only, no spend)

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

## 2. Conditional — new twelve-cell run

Only justified if step 1 reveals a harness defect (the #99 pattern:
structural inability, not model weakness). A rerun for its own sake
adds no information: run `019f7b51…` is sealed and valid.

## Explicitly not pending

- Tonight's "raw api and hermes failed" local test failures — resolved
  (working-tree lock damage; see #112 / PR #114). No worker involvement.
- Any re-run of unit/architecture/conformance on the worker — already
  green off-worker; they prove nothing new there.

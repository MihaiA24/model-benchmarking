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

## 2. Superseded — no new 12-cell run

The Functional V1 16-cell hard cut makes this prior conditional rerun
non-executable. Run `019f7b51…` remains immutable archival evidence; the current
operator accepts only complete 16-cell runs.

## 3. Pending after merge — sealed no-spend 16-cell Dry-launch Qualification

Checkout the exact integration merge commit on the qualified Linux/amd64 worker. Verify
all four pricing windows and OpenCode Go model routes, start the dedicated worker, and
provision/preflight every supported manifest. Keep `mb-host0` down for the complete
qualification window, then run:

```sh
scripts/qualify-functional-v1-dry-launch
```

Publish only the sealed qualification JSON, identity, and SHA-256 inventory. Acceptance is
16 terminal lifecycles, 16 sealed Result Bundles, at least one local proxy request per cell,
zero external egress/cost, no infrastructure or integrity invalidity, complete cleanup, and
verified uplink restoration. Task success is irrelevant. Any source, lock, manifest, pricing,
worker, or qualification change resets this qualification. Do not spend provider money in
this session.

## 4. Pending only after qualification — paid three-model Campaign

Run exactly three unchanged-commit 16-cell Runs: DeepSeek V4 Flash, Hy3, then MiniMax M3.
MiMo V2.5 remains supported but is not run, reported, or budgeted. Inspect each sealed Run
ID and cumulative cost before starting the next model; the sealed worst-case bound plus
overshoot must stay within the $25 Campaign ceiling. Resume interruptions under the same
Run ID. Restart an infrastructure-invalid model Run in full. A committed-input or pricing
change invalidates the qualification and every completed Campaign Run. Generate only
diagnostic/no-claims reports and archive full Run directories privately with immutable
SHA-256 inventories.

## Explicitly not pending

- Tonight's "raw api and hermes failed" local test failures — resolved
  (working-tree lock damage; see #112 / PR #114). No worker involvement.
- Any re-run of unit/architecture/conformance on the worker — already
  green off-worker; they prove nothing new there.

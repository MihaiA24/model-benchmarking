# Issue #75 — review of the two implementations and the combined branch

**Date:** 2026-07-17 · **Branch:** `feat/issue-75-combined` (base `run/issue-75-acceptance-b`, which bases on `origin/master` @ `08ce6f5`)
**Inputs reviewed:** PR #92 (implementation A, `issue-75-functional-v1-acceptance`, one squashed commit) and PR #93 (implementation B, `run/issue-75-acceptance-b`, ~30 targeted commits). Both completed a real, valid twelve-cell run on the same qualified worker.

## Verdict

Neither PR should merge as-is. **B is the architectural spine; A contributes the pricing
contract and the operator deliverables.** This branch is B plus four commits porting the
A-only assets, repairing the acceptance suites B left broken, and resealing the identity
chain. Every decision below names the winner and the reason.

## Where the implementations agreed

Both independently found and equivalently fixed: the `--storage-opt size=` key, the
qualification-record removal (integration-mode preflight), the capture Dockerfile build
context, the Hermes storage-driver `Size` identity check, the Hermes `PYTHONPATH` package
root, the egress-probe packaged entrypoint, the Harbor 0.18 array collect manifest
(fail-closed), zero-request proxy evidence, container-owned scratch chown, the dropped
`capture.build: null` override, and the `.model-benchmark` mkdir-collision in the
condition home. These carried over from B unchanged.

## Decisions, per divergence

| Divergence | A (#92) | B (#93) | Kept | Why |
|---|---|---|---|---|
| Scenario runtime images | Coordinator rebuilds its own tagged image set and rewrites `task.toml` bindings | Records the sealed store image IDs (`sha256:`) from the provisioning manifest; validates the projection binds exactly those | **B** | A creates a second, unsealed image set that can diverge from what preflight verified; mutable tags vs immutable IDs. Single identity chain wins. |
| Proxy evidence permissions | Proxy stays container-root; evidence dir `0733`, file `0622` (world-writable) | Proxy runs as the coordinator uid; `tmpfs mode=1777`; evidence owned by coordinator | **B** | Least privilege, no world-writable evidence, no special mount modes. |
| Zero-request evidence | Host touches `proxy.jsonl` before start | Proxy touches its evidence file at start | **B** | With B, an empty file proves the proxy started; A's host-side touch masks proxy-start failures. |
| Provider DNS | Operator-managed external forwarder container | `dns: [8.8.8.8, 1.1.1.1]` pinned on the credential-proxy service in the overlay | **B** | In-code, reproducible, no operator intervention; conditions stay isolated either way. |
| Isolation probe | Resolves the proxy IPv4 and probes by IP | Fixes the root cause (stdlib-only proxy import closure) and keeps name-based probing | **B** | The probe should mirror the real cell wiring (conditions resolve the `credential-proxy` alias). A's IP hop probes a different path. |
| Rejected capture | Not handled — `valid_completed` + rejected capture still seals `handoff-mismatch` (invalid infrastructure); A passed only because its models wrote clean patches | Reclassifies to `valid_harness_outcome` / `submission-rejected`; collect-manifest escalation restricted to the mandatory `capture.json` | **B** | B hit this live (cell 02) and proved the fix; A retains a latent false-infrastructure failure. |
| CPU limit probe | Requires `NanoCpus` exactly | Accepts `NanoCpus` or `CpuQuota`/`CpuPeriod` | **B** | Same exactness (2 cores), tolerant to the daemon's encoding. |
| Wall-time probe field | `enforced_after_ns` | `enforced_after_ms` | **B** | Both integer (canonical JSON); no reason to churn B. |
| Sealed-tree removal | chmod walk that raises on error | Tolerant walk, `rmtree(ignore_errors=True)` | **B** | Runs inside `except BaseException` paths; must not mask the original error. |
| Condition home | `mkdir -p` as 65532 | Root creates + `chmod -R a+rwX`, then proves 65532 can write | **B** | Works even when `/logs/agent` is root-owned; carries the CAP_CHOWN rationale. |
| Cost accounting | Immutable manifest pricing record; exact Decimal derivation from input/output tokens; stop-after-cost against the derived total | Observes provider-reported `cost`/`cost_usd`, per-response maximum | **Both, merged** | A's derivation is deterministic and works when the provider reports no monetary cost; B's observation captures true reported spend (zen's streaming cost event, trailing zero-cost event). The proxy now enforces against the derived total and records `provider_reported_cost_usd` alongside `provider_cost_usd`, per-component costs, token split, and the pricing identity. |
| Proxy request cap | `MODEL_BENCHMARK_REQUESTS_PER_TRIAL` env from the manifest | `FIXED_LIMITS` import from the new stdlib-only `declarations.limits` | **Both** | Env plumbing (A) makes the cap manifest-driven like every other limit and shrinks the proxy closure; `declarations.limits` and B's import-closure architecture test stay as the guard. |
| Executor crash forensics | Writes full `harbor.stdout/stderr.txt` into preserved raw evidence; rebrands all errors `cell-executor-failed` | Preserves evidence; re-raises with redacted tails, keeping the original reason code | **Both, merged** | Full streams into (redacted) preserved evidence from A; reason-code-preserving re-raise from B. |
| Worker provisioning | `scripts/functional-v1-worker` (XFS pquota loopback, netns, dedicated dockerd) | worker-local shell history only | **A** | The qualified-worker setup must be reproducible from the repo. |
| Runnable manifest | `functional-v1-issue-75.yaml` with the sealed pricing block | worker-local only | **A** | Committed, re-pinned to the resealed condition locks. |
| Run archives | `artifacts/acceptance/issue-75/` (manifest + handoff) | `research/functional-v1-issue-75-acceptance-run-b.md` | **Both** | Historical records of two real runs; both stay frozen. |

## Defects found during this review

1. **B left `tests/acceptance/issue_36` broken** (`TypeError: _runtime_scenario_package()
   got an unexpected keyword argument 'main_image'`, plus a stale `capture["build"] is
   None` assert). B's dev gate only runs `tests/unit` + `tests/architecture`, so the
   acceptance regression was invisible. Fixed here; the binding test now covers the
   validate-only seam plus a rejection case, and new tests pin the storage-opt key, both
   CPU encodings, the name-based isolation probe (including the pricing env the combined
   proxy requires), the artifact-tree mount probe, and the writable-home install proof.
2. **A's committed manifest pinned stale locks** — every runtime-tree change reseals the
   condition locks, so the root manifest's `functional-v1-condition:` digests must be
   re-pinned (done here; load smoke passes). The archived copy under
   `artifacts/acceptance/issue-75/` is intentionally untouched — it documents the exact
   manifest run A executed.

## Verification (this branch, macOS — everything that runs without Docker/Linux)

- `tests/unit` + `tests/architecture`: 157 passed (includes B's stdlib-closure test over
  the merged proxy and the combined-policy classification test).
- All 13 acceptance suites re-run green on the final tree: issues 28 (13), 29 (19),
  32 (25), 33 (4), 34 (4), 35 (5), 36 (20), 37 (5), 40 (4), 51 (10), 54 (11), 55 (1),
  74 (41) — 162 cases; sealed verification artifacts regenerated from this run.
- `tests/conformance/conditions`: 4 passed.
- `scripts/verify.py run-development --base origin/master --head HEAD`: exit 0.
- `python -m compileall -q src scripts verification`; `bash -n scripts/functional-v1-worker`.
- Condition locks resealed for the combined runtime tree;
  `functional-v1-issue-75.yaml` loads: manifest identity
  `functional-v1-manifest:sha256:9dd11a22…`, resolved `resolved-v1-manifest:sha256:3d998363…`.

## Required runs on the qualified Linux worker (before merge)

The combined tree has **not** executed on hardware; both sealed runs prove their own
trees, not this one. On the worker (`scripts/functional-v1-worker start`, `.env` with
`MODEL_BENCHMARK_PROVIDER_API_KEY`, `DOCKER_HOST=unix:///run/model-benchmark-docker/docker.sock`):

1. Refresh the pricing block in `functional-v1-issue-75.yaml` (new `retrieved_at_utc`
   inside a current effective interval; recompute `identity` over the canonical payload
   without the `identity` field) — the committed record's interval ended 2026-07-17.
2. `provision` from a clean managed home — exit 0, sealed inventory.
3. Network-disabled `preflight` (down the netns uplink, e.g. `ip link set mb-host0 down`)
   — must pass with the name-based isolation probe and the pricing-env proxy.
4. Twelve-cell `run` — `complete`/`valid`, 12/12 sealed terminals; expect derived
   (`provider_cost_usd`) and reported (`provider_reported_cost_usd`) spend on every
   priced response.
5. `inspect` twice (byte-identical), `run --resume` no-op, digest read-back 12/12,
   cleanup inventory empty, exact-byte credential scan of the managed home: zero hits.
6. Watch the two merged seams specifically: a streaming response must carry
   `prompt_tokens`/`completion_tokens` (the pricing record derivation fail-closes into
   `provider-contract-violation` when the split is missing), and a rejected-capture cell,
   if one occurs, must seal `valid_harness_outcome`/`submission-rejected`.

## Disposition of the open PRs

- **PR #93 (B):** superseded by this branch (same history plus the four commits). Close
  in favour of the combined PR, or retarget it to this branch.
- **PR #92 (A):** close without merging. Its pricing contract, worker script, manifest,
  handoff archive, and test intents are ported here; its run evidence remains valid on
  issue #75 and in `artifacts/acceptance/issue-75/`.
- Backport note from B's review ("`.model-benchmark` collision", "rejected-capture
  sealing") is resolved by this branch reaching master; no separate backport needed.

No Harness ranking, winner, production, release, or statistical claim is made here.

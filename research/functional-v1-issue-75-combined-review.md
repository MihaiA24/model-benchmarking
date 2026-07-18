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

## Executed acceptance run on the qualified Linux worker

Executed 2026-07-18 on the same worker as runs A and B (`cachyos`, native
linux/amd64, 24 CPU / 30.48 GiB, dedicated Docker Engine, overlay2 on the 128 GiB XFS
`prjquota` loopback, cgroup v2), from worktree `~/code/nter/mb-issue75-combined` at
`6bbd84f`, managed home `.model-benchmark`, credential only in `.env` (0600).

The committed `scripts/functional-v1-worker start` performed the worker bring-up
(first live use: XFS remount, netns + veth + NAT, transient containerd/dockerd units).
The daemon resolves registries itself (dockerd ignores the host's loopback-stub
`resolv.conf` and falls back to public DNS through the veth NAT); the credential-proxy
DNS pin in the cell overlay covers the container side.

1. Pricing refreshed first: models.dev re-retrieved, deepseek-v4-flash still USD
   0.14/0.28 per M tokens; new window 2026-07-17 → 2026-08-01, identity
   `pricing-record:sha256:869a04ae…` (commit `6bbd84f`).
2. `provision` from a clean managed home — `provisioned`, manifest
   `functional-v1-manifest:sha256:265f6de0…`, provisioning manifest
   `provisioning-manifest:sha256:5bffb000…`.
3. Network-disabled `preflight` (uplink `mb-host0` down for the whole window, trap-restored)
   — `passed`: capacity 24 CPU / 32.7 GB / 101 GiB free vs 8 / 24 GiB / 50 GiB required,
   exact limits, quota and wall-time probes, and the name-based isolation probe with the
   pricing-env proxy: `credential_proxy_ready`, direct/public/LAN/metadata/host-route all
   denied, zero provider requests.
4. Twelve-cell `run` — **`sealed` / `valid`**, Run ID `019f74c6-3c9c-70de-9e85-129aa2020fa2`,
   Run Record `functional-v1-run-record:sha256:86a517dd10059ccf27c24597fb7dcb8d1aeaa4ec088df466a4b8ed5ccc0f9289`,
   ~10 minutes wall with three active slots. Dispositions: 5 `valid_limit_outcome`
   (tokens-stop-after-response), 1 `valid_completed` (Angular/OpenCode), 6
   `valid_harness_outcome` (5 condition-ended-before-provider-response, and cell 02
   python/OpenCode sealed **`submission-rejected`** — the reclassification seam exercised
   live). 3/12 task passes (OMP python, OMP Angular, OpenCode Angular); 12/12
   `evidence_valid=true`.
5. Accounting: 45 provider requests, 652,015 tokens; **45/45 responses priced** with both
   figures — derived `provider_cost_usd` USD 0.09271010 at the sealed rates and
   provider-reported `provider_reported_cost_usd` USD 0.01505271 — each event carrying the
   pricing record identity. No cell approached the USD 5.00 stop.
6. Post-run: `inspect` twice byte-identical; `run --resume <run-id>` exit 0 with a payload
   exactly equal to the inspect payload; Run Record digest read-back OK; 12/12 Result
   Bundle identities recompute from `bundle/inventory.json` and all 251 present artifact
   digests verify; cleanup left zero Run-owned containers/networks/volumes and only the
   default `bridge`/`host`/`none` networks; exact-byte scan of the managed home for the
   live credential: zero hits.

Both merged seams behaved: streaming responses carried the token split (pricing
derivation never fail-closed), and the one rejected capture sealed as valid harness data.

## Disposition of the open PRs

- **PR #93 (B):** superseded by this branch (same history plus the four commits). Close
  in favour of the combined PR, or retarget it to this branch.
- **PR #92 (A):** close without merging. Its pricing contract, worker script, manifest,
  handoff archive, and test intents are ported here; its run evidence remains valid on
  issue #75 and in `artifacts/acceptance/issue-75/`.
- Backport note from B's review ("`.model-benchmark` collision", "rejected-capture
  sealing") is resolved by this branch reaching master; no separate backport needed.

No Harness ranking, winner, production, release, or statistical claim is made here.

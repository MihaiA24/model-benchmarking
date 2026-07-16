# Functional V1 — issue #75 acceptance run (implementation B): interim handoff

**Date:** 2026-07-16 · **Branch:** `run/issue-75-acceptance-b` (base `origin/master` @ `08ce6f5`)
**Worker:** native Linux/amd64 workstation (`CachyOS`, 24 CPU, 30.48 GiB RAM), dedicated Docker Engine 29.6.1 for the benchmark (overlay2, data root on a 128 GiB XFS volume with project quotas, 116 GiB free, cgroup v2), Docker Compose 5.3.1, Harbor 0.18.0, Python 3.12.12 via `uv`.
**Isolation:** a second, independent implementation of #75 runs concurrently on the same worker in the primary checkout; this run lives in its own worktree (`~/code/nter/mb-issue75-b`) with its own managed home, manifest, and branch. All container resources are Run-ID-scoped, so the two runs do not interfere.

## Outcome so far

- `provision` (network-enabled) — **exit 0** from a clean managed home.
- `preflight` (network-disabled, cache-read-only) — host capacity, resource-limit exactness, writable-disk quota, and wall-time probes **pass**; the final proxy-isolation probe currently fails because the probe helper container cannot resolve the credential-proxy service name from inside the shared probe namespace. The twelve-cell `run` has therefore not executed yet. This is the single open blocker.
- Eleven commits were required to get this far: executing the sealed operator path end-to-end on a real qualified worker surfaced defects that fixtures had masked (details below).

## Operator setup (exact)

```sh
# one-time
git worktree add -b run/issue-75-acceptance-b ~/code/nter/mb-issue75-b origin/master
cd ~/code/nter/mb-issue75-b && uv sync
cp ../model-benchmarking/.env .env          # MODEL_BENCHMARK_PROVIDER_API_KEY only; gitignored

# operator.sh: sources .env, exports the dedicated engine socket, and runs the CLI
#   export DOCKER_HOST=unix:///run/model-benchmark-docker/docker.sock
#   exec uv run model-benchmark "$@"

./operator.sh --home .model-benchmark --json provision functional-v1-issue-75-b.yaml
./operator.sh --home .model-benchmark --json preflight functional-v1-issue-75-b.yaml
# pending: run / inspect / run --resume
```

The real provider credential exists only in the operator environment and the per-Trial Credential Proxy; it is never placed in command arguments, condition environments, or the repository.

## Manifest

`functional-v1-issue-75-b.yaml` — template limits (100,000 tokens and $5.00 stop-after-cost per Trial, 64 requests, 1800 s wall time, 2 CPU / 4096 MiB / 8192 MiB writable per Trial, `max_parallel: 3`, `proxy-only-v1`), the three accepted Scenario Packages by committed lock digest, the four pinned condition locks, and the operator-selected route:

- Provider route: `https://opencode.ai/zen/go/v1`, model `deepseek-v4-flash`.
- Manifest identity: `functional-v1-manifest:sha256:1ada70be1608fbb9769e7693673c063b519db372effa60197f859bf1d33b9db7`
- Resolved identity: `resolved-v1-manifest:sha256:cc9b5adfe8a499d40989d4a016dccdd08f8343224e7e350b1ccdf374f8f6c4b8`

Provider probes (operator-side, before the run) confirmed the route reports `usage.total_tokens` on every response and per-request spend as a string `cost` field — `"0"` on non-streaming responses under the flat-rate plan, with the true per-request figure delivered as a final streaming cost event.

## Defects found on master and fixed on this branch

| Commit | Fix |
|---|---|
| `1db04fa` | Credential proxy only parsed `cost_usd`; the real route reports `cost`. Observe both, keep the per-response maximum so a trailing zero-cost event cannot clobber reported spend. |
| `07c527b` | Measured-mode provisioning demanded a Package Qualification Record; the committed artifacts are technical qualification evidence (the independent-review ceremony was dropped for V1). Provision/preflight as integration-mode candidates — the honest lifecycle state. |
| `585913c` | Scenario image reference called a `TypedDigest` attribute on a `str`; crashed every real provisioning. |
| `1f240a9` | Capture image build used the wrong build context; its recipe copies files relative to the environment directory. |
| `2870589` | Local Hermes image check compared a storage-backend-defined size figure; digest-pinned pull + Id equality already seal content identity. |
| `af67d9b` | Preflight re-injected image bindings into the already-projected task and tripped its own guard; validate the projection instead. |
| `02a8023` | The coordinator built a second, unsealed image set and ran cells with it, diverging from the preflight-verified store images; record the sealed store identities in the inventory. |
| `4ab23ae` | `--storage-opt` was passed without the `size=` key; both quota probes failed on every worker. |
| `b0ce453` | Modern engines encode `--cpus` as `NanoCpus`; accept either encoding. Read-only projected trees survived cleanup; restore write bits before removal. |
| `9c125c4` | The egress probe helper was started with the image's default entrypoint instead of the packaged sidecar entrypoint, so it exited before becoming ready. |
| `d88929c` + reseals | Condition locks embed a digest of the runtime source tree; every runtime fix requires resealing the four locks (and regenerating the manifest digests). |

## Evidence locations (worker)

- Worktree: `~/code/nter/mb-issue75-b`
- Operator logs: `logs/provision.json`, `logs/provision.err`, `logs/preflight.json`, `logs/preflight.err`
- Managed home: `.model-benchmark/` (provisioning inventory under `provisioning/<manifest-identity>.json` plus per-scenario store manifests)

## Remaining work

1. Resolve the isolation-probe service-name resolution failure (last preflight step).
2. Execute `run` to a sealed Run Record: twelve cells, one start marker and one valid terminal disposition each.
3. Verify `inspect` twice (read-only), `run --resume <run-id>` as inspect/no-op, digest read-back, cleanup inventory, spend accounting, and credential non-exposure.
4. Post the final implementation handoff on #75 with the Run ID, observed spend, and outcomes table.

No Harness ranking, winner, production, release, or statistical claim is made here or in any follow-up from this run.

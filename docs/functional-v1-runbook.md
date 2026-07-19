# Functional V1 operator runbook

How to execute Functional V1 benchmark runs in every supported configuration, and what
the worker must provide. The CLI surface is exactly four commands:

```sh
model-benchmark [--home DIR] [--json] {provision|preflight|run|inspect}
```

Every command reads one strict manifest (`functional-v1-issue-75.yaml` is the committed,
runnable example). All state lives under `--home` (default `.model-benchmark`).

## 1. Setup requirements

### Host (preflight fails closed on every row)

| Requirement | Minimum |
|---|---|
| Platform | native Linux/amd64 (no macOS, no other arch) |
| cgroup | v2 |
| CPUs | 8 |
| Memory | 24 GiB |
| Free Docker storage | 50 GiB |
| Storage driver | overlay2 on XFS mounted with `pquota`/`prjquota` |
| Concurrency envelope | 3 simultaneous cells (2 CPUs / 4 GiB / 8 GiB disk each) |

### Software

- Docker Engine + Compose v2 (Harbor 0.18 drives compose), `git`, `uv` (Python 3.12).
- A dedicated Docker daemon is strongly recommended so the benchmark cannot see or
  disturb the system daemon. The committed script provisions one end to end
  (128 GiB XFS loopback with project quotas, private network namespace, veth + NAT
  uplink, transient `containerd`/`dockerd` units):

```sh
sudo bash scripts/functional-v1-worker start    # idempotent; prints DOCKER_HOST
sudo bash scripts/functional-v1-worker status
sudo bash scripts/functional-v1-worker stop
export DOCKER_HOST=unix:///run/model-benchmark-docker/docker.sock
```

  The daemon does not survive reboot; rerun `start` after one. Registry pulls work
  despite a loopback-stub `/etc/resolv.conf` (dockerd falls back to public DNS through
  the NAT); the credential proxy's resolvers are pinned in the sealed cell overlay.

### Credential

Exactly one secret, never in the repo, never in command arguments:

```sh
printf 'MODEL_BENCHMARK_PROVIDER_API_KEY=<key>\n' > .env && chmod 600 .env
```

Conditions only ever receive an opaque per-Trial proxy token; the real key exists in the
operator environment and the per-Trial Credential Proxy.

### Checkout

```sh
git clone <repo> && cd model-benchmarking && uv sync --frozen
```

## 2. The standard run — all harnesses, all scenarios

The twelve-cell matrix (3 Scenario Packages × OMP, OpenCode, Hermes, Raw API) is the
only operator-executable unit. One invocation each, in order:

```sh
# 1. Network-enabled provisioning (idempotent, content-addressed; `reused: true` on repeat)
uv run --frozen --env-file .env model-benchmark --home .model-benchmark --json \
  provision functional-v1-issue-75.yaml

# 2. Network-disabled preflight: drop the daemon's uplink for the whole window
sudo ip link set mb-host0 down
uv run --frozen --env-file .env model-benchmark --home .model-benchmark --json \
  preflight functional-v1-issue-75.yaml            # expect "outcome": "passed"
sudo ip link set mb-host0 up

# 3. The run (provider-enabled). Prints the Run ID; seals a Run Record on completion.
uv run --frozen --env-file .env model-benchmark --home .model-benchmark --json \
  run functional-v1-issue-75.yaml                  # expect "outcome": "sealed", "validity": "valid"

# 4. Read-only verification (repeatable, byte-identical)
uv run --frozen model-benchmark --home .model-benchmark --json inspect <RUN_ID>
```

Valid terminal dispositions are benchmark data: `valid_completed`,
`valid_limit_outcome` (token/cost/wall-time stop), `valid_harness_outcome` (e.g.
`condition-ended-before-provider-response`, `submission-rejected`). Any
`invalid_infrastructure` cell invalidates the run.

Evidence: `.model-benchmark/runs/<RUN_ID>/` — `run-record.json` + `.identity`,
`cells/<cell>/terminal.json`, `cells/<cell>/bundle/` (sealed Result Bundle),
`cells/<cell>/raw/proxy-evidence/proxy.jsonl` (per-response tokens, derived
`provider_cost_usd`, provider-reported `provider_reported_cost_usd`, pricing identity).

## 3. One model / another provider route

A manifest pins exactly one OpenAI-compatible route and one exact model; benchmarking N
models means N manifests and N runs. To target a different model:

1. Copy the manifest; edit `provider.base_url` (must be canonical HTTPS, no trailing
   slash) and `provider.model`.
2. Reseal the pricing record — rates from an authoritative source, identity recomputed:

```sh
uv run --frozen python - <<'EOF'
from model_benchmark.declarations.canonical import canonical_json_bytes
from model_benchmark.declarations.identities import DigestKind, TypedDigest
payload = {
    "schema_version": 1, "currency": "USD", "unit": "usd-per-million-tokens",
    "input_usd_per_million_tokens": "<rate>", "output_usd_per_million_tokens": "<rate>",
    "effective_from_utc": "<YYYY-MM-DDT00:00:00Z>", "effective_until_utc": "<...>",
    "source_url": "<https source>", "retrieved_at_utc": "<actual retrieval time>",
}
print(TypedDigest.from_bytes(DigestKind.PRICING_RECORD, canonical_json_bytes(payload)))
EOF
```

   Paste rates, window, source, `retrieved_at_utc`, and the printed identity into
   `provider.pricing`. `retrieved_at_utc` must fall inside the effective window; the
   window must cover the run date. Manifest load rejects any drift
   (`pricing-record-mismatch`).
3. Run section 2 against the new manifest. Limits are template-fixed (64 requests,
   100k tokens, $5.00 stop-after-cost, 1800 s per Trial) and are not tunable in V1.

If the provider reports no monetary cost (flat-rate plans), enforcement and totals use
the exact Decimal cost derived from token usage at the sealed rates; any
provider-reported figure is recorded alongside as provenance.

## 4. One harness or one scenario — not operator-selectable

The matrix is fixed by design: a valid Run Record always proves all twelve cells, so
records are comparable and a partial run can never masquerade as an acceptance. There is
no CLI flag to run a single condition or scenario. (Single-condition schedules exist
only as `INTERNAL_QUALIFICATION_STAGES` on the runtime API for maintainer
qualification/tests — deliberately not reachable from the CLI.)

A cheaper-than-full-run signal: `preflight` exercises provisioning integrity, resource
enforcement, and proxy isolation for all four conditions without any provider spend.

The pre-V1 exploratory PoC scripts (root `run_*.py` / `poc_harness.py`) were removed
from the tree and live in git history; they were never part of the sealed V1 protocol.

## 5. Repeats, resume, and inspection

- Each `run` mints a fresh Run ID; sealed Run Records are immutable. Repetition = run
  again (same manifest, same provisioned inputs).
- `run --resume <RUN_ID>` (no manifest argument): resumes only an interrupted run; on a
  sealed Run ID it is a no-op that returns exactly the `inspect` payload.
- `inspect <RUN_ID>` is read-only, deterministic, and byte-identical across calls; it
  re-verifies record and bundle digests on every read.
- After completion nothing Run-owned remains: no containers, networks, volumes, or
  `/tmp` scratch. `docker ps --all` / `docker network ls` should show only defaults.

## 6. After changing runtime code

Condition-image identities embed the runtime tree (`src/model_benchmark/**`); any change
there stales the four condition locks and every manifest that pins them:

```sh
uv run --frozen python - <<'EOF'
import json
from pathlib import Path
from model_benchmark.declarations.identities import DigestKind, TypedDigest
from model_benchmark.runtime.execution import condition_image_content_digest, _runtime_source_root

locks = {c: f"profiles/functional-v1/{n}.condition.json" for c, n in [
    ("omp", "omp-v16.4.0"), ("opencode", "opencode-v1.17.18"),
    ("hermes", "hermes-v0.18.2"), ("raw-api", "raw-api-v1")]}
for condition, relative in locks.items():           # 1. reseal each lock's image pin
    path = Path(relative); data = path.read_bytes(); lock = json.loads(data)
    new = condition_image_content_digest(condition, lock, _runtime_source_root())
    path.write_bytes(data.replace(lock["image"]["content_digest"].encode(), new.encode()))
    print(condition, "->", str(TypedDigest.from_bytes(      # 2. re-pin this in the manifest
        DigestKind.FUNCTIONAL_V1_CONDITION, path.read_bytes())))
EOF
```

Update each `conditions.<name>.digest` in the manifest with the printed
`functional-v1-condition:` identities, then re-run `provision` (it will build fresh
sealed images). The dev gate (`uv run python scripts/verify.py run-development
--base origin/master --head HEAD`) must stay green.

## 7. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `unsupported-native-platform` before any Docker call | not native Linux/amd64 |
| provision/preflight can't reach the daemon | reboot cleared the transient units — `sudo bash scripts/functional-v1-worker start` |
| `condition-image-pin-mismatch` / `reference-digest-mismatch` | runtime tree changed — section 6 |
| `invalid-pricing-record` / `pricing-record-mismatch` | pricing fields edited without resealing — section 3 |
| `pricing-record-expired` at `run` start | the sealed record's `effective_until_utc` has passed — re-retrieve and reseal per section 3; `inspect` and sealed-run `run --resume` are unaffected |
| preflight isolation probe fails on proxy name | proxy container died at start — check its env is complete; the proxy import closure must stay stdlib-only (guarded by `tests/architecture`) |
| provider unreachable during `run` only | uplink still down from the preflight window — `sudo ip link set mb-host0 up` |

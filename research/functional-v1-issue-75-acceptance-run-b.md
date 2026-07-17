# Functional V1 — issue #75 acceptance run (implementation B): final handoff

**Date:** 2026-07-17 · **Branch:** `run/issue-75-acceptance-b` (base `origin/master` @ `08ce6f5`)
**Worker:** native Linux/amd64 workstation (`CachyOS`, 24 CPU, 30.48 GiB RAM), dedicated Docker Engine 29.6.1 for the benchmark (overlay2, data root on a 128 GiB XFS volume with project quotas, cgroup v2), Docker Compose 5.3.1, Harbor 0.18.0, Python 3.12.12 via `uv`.
**Isolation:** a second, independent implementation of #75 ran concurrently on the same worker in the primary checkout; this run lives in its own worktree (`~/code/nter/mb-issue75-b`) with its own managed home, manifest, and branch. All container resources are Run-ID-scoped, so the two runs did not interfere.

## Result

The native Linux/amd64 Functional V1 run completed all twelve Scenario-major cells with exactly three active slots and sealed a complete, valid Run Record.

- Run ID: `019f6eec-1443-752c-ac0c-85c227e54035`
- Run Record: `functional-v1-run-record:sha256:ef0a3a4a8cc41275f531e44156b0e5635c1be10e93a99c38d3de618b32326434`
- Run state / validity: `complete` / `valid`
- Manifest: `functional-v1-manifest:sha256:d579023b6df651ab0373f454ce494924110634c296a8b0cd4f8d3f611c87120f`
- Resolved manifest: `resolved-v1-manifest:sha256:4044261166cec2027f7f6fd3960df17852034229c8f7fbe588f215a831fec26a`
- Source YAML: `sha256:2ad6fd1f9f016c25a35f4593cbf55d1f162023f1943638b0baf8920421352ad2`

## Provider route and pricing

- Route: `https://opencode.ai/zen/go/v1`
- Exact model: `deepseek-v4-flash`
- Credential source: local `.env`, mode `0600`, variable `MODEL_BENCHMARK_PROVIDER_API_KEY`; the value is intentionally omitted.
- Limits per Trial: 64 requests, 100,000 provider tokens, stop after USD 5.00, 1,800 seconds, 2 CPUs, 4,096 MiB memory, 8,192 MiB writable disk.
- Cost accounting: the Credential Proxy recorded the provider-reported `cost` field on every response; all 47 provider responses were priced. Spend is the provider-reported figure, not a derived estimate.

## Exact operator commands

Run from the worktree root. `operator.sh` sources `.env` (only `MODEL_BENCHMARK_PROVIDER_API_KEY`) and exports `DOCKER_HOST=unix:///run/model-benchmark-docker/docker.sock` before `uv run model-benchmark`.

```sh
git worktree add -b run/issue-75-acceptance-b ~/code/nter/mb-issue75-b origin/master
cd ~/code/nter/mb-issue75-b && uv sync --frozen
chmod 600 .env

# network-enabled provisioning from a clean managed home
rm -rf .model-benchmark
./operator.sh --home .model-benchmark --json provision functional-v1-issue-75-b.yaml   # exit 0

# network-disabled preflight: the dedicated dockerd netns uplink (veth mb-host0) is
# downed for the whole preflight window and restored afterwards; the Docker socket and
# in-namespace bridges do not depend on the uplink.
sudo ip link set mb-host0 down
./operator.sh --home .model-benchmark --json preflight functional-v1-issue-75-b.yaml    # passed
sudo ip link set mb-host0 up

# the twelve-cell run, then read-only inspection
./operator.sh --home .model-benchmark --json run functional-v1-issue-75-b.yaml          # complete / valid
./operator.sh --home .model-benchmark --json inspect 019f6eec-1443-752c-ac0c-85c227e54035
```

## Cell evidence

| Cell | Disposition / reason | Requests | Tokens | USD | Task | Result Bundle |
|---|---|---:|---:|---:|---|---|
| 01 python / OMP | `valid_limit_outcome` / `tokens-stop-after-response` | 5 | 124528 | 0.00089076 | pass | `result-bundle:sha256:69725e0946e5f171987cf4d964594c4e36b3a11858aa07662b134ca677f471cb` |
| 02 python / OpenCode | `valid_harness_outcome` / `submission-rejected` | 8 | 62695 | 0.00087825 | fail | `result-bundle:sha256:8d073cea44b452484e5dac54578b8f26324c6c214408a6227b5e046aa0733683` |
| 03 python / Hermes | `valid_limit_outcome` / `tokens-stop-after-response` | 8 | 109035 | 0.00087075 | fail | `result-bundle:sha256:35dbfda6e2b7b3f0cfac30cc51a0eb778d7c0015635553c5f0c554a817f68767` |
| 04 python / Raw API | `valid_harness_outcome` / `condition-ended-before-provider-response` | 0 | 0 | 0 | fail | `result-bundle:sha256:acd954e763712690aa344a227b976aeec42968dd28be791be59b8a98352a80f0` |
| 05 Spring / OMP | `valid_harness_outcome` / `condition-ended-before-provider-response` | 0 | 0 | 0 | fail | `result-bundle:sha256:69f2defe6cc601cf23f3244e58342ec59175410a2e12b7d223d3840593af434b` |
| 06 Spring / OpenCode | `valid_harness_outcome` / `condition-ended-before-provider-response` | 0 | 0 | 0 | fail | `result-bundle:sha256:1b1d369953742120cad196b46cf7899dae7428949de69e49e752fbc9e1f2559c` |
| 07 Spring / Hermes | `valid_limit_outcome` / `tokens-stop-after-response` | 8 | 106928 | 0.00074390 | fail | `result-bundle:sha256:8e7417b11a900eeddafe2611e6cdb67919e7411bf3061a0a4185ba7a36923750` |
| 08 Spring / Raw API | `valid_harness_outcome` / `condition-ended-before-provider-response` | 0 | 0 | 0 | fail | `result-bundle:sha256:8473a2703ef0f851a263b443461d6ba4f651209213ef59fa422cc2d9320246d3` |
| 09 Angular / OMP | `valid_limit_outcome` / `tokens-stop-after-response` | 5 | 123050 | 0.00087679 | pass | `result-bundle:sha256:5864a4535dfe583874ec23cdbf1388709341e72f00bc4b5fb87322a75ee05dad` |
| 10 Angular / OpenCode | `valid_completed` / `verifier-completed` | 5 | 34499 | 0.00057415 | pass | `result-bundle:sha256:c4930998126bffa3887083bb116e41c2fb1813443ef7eb32b96cd99a275dfaa4` |
| 11 Angular / Hermes | `valid_limit_outcome` / `tokens-stop-after-response` | 8 | 110101 | 0.00069500 | fail | `result-bundle:sha256:bcf5d93d5f37b9dd4da64e378d7d19d42ac3b204b9edcf4f9e4c960acd621c46` |
| 12 Angular / Raw API | `valid_harness_outcome` / `condition-ended-before-provider-response` | 0 | 0 | 0 | fail | `result-bundle:sha256:ddf7f26ee2e74d1a2169dbf35d349873c55369c75e97f06e496ebf69e72784bb` |

Totals: 47 provider requests, 670,836 provider tokens, USD 0.00552960 provider-reported spend, 3/12 task-success cells, 12/12 regression-score cells. Dispositions: 1 completed, 5 valid limit outcomes, 6 valid harness outcomes (5 condition-ended-before-provider-response, 1 submission-rejected). Every terminal has `evidence_valid=true`; every Result Bundle exists and reads back.

## Post-run verification

- `inspect` run twice — byte-identical output (read-only, deterministic).
- `run --resume 019f6eec-…` — returns the inspect view and leaves the sealed Run Record unchanged (no-op).
- Digest read-back — the Run Record digest and all twelve Result Bundle digests reproduce their sealed identities (12/12).
- Cleanup inventory — zero Run-owned containers, networks, or volumes; only Docker's default `bridge`, `host`, `none` networks remain; no cell scratch left under `/tmp`.
- Credential audit — an exact-byte scan of the entire managed home for the live credential returned zero hits; the twelve harness records retain only the `MODEL_BENCHMARK_PROXY_TOKEN` placeholder.

## Defects found on master and fixed on this branch (run path)

Executing the sealed operator path end-to-end for the first time on real hardware surfaced defects that test fixtures had masked, beyond the provision/preflight fixes already listed in PR #93:

| Fix | Defect |
|---|---|
| stdlib-only proxy closure | The credential-proxy image is a bare Python base plus the runtime tree; the service imported `FIXED_LIMITS` from `declarations.functional_v1`, whose closure needs PyYAML/jsonschema, so the container died at import and the preflight isolation probe failed on name resolution. Moved `FIXED_LIMITS` to a stdlib-only `declarations.limits`; guarded by an import-closure architecture test. |
| condition-image content probe | The preflight mount probe asserted `/opt` inside the coordinator helper, which ships its own `/opt/model-benchmark-runtime`, so it could never pass. Assert the mounted condition image's `/artifact` tree instead; name copied artifacts after their condition. |
| wall-time probe integer | The preflight report carried a float `enforced_after_seconds`; canonical JSON forbids binary floats. Seal integer milliseconds. |
| zero-request evidence | The proxy created its evidence file lazily, so a zero-request Trial left no `proxy.jsonl` and the executor fail-closed the run. Touch the evidence file at proxy start. |
| container-owned scratch | Condition containers write Trial evidence as container root; the coordinator user could neither copy nor delete it. Hand the scratch tree back with a daemon-side recursive chown after Harbor exits. |
| capture build override | `services.capture.build: null` in the cell overlay was rejected by Compose schema validation. The override is unnecessary (every service pins a sealed image); removed it. |
| proxy runs as coordinator | The proxy dropped all capabilities, so its in-container root could not write the coordinator-owned evidence mount. Run the proxy as the coordinator uid. |
| Harbor 0.18 array manifest | Harbor writes `artifacts/manifest.json` as an array; the mapping-only parser marked valid cells `collector-failed`. Parse the array fail-closed. |
| condition home ownership | The main service drops all capabilities, so the adapter's runtime `chown` of the agent home always failed. Ensure `/logs/agent/home` is writable and let each launch script own its own `.model-benchmark`. |
| Hermes CLI import | The mounted Hermes venv could not import `hermes_cli` because the package root was absent from `PYTHONPATH`. Added it. |
| provider DNS egress | The isolated dockerd's embedded DNS forwards to the host's unreachable `127.0.0.53` stub, so the proxy on user networks could not resolve the provider route. Pin the proxy service to reachable public resolvers; condition containers stay isolated (they resolve only the internal `credential-proxy` alias). |
| rejected-capture sealing | A capture the boundary rejects (undeclared path) writes no patch, and Harbor runs the verifier regardless; two seal defects turned these valid harness outcomes into infrastructure failures. Restrict the collector check to the mandatory `capture.json`; seal `valid_completed` + rejected as `valid_harness_outcome` / `submission-rejected`. |

## Limitations and interventions

- Provider route is OpenCode Go/Zen because that is the credential available on this worker; the exact route/model are sealed in the manifest.
- USD 0.00552960 is the provider-reported spend under the flat-rate plan; it is not a per-token list-price estimate.
- Six cells legitimately made zero or limit-bounded provider progress: five conditions ended before a provider response (`valid_harness_outcome`), and five hit the 100,000-token threshold by one in-flight response (`valid_limit_outcome`). No cell approached the USD 5.00 threshold.
- Cell 02 (OpenCode, python) wrote an undeclared path; its submission sealed as `submission-rejected` (a valid harness outcome). This is model behaviour, not infrastructure.
- OMP cells 01 and 09 each report two non-mandatory native-diagnostic collection limitations; their required evidence and Result Bundles remain valid.
- The dedicated dockerd runs in a network namespace; the operator downed its uplink veth for the network-disabled preflight and restored it for the provider-enabled run. The proxy reaches the provider via pinned public resolvers rather than an operator DNS forwarder.

The acceptance claim is infrastructure and provenance validity, not model quality. No Harness ranking, winner, production, release, or statistical claim is made here or in any follow-up from this run.

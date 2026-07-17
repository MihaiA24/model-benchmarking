# Issue 75 Functional V1 native Linux handoff

Date: 2026-07-16 UTC

## Result

The native Linux/amd64 Functional V1 run completed all twelve Scenario-major cells with exactly three active slots and sealed a complete, valid Run Record.

- Run ID: `019f6ced-fd61-71d7-81d3-83d47c5037f0`
- Run Record: `functional-v1-run-record:sha256:56f17b4bebdf6585bf5fa21d63527c65f274e3212b1610f7e76dbe6690d4ba81`
- Run state / validity: `complete` / `valid`
- Manifest: `functional-v1-manifest:sha256:306eca861cf9afdf8bb6a0c240e1baf7045e5f4c1cc7bd171fb653460402f7e6`
- Resolved manifest: `resolved-v1-manifest:sha256:72b58ce41d2b044aa1f67384e3ecfab3b27677cf941f2d7473fab3681ded2301`
- Source YAML: `sha256:80cbb8a7632bf30356e6f2b624069d0cb9451a5f32c993ae8edac03012281c3e`
- Provisioning manifest: `provisioning-manifest:sha256:56b17470885146440456a1b5b42b74bd946c24bc3a62f3cc21bd64ef7cb189c8`
- Preflight report: `sha256:999eb71cfbdd03d16ae23f229d205bd24d0fb9a8b2443013f9bc0885d566e5eb`

## Qualified worker

Observed host and daemon configuration:

```text
Linux 7.1.3-2-cachyos x86_64
24 CPUs; 32,726,470,656 bytes memory
Docker 29.6.1; cgroup v2
Docker root: /var/lib/model-benchmark-worker/xfs/docker
Storage: overlay2 on /dev/loop0 XFS mounted at /var/lib/model-benchmark-worker/xfs with prjquota
```

The dedicated transient daemon was active with this exact `ExecStart`:

```text
/usr/bin/nsenter --net=/run/netns/model-benchmark-docker /usr/bin/dockerd --host=unix:///run/model-benchmark-docker/docker.sock --data-root=/var/lib/model-benchmark-worker/xfs/docker --exec-root=/run/model-benchmark-docker/exec --pidfile=/run/model-benchmark-docker/docker.pid --containerd=/run/model-benchmark-docker/containerd.sock --storage-driver=overlay2 --default-address-pool=base=10.251.0.0/16,size=24
```

Preflight observed 24 CPUs, 32,726,470,656 bytes memory, and 122,008,801,280 bytes free Docker storage against requirements of 8 CPUs, 25,769,803,776 bytes memory, and 53,687,091,200 bytes storage. It proved read-only selected condition images, no unselected artifacts, no verifier bytes, direct/public/LAN/metadata/host-route denial, a healthy Credential Proxy, zero provider requests, the three-slot envelope, and clean before/after inventories.

## Provider route and sealed pricing

- Route: `https://opencode.ai/zen/go/v1`
- Exact model: `deepseek-v4-flash`
- Credential source: local `.env`, mode `0600`, variable `MODEL_BENCHMARK_PROVIDER_API_KEY`; the value is intentionally omitted.
- Limits per Trial: 64 requests, 100,000 provider tokens, stop after USD 5.00, 1,800 seconds, 2 CPUs, 4,096 MiB memory, 8,192 MiB writable disk.
- Pricing identity: `pricing-record:sha256:bb89d137afcc43a9ac8dd4a5e21c3e490f3ea46ec4d1a67caf35f38ebd4e1031`
- Pricing source: `https://models.dev/providers/opencode-go`, retrieved `2026-07-16T20:50:00Z`; input USD 0.14/M tokens, output USD 0.28/M tokens.

OpenCode Go returned input/output token usage but no monetary-cost field. The Credential Proxy therefore used the immutable manifest Pricing Record to derive exact Decimal request cost, recorded the rate identity and input/output cost components on every provider response, and enforced stop-after-cost against the derived total. All 44 provider responses were priced; zero carried provider-reported cost.

## Exact operator commands

Run from repository root. The temporary DNS forwarder was required because the dedicated dockerd runs in a network namespace that cannot reach the host's `127.0.0.53` systemd-resolved stub. It was stopped for the network-disabled preflight, started for the provider-enabled run, and removed afterward.

The exact executed manifest bytes are archived at `artifacts/acceptance/issue-75/functional-v1-manifest.yaml`; its SHA-256 is the Source YAML digest above. `functional-v1-issue-75.yaml` is the rebased, runnable manifest for the current branch tip.

```bash
export DOCKER_HOST=unix:///run/model-benchmark-docker/docker.sock
chmod 600 .env
uv sync --frozen

uv run --frozen --env-file .env model-benchmark \
  --home .benchmark-cache/issue-75-final --json \
  provision functional-v1-issue-75.yaml

docker stop model-benchmark-dns-forwarder
uv run --frozen --env-file .env model-benchmark \
  --home .benchmark-cache/issue-75-final --json \
  preflight functional-v1-issue-75.yaml

docker start model-benchmark-dns-forwarder
uv run --frozen --env-file .env model-benchmark \
  --home .benchmark-cache/issue-75-final --json \
  run functional-v1-issue-75.yaml

uv run --frozen model-benchmark \
  --home .benchmark-cache/issue-75-final --json \
  inspect 019f6ced-fd61-71d7-81d3-83d47c5037f0

docker rm --force model-benchmark-dns-forwarder
docker ps --all --format '{{.Names}}|{{.Status}}'
docker network ls --format '{{.Name}}|{{.Driver}}'
```

Final cleanup output contained no containers and only Docker's default networks: `bridge`, `host`, and `none`.

## Cell evidence

| Cell | Disposition / reason | Requests | Tokens | USD | Task | Result Bundle |
|---|---|---:|---:|---:|---|---|
| 01 python / OMP | `valid_limit_outcome` / `tokens-stop-after-response` | 4 | 100484 | 0.01426894 | pass | `result-bundle:sha256:91a1afc0af4f124e583b6d0d3530a5f11fa95f2c0cd769bcc068872f107bb00d` |
| 02 python / OpenCode | `valid_completed` / `verifier-completed` | 6 | 45786 | 0.00664202 | pass | `result-bundle:sha256:6b2c4fa40a5c01ac79a5f5a43a83f8f7a9bc322a671b88ae0b5f1abb2a6820df` |
| 03 python / Hermes | `valid_limit_outcome` / `tokens-stop-after-response` | 8 | 106510 | 0.01503796 | fail | `result-bundle:sha256:7c20491779583d77cf8d1250aa04efb2266fa94a1d782dda5be04031720e1acb` |
| 04 python / Raw API | `valid_harness_outcome` / `condition-ended-before-provider-response` | 0 | 0 | 0 | fail | `result-bundle:sha256:844d44706fe4397efca9d9e284661cf4c23442d0202443ceee4d6a85b10e0c95` |
| 05 Spring / OMP | `valid_harness_outcome` / `condition-ended-before-provider-response` | 0 | 0 | 0 | fail | `result-bundle:sha256:0040c09a346f0be80cad3a9fd2082f2d2725d20c882ecbf4901c1d3d291a9816` |
| 06 Spring / OpenCode | `valid_harness_outcome` / `condition-ended-before-provider-response` | 0 | 0 | 0 | fail | `result-bundle:sha256:f7eb715f15b76507d643dc1e1bffc9fd135cdfd6294213960fee0c4f60a51c9f` |
| 07 Spring / Hermes | `valid_limit_outcome` / `tokens-stop-after-response` | 8 | 107035 | 0.01515738 | fail | `result-bundle:sha256:031108001b23ae19540b0674d483ea0480f6316014dc7860c9f795a04599ab93` |
| 08 Spring / Raw API | `valid_harness_outcome` / `condition-ended-before-provider-response` | 0 | 0 | 0 | fail | `result-bundle:sha256:e77125bdd1479decf8f267f2065dad2ed06b8c90da142f5aec1e03ea1c342721` |
| 09 Angular / OMP | `valid_limit_outcome` / `tokens-stop-after-response` | 5 | 123256 | 0.01739934 | pass | `result-bundle:sha256:80419f3b4534cd6860ac56c719f2b77c714cf7ebe3304a3de3282a5524f8323c` |
| 10 Angular / OpenCode | `valid_completed` / `verifier-completed` | 5 | 34636 | 0.00500976 | pass | `result-bundle:sha256:82c048cbec7a220d290b7d9bc127e3a276054bf4e1aa355a0049c20b93c32f49` |
| 11 Angular / Hermes | `valid_limit_outcome` / `tokens-stop-after-response` | 8 | 110346 | 0.01557416 | fail | `result-bundle:sha256:f9f2abb63ca60f2692f6ec98734ea98f0e6269cc604630ab8b976cdd2488a4b2` |
| 12 Angular / Raw API | `valid_harness_outcome` / `condition-ended-before-provider-response` | 0 | 0 | 0 | fail | `result-bundle:sha256:328fc0ca308a9200c13d24439addb49801439458a6c11f4658c69af1695d0cd4` |

Totals: 44 provider requests, 628,053 provider tokens, USD 0.08908956 proxy-accounted equivalent cost, 4/12 task-success cells, and 12/12 regression-score cells. Every terminal has `evidence_valid=true`; every Result Bundle exists. Dispositions: 2 completed, 5 valid limit outcomes, 5 valid harness outcomes.

## Evidence pointers

```text
artifacts/acceptance/issue-75/functional-v1-manifest.yaml
.benchmark-cache/issue-75-final/inputs/functional-v1-manifest/306eca861cf9afdf8bb6a0c240e1baf7045e5f4c1cc7bd171fb653460402f7e6.json
.benchmark-cache/issue-75-final/provisioning/306eca861cf9afdf8bb6a0c240e1baf7045e5f4c1cc7bd171fb653460402f7e6.json
.benchmark-cache/issue-75-final/runs/019f6ced-fd61-71d7-81d3-83d47c5037f0/provenance.json
.benchmark-cache/issue-75-final/runs/019f6ced-fd61-71d7-81d3-83d47c5037f0/run-record.json
.benchmark-cache/issue-75-final/runs/019f6ced-fd61-71d7-81d3-83d47c5037f0/run-record.identity
.benchmark-cache/issue-75-final/runs/019f6ced-fd61-71d7-81d3-83d47c5037f0/cells/<cell-id>/terminal.json
.benchmark-cache/issue-75-final/runs/019f6ced-fd61-71d7-81d3-83d47c5037f0/cells/<cell-id>/bundle/
.benchmark-cache/issue-75-final/runs/019f6ced-fd61-71d7-81d3-83d47c5037f0/cells/<cell-id>/raw/proxy-evidence/proxy.jsonl
```

## Credential and integrity audit

An exact-byte scan using the live credential against every regular file below `.benchmark-cache/issue-75-final` returned zero hits. The selected overlay gives the real credential only to `credential-proxy`; the `main` condition service has no real provider credential and harness records retain only the `MODEL_BENCHMARK_PROXY_TOKEN` placeholder. No real credential occurred in command arguments, condition environments, logs, proxy events, bundles, or canonical Run records.

All twelve Result Bundles and all terminals were read back successfully. The Harbor 0.18 collector emits `artifacts/manifest.json` as an array; the prior mapping-only parser incorrectly marked otherwise valid cells `collector-failed`. The runtime now parses and fail-closes the native array format, covered by a deterministic regression test.

## Verification

```text
35 passed — issue 32 proxy + issue 37 + issue 74 manifest contracts
15 passed — complete Result Bundle contract
145 passed — complete unit suite with installed pytest plugin
1 passed — Harbor array-manifest red/green regression
python -m compileall -q src/model_benchmark tests — exit 0
native provision — provisioned
network-disabled preflight — passed
native twelve-cell run — complete / valid
inspect — complete
```

## Limitations and interventions

- The provider route is OpenCode Go because it was the only valid credential available on this worker. OpenRouter rejected the available key. The exact route/model are sealed in the manifest.
- USD 0.08908956 is a proxy-accounted equivalent at the sealed per-token rates; OpenCode Go is subscription-backed and reported no monetary cost. It is not a provider invoice charge.
- Five cells legitimately exceeded the 100,000-token threshold by one in-flight response and sealed as valid limit outcomes. No cell approached the USD 5.00 threshold.
- Five cells ended before a provider response and sealed as valid harness outcomes. Four cells achieved task success. The acceptance claim is infrastructure/provenance validity, not model quality.
- OMP cells 01 and 09 report two non-mandatory native-diagnostic collection limitations each; their required evidence and Result Bundles remain valid.
- A temporary DNS forwarder was operator-provided for the isolated dockerd namespace during the provider-enabled run and was removed after cleanup. The preflight itself ran with that forwarder stopped.

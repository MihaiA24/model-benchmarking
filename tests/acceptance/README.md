# Acceptance proof suite

Each directory below is one **authoritative proof**: the complete acceptance
gate for one GitHub issue. Directories are named `issue_N_<domain>` — the
number is the proof identity, the slug says what it defends. Proofs publish
`artifacts/acceptance/issue-N/{verification.json,sha256sums.txt}` on success
and are removed fail-closed on any other outcome.

## Run

```sh
# whole suite, dependency order (needs a running Docker daemon)
uv run python scripts/acceptance.py

# inspect the plan / run a subset
uv run python scripts/acceptance.py --list
uv run python scripts/acceptance.py --only 33,34,35
uv run python scripts/acceptance.py --from 36 --keep-going

# one proof by hand (exactly one directory, --maxfail=1, no selection flags)
uv run --frozen pytest -q tests/acceptance/issue_28_foundation_harness --maxfail=1
```

The ordered stage manifest lives in `scripts/acceptance.py` (`STAGES`);
`tests/unit/test_acceptance_suite.py` keeps it, this README, and the
directories on disk in lockstep.

## Stages

| Order | Group | Directory | Proves | Notes |
| --- | --- | --- | --- | --- |
| 1 | foundation | `issue_28_foundation_harness` | Canonical JSON, identities, strict schemas, operator CLI, and the proof harness itself | |
| 2 | authoring | `issue_29_scenario_authoring` | Scenario scaffold → check → lock gates and the Docker qualification pipeline | Docker, expensive |
| 3 | conditions | `issue_32_condition_runner` | Credential proxy, raw-API materializer, generic sealed condition runner | |
| 4 | conditions | `issue_33_omp_condition` | OMP v16.4.0 condition lock, digest-first provisioning, fresh RPC trials | |
| 5 | conditions | `issue_34_opencode_condition` | OpenCode v1.17.18 condition lock and stock stdin-JSON-events trials | |
| 6 | conditions | `issue_35_hermes_condition` | Hermes v0.18.2 condition lock and native oneshot trials | |
| 7 | runtime | `issue_36_execution_scheduler` | Sliding-window cell scheduler and Harbor executor terminal facts | |
| 8 | runtime | `issue_37_evidence_sealing` | Drain-to-seal result bundles and run-record enrichment | |
| 9 | scenarios | `issue_40_functional_v1_scenarios` | Calibration packages lock deterministically with complete qualification evidence | |
| 10 | verification | `issue_51_proof_hardening` | Harness rejects partial selection, configuration failures, stale outputs | Docker probe |
| 11 | verification | `issue_54_verification_policy` | Closed-world development verification policy and guarded development runs | |
| 12 | provisioning | `issue_55_digest_provisioning` | Cold registry pull, then warm cache with zero registry traffic | Docker, slow (~10 min) |
| 13 | operator | `issue_74_functional_v1_operator` | Functional V1 operator: manifest, managed home, dispositions, CLI | |
| 14 | operator | `issue_123_hy3_manifest` | Hy3 manifest route, pricing, fixed matrix, and canonical identities | Seals authored manifest input |

## Proof contract

Enforced by the `model-benchmark-acceptance` pytest plugin
(`src/model_benchmark/evidence/pytest_acceptance.py`):

- A proof run targets **exactly one** `issue_N[_slug]` directory with
  `--maxfail=1`; selection options (`-k`, `--ignore`, `--deselect`, …) are
  rejected, and skips/xfails invalidate the proof.
- Two directories claiming the same issue number are rejected.
- Issues 29 and 55 mandate a responding Docker daemon; issue 51's canonical
  invocation adds `--require-docker --acceptance-input=tests/architecture`. Issue 123
  adds `--acceptance-input=functional-v1-hy3.yaml` so the authored manifest enters its
  proof identity (see `research/development-and-ci-verification-strategy.md`).
- On a full pass the plugin seals `artifacts/acceptance/issue-N/` with the
  executed command, case inventory, and digests over `src/`,
  `tests/conftest.py`, the issue directory, `tests/fixtures/`, `profiles/`,
  and `scaffolds/`. Anything else — including publication failure — removes
  those artifacts.
- `--run-live` additionally requires a sealed live-prerequisite attestation
  (`MODEL_BENCHMARK_LIVE_ATTESTATION`).

Development verification (`scripts/verify.py`) is the non-authoritative
counterpart: it selects `tests/unit`/`tests/architecture`/`tests/conformance`
slices from `verification/policy.json` and refuses to execute anything under
`tests/acceptance/`.

## Design notes

- **Proof directories are deliberately self-contained.** Fixtures such as the
  `RecordingProvider` variants (32/33/34/35) and `manifest_bundle` (37/74) are
  duplicated per directory on purpose: a proof's source-tree digest covers its
  own directory, so shared helpers under `tests/acceptance/` would sit outside
  the sealed inventory. Do not "DRY" them across proof boundaries.
- Artifact directories keep the numeric `issue-N` form; renaming a test
  directory never moves an artifact, and stale `verification.json` contents
  heal on the next successful run.

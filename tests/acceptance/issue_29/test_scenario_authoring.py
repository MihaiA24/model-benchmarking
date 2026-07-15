from __future__ import annotations

import json
import subprocess
import tarfile
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from harbor.models.task.task import Task
from harbor.publisher.packager import Packager

from model_benchmark.declarations.identities import DigestKind, TypedDigest
from model_benchmark.declarations.scenario_locks import HARBOR_COMMIT
from model_benchmark.declarations.scenario_qualification import (
    validate_scenario_state_transition,
)
from model_benchmark.declarations.scenario_sources import normalized_tree_digest
from model_benchmark.declarations.schemas import SchemaRegistry
from model_benchmark.declarations.scenarios import ScenarioPackageError


ROOT = Path(__file__).resolve().parents[3]
REGISTRY = SchemaRegistry(ROOT / "schemas")
ECOSYSTEMS = (
    "angular-typescript",
    "spring-boot-java",
    "python-data-engineering",
)


def _artifact(path: Path) -> str:
    return str(TypedDigest.from_bytes(DigestKind.ARTIFACT, path.read_bytes()))


def _qualification_command(case: Any, runner: Any) -> Any:
    return runner(
        "qualify",
        str(case.package),
        "--technical-evidence",
        str(case.technical_path),
        "--trusted-worker-identity",
        case.technical["worker"]["identity"],
        "--review",
        str(case.review_path),
        "--trusted-reviewer-identity",
        case.review["reviewer"]["identity"],
        "--output",
        str(case.output_path),
    )


@pytest.mark.parametrize("ecosystem", ECOSYSTEMS)
def test_each_ecosystem_fixture_passes_schema_and_exact_pinned_harbor_loader(
    tmp_path: Path,
    ecosystem: str,
    scenario_scaffold: Any,
    scenario_runner: Any,
) -> None:
    package = scenario_scaffold(
        tmp_path / ecosystem,
        scenario_id=f"acceptance/{ecosystem}",
        ecosystem=ecosystem,
        visibility="public",
    )

    checked = scenario_runner("check", str(package))
    task = Task(package)
    content_hash, packaged_files = Packager.compute_content_hash(package)

    assert checked.returncode == 0, checked.stderr or checked.stdout
    summary = json.loads(checked.stdout)
    assert summary["harbor_commit"] == HARBOR_COMMIT
    assert summary["harbor_task_sha256"] == f"harbor-task:sha256:{content_hash}"
    assert task.name == f"acceptance/{ecosystem}"
    assert packaged_files


def test_scaffold_check_and_lock_are_byte_reproducible(
    tmp_path: Path,
    scenario_scaffold: Any,
    scenario_runner: Any,
) -> None:
    first = scenario_scaffold(
        tmp_path / "first",
        scenario_id="acceptance/reproducible",
        ecosystem="python-data-engineering",
    )
    second = scenario_scaffold(
        tmp_path / "second",
        scenario_id="acceptance/reproducible",
        ecosystem="python-data-engineering",
    )

    for package in (first, second):
        checked = scenario_runner("check", str(package))
        assert checked.returncode == 0, checked.stderr or checked.stdout
        locked = scenario_runner("lock", str(package))
        assert locked.returncode == 0, locked.stderr or locked.stdout
        first_lock = (package / "scenario.lock.json").read_bytes()
        relocked = scenario_runner("lock", str(package))
        assert relocked.returncode == 0, relocked.stderr or relocked.stdout
        assert (package / "scenario.lock.json").read_bytes() == first_lock

    assert (first / "scenario.lock.json").read_bytes() == (
        second / "scenario.lock.json"
    ).read_bytes()
    first_files = {
        path.relative_to(first).as_posix(): path.read_bytes()
        for path in first.rglob("*")
        if path.is_file()
    }
    second_files = {
        path.relative_to(second).as_posix(): path.read_bytes()
        for path in second.rglob("*")
        if path.is_file()
    }
    assert first_files == second_files


@pytest.mark.parametrize(
    ("failure", "classification"),
    [
        ("duplicate-yaml", "invalid-scenario-yaml"),
        ("unknown-schema-field", "invalid-scenario-schema"),
        ("profile-drift", "profile-mismatch"),
        ("hidden-marker", "answer-leakage"),
    ],
)
def test_authoring_gates_fail_closed(
    tmp_path: Path,
    failure: str,
    classification: str,
    scenario_scaffold: Any,
    scenario_runner: Any,
) -> None:
    package = scenario_scaffold(
        tmp_path / failure,
        scenario_id=f"acceptance/{failure}",
        ecosystem="angular-typescript",
    )
    if failure == "duplicate-yaml":
        path = package / "scenario.yaml"
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace(
                "schema_version: 1\n",
                "schema_version: 1\nschema_version: 1\n",
                1,
            ),
            encoding="utf-8",
        )
    elif failure == "unknown-schema-field":
        path = package / "scenario.yaml"
        manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
        manifest["verification"]["unknown"] = True
        path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    elif failure == "profile-drift":
        path = package / "task.toml"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "storage_mb = 1024",
                "storage_mb = 2048",
            ),
            encoding="utf-8",
        )
    else:
        marker = "MODEL_BENCHMARK_HIDDEN:acceptance-answer\n"
        with (package / "solution/solve.sh").open("a", encoding="utf-8") as stream:
            stream.write(marker)
        (package / "environment/leaked.txt").write_text(marker, encoding="utf-8")

    checked = scenario_runner("check", str(package))

    assert checked.returncode != 0
    assert json.loads(checked.stdout)["classification"] == classification


def test_pristine_seed_baseline_and_dataset_are_reconstructed_without_downloads(
    tmp_path: Path,
    scenario_scaffold: Any,
    scenario_runner: Any,
) -> None:
    package = scenario_scaffold(
        tmp_path / "source-package",
        scenario_id="acceptance/source-identities",
        ecosystem="spring-boot-java",
    )
    pristine = tmp_path / "pristine"
    baseline = tmp_path / "baseline"
    pristine.mkdir()
    baseline.mkdir()
    (pristine / "value.txt").write_text("before\n", encoding="utf-8")
    (baseline / "value.txt").write_text("after\n", encoding="utf-8")
    (package / "environment/baseline/value.txt").write_text(
        "after\n",
        encoding="utf-8",
    )
    archive = package / "seed/pristine.tar"
    archive.parent.mkdir()
    with tarfile.open(archive, "w") as tar:
        tar.add(pristine / "value.txt", arcname="value.txt")
    patch = package / "seed/baseline.patch"
    patch.write_text(
        "diff --git a/value.txt b/value.txt\n"
        "--- a/value.txt\n"
        "+++ b/value.txt\n"
        "@@ -1 +1 @@\n"
        "-before\n"
        "+after\n",
        encoding="utf-8",
    )
    dataset = package / "data/fixture.csv"
    dataset.parent.mkdir()
    dataset.write_text("id,value\n1,locked\n", encoding="utf-8")
    manifest_path = package / "scenario.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["repository"] = {
        "pristine": {
            "origin": "https://github.com/example/pristine",
            "commit": "c" * 40,
            "archive": "seed/pristine.tar",
            "archive_sha256": _artifact(archive),
            "tree_sha256": str(normalized_tree_digest(pristine)),
            "license": "Apache-2.0",
        },
        "seed_inputs": [
            {
                "kind": "git-patch",
                "path": "seed/baseline.patch",
                "sha256": _artifact(patch),
            }
        ],
        "baseline_tree_sha256": str(normalized_tree_digest(baseline)),
        "datasets": [
            {
                "id": "locked-fixture",
                "path": "data/fixture.csv",
                "sha256": _artifact(dataset),
                "visibility": "agent",
            }
        ],
    }
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False),
        encoding="utf-8",
    )

    locked = scenario_runner("lock", str(package))

    assert locked.returncode == 0, locked.stderr or locked.stdout
    lock: Any = REGISTRY.validate_bytes((package / "scenario.lock.json").read_bytes())
    assert lock["resolved_inputs"]["pristine"]["tree_sha256"] == str(
        normalized_tree_digest(pristine)
    )
    assert lock["resolved_inputs"]["scenario_baseline"] == str(
        normalized_tree_digest(baseline)
    )
    assert lock["resolved_inputs"]["datasets"][0]["sha256"] == _artifact(dataset)


def test_non_patch_output_requires_harbor_sidecar_collect_materialization(
    tmp_path: Path,
    scenario_scaffold: Any,
    scenario_runner: Any,
) -> None:
    package = scenario_scaffold(
        tmp_path / "artifact-output",
        scenario_id="acceptance/non-patch-output",
        ecosystem="python-data-engineering",
    )
    schema = REGISTRY.entry("model-benchmark/verification-artifact", 1)
    task_path = package / "task.toml"
    task = task_path.read_text(encoding="utf-8")
    task = task.replace(
        "artifacts = [\n"
        '  { source = "/capture/capture.json", service = "capture" },\n'
        '  { source = "/capture/submission.patch", service = "capture" },\n'
        "]\n",
        "artifacts = [\n"
        '  { source = "/capture/materialization.json", service = "capture" },\n'
        '  { source = "/capture/output.json", service = "capture" },\n'
        "]\n",
        1,
    )
    task = task.replace(
        "[[verifier.collect]]\n"
        'service = "capture"\n'
        'command = "python3 /opt/capture/capture.py --repository /input/repository --baseline /opt/capture/baseline --policy /opt/capture/policy.json --output /capture"\n'
        "timeout_sec = 30.0\n",
        "[[verifier.collect]]\n"
        'service = "capture"\n'
        'command = "python3 /opt/capture/capture.py --artifact-source '
        "/input/repository/submission/output.json --artifact-output /capture/output.json "
        "--artifact-record /capture/materialization.json --artifact-media-type "
        f"application/json --artifact-schema-sha256 {schema.sha256} "
        "--artifact-max-bytes 100000 --visibility-root /input/repository "
        "--forbidden-marker MODEL_BENCHMARK_HIDDEN:replace-with-private-verifier-canary "
        '--stability-window-ms 250"\n'
        "timeout_sec = 30.0\n",
        1,
    )
    task_path.write_text(task, encoding="utf-8")
    manifest_path = package / "scenario.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["submission"] = {
        "kind": "artifact",
        "allowed_paths": ["submission/output.json"],
        "media_type": "application/json",
        "schema": {
            "name": schema.name,
            "version": schema.version,
            "sha256": schema.sha256,
        },
        "max_bytes": 100_000,
        "digest_algorithm": "sha256",
        "materialization": {
            "destination": "/capture/output.json",
            "mode": "copy-no-follow",
            "service": "capture",
        },
    }
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False),
        encoding="utf-8",
    )

    checked = scenario_runner("check", str(package))

    assert checked.returncode == 0, checked.stderr or checked.stdout


def test_production_qualify_measures_harbor_and_seals_authenticated_evidence(
    tmp_path: Path,
    scenario_scaffold: Any,
    scenario_runner: Any,
    document_writer: Any,
    review_signer: Any,
) -> None:
    package = scenario_scaffold(
        tmp_path / "live-package",
        scenario_id="acceptance/live-qualification",
        ecosystem="python-data-engineering",
        visibility="public",
    )
    locked = scenario_runner("lock", str(package))
    assert locked.returncode == 0, locked.stderr or locked.stdout
    worker_key = tmp_path / "worker.key"
    worker_key.write_bytes(bytes.fromhex("24" * 32))
    worker_key.chmod(0o600)

    context = subprocess.run(
        ["docker", "context", "show"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    platform = (
        subprocess.run(
            ["docker", "info", "--format", "{{.OSType}}/{{.Architecture}}"],
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.strip()
        .replace("aarch64", "arm64")
        .replace("x86_64", "amd64")
    )
    target_config = tmp_path / "provisioning-targets.yaml"
    target_config.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "visibility_domains": {
                    "public": {"docker_context": context, "platform": platform},
                    "private": {
                        "docker_context": "acceptance-unused-private-store",
                        "platform": platform,
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    provisioning_manifest = tmp_path / "provisioning-manifest.json"
    provisioned = scenario_runner(
        "qualify",
        str(package),
        "--provision",
        "--jobs-dir",
        str(tmp_path / "provision-jobs"),
        "--target-config",
        str(target_config),
        "--provisioning-manifest",
        str(provisioning_manifest),
    )
    assert provisioned.returncode == 0, provisioned.stderr or provisioned.stdout

    technical_path = tmp_path / "technical-qualification.json"
    measured = scenario_runner(
        "qualify",
        str(package),
        "--measure-output",
        str(technical_path),
        "--jobs-dir",
        str(tmp_path / "measured-jobs"),
        "--worker-private-key",
        str(worker_key),
        "--max-parallel",
        "3",
        "--provisioning-manifest",
        str(provisioning_manifest),
        "--preflight-output",
        str(tmp_path / "qualification-preflight"),
    )
    assert measured.returncode == 0, measured.stderr or measured.stdout
    measurement = json.loads(measured.stdout)
    assert measurement["max_parallel"] == 3
    assert len(measurement["generation_id"]) == 32
    technical: Any = REGISTRY.validate_bytes(technical_path.read_bytes())
    runs = technical["runs"]
    assert technical["provisioning"]["manifest_sha256"].startswith(
        "provisioning-manifest:sha256:"
    )
    assert runs["baseline"]["outcome"] == "declared-failure"
    assert [run["outcome"] for run in runs["reference"]] == ["passed", "passed"]
    assert runs["no_download"] is True
    assert (
        len(
            {
                runs["baseline"]["environment_id"],
                runs["hidden_marker"]["environment_id"],
                *(run["environment_id"] for run in runs["reference"]),
            }
        )
        == 4
    )

    lock_data = (package / "scenario.lock.json").read_bytes()
    lock: Any = REGISTRY.validate_bytes(lock_data)
    reviewed_at = (
        (
            datetime.fromisoformat(technical["qualified_at"].replace("Z", "+00:00"))
            + timedelta(seconds=1)
        )
        .astimezone(UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )
    review: dict[str, Any] = {
        "checklist_version": 1,
        "identities": lock["identities"],
        "judgment": "approve",
        "package_lock_sha256": str(
            TypedDigest.from_bytes(DigestKind.PACKAGE_LOCK, lock_data)
        ),
        "package_payload_sha256": lock["package"]["payload_sha256"],
        "reasons": {
            "answer_leakage": "The live package preserves the hidden-asset boundary.",
            "brief_verifier_alignment": "Measured scores match the declared contract.",
            "difficulty_and_boundedness": "The conformance task is intentionally bounded.",
            "disclosure_handling": "The fixture is safe for public acceptance evidence.",
            "implementation_neutrality": "The brief does not prescribe an implementation.",
            "professional_realism": "The package exercises the production handoff seam.",
            "provenance_and_licensing": "All fixture inputs are repository-authored.",
        },
        "reviewed_at": reviewed_at,
        "reviewer": {
            "principal_identity": "urn:model-benchmark:author:independent-reviewer",
            "authentication": {"kind": "signature", "value": "pending"},
            "identity": "pending",
            "independence_attested": True,
        },
        "schema": REGISTRY.envelope("model-benchmark/scenario-review", 1),
    }
    review_signer(review)
    review_path = tmp_path / "scenario-review.json"
    document_writer(review_path, review)
    pqr_path = tmp_path / "package-qualification-record.json"
    sealed = scenario_runner(
        "qualify",
        str(package),
        "--technical-evidence",
        str(technical_path),
        "--trusted-worker-identity",
        measurement["worker_identity"],
        "--review",
        str(review_path),
        "--trusted-reviewer-identity",
        review["reviewer"]["identity"],
        "--output",
        str(pqr_path),
    )
    assert sealed.returncode == 0, sealed.stderr or sealed.stdout
    pqr: Any = REGISTRY.validate_bytes(pqr_path.read_bytes())
    assert pqr["qualification"]["worker_identity"] == measurement["worker_identity"]


@pytest.mark.usefixtures("qualification_case")
def test_technical_qualification_review_and_pqr_ordering(
    qualification_case: Any,
    scenario_runner: Any,
) -> None:
    case = qualification_case
    completed = _qualification_command(case, scenario_runner)

    assert completed.returncode == 0, completed.stderr or completed.stdout
    first = case.output_path.read_bytes()
    record = REGISTRY.validate_bytes(first)
    assert record["lifecycle"] == {"from": "candidate", "to": "package_qualified"}
    assert record["state"] == "package_qualified"
    runs = case.technical["runs"]
    environments = {
        runs["baseline"]["environment_id"],
        runs["hidden_marker"]["environment_id"],
        *(run["environment_id"] for run in runs["reference"]),
        *(run["environment_id"] for run in runs["handoffs"]),
        runs["score_mismatch"]["environment_id"],
    }
    assert len(environments) == 7
    assert runs["score_mismatch"]["status"] == "passed"
    assert runs["no_download"] is True
    for run in [runs["baseline"], *runs["reference"]]:
        assert run["structured_score_vector"] == run["reward_score_vector"]
    second = _qualification_command(case, scenario_runner)
    assert second.returncode == 0, second.stderr or second.stdout
    assert case.output_path.read_bytes() == first


@pytest.mark.parametrize(
    ("failure", "classification"),
    [
        ("reward-mismatch", "invalid-infrastructure"),
        ("unsafe-handoff-succeeds", "invalid-technical-qualification"),
        ("qualification-download", "invalid-technical-qualification"),
        ("stale-review", "stale-independent-review"),
        ("package-changed-after-review", "instruction-digest-mismatch"),
    ],
)
def test_qualification_review_and_identity_failures_leave_no_authoritative_pqr(
    failure: str,
    classification: str,
    qualification_case: Any,
    scenario_runner: Any,
    document_writer: Any,
    technical_signer: Any,
) -> None:
    case = qualification_case
    technical = deepcopy(case.technical)
    review = deepcopy(case.review)
    if failure == "reward-mismatch":
        technical["runs"]["reference"][0]["reward_score_vector"][0]["value"] = "0"
    elif failure == "unsafe-handoff-succeeds":
        technical["runs"]["handoffs"][1]["task_success"] = True
    elif failure == "qualification-download":
        technical["runs"]["no_download"] = False
    elif failure == "stale-review":
        review["package_lock_sha256"] = "package-lock:sha256:" + "0" * 64
    else:
        with (case.package / "instruction.md").open("a", encoding="utf-8") as stream:
            stream.write("changed after review\n")
    if failure in {
        "reward-mismatch",
        "unsafe-handoff-succeeds",
        "qualification-download",
    }:
        technical_signer(technical)
    document_writer(case.technical_path, technical)
    document_writer(case.review_path, review)

    completed = _qualification_command(case, scenario_runner)

    assert completed.returncode != 0
    assert json.loads(completed.stdout)["classification"] == classification
    assert not case.output_path.exists()


def test_scenario_state_flow_is_closed() -> None:
    for current, requested in (
        ("authoring_target", "candidate"),
        ("private_slot", "candidate"),
        ("candidate", "package_qualified"),
        ("package_qualified", "roster_selected"),
        ("roster_selected", "suite_sealed"),
    ):
        validate_scenario_state_transition(current, requested)

    with pytest.raises(ScenarioPackageError, match="cannot move"):
        validate_scenario_state_transition("candidate", "suite_sealed")


def test_authoritative_schemas_are_catalogued_and_strict() -> None:
    expected = {
        "model-benchmark/package-qualification-record",
        "model-benchmark/scenario-lock",
        "model-benchmark/scenario-package",
        "model-benchmark/scenario-review",
        "model-benchmark/scenario-technical-qualification",
    }
    entries = {entry.name for entry in REGISTRY.entries}
    assert expected <= entries
    for name in expected:
        entry = REGISTRY.entry(name, 1)
        schema = json.loads((ROOT / "schemas" / entry.file).read_bytes())
        assert schema["x-model-benchmark-schema-name"] == name
        assert schema["additionalProperties"] is False

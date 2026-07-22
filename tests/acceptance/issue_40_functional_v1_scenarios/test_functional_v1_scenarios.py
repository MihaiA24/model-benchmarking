from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

from model_benchmark.declarations.identities import DigestKind, TypedDigest
from model_benchmark.declarations.scenario_locks import schema_root_path
from model_benchmark.declarations.schemas import SchemaRegistry


ROOT = Path(__file__).resolve().parents[3]
SCENARIO_ROOT = ROOT / "scenarios/calibration"
EVIDENCE_ROOT = ROOT / "artifacts/qualification/functional-v1"
PACKAGES = {
    "angular-reading-time": "functional-v1/angular-reading-time",
    "python-sales-by-genre": "functional-v1/python-sales-by-genre",
    "spring-petvalidator-whitespace": "functional-v1/spring-petvalidator-whitespace",
}
REGISTRY = SchemaRegistry(schema_root_path())


def run_scenario(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["model-benchmark-scenario", "--json", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def load_document(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_package_set_is_exact_and_diagnostic_only() -> None:
    package_directories = sorted(path.name for path in SCENARIO_ROOT.iterdir() if path.is_dir())
    assert package_directories == sorted(PACKAGES)

    for directory, scenario_id in PACKAGES.items():
        package = SCENARIO_ROOT / directory
        manifest = yaml.safe_load((package / "scenario.yaml").read_text(encoding="utf-8"))
        assert manifest["scenario"] == {
            **manifest["scenario"],
            "id": scenario_id,
            "lifecycle_state": "candidate",
            "visibility": "public",
        }
        serialized = json.dumps(manifest, sort_keys=True).lower()
        assert "suite" not in serialized
        assert "ranking" not in serialized
        assert "statistical" not in serialized

        checked = run_scenario("check", str(package))
        assert checked.returncode == 0, checked.stderr or checked.stdout
        assert json.loads(checked.stdout)["lock"] == "valid"


def test_locks_reproduce_every_package_identity(tmp_path: Path) -> None:
    for directory, scenario_id in PACKAGES.items():
        package = SCENARIO_ROOT / directory
        expected = (package / "scenario.lock.json").read_bytes()
        copied = tmp_path / directory
        shutil.copytree(package, copied)

        first = run_scenario("lock", str(copied))
        assert first.returncode == 0, first.stderr or first.stdout
        assert (copied / "scenario.lock.json").read_bytes() == expected
        second = run_scenario("lock", str(copied))
        assert second.returncode == 0, second.stderr or second.stdout
        assert (copied / "scenario.lock.json").read_bytes() == expected

        lock = REGISTRY.validate_bytes(expected)
        assert lock["scenario_id"] == scenario_id
        assert str(TypedDigest.from_bytes(DigestKind.PACKAGE_LOCK, expected)) == json.loads(first.stdout)["lock_sha256"]
        assert {identity["kind"] for identity in lock["identities"].values()} == {
            "scenario",
            "score-contract",
            "verifier",
        }


def test_sales_fixtures_reproduce_from_the_declared_generator(tmp_path: Path) -> None:
    source = SCENARIO_ROOT / "python-sales-by-genre"
    copied = tmp_path / source.name
    shutil.copytree(source, copied)
    expected = {
        path.relative_to(copied).as_posix(): path.read_bytes()
        for root in (copied / "data", copied / "tests/data", copied / "seed")
        for path in root.glob("sales-*.json")
    }

    completed = subprocess.run(
        [str(copied / "seed/generate_sales_data.py")],
        cwd=copied,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert {
        relative: (copied / relative).read_bytes() for relative in expected
    } == expected


def test_python_brief_keeps_sample_output_outside_submission() -> None:
    instruction = (
        SCENARIO_ROOT / "python-sales-by-genre/instruction.md"
    ).read_text(encoding="utf-8")

    assert "--output /tmp/sales-by-genre.csv" in instruction
    assert "--output sales-by-genre.csv" not in instruction


def test_diagnostic_qualification_evidence_covers_all_isolated_cases() -> None:
    assert sorted(path.stem for path in EVIDENCE_ROOT.glob("*.json")) == sorted(PACKAGES)
    for directory in PACKAGES:
        package = SCENARIO_ROOT / directory
        lock = REGISTRY.validate_bytes((package / "scenario.lock.json").read_bytes())
        evidence_path = EVIDENCE_ROOT / f"{directory}.json"
        evidence_bytes = evidence_path.read_bytes()
        technical = REGISTRY.validate_bytes(evidence_bytes)
        runs = technical["runs"]

        assert technical["candidate_status"] == "technically-qualified"
        assert technical["package_payload_sha256"] == lock["package"]["payload_sha256"]
        assert technical["validated_inputs"] == {
            "datasets": lock["resolved_inputs"]["datasets"],
            "images": lock["resolved_inputs"]["images"],
            "instruction_sha256": next(
                item["sha256"] for item in lock["package"]["files"] if item["path"] == "instruction.md"
            ),
            "package_payload_sha256": lock["package"]["payload_sha256"],
            "pristine": lock["resolved_inputs"]["pristine"],
            "scenario_baseline": lock["resolved_inputs"]["scenario_baseline"],
            "seed_inputs": lock["resolved_inputs"]["seed_inputs"],
        }
        assert runs["baseline"]["outcome"] == "declared-failure"
        assert [record["outcome"] for record in runs["reference"]] == ["passed", "passed"]
        assert runs["hidden_marker"]["status"] == "passed"
        assert len(runs["handoffs"]) == 2
        assert runs["score_mismatch"]["status"] == "passed"
        assert runs["no_download"] is True
        environments = {
            runs["baseline"]["environment_id"],
            runs["hidden_marker"]["environment_id"],
            *(record["environment_id"] for record in runs["reference"]),
            *(record["environment_id"] for record in runs["handoffs"]),
            runs["score_mismatch"]["environment_id"],
        }
        assert len(environments) == 7
        assert b"issue40-secret-canary" not in evidence_bytes
        assert b"MODEL_BENCHMARK_PROVIDER_API_KEY" not in evidence_bytes

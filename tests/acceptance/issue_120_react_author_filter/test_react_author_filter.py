from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import yaml

from model_benchmark.declarations.functional_v1 import FunctionalV1Manifest, SCENARIOS
from model_benchmark.declarations.scenario_locks import schema_root_path
from model_benchmark.declarations.schemas import SchemaRegistry


ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "scenarios/calibration/react-author-filter"
EVIDENCE = ROOT / "artifacts/qualification/functional-v1/react-author-filter.json"
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


def test_react_package_is_public_bounded_and_reproducible(tmp_path: Path) -> None:
    manifest = yaml.safe_load((PACKAGE / "scenario.yaml").read_text(encoding="utf-8"))
    assert manifest["scenario"] == {
        "id": "functional-v1/react-author-filter",
        "version": "1.0.0",
        "lifecycle_state": "candidate",
        "visibility": "public",
        "ecosystem": "react-javascript",
        "workload_family": "bounded-feature-implementation",
        "difficulty": "standard",
        "execution_profile": "standard-v1",
    }
    assert manifest["repository"]["pristine"] == {
        **manifest["repository"]["pristine"],
        "origin": "https://github.com/gothinkster/react-redux-realworld-example-app",
        "commit": "ee72eba4056392c95a27bc48d385d3f54ba38a18",
        "license": "MIT",
    }
    assert manifest["repository"]["seed_inputs"] == []
    assert manifest["submission"] == {
        "kind": "git-patch",
        "repository_root": "/workspace/repository",
        "allowed_paths": ["src/reducers/articleList.js"],
        "protected_paths": [".git/**"],
        "allow_additions": False,
        "allow_deletions": False,
        "max_files": 1,
        "max_bytes": 50_000,
        "symlinks": "reject",
        "executable_bits": "reject",
        "submodules": "reject",
        "nested_repositories": "reject",
        "binary_files": "reject",
    }
    assert [
        (group["id"], group["class"], group["required"])
        for group in manifest["verification"]["check_groups"]
    ] == [
        ("author-filter-output", "acceptance", True),
        ("author-filter-state", "domain", True),
        ("reducer-regression", "regression", True),
    ]
    assert any(
        "does not claim byte-identical legacy provenance" in disclosure
        for disclosure in manifest["provenance"]["contamination_disclosures"]
    )

    checked = run_scenario("check", str(PACKAGE))
    assert checked.returncode == 0, checked.stderr or checked.stdout
    assert json.loads(checked.stdout)["lock"] == "valid"

    copied = tmp_path / PACKAGE.name
    shutil.copytree(PACKAGE, copied)
    expected_lock = (copied / "scenario.lock.json").read_bytes()
    relocked = run_scenario("lock", str(copied))
    assert relocked.returncode == 0, relocked.stderr or relocked.stdout
    assert (copied / "scenario.lock.json").read_bytes() == expected_lock


def test_qualification_proves_behavior_and_isolation() -> None:
    manifest = yaml.safe_load((PACKAGE / "scenario.yaml").read_text(encoding="utf-8"))
    lock = REGISTRY.validate_bytes((PACKAGE / "scenario.lock.json").read_bytes())
    evidence_bytes = EVIDENCE.read_bytes()
    technical = REGISTRY.validate_bytes(evidence_bytes)
    runs = technical["runs"]
    declared = manifest["verification"]["qualification"]

    assert technical["candidate_status"] == "technically-qualified"
    assert technical["package_payload_sha256"] == lock["package"]["payload_sha256"]
    assert runs["baseline"]["outcome"] == "declared-failure"
    assert runs["baseline"]["structured_score_vector"] == declared["baseline_score_vector"]
    assert runs["baseline"]["reward_score_vector"] == declared["baseline_score_vector"]
    assert [record["outcome"] for record in runs["reference"]] == ["passed", "passed"]
    for record in runs["reference"]:
        assert record["structured_score_vector"] == declared["reference_score_vector"]
        assert record["reward_score_vector"] == declared["reference_score_vector"]
    assert runs["hidden_marker"]["status"] == "passed"
    assert [record["kind"] for record in runs["handoffs"]] == ["malformed", "unsafe"]
    assert all(record["task_success"] is False for record in runs["handoffs"])
    assert runs["score_mismatch"]["status"] == "passed"
    assert runs["no_download"] is True
    assert b"MODEL_BENCHMARK_HIDDEN" not in evidence_bytes
    assert b"MODEL_BENCHMARK_PROVIDER_API_KEY" not in evidence_bytes


def test_react_package_does_not_activate_existing_functional_v1_runs() -> None:
    assert set(SCENARIOS) == {
        "angular-reading-time",
        "python-sales-by-genre",
        "spring-petvalidator-whitespace",
    }
    manifests = sorted(ROOT.glob("functional-v1*.yaml"))
    assert manifests
    for path in manifests:
        loaded = FunctionalV1Manifest.load(path)
        assert set(loaded.scenario_locks) == set(SCENARIOS)

from __future__ import annotations

import json
import subprocess
import sys
import tomllib  # pyright: ignore[reportMissingImports]
from copy import deepcopy
from pathlib import Path

import pytest

import model_benchmark.evidence.verification as verification_module
from model_benchmark.declarations.canonical import (
    canonical_json_bytes,
    load_canonical_json,
)
from model_benchmark.declarations.identities import (
    DigestKind,
    ScenarioIdentity,
    ScoreContractIdentity,
    TypedDigest,
    VerifierIdentity,
)
from model_benchmark.declarations.schemas import SchemaRegistry, SchemaValidationError
from model_benchmark.evidence.imports import (
    harbor_import_is_allowed,
    import_candidates,
)
from model_benchmark.evidence.verification import (
    VerificationArtifactError,
    VerificationCase,
    VerificationInput,
    verify_checksum_manifest,
    write_verification_artifacts,
)


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_ROOT = ROOT / "schemas"
IDENTITY_FIXTURE = ROOT / "tests/fixtures/conformance/identity-set-v1.valid.json"
CANONICAL_FIXTURE = ROOT / "tests/fixtures/canonical/canonical-v1.expected.json"
HARBOR_COMMIT = "527d50deb63a5d279e8c20593c18a2cbc7f61f9e"


def _object_field(value: dict[str, object], name: str) -> dict[str, object]:
    child = value[name]
    assert isinstance(child, dict)
    return child


def _source_imports(path: Path, source_root: Path) -> set[str]:
    return import_candidates(path, source_root.parent)


def test_frozen_uv_project_has_only_immutable_dependency_sources() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["requires-python"] == "==3.12.*"
    assert (
        "harbor @ git+https://github.com/harbor-framework/harbor.git@" + HARBOR_COMMIT
        in project["project"]["dependencies"]
    )
    assert all(
        "==" in requirement or f"@{HARBOR_COMMIT}" in requirement
        for requirement in (
            project["build-system"]["requires"]
            + project["project"]["dependencies"]
            + project["dependency-groups"]["dev"]
        )
    )

    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    for package in lock["package"]:
        source = package.get("source", {})
        if "registry" in source:
            assert "version" in package
        if "git" in source:
            assert f"?rev={HARBOR_COMMIT}#{HARBOR_COMMIT}" in source["git"]


def test_canonical_fixture_and_typed_identity_vectors_are_reproducible() -> None:
    expected = CANONICAL_FIXTURE.read_bytes()
    value = {"z": [True, None, 3], "a": {"é": "mañana", "a": "first"}}
    assert canonical_json_bytes(value) == expected
    assert canonical_json_bytes(value) == expected
    assert str(TypedDigest.from_bytes(DigestKind.ARTIFACT, expected)) == (
        "artifact:sha256:b3329400b3735375c18fdd24760bf5cf3989a385c21c3a10dd9f28ef17d291f3"
    )

    scenario = ScenarioIdentity.from_payload("1.0.0", value)
    verifier = VerifierIdentity.from_payload("1.0.0", value)
    score_contract = ScoreContractIdentity.from_payload("1.0.0", value)
    assert [identity.digest.kind for identity in (scenario, verifier, score_contract)] == [
        DigestKind.SCENARIO,
        DigestKind.VERIFIER,
        DigestKind.SCORE_CONTRACT,
    ]


def test_schema_loader_fails_closed_for_unknown_fields_enums_digests_and_versions() -> None:
    registry = SchemaRegistry(SCHEMA_ROOT)
    valid = registry.validate_path(IDENTITY_FIXTURE)
    mutations = []
    unknown_field = deepcopy(valid)
    unknown_field["unknown"] = True
    mutations.append(unknown_field)
    unknown_enum = deepcopy(valid)
    identities = _object_field(unknown_enum, "identities")
    scenario = _object_field(identities, "scenario")
    scenario["kind"] = "unknown"
    mutations.append(unknown_enum)
    unknown_digest = deepcopy(valid)
    _object_field(unknown_digest, "schema")["sha256"] = (
        "schema:sha256:" + "0" * 64
    )
    mutations.append(unknown_digest)
    unknown_version = deepcopy(valid)
    _object_field(unknown_version, "schema")["version"] = 2
    mutations.append(unknown_version)
    unknown_canonicalization = deepcopy(valid)
    _object_field(unknown_canonicalization, "schema")[
        "canonicalization_sha256"
    ] = (
        "canonicalization:sha256:" + "0" * 64
    )
    mutations.append(unknown_canonicalization)

    for document in mutations:
        with pytest.raises(SchemaValidationError):
            registry.validate_bytes(canonical_json_bytes(document))


def test_operator_cli_has_human_help_and_canonical_json_without_prompting() -> None:
    executable = Path(sys.executable).with_name("model-benchmark")
    help_result = subprocess.run(
        [executable, "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert help_result.returncode == 0
    assert "usage: model-benchmark" in help_result.stdout
    assert help_result.stderr == ""

    json_result = subprocess.run(
        [executable, "--json"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert json_result.returncode == 2
    summary = json.loads(json_result.stdout)
    assert summary["command"] == "cli"
    assert summary["outcome"] == "rejected"
    assert summary["reason_code"] == "invalid-cli-usage"
    assert json_result.stdout.encode("utf-8") == canonical_json_bytes(summary) + b"\n"
    assert json_result.stderr == ""


def test_dependency_direction_and_harbor_import_guards_cover_the_source_tree(
    tmp_path: Path,
) -> None:
    source_root = ROOT / "src/model_benchmark"
    probe_root = tmp_path / "src/model_benchmark"
    relative_probe = probe_root / "declarations/example.py"
    relative_probe.parent.mkdir(parents=True)
    relative_probe.write_text(
        "from ..runtime import execute\n"
        "from model_benchmark import evidence\n",
        encoding="utf-8",
    )
    assert _source_imports(relative_probe, probe_root) == {
        "model_benchmark.runtime.execute",
        "model_benchmark.evidence",
    }
    forbidden = {
        "declarations": {"analysis", "evidence", "runtime"},
        "runtime": {"analysis", "evidence"},
        "evidence": {"analysis", "runtime"},
        "analysis": set(),
    }
    violations: list[str] = []
    for owner, reverse_dependencies in forbidden.items():
        for path in sorted((source_root / owner).rglob("*.py")):
            for imported in _source_imports(path, source_root):
                for reverse in reverse_dependencies:
                    if imported == f"model_benchmark.{reverse}" or imported.startswith(
                        f"model_benchmark.{reverse}."
                    ):
                        violations.append(f"{path}: reverse import {imported}")
                if imported == "harbor" or imported.startswith("harbor."):
                    adapter_root = source_root / "runtime/adapters"
                    if not harbor_import_is_allowed(path, adapter_root, imported):
                        violations.append(f"{path}: forbidden Harbor import {imported}")
    assert violations == []


def test_verification_writer_is_canonical_reproducible_and_read_back(tmp_path: Path) -> None:
    arguments = {
        "project_root": tmp_path,
        "schema_root": SCHEMA_ROOT,
        "issue": 28,
        "command": "uv run --frozen pytest -q tests/acceptance/issue_28 --maxfail=1",
        "inputs": [
            VerificationInput(
                name="fixture",
                digest=TypedDigest.from_bytes(
                    DigestKind.ARTIFACT,
                    IDENTITY_FIXTURE.read_bytes(),
                ),
            ),
            VerificationInput(
                name="scenario",
                digest=ScenarioIdentity.from_payload(
                    "1.0.0",
                    {"name": "scenario"},
                ).digest,
            ),
        ],
        "cases": [VerificationCase(id="foundation", outcome="passed")],
    }
    first = write_verification_artifacts(**arguments)
    first_bytes = tuple(path.read_bytes() for path in first)
    second = write_verification_artifacts(**arguments)
    assert tuple(path.read_bytes() for path in second) == first_bytes
    verify_checksum_manifest(tmp_path, second[1])
    document = load_canonical_json(second[0].read_bytes())
    assert isinstance(document, dict)
    assert document["issue"] == 28


def test_publication_failure_after_first_write_removes_partial_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_write = verification_module._atomic_verified_write
    calls = 0

    def fail_second_write(path: Path, data: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected manifest write failure")
        real_write(path, data)

    monkeypatch.setattr(
        verification_module,
        "_atomic_verified_write",
        fail_second_write,
    )
    with pytest.raises(VerificationArtifactError):
        write_verification_artifacts(
            project_root=tmp_path,
            schema_root=SCHEMA_ROOT,
            issue=28,
            command=(
                "uv run --frozen pytest -q "
                "tests/acceptance/issue_28 --maxfail=1"
            ),
            inputs=[
                VerificationInput(
                    name="fixture",
                    digest=TypedDigest.from_bytes(DigestKind.ARTIFACT, b"fixture"),
                )
            ],
            cases=[VerificationCase(id="foundation", outcome="passed")],
        )

    artifact_root = tmp_path / "artifacts/acceptance/issue-28"
    assert not (artifact_root / "verification.json").exists()
    assert not (artifact_root / "sha256sums.txt").exists()

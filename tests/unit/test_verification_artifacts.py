from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from model_benchmark.declarations.canonical import canonical_json_bytes, load_canonical_json
from model_benchmark.declarations.identities import (
    DigestKind,
    ScenarioIdentity,
    TypedDigest,
)
from model_benchmark.declarations.schemas import SchemaRegistry
from model_benchmark.evidence.verification import (
    VerificationArtifactError,
    VerificationCase,
    VerificationInput,
    verify_checksum_manifest,
    write_verification_artifacts,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = ROOT / "schemas"


def _inputs() -> list[VerificationInput]:
    return [
        VerificationInput(
            name="uv.lock",
            digest=TypedDigest.from_bytes(DigestKind.UV_LOCK, b"locked\n"),
        ),
        VerificationInput(
            name="source",
            digest=TypedDigest.from_bytes(DigestKind.SOURCE_TREE, b"source\n"),
        ),
        VerificationInput(
            name="scenario",
            digest=ScenarioIdentity.from_payload(
                "1.0.0",
                {"name": "scenario"},
            ).digest,
        ),
    ]


def test_writer_publishes_canonical_artifacts_and_verifies_readback(
    tmp_path: Path,
) -> None:
    first = write_verification_artifacts(
        project_root=tmp_path,
        schema_root=SCHEMA_ROOT,
        issue=28,
        command="uv run --frozen pytest -q tests/acceptance/issue_28 --maxfail=1",
        inputs=_inputs(),
        cases=[
            VerificationCase(id="case-b", outcome="passed"),
            VerificationCase(id="case-a", outcome="passed"),
        ],
    )
    first_bytes = tuple(path.read_bytes() for path in first)

    verification_path, manifest_path = write_verification_artifacts(
        project_root=tmp_path,
        schema_root=SCHEMA_ROOT,
        issue=28,
        command="uv run --frozen pytest -q tests/acceptance/issue_28 --maxfail=1",
        inputs=_inputs(),
        cases=[
            VerificationCase(id="case-a", outcome="passed"),
            VerificationCase(id="case-b", outcome="passed"),
        ],
    )

    assert tuple(
        path.read_bytes() for path in (verification_path, manifest_path)
    ) == first_bytes
    document = SchemaRegistry(SCHEMA_ROOT).validate_path(verification_path)
    case_results = document["case_results"]
    assert isinstance(case_results, list)
    assert all(isinstance(case, dict) for case in case_results)
    assert [case["id"] for case in case_results] == ["case-a", "case-b"]
    assert document["output_paths"] == [
        "artifacts/acceptance/issue-28/sha256sums.txt",
        "artifacts/acceptance/issue-28/verification.json",
    ]
    verify_checksum_manifest(tmp_path, manifest_path)
    expected_digest = hashlib.sha256(verification_path.read_bytes()).hexdigest()
    assert manifest_path.read_text(encoding="utf-8") == (
        f"{expected_digest}  artifacts/acceptance/issue-28/verification.json\n"
    )


def test_writer_removes_stale_authoritative_outputs_on_failure(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts/acceptance/issue-28"
    artifact_root.mkdir(parents=True)
    stale = [artifact_root / "verification.json", artifact_root / "sha256sums.txt"]
    for path in stale:
        path.write_text("stale\n", encoding="utf-8")

    with pytest.raises(VerificationArtifactError):
        write_verification_artifacts(
            project_root=tmp_path,
            schema_root=SCHEMA_ROOT,
            issue=28,
            command="proof",
            inputs=_inputs(),
            cases=[],
        )

    assert all(not path.exists() for path in stale)


def test_checksum_manifest_rejects_tampering(tmp_path: Path) -> None:
    verification_path, manifest_path = write_verification_artifacts(
        project_root=tmp_path,
        schema_root=SCHEMA_ROOT,
        issue=28,
        command="proof",
        inputs=_inputs(),
        cases=[VerificationCase(id="case", outcome="passed")],
    )
    document = load_canonical_json(verification_path.read_bytes())
    assert isinstance(document, dict)
    document["command"] = "tampered"
    verification_path.write_bytes(canonical_json_bytes(document))

    with pytest.raises(VerificationArtifactError):
        verify_checksum_manifest(tmp_path, manifest_path)

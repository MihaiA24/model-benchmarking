from __future__ import annotations

from pathlib import Path

import pytest

from model_benchmark.declarations.canonical import canonical_json_bytes, load_canonical_json
from model_benchmark.evidence.attestation import (
    LiveAttestationError,
    LivePrerequisite,
    seal_live_attestation,
    verify_live_attestation,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = ROOT / "schemas"


def test_live_attestation_is_non_secret_issue_bound_and_content_sealed(
    tmp_path: Path,
) -> None:
    data = seal_live_attestation(
        schema_root=SCHEMA_ROOT,
        issue=44,
        prerequisites=[
            LivePrerequisite(
                name="private-source-access",
                evidence_ref="attestations/private-source-access.json",
            )
        ],
    )
    path = tmp_path / "attestation.json"
    path.write_bytes(data)

    document = verify_live_attestation(
        path=path,
        schema_root=SCHEMA_ROOT,
        issue=44,
    )
    assert document["contains_secrets"] is False
    assert document["issue"] == 44


@pytest.mark.parametrize("tamper", ["issue", "seal", "unknown-field"])
def test_live_attestation_fails_closed_after_tampering(
    tmp_path: Path,
    tamper: str,
) -> None:
    document = load_canonical_json(
        seal_live_attestation(
            schema_root=SCHEMA_ROOT,
            issue=44,
            prerequisites=[
                LivePrerequisite(name="access", evidence_ref="attestations/access.json")
            ],
        )
    )
    assert isinstance(document, dict)
    if tamper == "issue":
        document["issue"] = 45
    elif tamper == "seal":
        document["seal"] = "artifact:sha256:" + "0" * 64
    else:
        document["extra"] = True
    path = tmp_path / "attestation.json"
    path.write_bytes(canonical_json_bytes(document))

    with pytest.raises(LiveAttestationError):
        verify_live_attestation(path=path, schema_root=SCHEMA_ROOT, issue=44)

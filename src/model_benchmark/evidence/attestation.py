from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from model_benchmark.declarations.canonical import canonical_json_bytes
from model_benchmark.declarations.identities import (
    DigestKind,
    IdentityError,
    TypedDigest,
)
from model_benchmark.declarations.schemas import SchemaRegistry, SchemaValidationError


class LiveAttestationError(ValueError):
    """A live prerequisite attestation is missing, secret-bearing, or unsealed."""


@dataclass(frozen=True)
class LivePrerequisite:
    name: str
    evidence_ref: str


def seal_live_attestation(
    *,
    schema_root: Path,
    issue: int,
    prerequisites: list[LivePrerequisite],
) -> bytes:
    """Build a canonical, non-secret, content-sealed live prerequisite attestation."""
    if issue < 1 or not prerequisites:
        raise LiveAttestationError("issue and at least one prerequisite are required")
    names = [item.name for item in prerequisites]
    if len(set(names)) != len(names):
        raise LiveAttestationError("prerequisite names must be unique")
    registry = SchemaRegistry(schema_root)
    entry = next(
        item
        for item in registry.entries
        if item.name == "model-benchmark/live-prerequisite-attestation"
        and item.version == 1
    )
    payload: dict[str, object] = {
        "contains_secrets": False,
        "issue": issue,
        "prerequisites": [
            {
                "evidence_ref": item.evidence_ref,
                "name": item.name,
                "status": "satisfied",
            }
            for item in sorted(prerequisites, key=lambda item: item.name)
        ],
        "schema": {
            "canonicalization_sha256": registry.canonicalization.sha256,
            "canonicalization_version": registry.canonicalization.version,
            "name": entry.name,
            "sha256": entry.sha256,
            "version": entry.version,
        },
    }
    payload["seal"] = str(
        TypedDigest.from_bytes(DigestKind.ARTIFACT, canonical_json_bytes(payload))
    )
    data = canonical_json_bytes(payload)
    try:
        registry.validate_bytes(data)
    except SchemaValidationError as error:
        raise LiveAttestationError(str(error)) from error
    return data


def verify_live_attestation(
    *,
    path: Path,
    schema_root: Path,
    issue: int,
) -> dict[str, object]:
    """Validate the strict schema, issue binding, and content seal."""
    try:
        document = SchemaRegistry(schema_root).validate_path(path)
    except SchemaValidationError as error:
        raise LiveAttestationError(str(error)) from error
    if document["issue"] != issue:
        raise LiveAttestationError("attestation is bound to a different issue")
    seal = document["seal"]
    if not isinstance(seal, str):
        raise LiveAttestationError("attestation seal is malformed")
    try:
        parsed_seal = TypedDigest.parse(seal)
    except IdentityError as error:
        raise LiveAttestationError(str(error)) from error
    if parsed_seal.kind is not DigestKind.ARTIFACT:
        raise LiveAttestationError("attestation seal must be an artifact digest")
    preimage = dict(document)
    del preimage["seal"]
    expected = TypedDigest.from_bytes(
        DigestKind.ARTIFACT,
        canonical_json_bytes(preimage),
    )
    if parsed_seal != expected:
        raise LiveAttestationError("attestation content seal does not match")
    return document

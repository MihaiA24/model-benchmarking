from __future__ import annotations

import base64
import hashlib
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from model_benchmark.declarations.canonical import canonical_json_bytes
from model_benchmark.declarations.identities import DigestKind, TypedDigest
from model_benchmark.declarations.scenario_locks import (
    HARBOR_COMMIT,
    schema_root_path,
)
from model_benchmark.declarations.schemas import SchemaRegistry, SchemaValidationError
from model_benchmark.declarations.scenarios import (
    ScenarioPackageError,
    _immutable_verified_write,
    _load_manifest,
    check_scenario_package,
)


TECHNICAL_SCHEMA_NAME = "model-benchmark/scenario-technical-qualification"
REVIEW_SCHEMA_NAME = "model-benchmark/scenario-review"
PQR_SCHEMA_NAME = "model-benchmark/package-qualification-record"
_SCHEMA_VERSION = 1
_ALLOWED_TRANSITIONS = {
    "authoring_target": {"candidate"},
    "private_slot": {"candidate"},
    "candidate": {"package_qualified", "rejected"},
    "package_qualified": {"roster_selected"},
    "roster_selected": {"suite_sealed"},
    "suite_sealed": set(),
    "rejected": set(),
}


def review_signing_bytes(review: dict[str, object]) -> bytes:
    """Return the canonical review preimage signed by its Ed25519 reviewer."""
    unsigned = deepcopy(review)
    reviewer = unsigned.get("reviewer")
    if not isinstance(reviewer, dict):
        raise ScenarioPackageError("unsigned-independent-review", "reviewer is missing")
    authentication = reviewer.get("authentication")
    if not isinstance(authentication, dict):
        raise ScenarioPackageError(
            "unsigned-independent-review",
            "review authentication is missing",
        )
    value = authentication.get("value")
    if not isinstance(value, str):
        raise ScenarioPackageError(
            "unsigned-independent-review",
            "review signature is missing",
        )
    parts = value.split(":")
    if len(parts) != 3 or parts[0] != "ed25519" or not parts[1]:
        raise ScenarioPackageError(
            "unsigned-independent-review",
            "review signature encoding is malformed",
        )
    authentication["value"] = f"ed25519:{parts[1]}:"
    return canonical_json_bytes(unsigned)


def technical_signing_bytes(technical: dict[str, object]) -> bytes:
    """Return the canonical technical-evidence preimage signed by its worker."""
    unsigned = deepcopy(technical)
    worker = unsigned.get("worker")
    if not isinstance(worker, dict):
        raise ScenarioPackageError("unsigned-technical-qualification", "worker is missing")
    authentication = worker.get("authentication")
    if not isinstance(authentication, dict):
        raise ScenarioPackageError(
            "unsigned-technical-qualification",
            "worker authentication is missing",
        )
    value = authentication.get("value")
    if not isinstance(value, str):
        raise ScenarioPackageError(
            "unsigned-technical-qualification",
            "worker signature is missing",
        )
    parts = value.split(":")
    if len(parts) != 3 or parts[0] != "ed25519" or not parts[1]:
        raise ScenarioPackageError(
            "unsigned-technical-qualification",
            "worker signature encoding is malformed",
        )
    authentication["value"] = f"ed25519:{parts[1]}:"
    return canonical_json_bytes(unsigned)


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ScenarioPackageError("invalid-qualification-order", f"{label} is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ScenarioPackageError(
            "invalid-qualification-order",
            f"{label} is not an RFC 3339 timestamp",
        ) from error
    if parsed.tzinfo is None:
        raise ScenarioPackageError(
            "invalid-qualification-order",
            f"{label} must include an offset",
        )
    return parsed


def validate_scenario_state_transition(current: str, requested: str) -> None:
    allowed = _ALLOWED_TRANSITIONS.get(current)
    if allowed is None or requested not in allowed:
        raise ScenarioPackageError(
            "invalid-scenario-state-transition",
            f"Scenario state cannot move from {current!r} to {requested!r}",
        )


def _load_document(
    path: Path,
    *,
    registry: SchemaRegistry,
    name: str,
    classification: str,
) -> tuple[dict[str, object], bytes]:
    if path.is_symlink() or not path.is_file():
        raise ScenarioPackageError(classification, f"document not found: {path}")
    try:
        data = path.read_bytes()
        value = registry.validate_bytes(data)
    except (OSError, SchemaValidationError) as error:
        raise ScenarioPackageError(classification, str(error)) from error
    envelope = value["schema"]
    if not isinstance(envelope, dict) or envelope.get("name") != name:
        raise ScenarioPackageError(classification, f"expected {name} document")
    if canonical_json_bytes(value) != data:
        raise ScenarioPackageError(
            classification,
            f"{name} document must use canonical JSON bytes",
        )
    return value, data


def _expected_validated_inputs(lock: dict[str, object]) -> dict[str, object]:
    package = lock["package"]
    resolved = lock["resolved_inputs"]
    assert isinstance(package, dict)
    assert isinstance(resolved, dict)
    files = package["files"]
    assert isinstance(files, list)
    instruction = next(
        (
            entry["sha256"]
            for entry in files
            if isinstance(entry, dict) and entry.get("path") == "instruction.md"
        ),
        None,
    )
    if not isinstance(instruction, str):
        raise ScenarioPackageError(
            "invalid-package-lock",
            "package lock has no Developer Brief identity",
        )
    return {
        "datasets": resolved["datasets"],
        "images": resolved["images"],
        "instruction_sha256": instruction,
        "package_payload_sha256": package["payload_sha256"],
        "pristine": resolved["pristine"],
        "scenario_baseline": resolved["scenario_baseline"],
        "seed_inputs": resolved["seed_inputs"],
    }


def _vector(record: dict[str, object], field: str) -> list[dict[str, str]]:
    raw = record[field]
    if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
        raise ScenarioPackageError(
            "invalid-technical-qualification",
            f"invalid {field}",
        )
    vector = [{str(key): str(value) for key, value in item.items()} for item in raw]
    names = [item["name"] for item in vector]
    if names != sorted(names) or len(names) != len(set(names)):
        raise ScenarioPackageError(
            "invalid-technical-qualification",
            f"{field} must be sorted and unique",
        )
    return vector


def _validate_run(
    record: dict[str, object],
    *,
    expected_outcome: str,
    expected_vector: list[dict[str, str]],
) -> str:
    if record["outcome"] != expected_outcome:
        raise ScenarioPackageError(
            "invalid-technical-qualification",
            f"expected {expected_outcome} qualification outcome",
        )
    structured = _vector(record, "structured_score_vector")
    reward = _vector(record, "reward_score_vector")
    if structured != reward:
        raise ScenarioPackageError(
            "invalid-infrastructure",
            "structured verifier result disagrees with Harbor reward projection",
        )
    if structured != expected_vector:
        raise ScenarioPackageError(
            "invalid-technical-qualification",
            "qualification score vector differs from the declared vector",
        )
    environment_id = record["environment_id"]
    if not isinstance(environment_id, str):
        raise ScenarioPackageError(
            "invalid-technical-qualification",
            "fresh environment identity is missing",
        )
    return environment_id


def _validate_worker_signature(technical: dict[str, object]) -> None:
    worker = technical["worker"]
    assert isinstance(worker, dict)
    identity = worker["identity"]
    authentication = worker["authentication"]
    assert isinstance(identity, str)
    assert isinstance(authentication, dict)
    value = authentication["value"]
    assert isinstance(value, str)
    try:
        algorithm, encoded_key, encoded_signature = value.split(":")
        if algorithm != "ed25519":
            raise ValueError("unsupported signature algorithm")
        public_key = _base64url_decode(encoded_key)
        signature = _base64url_decode(encoded_signature)
        expected_identity = "ed25519:sha256:" + hashlib.sha256(public_key).hexdigest()
        if identity != expected_identity:
            raise ValueError("worker identity does not match the signing key")
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            signature,
            technical_signing_bytes(technical),
        )
    except (InvalidSignature, ValueError, TypeError) as error:
        raise ScenarioPackageError(
            "unsigned-technical-qualification",
            "technical qualification signature is invalid",
        ) from error


def _validate_technical_evidence(
    technical: dict[str, object],
    *,
    lock: dict[str, object],
    manifest: dict[str, Any],
    trusted_worker_identity: str,
) -> None:
    _validate_worker_signature(technical)
    worker = technical["worker"]
    assert isinstance(worker, dict)
    if worker["identity"] != trusted_worker_identity:
        raise ScenarioPackageError(
            "untrusted-technical-worker",
            "technical qualification was not signed by the trusted worker",
        )
    for field in ("identities", "harbor", "standard_v1"):
        if technical[field] != lock[field]:
            raise ScenarioPackageError(
                "stale-technical-qualification",
                f"technical qualification {field} does not match the package lock",
            )
    package = lock["package"]
    assert isinstance(package, dict)
    if technical["package_payload_sha256"] != package["payload_sha256"]:
        raise ScenarioPackageError(
            "stale-technical-qualification",
            "technical qualification covers a different package payload",
        )
    if technical["validated_inputs"] != _expected_validated_inputs(lock):
        raise ScenarioPackageError(
            "invalid-technical-qualification",
            "technical qualification did not validate every locked input",
        )
    runs = technical["runs"]
    assert isinstance(runs, dict)
    baseline = runs["baseline"]
    reference = runs["reference"]
    hidden_marker = runs["hidden_marker"]
    handoffs = runs["handoffs"]
    score_mismatch = runs["score_mismatch"]
    assert isinstance(baseline, dict)
    assert isinstance(reference, list)
    assert isinstance(hidden_marker, dict)
    assert isinstance(handoffs, list)
    assert isinstance(score_mismatch, dict)
    declared = manifest["verification"]["qualification"]
    baseline_vector = declared["baseline_score_vector"]
    reference_vector = declared["reference_score_vector"]
    environment_ids = {
        _validate_run(
            baseline,
            expected_outcome="declared-failure",
            expected_vector=baseline_vector,
        )
    }
    for run in reference:
        assert isinstance(run, dict)
        environment_ids.add(
            _validate_run(
                run,
                expected_outcome="passed",
                expected_vector=reference_vector,
            )
        )
    hidden_environment = hidden_marker["environment_id"]
    environment_ids.add(str(hidden_environment))
    handoff_map = {
        entry["kind"]: (entry["classification"], entry["task_success"])
        for entry in handoffs
        if isinstance(entry, dict)
    }
    if handoff_map != {
        "malformed": ("valid_harness_outcome", False),
        "unsafe": ("valid_harness_outcome", False),
    }:
        raise ScenarioPackageError(
            "invalid-technical-qualification",
            "malformed and unsafe handoffs were not classified fail-closed",
        )
    environment_ids.update(str(entry["environment_id"]) for entry in handoffs)
    environment_ids.add(str(score_mismatch["environment_id"]))
    if len(environment_ids) != 7 or score_mismatch["status"] != "passed":
        raise ScenarioPackageError(
            "invalid-technical-qualification",
            "all qualification gates require seven fresh Harbor environments",
        )


def _validate_review(
    review: dict[str, object],
    *,
    review_data: bytes,
    lock: dict[str, object],
    lock_data: bytes,
    manifest: dict[str, Any],
    trusted_reviewer_identity: str,
) -> str:
    expected_lock = str(TypedDigest.from_bytes(DigestKind.PACKAGE_LOCK, lock_data))
    package = lock["package"]
    assert isinstance(package, dict)
    comparisons = {
        "identities": lock["identities"],
        "package_lock_sha256": expected_lock,
        "package_payload_sha256": package["payload_sha256"],
    }
    for field, expected in comparisons.items():
        if review[field] != expected:
            raise ScenarioPackageError(
                "stale-independent-review",
                f"independent review {field} does not match the exact package lock",
            )
    if review["judgment"] != "approve":
        raise ScenarioPackageError(
            "independent-review-rejected",
            "independent review did not approve the package",
        )
    reviewer = review["reviewer"]
    assert isinstance(reviewer, dict)
    identity = reviewer["identity"]
    if identity != trusted_reviewer_identity:
        raise ScenarioPackageError(
            "untrusted-independent-reviewer",
            "independent review was not signed by the designated reviewer",
        )
    if identity in manifest["provenance"]["authors"]:
        raise ScenarioPackageError(
            "non-independent-review",
            "package author cannot approve the independent review",
        )
    authentication = reviewer["authentication"]
    assert isinstance(authentication, dict)
    value = authentication["value"]
    assert isinstance(value, str)
    try:
        algorithm, encoded_key, encoded_signature = value.split(":")
        if algorithm != "ed25519":
            raise ValueError("unsupported signature algorithm")
        public_key = _base64url_decode(encoded_key)
        signature = _base64url_decode(encoded_signature)
        expected_identity = "ed25519:sha256:" + hashlib.sha256(public_key).hexdigest()
        if identity != expected_identity:
            raise ValueError("reviewer identity does not match the signing key")
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            signature,
            review_signing_bytes(review),
        )
    except (InvalidSignature, ValueError, TypeError) as error:
        raise ScenarioPackageError(
            "unsigned-independent-review",
            "independent review signature is invalid",
        ) from error
    return str(TypedDigest.from_bytes(DigestKind.SCENARIO_REVIEW, review_data))


def qualify_scenario_package(
    package_path: Path,
    *,
    technical_evidence: Path,
    review: Path,
    output: Path,
    trusted_worker_identity: str,
    trusted_reviewer_identity: str,
) -> dict[str, object]:
    """Seal a Suite-owned Package Qualification Record after exact review."""
    output = output.resolve()
    package_path = package_path.resolve()
    technical_evidence = technical_evidence.resolve()
    review = review.resolve()
    if output.is_relative_to(package_path):
        raise ScenarioPackageError(
            "invalid-qualification-output",
            "Package Qualification Record must remain outside the package payload",
        )
    if output in {technical_evidence, review}:
        raise ScenarioPackageError(
            "invalid-qualification-output",
            "Package Qualification Record cannot overwrite qualification inputs",
        )
    try:
        check = check_scenario_package(package_path)
        if check["lock"] != "valid":
            raise ScenarioPackageError(
                "missing-package-lock",
                "technical qualification must be followed by an exact package lock",
            )
        registry = SchemaRegistry(schema_root_path())
        lock_path = package_path / "scenario.lock.json"
        lock_data = lock_path.read_bytes()
        lock = registry.validate_bytes(lock_data)
        manifest = _load_manifest(package_path)
        technical, technical_data = _load_document(
            technical_evidence,
            registry=registry,
            name=TECHNICAL_SCHEMA_NAME,
            classification="invalid-technical-qualification",
        )
        review_value, review_data = _load_document(
            review,
            registry=registry,
            name=REVIEW_SCHEMA_NAME,
            classification="invalid-independent-review",
        )
        _validate_technical_evidence(
            technical,
            lock=lock,
            manifest=manifest,
            trusted_worker_identity=trusted_worker_identity,
        )
        if _timestamp(review_value["reviewed_at"], "reviewed_at") < _timestamp(
            technical["qualified_at"],
            "qualified_at",
        ):
            raise ScenarioPackageError(
                "invalid-qualification-order",
                "independent review predates technical qualification",
            )
        review_digest = _validate_review(
            review_value,
            review_data=review_data,
            lock=lock,
            lock_data=lock_data,
            manifest=manifest,
            trusted_reviewer_identity=trusted_reviewer_identity,
        )
        validate_scenario_state_transition("candidate", "package_qualified")
        package = lock["package"]
        assert isinstance(package, dict)
        pqr: dict[str, object] = {
            "harbor": lock["harbor"],
            "identities": lock["identities"],
            "lifecycle": {"from": "candidate", "to": "package_qualified"},
            "package_lock_sha256": str(
                TypedDigest.from_bytes(DigestKind.PACKAGE_LOCK, lock_data)
            ),
            "package_payload_sha256": package["payload_sha256"],
            "qualification": {
                "automated_evidence_sha256": str(
                    TypedDigest.from_bytes(
                        DigestKind.PACKAGE_QUALIFICATION,
                        technical_data,
                    )
                ),
                "independent_review_sha256": review_digest,
                "status": "approved",
                "worker_identity": trusted_worker_identity,
            },
            "reviewed_at": review_value["reviewed_at"],
            "scenario_id": lock["scenario_id"],
            "schema": registry.envelope(PQR_SCHEMA_NAME, _SCHEMA_VERSION),
            "standard_v1": lock["standard_v1"],
            "state": "package_qualified",
            "technical_qualified_at": technical["qualified_at"],
        }
        registry.validate_value(pqr, name=PQR_SCHEMA_NAME, version=_SCHEMA_VERSION)
        data = canonical_json_bytes(pqr)
        _immutable_verified_write(output, data)
    except ScenarioPackageError:
        raise
    except (OSError, SchemaValidationError) as error:
        raise ScenarioPackageError("qualification-publication-failed", str(error)) from error
    digest = str(TypedDigest.from_bytes(DigestKind.PACKAGE_QUALIFICATION, data))
    return {
        "message": f"Package Qualification Record sealed: {lock['scenario_id']}",
        "package_qualification_sha256": digest,
        "path": str(output),
        "scenario_id": lock["scenario_id"],
        "status": "package_qualified",
    }

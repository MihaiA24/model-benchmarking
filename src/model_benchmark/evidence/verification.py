from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

from model_benchmark.declarations.canonical import canonical_json_bytes
from model_benchmark.declarations.identities import TypedDigest
from model_benchmark.declarations.schemas import SchemaRegistry, SchemaValidationError


class VerificationArtifactError(RuntimeError):
    """Canonical verification artifacts could not be safely published."""


@dataclass(frozen=True)
class VerificationInput:
    name: str
    digest: TypedDigest


@dataclass(frozen=True)
class VerificationCase:
    id: str
    outcome: str


_CHECKSUM_LINE = re.compile(r"^([0-9a-f]{64})  (.+)$")


def _remove_outputs(paths: tuple[Path, Path]) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


def _atomic_verified_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
        if path.read_bytes() != data:
            raise VerificationArtifactError(f"read-back mismatch for {path}")
    finally:
        temporary.unlink(missing_ok=True)


def write_verification_artifacts(
    *,
    project_root: Path,
    schema_root: Path,
    issue: int,
    command: str,
    inputs: list[VerificationInput],
    cases: list[VerificationCase],
) -> tuple[Path, Path]:
    """Write and immediately verify canonical issue acceptance artifacts."""
    artifact_root = project_root / f"artifacts/acceptance/issue-{issue}"
    verification_path = artifact_root / "verification.json"
    manifest_path = artifact_root / "sha256sums.txt"
    outputs = (verification_path, manifest_path)
    _remove_outputs(outputs)
    try:
        if issue < 1 or not command:
            raise VerificationArtifactError("issue and command are required")
        input_names = [item.name for item in inputs]
        case_ids = [item.id for item in cases]
        if len(set(input_names)) != len(input_names):
            raise VerificationArtifactError("verification input names must be unique")
        if len(set(case_ids)) != len(case_ids):
            raise VerificationArtifactError("verification case IDs must be unique")

        registry = SchemaRegistry(schema_root)
        entry = next(
            item
            for item in registry.entries
            if item.name == "model-benchmark/verification-artifact"
            and item.version == 1
        )
        relative_verification = verification_path.relative_to(project_root).as_posix()
        relative_manifest = manifest_path.relative_to(project_root).as_posix()
        payload = {
            "case_results": [
                {"id": item.id, "outcome": item.outcome}
                for item in sorted(cases, key=lambda item: item.id)
            ],
            "command": command,
            "input_identities": [
                {"digest": str(item.digest), "name": item.name}
                for item in sorted(inputs, key=lambda item: item.name)
            ],
            "issue": issue,
            "output_paths": sorted([relative_manifest, relative_verification]),
            "schema": {
                "canonicalization_sha256": registry.canonicalization.sha256,
                "canonicalization_version": registry.canonicalization.version,
                "name": entry.name,
                "sha256": entry.sha256,
                "version": entry.version,
            },
        }
        verification_bytes = canonical_json_bytes(payload)
        registry.validate_bytes(verification_bytes)
        _atomic_verified_write(verification_path, verification_bytes)
        checksum = hashlib.sha256(verification_bytes).hexdigest()
        checksum_bytes = f"{checksum}  {relative_verification}\n".encode("utf-8")
        _atomic_verified_write(manifest_path, checksum_bytes)
        registry.validate_path(verification_path)
        verify_checksum_manifest(project_root, manifest_path)
        return outputs
    except (VerificationArtifactError, SchemaValidationError) as error:
        _remove_outputs(outputs)
        if isinstance(error, VerificationArtifactError):
            raise
        raise VerificationArtifactError(str(error)) from error
    except BaseException as error:
        _remove_outputs(outputs)
        raise VerificationArtifactError(str(error)) from error


def verify_checksum_manifest(project_root: Path, manifest: Path) -> None:
    """Verify every relative path and SHA-256 entry in a checksum manifest."""
    try:
        lines = manifest.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise VerificationArtifactError(f"cannot read checksum manifest: {manifest}") from error
    if not lines:
        raise VerificationArtifactError("checksum manifest is empty")
    root = project_root.resolve()
    seen: set[str] = set()
    for line in lines:
        match = _CHECKSUM_LINE.fullmatch(line)
        if match is None:
            raise VerificationArtifactError("malformed checksum manifest line")
        expected, relative = match.groups()
        relative_path = Path(relative)
        resolved = (root / relative_path).resolve()
        if (
            relative in seen
            or relative_path.is_absolute()
            or ".." in relative_path.parts
            or not resolved.is_relative_to(root)
        ):
            raise VerificationArtifactError("unsafe or duplicate checksum path")
        seen.add(relative)
        try:
            actual = hashlib.sha256(resolved.read_bytes()).hexdigest()
        except OSError as error:
            raise VerificationArtifactError(f"cannot read checksummed path: {relative}") from error
        if actual != expected:
            raise VerificationArtifactError(f"checksum mismatch for {relative}")

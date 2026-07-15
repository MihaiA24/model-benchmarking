from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum

from model_benchmark.declarations.canonical import canonical_json_bytes


class IdentityError(ValueError):
    """A typed identity is malformed or semantically mismatched."""


class DigestKind(str, Enum):
    SCENARIO = "scenario"
    VERIFIER = "verifier"
    SCORE_CONTRACT = "score-contract"
    CANONICALIZATION = "canonicalization"
    SCHEMA = "schema"
    ARTIFACT = "artifact"
    UV_LOCK = "uv-lock"
    SOURCE_TREE = "source-tree"
    PACKAGE_PAYLOAD = "package-payload"
    PACKAGE_LOCK = "package-lock"
    EXECUTION_PROFILE = "execution-profile"
    HARBOR_TASK = "harbor-task"
    OCI_IMAGE = "oci-image"
    PROVISIONING_MANIFEST = "provisioning-manifest"
    SCENARIO_REVIEW = "scenario-review"
    PACKAGE_QUALIFICATION = "package-qualification"


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


def _validate_version(version: str) -> None:
    if _SEMVER_PATTERN.fullmatch(version) is None:
        raise IdentityError(f"version is not strict SemVer: {version}")


@dataclass(frozen=True)
class TypedDigest:
    kind: DigestKind
    value: str
    algorithm: str = "sha256"

    def __post_init__(self) -> None:
        if not isinstance(self.kind, DigestKind):
            raise IdentityError(f"unknown digest kind: {self.kind}")
        if self.algorithm != "sha256":
            raise IdentityError(f"unsupported digest algorithm: {self.algorithm}")
        if _SHA256_PATTERN.fullmatch(self.value) is None:
            raise IdentityError("SHA-256 must be 64 lowercase hexadecimal characters")

    def __str__(self) -> str:
        return f"{self.kind.value}:{self.algorithm}:{self.value}"

    @classmethod
    def from_bytes(cls, kind: DigestKind, data: bytes) -> "TypedDigest":
        return cls(kind=kind, value=hashlib.sha256(data).hexdigest())

    @classmethod
    def parse(cls, value: str) -> "TypedDigest":
        parts = value.split(":")
        if len(parts) != 3:
            raise IdentityError("typed digest must contain kind, algorithm, and value")
        kind_value, algorithm, digest_value = parts
        try:
            kind = DigestKind(kind_value)
        except ValueError as error:
            raise IdentityError(f"unknown digest kind: {kind_value}") from error
        return cls(kind=kind, algorithm=algorithm, value=digest_value)


@dataclass(frozen=True)
class ScenarioIdentity:
    version: str
    digest: TypedDigest

    def __post_init__(self) -> None:
        _validate_version(self.version)
        if self.digest.kind is not DigestKind.SCENARIO:
            raise IdentityError("ScenarioIdentity requires a scenario digest")

    @classmethod
    def from_payload(cls, version: str, payload: object) -> "ScenarioIdentity":
        _validate_version(version)
        return cls(
            version=version,
            digest=TypedDigest.from_bytes(
                DigestKind.SCENARIO, canonical_json_bytes(payload)
            ),
        )


@dataclass(frozen=True)
class VerifierIdentity:
    version: str
    digest: TypedDigest

    def __post_init__(self) -> None:
        _validate_version(self.version)
        if self.digest.kind is not DigestKind.VERIFIER:
            raise IdentityError("VerifierIdentity requires a verifier digest")

    @classmethod
    def from_payload(cls, version: str, payload: object) -> "VerifierIdentity":
        _validate_version(version)
        return cls(
            version=version,
            digest=TypedDigest.from_bytes(
                DigestKind.VERIFIER, canonical_json_bytes(payload)
            ),
        )


@dataclass(frozen=True)
class ScoreContractIdentity:
    version: str
    digest: TypedDigest

    def __post_init__(self) -> None:
        _validate_version(self.version)
        if self.digest.kind is not DigestKind.SCORE_CONTRACT:
            raise IdentityError(
                "ScoreContractIdentity requires a score-contract digest"
            )

    @classmethod
    def from_payload(cls, version: str, payload: object) -> "ScoreContractIdentity":
        _validate_version(version)
        return cls(
            version=version,
            digest=TypedDigest.from_bytes(
                DigestKind.SCORE_CONTRACT, canonical_json_bytes(payload)
            ),
        )

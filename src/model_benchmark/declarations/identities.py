from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar, Self

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
    FUNCTIONAL_V1_MANIFEST = "functional-v1-manifest"
    RESOLVED_V1_MANIFEST = "resolved-v1-manifest"
    FUNCTIONAL_V1_CONDITION = "functional-v1-condition"
    PRICING_RECORD = "pricing-record"
    RESULT_BUNDLE = "result-bundle"
    FUNCTIONAL_V1_RUN_RECORD = "functional-v1-run-record"


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
class _VersionedIdentity:
    version: str
    digest: TypedDigest

    _KIND: ClassVar[DigestKind]

    def __post_init__(self) -> None:
        _validate_version(self.version)
        if self.digest.kind is not self._KIND:
            raise IdentityError(
                f"{type(self).__name__} requires a {self._KIND.value} digest"
            )

    @classmethod
    def from_payload(cls, version: str, payload: object) -> Self:
        _validate_version(version)
        return cls(
            version=version,
            digest=TypedDigest.from_bytes(cls._KIND, canonical_json_bytes(payload)),
        )


class ScenarioIdentity(_VersionedIdentity):
    _KIND = DigestKind.SCENARIO


class VerifierIdentity(_VersionedIdentity):
    _KIND = DigestKind.VERIFIER


class ScoreContractIdentity(_VersionedIdentity):
    _KIND = DigestKind.SCORE_CONTRACT

from __future__ import annotations

import hashlib
import json
import os
import stat
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping
from urllib.parse import urlsplit

from model_benchmark.declarations.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    load_canonical_json,
)
from model_benchmark.declarations.identities import DigestKind, TypedDigest
from model_benchmark.declarations.scenario_locks import (
    project_resource_root,
    standard_profile_path,
)
from model_benchmark.runtime.conditions import (
    ConditionProcessResult,
    SealedConditionProcess,
)
from model_benchmark.runtime.credential_proxy import TRIAL_PROXY_TOKEN_ENV


OMP_VERSION = "v16.4.0"
OMP_ARTIFACT_URL = (
    "https://github.com/can1357/oh-my-pi/releases/download/"
    "v16.4.0/omp-linux-x64"
)
OMP_ARTIFACT_IDENTITY = (
    "artifact:sha256:c7a2fa328c965131c0d0ef62a07a4fe63306ed1b7a90fbbb924c75605c68d38a"
)
OMP_ARTIFACT_BYTES = 171_952_256
OMP_SHIM_IDENTITY = (
    "artifact:sha256:3fa359ee22bb709a545a3dfed099d95f5567e189e13786bc00e415f387206271"
)
OMP_ENVIRONMENT_NAMES = (
    "MODEL_BENCHMARK_PROVIDER_MODEL",
    "MODEL_BENCHMARK_PROXY_BASE_URL",
    TRIAL_PROXY_TOKEN_ENV,
)
_QUALIFIED = "qualified"


class OmpConditionError(RuntimeError):
    """The pinned OMP condition cannot be provisioned or qualified safely."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class OmpProvisioning:
    condition_identity: str
    artifact_path: Path
    artifact_identity: str
    launch_shim_path: Path
    launch_shim_identity: str
    manifest_path: Path


@dataclass(frozen=True)
class OmpQualification:
    qualified: bool
    reason_code: str
    evidence: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", MappingProxyType(dict(self.evidence)))


def omp_condition_lock_path() -> Path:
    path = (
        project_resource_root("profiles", "published_profiles")
        / "functional-v1"
        / "omp-v16.4.0.condition.json"
    )
    if not path.is_file():
        raise OmpConditionError("condition-lock-unavailable", "OMP condition lock is unavailable")
    return path


def omp_launch_shim_path() -> Path:
    path = Path(__file__).with_name("omp_launch.py")
    if not path.is_file():
        raise OmpConditionError("launch-shim-unavailable", "OMP launch shim is unavailable")
    return path


def load_omp_condition_lock() -> tuple[bytes, Mapping[str, object], TypedDigest]:
    try:
        data = omp_condition_lock_path().read_bytes()
        value = load_canonical_json(data)
    except (OSError, CanonicalizationError) as error:
        raise OmpConditionError("invalid-condition-lock", str(error)) from error
    if not isinstance(value, dict):
        raise OmpConditionError("invalid-condition-lock", "OMP condition lock is not an object")
    _verify_lock_dependencies(value)
    identity = TypedDigest.from_bytes(DigestKind.FUNCTIONAL_V1_CONDITION, data)
    return data, MappingProxyType(value), identity


def validate_omp_condition_lock(data: bytes) -> TypedDigest:
    expected, _, identity = load_omp_condition_lock()
    if data != expected:
        raise OmpConditionError(
            "condition-unqualified",
            "OMP condition lock differs from the qualified v16.4.0 lock",
        )
    return identity


def _verify_lock_dependencies(lock: dict[str, object]) -> None:
    artifact = lock.get("artifact")
    adapter = lock.get("adapter")
    if not isinstance(artifact, dict) or not isinstance(adapter, dict):
        raise OmpConditionError("invalid-condition-lock", "OMP lock structure is invalid")
    configuration = adapter.get("configuration")
    if not isinstance(configuration, dict):
        raise OmpConditionError("invalid-condition-lock", "OMP adapter configuration is invalid")
    shim = configuration.get("launch_shim")
    if not isinstance(shim, dict):
        raise OmpConditionError("invalid-condition-lock", "OMP launch shim declaration is invalid")
    expected_profile = TypedDigest.from_bytes(
        DigestKind.EXECUTION_PROFILE,
        standard_profile_path().read_bytes(),
    )
    expected_shim = TypedDigest.from_bytes(
        DigestKind.ARTIFACT,
        omp_launch_shim_path().read_bytes(),
    )
    if (
        lock.get("schema_version") != 1
        or lock.get("condition") != "omp"
        or lock.get("execution_profile") != str(expected_profile)
        or artifact
        != {
            "digest": OMP_ARTIFACT_IDENTITY,
            "kind": "native-executable",
            "platform": "linux/amd64",
        }
        or configuration.get("artifact_bytes") != OMP_ARTIFACT_BYTES
        or configuration.get("artifact_source") != OMP_ARTIFACT_URL
        or configuration.get("artifact_version") != OMP_VERSION
        or shim.get("digest") != OMP_SHIM_IDENTITY
        or str(expected_shim) != OMP_SHIM_IDENTITY
        or adapter.get("environment_names") != list(OMP_ENVIRONMENT_NAMES)
        or adapter.get("non_interactive") is not True
        or adapter.get("self_update") is not False
        or adapter.get("working_directory") != "/workspace"
    ):
        raise OmpConditionError(
            "invalid-condition-lock",
            "OMP v16.4.0 artifact, profile, or adapter declaration does not match",
        )


def provision_omp(cache_root: Path, condition_lock: bytes) -> OmpProvisioning:
    condition_identity = validate_omp_condition_lock(condition_lock)
    root = cache_root / "omp" / condition_identity.value
    manifest_path = root / "provisioning.json"
    if manifest_path.exists() or manifest_path.is_symlink():
        return preflight_omp(cache_root, condition_lock)

    artifact_relative = (
        Path("artifacts") / OMP_ARTIFACT_IDENTITY.rsplit(":", 1)[1] / "omp"
    )
    shim_relative = Path("adapters") / OMP_SHIM_IDENTITY.rsplit(":", 1)[1] / "omp-launch"
    artifact_path = cache_root / artifact_relative
    shim_path = cache_root / shim_relative
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    artifact_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    shim_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if artifact_path.exists() or artifact_path.is_symlink():
        _verify_executable(artifact_path, OMP_ARTIFACT_IDENTITY, OMP_ARTIFACT_BYTES)
    else:
        _download_artifact(artifact_path)
    shim_data = omp_launch_shim_path().read_bytes()
    if shim_path.exists() or shim_path.is_symlink():
        _verify_executable(shim_path, OMP_SHIM_IDENTITY, len(shim_data))
    else:
        _publish_bytes(shim_path, shim_data, mode=0o555)
        _verify_executable(shim_path, OMP_SHIM_IDENTITY, len(shim_data))

    manifest = {
        "artifact": {
            "bytes": OMP_ARTIFACT_BYTES,
            "identity": OMP_ARTIFACT_IDENTITY,
            "path": artifact_relative.as_posix(),
            "source": OMP_ARTIFACT_URL,
            "version": OMP_VERSION,
        },
        "condition_identity": str(condition_identity),
        "launch_shim": {
            "bytes": len(shim_data),
            "identity": OMP_SHIM_IDENTITY,
            "path": shim_relative.as_posix(),
        },
        "network": "provision-only",
        "schema_version": 1,
    }
    _publish_bytes(manifest_path, canonical_json_bytes(manifest), mode=0o400)
    return preflight_omp(cache_root, condition_lock)


def preflight_omp(cache_root: Path, condition_lock: bytes) -> OmpProvisioning:
    condition_identity = validate_omp_condition_lock(condition_lock)
    root = cache_root / "omp" / condition_identity.value
    manifest_path = root / "provisioning.json"
    try:
        manifest_data = _read_regular_file(manifest_path)
        manifest = load_canonical_json(manifest_data)
    except (OSError, CanonicalizationError) as error:
        raise OmpConditionError(
            "condition-unqualified",
            f"OMP provisioning manifest is unavailable or invalid: {error}",
        ) from error
    artifact_relative = (
        Path("artifacts") / OMP_ARTIFACT_IDENTITY.rsplit(":", 1)[1] / "omp"
    )
    shim_relative = Path("adapters") / OMP_SHIM_IDENTITY.rsplit(":", 1)[1] / "omp-launch"
    shim_data = omp_launch_shim_path().read_bytes()
    expected = {
        "artifact": {
            "bytes": OMP_ARTIFACT_BYTES,
            "identity": OMP_ARTIFACT_IDENTITY,
            "path": artifact_relative.as_posix(),
            "source": OMP_ARTIFACT_URL,
            "version": OMP_VERSION,
        },
        "condition_identity": str(condition_identity),
        "launch_shim": {
            "bytes": len(shim_data),
            "identity": OMP_SHIM_IDENTITY,
            "path": shim_relative.as_posix(),
        },
        "network": "provision-only",
        "schema_version": 1,
    }
    if manifest != expected:
        raise OmpConditionError(
            "condition-unqualified",
            "OMP provisioning manifest does not match the sealed condition",
        )
    artifact_path = cache_root / artifact_relative
    launch_shim_path = cache_root / shim_relative
    _verify_executable(artifact_path, OMP_ARTIFACT_IDENTITY, OMP_ARTIFACT_BYTES)
    _verify_executable(launch_shim_path, OMP_SHIM_IDENTITY, len(shim_data))
    return OmpProvisioning(
        condition_identity=str(condition_identity),
        artifact_path=artifact_path,
        artifact_identity=OMP_ARTIFACT_IDENTITY,
        launch_shim_path=launch_shim_path,
        launch_shim_identity=OMP_SHIM_IDENTITY,
        manifest_path=manifest_path,
    )


def sealed_omp_process(
    provisioning: OmpProvisioning,
    *,
    proxy_base_url: str,
    provider_model: str,
    trial_proxy_token: str,
) -> SealedConditionProcess:
    _, lock, condition_identity = load_omp_condition_lock()
    artifact = lock.get("artifact")
    adapter = lock.get("adapter")
    configuration = adapter.get("configuration") if isinstance(adapter, dict) else None
    shim = (
        configuration.get("launch_shim")
        if isinstance(configuration, dict)
        else None
    )
    if (
        not isinstance(artifact, dict)
        or not isinstance(configuration, dict)
        or not isinstance(shim, dict)
        or provisioning.condition_identity != str(condition_identity)
        or provisioning.artifact_identity != artifact.get("digest")
        or provisioning.launch_shim_identity != shim.get("digest")
    ):
        raise OmpConditionError(
            "condition-unqualified",
            "measured OMP launch does not match the sealed condition",
        )
    artifact_bytes = configuration.get("artifact_bytes")
    if not isinstance(artifact_bytes, int) or isinstance(artifact_bytes, bool):
        raise OmpConditionError(
            "condition-unqualified",
            "sealed OMP artifact size is invalid",
        )
    _verify_executable(
        provisioning.artifact_path,
        provisioning.artifact_identity,
        artifact_bytes,
    )
    _verify_executable(
        provisioning.launch_shim_path,
        provisioning.launch_shim_identity,
        len(omp_launch_shim_path().read_bytes()),
    )
    parsed = urlsplit(proxy_base_url)
    if (
        parsed.scheme != "http"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or proxy_base_url.endswith("/")
    ):
        raise OmpConditionError(
            "condition-unqualified",
            "OMP must receive one canonical internal HTTP Credential Proxy route",
        )
    if not provider_model or any(ord(character) < 32 for character in provider_model):
        raise OmpConditionError("condition-unqualified", "OMP provider model is invalid")
    if not trial_proxy_token or any(character in trial_proxy_token for character in "\r\n\x00"):
        raise OmpConditionError("condition-unqualified", "OMP proxy token is invalid")
    return SealedConditionProcess(
        condition="omp",
        artifact_path=provisioning.launch_shim_path,
        artifact_identity=provisioning.launch_shim_identity,
        arguments=(
            "--omp",
            str(provisioning.artifact_path),
            "--artifact-identity",
            provisioning.artifact_identity,
        ),
        environment={
            "MODEL_BENCHMARK_PROVIDER_MODEL": provider_model,
            "MODEL_BENCHMARK_PROXY_BASE_URL": proxy_base_url,
            TRIAL_PROXY_TOKEN_ENV: trial_proxy_token,
        },
        native_artifact_paths=(
            "home/.model-benchmark/omp-delivery.json",
            "home/.model-benchmark/omp-rpc.jsonl",
        ),
    )


def evaluate_omp_qualification(
    result: ConditionProcessResult,
    proxy_evidence_path: Path,
    *,
    expected_brief_sha256: str,
    observed_brief_sha256: str,
    workspace_verified: bool,
    unexpected_network_requests: int,
) -> OmpQualification:
    evidence = {
        "artifact_digests": dict(result.artifact_digests),
        "brief_sha256": observed_brief_sha256,
        "exit_code": result.exit_code,
        "expected_brief_sha256": expected_brief_sha256,
        "process_tree_terminated": result.process_tree_terminated,
        "provider_response_count": 0,
        "signal": result.signal,
        "unexpected_network_requests": unexpected_network_requests,
        "workspace_verified": workspace_verified,
    }
    reason_code: str | None = None
    if not result.infrastructure_valid:
        reason_code = result.reason_code
    elif result.exit_code != 0 or result.signal is not None:
        reason_code = "omp-rpc-unsupported"
    elif not result.process_tree_terminated:
        reason_code = "omp-process-tree-incomplete"
    elif not {
        "home/.model-benchmark/omp-delivery.json",
        "home/.model-benchmark/omp-rpc.jsonl",
    }.issubset(result.artifact_digests):
        reason_code = "omp-native-artifact-missing"
    elif expected_brief_sha256 != observed_brief_sha256:
        reason_code = "omp-developer-brief-mismatch"
    elif not workspace_verified:
        reason_code = "omp-workspace-mismatch"
    elif unexpected_network_requests != 0:
        reason_code = "omp-unexpected-network"

    provider_events = _provider_events(proxy_evidence_path)
    evidence["provider_response_count"] = len(provider_events)
    if reason_code is None and not provider_events:
        reason_code = "omp-provider-evidence-missing"
    if reason_code is None and any(
        event.get("reason_code") is not None
        or not isinstance(event.get("provider_model"), str)
        or not isinstance(event.get("provider_tokens"), int)
        or isinstance(event.get("provider_tokens"), bool)
        or event.get("provider_cost_usd") is None
        for event in provider_events
    ):
        reason_code = "omp-provider-contract-violation"

    return OmpQualification(
        qualified=reason_code is None,
        reason_code=_QUALIFIED if reason_code is None else reason_code,
        evidence=evidence,
    )


def _provider_events(path: Path) -> list[dict[str, object]]:
    try:
        lines = _read_regular_file(path).splitlines()
    except OSError:
        return []
    events: list[dict[str, object]] = []
    for line in lines:
        try:
            value = json.loads(line.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError):
            return []
        if isinstance(value, dict) and value.get("event") == "provider-response":
            events.append(value)
    return events


def _download_artifact(destination: Path) -> None:
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    digest = hashlib.sha256()
    size = 0
    try:
        with urllib.request.urlopen(OMP_ARTIFACT_URL, timeout=120) as response:
            with temporary.open("xb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
                output.flush()
                os.fsync(output.fileno())
        identity = f"artifact:sha256:{digest.hexdigest()}"
        if identity != OMP_ARTIFACT_IDENTITY or size != OMP_ARTIFACT_BYTES:
            raise OmpConditionError(
                "artifact-verification-failed",
                "downloaded OMP v16.4.0 artifact does not match its sealed identity",
            )
        temporary.chmod(0o555)
        os.link(temporary, destination)
    except FileExistsError:
        _verify_executable(destination, OMP_ARTIFACT_IDENTITY, OMP_ARTIFACT_BYTES)
    finally:
        temporary.unlink(missing_ok=True)


def _publish_bytes(destination: Path, data: bytes, *, mode: int) -> None:
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        temporary.chmod(mode)
        os.link(temporary, destination)
    except FileExistsError:
        if _read_regular_file(destination) != data:
            raise OmpConditionError(
                "immutable-cache-conflict",
                f"immutable OMP cache path changed: {destination.name}",
            )
    finally:
        temporary.unlink(missing_ok=True)


def _read_regular_file(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError("not a regular file")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _verify_executable(path: Path, identity: str, expected_size: int) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_size != expected_size
                or metadata.st_mode & 0o111 == 0
            ):
                raise OSError("artifact metadata mismatch")
            digest = hashlib.sha256()
            while chunk := os.read(descriptor, 1024 * 1024):
                digest.update(chunk)
        finally:
            os.close(descriptor)
    except OSError as error:
        raise OmpConditionError(
            "condition-unqualified",
            f"OMP cached executable is unavailable: {error}",
        ) from error
    if f"artifact:sha256:{digest.hexdigest()}" != identity:
        raise OmpConditionError(
            "condition-unqualified",
            "OMP cached executable identity mismatch",
        )

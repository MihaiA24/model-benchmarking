from __future__ import annotations

import hashlib
import os
import stat
import tarfile
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
from model_benchmark.declarations.provider_routes import (
    PROVIDER_PROTOCOL_ENV,
    parse_provider_protocol,
)
from model_benchmark.declarations.scenario_locks import (
    project_resource_root,
    standard_profile_path,
)
from model_benchmark.runtime.conditions import (
    ConditionAdapterError,
    ConditionProcessResult,
    ConditionQualification,
    SealedConditionProcess,
    provider_events,
    publish_bytes,
    read_regular_file,
)
from model_benchmark.runtime.credential_proxy import TRIAL_PROXY_TOKEN_ENV


OPENCODE_VERSION = "v1.17.18"
OPENCODE_RELEASE_COMMIT = "b1fc811"
OPENCODE_ARCHIVE_URL = (
    "https://github.com/anomalyco/opencode/releases/download/"
    "v1.17.18/opencode-linux-x64.tar.gz"
)
OPENCODE_ARCHIVE_IDENTITY = (
    "artifact:sha256:e149d32ee5667c0cd5fb84d0bf8393b312e93782eeb4d74d29bbb0392de7133c"
)
OPENCODE_ARCHIVE_BYTES = 69_427_073
OPENCODE_ARTIFACT_IDENTITY = (
    "artifact:sha256:0cbfb6de55aa4ce3c74da12d8516376033693a88abca6238c5be32bf98130636"
)
OPENCODE_ARTIFACT_BYTES = 188_979_328
OPENCODE_SHIM_IDENTITY = (
    "artifact:sha256:bddb2f91b0d1555d7de23a19976b470e7630bc78ce8e38f0ae9fa68eea6c8e5d"
)
OPENCODE_ENVIRONMENT_NAMES = (
    "MODEL_BENCHMARK_PROVIDER_MODEL",
    PROVIDER_PROTOCOL_ENV,
    "MODEL_BENCHMARK_PROXY_BASE_URL",
    TRIAL_PROXY_TOKEN_ENV,
)
_QUALIFIED = "qualified"


@dataclass(frozen=True)
class OpenCodeProvisioning:
    condition_identity: str
    archive_path: Path
    archive_identity: str
    artifact_path: Path
    artifact_identity: str
    launch_shim_path: Path
    launch_shim_identity: str
    manifest_path: Path


def opencode_condition_lock_path() -> Path:
    path = (
        project_resource_root("profiles", "published_profiles")
        / "functional-v1"
        / "opencode-v1.17.18.condition.json"
    )
    if not path.is_file():
        raise ConditionAdapterError(
            "condition-lock-unavailable",
            "OpenCode condition lock is unavailable",
        )
    return path


def opencode_launch_shim_path() -> Path:
    path = Path(__file__).with_name("opencode_launch.py")
    if not path.is_file():
        raise ConditionAdapterError(
            "launch-shim-unavailable",
            "OpenCode launch shim is unavailable",
        )
    return path


def _locked_provider_config() -> dict[str, object]:
    return {
        "autoupdate": False,
        "mcp": {},
        "plugin": [],
        "provider": {
            "model-benchmark-proxy": {
                "models": {
                    "manifest-provider-model": {
                        "name": "manifest-provider-model",
                    }
                },
                "name": "Model Benchmark Credential Proxy",
                "npm": "manifest-provider-npm",
                "options": {
                    "apiKey": "{env:MODEL_BENCHMARK_PROXY_TOKEN}",
                    "baseURL": "manifest-provider-base-url",
                },
            }
        },
        "share": "disabled",
    }


def _locked_configuration() -> dict[str, object]:
    return {
        "archive_bytes": OPENCODE_ARCHIVE_BYTES,
        "archive_digest": OPENCODE_ARCHIVE_IDENTITY,
        "archive_source": OPENCODE_ARCHIVE_URL,
        "artifact_bytes": OPENCODE_ARTIFACT_BYTES,
        "artifact_commit": OPENCODE_RELEASE_COMMIT,
        "artifact_version": OPENCODE_VERSION,
        "auth_persistence": False,
        "fixed_environment": {
            "OPENCODE_CONFIG": "fresh-home/.model-benchmark/opencode.json",
            "OPENCODE_DISABLE_AUTOUPDATE": "true",
            "OPENCODE_DISABLE_PROJECT_CONFIG": "true",
        },
        "instruction_transport": "run-stdin-json-events",
        "launch_shim": {
            "digest": OPENCODE_SHIM_IDENTITY,
            "source_path": "model_benchmark/runtime/opencode_launch.py",
        },
        "opencode_json": _locked_provider_config(),
        "provision": {
            "archive_format": "tar-gzip",
            "archive_member": "opencode",
            "network": "provision-only",
            "operation": "download-once-verify-sha256-extract-single-file",
        },
        "runtime_installation": False,
        "session_persistence": False,
        "shutdown": "process-exit-then-process-group-teardown",
    }


def load_opencode_condition_lock() -> tuple[bytes, Mapping[str, object], TypedDigest]:
    try:
        data = opencode_condition_lock_path().read_bytes()
        value = load_canonical_json(data)
    except (OSError, CanonicalizationError) as error:
        raise ConditionAdapterError("invalid-condition-lock", str(error)) from error
    if not isinstance(value, dict):
        raise ConditionAdapterError(
            "invalid-condition-lock",
            "OpenCode condition lock is not an object",
        )
    _verify_lock_dependencies(value)
    identity = TypedDigest.from_bytes(DigestKind.FUNCTIONAL_V1_CONDITION, data)
    return data, MappingProxyType(value), identity


def validate_opencode_condition_lock(data: bytes) -> TypedDigest:
    expected, _, identity = load_opencode_condition_lock()
    if data != expected:
        raise ConditionAdapterError(
            "condition-unqualified",
            "OpenCode condition lock differs from the qualified v1.17.18 lock",
        )
    return identity


def _verify_lock_dependencies(lock: dict[str, object]) -> None:
    artifact = lock.get("artifact")
    adapter = lock.get("adapter")
    if not isinstance(artifact, dict) or not isinstance(adapter, dict):
        raise ConditionAdapterError(
            "invalid-condition-lock",
            "OpenCode lock structure is invalid",
        )
    expected_profile = TypedDigest.from_bytes(
        DigestKind.EXECUTION_PROFILE,
        standard_profile_path().read_bytes(),
    )
    expected_shim = TypedDigest.from_bytes(
        DigestKind.ARTIFACT,
        opencode_launch_shim_path().read_bytes(),
    )
    if (
        lock.get("schema_version") != 1
        or lock.get("condition") != "opencode"
        or lock.get("execution_profile") != str(expected_profile)
        or artifact
        != {
            "digest": OPENCODE_ARTIFACT_IDENTITY,
            "kind": "native-executable",
            "platform": "linux/amd64",
        }
        or adapter.get("argv")
        != [
            "/opt/model-benchmark-condition/entrypoint",
            "--condition",
            "opencode",
            "--artifact-identity",
            "{artifact_identity}",
        ]
        or adapter.get("configuration") != _locked_configuration()
        or adapter.get("environment_names") != list(OPENCODE_ENVIRONMENT_NAMES)
        or adapter.get("non_interactive") is not True
        or adapter.get("self_update") is not False
        or adapter.get("working_directory") != "/workspace"
        or str(expected_shim) != OPENCODE_SHIM_IDENTITY
    ):
        raise ConditionAdapterError(
            "invalid-condition-lock",
            "OpenCode v1.17.18 artifact, profile, or adapter declaration does not match",
        )


def provision_opencode(cache_root: Path, condition_lock: bytes) -> OpenCodeProvisioning:
    condition_identity = validate_opencode_condition_lock(condition_lock)
    root = cache_root / "opencode" / condition_identity.value
    manifest_path = root / "provisioning.json"
    if manifest_path.exists() or manifest_path.is_symlink():
        return preflight_opencode(cache_root, condition_lock)

    archive_relative = (
        Path("downloads")
        / OPENCODE_ARCHIVE_IDENTITY.rsplit(":", 1)[1]
        / "opencode-linux-x64.tar.gz"
    )
    artifact_relative = (
        Path("artifacts") / OPENCODE_ARTIFACT_IDENTITY.rsplit(":", 1)[1] / "opencode"
    )
    shim_relative = (
        Path("adapters") / OPENCODE_SHIM_IDENTITY.rsplit(":", 1)[1] / "opencode-launch"
    )
    archive_path = cache_root / archive_relative
    artifact_path = cache_root / artifact_relative
    shim_path = cache_root / shim_relative
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    archive_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    artifact_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    shim_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if archive_path.exists() or archive_path.is_symlink():
        _verify_file(
            archive_path,
            OPENCODE_ARCHIVE_IDENTITY,
            OPENCODE_ARCHIVE_BYTES,
            executable=False,
            label="archive",
        )
    else:
        _download_archive(archive_path)
    if artifact_path.exists() or artifact_path.is_symlink():
        _verify_file(
            artifact_path,
            OPENCODE_ARTIFACT_IDENTITY,
            OPENCODE_ARTIFACT_BYTES,
            executable=True,
            label="executable",
        )
    else:
        _extract_artifact(archive_path, artifact_path)
    shim_data = opencode_launch_shim_path().read_bytes()
    if shim_path.exists() or shim_path.is_symlink():
        _verify_file(
            shim_path,
            OPENCODE_SHIM_IDENTITY,
            len(shim_data),
            executable=True,
            label="launch shim",
        )
    else:
        publish_bytes(shim_path, shim_data, mode=0o555, condition="OpenCode")
        _verify_file(
            shim_path,
            OPENCODE_SHIM_IDENTITY,
            len(shim_data),
            executable=True,
            label="launch shim",
        )

    manifest = _provisioning_manifest(
        condition_identity=str(condition_identity),
        archive_relative=archive_relative,
        artifact_relative=artifact_relative,
        shim_relative=shim_relative,
        shim_bytes=len(shim_data),
    )
    publish_bytes(
        manifest_path, canonical_json_bytes(manifest), mode=0o400, condition="OpenCode"
    )
    return preflight_opencode(cache_root, condition_lock)


def preflight_opencode(cache_root: Path, condition_lock: bytes) -> OpenCodeProvisioning:
    condition_identity = validate_opencode_condition_lock(condition_lock)
    root = cache_root / "opencode" / condition_identity.value
    manifest_path = root / "provisioning.json"
    try:
        manifest = load_canonical_json(read_regular_file(manifest_path))
    except (OSError, CanonicalizationError) as error:
        raise ConditionAdapterError(
            "condition-unqualified",
            f"OpenCode provisioning manifest is unavailable or invalid: {error}",
        ) from error
    archive_relative = (
        Path("downloads")
        / OPENCODE_ARCHIVE_IDENTITY.rsplit(":", 1)[1]
        / "opencode-linux-x64.tar.gz"
    )
    artifact_relative = (
        Path("artifacts") / OPENCODE_ARTIFACT_IDENTITY.rsplit(":", 1)[1] / "opencode"
    )
    shim_relative = (
        Path("adapters") / OPENCODE_SHIM_IDENTITY.rsplit(":", 1)[1] / "opencode-launch"
    )
    shim_data = opencode_launch_shim_path().read_bytes()
    expected = _provisioning_manifest(
        condition_identity=str(condition_identity),
        archive_relative=archive_relative,
        artifact_relative=artifact_relative,
        shim_relative=shim_relative,
        shim_bytes=len(shim_data),
    )
    if manifest != expected:
        raise ConditionAdapterError(
            "condition-unqualified",
            "OpenCode provisioning manifest does not match the sealed condition",
        )
    archive_path = cache_root / archive_relative
    artifact_path = cache_root / artifact_relative
    launch_shim_path = cache_root / shim_relative
    _verify_file(
        archive_path,
        OPENCODE_ARCHIVE_IDENTITY,
        OPENCODE_ARCHIVE_BYTES,
        executable=False,
        label="archive",
    )
    _verify_file(
        artifact_path,
        OPENCODE_ARTIFACT_IDENTITY,
        OPENCODE_ARTIFACT_BYTES,
        executable=True,
        label="executable",
    )
    _verify_file(
        launch_shim_path,
        OPENCODE_SHIM_IDENTITY,
        len(shim_data),
        executable=True,
        label="launch shim",
    )
    return OpenCodeProvisioning(
        condition_identity=str(condition_identity),
        archive_path=archive_path,
        archive_identity=OPENCODE_ARCHIVE_IDENTITY,
        artifact_path=artifact_path,
        artifact_identity=OPENCODE_ARTIFACT_IDENTITY,
        launch_shim_path=launch_shim_path,
        launch_shim_identity=OPENCODE_SHIM_IDENTITY,
        manifest_path=manifest_path,
    )


def _provisioning_manifest(
    *,
    condition_identity: str,
    archive_relative: Path,
    artifact_relative: Path,
    shim_relative: Path,
    shim_bytes: int,
) -> dict[str, object]:
    return {
        "archive": {
            "bytes": OPENCODE_ARCHIVE_BYTES,
            "identity": OPENCODE_ARCHIVE_IDENTITY,
            "path": archive_relative.as_posix(),
            "source": OPENCODE_ARCHIVE_URL,
        },
        "artifact": {
            "bytes": OPENCODE_ARTIFACT_BYTES,
            "commit": OPENCODE_RELEASE_COMMIT,
            "identity": OPENCODE_ARTIFACT_IDENTITY,
            "path": artifact_relative.as_posix(),
            "version": OPENCODE_VERSION,
        },
        "condition_identity": condition_identity,
        "extraction": {
            "archive_format": "tar-gzip",
            "archive_member": "opencode",
        },
        "launch_shim": {
            "bytes": shim_bytes,
            "identity": OPENCODE_SHIM_IDENTITY,
            "path": shim_relative.as_posix(),
        },
        "network": "provision-only",
        "schema_version": 1,
    }


def sealed_opencode_process(
    provisioning: OpenCodeProvisioning,
    *,
    proxy_base_url: str,
    provider_model: str,
    trial_proxy_token: str,
    provider_protocol: str = "openai-chat-completions",
) -> SealedConditionProcess:
    _, lock, condition_identity = load_opencode_condition_lock()
    artifact = lock.get("artifact")
    adapter = lock.get("adapter")
    configuration = adapter.get("configuration") if isinstance(adapter, dict) else None
    shim = configuration.get("launch_shim") if isinstance(configuration, dict) else None
    if (
        not isinstance(artifact, dict)
        or not isinstance(configuration, dict)
        or not isinstance(shim, dict)
        or provisioning.condition_identity != str(condition_identity)
        or provisioning.archive_identity != configuration.get("archive_digest")
        or provisioning.artifact_identity != artifact.get("digest")
        or provisioning.launch_shim_identity != shim.get("digest")
    ):
        raise ConditionAdapterError(
            "condition-unqualified",
            "measured OpenCode launch does not match the sealed condition",
        )
    archive_bytes = configuration.get("archive_bytes")
    artifact_bytes = configuration.get("artifact_bytes")
    if (
        not isinstance(archive_bytes, int)
        or isinstance(archive_bytes, bool)
        or not isinstance(artifact_bytes, int)
        or isinstance(artifact_bytes, bool)
    ):
        raise ConditionAdapterError(
            "condition-unqualified",
            "sealed OpenCode artifact sizes are invalid",
        )
    _verify_file(
        provisioning.archive_path,
        provisioning.archive_identity,
        archive_bytes,
        executable=False,
        label="archive",
    )
    _verify_file(
        provisioning.artifact_path,
        provisioning.artifact_identity,
        artifact_bytes,
        executable=True,
        label="executable",
    )
    _verify_file(
        provisioning.launch_shim_path,
        provisioning.launch_shim_identity,
        len(opencode_launch_shim_path().read_bytes()),
        executable=True,
        label="launch shim",
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
        raise ConditionAdapterError(
            "condition-unqualified",
            "OpenCode must receive one canonical internal HTTP Credential Proxy route",
        )
    if not provider_model or any(ord(character) < 32 for character in provider_model):
        raise ConditionAdapterError(
            "condition-unqualified",
            "OpenCode provider model is invalid",
        )
    if not trial_proxy_token or any(
        character in trial_proxy_token for character in "\r\n\x00"
    ):
        raise ConditionAdapterError(
            "condition-unqualified",
            "OpenCode proxy token is invalid",
        )
    try:
        protocol = parse_provider_protocol(provider_protocol)
    except ValueError as error:
        raise ConditionAdapterError("condition-unqualified", str(error)) from error
    return SealedConditionProcess(
        condition="opencode",
        artifact_path=provisioning.launch_shim_path,
        artifact_identity=provisioning.launch_shim_identity,
        arguments=(
            "--opencode",
            str(provisioning.artifact_path),
            "--artifact-identity",
            provisioning.artifact_identity,
        ),
        environment={
            "MODEL_BENCHMARK_PROVIDER_MODEL": provider_model,
            PROVIDER_PROTOCOL_ENV: protocol.value,
            "MODEL_BENCHMARK_PROXY_BASE_URL": proxy_base_url,
            TRIAL_PROXY_TOKEN_ENV: trial_proxy_token,
        },
        native_artifact_paths=(
            "home/.model-benchmark/opencode-delivery.json",
            "home/.model-benchmark/opencode-events.jsonl",
        ),
    )


def evaluate_opencode_qualification(
    result: ConditionProcessResult,
    proxy_evidence_path: Path,
    *,
    expected_brief_sha256: str,
    observed_brief_sha256: str,
    workspace_verified: bool,
    unexpected_network_requests: int,
) -> ConditionQualification:
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
        reason_code = "opencode-run-unsupported"
    elif not result.process_tree_terminated:
        reason_code = "opencode-process-tree-incomplete"
    elif not {
        "home/.model-benchmark/opencode-delivery.json",
        "home/.model-benchmark/opencode-events.jsonl",
    }.issubset(result.artifact_digests):
        reason_code = "opencode-native-artifact-missing"
    elif expected_brief_sha256 != observed_brief_sha256:
        reason_code = "opencode-developer-brief-mismatch"
    elif not workspace_verified:
        reason_code = "opencode-workspace-mismatch"
    elif unexpected_network_requests != 0:
        reason_code = "opencode-unexpected-network"

    events = provider_events(proxy_evidence_path)
    evidence["provider_response_count"] = len(events)
    if reason_code is None and not events:
        reason_code = "opencode-provider-evidence-missing"
    if reason_code is None and any(
        event.get("reason_code") is not None
        or not isinstance(event.get("provider_model"), str)
        or not isinstance(event.get("provider_tokens"), int)
        or isinstance(event.get("provider_tokens"), bool)
        or event.get("provider_cost_usd") is None
        for event in events
    ):
        reason_code = "opencode-provider-contract-violation"

    return ConditionQualification(
        qualified=reason_code is None,
        reason_code=_QUALIFIED if reason_code is None else reason_code,
        evidence=evidence,
    )


def _download_archive(destination: Path) -> None:
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    digest = hashlib.sha256()
    size = 0
    try:
        with urllib.request.urlopen(OPENCODE_ARCHIVE_URL, timeout=120) as response:
            with temporary.open("xb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
                output.flush()
                os.fsync(output.fileno())
        identity = f"artifact:sha256:{digest.hexdigest()}"
        if identity != OPENCODE_ARCHIVE_IDENTITY or size != OPENCODE_ARCHIVE_BYTES:
            raise ConditionAdapterError(
                "artifact-verification-failed",
                "downloaded OpenCode v1.17.18 archive does not match its sealed identity",
            )
        temporary.chmod(0o444)
        os.link(temporary, destination)
    except FileExistsError:
        _verify_file(
            destination,
            OPENCODE_ARCHIVE_IDENTITY,
            OPENCODE_ARCHIVE_BYTES,
            executable=False,
            label="archive",
        )
    finally:
        temporary.unlink(missing_ok=True)


def _extract_artifact(archive_path: Path, destination: Path) -> None:
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            members = archive.getmembers()
            if (
                len(members) != 1
                or members[0].name != "opencode"
                or not members[0].isfile()
                or members[0].size != OPENCODE_ARTIFACT_BYTES
            ):
                raise ConditionAdapterError(
                    "artifact-verification-failed",
                    "OpenCode archive does not contain exactly the sealed executable",
                )
            source = archive.extractfile(members[0])
            if source is None:
                raise ConditionAdapterError(
                    "artifact-verification-failed",
                    "OpenCode executable cannot be read from the sealed archive",
                )
            with source, temporary.open("xb") as output:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
        temporary.chmod(0o555)
        _verify_file(
            temporary,
            OPENCODE_ARTIFACT_IDENTITY,
            OPENCODE_ARTIFACT_BYTES,
            executable=True,
            label="executable",
        )
        os.link(temporary, destination)
    except FileExistsError:
        _verify_file(
            destination,
            OPENCODE_ARTIFACT_IDENTITY,
            OPENCODE_ARTIFACT_BYTES,
            executable=True,
            label="executable",
        )
    except (OSError, tarfile.TarError) as error:
        raise ConditionAdapterError(
            "artifact-verification-failed",
            f"OpenCode archive extraction failed: {error}",
        ) from error
    finally:
        temporary.unlink(missing_ok=True)


def _verify_file(
    path: Path,
    identity: str,
    expected_size: int,
    *,
    executable: bool,
    label: str,
) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_size != expected_size
                or (executable and metadata.st_mode & 0o111 == 0)
            ):
                raise OSError("artifact metadata mismatch")
            digest = hashlib.sha256()
            while chunk := os.read(descriptor, 1024 * 1024):
                digest.update(chunk)
        finally:
            os.close(descriptor)
    except OSError as error:
        raise ConditionAdapterError(
            "condition-unqualified",
            f"OpenCode cached {label} is unavailable: {error}",
        ) from error
    if f"artifact:sha256:{digest.hexdigest()}" != identity:
        raise ConditionAdapterError(
            "condition-unqualified",
            f"OpenCode cached {label} identity mismatch",
        )

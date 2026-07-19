from __future__ import annotations

import os
import tarfile

# ``urllib`` stays imported here because the acceptance suite patches
# ``urllib.request.urlopen`` through this module's namespace.
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from model_benchmark.declarations.canonical import canonical_json_bytes
from model_benchmark.declarations.identities import TypedDigest
from model_benchmark.declarations.scenario_locks import (
    project_resource_root,
    standard_profile_path,
)
from model_benchmark.runtime.conditions import (
    ConditionAdapterError,
    ConditionProcessResult,
    ConditionQualification,
    SealedConditionProcess,
    cache_relative_path,
    check_provisioning_manifest,
    download_verified,
    ensure_launch_shim,
    evaluate_harness_qualification,
    harness_environment,
    load_condition_lock,
    publish_bytes,
    validate_condition_lock,
    validate_sealed_launch_inputs,
    verify_cached_file,
    verify_lock_declaration,
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
    "artifact:sha256:c6a931f179f7b0d43742cb07e784ba6723790e6ea1a27eb022a8b2e3184301c7"
)
OPENCODE_ENVIRONMENT_NAMES = (
    "MODEL_BENCHMARK_PROVIDER_MODEL",
    "MODEL_BENCHMARK_PROXY_BASE_URL",
    TRIAL_PROXY_TOKEN_ENV,
)
_NATIVE_ARTIFACT_PATHS = (
    "home/.model-benchmark/opencode-delivery.json",
    "home/.model-benchmark/opencode-events.jsonl",
)


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
                "npm": "@ai-sdk/openai-compatible",
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
    return load_condition_lock(
        opencode_condition_lock_path, label="OpenCode", verify=_verify_lock_dependencies
    )


def validate_opencode_condition_lock(data: bytes) -> TypedDigest:
    return validate_condition_lock(
        load_opencode_condition_lock,
        data,
        mismatch_message="OpenCode condition lock differs from the qualified v1.17.18 lock",
    )


def _verify_lock_dependencies(lock: dict[str, object]) -> None:
    verify_lock_declaration(
        lock,
        condition="opencode",
        artifact_identity=OPENCODE_ARTIFACT_IDENTITY,
        configuration=_locked_configuration(),
        environment_names=OPENCODE_ENVIRONMENT_NAMES,
        shim_identity=OPENCODE_SHIM_IDENTITY,
        profile_data=standard_profile_path().read_bytes(),
        shim_data=opencode_launch_shim_path().read_bytes(),
        structure_message="OpenCode lock structure is invalid",
        mismatch_message="OpenCode v1.17.18 artifact, profile, or adapter declaration does not match",
    )


def _provisioning_manifest(
    *, condition_identity: str, shim_bytes: int
) -> dict[str, object]:
    return {
        "archive": {
            "bytes": OPENCODE_ARCHIVE_BYTES,
            "identity": OPENCODE_ARCHIVE_IDENTITY,
            "path": cache_relative_path(
                "downloads", OPENCODE_ARCHIVE_IDENTITY, "opencode-linux-x64.tar.gz"
            ).as_posix(),
            "source": OPENCODE_ARCHIVE_URL,
        },
        "artifact": {
            "bytes": OPENCODE_ARTIFACT_BYTES,
            "commit": OPENCODE_RELEASE_COMMIT,
            "identity": OPENCODE_ARTIFACT_IDENTITY,
            "path": cache_relative_path(
                "artifacts", OPENCODE_ARTIFACT_IDENTITY, "opencode"
            ).as_posix(),
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
            "path": cache_relative_path(
                "adapters", OPENCODE_SHIM_IDENTITY, "opencode-launch"
            ).as_posix(),
        },
        "network": "provision-only",
        "schema_version": 1,
    }


def provision_opencode(cache_root: Path, condition_lock: bytes) -> OpenCodeProvisioning:
    condition_identity = validate_opencode_condition_lock(condition_lock)
    root = cache_root / "opencode" / condition_identity.value
    manifest_path = root / "provisioning.json"
    if manifest_path.exists() or manifest_path.is_symlink():
        return preflight_opencode(cache_root, condition_lock)

    archive_path = cache_root / cache_relative_path(
        "downloads", OPENCODE_ARCHIVE_IDENTITY, "opencode-linux-x64.tar.gz"
    )
    artifact_path = cache_root / cache_relative_path(
        "artifacts", OPENCODE_ARTIFACT_IDENTITY, "opencode"
    )
    shim_path = cache_root / cache_relative_path(
        "adapters", OPENCODE_SHIM_IDENTITY, "opencode-launch"
    )
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
        download_verified(
            archive_path,
            url=OPENCODE_ARCHIVE_URL,
            identity=OPENCODE_ARCHIVE_IDENTITY,
            expected_bytes=OPENCODE_ARCHIVE_BYTES,
            mode=0o444,
            condition="OpenCode",
            label="archive",
            executable=False,
            mismatch_message="downloaded OpenCode v1.17.18 archive does not match its sealed identity",
        )
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
    ensure_launch_shim(
        shim_path,
        shim_data,
        identity=OPENCODE_SHIM_IDENTITY,
        condition="OpenCode",
        label="launch shim",
    )
    publish_bytes(
        manifest_path,
        canonical_json_bytes(
            _provisioning_manifest(
                condition_identity=str(condition_identity), shim_bytes=len(shim_data)
            )
        ),
        mode=0o400,
        condition="OpenCode",
    )
    return preflight_opencode(cache_root, condition_lock)


def preflight_opencode(cache_root: Path, condition_lock: bytes) -> OpenCodeProvisioning:
    condition_identity = validate_opencode_condition_lock(condition_lock)
    manifest_path = (
        cache_root / "opencode" / condition_identity.value / "provisioning.json"
    )
    shim_data = opencode_launch_shim_path().read_bytes()
    check_provisioning_manifest(
        manifest_path,
        _provisioning_manifest(
            condition_identity=str(condition_identity), shim_bytes=len(shim_data)
        ),
        condition="OpenCode",
    )
    archive_path = cache_root / cache_relative_path(
        "downloads", OPENCODE_ARCHIVE_IDENTITY, "opencode-linux-x64.tar.gz"
    )
    artifact_path = cache_root / cache_relative_path(
        "artifacts", OPENCODE_ARTIFACT_IDENTITY, "opencode"
    )
    launch_shim_path = cache_root / cache_relative_path(
        "adapters", OPENCODE_SHIM_IDENTITY, "opencode-launch"
    )
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


def sealed_opencode_process(
    provisioning: OpenCodeProvisioning,
    *,
    proxy_base_url: str,
    provider_model: str,
    trial_proxy_token: str,
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
    validate_sealed_launch_inputs(
        condition="OpenCode",
        proxy_base_url=proxy_base_url,
        provider_model=provider_model,
        trial_proxy_token=trial_proxy_token,
    )
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
        environment=harness_environment(
            provider_model=provider_model,
            proxy_base_url=proxy_base_url,
            trial_proxy_token=trial_proxy_token,
        ),
        native_artifact_paths=_NATIVE_ARTIFACT_PATHS,
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
    return evaluate_harness_qualification(
        result,
        proxy_evidence_path,
        prefix="opencode",
        run_failure_reason="opencode-run-unsupported",
        required_artifacts=frozenset(_NATIVE_ARTIFACT_PATHS),
        expected_brief_sha256=expected_brief_sha256,
        observed_brief_sha256=observed_brief_sha256,
        workspace_verified=workspace_verified,
        unexpected_network_requests=unexpected_network_requests,
    )


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
    verify_cached_file(
        path,
        identity,
        expected_size,
        condition="OpenCode",
        label=label,
        executable=executable,
    )

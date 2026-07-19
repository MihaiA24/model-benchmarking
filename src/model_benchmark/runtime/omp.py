from __future__ import annotations

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
_NATIVE_ARTIFACT_PATHS = (
    "home/.model-benchmark/omp-delivery.json",
    "home/.model-benchmark/omp-rpc.jsonl",
)


@dataclass(frozen=True)
class OmpProvisioning:
    condition_identity: str
    artifact_path: Path
    artifact_identity: str
    launch_shim_path: Path
    launch_shim_identity: str
    manifest_path: Path


def omp_condition_lock_path() -> Path:
    path = (
        project_resource_root("profiles", "published_profiles")
        / "functional-v1"
        / "omp-v16.4.0.condition.json"
    )
    if not path.is_file():
        raise ConditionAdapterError("condition-lock-unavailable", "OMP condition lock is unavailable")
    return path


def omp_launch_shim_path() -> Path:
    path = Path(__file__).with_name("omp_launch.py")
    if not path.is_file():
        raise ConditionAdapterError("launch-shim-unavailable", "OMP launch shim is unavailable")
    return path


def _locked_provider_config() -> dict[str, object]:
    return {
        "providers": {
            "model-benchmark-proxy": {
                "api": "openai-completions",
                "apiKey": "MODEL_BENCHMARK_PROXY_TOKEN",
                "authHeader": True,
                "baseUrl": "manifest-provider-base-url",
                "models": [
                    {
                        "id": "manifest-provider-model",
                        "name": "manifest-provider-model",
                    }
                ],
            }
        },
    }


def _locked_configuration() -> dict[str, object]:
    return {
        "artifact_bytes": OMP_ARTIFACT_BYTES,
        "artifact_source": OMP_ARTIFACT_URL,
        "artifact_version": OMP_VERSION,
        "instruction_transport": "rpc-prompt-jsonl",
        "launch_shim": {
            "digest": OMP_SHIM_IDENTITY,
            "source_path": "model_benchmark/runtime/omp_launch.py",
        },
        "models_yml": _locked_provider_config(),
        "provision": {
            "network": "provision-only",
            "operation": "download-once-verify-sha256",
        },
        "runtime_installation": False,
        "session_persistence": False,
        "shutdown": "close-stdin-after-agent-end",
    }


def load_omp_condition_lock() -> tuple[bytes, Mapping[str, object], TypedDigest]:
    return load_condition_lock(
        omp_condition_lock_path, label="OMP", verify=_verify_lock_dependencies
    )


def validate_omp_condition_lock(data: bytes) -> TypedDigest:
    return validate_condition_lock(
        load_omp_condition_lock,
        data,
        mismatch_message="OMP condition lock differs from the qualified v16.4.0 lock",
    )


def _verify_lock_dependencies(lock: dict[str, object]) -> None:
    verify_lock_declaration(
        lock,
        condition="omp",
        artifact_identity=OMP_ARTIFACT_IDENTITY,
        configuration=_locked_configuration(),
        environment_names=OMP_ENVIRONMENT_NAMES,
        shim_identity=OMP_SHIM_IDENTITY,
        profile_data=standard_profile_path().read_bytes(),
        shim_data=omp_launch_shim_path().read_bytes(),
        structure_message="OMP lock structure is invalid",
        mismatch_message="OMP v16.4.0 artifact, profile, or adapter declaration does not match",
    )


def _provisioning_manifest(
    *, condition_identity: str, shim_bytes: int
) -> dict[str, object]:
    return {
        "artifact": {
            "bytes": OMP_ARTIFACT_BYTES,
            "identity": OMP_ARTIFACT_IDENTITY,
            "path": cache_relative_path(
                "artifacts", OMP_ARTIFACT_IDENTITY, "omp"
            ).as_posix(),
            "source": OMP_ARTIFACT_URL,
            "version": OMP_VERSION,
        },
        "condition_identity": condition_identity,
        "launch_shim": {
            "bytes": shim_bytes,
            "identity": OMP_SHIM_IDENTITY,
            "path": cache_relative_path(
                "adapters", OMP_SHIM_IDENTITY, "omp-launch"
            ).as_posix(),
        },
        "network": "provision-only",
        "schema_version": 1,
    }


def provision_omp(cache_root: Path, condition_lock: bytes) -> OmpProvisioning:
    condition_identity = validate_omp_condition_lock(condition_lock)
    root = cache_root / "omp" / condition_identity.value
    manifest_path = root / "provisioning.json"
    if manifest_path.exists() or manifest_path.is_symlink():
        return preflight_omp(cache_root, condition_lock)

    artifact_path = cache_root / cache_relative_path(
        "artifacts", OMP_ARTIFACT_IDENTITY, "omp"
    )
    shim_path = cache_root / cache_relative_path(
        "adapters", OMP_SHIM_IDENTITY, "omp-launch"
    )
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    artifact_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    shim_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if artifact_path.exists() or artifact_path.is_symlink():
        _verify_executable(artifact_path, OMP_ARTIFACT_IDENTITY, OMP_ARTIFACT_BYTES)
    else:
        download_verified(
            artifact_path,
            url=OMP_ARTIFACT_URL,
            identity=OMP_ARTIFACT_IDENTITY,
            expected_bytes=OMP_ARTIFACT_BYTES,
            mode=0o555,
            condition="OMP",
            label="executable",
            executable=True,
            mismatch_message="downloaded OMP v16.4.0 artifact does not match its sealed identity",
        )
    shim_data = omp_launch_shim_path().read_bytes()
    ensure_launch_shim(
        shim_path, shim_data, identity=OMP_SHIM_IDENTITY, condition="OMP", label="executable"
    )
    publish_bytes(
        manifest_path,
        canonical_json_bytes(
            _provisioning_manifest(
                condition_identity=str(condition_identity), shim_bytes=len(shim_data)
            )
        ),
        mode=0o400,
        condition="OMP",
    )
    return preflight_omp(cache_root, condition_lock)


def preflight_omp(cache_root: Path, condition_lock: bytes) -> OmpProvisioning:
    condition_identity = validate_omp_condition_lock(condition_lock)
    manifest_path = cache_root / "omp" / condition_identity.value / "provisioning.json"
    shim_data = omp_launch_shim_path().read_bytes()
    check_provisioning_manifest(
        manifest_path,
        _provisioning_manifest(
            condition_identity=str(condition_identity), shim_bytes=len(shim_data)
        ),
        condition="OMP",
    )
    artifact_path = cache_root / cache_relative_path(
        "artifacts", OMP_ARTIFACT_IDENTITY, "omp"
    )
    launch_shim_path = cache_root / cache_relative_path(
        "adapters", OMP_SHIM_IDENTITY, "omp-launch"
    )
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
        raise ConditionAdapterError(
            "condition-unqualified",
            "measured OMP launch does not match the sealed condition",
        )
    artifact_bytes = configuration.get("artifact_bytes")
    if not isinstance(artifact_bytes, int) or isinstance(artifact_bytes, bool):
        raise ConditionAdapterError(
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
    validate_sealed_launch_inputs(
        condition="OMP",
        proxy_base_url=proxy_base_url,
        provider_model=provider_model,
        trial_proxy_token=trial_proxy_token,
    )
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
        environment=harness_environment(
            provider_model=provider_model,
            proxy_base_url=proxy_base_url,
            trial_proxy_token=trial_proxy_token,
        ),
        native_artifact_paths=_NATIVE_ARTIFACT_PATHS,
    )


def evaluate_omp_qualification(
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
        prefix="omp",
        run_failure_reason="omp-rpc-unsupported",
        required_artifacts=frozenset(_NATIVE_ARTIFACT_PATHS),
        expected_brief_sha256=expected_brief_sha256,
        observed_brief_sha256=observed_brief_sha256,
        workspace_verified=workspace_verified,
        unexpected_network_requests=unexpected_network_requests,
    )


def _verify_executable(path: Path, identity: str, expected_size: int) -> None:
    verify_cached_file(
        path, identity, expected_size, condition="OMP", label="executable"
    )

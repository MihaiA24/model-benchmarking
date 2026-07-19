from __future__ import annotations

import json
import os
import shutil
import subprocess
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


HERMES_VERSION = "v0.18.2"
HERMES_RELEASE_TAG = "v2026.7.7.2"
HERMES_RELEASE_COMMIT = "9de9c25f620ff7f1ce0fd5457d596052d5159596"
HERMES_IMAGE_REFERENCE = (
    "nousresearch/hermes-agent@sha256:"
    "3db34ce19adfa080736a2a3feb0316dbcccc588faa9afe7fd8ae1c03b4f1a53a"
)
HERMES_IMAGE_IDENTITY = (
    "oci-image:sha256:3db34ce19adfa080736a2a3feb0316dbcccc588faa9afe7fd8ae1c03b4f1a53a"
)
HERMES_IMAGE_ID = (
    "sha256:e99ecbf328fe130bafe105748189f1e1b24e80189967cc7dd9ce129542370416"
)
HERMES_IMAGE_BYTES = 2_601_516_459
HERMES_ARTIFACT_CONTAINER_PATH = "/opt/hermes/bin/hermes"
HERMES_ARTIFACT_IDENTITY = (
    "artifact:sha256:57637e73c8db76aa84a38e4a2edb1b155bfd86a2e89a8d4c38c4546ee1175985"
)
HERMES_ARTIFACT_BYTES = 3_711
HERMES_SHIM_IDENTITY = (
    "artifact:sha256:1d0e721cead8e28b53dd10f479d92d39a2f1a60dd032ecaa195243d460932e4a"
)
HERMES_ENVIRONMENT_NAMES = (
    "MODEL_BENCHMARK_PROVIDER_MODEL",
    "MODEL_BENCHMARK_PROXY_BASE_URL",
    TRIAL_PROXY_TOKEN_ENV,
)
_NATIVE_ARTIFACT_PATHS = (
    "home/.hermes/logs/agent.log",
    "home/.hermes/state.db",
    "home/.model-benchmark/hermes-delivery.json",
    "home/.model-benchmark/hermes-usage.json",
)


@dataclass(frozen=True)
class HermesProvisioning:
    condition_identity: str
    image_reference: str
    image_identity: str
    image_id: str
    container_runtime_path: Path
    artifact_path: Path
    artifact_identity: str
    launch_shim_path: Path
    launch_shim_identity: str
    manifest_path: Path


def hermes_condition_lock_path() -> Path:
    path = (
        project_resource_root("profiles", "published_profiles")
        / "functional-v1"
        / "hermes-v0.18.2.condition.json"
    )
    if not path.is_file():
        raise ConditionAdapterError(
            "condition-lock-unavailable",
            "Hermes condition lock is unavailable",
        )
    return path


def hermes_launch_shim_path() -> Path:
    path = Path(__file__).with_name("hermes_launch.py")
    if not path.is_file():
        raise ConditionAdapterError(
            "launch-shim-unavailable",
            "Hermes launch shim is unavailable",
        )
    return path


def _locked_provider_config() -> dict[str, object]:
    return {
        "model": {
            "api_mode": "chat_completions",
            "base_url": "manifest-provider-base-url",
            "default": "manifest-provider-model",
            "provider": "custom:model-benchmark-proxy",
        },
        "providers": {
            "model-benchmark-proxy": {
                "api": "manifest-provider-base-url",
                "default_model": "manifest-provider-model",
                "key_env": "MODEL_BENCHMARK_PROXY_TOKEN",
                "name": "Model Benchmark Credential Proxy",
                "transport": "chat_completions",
            }
        },
    }


def _locked_configuration() -> dict[str, object]:
    return {
        "artifact_bytes": HERMES_ARTIFACT_BYTES,
        "artifact_commit": HERMES_RELEASE_COMMIT,
        "artifact_container_path": HERMES_ARTIFACT_CONTAINER_PATH,
        "artifact_version": HERMES_VERSION,
        "auth_persistence": False,
        "fixed_environment": {
            "HERMES_DISABLE_LAZY_INSTALLS": "1",
            "HERMES_HOME": "fresh-home/.hermes",
        },
        "hermes_config_yaml": _locked_provider_config(),
        "instruction_transport": "oneshot-argument-with-native-tools",
        "launch_shim": {
            "digest": HERMES_SHIM_IDENTITY,
            "source_path": "model_benchmark/runtime/hermes_launch.py",
        },
        "native_behavior": {
            "compaction": "stock",
            "planning": "stock",
            "retries": "stock",
            "tools": "stock",
        },
        "provision": {
            "image_bytes": HERMES_IMAGE_BYTES,
            "image_id": HERMES_IMAGE_ID,
            "image_identity": HERMES_IMAGE_IDENTITY,
            "image_reference": HERMES_IMAGE_REFERENCE,
            "network": "provision-only",
            "operation": "pull-exact-image-verify-commit-extract-executable",
            "release_tag": HERMES_RELEASE_TAG,
        },
        "rules_memory_skills_injection": False,
        "runtime_installation": False,
        "session_persistence": False,
        "shutdown": "process-exit-then-process-group-teardown",
    }


def load_hermes_condition_lock() -> tuple[bytes, Mapping[str, object], TypedDigest]:
    return load_condition_lock(
        hermes_condition_lock_path, label="Hermes", verify=_verify_lock_dependencies
    )


def validate_hermes_condition_lock(data: bytes) -> TypedDigest:
    return validate_condition_lock(
        load_hermes_condition_lock,
        data,
        mismatch_message="Hermes condition lock differs from the qualified v0.18.2 lock",
    )


def _verify_lock_dependencies(lock: dict[str, object]) -> None:
    verify_lock_declaration(
        lock,
        condition="hermes",
        artifact_identity=HERMES_ARTIFACT_IDENTITY,
        configuration=_locked_configuration(),
        environment_names=HERMES_ENVIRONMENT_NAMES,
        shim_identity=HERMES_SHIM_IDENTITY,
        profile_data=standard_profile_path().read_bytes(),
        shim_data=hermes_launch_shim_path().read_bytes(),
        structure_message="Hermes lock structure is invalid",
        mismatch_message="Hermes v0.18.2 artifact, profile, or adapter declaration does not match",
    )


def _container_runtime_path() -> Path:
    runtime = shutil.which("docker")
    if runtime is None:
        raise ConditionAdapterError(
            "condition-unqualified",
            "Docker is unavailable for the pinned Hermes image",
        )
    path = Path(runtime).absolute()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ConditionAdapterError(
            "condition-unqualified",
            "Docker is not an executable regular file",
        )
    return path


def _provisioning_manifest(
    *, condition_identity: str, shim_bytes: int, image: dict[str, object]
) -> dict[str, object]:
    return {
        "artifact": {
            "bytes": HERMES_ARTIFACT_BYTES,
            "container_path": HERMES_ARTIFACT_CONTAINER_PATH,
            "identity": HERMES_ARTIFACT_IDENTITY,
            "path": cache_relative_path(
                "artifacts", HERMES_ARTIFACT_IDENTITY, "hermes"
            ).as_posix(),
        },
        "condition_identity": condition_identity,
        "image": image,
        "launch_shim": {
            "bytes": shim_bytes,
            "identity": HERMES_SHIM_IDENTITY,
            "path": cache_relative_path(
                "adapters", HERMES_SHIM_IDENTITY, "hermes-launch"
            ).as_posix(),
        },
        "network": "provision-only",
        "schema_version": 1,
    }


def provision_hermes(cache_root: Path, condition_lock: bytes) -> HermesProvisioning:
    condition_identity = validate_hermes_condition_lock(condition_lock)
    root = cache_root / "hermes" / condition_identity.value
    manifest_path = root / "provisioning.json"
    if manifest_path.exists() or manifest_path.is_symlink():
        return preflight_hermes(cache_root, condition_lock)

    artifact_path = cache_root / cache_relative_path(
        "artifacts", HERMES_ARTIFACT_IDENTITY, "hermes"
    )
    shim_path = cache_root / cache_relative_path(
        "adapters", HERMES_SHIM_IDENTITY, "hermes-launch"
    )
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    artifact_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    shim_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    image = _ensure_image(pull=True)
    if artifact_path.exists() or artifact_path.is_symlink():
        _verify_file(
            artifact_path,
            HERMES_ARTIFACT_IDENTITY,
            HERMES_ARTIFACT_BYTES,
            label="executable",
        )
    else:
        _extract_artifact(artifact_path)
    shim_data = hermes_launch_shim_path().read_bytes()
    ensure_launch_shim(
        shim_path,
        shim_data,
        identity=HERMES_SHIM_IDENTITY,
        condition="Hermes",
        label="launch shim",
    )
    publish_bytes(
        manifest_path,
        canonical_json_bytes(
            _provisioning_manifest(
                condition_identity=str(condition_identity),
                shim_bytes=len(shim_data),
                image=image,
            )
        ),
        mode=0o400,
        condition="Hermes",
    )
    return preflight_hermes(cache_root, condition_lock)


def preflight_hermes(cache_root: Path, condition_lock: bytes) -> HermesProvisioning:
    condition_identity = validate_hermes_condition_lock(condition_lock)
    container_runtime_path = _container_runtime_path()
    manifest_path = (
        cache_root / "hermes" / condition_identity.value / "provisioning.json"
    )
    shim_data = hermes_launch_shim_path().read_bytes()
    image = _ensure_image(pull=False)
    check_provisioning_manifest(
        manifest_path,
        _provisioning_manifest(
            condition_identity=str(condition_identity),
            shim_bytes=len(shim_data),
            image=image,
        ),
        condition="Hermes",
    )
    artifact_path = cache_root / cache_relative_path(
        "artifacts", HERMES_ARTIFACT_IDENTITY, "hermes"
    )
    launch_shim_path = cache_root / cache_relative_path(
        "adapters", HERMES_SHIM_IDENTITY, "hermes-launch"
    )
    _verify_file(
        artifact_path,
        HERMES_ARTIFACT_IDENTITY,
        HERMES_ARTIFACT_BYTES,
        label="executable",
    )
    _verify_file(
        launch_shim_path,
        HERMES_SHIM_IDENTITY,
        len(shim_data),
        label="launch shim",
    )
    return HermesProvisioning(
        condition_identity=str(condition_identity),
        image_reference=HERMES_IMAGE_REFERENCE,
        image_identity=HERMES_IMAGE_IDENTITY,
        image_id=HERMES_IMAGE_ID,
        container_runtime_path=container_runtime_path,
        artifact_path=artifact_path,
        artifact_identity=HERMES_ARTIFACT_IDENTITY,
        launch_shim_path=launch_shim_path,
        launch_shim_identity=HERMES_SHIM_IDENTITY,
        manifest_path=manifest_path,
    )


def sealed_hermes_process(
    provisioning: HermesProvisioning,
    *,
    proxy_base_url: str,
    provider_model: str,
    trial_proxy_token: str,
) -> SealedConditionProcess:
    _, lock, condition_identity = load_hermes_condition_lock()
    artifact = lock.get("artifact")
    adapter = lock.get("adapter")
    configuration = adapter.get("configuration") if isinstance(adapter, dict) else None
    shim = configuration.get("launch_shim") if isinstance(configuration, dict) else None
    provision = configuration.get("provision") if isinstance(configuration, dict) else None
    if (
        not isinstance(artifact, dict)
        or not isinstance(configuration, dict)
        or not isinstance(shim, dict)
        or not isinstance(provision, dict)
        or provisioning.condition_identity != str(condition_identity)
        or provisioning.image_reference != provision.get("image_reference")
        or provisioning.image_identity != provision.get("image_identity")
        or provisioning.image_id != provision.get("image_id")
        or not provisioning.container_runtime_path.is_file()
        or not os.access(provisioning.container_runtime_path, os.X_OK)
        or provisioning.artifact_identity != artifact.get("digest")
        or provisioning.launch_shim_identity != shim.get("digest")
    ):
        raise ConditionAdapterError(
            "condition-unqualified",
            "measured Hermes launch does not match the sealed condition",
        )
    artifact_bytes = configuration.get("artifact_bytes")
    if not isinstance(artifact_bytes, int) or isinstance(artifact_bytes, bool):
        raise ConditionAdapterError(
            "condition-unqualified",
            "sealed Hermes artifact size is invalid",
        )
    _verify_file(
        provisioning.artifact_path,
        provisioning.artifact_identity,
        artifact_bytes,
        label="executable",
    )
    _verify_file(
        provisioning.launch_shim_path,
        provisioning.launch_shim_identity,
        len(hermes_launch_shim_path().read_bytes()),
        label="launch shim",
    )
    validate_sealed_launch_inputs(
        condition="Hermes",
        proxy_base_url=proxy_base_url,
        provider_model=provider_model,
        trial_proxy_token=trial_proxy_token,
    )
    return SealedConditionProcess(
        condition="hermes",
        artifact_path=provisioning.launch_shim_path,
        artifact_identity=provisioning.launch_shim_identity,
        arguments=(
            "--docker",
            str(provisioning.container_runtime_path),
            "--hermes",
            str(provisioning.artifact_path),
            "--artifact-identity",
            provisioning.artifact_identity,
            "--artifact-container-path",
            HERMES_ARTIFACT_CONTAINER_PATH,
            "--image-reference",
            provisioning.image_reference,
            "--image-identity",
            provisioning.image_identity,
        ),
        environment=harness_environment(
            provider_model=provider_model,
            proxy_base_url=proxy_base_url,
            trial_proxy_token=trial_proxy_token,
        ),
        native_artifact_paths=_NATIVE_ARTIFACT_PATHS,
    )


def evaluate_hermes_qualification(
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
        prefix="hermes",
        run_failure_reason="hermes-oneshot-unsupported",
        required_artifacts=frozenset(_NATIVE_ARTIFACT_PATHS),
        expected_brief_sha256=expected_brief_sha256,
        observed_brief_sha256=observed_brief_sha256,
        workspace_verified=workspace_verified,
        unexpected_network_requests=unexpected_network_requests,
    )


def _docker(
    arguments: list[str],
    *,
    timeout: int = 30,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            ["docker", *arguments],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ConditionAdapterError("provisioning-runtime-failed", str(error)) from error
    if check and completed.returncode != 0:
        detail = (completed.stderr.strip() or completed.stdout.strip())[-2000:]
        raise ConditionAdapterError(
            "provisioning-runtime-failed",
            f"Docker command failed ({completed.returncode}): {detail}",
        )
    return completed


def _inspect_image() -> dict[str, object] | None:
    completed = _docker(
        ["image", "inspect", HERMES_IMAGE_REFERENCE, "--format", "{{json .}}"],
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr + completed.stdout).lower()
        if "no such image" in detail or "no such object" in detail:
            return None
        raise ConditionAdapterError(
            "provisioning-runtime-failed",
            (completed.stderr.strip() or completed.stdout.strip())[-2000:],
        )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ConditionAdapterError(
            "provisioning-runtime-failed",
            "Hermes image inspection is invalid",
        ) from error
    if not isinstance(value, dict):
        raise ConditionAdapterError(
            "provisioning-runtime-failed",
            "Hermes image inspection is not an object",
        )
    config = value.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    environment = config.get("Env") if isinstance(config, dict) else None
    repo_digests = value.get("RepoDigests")
    expected_repo_digest = HERMES_IMAGE_REFERENCE
    if (
        value.get("Architecture") != "amd64"
        or value.get("Os") != "linux"
        or value.get("Id") != HERMES_IMAGE_ID
        or not isinstance(repo_digests, list)
        or expected_repo_digest not in repo_digests
        or not isinstance(labels, dict)
        or labels.get("org.opencontainers.image.revision") != HERMES_RELEASE_COMMIT
        or not isinstance(environment, list)
        or "HERMES_DISABLE_LAZY_INSTALLS=1" not in environment
    ):
        raise ConditionAdapterError(
            "condition-unqualified",
            "local Hermes image does not match the sealed Linux/amd64 release",
        )
    return {
        "architecture": "amd64",
        "bytes": HERMES_IMAGE_BYTES,
        "id": HERMES_IMAGE_ID,
        "identity": HERMES_IMAGE_IDENTITY,
        "os": "linux",
        "reference": HERMES_IMAGE_REFERENCE,
        "release_commit": HERMES_RELEASE_COMMIT,
        "release_tag": HERMES_RELEASE_TAG,
    }


def _ensure_image(*, pull: bool) -> dict[str, object]:
    image = _inspect_image()
    if image is None and pull:
        _docker(
            ["pull", "--platform", "linux/amd64", HERMES_IMAGE_REFERENCE],
            timeout=600,
        )
        image = _inspect_image()
    if image is None:
        raise ConditionAdapterError(
            "condition-unqualified",
            "exact Hermes Linux/amd64 image is absent from the local cache",
        )
    return image


def _extract_artifact(destination: Path) -> None:
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    container_id = ""
    try:
        created = _docker(
            ["create", "--platform", "linux/amd64", HERMES_IMAGE_REFERENCE]
        )
        container_id = created.stdout.strip()
        if not container_id:
            raise ConditionAdapterError(
                "artifact-verification-failed",
                "Docker did not return a Hermes extraction container identity",
            )
        _docker(["cp", f"{container_id}:{HERMES_ARTIFACT_CONTAINER_PATH}", str(temporary)])
        temporary.chmod(0o555)
        _verify_file(
            temporary,
            HERMES_ARTIFACT_IDENTITY,
            HERMES_ARTIFACT_BYTES,
            label="executable",
        )
        os.link(temporary, destination)
    except FileExistsError:
        _verify_file(
            destination,
            HERMES_ARTIFACT_IDENTITY,
            HERMES_ARTIFACT_BYTES,
            label="executable",
        )
    finally:
        if container_id:
            _docker(["rm", "-f", container_id], check=False)
        temporary.unlink(missing_ok=True)


def _verify_file(path: Path, identity: str, expected_size: int, *, label: str) -> None:
    verify_cached_file(path, identity, expected_size, condition="Hermes", label=label)

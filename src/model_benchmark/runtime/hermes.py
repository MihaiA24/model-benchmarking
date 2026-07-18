from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
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
_QUALIFIED = "qualified"


class HermesConditionError(RuntimeError):
    """The pinned Hermes condition cannot be provisioned or qualified safely."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


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


@dataclass(frozen=True)
class HermesQualification:
    qualified: bool
    reason_code: str
    evidence: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", MappingProxyType(dict(self.evidence)))


def hermes_condition_lock_path() -> Path:
    path = (
        project_resource_root("profiles", "published_profiles")
        / "functional-v1"
        / "hermes-v0.18.2.condition.json"
    )
    if not path.is_file():
        raise HermesConditionError(
            "condition-lock-unavailable",
            "Hermes condition lock is unavailable",
        )
    return path


def hermes_launch_shim_path() -> Path:
    path = Path(__file__).with_name("hermes_launch.py")
    if not path.is_file():
        raise HermesConditionError(
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
    try:
        data = hermes_condition_lock_path().read_bytes()
        value = load_canonical_json(data)
    except (OSError, CanonicalizationError) as error:
        raise HermesConditionError("invalid-condition-lock", str(error)) from error
    if not isinstance(value, dict):
        raise HermesConditionError(
            "invalid-condition-lock",
            "Hermes condition lock is not an object",
        )
    _verify_lock_dependencies(value)
    identity = TypedDigest.from_bytes(DigestKind.FUNCTIONAL_V1_CONDITION, data)
    return data, MappingProxyType(value), identity


def validate_hermes_condition_lock(data: bytes) -> TypedDigest:
    expected, _, identity = load_hermes_condition_lock()
    if data != expected:
        raise HermesConditionError(
            "condition-unqualified",
            "Hermes condition lock differs from the qualified v0.18.2 lock",
        )
    return identity


def _verify_lock_dependencies(lock: dict[str, object]) -> None:
    artifact = lock.get("artifact")
    adapter = lock.get("adapter")
    if not isinstance(artifact, dict) or not isinstance(adapter, dict):
        raise HermesConditionError(
            "invalid-condition-lock",
            "Hermes lock structure is invalid",
        )
    expected_profile = TypedDigest.from_bytes(
        DigestKind.EXECUTION_PROFILE,
        standard_profile_path().read_bytes(),
    )
    expected_shim = TypedDigest.from_bytes(
        DigestKind.ARTIFACT,
        hermes_launch_shim_path().read_bytes(),
    )
    if (
        lock.get("schema_version") != 1
        or lock.get("condition") != "hermes"
        or lock.get("execution_profile") != str(expected_profile)
        or artifact
        != {
            "digest": HERMES_ARTIFACT_IDENTITY,
            "kind": "native-executable",
            "platform": "linux/amd64",
        }
        or adapter.get("argv")
        != [
            "/opt/model-benchmark-condition/entrypoint",
            "--condition",
            "hermes",
            "--artifact-identity",
            "{artifact_identity}",
        ]
        or adapter.get("configuration") != _locked_configuration()
        or adapter.get("environment_names") != list(HERMES_ENVIRONMENT_NAMES)
        or adapter.get("non_interactive") is not True
        or adapter.get("self_update") is not False
        or adapter.get("working_directory") != "/workspace"
        or str(expected_shim) != HERMES_SHIM_IDENTITY
    ):
        raise HermesConditionError(
            "invalid-condition-lock",
            "Hermes v0.18.2 artifact, profile, or adapter declaration does not match",
        )


def _container_runtime_path() -> Path:
    runtime = shutil.which("docker")
    if runtime is None:
        raise HermesConditionError(
            "condition-unqualified",
            "Docker is unavailable for the pinned Hermes image",
        )
    path = Path(runtime).absolute()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise HermesConditionError(
            "condition-unqualified",
            "Docker is not an executable regular file",
        )
    return path


def provision_hermes(cache_root: Path, condition_lock: bytes) -> HermesProvisioning:
    condition_identity = validate_hermes_condition_lock(condition_lock)
    root = cache_root / "hermes" / condition_identity.value
    manifest_path = root / "provisioning.json"
    if manifest_path.exists() or manifest_path.is_symlink():
        return preflight_hermes(cache_root, condition_lock)

    artifact_relative = (
        Path("artifacts") / HERMES_ARTIFACT_IDENTITY.rsplit(":", 1)[1] / "hermes"
    )
    shim_relative = (
        Path("adapters") / HERMES_SHIM_IDENTITY.rsplit(":", 1)[1] / "hermes-launch"
    )
    artifact_path = cache_root / artifact_relative
    shim_path = cache_root / shim_relative
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
    if shim_path.exists() or shim_path.is_symlink():
        _verify_file(
            shim_path,
            HERMES_SHIM_IDENTITY,
            len(shim_data),
            label="launch shim",
        )
    else:
        _publish_bytes(shim_path, shim_data, mode=0o555)
        _verify_file(
            shim_path,
            HERMES_SHIM_IDENTITY,
            len(shim_data),
            label="launch shim",
        )

    manifest = _provisioning_manifest(
        condition_identity=str(condition_identity),
        artifact_relative=artifact_relative,
        shim_relative=shim_relative,
        shim_bytes=len(shim_data),
        image=image,
    )
    _publish_bytes(manifest_path, canonical_json_bytes(manifest), mode=0o400)
    return preflight_hermes(cache_root, condition_lock)


def preflight_hermes(cache_root: Path, condition_lock: bytes) -> HermesProvisioning:
    condition_identity = validate_hermes_condition_lock(condition_lock)
    container_runtime_path = _container_runtime_path()
    root = cache_root / "hermes" / condition_identity.value
    manifest_path = root / "provisioning.json"
    try:
        manifest = load_canonical_json(_read_regular_file(manifest_path))
    except (OSError, CanonicalizationError) as error:
        raise HermesConditionError(
            "condition-unqualified",
            f"Hermes provisioning manifest is unavailable or invalid: {error}",
        ) from error
    artifact_relative = (
        Path("artifacts") / HERMES_ARTIFACT_IDENTITY.rsplit(":", 1)[1] / "hermes"
    )
    shim_relative = (
        Path("adapters") / HERMES_SHIM_IDENTITY.rsplit(":", 1)[1] / "hermes-launch"
    )
    shim_data = hermes_launch_shim_path().read_bytes()
    image = _ensure_image(pull=False)
    expected = _provisioning_manifest(
        condition_identity=str(condition_identity),
        artifact_relative=artifact_relative,
        shim_relative=shim_relative,
        shim_bytes=len(shim_data),
        image=image,
    )
    if manifest != expected:
        raise HermesConditionError(
            "condition-unqualified",
            "Hermes provisioning manifest does not match the sealed condition",
        )
    artifact_path = cache_root / artifact_relative
    launch_shim_path = cache_root / shim_relative
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


def _provisioning_manifest(
    *,
    condition_identity: str,
    artifact_relative: Path,
    shim_relative: Path,
    shim_bytes: int,
    image: dict[str, object],
) -> dict[str, object]:
    return {
        "artifact": {
            "bytes": HERMES_ARTIFACT_BYTES,
            "container_path": HERMES_ARTIFACT_CONTAINER_PATH,
            "identity": HERMES_ARTIFACT_IDENTITY,
            "path": artifact_relative.as_posix(),
        },
        "condition_identity": condition_identity,
        "image": image,
        "launch_shim": {
            "bytes": shim_bytes,
            "identity": HERMES_SHIM_IDENTITY,
            "path": shim_relative.as_posix(),
        },
        "network": "provision-only",
        "schema_version": 1,
    }


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
        raise HermesConditionError(
            "condition-unqualified",
            "measured Hermes launch does not match the sealed condition",
        )
    artifact_bytes = configuration.get("artifact_bytes")
    if not isinstance(artifact_bytes, int) or isinstance(artifact_bytes, bool):
        raise HermesConditionError(
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
        raise HermesConditionError(
            "condition-unqualified",
            "Hermes must receive one canonical internal HTTP Credential Proxy route",
        )
    if not provider_model or any(ord(character) < 32 for character in provider_model):
        raise HermesConditionError(
            "condition-unqualified",
            "Hermes provider model is invalid",
        )
    if not trial_proxy_token or any(
        character in trial_proxy_token for character in "\r\n\x00"
    ):
        raise HermesConditionError(
            "condition-unqualified",
            "Hermes proxy token is invalid",
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
        environment={
            "MODEL_BENCHMARK_PROVIDER_MODEL": provider_model,
            "MODEL_BENCHMARK_PROXY_BASE_URL": proxy_base_url,
            TRIAL_PROXY_TOKEN_ENV: trial_proxy_token,
        },
        native_artifact_paths=(
            "home/.hermes/logs/agent.log",
            "home/.hermes/state.db",
            "home/.model-benchmark/hermes-delivery.json",
            "home/.model-benchmark/hermes-usage.json",
        ),
    )


def evaluate_hermes_qualification(
    result: ConditionProcessResult,
    proxy_evidence_path: Path,
    *,
    expected_brief_sha256: str,
    observed_brief_sha256: str,
    workspace_verified: bool,
    unexpected_network_requests: int,
) -> HermesQualification:
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
        reason_code = "hermes-oneshot-unsupported"
    elif not result.process_tree_terminated:
        reason_code = "hermes-process-tree-incomplete"
    elif not {
        "home/.hermes/logs/agent.log",
        "home/.hermes/state.db",
        "home/.model-benchmark/hermes-delivery.json",
        "home/.model-benchmark/hermes-usage.json",
    }.issubset(result.artifact_digests):
        reason_code = "hermes-native-artifact-missing"
    elif expected_brief_sha256 != observed_brief_sha256:
        reason_code = "hermes-developer-brief-mismatch"
    elif not workspace_verified:
        reason_code = "hermes-workspace-mismatch"
    elif unexpected_network_requests != 0:
        reason_code = "hermes-unexpected-network"

    provider_events = _provider_events(proxy_evidence_path)
    evidence["provider_response_count"] = len(provider_events)
    if reason_code is None and not provider_events:
        reason_code = "hermes-provider-evidence-missing"
    if reason_code is None and any(
        event.get("reason_code") is not None
        or not isinstance(event.get("provider_model"), str)
        or not isinstance(event.get("provider_tokens"), int)
        or isinstance(event.get("provider_tokens"), bool)
        or event.get("provider_cost_usd") is None
        for event in provider_events
    ):
        reason_code = "hermes-provider-contract-violation"

    return HermesQualification(
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
        raise HermesConditionError("provisioning-runtime-failed", str(error)) from error
    if check and completed.returncode != 0:
        detail = (completed.stderr.strip() or completed.stdout.strip())[-2000:]
        raise HermesConditionError(
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
        raise HermesConditionError(
            "provisioning-runtime-failed",
            (completed.stderr.strip() or completed.stdout.strip())[-2000:],
        )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise HermesConditionError(
            "provisioning-runtime-failed",
            "Hermes image inspection is invalid",
        ) from error
    if not isinstance(value, dict):
        raise HermesConditionError(
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
        raise HermesConditionError(
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
        raise HermesConditionError(
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
            raise HermesConditionError(
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
            raise HermesConditionError(
                "immutable-cache-conflict",
                f"immutable Hermes cache path changed: {destination.name}",
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


def _verify_file(path: Path, identity: str, expected_size: int, *, label: str) -> None:
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
        raise HermesConditionError(
            "condition-unqualified",
            f"Hermes cached {label} is unavailable: {error}",
        ) from error
    if f"artifact:sha256:{digest.hexdigest()}" != identity:
        raise HermesConditionError(
            "condition-unqualified",
            f"Hermes cached {label} identity mismatch",
        )

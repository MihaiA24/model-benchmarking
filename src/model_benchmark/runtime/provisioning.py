from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import tomllib
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

import yaml

from model_benchmark.declarations.canonical import canonical_json_bytes
from model_benchmark.declarations.identities import DigestKind, TypedDigest
from model_benchmark.declarations.scenario_locks import HARBOR_COMMIT, schema_root_path
from model_benchmark.declarations.schemas import SchemaRegistry, SchemaValidationError
from model_benchmark.declarations.scenarios import (
    ScenarioPackageError,
    _harbor_probe,
    _immutable_verified_write,
    check_scenario_package,
)


_MANIFEST_SCHEMA_NAME = "model-benchmark/provisioning-manifest"
_SCHEMA_VERSION = 1
_PLATFORM = re.compile(r"^(linux|windows)/(amd64|arm64)(?:/[A-Za-z0-9._-]+)?$")
_HARBOR_KERNEL_PROBE = (
    "alpine:3.23.4@sha256:"
    "5b10f432ef3da1b8d4c7eb6c487f2f5a8f096bc91145e68878dd4a5019afde11"
)
_HARBOR_EGRESS_IMAGE = "harbor-prebuilt:harbor-docker-egress-control-sidecar"


@dataclass(frozen=True)
class DockerTarget:
    context: str
    platform: str

    @property
    def os(self) -> str:
        return self.platform.split("/", 1)[0]

    @property
    def architecture(self) -> str:
        return self.platform.split("/")[1]

    @property
    def variant(self) -> str | None:
        parts = self.platform.split("/")
        return parts[2] if len(parts) == 3 else None


@dataclass(frozen=True)
class StoreLease:
    target: DockerTarget
    visibility_domain: str
    store: dict[str, str]


def _artifact_digest(value: object) -> str:
    return str(TypedDigest.from_bytes(DigestKind.ARTIFACT, canonical_json_bytes(value)))


def _canonical_repo_digest(reference: str) -> str:
    name, digest = reference.rsplit("@", 1)
    slash = name.rfind("/")
    colon = name.rfind(":")
    repository = name[:colon] if colon > slash else name
    return f"{repository}@{digest}"


def _docker(
    arguments: list[str],
    *,
    timeout: int = 30,
    check: bool = True,
    context: str | None = None,
) -> subprocess.CompletedProcess[str]:
    command = ["docker"]
    if context is not None:
        command.extend(["--context", context])
    command.extend(arguments)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ScenarioPackageError("provisioning-runtime-failed", str(error)) from error
    if check and completed.returncode != 0:
        detail = (completed.stderr.strip() or completed.stdout.strip())[-2000:]
        raise ScenarioPackageError(
            "provisioning-runtime-failed",
            f"Docker command failed ({completed.returncode}): {detail}",
        )
    return completed


def _json_output(completed: subprocess.CompletedProcess[str], *, label: str) -> Any:
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ScenarioPackageError(
            "provisioning-runtime-failed", f"invalid {label}"
        ) from error


def load_target_config(path: Path, *, visibility: str) -> DockerTarget:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ScenarioPackageError("invalid-provisioning-target", str(error)) from error
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "visibility_domains",
    }:
        raise ScenarioPackageError(
            "invalid-provisioning-target",
            "target config must contain schema_version and visibility_domains",
        )
    domains = value["visibility_domains"]
    if (
        value["schema_version"] != 1
        or not isinstance(domains, dict)
        or set(domains) != {"public", "private"}
    ):
        raise ScenarioPackageError(
            "invalid-provisioning-target",
            "target config must map exactly public and private visibility domains",
        )
    parsed: dict[str, DockerTarget] = {}
    for domain, target in domains.items():
        if not isinstance(target, dict) or set(target) != {
            "docker_context",
            "platform",
        }:
            raise ScenarioPackageError(
                "invalid-provisioning-target",
                f"target for {domain} must contain docker_context and platform",
            )
        context = target["docker_context"]
        platform = target["platform"]
        if (
            not isinstance(context, str)
            or not context
            or any(character.isspace() for character in context)
            or not isinstance(platform, str)
            or _PLATFORM.fullmatch(platform) is None
        ):
            raise ScenarioPackageError(
                "invalid-provisioning-target",
                f"invalid Docker context or target platform for {domain}",
            )
        parsed[domain] = DockerTarget(context=context, platform=platform)
    if parsed["public"].context == parsed["private"].context:
        raise ScenarioPackageError(
            "invalid-provisioning-target",
            "public and private visibility require separate Docker contexts",
        )
    return parsed[visibility]


def _inspect_store(target: DockerTarget) -> dict[str, str]:
    contexts = _json_output(
        _docker(["context", "inspect", target.context]),
        label="Docker context inspection",
    )
    info = _json_output(
        _docker(["info", "--format", "{{json .}}"], context=target.context),
        label="Docker daemon inspection",
    )
    if (
        not isinstance(contexts, list)
        or len(contexts) != 1
        or not isinstance(contexts[0], dict)
        or not isinstance(info, dict)
    ):
        raise ScenarioPackageError(
            "provisioning-target-mismatch", "Docker target inspection is malformed"
        )
    endpoint = contexts[0].get("Endpoints")
    docker_endpoint = endpoint.get("docker") if isinstance(endpoint, dict) else None
    host = docker_endpoint.get("Host") if isinstance(docker_endpoint, dict) else None
    fields = {
        "daemon_id": info.get("ID"),
        "docker_context": target.context,
        "docker_root_dir": info.get("DockerRootDir"),
        "endpoint": host,
        "server_version": info.get("ServerVersion"),
    }
    if any(not isinstance(value, str) or not value for value in fields.values()):
        raise ScenarioPackageError(
            "provisioning-target-mismatch", "Docker target identity is incomplete"
        )
    daemon_os = info.get("OSType")
    daemon_arch = info.get("Architecture")
    normalized_arch = {"aarch64": "arm64", "x86_64": "amd64"}.get(
        daemon_arch, daemon_arch
    )
    if daemon_os != target.os or normalized_arch != target.architecture:
        raise ScenarioPackageError(
            "provisioning-target-mismatch",
            f"Docker daemon platform {daemon_os}/{normalized_arch} does not match {target.platform}",
        )
    physical_identity = {
        "daemon_id": fields["daemon_id"],
        "docker_root_dir": fields["docker_root_dir"],
    }
    return {
        "docker_context": target.context,
        "platform": target.platform,
        "server_version": fields["server_version"],
        "store_identity": _artifact_digest(physical_identity),
    }


@contextmanager
def acquire_store_lease(
    target: DockerTarget, *, visibility: str
) -> Iterator[StoreLease]:
    store = _inspect_store(target)
    root = (
        Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        / "model-benchmark"
        / "provisioning-locks"
    )
    root.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(store["store_identity"].encode()).hexdigest()
    with (root / f"{key}.lock").open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            if _inspect_store(target) != store:
                raise ScenarioPackageError(
                    "provisioning-target-mismatch",
                    "Docker target changed while acquiring the provisioning lock",
                )
            binding = root / f"{key}.visibility"
            if binding.exists():
                try:
                    bound_visibility = binding.read_text(encoding="utf-8").strip()
                except OSError as error:
                    raise ScenarioPackageError(
                        "provisioning-target-mismatch", str(error)
                    ) from error
                if bound_visibility != visibility:
                    raise ScenarioPackageError(
                        "provisioning-target-mismatch",
                        "Docker store is already bound to another visibility domain",
                    )
            else:
                _immutable_verified_write(binding, visibility.encode("utf-8") + b"\n")
            yield StoreLease(target=target, visibility_domain=visibility, store=store)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def acquire_store_read_lease(
    target: DockerTarget, *, visibility: str
) -> Iterator[StoreLease]:
    store = _inspect_store(target)
    root = (
        Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        / "model-benchmark"
        / "provisioning-locks"
    )
    key = hashlib.sha256(store["store_identity"].encode()).hexdigest()
    lock_path = root / f"{key}.lock"
    binding = root / f"{key}.visibility"
    if not lock_path.is_file() or not binding.is_file():
        raise ScenarioPackageError(
            "preflight-store-mismatch",
            "Docker store has no sealed provisioning lease metadata",
        )
    try:
        with lock_path.open("rb") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
            try:
                if _inspect_store(target) != store:
                    raise ScenarioPackageError(
                        "preflight-store-mismatch",
                        "Docker target changed while acquiring the read lease",
                    )
                if binding.read_text(encoding="utf-8").strip() != visibility:
                    raise ScenarioPackageError(
                        "preflight-store-mismatch",
                        "Docker store visibility binding does not match",
                    )
                yield StoreLease(
                    target=target, visibility_domain=visibility, store=store
                )
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError as error:
        raise ScenarioPackageError("preflight-store-mismatch", str(error)) from error


def _image_record(target: DockerTarget, reference: str) -> dict[str, object] | None:
    completed = _docker(
        ["image", "inspect", reference], check=False, context=target.context
    )
    if completed.returncode != 0:
        detail = (completed.stderr + completed.stdout).lower()
        if "no such image" in detail or "no such object" in detail:
            return None
        raise ScenarioPackageError(
            "provisioning-runtime-failed",
            (completed.stderr.strip() or completed.stdout.strip())[-2000:],
        )
    values = _json_output(completed, label="Docker image inspection")
    if (
        not isinstance(values, list)
        or len(values) != 1
        or not isinstance(values[0], dict)
    ):
        raise ScenarioPackageError(
            "provisioning-runtime-failed", "Docker image inspection is malformed"
        )
    value = values[0]
    architecture = {"aarch64": "arm64", "x86_64": "amd64"}.get(
        value.get("Architecture"), value.get("Architecture")
    )
    variant = value.get("Variant") or None
    if (
        value.get("Os") != target.os
        or architecture != target.architecture
        or (target.variant is not None and variant != target.variant)
    ):
        raise ScenarioPackageError(
            "provisioning-platform-mismatch",
            f"image {reference} does not match target platform {target.platform}",
        )
    image_id = value.get("Id")
    layers = (
        value.get("RootFS", {}).get("Layers")
        if isinstance(value.get("RootFS"), dict)
        else None
    )
    repo_digests = value.get("RepoDigests") or []
    labels = (
        value.get("Config", {}).get("Labels")
        if isinstance(value.get("Config"), dict)
        else None
    )
    if (
        not isinstance(image_id, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None
        or not isinstance(layers, list)
        or not layers
        or any(
            re.fullmatch(r"sha256:[0-9a-f]{64}", layer or "") is None
            for layer in layers
        )
        or not isinstance(repo_digests, list)
        or any(not isinstance(item, str) for item in repo_digests)
        or labels is not None
        and not isinstance(labels, dict)
    ):
        raise ScenarioPackageError(
            "provisioning-runtime-failed",
            f"image {reference} has incomplete identity metadata",
        )
    record: dict[str, object] = {
        "architecture": architecture,
        "id": image_id,
        "layers": layers,
        "os": value["Os"],
        "repo_digests": sorted(repo_digests),
        "variant": variant,
    }
    record["content_identity"] = _artifact_digest(record)
    record["labels"] = labels or {}
    return record


def locked_image_requests(lock: dict[str, Any]) -> list[dict[str, str]]:
    requests = [dict(item) for item in lock["resolved_inputs"]["images"]]
    kernel_reference = harbor_kernel_probe_reference()
    requests.append(
        {
            "identity": str(
                TypedDigest(
                    DigestKind.OCI_IMAGE, kernel_reference.rsplit("sha256:", 1)[1]
                )
            ),
            "reference": kernel_reference,
        }
    )
    return sorted(requests, key=lambda item: item["reference"])


def ensure_locked_images(
    lease: StoreLease,
    locked_images: list[dict[str, str]],
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for locked in sorted(locked_images, key=lambda item: item["reference"]):
        reference = locked["reference"]
        image = _image_record(lease.target, reference)
        cache = "hit"
        if image is None:
            cache = "miss"
            _docker(
                ["pull", "--platform", lease.target.platform, reference],
                timeout=600,
                context=lease.target.context,
            )
            image = _image_record(lease.target, reference)
        if (
            image is None
            or _canonical_repo_digest(reference) not in image["repo_digests"]
        ):
            raise ScenarioPackageError(
                "provisioning-digest-mismatch",
                f"Docker cache does not expose the exact locked digest {reference}",
            )
        image.pop("labels", None)
        records.append(
            {
                "cache": cache,
                "image": image,
                "locked_identity": locked["identity"],
                "reference": reference,
            }
        )
    return records


def remove_project_images(lease: StoreLease, projects: set[str]) -> None:
    for project in sorted(projects):
        completed = _docker(
            [
                "image",
                "ls",
                "--no-trunc",
                "--quiet",
                "--filter",
                f"label=com.docker.compose.project={project}",
            ],
            check=False,
            context=lease.target.context,
        )
        for image_id in sorted(set(completed.stdout.splitlines())):
            if not image_id:
                continue
            tags = _docker(
                ["image", "inspect", image_id, "--format", "{{json .RepoTags}}"],
                check=False,
                context=lease.target.context,
            )
            if tags.returncode != 0:
                continue
            try:
                references = json.loads(tags.stdout) or []
            except json.JSONDecodeError:
                continue
            for reference in references:
                if isinstance(reference, str):
                    _docker(
                        ["image", "rm", reference],
                        check=False,
                        context=lease.target.context,
                    )


def project_runtime_images(
    lease: StoreLease,
    *,
    project: str,
    package: Path,
) -> list[dict[str, object]]:
    completed = _docker(
        [
            "image",
            "ls",
            "--no-trunc",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={project}",
        ],
        context=lease.target.context,
    )
    by_role: dict[str, dict[str, object]] = {}
    for image_id in sorted(set(completed.stdout.splitlines())):
        if not image_id:
            continue
        image = _image_record(lease.target, image_id)
        if image is None:
            continue
        labels = image.pop("labels")
        role = (
            labels.get("com.docker.compose.service")
            if isinstance(labels, dict)
            else None
        )
        if role in {"main", "capture"}:
            by_role["agent" if role == "main" else "capture"] = image
    if set(by_role) != {"agent", "capture"}:
        raise ScenarioPackageError(
            "provisioning-runtime-failed",
            "Harbor provisioning did not retain exact agent and capture images",
        )
    return [
        {
            "build_input_sha256": build_input_digest(package, role=role),
            "execution_reference": None,
            "image": by_role[role],
            "role": role,
        }
        for role in ("agent", "capture")
    ]


def project_single_runtime_image(
    lease: StoreLease,
    *,
    project: str,
    package: Path,
) -> dict[str, object]:
    completed = _docker(
        [
            "image",
            "ls",
            "--no-trunc",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={project}",
        ],
        context=lease.target.context,
    )
    images: list[dict[str, object]] = []
    for image_id in sorted(set(completed.stdout.splitlines())):
        if not image_id:
            continue
        image = _image_record(lease.target, image_id)
        if image is None:
            continue
        labels = image.pop("labels")
        if (
            isinstance(labels, dict)
            and labels.get("com.docker.compose.service") == "main"
        ):
            images.append(image)
    if len(images) != 1:
        raise ScenarioPackageError(
            "provisioning-runtime-failed",
            "Harbor provisioning did not retain exactly one verifier image",
        )
    return {
        "build_input_sha256": build_input_digest(package, role="verifier"),
        "execution_reference": None,
        "image": images[0],
        "role": "verifier",
    }


def prefixed_runtime_image(
    lease: StoreLease,
    *,
    prefix: str,
    role: str,
    build_input_sha256: str,
) -> dict[str, object]:
    completed = _docker(
        ["image", "ls", "--format", "{{.Repository}}:{{.Tag}}"],
        context=lease.target.context,
    )
    matches = sorted(
        reference
        for reference in completed.stdout.splitlines()
        if reference.startswith(prefix + "--")
    )
    if len(matches) != 1:
        raise ScenarioPackageError(
            "provisioning-runtime-failed",
            f"expected one content-addressed runtime image for {prefix}, found {len(matches)}",
        )
    return tagged_runtime_image(
        lease,
        reference=matches[0],
        role=role,
        build_input_sha256=build_input_sha256,
    )


def tagged_runtime_image(
    lease: StoreLease,
    *,
    reference: str,
    role: str,
    build_input_sha256: str,
) -> dict[str, object]:
    image = _image_record(lease.target, reference)
    if image is None:
        raise ScenarioPackageError(
            "provisioning-runtime-failed", f"missing runtime image {reference}"
        )
    image.pop("labels", None)
    return {
        "build_input_sha256": build_input_sha256,
        "execution_reference": reference,
        "image": image,
        "role": role,
    }


def build_input_digest(package: Path, *, role: str) -> str:
    roots = (
        ("task.toml", "environment")
        if role in {"agent", "capture"}
        else ("task.toml", "tests")
    )
    entries: list[dict[str, object]] = []
    for root_name in roots:
        root = package / root_name
        candidates = [root] if root.is_file() else sorted(root.rglob("*"))
        for path in candidates:
            if path.is_symlink() or not path.is_file():
                continue
            data = path.read_bytes()
            entries.append(
                {
                    "mode": "0755" if path.stat().st_mode & 0o111 else "0644",
                    "path": path.relative_to(package).as_posix(),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
    if not entries:
        raise ScenarioPackageError(
            "provisioning-input-mismatch", f"missing build inputs for {role}"
        )
    return _artifact_digest(
        {"files": entries, "harbor_commit": HARBOR_COMMIT, "role": role}
    )


def create_verifier_build_package(package: Path, destination: Path) -> Path:
    if destination.exists():
        raise ScenarioPackageError(
            "qualification-publication-failed", f"path already exists: {destination}"
        )
    try:
        destination.mkdir(parents=True)
        shutil.copytree(package / "tests", destination / "environment", symlinks=True)
        (destination / "tests").mkdir()
        (destination / "solution").mkdir()
        (destination / "instruction.md").write_text(
            "Build the sealed verifier image.\n", encoding="utf-8"
        )
        (destination / "tests/test.sh").write_text(
            "#!/bin/sh\nexit 0\n", encoding="utf-8"
        )
        (destination / "solution/solve.sh").write_text(
            "#!/bin/sh\nexit 0\n", encoding="utf-8"
        )
        (destination / "tests/test.sh").chmod(0o755)
        (destination / "solution/solve.sh").chmod(0o755)
        scenario_id = yaml.safe_load(
            (package / "scenario.yaml").read_text(encoding="utf-8")
        )["scenario"]["id"]
        (destination / "task.toml").write_text(
            'version = "1.0"\n\n'
            "[task]\n"
            f'name = "{scenario_id}-verifier"\n'
            'description = "Sealed verifier image provisioning"\n\n'
            "[verifier]\n"
            "disable = true\n\n"
            "[agent]\n"
            'network_mode = "no-network"\n\n'
            "[environment]\n"
            'network_mode = "no-network"\n',
            encoding="utf-8",
        )
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return destination


def qualification_authority(
    path: Path | None,
    *,
    lock: dict[str, Any],
    lock_bytes: bytes,
) -> tuple[str, str | None]:
    if path is None:
        return "candidate", None
    registry = SchemaRegistry(schema_root_path())
    try:
        data = path.read_bytes()
        record = registry.validate_bytes(data)
    except (OSError, SchemaValidationError) as error:
        raise ScenarioPackageError(
            "invalid-qualification-authority", str(error)
        ) from error
    expected_lock = str(TypedDigest.from_bytes(DigestKind.PACKAGE_LOCK, lock_bytes))
    if (
        not isinstance(record, dict)
        or record.get("state") != "package_qualified"
        or record.get("scenario_id") != lock["scenario_id"]
        or record.get("package_lock_sha256") != expected_lock
        or record.get("package_payload_sha256") != lock["package"]["payload_sha256"]
        or record.get("harbor") != lock["harbor"]
        or record.get("identities") != lock["identities"]
        or record.get("standard_v1") != lock["standard_v1"]
    ):
        raise ScenarioPackageError(
            "invalid-qualification-authority",
            "qualification authority does not bind the exact locked Scenario Package",
        )
    return "package_qualified", _artifact_digest(record)


def publish_manifest(
    path: Path,
    *,
    lease: StoreLease,
    lock: dict[str, Any],
    lock_bytes: bytes,
    lifecycle_state: str,
    qualification_record_sha256: str | None,
    requested_images: list[dict[str, object]],
    runtime_images: list[dict[str, object]],
) -> dict[str, object]:
    registry = SchemaRegistry(schema_root_path())
    data: dict[str, Any] = {
        "lifecycle_state": lifecycle_state,
        "provisioned_at": datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "requested_images": requested_images,
        "runtime_images": sorted(runtime_images, key=lambda item: item["role"]),
        "scenario_id": lock["scenario_id"],
        "schema": registry.envelope(_MANIFEST_SCHEMA_NAME, _SCHEMA_VERSION),
        "source": {
            "harbor": lock["harbor"],
            "package_lock_sha256": str(
                TypedDigest.from_bytes(DigestKind.PACKAGE_LOCK, lock_bytes)
            ),
            "package_payload_sha256": lock["package"]["payload_sha256"],
            "qualification_record_sha256": qualification_record_sha256,
            "standard_v1": lock["standard_v1"],
        },
        "target": lease.store,
        "transaction_id": "sha256:" + hashlib.sha256(os.urandom(32)).hexdigest(),
        "visibility_domain": lease.visibility_domain,
    }
    registry.validate_value(data, name=_MANIFEST_SCHEMA_NAME, version=_SCHEMA_VERSION)
    encoded = canonical_json_bytes(data)
    try:
        _immutable_verified_write(path, encoded)
    except OSError as error:
        raise ScenarioPackageError(
            "qualification-publication-failed", str(error)
        ) from error
    return {
        "manifest_sha256": str(
            TypedDigest.from_bytes(DigestKind.PROVISIONING_MANIFEST, encoded)
        ),
        "path": str(path),
    }


def _load_manifest(path: Path) -> tuple[dict[str, Any], bytes]:
    registry = SchemaRegistry(schema_root_path())
    try:
        data = path.read_bytes()
        value = registry.validate_bytes(data)
    except (OSError, SchemaValidationError) as error:
        raise ScenarioPackageError(
            "invalid-provisioning-manifest", str(error)
        ) from error
    if not isinstance(value, dict):
        raise ScenarioPackageError(
            "invalid-provisioning-manifest", "manifest is not an object"
        )
    return value, data


def _assert_image(
    record: dict[str, Any],
    target: DockerTarget,
    *,
    reference: str | None = None,
) -> None:
    expected = record["image"]
    actual = _image_record(target, reference or expected["id"])
    if actual is None:
        raise ScenarioPackageError(
            "preflight-cache-miss", f"missing exact image {expected['id']}"
        )
    actual.pop("labels", None)
    if actual != expected:
        raise ScenarioPackageError(
            "preflight-image-mismatch", f"image identity drifted: {expected['id']}"
        )


def _project_task(package: Path, destination: Path, images: dict[str, str]) -> None:
    shutil.copytree(package, destination, symlinks=True)
    task_path = destination / "task.toml"
    text = task_path.read_text(encoding="utf-8")
    if "[environment]\n" not in text or "[verifier.environment]" in text:
        raise ScenarioPackageError(
            "preflight-projection-failed", "task environment cannot be projected safely"
        )
    text = text.replace(
        "[environment]\n",
        f'[environment]\ndocker_image = "{images["agent"]}"\n',
        1,
    )
    parsed = tomllib.loads(text)
    environment = parsed["environment"]
    fields = [
        f'docker_image = "{images["verifier"]}"',
        f'network_mode = "{environment["network_mode"]}"',
        f'workdir = "{environment["workdir"]}"',
        f"build_timeout_sec = {environment['build_timeout_sec']}",
        f"cpus = {environment['cpus']}",
        f"memory_mb = {environment['memory_mb']}",
        f"storage_mb = {environment['storage_mb']}",
    ]
    task_path.write_text(
        text.rstrip() + "\n\n[verifier.environment]\n" + "\n".join(fields) + "\n",
        encoding="utf-8",
    )
    compose_path = destination / "environment/docker-compose.yaml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    capture = (
        compose.get("services", {}).get("capture")
        if isinstance(compose, dict)
        else None
    )
    if not isinstance(capture, dict) or "build" not in capture:
        raise ScenarioPackageError(
            "preflight-projection-failed",
            "capture image build cannot be projected safely",
        )
    capture.pop("build")
    capture["image"] = images["capture"]
    services = compose["services"]
    services.setdefault("main", {})["pull_policy"] = "never"
    capture["pull_policy"] = "never"
    services.setdefault("harbor-docker-egress-control-sidecar", {})["pull_policy"] = (
        "never"
    )
    compose_path.write_text(yaml.safe_dump(compose, sort_keys=False), encoding="utf-8")


def _write_docker_guard(
    output: Path, *, egress_reference: str, egress_image_id: str
) -> Path:
    docker = shutil.which("docker")
    if docker is None:
        raise ScenarioPackageError(
            "preflight-runtime-unavailable", "Docker CLI is unavailable"
        )
    guard = output / "bin/docker"
    guard.parent.mkdir()
    quoted_docker = shlex.quote(docker)
    quoted_reference = shlex.quote(egress_reference)
    quoted_image_id = shlex.quote(egress_image_id)
    guard.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        f"actual=$({quoted_docker} image inspect {quoted_reference} "
        "--format '{{.Id}}' 2>/dev/null) || exit 126\n"
        f'[ "$actual" = {quoted_image_id} ] || exit 126\n'
        f"export EGRESS_CONTROL_SIDECAR_IMAGE_NAME={quoted_image_id}\n"
        'case "${1-}" in pull|build|buildx) exit 125 ;; esac\n'
        'if [ "${1-}" = image ] && [ "${2-}" = pull ]; then exit 125; fi\n'
        'if [ "${1-}" = run ]; then shift; '
        f'exec {quoted_docker} run --pull=never "$@"; fi\n'
        'if [ "${1-}" = container ] && [ "${2-}" = run ]; then '
        f'shift 2; exec {quoted_docker} container run --pull=never "$@"; fi\n'
        'if [ "${1-}" = compose ]; then\n'
        '  for argument in "$@"; do\n'
        '    case "$argument" in build|pull) exit 125 ;; esac\n'
        "  done\n"
        "fi\n"
        f'exec {quoted_docker} "$@"\n',
        encoding="utf-8",
    )
    guard.chmod(0o755)
    return guard


def preflight(
    package: Path,
    *,
    manifest_path: Path,
    mode: str,
    output: Path,
    qualification_record: Path | None = None,
) -> dict[str, object]:
    if mode not in {"integration", "qualification", "measured"}:
        raise ScenarioPackageError("invalid-preflight-mode", mode)
    package = package.resolve()
    checked = check_scenario_package(package)
    if checked["lock"] != "valid":
        raise ScenarioPackageError(
            "missing-package-lock", "preflight requires an exact valid package lock"
        )
    try:
        lock_bytes = (package / "scenario.lock.json").read_bytes()
        lock = json.loads(lock_bytes)
        scenario = yaml.safe_load(
            (package / "scenario.yaml").read_text(encoding="utf-8")
        )["scenario"]
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        yaml.YAMLError,
        KeyError,
        TypeError,
    ) as error:
        raise ScenarioPackageError("invalid-package-lock", str(error)) from error
    manifest, manifest_bytes = _load_manifest(manifest_path)
    visibility = scenario["visibility"]
    authority_state, authority_digest = qualification_authority(
        qualification_record.resolve() if qualification_record is not None else None,
        lock=lock,
        lock_bytes=lock_bytes,
    )
    expected_source = {
        "harbor": lock["harbor"],
        "package_lock_sha256": str(
            TypedDigest.from_bytes(DigestKind.PACKAGE_LOCK, lock_bytes)
        ),
        "package_payload_sha256": lock["package"]["payload_sha256"],
        "qualification_record_sha256": authority_digest,
        "standard_v1": lock["standard_v1"],
    }
    if (
        manifest["scenario_id"] != lock["scenario_id"]
        or manifest["visibility_domain"] != visibility
        or manifest["source"] != expected_source
    ):
        raise ScenarioPackageError(
            "preflight-source-mismatch",
            "manifest does not bind the exact locked source",
        )
    state = manifest["lifecycle_state"]
    if state != authority_state:
        raise ScenarioPackageError(
            "preflight-ineligible-source",
            "manifest lifecycle is not backed by the supplied qualification authority",
        )
    if mode == "measured" and authority_state != "package_qualified":
        raise ScenarioPackageError(
            "preflight-ineligible-source",
            "measured execution requires package_qualified authority",
        )
    if mode == "qualification" and authority_state != "candidate":
        raise ScenarioPackageError(
            "preflight-ineligible-source", "qualification requires a candidate source"
        )
    target = DockerTarget(
        context=manifest["target"]["docker_context"],
        platform=manifest["target"]["platform"],
    )
    with acquire_store_read_lease(target, visibility=visibility) as lease:
        if lease.store != manifest["target"]:
            raise ScenarioPackageError(
                "preflight-store-mismatch", "Docker store identity drifted"
            )
        expected_requests = [
            (item["identity"], item["reference"])
            for item in locked_image_requests(lock)
        ]
        manifest_requests = [
            (record["locked_identity"], record["reference"])
            for record in manifest["requested_images"]
        ]
        if manifest_requests != expected_requests:
            raise ScenarioPackageError(
                "preflight-image-mismatch",
                "manifest requested images do not equal the exact locked image inventory",
            )
        for record in manifest["requested_images"]:
            _assert_image(record, target)
            if (
                _canonical_repo_digest(record["reference"])
                not in record["image"]["repo_digests"]
            ):
                raise ScenarioPackageError(
                    "preflight-image-mismatch", "locked repository digest is absent"
                )
        runtime = {record["role"]: record for record in manifest["runtime_images"]}
        if set(runtime) != {"agent", "capture", "egress-control", "verifier"}:
            raise ScenarioPackageError(
                "invalid-provisioning-manifest", "runtime image roles are incomplete"
            )
        for role, record in runtime.items():
            execution_reference = record["execution_reference"]
            if role == "egress-control":
                if not isinstance(
                    execution_reference, str
                ) or not execution_reference.startswith(harbor_egress_image() + "--"):
                    raise ScenarioPackageError(
                        "preflight-image-mismatch",
                        "egress-control execution reference is not content-addressed",
                    )
                _assert_image(record, target, reference=execution_reference)
            else:
                if execution_reference is not None:
                    raise ScenarioPackageError(
                        "preflight-image-mismatch",
                        f"{role} must execute by sealed image ID",
                    )
                _assert_image(record, target)
            expected_input = (
                _artifact_digest(
                    {"harbor_commit": HARBOR_COMMIT, "source": _HARBOR_KERNEL_PROBE}
                )
                if role == "egress-control"
                else build_input_digest(package, role=role)
            )
            if record["build_input_sha256"] != expected_input:
                raise ScenarioPackageError(
                    "preflight-build-input-mismatch", f"{role} build inputs drifted"
                )
        if output.exists() or output.is_symlink():
            raise ScenarioPackageError(
                "preflight-projection-failed",
                f"projection path already exists: {output}",
            )
        output.mkdir(parents=True)
        try:
            projected_package = output / "package"
            _project_task(
                package,
                projected_package,
                {
                    role: runtime[role]["image"]["id"]
                    for role in ("agent", "capture", "verifier")
                },
            )
            docker_guard = _write_docker_guard(
                output,
                egress_reference=runtime["egress-control"]["execution_reference"],
                egress_image_id=runtime["egress-control"]["image"]["id"],
            )
            projected_task = _harbor_probe(projected_package)
            projection = {
                "docker_guard_sha256": _artifact_digest(
                    docker_guard.read_bytes().hex()
                ),
                "lifecycle_state": state,
                "mode": mode,
                "package_payload_sha256": lock["package"]["payload_sha256"],
                "projected_task_sha256": str(
                    TypedDigest(DigestKind.HARBOR_TASK, projected_task["content_hash"])
                ),
                "provisioning_manifest_sha256": str(
                    TypedDigest.from_bytes(
                        DigestKind.PROVISIONING_MANIFEST, manifest_bytes
                    )
                ),
                "runtime_images": {
                    role: runtime[role]["image"]["id"] for role in sorted(runtime)
                },
                "target": manifest["target"],
            }
            projection_bytes = canonical_json_bytes(projection)
            _immutable_verified_write(output / "projection.json", projection_bytes)
        except BaseException:
            shutil.rmtree(output, ignore_errors=True)
            raise
        return {
            "docker_context": target.context,
            "docker_guard_path": str(docker_guard),
            "mode": mode,
            "package_path": str(projected_package),
            "projected_task_sha256": projection["projected_task_sha256"],
            "projection_path": str(output / "projection.json"),
            "projection_sha256": _artifact_digest(projection),
            "provisioning_manifest_sha256": projection["provisioning_manifest_sha256"],
            "status": "preflight-passed",
        }


def harbor_kernel_probe_reference() -> str:
    return _HARBOR_KERNEL_PROBE


def harbor_egress_image() -> str:
    return _HARBOR_EGRESS_IMAGE

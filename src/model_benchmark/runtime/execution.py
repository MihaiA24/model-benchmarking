from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

import yaml

from model_benchmark.declarations.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    load_canonical_json,
)
from model_benchmark.declarations.functional_v1 import (
    CONDITIONS,
    FIXED_LIMITS,
    MAX_PARALLEL,
    SCENARIOS,
    FunctionalV1Manifest,
)
from model_benchmark.declarations.identities import DigestKind, TypedDigest
from model_benchmark.declarations.scenarios import (
    ScenarioPackageError,
    check_scenario_package,
)
from model_benchmark.runtime.functional_v1 import (
    CELL_SCHEDULE,
    CommandResult,
    FunctionalV1Home,
    FunctionalV1HomeError,
    RunWorkspace,
    _immutable_write,
    _inspect_result,
)
from model_benchmark.runtime.hermes import (
    HERMES_IMAGE_REFERENCE,
    provision_hermes,
)
from model_benchmark.runtime.omp import provision_omp
from model_benchmark.runtime.opencode import provision_opencode
from model_benchmark.runtime.provisioning import preflight as preflight_scenario_package
from model_benchmark.runtime.scenario_qualification import provision_scenario_package


_NATIVE_PLATFORM = "linux/amd64"
_MINIMUM_CPU = 8
_MINIMUM_MEMORY_BYTES = 24 * 1024**3
_MINIMUM_DOCKER_FREE_BYTES = 50 * 1024**3
_PIDS_LIMIT = 256
_CONDITION_MOUNT = "/opt/model-benchmark-condition"
_WALL_TIME_SECONDS = FIXED_LIMITS["wall_time_seconds_per_trial"]
_WALL_TIME_GRACE_SECONDS = 60
_STORAGE_OPT_SIZE = f"{FIXED_LIMITS['writable_disk_mib_per_trial']}M"
_PYTHON_BASE = (
    "python:3.12.12-slim-bookworm@sha256:"
    "593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c"
)
_RUN_LABEL = "org.model-benchmark.functional-v1.run"
_CELL_LABEL = "org.model-benchmark.functional-v1.cell"
_HARBOR_EGRESS_SERVICE = "harbor-docker-egress-control-sidecar"
_VALID_CONTINUE = {
    "valid_completed",
    "valid_harness_outcome",
    "valid_limit_outcome",
}
_GLOBAL_FAULTS = {"invalid_infrastructure", "invalid_integrity", "not_started"}


def _stage_schedules() -> Mapping[str, tuple[Mapping[str, object], ...]]:
    scenario = SCENARIOS[0]
    stages: dict[str, tuple[Mapping[str, object], ...]] = {
        f"single-{condition}": tuple(
            cell
            for cell in CELL_SCHEDULE
            if cell["scenario"] == scenario and cell["condition"] == condition
        )
        for condition in ("omp", "opencode", "hermes")
    }
    stages["four-condition"] = tuple(
        cell for cell in CELL_SCHEDULE if cell["scenario"] == scenario
    )
    stages["twelve-cell"] = tuple(CELL_SCHEDULE)
    return MappingProxyType(stages)


INTERNAL_QUALIFICATION_STAGES = _stage_schedules()


class ExecutionError(RuntimeError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class CellExecution:
    disposition: str
    terminal_phase: str
    reason_code: str
    duration_ns: int
    evidence_valid: bool
    details: Mapping[str, object]


class CellExecutor(Protocol):
    def run_cell(
        self,
        cell: Mapping[str, object],
        *,
        run_id: str,
        raw_root: Path,
        cancel: threading.Event,
    ) -> CellExecution: ...

    def terminate_all(self) -> None: ...


@dataclass(frozen=True)
class PreflightProjection:
    report: Mapping[str, object]
    packages: Mapping[str, Path]
    temporary_root: Path


@dataclass(frozen=True)
class ProvisioningInventory:
    identity: TypedDigest
    value: Mapping[str, object]
    path: Path


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _command(
    arguments: Sequence[str],
    *,
    timeout: int,
    environment: Mapping[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    child_environment = dict(os.environ if environment is None else environment)
    try:
        completed = subprocess.run(
            list(arguments),
            env=child_environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ExecutionError("execution-command-failed", str(error)) from error
    if check and completed.returncode != 0:
        detail = (completed.stderr.strip() or completed.stdout.strip())[-2000:]
        raise ExecutionError(
            "execution-command-failed",
            f"command failed ({completed.returncode}): {detail}",
        )
    return completed


def _docker(
    arguments: Sequence[str],
    *,
    timeout: int = 60,
    environment: Mapping[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return _command(
        ["docker", *arguments],
        timeout=timeout,
        environment=environment,
        check=check,
    )


def _json_stdout(completed: subprocess.CompletedProcess[str], label: str) -> Any:
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ExecutionError("invalid-infrastructure", f"invalid {label}") from error


def _typed_file_digest(path: Path) -> str:
    return str(TypedDigest.from_bytes(DigestKind.ARTIFACT, path.read_bytes()))


def _tree_digest(root: Path) -> str:
    entries: list[dict[str, object]] = []
    for path in sorted(
        candidate
        for candidate in root.rglob("*.py")
        if candidate.is_file() and "__pycache__" not in candidate.parts
    ):
        relative = path.relative_to(root).as_posix()
        data = path.read_bytes()
        entries.append(
            {
                "bytes": len(data),
                "path": relative,
                "sha256": str(TypedDigest.from_bytes(DigestKind.ARTIFACT, data)),
            }
        )
    return str(
        TypedDigest.from_bytes(DigestKind.ARTIFACT, canonical_json_bytes(entries))
    )


def _condition_build_value(
    condition: str,
    lock: Mapping[str, object],
    runtime_tree_digest: str,
) -> dict[str, object]:
    base_image = HERMES_IMAGE_REFERENCE if condition == "hermes" else _PYTHON_BASE
    return {
        "adapter": lock["adapter"],
        "artifact": lock["artifact"],
        "base_image": base_image,
        "condition": condition,
        "provider_mapping": lock["provider_mapping"],
        "runtime_tree_digest": runtime_tree_digest,
        "schema_version": 1,
    }


def condition_image_content_digest(
    condition: str,
    lock: Mapping[str, object],
    runtime_root: Path,
) -> str:
    return str(
        TypedDigest.from_bytes(
            DigestKind.ARTIFACT,
            canonical_json_bytes(
                _condition_build_value(condition, lock, _tree_digest(runtime_root))
            ),
        )
    )


def _manifest_reference_path(
    manifest: FunctionalV1Manifest,
    collection: str,
    name: str,
) -> Path:
    references = manifest.value[collection]
    if not isinstance(references, Mapping):
        raise ExecutionError("invalid-manifest-schema", f"{collection} is malformed")
    reference = references[name]
    if not isinstance(reference, Mapping) or not isinstance(reference.get("path"), str):
        raise ExecutionError(
            "invalid-manifest-schema", f"{collection}.{name} is malformed"
        )
    return (manifest.source_path.parent / str(reference["path"])).resolve()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _runtime_source_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _target_config(path: Path) -> None:
    value = {
        "schema_version": 1,
        "visibility_domains": {
            "public": {"docker_context": "default", "platform": _NATIVE_PLATFORM},
            "private": {
                "docker_context": "functional-v1-unused-private",
                "platform": _NATIVE_PLATFORM,
            },
        },
    }
    path.write_text(yaml.safe_dump(value, sort_keys=True), encoding="utf-8")


def _qualification_record(name: str) -> Path:
    path = _project_root() / "artifacts/qualification/functional-v1" / f"{name}.json"
    if not path.is_file():
        raise ExecutionError(
            "scenario-unqualified", f"missing Functional V1 qualification for {name}"
        )
    return path


def _scenario_package(manifest: FunctionalV1Manifest, name: str) -> Path:
    package = _manifest_reference_path(manifest, "scenarios", name).parent
    checked = check_scenario_package(package)
    if checked.get("lock") != "valid":
        raise ExecutionError(
            "scenario-lock-mismatch", f"Scenario Package changed: {name}"
        )
    return package


def _inspect_image(reference: str) -> dict[str, object]:
    value = _json_stdout(
        _docker(["image", "inspect", reference, "--format", "{{json .}}"]),
        "Docker image inspection",
    )
    if not isinstance(value, dict):
        raise ExecutionError(
            "invalid-infrastructure", "Docker image inspection is malformed"
        )
    return value


def _image_record(reference: str, role: str) -> dict[str, object]:
    image = _inspect_image(reference)
    image_id = image.get("Id")
    architecture = image.get("Architecture")
    os_name = image.get("Os")
    if (
        not isinstance(image_id, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None
        or os_name != "linux"
        or architecture not in {"amd64", "x86_64"}
    ):
        raise ExecutionError("invalid-artifact-identity", f"invalid {role} image")
    return {
        "image_id": f"oci-image:{image_id}",
        "reference": reference,
        "role": role,
    }


def _write_build_context(
    destination: Path,
    *,
    condition: str | None,
    artifact: Path | None,
    base_image: str,
    lock_identity: str | None,
    content_digest: str,
    service: str | None = None,
) -> None:
    if destination.exists():
        return
    temporary = destination.with_name(f".{destination.name}.{secrets.token_hex(6)}")
    temporary.mkdir(parents=True)
    try:
        shutil.copytree(
            _runtime_source_root(),
            temporary / "model_benchmark",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        if artifact is not None:
            artifact_name = "omp" if condition == "omp" else "opencode"
            target = temporary / "artifact" / artifact_name
            target.parent.mkdir()
            shutil.copyfile(artifact, target)
            target.chmod(0o555)
        if condition is None:
            entrypoint = (
                "python3 -m model_benchmark.runtime.credential_proxy_service"
                if service == "credential-proxy"
                else "python3 -m model_benchmark.cli"
            )
            instruction = "ENTRYPOINT" if service == "credential-proxy" else "CMD"
            dockerfile = f"""FROM {base_image}\nUSER root\nCOPY model_benchmark/ /opt/model-benchmark-runtime/model_benchmark/\nENV PYTHONPATH=/opt/model-benchmark-runtime\nLABEL org.model-benchmark.image-content={content_digest}\n{instruction} [{json.dumps(entrypoint.split()[0])},{",".join(json.dumps(item) for item in entrypoint.split()[1:])}]\n"""
        else:
            entrypoint = "#!/bin/sh\nset -eu\n"
            entrypoint += (
                "ROOT=/opt/model-benchmark-condition\n"
                "LOADER=$ROOT/lib64/ld-linux-x86-64.so.2\n"
                "LIBRARY_PATH=$ROOT/lib/x86_64-linux-gnu:$ROOT/usr/lib/x86_64-linux-gnu:$ROOT/usr/local/lib\n"
            )
            if condition == "hermes":
                entrypoint += (
                    "export PYTHONHOME=$ROOT/usr\n"
                    "export PYTHONPATH=$ROOT/opt/model-benchmark-runtime:$ROOT/opt/hermes/.venv/lib/python3.13/site-packages\n"
                    "exec $LOADER --library-path $LIBRARY_PATH $ROOT/usr/bin/python3 -m "
                    'model_benchmark.runtime.condition_image "$@"\n'
                )
            else:
                entrypoint += (
                    "export PYTHONHOME=$ROOT/usr/local\n"
                    "export PYTHONPATH=$ROOT/opt/model-benchmark-runtime\n"
                    "exec $LOADER --library-path $LIBRARY_PATH $ROOT/usr/local/bin/python3.12 -m "
                    'model_benchmark.runtime.condition_image "$@"\n'
                )
            (temporary / "entrypoint").write_text(entrypoint, encoding="utf-8")
            (temporary / "entrypoint").chmod(0o555)
            copy_artifact = (
                "\nCOPY artifact/ /artifact/" if artifact is not None else ""
            )
            dockerfile = f"""FROM {base_image}\nUSER root\nCOPY model_benchmark/ /opt/model-benchmark-runtime/model_benchmark/\nCOPY entrypoint /entrypoint{copy_artifact}\nLABEL org.model-benchmark.condition-lock={lock_identity}\nLABEL org.model-benchmark.image-content={content_digest}\n"""
        (temporary / "Dockerfile").write_text(dockerfile, encoding="utf-8")
        os.replace(temporary, destination)
        for path in destination.rglob("*"):
            if path.is_file():
                path.chmod(path.stat().st_mode & ~0o222)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _pull_exact_image(reference: str) -> None:
    if "@sha256:" not in reference:
        raise ExecutionError(
            "unpinned-base-image", f"image reference is not digest-pinned: {reference}"
        )
    present = _docker(["image", "inspect", reference], check=False)
    if present.returncode == 0:
        return
    _docker(["pull", "--platform", _NATIVE_PLATFORM, reference], timeout=900)


def _dockerfile_base(context: Path) -> str:
    first = (context / "Dockerfile").read_text(encoding="utf-8").splitlines()[0]
    if not first.startswith("FROM "):
        raise ExecutionError(
            "invalid-image-recipe", f"{context}/Dockerfile has no pinned base"
        )
    return first.removeprefix("FROM ").split()[0]


def _harbor_seam() -> dict[str, object]:
    binary = shutil.which("harbor")
    if binary is None:
        raise ExecutionError(
            "harbor-seam-missing", "the pinned Harbor CLI is not installed"
        )
    try:
        version = importlib.metadata.version("harbor")
    except importlib.metadata.PackageNotFoundError as error:
        raise ExecutionError(
            "harbor-seam-missing", "the pinned Harbor distribution is absent"
        ) from error
    return {"binary": str(Path(binary).resolve()), "version": version}


def _harbor_egress_identity() -> tuple[Path, str]:
    script = (
        "import json\n"
        "from harbor.environments.docker import EGRESS_CONTROL_SIDECAR_CONTEXT_PATH\n"
        "from harbor.utils.container_cache import docker_build_context_hash\n"
        "context = EGRESS_CONTROL_SIDECAR_CONTEXT_PATH\n"
        "hash_key = docker_build_context_hash(\n"
        "    context=context,\n"
        "    dockerfile_path=context / 'Dockerfile',\n"
        "    build_args={},\n"
        f"    platform='{_NATIVE_PLATFORM}',\n"
        ")\n"
        "print(json.dumps({'context': str(context), 'hash': hash_key}))\n"
    )
    completed = _command([sys.executable, "-c", script], timeout=120)
    value = _json_stdout(completed, "Harbor egress sidecar identity")
    context = value.get("context") if isinstance(value, dict) else None
    hash_key = value.get("hash") if isinstance(value, dict) else None
    if not isinstance(context, str) or not isinstance(hash_key, str):
        raise ExecutionError(
            "harbor-seam-invalid", "Harbor egress sidecar identity is malformed"
        )
    return Path(context), hash_key


def _build_harbor_egress_image() -> dict[str, object]:
    context, hash_key = _harbor_egress_identity()
    dockerfile = context / "Dockerfile"
    _pull_exact_image(_dockerfile_base(context))
    reference = "harbor-prebuilt:harbor-docker-egress-control-sidecar--" + hash_key
    try:
        record = _image_record(reference, "harbor-egress-control")
    except ExecutionError:
        _docker(
            [
                "buildx",
                "build",
                f"--file={dockerfile}",
                f"--platform={_NATIVE_PLATFORM}",
                f"--output=type=docker,name={reference}",
                str(context),
            ],
            timeout=900,
        )
        record = _image_record(reference, "harbor-egress-control")
    record["context_digest"] = f"artifact:sha256:{hash_key}"
    return record


def _build_image(context: Path, reference: str) -> dict[str, object]:
    _pull_exact_image(_dockerfile_base(context))
    _docker(
        [
            "build",
            "--network",
            "none",
            "--pull=false",
            "--tag",
            reference,
            str(context),
        ],
        timeout=900,
    )
    return _image_record(reference, reference.rsplit("/", 1)[-1])


def _native_host() -> dict[str, object]:
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "amd64"}:
        raise ExecutionError(
            "unsupported-native-platform",
            "Functional V1 requires native Linux/amd64",
        )
    info = _json_stdout(
        _docker(["info", "--format", "{{json .}}"]), "Docker daemon information"
    )
    if not isinstance(info, dict):
        raise ExecutionError(
            "invalid-infrastructure", "Docker daemon information is malformed"
        )
    architecture = {"x86_64": "amd64"}.get(
        str(info.get("Architecture")), info.get("Architecture")
    )
    if info.get("OSType") != "linux" or architecture != "amd64":
        raise ExecutionError(
            "unsupported-native-platform", "Docker Engine is not linux/amd64"
        )
    if info.get("CgroupVersion") != "2":
        raise ExecutionError("cgroup-v2-required", "Docker Engine must use cgroup v2")
    if info.get("Driver") != "overlay2":
        raise ExecutionError("storage-driver-unsupported", "Docker must use overlay2")
    cpu = info.get("NCPU")
    memory = info.get("MemTotal")
    root = info.get("DockerRootDir")
    if not isinstance(cpu, int) or cpu < _MINIMUM_CPU:
        raise ExecutionError(
            "insufficient-cpu", "worker requires at least 8 logical CPUs"
        )
    if not isinstance(memory, int) or memory < _MINIMUM_MEMORY_BYTES:
        raise ExecutionError(
            "insufficient-memory", "worker requires at least 24 GiB RAM"
        )
    if not isinstance(root, str) or not root:
        raise ExecutionError(
            "invalid-infrastructure", "Docker root directory is unavailable"
        )
    try:
        free = shutil.disk_usage(root).free
    except OSError as error:
        raise ExecutionError("invalid-infrastructure", str(error)) from error
    if free < _MINIMUM_DOCKER_FREE_BYTES:
        raise ExecutionError(
            "insufficient-docker-storage", "worker requires 50 GiB free Docker storage"
        )
    mount = (
        _command(
            ["findmnt", "--noheadings", "--output", "FSTYPE,OPTIONS", "--target", root],
            timeout=30,
        )
        .stdout.strip()
        .lower()
    )
    if "xfs" not in mount or not (
        {"pquota", "prjquota"} & set(re.split(r"[ ,]+", mount))
    ):
        raise ExecutionError(
            "xfs-pquota-required", "Docker overlay2 must be backed by XFS pquota"
        )
    return {
        "architecture": "amd64",
        "cgroup_version": "2",
        "cpu": cpu,
        "docker_free_bytes": free,
        "docker_root_dir": root,
        "memory_bytes": memory,
        "os": "linux",
        "storage_driver": "overlay2",
        "storage_mount": mount,
    }


def _inventory_path(home: FunctionalV1Home, manifest: FunctionalV1Manifest) -> Path:
    return home.root / "provisioning" / f"{manifest.identity.value}.json"


def _load_inventory(
    home: FunctionalV1Home, manifest: FunctionalV1Manifest
) -> ProvisioningInventory:
    path = _inventory_path(home, manifest)
    identity_path = path.with_suffix(".identity")
    try:
        data = path.read_bytes()
        value = load_canonical_json(data)
        identity = TypedDigest.parse(identity_path.read_text(encoding="ascii").strip())
    except (OSError, UnicodeError, CanonicalizationError, ValueError) as error:
        raise ExecutionError("unprovisioned-inventory", str(error)) from error
    if (
        not isinstance(value, dict)
        or identity.kind is not DigestKind.PROVISIONING_MANIFEST
        or identity != TypedDigest.from_bytes(DigestKind.PROVISIONING_MANIFEST, data)
        or value.get("manifest_identity") != str(manifest.identity)
    ):
        raise ExecutionError(
            "provisioning-inventory-mismatch", "Provisioning inventory is invalid"
        )
    return ProvisioningInventory(identity=identity, value=value, path=path)


def _verify_inventory_images(inventory: ProvisioningInventory) -> None:
    images = inventory.value.get("images")
    if not isinstance(images, list):
        raise ExecutionError(
            "provisioning-inventory-mismatch", "image inventory is missing"
        )
    for expected in images:
        if not isinstance(expected, dict):
            raise ExecutionError(
                "provisioning-inventory-mismatch", "image record is malformed"
            )
        observed = _inspect_image(str(expected.get("reference")))
        if f"oci-image:{observed.get('Id')}" != expected.get("image_id"):
            raise ExecutionError(
                "artifact-digest-drift", f"image changed: {expected.get('role')}"
            )


def _resource_inventory(
    run_id: str, cell_id: str | None = None
) -> list[dict[str, str]]:
    filters = ["--filter", f"label={_RUN_LABEL}={run_id}"]
    if cell_id is not None:
        filters.extend(["--filter", f"label={_CELL_LABEL}={cell_id}"])
    commands = {
        "container": ["container", "ls", "--all", *filters, "--format", "{{.ID}}"],
        "network": ["network", "ls", *filters, "--format", "{{.ID}}"],
        "volume": ["volume", "ls", *filters, "--format", "{{.Name}}"],
    }
    resources: list[dict[str, str]] = []
    for kind, command in commands.items():
        for identity in _docker(command).stdout.splitlines():
            if identity:
                resources.append({"id": identity, "kind": kind})
    return sorted(resources, key=lambda item: (item["kind"], item["id"]))


def _cleanup_owned(run_id: str, cell_id: str | None = None) -> list[dict[str, str]]:
    removals = {
        "container": ["container", "rm", "--force"],
        "network": ["network", "rm"],
        "volume": ["volume", "rm", "--force"],
    }
    for resource in _resource_inventory(run_id, cell_id):
        _docker([*removals[resource["kind"]], resource["id"]], check=False)
    remaining = _resource_inventory(run_id, cell_id)
    if remaining:
        raise ExecutionError("cleanup-leftovers", "Run-owned Docker resources remain")
    return remaining


def _probe_limits(image: str, run_id: str) -> dict[str, object]:
    label = f"{_RUN_LABEL}={run_id}"
    created = _docker(
        [
            "container",
            "create",
            "--label",
            label,
            "--network",
            "none",
            "--cpus",
            str(FIXED_LIMITS["cpu_cores_per_trial"]),
            "--memory",
            f"{FIXED_LIMITS['memory_mib_per_trial']}m",
            "--memory-swap",
            f"{FIXED_LIMITS['memory_mib_per_trial']}m",
            "--pids-limit",
            str(_PIDS_LIMIT),
            "--storage-opt",
            _STORAGE_OPT_SIZE,
            image,
            "python3",
            "-c",
            "from pathlib import Path; Path('/tmp/output').write_text('ok')",
        ]
    ).stdout.strip()
    try:
        inspected = _json_stdout(
            _docker(
                ["container", "inspect", created, "--format", "{{json .HostConfig}}"]
            ),
            "resource probe",
        )
        expected = {
            "CpuQuota": 200000,
            "CpuPeriod": 100000,
            "Memory": FIXED_LIMITS["memory_mib_per_trial"] * 1024**2,
            "MemorySwap": FIXED_LIMITS["memory_mib_per_trial"] * 1024**2,
            "PidsLimit": _PIDS_LIMIT,
        }
        if not isinstance(inspected, dict) or any(
            inspected.get(key) != value for key, value in expected.items()
        ):
            raise ExecutionError(
                "resource-enforcement-failed", "Docker resource limits were not exact"
            )
        _docker(["container", "start", "--attach", created], timeout=60)
    finally:
        _docker(["container", "rm", "--force", created], check=False)

    quota = _docker(
        [
            "run",
            "--rm",
            "--label",
            label,
            "--network",
            "none",
            "--storage-opt",
            _STORAGE_OPT_SIZE,
            image,
            "sh",
            "-c",
            "command -v fallocate >/dev/null && ! fallocate -l 9G /quota-probe",
        ],
        timeout=120,
        check=False,
    )
    if quota.returncode != 0:
        raise ExecutionError(
            "storage-quota-probe-failed", "8 GiB writable quota was not enforced"
        )
    return {
        "cpu_cores": FIXED_LIMITS["cpu_cores_per_trial"],
        "memory_mib": FIXED_LIMITS["memory_mib_per_trial"],
        "pids": _PIDS_LIMIT,
        "storage_mib": FIXED_LIMITS["writable_disk_mib_per_trial"],
        "wall_time_enforcement": _probe_wall_time_enforcement(image, run_id),
        "wall_time_seconds": _WALL_TIME_SECONDS,
        "writable_output": True,
    }


def _probe_wall_time_enforcement(image: str, run_id: str) -> dict[str, object]:
    label = f"{_RUN_LABEL}={run_id}"
    name = f"mb-{run_id[:12]}-wall-time"
    budget_seconds = 2
    started = time.monotonic()
    process = subprocess.Popen(
        [
            "docker",
            "run",
            "--rm",
            "--name",
            name,
            "--label",
            label,
            "--network",
            "none",
            image,
            "python3",
            "-c",
            "import time; time.sleep(600)",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    enforced = False
    try:
        process.communicate(timeout=budget_seconds)
    except subprocess.TimeoutExpired:
        _docker(["rm", "--force", name], check=False)
        try:
            process.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
        enforced = True
    if not enforced:
        raise ExecutionError(
            "wall-time-enforcement-probe-failed",
            "wall-time probe container exited before its budget elapsed",
        )
    return {
        "budget_seconds": budget_seconds,
        "enforced_after_seconds": round(time.monotonic() - started, 3),
        "mechanism": "coordinator-timeout-forced-termination",
    }


def _probe_network(
    proxy_image: str, main_image: str, egress_image: str, run_id: str
) -> dict[str, object]:
    internal = f"mb-{run_id[:12]}-internal"
    egress = f"mb-{run_id[:12]}-egress"
    label = f"{_RUN_LABEL}={run_id}"
    token = secrets.token_urlsafe(32)
    proxy = f"mb-{run_id[:12]}-proxy"
    firewall = f"mb-{run_id[:12]}-firewall"
    _docker(["network", "create", "--internal", "--label", label, internal])
    _docker(["network", "create", "--label", label, egress])
    try:
        _docker(
            [
                "run",
                "--detach",
                "--name",
                proxy,
                "--label",
                label,
                "--network",
                internal,
                "--network-alias",
                "mb-proxy",
                "--read-only",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,nodev,size=16m",
                "--tmpfs",
                "/evidence:rw,noexec,nosuid,nodev,size=16m",
                "--env",
                "MODEL_BENCHMARK_PROVIDER_API_KEY=[REDACTED:API key param]",
                "--env",
                f"MODEL_BENCHMARK_PROXY_TOKEN={token}",
                "--env",
                "MODEL_BENCHMARK_PROVIDER_BASE_URL=https://provider.invalid/v1",
                "--env",
                "MODEL_BENCHMARK_PROVIDER_MODEL=preflight/model",
                "--env",
                "MODEL_BENCHMARK_PROVIDER_TOKENS_PER_TRIAL=1",
                "--env",
                "MODEL_BENCHMARK_STOP_AFTER_COST_USD_PER_TRIAL=0.01",
                proxy_image,
            ]
        )
        _docker(["network", "connect", egress, proxy])
        _docker(
            [
                "run",
                "--detach",
                "--name",
                firewall,
                "--label",
                label,
                "--network",
                internal,
                "--cap-add",
                "NET_ADMIN",
                "--cap-add",
                "NET_RAW",
                "--env",
                "EGRESS_CONTROL_INITIAL_NETWORK_MODE=no-network",
                egress_image,
            ]
        )
        for _ in range(50):
            ready = _docker(
                [
                    "exec",
                    firewall,
                    "test",
                    "-f",
                    "/tmp/harbor-docker-egress-control-sidecar.ready",
                ],
                check=False,
            )
            if ready.returncode == 0:
                break
            time.sleep(0.1)
        else:
            raise ExecutionError(
                "proxy-isolation-probe-failed",
                "Harbor egress firewall did not become ready",
            )
        _docker(["exec", firewall, "network-policy", "allow", "mb-proxy"])
        probe = """
import socket, urllib.request
assert urllib.request.urlopen('http://mb-proxy:8080/healthz', timeout=5).status == 200
for host, port in [('1.1.1.1', 443), ('10.0.0.1', 443), ('169.254.169.254', 80), ('172.17.0.1', 2375), ('host.docker.internal', 2375)]:
    try:
        socket.create_connection((host, port), timeout=0.5)
    except OSError:
        continue
    raise SystemExit(f'direct route unexpectedly reachable: {host}')
"""
        completed = _docker(
            [
                "run",
                "--rm",
                "--label",
                label,
                "--network",
                f"container:{firewall}",
                main_image,
                "python3",
                "-c",
                probe,
            ],
            timeout=60,
            check=False,
        )
        if completed.returncode != 0:
            raise ExecutionError(
                "proxy-isolation-probe-failed",
                (completed.stderr.strip() or completed.stdout.strip())[-1000:],
            )
    finally:
        _cleanup_owned(run_id)
    return {
        "credential_proxy_ready": True,
        "direct_egress_denied": True,
        "harbor_egress_firewall": str(egress_image),
        "host_route_denied": True,
        "lan_denied": True,
        "metadata_denied": True,
        "network_policy": "proxy-only-v1",
        "provider_request_made": False,
        "public_egress_denied": True,
    }


def _runtime_scenario_package(
    source: Path,
    destination: Path,
    *,
    main_image: str,
    verifier_image: str,
) -> tuple[Path, TypedDigest]:
    shutil.copytree(source, destination)
    task = destination / "task.toml"
    text = task.read_text(encoding="utf-8")
    environment = "[environment]\n"
    if text.count(environment) != 1 or "docker_image" in text:
        raise ExecutionError(
            "scenario-runtime-binding-failed",
            "Scenario task environment cannot accept the sealed runtime images",
        )
    text = text.replace(
        environment,
        environment + f"docker_image = {json.dumps(main_image)}\n",
    )
    text += (
        "\n[verifier.environment]\n"
        f"docker_image = {json.dumps(verifier_image)}\n"
        'network_mode = "no-network"\n'
        f"cpus = {FIXED_LIMITS['cpu_cores_per_trial']}\n"
        f"memory_mb = {FIXED_LIMITS['memory_mib_per_trial']}\n"
        f"storage_mb = {FIXED_LIMITS['writable_disk_mib_per_trial']}\n"
    )
    task.write_text(text, encoding="utf-8")
    identity = _tree_digest(destination)
    for item in sorted(destination.rglob("*"), reverse=True):
        item.chmod(0o555 if item.is_dir() else 0o444)
    destination.chmod(0o555)
    return destination, identity


def _condition_mounts(reference: str) -> list[dict[str, object]]:
    return [
        {
            "type": "image",
            "source": reference,
            "target": _CONDITION_MOUNT,
            "read_only": True,
        }
    ]


def _probe_condition_mounts(
    inventory: ProvisioningInventory, main_image: str, run_id: str
) -> list[dict[str, object]]:
    records = inventory.value["conditions"]
    if not isinstance(records, dict):
        raise ExecutionError(
            "provisioning-inventory-mismatch", "condition inventory is missing"
        )
    results: list[dict[str, object]] = []
    for condition in CONDITIONS:
        record = records[condition]
        if not isinstance(record, dict):
            raise ExecutionError(
                "provisioning-inventory-mismatch", "condition record is malformed"
            )
        reference = str(record["reference"])
        arguments = ["run", "--rm", "--network", "none"]
        for mount in _condition_mounts(reference):
            arguments.extend(
                [
                    "--mount",
                    f"type=image,src={mount['source']},dst={mount['target']},readonly",
                ]
            )
        arguments.append(main_image)
        entrypoint_probe = _docker(
            [*arguments, "test", "-x", f"{_CONDITION_MOUNT}/entrypoint"],
            timeout=60,
            check=False,
        )
        if entrypoint_probe.returncode != 0:
            raise ExecutionError(
                "condition-image-mount-failed", f"cannot mount {condition} read-only"
            )
        verifier_probe = _docker(
            [*arguments, "test", "-e", f"{_CONDITION_MOUNT}/verifier"],
            timeout=60,
            check=False,
        )
        mounted = _docker([*arguments, "ls", "/opt"], timeout=60, check=False)
        mounted_entries = mounted.stdout.split()
        verifier_present = verifier_probe.returncode == 0
        unselected_present = (
            mounted.returncode != 0
            or mounted_entries != [_CONDITION_MOUNT.rsplit("/", 1)[1]]
        )
        if verifier_present or unselected_present:
            raise ExecutionError(
                "condition-image-content-invalid",
                f"{condition} image exposes verifier bytes or unselected artifacts",
            )
        results.append(
            {
                "condition": condition,
                "image_id": record["image_id"],
                "mounted_opt_entries": mounted_entries,
                "read_only": True,
                "unselected_artifacts_present": unselected_present,
                "verifier_bytes_present": verifier_present,
            }
        )
    return results


class FunctionalV1Coordinator:
    """Fixed-order, fixed-width one-attempt scheduler."""

    def __init__(self, workspace: RunWorkspace, executor: CellExecutor) -> None:
        self.workspace = workspace
        self.executor = executor

    def execute(
        self,
        schedule: Sequence[Mapping[str, object]] = CELL_SCHEDULE,
    ) -> tuple[CellExecution, ...]:
        cancel = threading.Event()
        results: dict[str, CellExecution] = {}
        futures: dict[Future[CellExecution], Mapping[str, object]] = {}
        next_index = 0

        def submit(pool: ThreadPoolExecutor, cell: Mapping[str, object]) -> None:
            cell_id = str(cell["cell_id"])
            self.workspace.write_cell_start(
                cell_id,
                started_at_utc=_utc_now(),
                details={"condition": cell["condition"], "scenario": cell["scenario"]},
            )
            future = pool.submit(
                self.executor.run_cell,
                cell,
                run_id=self.workspace.run_id,
                raw_root=self.workspace.root / "cells" / cell_id / "raw",
                cancel=cancel,
            )
            futures[future] = cell

        try:
            with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
                while next_index < len(schedule) and len(futures) < MAX_PARALLEL:
                    submit(pool, schedule[next_index])
                    next_index += 1
                while futures:
                    completed, _ = wait(tuple(futures), return_when=FIRST_COMPLETED)
                    for future in sorted(
                        completed, key=lambda item: int(futures[item]["index"])
                    ):
                        cell = futures.pop(future)
                        cell_id = str(cell["cell_id"])
                        try:
                            outcome = future.result()
                        except BaseException as error:
                            outcome = CellExecution(
                                disposition="invalid_infrastructure",
                                terminal_phase="execution",
                                reason_code="cell-executor-failed",
                                duration_ns=0,
                                evidence_valid=False,
                                details={"message": str(error)},
                            )
                        results[cell_id] = outcome
                        self.workspace.write_cell_execution(
                            cell_id,
                            disposition=outcome.disposition,
                            terminal_phase=outcome.terminal_phase,
                            reason_code=outcome.reason_code,
                            ended_at_utc=_utc_now(),
                            duration_ns=outcome.duration_ns,
                            evidence_valid=outcome.evidence_valid,
                            details=outcome.details,
                        )
                        if (
                            outcome.disposition in _GLOBAL_FAULTS
                            and not cancel.is_set()
                        ):
                            cancel.set()
                            self.executor.terminate_all()
                    if cancel.is_set():
                        continue
                    while next_index < len(schedule) and len(futures) < MAX_PARALLEL:
                        submit(pool, schedule[next_index])
                        next_index += 1
        except KeyboardInterrupt:
            cancel.set()
            self.executor.terminate_all()
            raise
        return tuple(
            results[str(cell["cell_id"])]
            for cell in schedule
            if str(cell["cell_id"]) in results
        )


class HarborCellExecutor:
    def __init__(
        self,
        manifest: FunctionalV1Manifest,
        inventory: ProvisioningInventory,
        packages: Mapping[str, Path],
        workspace: RunWorkspace,
    ) -> None:
        self.manifest = manifest
        self.inventory = inventory
        self.packages = packages
        self.workspace = workspace
        self._processes: set[subprocess.Popen[str]] = set()
        self._lock = threading.Lock()

    def terminate_all(self) -> None:
        with self._lock:
            processes = tuple(self._processes)
        for process in processes:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def _record(self, collection: str, key: str) -> Mapping[str, object]:
        value = self.inventory.value[collection]
        if not isinstance(value, Mapping) or not isinstance(value[key], Mapping):
            raise ExecutionError(
                "provisioning-inventory-mismatch", f"missing {collection}.{key}"
            )
        return value[key]

    def _harbor_binary(self) -> str:
        seam = self._record("shared", "harbor-seam")
        binary = seam.get("binary")
        if not isinstance(binary, str) or not binary:
            raise ExecutionError(
                "harbor-seam-missing", "provisioned Harbor seam identity is invalid"
            )
        return binary

    def _target_path(self, scenario: str) -> str:
        package = _scenario_package(self.manifest, scenario)
        value = yaml.safe_load((package / "scenario.yaml").read_text(encoding="utf-8"))
        allowed = value["submission"]["allowed_paths"]
        if (
            not isinstance(allowed, list)
            or len(allowed) != 1
            or not isinstance(allowed[0], str)
        ):
            raise ExecutionError(
                "raw-api-target-invalid", "Scenario must declare one Raw API target"
            )
        return allowed[0]

    def _overlay(
        self,
        path: Path,
        *,
        run_id: str,
        cell_id: str,
        condition_image: str,
        main_image: str,
        capture_image: str,
        proxy_image: str,
        proxy_evidence: Path,
    ) -> None:
        labels = {_RUN_LABEL: run_id, _CELL_LABEL: cell_id}
        value = {
            "services": {
                "capture": {
                    "build": None,
                    "image": capture_image,
                    "labels": labels,
                    "pull_policy": "never",
                },
                _HARBOR_EGRESS_SERVICE: {
                    "labels": labels,
                    "networks": ["proxy-only"],
                    "pull_policy": "never",
                },
                "main": {
                    "depends_on": {
                        "credential-proxy": {"condition": "service_healthy"}
                    },
                    "image": main_image,
                    "labels": labels,
                    "pids_limit": _PIDS_LIMIT,
                    "pull_policy": "never",
                    "storage_opt": {"size": _STORAGE_OPT_SIZE},
                    "volumes": _condition_mounts(condition_image),
                },
                "credential-proxy": {
                    "cap_drop": ["ALL"],
                    "environment": {
                        "MODEL_BENCHMARK_PROVIDER_API_KEY": "${MODEL_BENCHMARK_PROVIDER_API_KEY:?}",
                        "MODEL_BENCHMARK_PROVIDER_BASE_URL": "${MODEL_BENCHMARK_PROVIDER_BASE_URL:?}",
                        "MODEL_BENCHMARK_PROVIDER_MODEL": "${MODEL_BENCHMARK_PROVIDER_MODEL:?}",
                        "MODEL_BENCHMARK_PROVIDER_TOKENS_PER_TRIAL": "${MODEL_BENCHMARK_PROVIDER_TOKENS_PER_TRIAL:?}",
                        "MODEL_BENCHMARK_PROXY_TOKEN": "${MODEL_BENCHMARK_PROXY_TOKEN:?}",
                        "MODEL_BENCHMARK_STOP_AFTER_COST_USD_PER_TRIAL": "${MODEL_BENCHMARK_STOP_AFTER_COST_USD_PER_TRIAL:?}",
                    },
                    "healthcheck": {
                        "test": [
                            "CMD",
                            "python3",
                            "-c",
                            "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)",
                        ],
                        "interval": "1s",
                        "timeout": "2s",
                        "retries": 10,
                    },
                    "image": proxy_image,
                    "labels": labels,
                    "pull_policy": "never",
                    "networks": ["proxy-only", "provider-egress"],
                    "pids_limit": 64,
                    "read_only": True,
                    "security_opt": ["no-new-privileges:true"],
                    "tmpfs": ["/tmp:rw,noexec,nosuid,nodev,size=16m"],
                    "volumes": [f"{proxy_evidence}:/evidence"],
                },
            },
            "networks": {
                "provider-egress": {"labels": labels},
                "proxy-only": {"internal": True, "labels": labels},
            },
        }
        path.write_text(yaml.safe_dump(value, sort_keys=True), encoding="utf-8")

    def _trial_result(self, trials: Path) -> tuple[Path, dict[str, object]]:
        paths = sorted(trials.rglob("result.json"))
        if len(paths) != 1:
            raise ExecutionError(
                "harbor-result-missing", "Harbor produced no unique Trial result"
            )
        value = json.loads(paths[0].read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ExecutionError(
                "harbor-result-invalid", "Harbor Trial result is malformed"
            )
        return paths[0], value

    def _proxy_events(self, evidence_path: Path) -> list[dict[str, object]]:
        try:
            evidence = evidence_path.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeError) as error:
            raise ExecutionError(
                "proxy-evidence-missing", "Credential Proxy evidence is missing"
            ) from error
        events: list[dict[str, object]] = []
        for line in evidence.splitlines():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ExecutionError(
                    "proxy-evidence-invalid", "proxy event is not an object"
                )
            events.append(value)
        return events

    def _copy_redacted(
        self,
        source: Path,
        destination: Path,
        secrets_to_redact: tuple[bytes, ...],
    ) -> None:
        destination.mkdir(parents=True, exist_ok=False)
        for path in sorted(source.rglob("*")):
            relative = path.relative_to(source)
            target = destination / relative
            if path.is_symlink():
                raise ExecutionError(
                    "invalid_integrity", "Harbor evidence contains a symlink"
                )
            if path.is_dir():
                target.mkdir(exist_ok=True)
                continue
            data = path.read_bytes()
            for secret in secrets_to_redact:
                data = data.replace(secret, b"[REDACTED]")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            if any(secret in data for secret in secrets_to_redact):
                raise ExecutionError(
                    "secret-redaction-failed", "credential remained in evidence"
                )

    def _preserve_raw_evidence(
        self,
        source: Path,
        destination: Path,
        secrets_to_redact: tuple[bytes, ...],
    ) -> bool:
        try:
            self._copy_redacted(source, destination, secrets_to_redact)
        except (ExecutionError, OSError):
            shutil.rmtree(destination, ignore_errors=True)
            return False
        return True

    def _execution(
        self,
        result_path: Path,
        result: Mapping[str, object],
        events: list[dict[str, object]],
        elapsed: int,
    ) -> CellExecution:
        responses = [
            event for event in events if event.get("event") == "provider-response"
        ]
        requests = len(responses)
        tokens = sum(
            int(event["provider_tokens"])
            for event in responses
            if isinstance(event.get("provider_tokens"), int)
        )
        costs = [
            Decimal(str(event["provider_cost_usd"]))
            for event in responses
            if event.get("provider_cost_usd") is not None
        ]
        budget_events = [
            str(boundary)
            for event in responses
            for boundary in event.get("budget_events", [])
            if isinstance(boundary, str)
        ]
        rejected_limits = [
            str(event["reason_code"])
            for event in events
            if event.get("event") == "request-rejected"
            and event.get("reason_code")
            in {
                "request-limit-reached",
                "tokens-stop-after-response",
                "cost-stop-after-response",
            }
        ]
        fatal = next(
            (
                str(event.get("reason_code"))
                for event in events
                if event.get("reason_code")
                in {"provider-contract-violation", "provider-connection-failed"}
            ),
            None,
        )
        scores: dict[str, object] = {}
        structured_path = result_path.parent / "verifier/verifier-result.json"
        if structured_path.is_file():
            structured = json.loads(structured_path.read_text(encoding="utf-8"))
            if isinstance(structured, dict):
                for field in ("domain_scores", "scores"):
                    candidate = structured.get(field)
                    if isinstance(candidate, dict):
                        scores.update(candidate)
                for name in ("task_success", "acceptance_score", "regression_score"):
                    if name in structured:
                        scores[name] = structured[name]
        details: dict[str, object] = {
            "budget_events": budget_events,
            "cost_overshoot_explicit": True,
            "cost_overshoot_usd": format(
                max(
                    (
                        Decimal(str(event.get("cost_overshoot_usd", "0")))
                        for event in responses
                    ),
                    default=Decimal(0),
                ),
                "f",
            ),
            "cost_usd": format(sum(costs, Decimal(0)), "f"),
            "harbor_exception": result.get("exception_info"),
            "harbor_trial_name": result.get("trial_name"),
            "limits": {
                "cpu_cores": FIXED_LIMITS["cpu_cores_per_trial"],
                "memory_mib": FIXED_LIMITS["memory_mib_per_trial"],
                "pids": _PIDS_LIMIT,
                "requests": FIXED_LIMITS["requests_per_trial"],
                "wall_time_seconds": _WALL_TIME_SECONDS,
                "writable_disk_mib": FIXED_LIMITS["writable_disk_mib_per_trial"],
            },
            "provider_requests": requests,
            "provider_tokens": tokens,
            "score_vector": {name: scores[name] for name in sorted(scores)},
            "token_overshoot": max(
                (
                    int(event.get("token_overshoot", 0))
                    for event in responses
                    if isinstance(event.get("token_overshoot", 0), int)
                ),
                default=0,
            ),
            "token_overshoot_explicit": True,
        }
        if fatal is not None:
            return CellExecution(
                "invalid_infrastructure", "provider", fatal, elapsed, False, details
            )
        if responses and (
            len(costs) != len(responses)
            or any(event.get("provider_tokens") is None for event in responses)
        ):
            return CellExecution(
                "invalid_infrastructure",
                "provider",
                "provider-usage-or-cost-missing",
                elapsed,
                False,
                details,
            )
        if rejected_limits or budget_events:
            return CellExecution(
                "valid_limit_outcome",
                "provider",
                (rejected_limits or budget_events)[0],
                elapsed,
                True,
                details,
            )
        agent_result = result.get("agent_result")
        metadata = (
            agent_result.get("metadata") if isinstance(agent_result, dict) else None
        )
        if isinstance(metadata, dict) and metadata.get("exit_code") == 137:
            return CellExecution(
                "valid_limit_outcome",
                "condition",
                "memory-oom-limit",
                elapsed,
                True,
                details,
            )
        exception_info = result.get("exception_info")
        exception_type = (
            exception_info.get("exception_type")
            if isinstance(exception_info, dict)
            else None
        )
        if exception_type == "AgentTimeoutError":
            return CellExecution(
                "valid_limit_outcome",
                "condition",
                "wall-time-limit",
                elapsed,
                True,
                {
                    **details,
                    "limit": "wall_time_seconds_per_trial",
                    "wall_time_seconds": _WALL_TIME_SECONDS,
                },
            )
        if exception_info is not None:
            return CellExecution(
                "valid_harness_outcome",
                "harbor",
                "harness-terminal-outcome",
                elapsed,
                True,
                details,
            )
        if not responses:
            return CellExecution(
                "valid_harness_outcome",
                "condition",
                "condition-ended-before-provider-response",
                elapsed,
                True,
                details,
            )
        if not scores:
            return CellExecution(
                "valid_harness_outcome",
                "verification",
                "submission-not-evaluable",
                elapsed,
                True,
                details,
            )
        return CellExecution(
            "valid_completed",
            "verification",
            "verifier-completed",
            elapsed,
            True,
            details,
        )

    def run_cell(
        self,
        cell: Mapping[str, object],
        *,
        run_id: str,
        raw_root: Path,
        cancel: threading.Event,
    ) -> CellExecution:
        started = time.monotonic_ns()
        cell_id = str(cell["cell_id"])
        scenario = str(cell["scenario"])
        condition = str(cell["condition"])
        condition_record = self._record("conditions", condition)
        proxy_record = self._record("shared", "credential-proxy")
        scenario_record = self._record("scenarios", scenario)
        runtime_images = scenario_record.get("runtime_images")
        if not isinstance(runtime_images, Mapping):
            raise ExecutionError(
                "provisioning-inventory-mismatch",
                f"missing scenarios.{scenario}.runtime_images",
            )
        main_record = runtime_images.get("main")
        capture_record = runtime_images.get("capture")
        if not isinstance(main_record, Mapping) or not isinstance(
            capture_record, Mapping
        ):
            raise ExecutionError(
                "provisioning-inventory-mismatch",
                f"missing scenarios.{scenario} main or capture image",
            )
        condition_image = str(condition_record["reference"])
        main_image = str(main_record["reference"])
        capture_image = str(capture_record["reference"])
        proxy_image = str(proxy_record["reference"])
        lock = self.manifest.condition_locks[condition]
        artifact = lock["artifact"]
        if not isinstance(artifact, Mapping):
            raise ExecutionError(
                "invalid-condition-lock", "condition artifact is malformed"
            )
        token = secrets.token_urlsafe(32)
        real_key = os.environ.get("MODEL_BENCHMARK_PROVIDER_API_KEY", "")
        if not real_key:
            raise ExecutionError(
                "provider-credential-missing", "provider credential is absent"
            )
        with tempfile.TemporaryDirectory(
            prefix=f"model-benchmark-{cell_id}-"
        ) as temporary:
            root = Path(temporary)
            overlay = root / "overlay.yaml"
            trials = root / "trials"
            proxy_evidence = root / "proxy-evidence"
            proxy_evidence.mkdir(mode=0o700)
            self._overlay(
                overlay,
                run_id=run_id,
                cell_id=cell_id,
                condition_image=condition_image,
                main_image=main_image,
                capture_image=capture_image,
                proxy_image=proxy_image,
                proxy_evidence=proxy_evidence,
            )
            arguments = [
                self._harbor_binary(),
                "trial",
                "start",
                "--path",
                str(self.packages[scenario]),
                "--agent",
                str(lock["adapter"]["harbor_agent"]),
                "--trial-name",
                cell_id,
                "--trials-dir",
                str(trials),
                "--delete",
                "--no-force-build",
                "--cpus",
                "limit",
                "--memory",
                "limit",
                "--override-cpus",
                str(FIXED_LIMITS["cpu_cores_per_trial"]),
                "--override-memory-mb",
                str(FIXED_LIMITS["memory_mib_per_trial"]),
                "--override-storage-mb",
                str(FIXED_LIMITS["writable_disk_mib_per_trial"]),
                "--agent-timeout",
                str(_WALL_TIME_SECONDS),
                "--extra-docker-compose",
                str(overlay),
                "--allow-agent-host",
                "credential-proxy",
                "--agent-kwarg",
                f"condition={condition}",
                "--agent-kwarg",
                f"entrypoint={_CONDITION_MOUNT}/entrypoint",
                "--agent-kwarg",
                f"artifact_identity={artifact['digest']}",
                "--agent-env",
                f"MODEL_BENCHMARK_PROVIDER_MODEL={self.manifest.value['provider']['model']}",
                "--agent-env",
                "MODEL_BENCHMARK_PROXY_BASE_URL=http://credential-proxy:8080"
                + urlsplit(str(self.manifest.value["provider"]["base_url"])).path,
                "--agent-env",
                f"MODEL_BENCHMARK_PROXY_TOKEN={token}",
            ]
            if condition == "raw-api":
                arguments.extend(
                    ["--agent-kwarg", f"target_path={self._target_path(scenario)}"]
                )
            environment = {
                **os.environ,
                "MODEL_BENCHMARK_PROVIDER_API_KEY": real_key,
                "MODEL_BENCHMARK_PROVIDER_BASE_URL": str(
                    self.manifest.value["provider"]["base_url"]
                ),
                "MODEL_BENCHMARK_PROVIDER_MODEL": str(
                    self.manifest.value["provider"]["model"]
                ),
                "MODEL_BENCHMARK_PROVIDER_TOKENS_PER_TRIAL": str(
                    self.manifest.value["limits"]["provider_tokens_per_trial"]
                ),
                "MODEL_BENCHMARK_PROXY_TOKEN": token,
                "MODEL_BENCHMARK_STOP_AFTER_COST_USD_PER_TRIAL": str(
                    self.manifest.value["limits"]["stop_after_cost_usd_per_trial"]
                ),
            }
            process = subprocess.Popen(
                arguments,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            with self._lock:
                self._processes.add(process)
            try:
                try:
                    stdout, stderr = process.communicate(
                        timeout=_WALL_TIME_SECONDS + _WALL_TIME_GRACE_SECONDS
                    )
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        stdout, stderr = process.communicate(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        stdout, stderr = process.communicate()
                    _cleanup_owned(run_id, cell_id)
                    return CellExecution(
                        "valid_limit_outcome",
                        "condition",
                        "wall-time-limit",
                        time.monotonic_ns() - started,
                        True,
                        {
                            "exit_code": process.returncode,
                            "limit": "wall_time_seconds_per_trial",
                            "wall_time_seconds": _WALL_TIME_SECONDS,
                        },
                    )
            finally:
                with self._lock:
                    self._processes.discard(process)
            if cancel.is_set():
                preserved = self._preserve_raw_evidence(
                    root, raw_root, (real_key.encode(), token.encode())
                )
                _cleanup_owned(run_id, cell_id)
                return CellExecution(
                    "invalid_infrastructure",
                    "cleanup",
                    "shared-fault-terminated",
                    time.monotonic_ns() - started,
                    False,
                    {
                        "exit_code": process.returncode,
                        "raw_evidence_preserved": preserved,
                    },
                )
            try:
                result_path, result = self._trial_result(trials)
                events = self._proxy_events(proxy_evidence / "proxy.jsonl")
                self._copy_redacted(
                    root,
                    raw_root,
                    (real_key.encode(), token.encode()),
                )
                outcome = self._execution(
                    result_path,
                    result,
                    events,
                    time.monotonic_ns() - started,
                )
            except BaseException:
                _cleanup_owned(run_id, cell_id)
                raise
            cleanup_before = _resource_inventory(run_id, cell_id)
            _cleanup_owned(run_id, cell_id)
            details = {
                **dict(outcome.details),
                "cleanup_before": cleanup_before,
                "cleanup_after": [],
                "harbor_exit_code": process.returncode,
                "harbor_stderr": stderr[-2000:],
                "harbor_stdout": stdout[-2000:],
            }
            return CellExecution(
                outcome.disposition,
                outcome.terminal_phase,
                outcome.reason_code,
                outcome.duration_ns,
                outcome.evidence_valid,
                details,
            )


def _workspace_manifest(
    home: FunctionalV1Home, workspace: RunWorkspace
) -> tuple[FunctionalV1Manifest, Path]:
    temporary = Path(tempfile.mkdtemp(prefix="functional-v1-resume-", dir=home.root))
    try:
        source = workspace.root / "input/source.yaml"
        value = yaml.safe_load(source.read_text(encoding="utf-8", errors="strict"))
        if not isinstance(value, dict):
            raise ExecutionError(
                "corrupt-run-workspace", "stored manifest is malformed"
            )
        destination = temporary / "functional-v1.yaml"
        destination.write_bytes(source.read_bytes())
        manifest_identity = TypedDigest.parse(
            str(workspace.header["manifest_identity"])
        )
        inventory_value = load_canonical_json(
            (
                home.root / "provisioning" / f"{manifest_identity.value}.json"
            ).read_bytes()
        )
        if not isinstance(inventory_value, dict) or not isinstance(
            inventory_value.get("scenarios"), dict
        ):
            raise ExecutionError(
                "provisioning-inventory-mismatch",
                "stored scenario inventory is malformed",
            )
        for collection, names in (("scenarios", SCENARIOS), ("conditions", CONDITIONS)):
            references = value.get(collection)
            if not isinstance(references, dict):
                raise ExecutionError(
                    "corrupt-run-workspace", f"stored {collection} are malformed"
                )
            for name in names:
                reference = references.get(name)
                if not isinstance(reference, dict):
                    raise ExecutionError(
                        "corrupt-run-workspace",
                        f"stored {collection}.{name} is malformed",
                    )
                relative = reference.get("path")
                identity = TypedDigest.parse(str(reference.get("digest")))
                if not isinstance(relative, str):
                    raise ExecutionError(
                        "corrupt-run-workspace",
                        f"stored {collection}.{name} path is invalid",
                    )
                captured = (
                    home.root
                    / "inputs"
                    / identity.kind.value
                    / f"{identity.value}.json"
                )
                target = temporary / relative
                if collection == "scenarios":
                    scenario_record = inventory_value["scenarios"].get(name)
                    if not isinstance(scenario_record, dict) or not isinstance(
                        scenario_record.get("package_path"), str
                    ):
                        raise ExecutionError(
                            "provisioning-inventory-mismatch",
                            f"stored Scenario Package is missing: {name}",
                        )
                    shutil.copytree(
                        Path(scenario_record["package_path"]),
                        target.parent,
                        dirs_exist_ok=True,
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(captured.read_bytes())
        return FunctionalV1Manifest.load(destination), temporary
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


class NativeFunctionalV1Runtime:
    def __init__(self, home: FunctionalV1Home) -> None:
        self.home = home

    def provision(self, manifest: FunctionalV1Manifest) -> CommandResult:
        try:
            return self._provision(manifest)
        except RuntimeError as error:
            return CommandResult(
                3,
                f"Provisioning rejected: {error}",
                {
                    "command": "provision",
                    "manifest_identity": str(manifest.identity),
                    "message": str(error),
                    "outcome": "rejected",
                    "reason_code": getattr(
                        error, "reason_code", "provisioning-rejected"
                    ),
                },
            )

    def _provision(self, manifest: FunctionalV1Manifest) -> CommandResult:
        with self.home.provisioning_lease():
            host = _native_host()
            self.home.store_manifest_inputs(manifest)
            inventory_path = _inventory_path(self.home, manifest)
            identity_path = inventory_path.with_suffix(".identity")
            if inventory_path.exists() or identity_path.exists():
                existing = _load_inventory(self.home, manifest)
                _verify_inventory_images(existing)
                return self._provision_result(manifest, existing, reused=True)

            root = self.home.root / "provisioning" / manifest.identity.value
            root.mkdir(parents=True, exist_ok=True)
            target = root / "target.yaml"
            _target_config(target)
            scenarios: dict[str, object] = {}
            images: list[dict[str, object]] = []
            for name in SCENARIOS:
                package = _scenario_package(manifest, name)
                lock_digest = TypedDigest.from_bytes(
                    DigestKind.PACKAGE_LOCK, manifest.scenario_lock_bytes[name]
                )
                output = root / "scenarios" / lock_digest.value / "manifest.json"
                jobs = root / "scenarios" / lock_digest.value / "jobs"
                output.parent.mkdir(parents=True, exist_ok=True)
                provisioned = provision_scenario_package(
                    package,
                    jobs_dir=jobs,
                    manifest_output=output,
                    target_config=target,
                    qualification_record=_qualification_record(name),
                )
                runtime_images: dict[str, object] = {}
                for role, relative in (
                    ("main", "environment"),
                    ("capture", "environment/capture"),
                    ("verifier", "tests"),
                ):
                    context = package / relative
                    context_digest = _tree_digest(context)
                    reference = (
                        f"model-benchmark.local/scenario-{name}-{role}:"
                        f"{context_digest.value.rsplit(':', 1)[1]}"
                    )
                    image_record = _build_image(context, reference)
                    runtime_images[role] = image_record
                    images.append(image_record)
                scenarios[name] = {
                    "package_lock": str(lock_digest),
                    "package_path": str(package),
                    "provisioning_manifest": str(output),
                    "provisioning_manifest_sha256": provisioned["manifest_sha256"],
                    "runtime_images": runtime_images,
                }

            cache = root / "conditions-cache"
            condition_sources = {
                "omp": provision_omp(cache, manifest.condition_lock_bytes["omp"]),
                "opencode": provision_opencode(
                    cache, manifest.condition_lock_bytes["opencode"]
                ),
                "hermes": provision_hermes(
                    cache, manifest.condition_lock_bytes["hermes"]
                ),
            }
            runtime_digest = _tree_digest(_runtime_source_root())
            conditions: dict[str, object] = {}
            for name in CONDITIONS:
                lock = manifest.condition_locks[name]
                image = lock.get("image")
                if not isinstance(image, Mapping):
                    raise ExecutionError(
                        "invalid-condition-lock", f"{name} image pin is missing"
                    )
                expected_content = condition_image_content_digest(
                    name, lock, _runtime_source_root()
                )
                if image.get("content_digest") != expected_content:
                    raise ExecutionError(
                        "condition-image-pin-mismatch",
                        f"{name} image content pin is stale",
                    )
                lock_identity = TypedDigest.from_bytes(
                    DigestKind.FUNCTIONAL_V1_CONDITION,
                    manifest.condition_lock_bytes[name],
                )
                reference = (
                    f"model-benchmark.local/functional-v1/{name}:{lock_identity.value}"
                )
                source = condition_sources.get(name)
                artifact_path = getattr(source, "artifact_path", None)
                context = root / "image-contexts" / lock_identity.value
                _write_build_context(
                    context,
                    condition=name,
                    artifact=artifact_path,
                    base_image=HERMES_IMAGE_REFERENCE
                    if name == "hermes"
                    else _PYTHON_BASE,
                    lock_identity=str(lock_identity),
                    content_digest=expected_content,
                )
                record = _build_image(context, reference)
                record.update(
                    {
                        "condition_identity": str(lock_identity),
                        "content_digest": expected_content,
                        "read_only_mount": _CONDITION_MOUNT,
                    }
                )
                conditions[name] = record
                images.append(record)

            egress_record = _build_harbor_egress_image()
            shared: dict[str, object] = {
                "harbor-egress-control": egress_record,
                "harbor-seam": _harbor_seam(),
            }
            images.append(egress_record)
            for role in ("coordinator", "credential-proxy"):
                content = str(
                    TypedDigest.from_bytes(
                        DigestKind.ARTIFACT,
                        canonical_json_bytes(
                            {
                                "base_image": _PYTHON_BASE,
                                "role": role,
                                "runtime_tree_digest": runtime_digest,
                            }
                        ),
                    )
                )
                reference = f"model-benchmark.local/functional-v1/{role}:{content.rsplit(':', 1)[1]}"
                context = root / "image-contexts" / content.rsplit(":", 1)[1]
                _write_build_context(
                    context,
                    condition=None,
                    artifact=None,
                    base_image=_PYTHON_BASE,
                    lock_identity=None,
                    content_digest=content,
                    service=role,
                )
                record = _build_image(context, reference)
                record["content_digest"] = content
                shared[role] = record
                images.append(record)

            value = {
                "conditions": conditions,
                "host": host,
                "images": images,
                "manifest_identity": str(manifest.identity),
                "platform": _NATIVE_PLATFORM,
                "scenarios": scenarios,
                "schema_version": 1,
                "shared": shared,
            }
            data = canonical_json_bytes(value)
            identity = TypedDigest.from_bytes(DigestKind.PROVISIONING_MANIFEST, data)
            path = _inventory_path(self.home, manifest)
            _immutable_write(path, data, allow_identical=False)
            _immutable_write(
                path.with_suffix(".identity"),
                (str(identity) + "\n").encode("ascii"),
                allow_identical=False,
            )
            inventory = ProvisioningInventory(identity, value, path)
            return self._provision_result(manifest, inventory, reused=False)

    def _provision_result(
        self,
        manifest: FunctionalV1Manifest,
        inventory: ProvisioningInventory,
        *,
        reused: bool,
    ) -> CommandResult:
        return CommandResult(
            0,
            f"Provisioned sealed Functional V1 inventory {inventory.identity}",
            {
                "command": "provision",
                "manifest_identity": str(manifest.identity),
                "outcome": "provisioned",
                "provisioning_manifest_identity": str(inventory.identity),
                "reused": reused,
            },
        )

    def _preflight(self, manifest: FunctionalV1Manifest) -> PreflightProjection:
        self.home.verify_manifest_inputs(manifest)
        host = _native_host()
        inventory = _load_inventory(self.home, manifest)
        _verify_inventory_images(inventory)
        if not os.environ.get("MODEL_BENCHMARK_PROVIDER_API_KEY"):
            raise ExecutionError(
                "provider-credential-missing",
                "MODEL_BENCHMARK_PROVIDER_API_KEY is absent",
            )
        temporary = Path(
            tempfile.mkdtemp(prefix="functional-v1-preflight-", dir=self.home.root)
        )
        packages: dict[str, Path] = {}
        try:
            scenarios = inventory.value["scenarios"]
            if not isinstance(scenarios, Mapping):
                raise ExecutionError(
                    "provisioning-inventory-mismatch", "scenario inventory is missing"
                )
            package_probes: list[dict[str, object]] = []
            for name in SCENARIOS:
                record = scenarios[name]
                if not isinstance(record, Mapping):
                    raise ExecutionError(
                        "provisioning-inventory-mismatch",
                        "scenario record is malformed",
                    )
                package = _scenario_package(manifest, name)
                output = temporary / name
                receipt = preflight_scenario_package(
                    package,
                    manifest_path=Path(str(record["provisioning_manifest"])),
                    mode="measured",
                    output=output,
                    qualification_record=_qualification_record(name),
                )
                runtime_images = record.get("runtime_images")
                if not isinstance(runtime_images, Mapping):
                    raise ExecutionError(
                        "provisioning-inventory-mismatch",
                        f"{name} runtime image inventory is missing",
                    )
                main_record = runtime_images.get("main")
                verifier_record = runtime_images.get("verifier")
                if not isinstance(main_record, Mapping) or not isinstance(
                    verifier_record, Mapping
                ):
                    raise ExecutionError(
                        "provisioning-inventory-mismatch",
                        f"{name} main or verifier image inventory is missing",
                    )
                runtime_package, runtime_identity = _runtime_scenario_package(
                    Path(str(receipt["package_path"])),
                    temporary / f"{name}-runtime",
                    main_image=str(main_record["reference"]),
                    verifier_image=str(verifier_record["reference"]),
                )
                packages[name] = runtime_package
                package_probes.append(
                    {
                        "package_lock": record["package_lock"],
                        "projected_task_sha256": receipt["projected_task_sha256"],
                        "runtime_package_identity": str(runtime_identity),
                        "scenario": name,
                    }
                )
            shared = inventory.value["shared"]
            if not isinstance(shared, Mapping):
                raise ExecutionError(
                    "provisioning-inventory-mismatch",
                    "shared image inventory is missing",
                )
            coordinator = str(shared["coordinator"]["reference"])
            proxy = str(shared["credential-proxy"]["reference"])
            egress_record = shared.get("harbor-egress-control")
            if not isinstance(egress_record, Mapping):
                raise ExecutionError(
                    "provisioning-inventory-mismatch",
                    "Harbor egress image inventory is missing",
                )
            egress_image = str(egress_record["reference"])
            recorded_seam = shared.get("harbor-seam")
            if not isinstance(recorded_seam, Mapping):
                raise ExecutionError(
                    "provisioning-inventory-mismatch",
                    "Harbor seam identity is missing from the inventory",
                )
            observed_seam = _harbor_seam()
            if dict(recorded_seam) != observed_seam:
                raise ExecutionError(
                    "harbor-seam-drift",
                    "installed Harbor differs from the provisioned seam identity",
                )
            probe_id = f"preflight-{secrets.token_hex(8)}"
            before = _resource_inventory(probe_id)
            if before:
                raise ExecutionError(
                    "cleanup-probe-failed", "preflight label was already in use"
                )
            limits = _probe_limits(coordinator, probe_id)
            network = _probe_network(proxy, coordinator, egress_image, probe_id)
            mounts = _probe_condition_mounts(inventory, coordinator, probe_id)
            after = _resource_inventory(probe_id)
            if after:
                raise ExecutionError(
                    "cleanup-probe-failed", "preflight left Docker resources"
                )
            report = {
                "artifact_images": mounts,
                "capacity": {
                    "observed_cpu": host["cpu"],
                    "observed_memory_bytes": host["memory_bytes"],
                    "observed_storage_bytes": host["docker_free_bytes"],
                    "required_cpu": _MINIMUM_CPU,
                    "required_memory_bytes": _MINIMUM_MEMORY_BYTES,
                    "required_storage_bytes": _MINIMUM_DOCKER_FREE_BYTES,
                    "slots": MAX_PARALLEL,
                },
                "cleanup": {"after": after, "before": before, "passed": True},
                "harbor_seam": observed_seam,
                "host": host,
                "limits": limits,
                "network": network,
                "packages": package_probes,
                "provisioning_manifest_identity": str(inventory.identity),
                "schema_version": 1,
                "token_cost_overshoot": "one in-flight response may overshoot",
            }
            return PreflightProjection(report, packages, temporary)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def preflight(self, manifest: FunctionalV1Manifest) -> CommandResult:
        try:
            with self.home.coordinator_lease():
                projection = self._preflight(manifest)
        except (ExecutionError, FunctionalV1HomeError, ScenarioPackageError) as error:
            reason = getattr(error, "reason_code", "preflight-rejected")
            return CommandResult(
                3,
                f"Preflight rejected: {error}",
                {
                    "command": "preflight",
                    "manifest_identity": str(manifest.identity),
                    "message": str(error),
                    "outcome": "rejected",
                    "reason_code": reason,
                },
            )
        try:
            return CommandResult(
                0,
                "Functional V1 native preflight passed",
                {
                    "command": "preflight",
                    "manifest_identity": str(manifest.identity),
                    "outcome": "passed",
                    "report": dict(projection.report),
                },
            )
        finally:
            shutil.rmtree(projection.temporary_root, ignore_errors=True)

    def run(self, manifest: FunctionalV1Manifest) -> CommandResult:
        return self._run_schedule(manifest, CELL_SCHEDULE)

    def internal_qualification(
        self, manifest: FunctionalV1Manifest, stage: str
    ) -> CommandResult:
        """Internal incremental qualification path; never operator-selectable."""
        schedule = INTERNAL_QUALIFICATION_STAGES.get(stage)
        if schedule is None:
            raise ExecutionError(
                "unknown-qualification-stage",
                f"unknown internal qualification stage: {stage}",
            )
        return self._run_schedule(manifest, schedule)

    def _run_schedule(
        self,
        manifest: FunctionalV1Manifest,
        schedule: Sequence[Mapping[str, object]],
    ) -> CommandResult:
        try:
            with self.home.coordinator_lease():
                projection = self._preflight(manifest)
                workspace = self.home.create_workspace(manifest)
                try:
                    inventory = _load_inventory(self.home, manifest)
                    executor = HarborCellExecutor(
                        manifest, inventory, projection.packages, workspace
                    )
                    return self._execute_schedule(workspace, executor, schedule)
                finally:
                    shutil.rmtree(projection.temporary_root, ignore_errors=True)
        except (ExecutionError, FunctionalV1HomeError, ScenarioPackageError) as error:
            reason = getattr(error, "reason_code", "run-rejected")
            return CommandResult(
                3,
                f"Run rejected before provider spend: {error}",
                {
                    "command": "run",
                    "manifest_identity": str(manifest.identity),
                    "message": str(error),
                    "outcome": "rejected",
                    "reason_code": reason,
                },
            )

    def _execute_schedule(
        self,
        workspace: RunWorkspace,
        executor: CellExecutor,
        schedule: Sequence[Mapping[str, object]],
    ) -> CommandResult:
        run_id = workspace.run_id
        try:
            outcomes = FunctionalV1Coordinator(workspace, executor).execute(schedule)
        except KeyboardInterrupt:
            self._terminalize_started(
                workspace,
                schedule,
                disposition="aborted_operator",
                terminal_phase="operator",
                reason_code="operator-stop",
            )
            _cleanup_owned(run_id)
            return CommandResult(
                1,
                "Run stopped; unstarted cells remain narrowly resumable",
                {
                    "command": "run",
                    "outcome": "aborted-operator",
                    "run_id": run_id,
                },
            )
        except BaseException as error:
            executor.terminate_all()
            _cleanup_owned(run_id)
            self._terminalize_started(
                workspace,
                schedule,
                disposition="invalid_infrastructure",
                terminal_phase="coordinator",
                reason_code="coordinator-crash",
            )
            return CommandResult(
                1,
                "Coordinator failed; unstarted cells remain narrowly resumable",
                {
                    "command": "run",
                    "message": str(error),
                    "outcome": "coordinator-crash",
                    "run_id": run_id,
                },
            )
        _cleanup_owned(run_id)
        global_fault = next(
            (
                outcome
                for outcome in outcomes
                if outcome.disposition in _GLOBAL_FAULTS
            ),
            None,
        )
        if global_fault is not None:
            self._terminalize_fault(workspace, schedule, global_fault)
            return CommandResult(
                1,
                "Run invalidated; terminal facts await evidence sealing",
                {
                    "command": "run",
                    "outcome": "invalid-unsealed",
                    "reason_code": global_fault.reason_code,
                    "run_id": run_id,
                },
            )
        return CommandResult(
            1,
            "Execution complete; raw cells await Result Bundle sealing",
            {
                "cells_executed": len(outcomes),
                "command": "run",
                "outcome": "execution-complete-unsealed",
                "run_id": run_id,
            },
        )

    def _terminalize_started(
        self,
        workspace: RunWorkspace,
        schedule: Sequence[Mapping[str, object]],
        *,
        disposition: str,
        terminal_phase: str,
        reason_code: str,
    ) -> None:
        for cell in schedule:
            cell_id = str(cell["cell_id"])
            start = workspace.root / "cells" / cell_id / "start.json"
            execution_record = workspace.root / "cells" / cell_id / "execution.json"
            terminal = workspace.root / "cells" / cell_id / "terminal.json"
            if not start.exists() or terminal.exists() or execution_record.exists():
                continue
            workspace.write_cell_terminal(
                cell_id,
                disposition=disposition,
                terminal_phase=terminal_phase,
                reason_code=reason_code,
                ended_at_utc=_utc_now(),
                duration_ns=0,
                evidence_valid=False,
                result_bundle_identity=None,
                details={},
            )

    def _terminalize_fault(
        self,
        workspace: RunWorkspace,
        schedule: Sequence[Mapping[str, object]],
        cause: CellExecution,
    ) -> None:
        for cell in schedule:
            cell_id = str(cell["cell_id"])
            start = workspace.root / "cells" / cell_id / "start.json"
            terminal = workspace.root / "cells" / cell_id / "terminal.json"
            if terminal.exists():
                continue
            if not start.exists():
                workspace.write_cell_start(
                    cell_id,
                    started_at_utc=_utc_now(),
                    details={
                        "condition": cell["condition"],
                        "scenario": cell["scenario"],
                        "shared_fault_prevented_execution": True,
                    },
                )
            workspace.write_cell_terminal(
                cell_id,
                disposition=cause.disposition,
                terminal_phase=cause.terminal_phase,
                reason_code=cause.reason_code,
                ended_at_utc=_utc_now(),
                duration_ns=cause.duration_ns,
                evidence_valid=False,
                result_bundle_identity=None,
                details={"shared_cause": cause.reason_code},
            )

    def resume(self, run_id: str) -> CommandResult:
        manifest_root: Path | None = None
        projection: PreflightProjection | None = None
        try:
            with self.home.coordinator_lease():
                try:
                    sealed = self.home.sealed_run(run_id)
                except FunctionalV1HomeError as sealed_error:
                    if sealed_error.reason_code != "unsealed-or-corrupt-run":
                        raise
                else:
                    return _inspect_result(sealed)
                workspace = self.home.workspace(run_id)
                _cleanup_owned(run_id)
                leftovers = _resource_inventory(run_id)
                if leftovers:
                    raise ExecutionError(
                        "cleanup-incomplete",
                        "coordinator-crash recovery left Run-owned resources",
                    )
                manifest, manifest_root = _workspace_manifest(self.home, workspace)
                projection = self._preflight(manifest)
                self._terminalize_started(
                    workspace,
                    CELL_SCHEDULE,
                    disposition="invalid_infrastructure",
                    terminal_phase="coordinator",
                    reason_code="started-cell-missing-terminal-record",
                )
                pending = [
                    cell
                    for cell in CELL_SCHEDULE
                    if not (
                        workspace.root / "cells" / str(cell["cell_id"]) / "start.json"
                    ).exists()
                ]
                if not pending:
                    return CommandResult(
                        1,
                        "Run has no resumable unstarted cells",
                        {
                            "command": "run",
                            "outcome": "unsealed",
                            "reason_code": "capture-layer-required",
                            "run_id": run_id,
                        },
                    )
                inventory = _load_inventory(self.home, manifest)
                executor = HarborCellExecutor(
                    manifest, inventory, projection.packages, workspace
                )
                return self._execute_schedule(workspace, executor, pending)
        except (ExecutionError, FunctionalV1HomeError, ScenarioPackageError) as error:
            return CommandResult(
                1,
                f"Resume rejected: {error}",
                {
                    "command": "run",
                    "message": str(error),
                    "outcome": "rejected",
                    "reason_code": getattr(error, "reason_code", "resume-rejected"),
                },
            )
        finally:
            if projection is not None:
                shutil.rmtree(projection.temporary_root, ignore_errors=True)
            if manifest_root is not None:
                shutil.rmtree(manifest_root, ignore_errors=True)

    def inspect(self, run_id: str) -> CommandResult:
        return _inspect_result(self.home.sealed_run(run_id))

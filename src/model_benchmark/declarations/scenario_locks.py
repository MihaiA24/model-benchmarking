from __future__ import annotations

import re
import stat
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from model_benchmark.declarations.canonical import canonical_json_bytes
from model_benchmark.declarations.identities import (
    DigestKind,
    ScenarioIdentity,
    ScoreContractIdentity,
    TypedDigest,
    VerifierIdentity,
)
from model_benchmark.declarations.schemas import SchemaRegistry, SchemaValidationError


HARBOR_COMMIT = "527d50deb63a5d279e8c20593c18a2cbc7f61f9e"
LOCK_SCHEMA_NAME = "model-benchmark/scenario-lock"
LOCK_SCHEMA_VERSION = 1
_IMAGE_REFERENCE = re.compile(r"^[^\s@]+@sha256:([0-9a-f]{64})$")


class ScenarioLockError(ValueError):
    """A package cannot produce the accepted non-circular lock."""


def _portable_relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or "." in path.parts
        or path.as_posix() != value
        or "\\" in value
        or ":" in value
        or "\x00" in value
    ):
        raise ScenarioLockError(f"package path is not portable: {value}")
    return value


def project_resource_root(source_name: str, packaged_name: str) -> Path:
    source = Path(__file__).resolve().parents[3] / source_name
    if source.is_dir():
        return source
    packaged = Path(__file__).resolve().parents[1] / packaged_name
    if packaged.is_dir():
        return packaged
    raise ScenarioLockError(f"published {source_name} resources are unavailable")


def schema_root_path() -> Path:
    return project_resource_root("schemas", "published_schemas")


def standard_profile_path() -> Path:
    path = project_resource_root("profiles", "published_profiles") / "standard-v1.yaml"
    if not path.is_file():
        raise ScenarioLockError("standard-v1 profile is unavailable")
    return path


def scaffold_root_path() -> Path:
    return project_resource_root("scaffolds", "published_scaffolds")


def _file_role(relative: str, manifest: dict[str, Any]) -> tuple[str, bool]:
    if relative == "instruction.md":
        return "developer-brief", True
    if relative == "scenario.yaml":
        return "project-declaration", False
    if relative == "task.toml":
        return "harbor-task", False
    if relative.startswith("tests/"):
        return "verifier-only", False
    if relative.startswith("solution/"):
        return "author-only", False
    if relative.startswith("seed/"):
        return "trusted-provisioning", False
    if relative.startswith("environment/capture/"):
        return "trusted-submission-capture", False
    if relative.startswith("environment/"):
        return "agent-image-input", True
    if relative.startswith("data/"):
        datasets = manifest["repository"]["datasets"]
        visible = any(
            entry["path"] == relative and entry["visibility"] == "agent"
            for entry in datasets
        )
        return "agent-resource" if visible else "verifier-resource", visible
    raise ScenarioLockError(f"file is outside the canonical package layout: {relative}")


def _inventory(package: Path, manifest: dict[str, Any]) -> list[dict[str, object]]:
    files: list[dict[str, object]] = []
    allowed_roots = {
        "data",
        "environment",
        "instruction.md",
        "scenario.lock.json",
        "scenario.yaml",
        "seed",
        "solution",
        "task.toml",
        "tests",
    }
    for child in package.iterdir():
        if child.name not in allowed_roots:
            raise ScenarioLockError(f"unknown or transient package path: {child.name}")
    relative_paths: set[str] = set()
    casefolded_paths: set[str] = set()
    for path in sorted(package.rglob("*")):
        if path.name == "scenario.lock.json" and path.parent == package:
            continue
        if path.is_symlink():
            raise ScenarioLockError(f"package cannot contain symlinks: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ScenarioLockError(f"package path is not a regular file: {path}")
        relative = _portable_relative_path(path.relative_to(package).as_posix())
        if relative in relative_paths or relative.casefold() in casefolded_paths:
            raise ScenarioLockError(f"package path collides by case: {relative}")
        relative_paths.add(relative)
        casefolded_paths.add(relative.casefold())
        role, agent_visible = _file_role(relative, manifest)
        mode = stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)
        if mode not in {0o644, 0o755}:
            raise ScenarioLockError(
                f"package file has noncanonical mode {mode:04o}: {relative}"
            )
        data = path.read_bytes()
        files.append(
            {
                "agent_visible": agent_visible,
                "mode": f"{mode:04o}",
                "bytes": len(data),
                "path": relative,
                "role": role,
                "sha256": str(TypedDigest.from_bytes(DigestKind.ARTIFACT, data)),
            }
        )
    if not files:
        raise ScenarioLockError("package payload is empty")
    return files


def _require_declared_file(
    package: Path,
    relative: str,
    expected: str,
    label: str,
) -> None:
    path = package / relative
    if path.is_symlink() or not path.is_file():
        raise ScenarioLockError(f"{label} file is missing: {relative}")
    actual = str(TypedDigest.from_bytes(DigestKind.ARTIFACT, path.read_bytes()))
    if actual != expected:
        raise ScenarioLockError(f"{label} digest mismatch: {relative}")


def _resolve_declared_inputs(package: Path, manifest: dict[str, Any]) -> dict[str, object]:
    repository = manifest["repository"]
    pristine = repository["pristine"]
    archive = pristine["archive"]
    if archive is not None:
        _require_declared_file(
            package,
            archive,
            pristine["archive_sha256"],
            "pristine archive",
        )
    for seed in repository["seed_inputs"]:
        _require_declared_file(package, seed["path"], seed["sha256"], "seed input")
    for dataset in repository["datasets"]:
        _require_declared_file(package, dataset["path"], dataset["sha256"], "dataset")
    return {
        "datasets": repository["datasets"],
        "pristine": pristine,
        "scenario_baseline": repository["baseline_tree_sha256"],
        "seed_inputs": repository["seed_inputs"],
    }


def _dockerfile_images(path: Path) -> set[str]:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ScenarioLockError(f"cannot read Dockerfile {path}: {error}") from error
    logical_lines: list[str] = []
    current = ""
    for physical_line in content.splitlines():
        stripped = physical_line.rstrip()
        if stripped.endswith("\\"):
            current += stripped[:-1] + " "
            continue
        logical_lines.append(current + physical_line)
        current = ""
    if current:
        raise ScenarioLockError(f"Dockerfile has an unterminated continuation: {path}")

    references: set[str] = set()
    local_stages: set[str] = set()
    stage_index = 0

    def add_external(candidate: str) -> None:
        reference = candidate.strip("\"'")
        if reference and reference not in local_stages and not reference.isdecimal():
            references.add(reference)

    for raw_line in logical_lines:
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        instruction, _, arguments = line.partition(" ")
        if instruction.upper() == "FROM":
            tokens = arguments.split()
            candidates = [token for token in tokens if not token.startswith("--")]
            if not candidates:
                raise ScenarioLockError(f"Dockerfile has malformed FROM: {path}")
            add_external(candidates[0])
            local_stages.add(str(stage_index))
            stage_index += 1
            for index, token in enumerate(tokens[:-1]):
                if token.upper() == "AS":
                    local_stages.add(tokens[index + 1])
                    break
            continue
        for match in re.finditer(r"(?:^|\s)--from(?:=|\s+)([^\s]+)", arguments):
            add_external(match.group(1))
        for match in re.finditer(r"(?:^|\s)--mount=([^\s]+)", arguments):
            mount = match.group(1).strip("\"'")
            for option in mount.split(","):
                key, separator, value = option.partition("=")
                if separator and key == "from":
                    add_external(value)
    return references


def _walk_docker_image_fields(value: object) -> set[str]:
    references: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "docker_image" and isinstance(child, str):
                references.add(child)
            references.update(_walk_docker_image_fields(child))
    elif isinstance(value, list):
        for child in value:
            references.update(_walk_docker_image_fields(child))
    return references


def _image_references(package: Path) -> list[dict[str, str]]:
    references: set[str] = set()
    for dockerfile in sorted(package.rglob("Dockerfile")):
        references.update(_dockerfile_images(dockerfile))
    for compose_path in sorted(package.rglob("docker-compose.y*ml")):
        try:
            compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as error:
            raise ScenarioLockError(f"invalid compose file {compose_path}: {error}") from error
        if not isinstance(compose, dict) or not isinstance(compose.get("services"), dict):
            raise ScenarioLockError(f"compose services are missing: {compose_path}")
        for service in compose["services"].values():
            if isinstance(service, dict) and isinstance(service.get("image"), str):
                references.add(service["image"])
    try:
        task = tomllib.loads((package / "task.toml").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise ScenarioLockError(f"invalid task.toml: {error}") from error
    references.update(_walk_docker_image_fields(task))
    if not references:
        raise ScenarioLockError("package declares no immutable OCI image")
    resolved: list[dict[str, str]] = []
    for reference in sorted(references):
        match = _IMAGE_REFERENCE.fullmatch(reference)
        if match is None:
            raise ScenarioLockError(f"Docker image is not digest-pinned: {reference}")
        resolved.append(
            {
                "identity": str(TypedDigest(DigestKind.OCI_IMAGE, match.group(1))),
                "reference": reference,
            }
        )
    return resolved


def build_scenario_lock(
    package: Path,
    manifest: dict[str, Any],
    *,
    harbor_content_hash: str,
) -> tuple[dict[str, object], bytes]:
    """Build lock bytes over every canonical input except the lock itself."""
    if re.fullmatch(r"[0-9a-f]{64}", harbor_content_hash) is None:
        raise ScenarioLockError("pinned Harbor returned a malformed task content hash")
    files = _inventory(package, manifest)
    payload_digest = TypedDigest.from_bytes(
        DigestKind.PACKAGE_PAYLOAD,
        canonical_json_bytes({"files": files}),
    )
    scenario_section = manifest["scenario"]
    verification = manifest["verification"]
    scenario_identity = ScenarioIdentity.from_payload(
        scenario_section["version"],
        {
            "environment_files": [
                entry
                for entry in files
                if str(entry["path"]).startswith("environment/")
            ],
            "instruction": manifest["instruction"],
            "repository": manifest["repository"],
            "scenario": scenario_section,
            "submission": manifest["submission"],
        },
    )
    verifier_identity = VerifierIdentity.from_payload(
        verification["verifier"]["version"],
        {
            "files": [
                entry
                for entry in files
                if entry["role"]
                in {"trusted-submission-capture", "verifier-only", "verifier-resource"}
            ],
            "qualification": verification["qualification"],
            "verifier": verification["verifier"],
        },
    )
    score_identity = ScoreContractIdentity.from_payload(
        verification["score_contract"]["version"],
        {
            "check_groups": verification["check_groups"],
            "domain_scores": verification["domain_scores"],
            "score_contract": verification["score_contract"],
            "total_scoring": verification["total_scoring"],
        },
    )
    registry = SchemaRegistry(schema_root_path())
    lock: dict[str, object] = {
        "harbor": {
            "commit": HARBOR_COMMIT,
            "task_content_sha256": str(
                TypedDigest(DigestKind.HARBOR_TASK, harbor_content_hash)
            ),
        },
        "identities": {
            "scenario": {
                "digest": str(scenario_identity.digest),
                "kind": "scenario",
                "version": scenario_identity.version,
            },
            "score_contract": {
                "digest": str(score_identity.digest),
                "kind": "score-contract",
                "version": score_identity.version,
            },
            "verifier": {
                "digest": str(verifier_identity.digest),
                "kind": "verifier",
                "version": verifier_identity.version,
            },
        },
        "package": {
            "files": files,
            "payload_sha256": str(payload_digest),
        },
        "resolved_inputs": {
            **_resolve_declared_inputs(package, manifest),
            "images": _image_references(package),
        },
        "scenario_id": scenario_section["id"],
        "schema": registry.envelope(LOCK_SCHEMA_NAME, LOCK_SCHEMA_VERSION),
        "standard_v1": {
            "id": "standard-v1",
            "sha256": str(
                TypedDigest.from_bytes(
                    DigestKind.EXECUTION_PROFILE,
                    standard_profile_path().read_bytes(),
                )
            ),
        },
    }
    try:
        registry.validate_value(lock, name=LOCK_SCHEMA_NAME, version=LOCK_SCHEMA_VERSION)
    except SchemaValidationError as error:
        raise ScenarioLockError(f"generated lock is invalid: {error}") from error
    return lock, canonical_json_bytes(lock)

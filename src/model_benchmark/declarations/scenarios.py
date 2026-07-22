from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Hashable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

import yaml
from yaml.constructor import ConstructorError
from yaml.events import AliasEvent
from yaml.nodes import MappingNode, Node

from model_benchmark.declarations.identities import DigestKind, TypedDigest
from model_benchmark.declarations.scenario_locks import (
    HARBOR_COMMIT,
    ScenarioLockError,
    build_scenario_lock,
    scaffold_root_path,
    schema_root_path,
    standard_profile_path,
)
from model_benchmark.declarations.scenario_schema import (
    ScenarioContractError,
    validate_scenario_manifest,
)
from model_benchmark.declarations.scenario_sources import (
    ScenarioSourceError,
    normalized_tree_digest,
    verify_source_reconstruction,
)
from model_benchmark.declarations.schemas import SchemaRegistry, SchemaValidationError


_STANDARD_PROFILE = "standard-v1"
_HIDDEN_MARKER = "MODEL_BENCHMARK_HIDDEN:replace-with-private-verifier-canary"
_SAFE_MATERIALIZATION_PATH = re.compile(r"[A-Za-z0-9._/-]+")
_SAFE_MEDIA_TYPE = re.compile(r"[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+")
_CAPTURE_IMAGE = (
    "python:3.12.12-slim-bookworm@sha256:"
    "593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c"
)
_SCENARIO_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*$")
_TOP_LEVEL_SECTIONS = (
    "schema_version",
    "scenario",
    "repository",
    "instruction",
    "submission",
    "verification",
    "provenance",
)
_ECOSYSTEMS = (
    "angular-typescript",
    "react-javascript",
    "spring-boot-java",
    "python-data-engineering",
)


class ScenarioPackageError(ValueError):
    """A Scenario Package failed a strict authoring or qualification contract."""

    def __init__(self, classification: str, message: str) -> None:
        super().__init__(message)
        self.classification = classification

    def summary(self) -> dict[str, object]:
        return {
            "classification": self.classification,
            "message": str(self),
            "status": "rejected",
        }


class _StrictYamlLoader(yaml.SafeLoader):
    def compose_node(self, parent: Node | None, index: int) -> Node | None:
        if self.check_event(AliasEvent):
            raise ConstructorError(None, None, "YAML aliases are forbidden", self.peek_event().start_mark)
        event = self.peek_event()
        if getattr(event, "anchor", None) is not None:
            raise ConstructorError(None, None, "YAML anchors are forbidden", event.start_mark)
        return super().compose_node(parent, index)

    def flatten_mapping(self, node: MappingNode) -> None:
        if any(key.value == "<<" for key, _ in node.value):
            raise ConstructorError(None, None, "YAML merge keys are forbidden", node.start_mark)
        super().flatten_mapping(node)

    def construct_mapping(
        self,
        node: MappingNode,
        deep: bool = False,
    ) -> dict[Hashable, Any]:
        keys: set[Hashable] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, Hashable):
                raise ConstructorError(
                    None,
                    None,
                    "YAML mapping keys must be scalar",
                    key_node.start_mark,
                )
            if key in keys:
                raise ConstructorError(
                    None,
                    None,
                    f"duplicate YAML key: {key!r}",
                    key_node.start_mark,
                )
            keys.add(key)
        return super().construct_mapping(node, deep=deep)


def _load_yaml(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = yaml.load(
            path.read_text(encoding="utf-8"),
            Loader=_StrictYamlLoader,
        )
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ScenarioPackageError(f"invalid-{label}", str(error)) from error
    if not isinstance(value, dict):
        raise ScenarioPackageError(f"invalid-{label}", f"{label} must be an object")
    return value


def _typed_artifact(data: bytes) -> str:
    return str(TypedDigest.from_bytes(DigestKind.ARTIFACT, data))


def _write_text(path: Path, content: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    if executable:
        path.chmod(0o755)


def _atomic_verified_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
        if path.read_bytes() != data:
            raise OSError("authoritative artifact read-back mismatch")
    except OSError:
        temporary.unlink(missing_ok=True)
        path.unlink(missing_ok=True)
        raise


def _immutable_verified_write(path: Path, data: bytes) -> None:
    """Publish bytes atomically without replacing a prior declaration."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != data:
            raise FileExistsError(f"immutable declaration already exists: {path}")
        return
    temporary_path: Path | None = None
    published = False
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.link(temporary_path, path)
        published = True
        if path.read_bytes() != data:
            raise OSError(f"read-back mismatch for {path}")
    except FileExistsError:
        if path.is_symlink() or not path.is_file() or path.read_bytes() != data:
            raise
    except BaseException:
        if published:
            path.unlink(missing_ok=True)
        raise
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _standard_profile() -> dict[str, Any]:
    profile = _load_yaml(standard_profile_path(), label="standard-v1-profile")
    if set(profile) != {"schema_version", "id", "trusted_capture", "container_limits", "harbor_task"}:
        raise ScenarioPackageError(
            "invalid-standard-v1-profile",
            "standard-v1 has unknown or missing fields",
        )
    harbor = profile["harbor_task"]
    if not isinstance(harbor, dict) or set(harbor) != {
        "agent",
        "environment",
        "verifier",
        "version",
    }:
        raise ScenarioPackageError(
            "invalid-standard-v1-profile",
            "standard-v1 Harbor task expansion is not strict",
        )
    expected_sections = {
        "agent": {"network_mode", "timeout_sec", "user"},
        "environment": {
            "build_timeout_sec",
            "cpus",
            "memory_mb",
            "network_mode",
            "storage_mb",
            "workdir",
        },
        "verifier": {
            "environment_mode",
            "network_mode",
            "timeout_sec",
            "user",
        },
    }
    for name, fields in expected_sections.items():
        value = harbor.get(name)
        if not isinstance(value, dict) or set(value) != fields:
            raise ScenarioPackageError(
                "invalid-standard-v1-profile",
                f"standard-v1 {name} section is not strict",
            )
    if profile["schema_version"] != 1 or profile["id"] != _STANDARD_PROFILE:
        raise ScenarioPackageError(
            "invalid-standard-v1-profile",
            "standard-v1 identity mismatch",
        )
    trusted_capture = profile["trusted_capture"]
    if (
        not isinstance(trusted_capture, dict)
        or set(trusted_capture) != {"source_sha256"}
        or re.fullmatch(
            r"artifact:sha256:[0-9a-f]{64}",
            trusted_capture.get("source_sha256", ""),
        )
        is None
    ):
        raise ScenarioPackageError(
            "invalid-standard-v1-profile",
            "standard-v1 trusted capture identity is invalid",
        )
    container_limits = profile["container_limits"]
    if (
        not isinstance(container_limits, dict)
        or set(container_limits) != {"process_count"}
        or not isinstance(container_limits["process_count"], int)
        or container_limits["process_count"] < 1
    ):
        raise ScenarioPackageError(
            "invalid-standard-v1-profile",
            "standard-v1 process ceiling is invalid",
        )
    if harbor["agent"]["timeout_sec"] is not None:
        raise ScenarioPackageError(
            "invalid-standard-v1-profile",
            "standard-v1 must use observational agent elapsed time",
        )
    return profile


def _scaffold_definition(ecosystem: str) -> dict[str, Any]:
    definition = _load_yaml(
        scaffold_root_path() / ecosystem / "scaffold.yaml",
        label="scaffold",
    )
    expected = {
        "base_image",
        "build_example",
        "ecosystem",
        "schema_version",
        "test_example",
        "working_directory",
    }
    if set(definition) != expected or definition.get("schema_version") != 1:
        raise ScenarioPackageError("invalid-scaffold", "scaffold definition is not strict")
    if definition.get("ecosystem") != ecosystem:
        raise ScenarioPackageError("invalid-scaffold", "scaffold ecosystem mismatch")
    image = definition.get("base_image")
    if not isinstance(image, str) or re.fullmatch(
        r"[^\s@]+@sha256:[0-9a-f]{64}", image
    ) is None:
        raise ScenarioPackageError("invalid-scaffold", "scaffold image is not immutable")
    if not all(
        isinstance(definition[field], str) and definition[field]
        for field in ("build_example", "test_example", "working_directory")
    ):
        raise ScenarioPackageError("invalid-scaffold", "scaffold text fields are invalid")
    return definition


def _capture_collect_hook() -> dict[str, object]:
    return {
        "service": "capture",
        "command": (
            "python3 /opt/capture/capture.py --repository /input/repository "
            "--baseline /opt/capture/baseline --policy /opt/capture/policy.json "
            "--output /capture"
        ),
        "timeout_sec": 30.0,
    }


def _artifact_collect_hook(submission: dict[str, Any]) -> dict[str, object]:
    allowed_paths = submission["allowed_paths"]
    materialization = submission["materialization"]
    destination = materialization["destination"]
    destination_path = PurePosixPath(destination)
    if (
        len(allowed_paths) != 1
        or _SAFE_MATERIALIZATION_PATH.fullmatch(allowed_paths[0]) is None
        or _SAFE_MATERIALIZATION_PATH.fullmatch(destination) is None
        or not destination_path.is_absolute()
        or len(destination_path.parts) <= 2
        or destination_path.parts[:2] != ("/", "capture")
        or any(part in {"", ".", ".."} for part in destination_path.parts[2:])
        or destination_path.as_posix() != destination
        or materialization["service"] != "capture"
        or materialization["mode"] != "copy-no-follow"
        or _SAFE_MEDIA_TYPE.fullmatch(submission["media_type"]) is None
    ):
        raise ScenarioPackageError(
            "invalid-submission-materialization",
            "non-patch output must use one safe path and the trusted capture service",
        )
    source = f"/input/repository/{allowed_paths[0]}"
    schema = submission["schema"]
    command = (
        f"python3 /opt/capture/capture.py --artifact-source {source} "
        f"--artifact-output {destination} "
        "--artifact-record /capture/materialization.json "
        f"--artifact-media-type {submission['media_type']} "
        f"--artifact-schema-sha256 {schema['sha256']} "
        f"--artifact-max-bytes {submission['max_bytes']} "
        f"--visibility-root /input/repository --forbidden-marker {_HIDDEN_MARKER} "
        "--stability-window-ms 250"
    )
    return {"service": "capture", "command": command, "timeout_sec": 30.0}


def _capture_compose() -> dict[str, object]:
    process_count = _standard_profile()["container_limits"]["process_count"]
    sandbox = {
        "cap_drop": ["ALL"],
        "pids_limit": process_count,
        "read_only": True,
        "security_opt": ["no-new-privileges:true"],
    }
    return {
        "services": {
            "main": {
                **sandbox,
                "tmpfs": [
                    "/solution:rw,exec,nosuid,nodev,size=1m,mode=0755",
                    "/tmp:rw,noexec,nosuid,nodev,size=64m",
                ],
                "volumes": ["trial-repository:/workspace"],
            },
            "capture": {
                **sandbox,
                "build": {"context": ".", "dockerfile": "capture/Dockerfile"},
                "command": ["sh", "-c", "sleep infinity"],
                "depends_on": {"main": {"condition": "service_started"}},
                "network_mode": "none",
                "tmpfs": [
                    "/tmp:rw,noexec,nosuid,nodev,size=16m",
                ],
                "volumes": [
                    "capture-output:/capture",
                    "trial-repository:/input:ro",
                ],
            },
        },
        "volumes": {"capture-output": None, "trial-repository": None},
    }


def _capture_dockerfile() -> str:
    return (
        f"FROM {_CAPTURE_IMAGE}\n"
        "WORKDIR /opt/capture\n"
        "COPY capture/capture.py capture/policy.json /opt/capture/\n"
        "COPY baseline/ /opt/capture/baseline/\n"
        "RUN --network=none chmod -R a=rX /opt/capture && "
        "install -d -o 65532 -g 65532 -m 0700 /capture\n"
        "USER 65532:65532\n"
    )


def _task_toml(scenario_id: str, profile: dict[str, Any]) -> str:
    task = profile["harbor_task"]
    verifier = task["verifier"]
    agent = task["agent"]
    environment = task["environment"]
    return f'''version = "{task["version"]}"

artifacts = [
  {{ source = "/capture/capture.json", service = "capture" }},
  {{ source = "/capture/submission.patch", service = "capture" }},
]

[task]
name = "{scenario_id}"
description = "TODO: describe the professional Scenario without answer leakage."
keywords = ["model-benchmark", "standard-v1"]

[verifier]
timeout_sec = {verifier["timeout_sec"]}.0
environment_mode = "{verifier["environment_mode"]}"
network_mode = "{verifier["network_mode"]}"
user = {verifier["user"]}

[[verifier.collect]]
service = "capture"
command = "python3 /opt/capture/capture.py --repository /input/repository --baseline /opt/capture/baseline --policy /opt/capture/policy.json --output /capture"
timeout_sec = 30.0

[agent]
network_mode = "{agent["network_mode"]}"
user = {agent["user"]}

[environment]
build_timeout_sec = {environment["build_timeout_sec"]}.0
workdir = "{environment["workdir"]}"
network_mode = "{environment["network_mode"]}"
cpus = {environment["cpus"]}
memory_mb = {environment["memory_mb"]}
storage_mb = {environment["storage_mb"]}
'''


def _scenario_manifest(
    *,
    scenario_id: str,
    ecosystem: str,
    visibility: str,
    instruction_bytes: bytes,
) -> dict[str, object]:
    empty_tree = str(
        TypedDigest(kind=DigestKind.SOURCE_TREE, value=hashlib.sha256().hexdigest())
    )
    return {
        "schema_version": 1,
        "scenario": {
            "id": scenario_id,
            "version": "0.1.0",
            "lifecycle_state": "candidate",
            "visibility": visibility,
            "ecosystem": ecosystem,
            "workload_family": "bounded-feature-implementation",
            "difficulty": "standard",
            "execution_profile": _STANDARD_PROFILE,
        },
        "repository": {
            "pristine": {
                "origin": f"urn:model-benchmark:scaffold:{scenario_id}",
                "commit": "0" * 40,
                "archive": None,
                "archive_sha256": None,
                "tree_sha256": empty_tree,
                "license": "NOASSERTION",
            },
            "seed_inputs": [],
            "baseline_tree_sha256": empty_tree,
            "datasets": [],
        },
        "instruction": {
            "path": "instruction.md",
            "sha256": _typed_artifact(instruction_bytes),
        },
        "submission": {
            "kind": "git-patch",
            "repository_root": "/workspace/repository",
            "allowed_paths": ["*", "**/*"],
            "protected_paths": [".git/**"],
            "allow_additions": True,
            "allow_deletions": True,
            "max_files": 100,
            "max_bytes": 1_000_000,
            "symlinks": "reject",
            "executable_bits": "reject",
            "submodules": "reject",
            "nested_repositories": "reject",
            "binary_files": "reject",
        },
        "verification": {
            "verifier": {"version": "0.1.0"},
            "score_contract": {"version": "0.1.0"},
            "check_groups": [
                {
                    "id": "acceptance",
                    "class": "acceptance",
                    "required": True,
                    "weight": "1",
                    "score_direction": "maximize",
                    "evidence_key": "acceptance",
                },
                {
                    "id": "regression",
                    "class": "regression",
                    "required": True,
                    "weight": "1",
                    "score_direction": "maximize",
                    "evidence_key": "regression",
                },
            ],
            "domain_scores": [],
            "qualification": {
                "baseline_score_vector": [
                    {"name": "acceptance_score", "value": "0"},
                    {"name": "regression_score", "value": "1"},
                    {"name": "task_success", "value": "0"},
                ],
                "reference_score_vector": [
                    {"name": "acceptance_score", "value": "1"},
                    {"name": "regression_score", "value": "1"},
                    {"name": "task_success", "value": "1"},
                ],
            },
            "total_scoring": {
                "safe_partial": "score-declared-groups",
                "missing": "score-zero",
                "malformed": "reject-score-zero",
                "oversized": "reject-score-zero",
                "unsafe": "reject-score-zero",
            },
        },
        "provenance": {
            "authors": [f"urn:model-benchmark:author:{scenario_id}"],
            "source_references": [],
            "licenses": ["NOASSERTION"],
            "contamination_disclosures": [],
        },
    }


def scaffold_scenario_package(
    *,
    path: Path,
    scenario_id: str,
    ecosystem: str,
    visibility: str,
    trusted_capture_source: str,
) -> dict[str, object]:
    """Create one minimal candidate through the production authoring seam."""
    if _SCENARIO_ID.fullmatch(scenario_id) is None:
        raise ScenarioPackageError("invalid-scenario-id", "scenario ID must be org/name")
    if ecosystem not in _ECOSYSTEMS:
        raise ScenarioPackageError("invalid-ecosystem", f"unsupported ecosystem: {ecosystem}")
    if visibility not in {"public", "private"}:
        raise ScenarioPackageError("invalid-visibility", visibility)
    if path.exists():
        raise ScenarioPackageError("path-exists", f"scaffold path already exists: {path}")
    profile = _standard_profile()
    expected_capture = profile["trusted_capture"]["source_sha256"]
    if _typed_artifact(trusted_capture_source.encode("utf-8")) != expected_capture:
        raise ScenarioPackageError(
            "invalid-scaffold",
            "evidence-owned capture source does not match standard-v1",
        )
    definition = _scaffold_definition(ecosystem)
    instruction = (
        "# Developer Brief\n\n"
        "TODO: state observable behavior, legitimate constraints, and allowed deliverables.\n"
    ).encode("utf-8")
    try:
        path.mkdir(parents=True)
        _write_text(path / "instruction.md", instruction.decode("utf-8"))
        manifest = _scenario_manifest(
            scenario_id=scenario_id,
            ecosystem=ecosystem,
            visibility=visibility,
            instruction_bytes=instruction,
        )
        _write_text(
            path / "scenario.yaml",
            yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
        )
        _write_text(path / "task.toml", _task_toml(scenario_id, profile))
        image = definition["base_image"]
        environment = profile["harbor_task"]["environment"]
        (path / "environment/baseline").mkdir(parents=True)
        _write_text(
            path / "environment/Dockerfile",
            f"FROM {image}\n"
            "USER root\n"
            f"COPY baseline/ {environment['workdir']}/\n"
            f"RUN --network=none mkdir -p {environment['workdir']} && "
            f"chown {profile['harbor_task']['agent']['user']}:"
            f"{profile['harbor_task']['agent']['user']} {environment['workdir']} && "
            f"chmod -R a+rwX {environment['workdir']}\n"
            f"USER {profile['harbor_task']['agent']['user']}\n"
            f"WORKDIR {environment['workdir']}\n"
            f"# Example build: {definition['build_example']}\n",
        )
        _write_text(
            path / "environment/docker-compose.yaml",
            yaml.safe_dump(json.loads(json.dumps(_capture_compose())), sort_keys=False),
        )
        _write_text(
            path / "environment/capture/Dockerfile",
            _capture_dockerfile(),
        )
        _write_text(path / "environment/capture/capture.py", trusted_capture_source)
        submission = cast(dict[str, Any], manifest["submission"])
        _write_text(
            path / "environment/capture/policy.json",
            json.dumps(
                {
                    "allowed_paths": submission["allowed_paths"],
                    "protected_paths": submission["protected_paths"],
                    "allow_additions": submission["allow_additions"],
                    "allow_deletions": submission["allow_deletions"],
                    "forbidden_markers": [_HIDDEN_MARKER],
                    "max_file_count": submission["max_files"],
                    "max_total_bytes": submission["max_bytes"],
                    "stability_window_ms": 250,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
        )
        _write_text(
            path / "tests/Dockerfile",
            f"FROM {image}\n"
            "USER root\n"
            "COPY . /tests/\n"
            "RUN --network=none chmod +x /tests/test.sh\n"
            f"USER {profile['harbor_task']['verifier']['user']}\n"
            f"WORKDIR {environment['workdir']}\n"
            f"# Example test: {definition['test_example']}\n",
        )
        _write_text(
            path / "tests/test.sh",
            "#!/bin/sh\n"
            f"# {_HIDDEN_MARKER}\n"
            "set -eu\n"
            f"prlimit --pid $$ --nproc={profile['container_limits']['process_count']}:{profile['container_limits']['process_count']}\n"
            "mkdir -p /logs/verifier\n"
            "if grep -q '\"status\":\"accepted\"' /capture/capture.json; then\n"
            "  regression=1; regression_status=pass\n"
            "else\n"
            "  regression=0; regression_status=fail\n"
            "fi\n"
            "if [ \"${regression}\" = 1 ] && "
            "grep -q '\"kind\":\"patch\"' /capture/capture.json; then\n"
            "  acceptance=1; task_success=true; acceptance_status=pass\n"
            "else\n"
            "  acceptance=0; task_success=false; acceptance_status=fail\n"
            "fi\n"
            "printf '%s\\n' "
            "\"{\\\"acceptance_score\\\":${acceptance},\\\"checks\\\":[{\\\"evidence\\\":[\\\"capture/capture.json\\\"],\\\"id\\\":\\\"acceptance\\\",\\\"status\\\":\\\"${acceptance_status}\\\"},{\\\"evidence\\\":[\\\"tests/test.sh\\\"],\\\"id\\\":\\\"regression\\\",\\\"status\\\":\\\"${regression_status}\\\"}],\\\"domain_scores\\\":{},\\\"regression_score\\\":${regression},\\\"required_group_statuses\\\":{\\\"acceptance\\\":\\\"${acceptance_status}\\\",\\\"regression\\\":\\\"${regression_status}\\\"},\\\"task_success\\\":${task_success},\\\"verifier_complete\\\":true}\" "
            "> /logs/verifier/verifier-result.json\n"
            "printf '%s\\n' "
            "\"{\\\"acceptance_score\\\":${acceptance},\\\"regression_score\\\":${regression},\\\"task_success\\\":${acceptance}}\" "
            "> /logs/verifier/reward.json\n",
            executable=True,
        )
        _write_text(path / "tests/private-canary.txt", f"{_HIDDEN_MARKER}\n")
        _write_text(
            path / "solution/solve.sh",
            "#!/bin/sh\n"
            "# MODEL_BENCHMARK_HIDDEN:replace-with-reference-solution-canary\n"
            "set -eu\n"
            f"printf '%s\\n' solved > {environment['workdir']}/reference-result.txt\n",
            executable=True,
        )
    except BaseException:
        shutil.rmtree(path, ignore_errors=True)
        raise
    return {
        "message": f"scaffolded candidate Scenario Package at {path}",
        "path": str(path.resolve()),
        "scenario_id": scenario_id,
        "status": "candidate",
    }


def _load_manifest(path: Path) -> dict[str, Any]:
    value = _load_yaml(path / "scenario.yaml", label="scenario-yaml")
    if tuple(value) != _TOP_LEVEL_SECTIONS:
        raise ScenarioPackageError(
            "invalid-scenario-schema",
            "scenario.yaml must contain exactly the seven canonical sections",
        )
    registry = SchemaRegistry(schema_root_path())
    try:
        validate_scenario_manifest(value, registry=registry)
    except ScenarioContractError as error:
        raise ScenarioPackageError("invalid-scenario-schema", str(error)) from error
    return value


def _check_instruction(path: Path, manifest: dict[str, Any]) -> bytes:
    try:
        data = (path / "instruction.md").read_bytes()
        text = data.decode("utf-8", errors="strict")
    except (OSError, UnicodeError) as error:
        raise ScenarioPackageError("invalid-instruction", str(error)) from error
    if text.startswith("\ufeff") or "\r" in text or not text.endswith("\n"):
        raise ScenarioPackageError(
            "invalid-instruction",
            "Developer Brief must be normalized UTF-8 with LF endings",
        )
    if manifest["instruction"]["sha256"] != _typed_artifact(data):
        raise ScenarioPackageError(
            "instruction-digest-mismatch",
            "Developer Brief digest mismatch",
        )
    return data


def _check_offline_builds(path: Path) -> None:
    dockerfiles = sorted(path.rglob("Dockerfile"))
    if not dockerfiles:
        raise ScenarioPackageError("invalid-build-input", "package has no Dockerfiles")
    for dockerfile in dockerfiles:
        try:
            text = dockerfile.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise ScenarioPackageError("invalid-build-input", str(error)) from error
        logical_lines = re.sub(r"\\\n[ \t]*", " ", text).splitlines()
        for raw_line in logical_lines:
            instruction = raw_line.strip()
            upper = instruction.upper()
            if upper.startswith("FROM ") and re.search(
                r"@sha256:[0-9a-f]{64}(?:\s+AS\s+\S+)?$", instruction, re.IGNORECASE
            ) is None:
                raise ScenarioPackageError(
                    "mutable-build-input",
                    f"Dockerfile FROM must use an immutable digest: {dockerfile}",
                )
            if upper.startswith("RUN ") and not upper.startswith("RUN --NETWORK=NONE "):
                raise ScenarioPackageError(
                    "download-capable-build",
                    f"Dockerfile RUN must declare --network=none: {dockerfile}",
                )
            if upper.startswith("ADD ") and re.search(r"(?:HTTPS?|GIT)://", instruction, re.IGNORECASE):
                raise ScenarioPackageError(
                    "download-capable-build",
                    f"Dockerfile ADD cannot use a remote source: {dockerfile}",
                )


def _check_answer_leakage(path: Path, manifest: dict[str, Any]) -> None:
    hidden_files = [
        candidate
        for root in (path / "tests", path / "solution")
        for candidate in root.rglob("*")
        if candidate.is_file() and not candidate.is_symlink()
    ]
    marker_pattern = re.compile(rb"MODEL_BENCHMARK_HIDDEN:[^\r\n]+")
    markers = {
        marker
        for hidden in hidden_files
        for marker in marker_pattern.findall(hidden.read_bytes())
    }
    verifier_files = [
        candidate
        for candidate in (path / "tests").rglob("*")
        if candidate.is_file() and not candidate.is_symlink()
    ]
    if not any(_HIDDEN_MARKER.encode("utf-8") in item.read_bytes() for item in verifier_files):
        raise ScenarioPackageError(
            "answer-leakage",
            "the capture canary must identify a hidden verifier asset",
        )
    if any(hidden.stat().st_size == 0 for hidden in hidden_files):
        raise ScenarioPackageError(
            "answer-leakage",
            "hidden verifier assets must be non-empty for leakage validation",
        )
    hidden_assets = [hidden.read_bytes() for hidden in hidden_files]
    agent_visible = [path / "instruction.md"] + [
        candidate
        for candidate in (path / "environment").rglob("*")
        if candidate.is_file()
        and not candidate.is_symlink()
        and not candidate.is_relative_to(path / "environment/capture")
    ]
    agent_visible.extend(
        path / entry["path"]
        for entry in manifest["repository"]["datasets"]
        if entry["visibility"] == "agent"
    )
    for visible in agent_visible:
        try:
            data = visible.read_bytes()
        except OSError as error:
            raise ScenarioPackageError("invalid-agent-input", str(error)) from error
        if marker_pattern.search(data) is not None or any(marker in data for marker in markers) or any(
            hidden_asset in data for hidden_asset in hidden_assets
        ):
            raise ScenarioPackageError(
                "answer-leakage",
                f"hidden asset reached agent-visible input: {visible.relative_to(path)}",
            )


def _check_profile(path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest["scenario"]["execution_profile"] != _STANDARD_PROFILE:
        raise ScenarioPackageError("profile-mismatch", "Scenario must reference standard-v1")
    if manifest["scenario"].get("execution_profile_exception") is not None:
        raise ScenarioPackageError(
            "unsupported-profile-exception",
            "standard-v1 exceptions require a future trusted approval registry",
        )
    try:
        task = tomllib.loads((path / "task.toml").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise ScenarioPackageError("invalid-harbor-task", str(error)) from error
    profile = _standard_profile()["harbor_task"]
    expected = {
        ("verifier", "environment_mode"): profile["verifier"]["environment_mode"],
        ("verifier", "network_mode"): profile["verifier"]["network_mode"],
        ("verifier", "timeout_sec"): float(profile["verifier"]["timeout_sec"]),
        ("verifier", "user"): profile["verifier"]["user"],
        ("agent", "network_mode"): profile["agent"]["network_mode"],
        ("agent", "user"): profile["agent"]["user"],
        ("environment", "build_timeout_sec"): float(
            profile["environment"]["build_timeout_sec"]
        ),
        ("environment", "network_mode"): profile["environment"]["network_mode"],
        ("environment", "workdir"): profile["environment"]["workdir"],
        ("environment", "cpus"): profile["environment"]["cpus"],
        ("environment", "memory_mb"): profile["environment"]["memory_mb"],
        ("environment", "storage_mb"): profile["environment"]["storage_mb"],
    }
    if task.get("version") != profile["version"]:
        raise ScenarioPackageError("profile-mismatch", "task.toml version drifted")
    for (section, field), value in expected.items():
        actual_section = task.get(section)
        if not isinstance(actual_section, dict) or actual_section.get(field) != value:
            raise ScenarioPackageError(
                "profile-mismatch",
                f"task.toml {section}.{field} must equal {value!r}",
            )
    agent = task.get("agent")
    if not isinstance(agent, dict) or "timeout_sec" in agent:
        raise ScenarioPackageError(
            "profile-mismatch",
            "standard-v1 forbids wall-clock agent termination",
        )
    return task


def _check_trusted_capture_boundary(
    path: Path,
    *,
    compose: dict[str, Any],
    collect: object,
    expected_hook: dict[str, object],
) -> None:
    if collect != [expected_hook]:
        raise ScenarioPackageError(
            "invalid-submission-materialization",
            "submission requires the exact trusted capture collect hook",
        )
    if compose != _capture_compose():
        raise ScenarioPackageError(
            "invalid-submission-materialization",
            "trusted capture sidecar security boundary drifted",
        )
    capture_path = path / "environment/capture/capture.py"
    capture_dockerfile = path / "environment/capture/Dockerfile"
    try:
        capture_source = capture_path.read_bytes()
        dockerfile_source = capture_dockerfile.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ScenarioPackageError(
            "invalid-submission-materialization",
            f"trusted capture implementation is unreadable: {error}",
        ) from error
    profile = _standard_profile()
    if (
        capture_path.is_symlink()
        or capture_dockerfile.is_symlink()
        or _typed_artifact(capture_source)
        != profile["trusted_capture"]["source_sha256"]
        or dockerfile_source != _capture_dockerfile()
    ):
        raise ScenarioPackageError(
            "invalid-submission-materialization",
            "trusted capture implementation drifted",
        )


def _check_submission_materialization(
    path: Path,
    task: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    submission = manifest["submission"]
    artifacts = task.get("artifacts")
    verifier = task.get("verifier")
    collect = verifier.get("collect") if isinstance(verifier, dict) else None
    compose_path = path / "environment/docker-compose.yaml"
    if not compose_path.is_file() or compose_path.is_symlink():
        raise ScenarioPackageError(
            "invalid-submission-materialization",
            "submission materialization requires docker-compose.yaml",
        )
    compose = _load_yaml(compose_path, label="harbor-compose")
    services = compose.get("services")
    if not isinstance(services, dict):
        raise ScenarioPackageError(
            "invalid-submission-materialization",
            "submission materialization services are missing",
        )
    baseline_path = path / "environment/baseline"
    if baseline_path.is_symlink() or not baseline_path.is_dir():
        raise ScenarioPackageError(
            "invalid-submission-materialization",
            "capture baseline is missing",
        )
    try:
        baseline_digest = str(normalized_tree_digest(baseline_path))
    except ScenarioSourceError as error:
        raise ScenarioPackageError(
            "invalid-submission-materialization",
            str(error),
        ) from error
    if baseline_digest != manifest["repository"]["baseline_tree_sha256"]:
        raise ScenarioPackageError(
            "invalid-submission-materialization",
            "capture baseline does not equal the Scenario Baseline",
        )
    if submission["kind"] == "git-patch":
        expected_artifacts = {
            ("capture", "/capture/capture.json"),
            ("capture", "/capture/submission.patch"),
        }
        actual_artifacts = {
            (artifact.get("service"), artifact.get("source"))
            for artifact in artifacts
            if isinstance(artifact, dict)
        } if isinstance(artifacts, list) else set()
        if actual_artifacts != expected_artifacts:
            raise ScenarioPackageError(
                "invalid-submission-materialization",
                "git-patch submission requires the exact trusted capture artifacts",
            )
        _check_trusted_capture_boundary(
            path,
            compose=compose,
            collect=collect,
            expected_hook=_capture_collect_hook(),
        )
        policy_path = path / "environment/capture/policy.json"
        try:
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ScenarioPackageError(
                "invalid-submission-materialization",
                f"invalid capture policy: {error}",
            ) from error
        if policy != {
            "allowed_paths": submission["allowed_paths"],
            "protected_paths": submission["protected_paths"],
            "allow_additions": submission["allow_additions"],
            "allow_deletions": submission["allow_deletions"],
            "forbidden_markers": [_HIDDEN_MARKER],
            "max_file_count": submission["max_files"],
            "max_total_bytes": submission["max_bytes"],
            "stability_window_ms": 250,
        }:
            raise ScenarioPackageError(
                "invalid-submission-materialization",
                "capture policy does not match the Submission boundary",
            )
        return
    materialization = submission["materialization"]
    service = materialization["service"]
    destination = materialization["destination"]
    expected_artifacts = {
        ("capture", destination),
        ("capture", "/capture/materialization.json"),
    }
    actual_artifacts = {
        (artifact.get("service"), artifact.get("source"))
        for artifact in artifacts
        if isinstance(artifact, dict)
    } if isinstance(artifacts, list) else set()
    if service != "capture" or actual_artifacts != expected_artifacts:
        raise ScenarioPackageError(
            "invalid-submission-materialization",
            "non-patch output requires exact trusted materialization artifacts",
        )
    _check_trusted_capture_boundary(
        path,
        compose=compose,
        collect=collect,
        expected_hook=_artifact_collect_hook(submission),
    )


def _harbor_probe(path: Path) -> dict[str, Any]:
    script = r'''
import importlib.metadata
import json
import sys
import tomllib
from pathlib import Path
from harbor.models.task.task import Task
from harbor.publisher.packager import Packager

def unknown(raw, parsed, prefix=""):
    findings = []
    if isinstance(raw, dict):
        parsed_dict = parsed if isinstance(parsed, dict) else {}
        for key, value in raw.items():
            location = f"{prefix}.{key}" if prefix else key
            if key not in parsed_dict:
                findings.append(location)
            else:
                findings.extend(unknown(value, parsed_dict[key], location))
    elif isinstance(raw, list) and isinstance(parsed, list):
        for index, value in enumerate(raw):
            if index < len(parsed):
                findings.extend(unknown(value, parsed[index], f"{prefix}[{index}]"))
    return findings

root = Path(sys.argv[1])
distribution = importlib.metadata.distribution("harbor")
direct = json.loads(distribution.read_text("direct_url.json") or "{}")
task = Task(root)
content_hash, files = Packager.compute_content_hash(root)
raw = tomllib.loads((root / "task.toml").read_text(encoding="utf-8"))
parsed = task.config.model_dump(mode="json", by_alias=True, exclude_unset=True)
raw_without_version = dict(raw)
raw_without_version.pop("version", None)
print(json.dumps({
    "commit_id": direct.get("vcs_info", {}).get("commit_id"),
    "content_hash": content_hash,
    "instruction_sha256": __import__("hashlib").sha256(task.instruction.encode("utf-8")).hexdigest(),
    "requested_revision": direct.get("vcs_info", {}).get("requested_revision"),
    "task_name": task.name,
    "unknown_fields": unknown(raw_without_version, parsed),
    "valid_directory": Task.is_valid_dir(root),
    "version": distribution.version,
}, sort_keys=True, separators=(",", ":")))
'''
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-c", script, str(path)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ScenarioPackageError("invalid-harbor-task", str(error)) from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ScenarioPackageError("invalid-harbor-task", detail)
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ScenarioPackageError("invalid-harbor-task", "Harbor probe was not JSON") from error
    expected_keys = {
        "commit_id",
        "content_hash",
        "instruction_sha256",
        "requested_revision",
        "task_name",
        "unknown_fields",
        "valid_directory",
        "version",
    }
    if not isinstance(result, dict) or set(result) != expected_keys:
        raise ScenarioPackageError("invalid-harbor-task", "Harbor probe result is malformed")
    if (
        result["version"] != "0.18.0"
        or result["commit_id"] != HARBOR_COMMIT
        or result["requested_revision"] != HARBOR_COMMIT
        or result["valid_directory"] is not True
    ):
        raise ScenarioPackageError(
            "harbor-pin-mismatch",
            "installed Harbor is not exact v0.18.0 commit",
        )
    if result["unknown_fields"]:
        raise ScenarioPackageError(
            "invalid-harbor-task",
            f"task.toml has unknown fields: {result['unknown_fields']}",
        )
    if re.fullmatch(r"[0-9a-f]{64}", str(result["content_hash"])) is None:
        raise ScenarioPackageError("invalid-harbor-task", "Harbor task hash is malformed")
    return result


def _checked_lock_bytes(path: Path) -> tuple[dict[str, Any], bytes, dict[str, Any]]:
    path = path.resolve()
    if not path.is_dir() or path.is_symlink():
        raise ScenarioPackageError("missing-package", f"package directory not found: {path}")
    required_files = ("scenario.yaml", "instruction.md", "task.toml")
    required_directories = ("environment", "tests", "solution")
    for required in required_files:
        candidate = path / required
        if candidate.is_symlink() or not candidate.is_file():
            raise ScenarioPackageError("missing-package-file", f"missing file: {required}")
    for required in required_directories:
        candidate = path / required
        if candidate.is_symlink() or not candidate.is_dir():
            raise ScenarioPackageError("missing-package-file", f"missing directory: {required}")
    manifest = _load_manifest(path)
    try:
        verify_source_reconstruction(path, manifest)
    except ScenarioSourceError as error:
        raise ScenarioPackageError("source-reconstruction-failed", str(error)) from error
    instruction = _check_instruction(path, manifest)
    _check_answer_leakage(path, manifest)
    _check_offline_builds(path)
    task = _check_profile(path, manifest)
    _check_submission_materialization(path, task, manifest)
    harbor = _harbor_probe(path)
    if harbor["task_name"] != manifest["scenario"]["id"]:
        raise ScenarioPackageError(
            "invalid-harbor-task",
            "task.toml task.name must equal scenario.id",
        )
    if harbor["instruction_sha256"] != hashlib.sha256(instruction).hexdigest():
        raise ScenarioPackageError(
            "developer-brief-delivery-mismatch",
            "pinned Harbor did not load the Developer Brief byte-for-byte",
        )
    try:
        _, lock_bytes = build_scenario_lock(
            path,
            manifest,
            harbor_content_hash=harbor["content_hash"],
        )
    except ScenarioLockError as error:
        raise ScenarioPackageError("invalid-package-payload", str(error)) from error
    return manifest, lock_bytes, harbor


def check_scenario_package(path: Path) -> dict[str, object]:
    """Validate authored files, profile expansion, pinned Harbor, and any lock."""
    path = path.resolve()
    manifest, expected_lock, harbor = _checked_lock_bytes(path)
    lock_path = path / "scenario.lock.json"
    lock_status = "missing"
    if lock_path.exists():
        if lock_path.is_symlink() or not lock_path.is_file():
            raise ScenarioPackageError("stale-package-lock", "package lock is not a file")
        actual_lock = lock_path.read_bytes()
        try:
            SchemaRegistry(schema_root_path()).validate_bytes(actual_lock)
        except SchemaValidationError as error:
            raise ScenarioPackageError("stale-package-lock", str(error)) from error
        if actual_lock != expected_lock:
            raise ScenarioPackageError(
                "stale-package-lock",
                "scenario.lock.json does not reproduce from current package inputs",
            )
        lock_status = "valid"
    scenario = manifest["scenario"]
    return {
        "harbor_commit": HARBOR_COMMIT,
        "harbor_task_sha256": str(
            TypedDigest(DigestKind.HARBOR_TASK, harbor["content_hash"])
        ),
        "lock": lock_status,
        "message": f"Scenario Package is a valid candidate: {scenario['id']}",
        "path": str(path),
        "scenario_id": scenario["id"],
        "status": "candidate-valid",
    }


def lock_scenario_package(path: Path) -> dict[str, object]:
    """Atomically write and immediately read back the non-circular package lock."""
    path = path.resolve()
    lock_path = path / "scenario.lock.json"
    try:
        lock_path.unlink(missing_ok=True)
    except OSError as error:
        raise ScenarioPackageError("lock-publication-failed", str(error)) from error
    manifest, data, _ = _checked_lock_bytes(path)
    try:
        _atomic_verified_write(lock_path, data)
    except OSError as error:
        raise ScenarioPackageError("lock-publication-failed", str(error)) from error
    lock_digest = str(TypedDigest.from_bytes(DigestKind.PACKAGE_LOCK, data))
    return {
        "lock_sha256": lock_digest,
        "message": f"sealed deterministic Scenario Package lock: {manifest['scenario']['id']}",
        "path": str(lock_path),
        "scenario_id": manifest["scenario"]["id"],
        "status": "locked",
    }


@dataclass(frozen=True)
class ScenarioPackage:
    """One deep public interface for Scenario Package authoring and qualification."""

    root: Path

    @classmethod
    def scaffold(
        cls,
        destination: Path,
        *,
        scenario_id: str,
        ecosystem: str,
        visibility: str,
        trusted_capture_source: str,
    ) -> "ScenarioPackage":
        scaffold_scenario_package(
            path=destination,
            scenario_id=scenario_id,
            ecosystem=ecosystem,
            visibility=visibility,
            trusted_capture_source=trusted_capture_source,
        )
        return cls(destination.resolve())

    @classmethod
    def open(cls, root: Path) -> "ScenarioPackage":
        return cls(root.resolve())

    def check(self) -> dict[str, object]:
        return check_scenario_package(self.root)

    def lock(self) -> dict[str, object]:
        return lock_scenario_package(self.root)

    def qualify(
        self,
        *,
        technical_evidence: Path,
        review: Path,
        output: Path,
        trusted_worker_identity: str,
        trusted_reviewer_identity: str,
    ) -> dict[str, object]:
        from model_benchmark.declarations.scenario_qualification import (
            qualify_scenario_package,
        )

        return qualify_scenario_package(
            self.root,
            technical_evidence=technical_evidence,
            review=review,
            output=output,
            trusted_worker_identity=trusted_worker_identity,
            trusted_reviewer_identity=trusted_reviewer_identity,
        )

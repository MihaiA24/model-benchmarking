from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from model_benchmark.declarations.canonical import canonical_json_bytes
from model_benchmark.declarations.identities import DigestKind, TypedDigest
from model_benchmark.declarations.scenario_locks import schema_root_path
from model_benchmark.declarations.scenario_qualification import technical_signing_bytes
from model_benchmark.declarations.schemas import SchemaRegistry, SchemaValidationError
from model_benchmark.declarations.scenarios import (
    ScenarioPackageError,
    _harbor_probe,
    _immutable_verified_write,
    check_scenario_package,
)
from model_benchmark.runtime.provisioning import (
    acquire_store_lease,
    create_verifier_build_package,
    ensure_locked_images,
    harbor_egress_image,
    harbor_kernel_probe_reference,
    load_target_config,
    locked_image_requests,
    project_runtime_images,
    project_single_runtime_image,
    publish_manifest,
    preflight,
    prefixed_runtime_image,
    qualification_authority,
    remove_project_images,
)


_TECHNICAL_SCHEMA_NAME = "model-benchmark/scenario-technical-qualification"
_SCHEMA_VERSION = 1
_CheckGroup = tuple[str, str, bool, str, Decimal, str | None]
_CheckGroups = tuple[_CheckGroup, ...]


def _run(
    command: list[str],
    *,
    timeout: int,
    cwd: Path | None = None,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=None if environment is None else {**os.environ, **environment},
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ScenarioPackageError(
            "qualification-runtime-failed", str(error)
        ) from error
    if completed.returncode != 0:
        detail = (completed.stderr.strip() or completed.stdout.strip())[-2000:]
        raise ScenarioPackageError(
            "qualification-runtime-failed",
            f"command failed ({completed.returncode}): {detail}",
        )
    return completed


def _harbor_executable() -> str:
    sibling = Path(sys.executable).with_name("harbor")
    if sibling.is_file() and os.access(sibling, os.X_OK):
        return str(sibling)
    executable = shutil.which("harbor")
    if executable is None:
        raise ScenarioPackageError(
            "qualification-runtime-unavailable",
            "the pinned Harbor executable is unavailable",
        )
    return executable


def _locked_package(package: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    checked = check_scenario_package(package)
    if checked["lock"] != "valid":
        raise ScenarioPackageError(
            "missing-package-lock",
            "live qualification requires an exact valid package lock",
        )
    registry = SchemaRegistry(schema_root_path())
    try:
        lock = registry.validate_bytes((package / "scenario.lock.json").read_bytes())
        manifest = yaml.safe_load(
            (package / "scenario.yaml").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, yaml.YAMLError, SchemaValidationError) as error:
        raise ScenarioPackageError("invalid-package-lock", str(error)) from error
    if not isinstance(lock, dict) or not isinstance(manifest, dict):
        raise ScenarioPackageError(
            "invalid-package-lock", "invalid package declarations"
        )
    return lock, manifest


def _harbor_command(
    package: Path,
    jobs_dir: Path,
    *,
    agent: str,
    attempts: int,
    install_only: bool = False,
) -> list[str]:
    command = [
        _harbor_executable(),
        "job",
        "start",
        "--path",
        str(package),
        "--agent",
        agent,
        "--env",
        "docker",
        "--jobs-dir",
        str(jobs_dir),
        "--n-concurrent",
        "1",
        "--n-attempts",
        str(attempts),
        "--yes",
        "--quiet",
    ]
    if install_only:
        command.extend(["--install-only", "--no-delete"])
    return command


def provision_scenario_package(
    package: Path,
    *,
    jobs_dir: Path,
    manifest_output: Path,
    target_config: Path,
    qualification_record: Path | None = None,
) -> dict[str, object]:
    """Populate one visibility-scoped Docker store and seal its exact identities."""
    package = package.resolve()
    jobs_dir = jobs_dir.resolve()
    manifest_output = manifest_output.resolve()
    if any(
        candidate.is_relative_to(package) for candidate in (jobs_dir, manifest_output)
    ):
        raise ScenarioPackageError(
            "invalid-qualification-output",
            "provisioning outputs must remain outside the package payload",
        )
    if manifest_output.exists() or manifest_output.is_symlink():
        raise ScenarioPackageError(
            "qualification-publication-failed",
            f"provisioning manifest path already exists: {manifest_output}",
        )
    if jobs_dir.exists() and any(jobs_dir.iterdir()):
        raise ScenarioPackageError(
            "qualification-publication-failed",
            f"provisioning jobs directory is not empty: {jobs_dir}",
        )
    lock, manifest = _locked_package(package)
    lock_bytes = (package / "scenario.lock.json").read_bytes()
    visibility = manifest["scenario"]["visibility"]
    target = load_target_config(target_config.resolve(), visibility=visibility)
    lifecycle_state, authority_digest = qualification_authority(
        qualification_record.resolve() if qualification_record is not None else None,
        lock=lock,
        lock_bytes=lock_bytes,
    )
    phase = jobs_dir / "provision"
    verifier_phase = jobs_dir / "verifier-provision"
    verifier_package = jobs_dir / "verifier-package"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    with acquire_store_lease(target, visibility=visibility) as lease:
        try:
            locked_images = locked_image_requests(lock)
            kernel_reference = harbor_kernel_probe_reference()
            requested_images = ensure_locked_images(lease, locked_images)
            _run(
                _harbor_command(
                    package,
                    phase,
                    agent="nop",
                    attempts=1,
                    install_only=True,
                ),
                timeout=900,
                environment={"DOCKER_CONTEXT": lease.target.context},
            )
            trial_path = _trial_results(phase, expected=1, agent="nop")[0]
            trial = json.loads(trial_path.read_text(encoding="utf-8"))
            if trial.get("exception_info") is not None:
                raise ScenarioPackageError(
                    "provisioning-runtime-failed",
                    "Harbor provisioning recorded a trial exception",
                )
            trial_name = trial.get("trial_name")
            if not isinstance(trial_name, str) or not trial_name:
                raise ScenarioPackageError(
                    "provisioning-runtime-failed",
                    "Harbor provisioning omitted the trial identity",
                )
            runtime_images = project_runtime_images(
                lease,
                project=_compose_project_name(f"{trial_name}__env"),
                package=package,
            )
            create_verifier_build_package(package, verifier_package)
            _run(
                _harbor_command(
                    verifier_package,
                    verifier_phase,
                    agent="nop",
                    attempts=1,
                    install_only=True,
                ),
                timeout=900,
                environment={"DOCKER_CONTEXT": lease.target.context},
            )
            verifier_result = _trial_results(verifier_phase, expected=1, agent="nop")[0]
            verifier_trial = json.loads(verifier_result.read_text(encoding="utf-8"))
            if verifier_trial.get("exception_info") is not None:
                raise ScenarioPackageError(
                    "provisioning-runtime-failed",
                    "Harbor verifier provisioning recorded a trial exception",
                )
            verifier_trial_name = verifier_trial.get("trial_name")
            if not isinstance(verifier_trial_name, str) or not verifier_trial_name:
                raise ScenarioPackageError(
                    "provisioning-runtime-failed",
                    "Harbor verifier provisioning omitted the trial identity",
                )
            runtime_images.append(
                project_single_runtime_image(
                    lease,
                    project=_compose_project_name(f"{verifier_trial_name}__env"),
                    package=package,
                )
            )
            runtime_images.append(
                prefixed_runtime_image(
                    lease,
                    prefix=harbor_egress_image(),
                    role="egress-control",
                    build_input_sha256=str(
                        TypedDigest.from_bytes(
                            DigestKind.ARTIFACT,
                            canonical_json_bytes(
                                {
                                    "harbor_commit": lock["harbor"]["commit"],
                                    "source": kernel_reference,
                                }
                            ),
                        )
                    ),
                )
            )
            published = publish_manifest(
                manifest_output,
                lease=lease,
                lock=lock,
                lock_bytes=lock_bytes,
                lifecycle_state=lifecycle_state,
                qualification_record_sha256=authority_digest,
                requested_images=requested_images,
                runtime_images=runtime_images,
            )
        except BaseException:
            projects = {
                _compose_project_name(f"{config.parent.name}__env")
                for root in (phase, verifier_phase)
                for config in root.rglob("config.json")
            }
            remove_project_images(lease, projects)
            for candidate in (phase, verifier_phase, verifier_package):
                shutil.rmtree(candidate, ignore_errors=True)
            raise
    return {
        "images": len(requested_images) + len(runtime_images),
        "jobs_dir": str(jobs_dir),
        "lifecycle_state": lifecycle_state,
        "manifest_sha256": published["manifest_sha256"],
        "message": f"provisioned exact locked inputs for {lock['scenario_id']}",
        "path": published["path"],
        "scenario_id": lock["scenario_id"],
        "status": "provisioned",
        "visibility_domain": visibility,
    }


def _normalized_score(value: object) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if not isinstance(value, (int, float, str, Decimal)):
        raise ScenarioPackageError(
            "invalid-infrastructure",
            "score value is not numeric",
        )
    try:
        decimal = Decimal(str(value))
    except InvalidOperation as error:
        raise ScenarioPackageError(
            "invalid-infrastructure", "invalid score value"
        ) from error
    if not decimal.is_finite() or decimal < 0 or decimal > 1:
        raise ScenarioPackageError("invalid-infrastructure", "score is outside [0, 1]")
    text = format(decimal.normalize(), "f")
    return "0" if text == "-0" else text


def _vector(
    value: dict[str, object], expected_names: tuple[str, ...]
) -> list[dict[str, str]]:
    if any(name not in value for name in expected_names):
        raise ScenarioPackageError(
            "invalid-infrastructure",
            "score projection does not contain every declared score",
        )
    return [
        {"name": name, "value": _normalized_score(value[name])}
        for name in sorted(expected_names)
    ]


def _trial_results(phase: Path, *, expected: int, agent: str) -> list[Path]:
    results: list[Path] = []
    for path in phase.rglob("result.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if (
            isinstance(value, dict)
            and value.get("task_name")
            and value.get("agent_info")
        ):
            if (
                not isinstance(value["agent_info"], dict)
                or value["agent_info"].get("name") != agent
            ):
                raise ScenarioPackageError(
                    "invalid-infrastructure",
                    "Harbor trial used an unexpected agent",
                )
            results.append(path)
    if len(results) != expected:
        raise ScenarioPackageError(
            "invalid-infrastructure",
            f"expected {expected} Harbor trials, found {len(results)}",
        )
    return sorted(results)


def _validate_structured_result(
    structured: dict[str, object],
    expected_groups: _CheckGroups,
) -> None:
    checks = structured.get("checks")
    statuses = structured.get("required_group_statuses")
    if (
        structured.get("verifier_complete") is not True
        or not isinstance(checks, list)
        or not isinstance(statuses, dict)
        or not isinstance(structured.get("domain_scores"), dict)
    ):
        raise ScenarioPackageError(
            "invalid-infrastructure",
            "structured verifier result is incomplete",
        )
    parsed_checks: dict[str, tuple[str, tuple[str, ...]]] = {}
    for check in checks:
        if not isinstance(check, dict) or set(check) != {"evidence", "id", "status"}:
            raise ScenarioPackageError(
                "invalid-infrastructure",
                "structured verifier check is malformed",
            )
        check_id = check["id"]
        status = check["status"]
        evidence = check["evidence"]
        if (
            not isinstance(check_id, str)
            or not check_id
            or check_id in parsed_checks
            or status not in {"pass", "fail", "error", "not_evaluable"}
            or not isinstance(evidence, list)
            or not evidence
            or any(not isinstance(item, str) or not item for item in evidence)
        ):
            raise ScenarioPackageError(
                "invalid-infrastructure",
                "structured verifier check identity, status, or evidence is invalid",
            )
        parsed_checks[check_id] = (status, tuple(evidence))
    expected_statuses = {group_id for group_id, _, _, _, _, _ in expected_groups}
    if set(statuses) != expected_statuses:
        raise ScenarioPackageError(
            "invalid-infrastructure",
            "structured verifier result omits or invents Check Groups",
        )
    for group_id, evidence_key, _, _, _, _ in expected_groups:
        status = statuses[group_id]
        if status not in {"pass", "fail", "error", "not_evaluable"}:
            raise ScenarioPackageError(
                "invalid-infrastructure",
                f"invalid status for Check Group {group_id}",
            )
        if (
            evidence_key not in parsed_checks
            or parsed_checks[evidence_key][0] != status
        ):
            raise ScenarioPackageError(
                "invalid-infrastructure",
                f"Check Group {group_id} lacks matching raw evidence",
            )
    domain_scores = structured["domain_scores"]
    declared_domain_scores = {
        domain_score
        for _, _, _, _, _, domain_score in expected_groups
        if domain_score is not None
    }
    if set(domain_scores) != declared_domain_scores:
        raise ScenarioPackageError(
            "invalid-infrastructure",
            "structured verifier result omits or invents domain scores",
        )
    score_targets = (
        ("acceptance_score", "acceptance"),
        ("regression_score", "regression"),
        *((name, None) for name in sorted(declared_domain_scores)),
    )
    for score_name, group_class in score_targets:
        derived = sum(
            (
                weight
                for (
                    group_id,
                    _,
                    _,
                    declared_class,
                    weight,
                    domain_score,
                ) in expected_groups
                if (
                    (group_class is not None and declared_class == group_class)
                    or domain_score == score_name
                )
                and statuses[group_id] == "pass"
            ),
            Decimal(0),
        )
        actual = (
            structured.get(score_name)
            if group_class is not None
            else domain_scores.get(score_name)
        )
        if _normalized_score(actual) != _normalized_score(derived):
            raise ScenarioPackageError(
                "invalid-infrastructure",
                f"{score_name} disagrees with declared Check Group outcomes",
            )
    declared_success = structured.get("task_success")
    required_pass = all(
        statuses[group_id] == "pass"
        for group_id, _, required, group_class, _, _ in expected_groups
        if required and group_class in {"acceptance", "regression"}
    )
    if not isinstance(declared_success, bool) or declared_success is not required_pass:
        raise ScenarioPackageError(
            "invalid-infrastructure",
            "task_success disagrees with required acceptance/regression Check Group outcomes",
        )


def _compose_project_name(value: str) -> str:
    lowered = value.lower()
    if not re.match(r"^[a-z0-9]", lowered):
        lowered = "0" + lowered
    return re.sub(r"[^a-z0-9_-]", "-", lowered)


def _environment_identity(trial: dict[str, object]) -> str:
    trial_name = trial.get("trial_name")
    started_at = trial.get("started_at")
    finished_at = trial.get("finished_at")
    if not all(
        isinstance(value, str) and value
        for value in (trial_name, started_at, finished_at)
    ):
        raise ScenarioPackageError(
            "invalid-infrastructure",
            "Harbor environment timestamps or trial name are missing",
        )
    completed = _run(
        [
            "docker",
            "events",
            "--since",
            started_at,
            "--until",
            str(int(time.time()) + 1),
            "--filter",
            "type=container",
            "--format",
            "{{json .}}",
        ],
        timeout=30,
    )
    prefix = _compose_project_name(trial_name)
    evidence: list[dict[str, str]] = []
    for line in completed.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise ScenarioPackageError("invalid-infrastructure", str(error)) from error
        actor = event.get("Actor")
        attributes = actor.get("Attributes") if isinstance(actor, dict) else None
        project = (
            attributes.get("com.docker.compose.project")
            if isinstance(attributes, dict)
            else None
        )
        if not isinstance(project, str) or not project.startswith(prefix):
            continue
        event_type = event.get("Type")
        action = event.get("Action")
        identity = event.get("id") or (
            actor.get("ID") if isinstance(actor, dict) else None
        )
        service = attributes.get("com.docker.compose.service", "")
        if not all(
            isinstance(value, str) for value in (action, event_type, identity, service)
        ):
            raise ScenarioPackageError(
                "invalid-infrastructure",
                "Docker environment event is malformed",
            )
        evidence.append(
            {
                "action": action,
                "id": identity,
                "project": project,
                "service": service,
                "type": event_type,
            }
        )
    agent_project = _compose_project_name(f"{trial_name}__env")
    agent_services = {
        item["service"] for item in evidence if item["project"] == agent_project
    }
    verifier_projects = {
        item["project"]
        for item in evidence
        if item["project"].startswith(
            _compose_project_name(f"{trial_name}__verifier__")
        )
    }
    container_ids = {item["id"] for item in evidence if item["type"] == "container"}
    if (
        not {"main", "capture"} <= agent_services
        or len(verifier_projects) != 1
        or len(container_ids) < 3
    ):
        raise ScenarioPackageError(
            "invalid-infrastructure",
            "Docker events do not prove fresh agent, capture, and verifier containers",
        )
    return (
        "docker-environment:sha256:"
        + hashlib.sha256(
            canonical_json_bytes(
                sorted(evidence, key=lambda item: tuple(item.values()))
            )
        ).hexdigest()
    )


def _run_record(
    path: Path,
    *,
    expected_outcome: str,
    expected_capture_kind: str | None,
    expected_capture_reason: str | None,
    expected_artifact_destination: str | None,
    expected_task_digest: str,
    expected_score_names: tuple[str, ...],
    expected_hidden_marker_digests: tuple[str, ...],
    expected_groups: _CheckGroups,
) -> dict[str, object]:
    capture_destination = (
        "artifacts/capture/materialization.json"
        if expected_capture_kind == "artifact"
        else "artifacts/capture/capture.json"
    )
    try:
        trial = json.loads(path.read_text(encoding="utf-8"))
        structured = json.loads(
            (path.parent / "verifier/verifier-result.json").read_text(encoding="utf-8")
        )
        native_reward = json.loads(
            (path.parent / "verifier/reward.json").read_text(encoding="utf-8")
        )
        native_lock = json.loads(
            (path.parent / "lock.json").read_text(encoding="utf-8")
        )
        artifact_manifest = json.loads(
            (path.parent / "artifacts/manifest.json").read_text(encoding="utf-8")
        )
        capture = json.loads(
            (path.parent / capture_destination).read_text(encoding="utf-8")
        )

    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ScenarioPackageError("invalid-infrastructure", str(error)) from error
    if trial.get("exception_info") is not None:
        raise ScenarioPackageError(
            "qualification-runtime-failed",
            "Harbor trial recorded an exception",
        )
    verifier = trial.get("verifier_result")
    rewards = verifier.get("rewards") if isinstance(verifier, dict) else None
    if (
        not isinstance(rewards, dict)
        or not isinstance(structured, dict)
        or not isinstance(native_reward, dict)
        or not isinstance(native_lock, dict)
        or not isinstance(artifact_manifest, list)
        or not isinstance(capture, dict)
    ):
        raise ScenarioPackageError(
            "invalid-infrastructure",
            "Harbor verifier outputs are incomplete",
        )
    reward_vector = _vector(rewards, expected_score_names)
    if _vector(native_reward, expected_score_names) != reward_vector:
        raise ScenarioPackageError(
            "invalid-infrastructure",
            "Harbor reward file differs from the Trial reward projection",
        )
    structured_vector = _vector(structured, expected_score_names)
    if structured_vector != reward_vector:
        raise ScenarioPackageError(
            "invalid-infrastructure",
            "numeric Harbor reward differs from structured verifier output",
        )
    _validate_structured_result(structured, expected_groups)
    task = native_lock.get("task")
    native_task_digest = task.get("digest") if isinstance(task, dict) else None
    if native_task_digest != expected_task_digest.replace("harbor-task:", "", 1):
        raise ScenarioPackageError(
            "invalid-infrastructure",
            "Harbor native lock identifies unexpected task bytes",
        )
    collected = {
        entry.get("destination"): entry.get("status")
        for entry in artifact_manifest
        if isinstance(entry, dict)
    }
    if collected.get(capture_destination) != "ok":
        raise ScenarioPackageError(
            "invalid-infrastructure",
            "Harbor did not collect the trusted capture record",
        )
    if expected_capture_reason is not None:
        if (
            capture.get("status") != "rejected"
            or capture.get("reason") != expected_capture_reason
        ):
            raise ScenarioPackageError(
                "invalid-infrastructure",
                "trusted capture rejection does not match the diagnostic handoff",
            )
    elif capture.get("status") != "accepted":
        raise ScenarioPackageError(
            "invalid-infrastructure",
            "trusted capture record does not match the measured handoff",
        )
    elif expected_capture_kind == "artifact":
        if expected_artifact_destination is None:
            raise ScenarioPackageError(
                "invalid-infrastructure",
                "artifact handoff destination is missing",
            )
        artifact_destination = f"artifacts{expected_artifact_destination}"
        if collected.get(artifact_destination) != "ok":
            raise ScenarioPackageError(
                "invalid-infrastructure",
                "Harbor did not collect the declared artifact output",
            )
        try:
            artifact = (path.parent / artifact_destination).read_bytes()
        except OSError as error:
            raise ScenarioPackageError("invalid-infrastructure", str(error)) from error
        if capture.get("hidden_markers") != {
            "digests": list(expected_hidden_marker_digests),
            "status": "absent",
        }:
            raise ScenarioPackageError(
                "invalid-infrastructure",
                "trusted capture did not prove hidden markers absent from the agent-visible tree",
            )
        if capture.get("artifact_sha256") != hashlib.sha256(artifact).hexdigest():
            raise ScenarioPackageError(
                "invalid-infrastructure",
                "captured artifact digest does not match the collected artifact",
            )
    elif capture.get("kind") != expected_capture_kind:
        raise ScenarioPackageError(
            "invalid-infrastructure",
            "trusted capture record does not match the measured handoff",
        )
    else:
        if collected.get("artifacts/capture/submission.patch") != "ok":
            raise ScenarioPackageError(
                "invalid-infrastructure",
                "Harbor did not collect the declared patch artifact",
            )
        try:
            patch = (path.parent / "artifacts/capture/submission.patch").read_bytes()
        except OSError as error:
            raise ScenarioPackageError("invalid-infrastructure", str(error)) from error
        if capture.get("hidden_markers") != {
            "digests": list(expected_hidden_marker_digests),
            "status": "absent",
        }:
            raise ScenarioPackageError(
                "invalid-infrastructure",
                "trusted capture did not prove hidden markers absent from the agent-visible tree",
            )
        if capture.get("patch_sha256") != hashlib.sha256(patch).hexdigest():
            raise ScenarioPackageError(
                "invalid-infrastructure",
                "captured patch digest does not match the collected artifact",
            )
    outcome = (
        "passed"
        if _normalized_score(rewards.get("task_success")) == "1"
        else "declared-failure"
    )
    if outcome != expected_outcome:
        raise ScenarioPackageError(
            "invalid-technical-qualification",
            f"Harbor trial produced {outcome}, expected {expected_outcome}",
        )
    environment_id = _environment_identity(trial)
    return {
        "environment_id": environment_id,
        "outcome": outcome,
        "reward_score_vector": reward_vector,
        "structured_score_vector": structured_vector,
    }


def _run_phase(
    package: Path,
    jobs_dir: Path,
    *,
    name: str,
    agent: str,
    attempts: int,
    expected_outcome: str,
    expected_task_digest: str,
    expected_score_names: tuple[str, ...],
    expected_hidden_marker_digests: tuple[str, ...],
    expected_groups: _CheckGroups,
    expected_capture_reason: str | None,
    environment: dict[str, str],
) -> tuple[list[dict[str, object]], str]:
    phase = jobs_dir / name
    if phase.exists():
        raise ScenarioPackageError(
            "qualification-publication-failed",
            f"qualification phase already exists: {phase}",
        )
    records: list[dict[str, object]] = []
    outputs: list[str] = []
    known_results: set[Path] = set()
    for attempt in range(1, attempts + 1):
        completed = _run(
            _harbor_command(package, phase, agent=agent, attempts=1),
            timeout=1200,
            environment=environment,
        )
        outputs.append(completed.stdout + completed.stderr)
        result_paths = _trial_results(phase, expected=attempt, agent=agent)
        fresh_results = set(result_paths) - known_results
        if len(fresh_results) != 1:
            raise ScenarioPackageError(
                "invalid-infrastructure",
                "Harbor did not produce exactly one fresh trial",
            )
        path = fresh_results.pop()
        known_results.add(path)
        records.append(
            _run_record(
                path,
                expected_outcome=expected_outcome,
                expected_capture_kind="patch" if agent == "oracle" else "no-op",
                expected_capture_reason=expected_capture_reason,
                expected_artifact_destination=None,
                expected_task_digest=expected_task_digest,
                expected_score_names=expected_score_names,
                expected_hidden_marker_digests=expected_hidden_marker_digests,
                expected_groups=expected_groups,
            )
        )
    return records, "".join(outputs)


def _run_rejection_phase(
    package: Path,
    jobs_dir: Path,
    *,
    kind: str,
    expected_score_names: tuple[str, ...],
    expected_hidden_marker_digests: tuple[str, ...],
    expected_groups: _CheckGroups,
    environment: dict[str, str],
) -> tuple[dict[str, object], str]:
    if kind == "malformed":
        solution = (
            "#!/bin/sh\nset -eu\n"
            "printf '\\000invalid' > /workspace/repository/malformed.bin\n"
        )
        expected_reason = "binary_file"
    elif kind == "unsafe":
        solution = (
            "#!/bin/sh\nset -eu\n"
            "printf 'target\\n' > /workspace/repository/target.txt\n"
            "ln -s target.txt /workspace/repository/unsafe-link\n"
        )
        expected_reason = "symlink"
    else:
        raise AssertionError(kind)

    with tempfile.TemporaryDirectory(prefix=f"scenario-{kind}-handoff-") as temporary:
        diagnostic = Path(temporary) / "package"
        shutil.copytree(package, diagnostic, symlinks=True)
        (diagnostic / "scenario.lock.json").unlink(missing_ok=True)
        solution_path = diagnostic / "solution/solve.sh"
        solution_path.write_text(solution, encoding="utf-8")
        solution_path.chmod(0o755)
        probe = _harbor_probe(diagnostic)
        task_digest = str(TypedDigest(DigestKind.HARBOR_TASK, probe["content_hash"]))
        records, output = _run_phase(
            diagnostic,
            jobs_dir,
            name=f"{kind}-handoff",
            agent="oracle",
            attempts=1,
            expected_outcome="declared-failure",
            expected_task_digest=task_digest,
            expected_score_names=expected_score_names,
            expected_hidden_marker_digests=expected_hidden_marker_digests,
            expected_groups=expected_groups,
            expected_capture_reason=expected_reason,
            environment=environment,
        )
    return (
        {
            "classification": "valid_harness_outcome",
            "environment_id": records[0]["environment_id"],
            "kind": kind,
            "task_success": False,
        },
        output,
    )


def _run_score_mismatch_phase(
    package: Path,
    jobs_dir: Path,
    *,
    expected_task_digest: str,
    expected_score_names: tuple[str, ...],
    expected_hidden_marker_digests: tuple[str, ...],
    expected_groups: _CheckGroups,
    environment: dict[str, str],
) -> tuple[dict[str, str], str]:
    phase = jobs_dir / "score-mismatch"
    completed = _run(
        _harbor_command(package, phase, agent="nop", attempts=1),
        timeout=1200,
        environment=environment,
    )
    result_path = _trial_results(phase, expected=1, agent="nop")[0]
    valid_record = _run_record(
        result_path,
        expected_outcome="declared-failure",
        expected_capture_kind="no-op",
        expected_capture_reason=None,
        expected_artifact_destination=None,
        expected_task_digest=expected_task_digest,
        expected_score_names=expected_score_names,
        expected_hidden_marker_digests=expected_hidden_marker_digests,
        expected_groups=expected_groups,
    )
    structured_path = result_path.parent / "verifier/verifier-result.json"
    try:
        structured = json.loads(structured_path.read_text(encoding="utf-8"))
        score_name = next(
            name for name in expected_score_names if name != "task_success"
        )
        structured[score_name] = 1 if structured[score_name] != 1 else 0
        structured_path.write_text(json.dumps(structured), encoding="utf-8")
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        StopIteration,
    ) as error:
        raise ScenarioPackageError("invalid-infrastructure", str(error)) from error
    try:
        _run_record(
            result_path,
            expected_outcome="declared-failure",
            expected_capture_kind="no-op",
            expected_capture_reason=None,
            expected_artifact_destination=None,
            expected_task_digest=expected_task_digest,
            expected_score_names=expected_score_names,
            expected_hidden_marker_digests=expected_hidden_marker_digests,
            expected_groups=expected_groups,
        )
    except ScenarioPackageError as error:
        if (
            error.classification != "invalid-infrastructure"
            or "numeric Harbor reward differs" not in str(error)
        ):
            raise
    else:
        raise ScenarioPackageError(
            "invalid-technical-qualification",
            "numeric/structured verifier mismatch was accepted",
        )
    return (
        {"environment_id": str(valid_record["environment_id"]), "status": "passed"},
        completed.stdout + completed.stderr,
    )


def _docker_pull_events(
    started: int, finished: int, *, environment: dict[str, str]
) -> str:
    completed = _run(
        [
            "docker",
            "events",
            "--since",
            str(started),
            "--until",
            str(max(finished, started + 1)),
            "--filter",
            "type=image",
            "--filter",
            "event=pull",
            "--format",
            "{{json .}}",
        ],
        timeout=30,
        environment=environment,
    )
    return completed.stdout.strip()


def _load_private_key(path: Path) -> Ed25519PrivateKey:
    if path.is_symlink() or not path.is_file():
        raise ScenarioPackageError(
            "qualification-worker-key-invalid",
            "worker private key is not a regular file",
        )
    try:
        key = path.read_bytes()
    except OSError as error:
        raise ScenarioPackageError(
            "qualification-worker-key-invalid", str(error)
        ) from error
    if len(key) != 32:
        raise ScenarioPackageError(
            "qualification-worker-key-invalid",
            "worker private key must contain exactly 32 raw bytes",
        )
    return Ed25519PrivateKey.from_private_bytes(key)


def _sign_technical(
    technical: dict[str, Any],
    private_key: Ed25519PrivateKey,
) -> str:
    public_key = private_key.public_key().public_bytes_raw()
    encoded_key = base64.urlsafe_b64encode(public_key).decode("ascii").rstrip("=")
    identity = "ed25519:sha256:" + hashlib.sha256(public_key).hexdigest()
    technical["worker"] = {
        "authentication": {
            "kind": "signature",
            "value": f"ed25519:{encoded_key}:",
        },
        "environment": "harbor-v0.18.0/docker-local",
        "identity": identity,
    }
    signature = private_key.sign(technical_signing_bytes(technical))
    encoded_signature = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    technical["worker"]["authentication"]["value"] = (
        f"ed25519:{encoded_key}:{encoded_signature}"
    )
    return identity


def measure_scenario_package(
    package: Path,
    *,
    jobs_dir: Path,
    output: Path,
    worker_private_key: Path,
    provisioning_manifest: Path,
    preflight_output: Path,
) -> dict[str, object]:
    """Run baseline, hidden-marker, and Reference qualification through Harbor."""
    package = package.resolve()
    jobs_dir = jobs_dir.resolve()
    output = output.resolve()
    worker_private_key = worker_private_key.resolve()
    provisioning_manifest = provisioning_manifest.resolve()
    preflight_output = preflight_output.resolve()
    for candidate in (jobs_dir, output, preflight_output):
        if candidate.is_relative_to(package):
            raise ScenarioPackageError(
                "invalid-qualification-output",
                "qualification evidence must remain outside the package payload",
            )
    lock, manifest = _locked_package(package)
    receipt = preflight(
        package,
        manifest_path=provisioning_manifest,
        mode="qualification",
        output=preflight_output,
    )
    execution_package = Path(str(receipt["package_path"]))
    docker_guard = Path(str(receipt["docker_guard_path"]))
    expected_guard = preflight_output / "bin/docker"
    if (
        docker_guard != expected_guard
        or not docker_guard.is_file()
        or not os.access(docker_guard, os.X_OK)
    ):
        raise ScenarioPackageError(
            "invalid-infrastructure", "preflight Docker guard is unavailable"
        )
    execution_environment = {
        "DOCKER_CONTEXT": str(receipt["docker_context"]),
        "PATH": str(docker_guard.parent) + os.pathsep + os.environ.get("PATH", ""),
    }
    declared = manifest["verification"]["qualification"]
    domain_score_by_group = {
        group_id: score["name"]
        for score in manifest["verification"]["domain_scores"]
        for group_id in score["check_groups"]
    }
    expected_score_names = tuple(
        entry["name"] for entry in declared["baseline_score_vector"]
    )
    expected_groups = tuple(
        (
            group["id"],
            group["evidence_key"],
            group["required"],
            group["class"],
            Decimal(str(group["weight"])),
            domain_score_by_group.get(group["id"]),
        )
        for group in manifest["verification"]["check_groups"]
    )
    if set(expected_score_names) != {
        entry["name"] for entry in declared["reference_score_vector"]
    }:
        raise ScenarioPackageError(
            "invalid-technical-qualification",
            "baseline and Reference qualification vectors name different scores",
        )
    try:
        policy = json.loads(
            (package / "environment/capture/policy.json").read_text(encoding="utf-8")
        )
        markers = policy["forbidden_markers"]
        expected_hidden_marker_digests = tuple(
            sorted(
                hashlib.sha256(marker.encode("utf-8")).hexdigest() for marker in markers
            )
        )
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ScenarioPackageError("invalid-infrastructure", str(error)) from error
    if jobs_dir.exists() and any(jobs_dir.iterdir()):
        raise ScenarioPackageError(
            "qualification-publication-failed",
            f"qualification jobs directory is not empty: {jobs_dir}",
        )
    jobs_dir.mkdir(parents=True, exist_ok=True)
    started = int(time.time())
    expected_task_digest = str(receipt["projected_task_sha256"])
    baseline_records, baseline_output = _run_phase(
        execution_package,
        jobs_dir,
        name="baseline",
        agent="nop",
        attempts=1,
        expected_outcome="declared-failure",
        expected_task_digest=expected_task_digest,
        expected_score_names=expected_score_names,
        expected_hidden_marker_digests=expected_hidden_marker_digests,
        expected_groups=expected_groups,
        expected_capture_reason=None,
        environment=execution_environment,
    )
    hidden_records, hidden_output = _run_phase(
        execution_package,
        jobs_dir,
        name="hidden-marker",
        agent="nop",
        attempts=1,
        expected_outcome="declared-failure",
        expected_task_digest=expected_task_digest,
        expected_score_names=expected_score_names,
        expected_hidden_marker_digests=expected_hidden_marker_digests,
        expected_groups=expected_groups,
        expected_capture_reason=None,
        environment=execution_environment,
    )
    reference_records, reference_output = _run_phase(
        execution_package,
        jobs_dir,
        name="reference",
        agent="oracle",
        attempts=2,
        expected_outcome="passed",
        expected_task_digest=expected_task_digest,
        expected_score_names=expected_score_names,
        expected_hidden_marker_digests=expected_hidden_marker_digests,
        expected_groups=expected_groups,
        expected_capture_reason=None,
        environment=execution_environment,
    )
    malformed_handoff, malformed_output = _run_rejection_phase(
        execution_package,
        jobs_dir,
        kind="malformed",
        expected_score_names=expected_score_names,
        expected_hidden_marker_digests=expected_hidden_marker_digests,
        expected_groups=expected_groups,
        environment=execution_environment,
    )
    unsafe_handoff, unsafe_output = _run_rejection_phase(
        execution_package,
        jobs_dir,
        kind="unsafe",
        expected_score_names=expected_score_names,
        expected_hidden_marker_digests=expected_hidden_marker_digests,
        expected_groups=expected_groups,
        environment=execution_environment,
    )
    score_mismatch, score_mismatch_output = _run_score_mismatch_phase(
        execution_package,
        jobs_dir,
        expected_task_digest=expected_task_digest,
        expected_score_names=expected_score_names,
        expected_hidden_marker_digests=expected_hidden_marker_digests,
        expected_groups=expected_groups,
        environment=execution_environment,
    )
    finished = int(time.time())
    pull_events = _docker_pull_events(
        started, finished, environment=execution_environment
    )
    combined_output = (
        baseline_output
        + hidden_output
        + reference_output
        + malformed_output
        + unsafe_output
        + score_mismatch_output
    ).lower()
    if (
        pull_events
        or "pulling from" in combined_output
        or "downloading" in combined_output
    ):
        raise ScenarioPackageError(
            "qualification-download-detected",
            "measured qualification downloaded an image or package",
        )
    if (
        baseline_records[0]["structured_score_vector"]
        != declared["baseline_score_vector"]
    ):
        raise ScenarioPackageError(
            "invalid-technical-qualification",
            "measured baseline vector differs from the declared vector",
        )
    if any(
        record["structured_score_vector"] != declared["reference_score_vector"]
        for record in reference_records
    ):
        raise ScenarioPackageError(
            "invalid-technical-qualification",
            "measured Reference vector differs from the declared vector",
        )
    environment_ids = {
        baseline_records[0]["environment_id"],
        hidden_records[0]["environment_id"],
        *(record["environment_id"] for record in reference_records),
        malformed_handoff["environment_id"],
        unsafe_handoff["environment_id"],
        score_mismatch["environment_id"],
    }
    if len(environment_ids) != 7:
        raise ScenarioPackageError(
            "invalid-technical-qualification",
            "qualification did not use seven fresh Harbor environments",
        )
    package_record = lock["package"]
    resolved = lock["resolved_inputs"]
    instruction = next(
        entry["sha256"]
        for entry in package_record["files"]
        if entry["path"] == "instruction.md"
    )
    registry = SchemaRegistry(schema_root_path())
    technical: dict[str, Any] = {
        "candidate_status": "technically-qualified",
        "harbor": lock["harbor"],
        "identities": lock["identities"],
        "provisioning": {
            "manifest_sha256": receipt["provisioning_manifest_sha256"],
            "projected_task_sha256": receipt["projected_task_sha256"],
            "projection_sha256": receipt["projection_sha256"],
        },
        "package_payload_sha256": package_record["payload_sha256"],
        "qualified_at": datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "runs": {
            "baseline": baseline_records[0],
            "handoffs": [malformed_handoff, unsafe_handoff],
            "hidden_marker": {
                "environment_id": hidden_records[0]["environment_id"],
                "status": "passed",
            },
            "no_download": True,
            "reference": reference_records,
            "score_mismatch": score_mismatch,
        },
        "schema": registry.envelope(_TECHNICAL_SCHEMA_NAME, _SCHEMA_VERSION),
        "standard_v1": lock["standard_v1"],
        "validated_inputs": {
            "datasets": resolved["datasets"],
            "images": resolved["images"],
            "instruction_sha256": instruction,
            "package_payload_sha256": package_record["payload_sha256"],
            "pristine": resolved["pristine"],
            "scenario_baseline": resolved["scenario_baseline"],
            "seed_inputs": resolved["seed_inputs"],
        },
    }
    identity = _sign_technical(technical, _load_private_key(worker_private_key))
    registry.validate_value(
        technical,
        name=_TECHNICAL_SCHEMA_NAME,
        version=_SCHEMA_VERSION,
    )
    data = canonical_json_bytes(technical)
    try:
        _immutable_verified_write(output, data)
    except OSError as error:
        raise ScenarioPackageError(
            "qualification-publication-failed",
            str(error),
        ) from error
    digest = str(TypedDigest.from_bytes(DigestKind.PACKAGE_QUALIFICATION, data))
    return {
        "jobs_dir": str(jobs_dir),
        "message": f"measured technical qualification: {lock['scenario_id']}",
        "path": str(output),
        "scenario_id": lock["scenario_id"],
        "status": "technically-qualified",
        "technical_qualification_sha256": digest,
        "worker_identity": identity,
    }

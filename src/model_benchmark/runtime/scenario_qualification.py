from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
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


def _terminate_process(
    process: subprocess.Popen[str], *, grace_seconds: int = 10
) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def _run(
    command: list[str],
    *,
    timeout: int,
    cwd: Path | None = None,
    environment: dict[str, str] | None = None,
    cancel: threading.Event | None = None,
    inherit_environment: bool = True,
) -> subprocess.CompletedProcess[str]:
    process_environment = None
    if environment is not None:
        process_environment = (
            {**os.environ, **environment} if inherit_environment else environment
        )
    try:
        if cancel is None:
            completed = subprocess.run(
                command,
                cwd=cwd,
                env=process_environment,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        else:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=process_environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            deadline = time.monotonic() + timeout
            while True:
                if cancel.is_set():
                    _terminate_process(process)
                    raise ScenarioPackageError(
                        "qualification-cancelled",
                        "qualification phase was cancelled after a sibling failure",
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _terminate_process(process)
                    raise subprocess.TimeoutExpired(command, timeout)
                try:
                    stdout, stderr = process.communicate(timeout=min(0.2, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
            completed = subprocess.CompletedProcess(
                command, process.returncode, stdout, stderr
            )
    except ScenarioPackageError:
        raise
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
    job_name: str | None = None,
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
    if job_name is not None:
        command.extend(["--job-name", job_name])
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


def _environment_identity(
    trial: dict[str, object],
    *,
    environment: dict[str, str] | None = None,
    event_log: Path | None = None,
) -> str:
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
    if event_log is None:
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
            environment=environment,
            inherit_environment=environment is None,
        )
        event_output = completed.stdout
    else:
        try:
            event_output = event_log.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise ScenarioPackageError("invalid-infrastructure", str(error)) from error
    prefix = _compose_project_name(trial_name)
    evidence: list[dict[str, str]] = []
    for line in event_output.splitlines():
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
    environment: dict[str, str] | None = None,
    event_log: Path | None = None,
) -> dict[str, object]:
    capture_destination = (
        "artifacts/capture/materialization.json"
        if expected_capture_kind == "artifact"
        else "artifacts/capture/capture.json"
    )
    try:
        trial = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ScenarioPackageError("invalid-infrastructure", str(error)) from error
    if trial.get("exception_info") is not None:
        raise ScenarioPackageError(
            "qualification-runtime-failed",
            "Harbor trial recorded an exception",
        )
    try:
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
    environment_id = _environment_identity(
        trial, environment=environment, event_log=event_log
    )
    return {
        "environment_id": environment_id,
        "outcome": outcome,
        "reward_score_vector": reward_vector,
        "structured_score_vector": structured_vector,
    }


def _run_with_docker_event_capture(
    command: list[str],
    *,
    timeout: int,
    environment: dict[str, str],
    cancel: threading.Event | None,
    event_log: Path,
) -> subprocess.CompletedProcess[str]:
    event_log.parent.mkdir(parents=True, exist_ok=True)
    event_error = event_log.with_suffix(".stderr")
    if event_log.exists() or event_error.exists():
        raise ScenarioPackageError(
            "qualification-publication-failed",
            f"Docker event capture path already exists: {event_log}",
        )
    with event_log.open("w", encoding="utf-8") as output_stream, event_error.open(
        "w", encoding="utf-8"
    ) as error_stream:
        collector = subprocess.Popen(
            [
                "docker",
                "events",
                "--since",
                str(int(time.time())),
                "--format",
                "{{json .}}",
            ],
            stdout=output_stream,
            stderr=error_stream,
            text=True,
            env=environment,
            start_new_session=sys.platform != "win32",
        )
        try:
            completed = _run(
                command,
                timeout=timeout,
                environment=environment,
                cancel=cancel,
                inherit_environment=False,
            )
        finally:
            _terminate_process(collector, grace_seconds=1)
    event_log.chmod(0o444)
    event_error.chmod(0o444)
    expected_exit_codes = {
        0,
        -signal.SIGTERM,
        -signal.SIGKILL,
        128 + signal.SIGTERM,
        128 + signal.SIGKILL,
    }
    if collector.returncode not in expected_exit_codes:
        try:
            message = event_error.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            message = ""
        raise ScenarioPackageError(
            "invalid-infrastructure",
            message
            or f"Docker event capture failed with exit {collector.returncode}",
        )
    return completed


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
    cancel: threading.Event | None = None,
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
        if cancel is not None and cancel.is_set():
            raise ScenarioPackageError(
                "qualification-cancelled",
                "qualification phase was cancelled before execution",
            )
        event_log = (
            Path(environment["XDG_STATE_HOME"])
            / f"docker-events-{attempt}.jsonl"
        )
        completed = _run_with_docker_event_capture(
            _harbor_command(
                package,
                phase,
                agent=agent,
                attempts=1,
                job_name=f"{name}-{attempt}",
            ),
            timeout=1200,
            environment=environment,
            cancel=cancel,
            event_log=event_log,
        )
        outputs.append(completed.stdout + completed.stderr)
        result_paths = _trial_results(phase, expected=attempt, agent=agent)
        fresh_results = set(result_paths) - known_results
        if len(fresh_results) != 1:
            raise ScenarioPackageError(
                "invalid-infrastructure",
                "Harbor did not produce exactly one fresh trial",
            )
        result_path = fresh_results.pop()
        known_results.add(result_path)
        records.append(
            _run_record(
                result_path,
                expected_outcome=expected_outcome,
                expected_capture_kind="patch" if agent == "oracle" else "no-op",
                expected_capture_reason=expected_capture_reason,
                expected_artifact_destination=None,
                expected_task_digest=expected_task_digest,
                expected_score_names=expected_score_names,
                expected_hidden_marker_digests=expected_hidden_marker_digests,
                expected_groups=expected_groups,
                environment=environment,
                event_log=event_log,
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
    scratch_dir: Path | None = None,
    cancel: threading.Event | None = None,
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

    with tempfile.TemporaryDirectory(
        prefix=f"scenario-{kind}-handoff-",
        dir=scratch_dir,
    ) as temporary:
        diagnostic = Path(temporary) / "package"
        shutil.copytree(package, diagnostic, symlinks=True)
        _make_tree_writable(diagnostic)
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
            cancel=cancel,
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
    cancel: threading.Event | None = None,
) -> tuple[dict[str, str], str]:
    phase = jobs_dir / "score-mismatch"
    event_log = Path(environment["XDG_STATE_HOME"]) / "docker-events-1.jsonl"
    completed = _run_with_docker_event_capture(
        _harbor_command(
            package,
            phase,
            agent="nop",
            attempts=1,
            job_name="score-mismatch-1",
        ),
        timeout=1200,
        environment=environment,
        cancel=cancel,
        event_log=event_log,
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
        environment=environment,
        event_log=event_log,
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
            environment=environment,
            event_log=event_log,
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


def _docker_pull_events(event_logs: list[Path]) -> str:
    pulls: set[str] = set()
    for path in event_logs:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as error:
            raise ScenarioPackageError("invalid-infrastructure", str(error)) from error
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise ScenarioPackageError("invalid-infrastructure", str(error)) from error
            if event.get("Type") == "image" and event.get("Action") == "pull":
                pulls.add(line)
    return "\n".join(sorted(pulls))


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


_QUALIFICATION_PHASES = (
    "baseline",
    "hidden-marker",
    "reference",
    "malformed",
    "unsafe",
    "score-mismatch",
)
_PHASE_RESULT_SCHEMA = "model-benchmark/qualification-phase-result/v1"
_PHASE_AGGREGATE_SCHEMA = "model-benchmark/qualification-phase-aggregate/v1"


def _make_tree_writable(root: Path) -> None:
    for candidate in sorted(root.rglob("*")):
        if candidate.is_symlink():
            continue
        if candidate.is_dir():
            candidate.chmod(0o700)
        elif candidate.is_file():
            executable = candidate.stat().st_mode & 0o111
            candidate.chmod(0o700 if executable else 0o600)
    root.chmod(0o700)


def _make_tree_read_only(root: Path) -> None:
    for candidate in sorted(root.rglob("*"), reverse=True):
        if candidate.is_symlink():
            continue
        if candidate.is_dir():
            candidate.chmod(0o555)
        elif candidate.is_file():
            executable = candidate.stat().st_mode & 0o111
            candidate.chmod(0o555 if executable else 0o444)
    root.chmod(0o555)


def _worker_identity(private_key: Ed25519PrivateKey) -> str:
    public_key = private_key.public_key().public_bytes_raw()
    return "ed25519:sha256:" + hashlib.sha256(public_key).hexdigest()


def _inspect_docker_context(context: str) -> dict[str, object]:
    completed = _run(
        ["docker", "context", "inspect", context],
        timeout=30,
    )
    try:
        values = json.loads(completed.stdout)
        value = values[0]
        endpoint = value["Endpoints"]["docker"]
        host = endpoint["Host"]
        skip_tls_verify = endpoint.get("SkipTLSVerify", False)
        tls_material = value.get("TLSMaterial", {})
    except (json.JSONDecodeError, IndexError, KeyError, TypeError) as error:
        raise ScenarioPackageError(
            "invalid-infrastructure",
            "Docker context inspection is incomplete",
        ) from error
    if (
        len(values) != 1
        or not isinstance(host, str)
        or not host
        or not isinstance(skip_tls_verify, bool)
        or not isinstance(tls_material, dict)
    ):
        raise ScenarioPackageError(
            "invalid-infrastructure",
            "Docker context inspection is malformed",
        )
    return {
        "host": host,
        "skip_tls_verify": skip_tls_verify,
        "tls_material": tls_material,
    }


def _docker_compose_plugin_directory() -> Path:
    completed = _run(
        ["docker", "info", "--format", "{{json .ClientInfo.Plugins}}"],
        timeout=30,
    )
    try:
        plugins = json.loads(completed.stdout)
        paths = [
            Path(plugin["Path"]).resolve()
            for plugin in plugins
            if isinstance(plugin, dict) and plugin.get("Name") == "compose"
        ]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise ScenarioPackageError(
            "invalid-infrastructure",
            "Docker Compose plugin discovery is malformed",
        ) from error
    if len(paths) != 1 or not paths[0].is_file():
        raise ScenarioPackageError(
            "invalid-infrastructure",
            "exactly one Docker Compose plugin is required",
        )
    return paths[0].parent


def _phase_environment(
    context: dict[str, object],
    root: Path,
    *,
    docker_guard: Path,
    docker_compose_plugin_directory: Path,
) -> dict[str, str]:
    root.mkdir(parents=True)
    directories = {
        "HOME": root / "home",
        "TMPDIR": root / "scratch",
        "XDG_CACHE_HOME": root / "cache",
        "XDG_CONFIG_HOME": root / "config",
        "XDG_DATA_HOME": root / "data",
        "XDG_STATE_HOME": root / "state",
        "DOCKER_CONFIG": root / "docker",
        "HARBOR_HOME": root / "harbor",
    }
    for directory in directories.values():
        directory.mkdir(mode=0o700)
    environment = {
        name: str(directory) for name, directory in directories.items()
    }
    _immutable_verified_write(
        directories["DOCKER_CONFIG"] / "config.json",
        canonical_json_bytes(
            {
                "cliPluginsExtraDirs": [
                    str(docker_compose_plugin_directory.resolve())
                ]
            }
        ),
    )
    environment.update(
        {
            "DOCKER_HOST": str(context["host"]),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
            "PATH": str(docker_guard.parent)
            + os.pathsep
            + os.environ.get("PATH", ""),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
            "PYTHONUTF8": "1",
        }
    )
    tls_material = context["tls_material"]
    if tls_material:
        certificate_root = root / "docker-tls"
        certificate_root.mkdir(mode=0o700)
        for name, value in sorted(tls_material.items()):
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
                raise ScenarioPackageError(
                    "invalid-infrastructure",
                    "Docker context TLS material has an unsafe name",
                )
            if isinstance(value, list) and all(
                isinstance(item, str) for item in value
            ):
                content = "\n".join(value)
            elif isinstance(value, str):
                content = value
            else:
                raise ScenarioPackageError(
                    "invalid-infrastructure",
                    "Docker context TLS material is malformed",
                )
            certificate = certificate_root / name
            certificate.write_text(content, encoding="utf-8")
            certificate.chmod(0o600)
        environment["DOCKER_CERT_PATH"] = str(certificate_root)
        environment["DOCKER_TLS"] = "1"
        if context["skip_tls_verify"] is False:
            environment["DOCKER_TLS_VERIFY"] = "1"
    return environment


def _write_phase_result(
    path: Path,
    *,
    generation_id: str,
    phase: str,
    package_payload_sha256: str,
    projected_task_sha256: str,
    projection_sha256: str,
    worker_identity: str,
    result: dict[str, object],
) -> None:
    value = {
        "generation_id": generation_id,
        "package_payload_sha256": package_payload_sha256,
        "phase": phase,
        "projected_task_sha256": projected_task_sha256,
        "projection_sha256": projection_sha256,
        "result": result,
        "schema": _PHASE_RESULT_SCHEMA,
        "worker_identity": worker_identity,
    }
    data = canonical_json_bytes(value)
    try:
        _immutable_verified_write(path, data)
        if path.read_bytes() != data:
            raise OSError("phase result digest read-back failed")
    except OSError as error:
        raise ScenarioPackageError(
            "qualification-publication-failed", str(error)
        ) from error


def _aggregate_phase_results(
    results_dir: Path,
    *,
    generation_id: str,
    package_payload_sha256: str,
    projected_task_sha256: str,
    projection_sha256: str,
    worker_identity: str,
) -> tuple[dict[str, object], bytes]:
    expected_paths = {f"{name}.json" for name in _QUALIFICATION_PHASES}
    actual_paths = {path.name for path in results_dir.glob("*.json")}
    if actual_paths != expected_paths:
        raise ScenarioPackageError(
            "invalid-qualification-aggregate",
            "qualification phase results are missing, duplicated, or unexpected",
        )
    expected_binding = {
        "generation_id": generation_id,
        "package_payload_sha256": package_payload_sha256,
        "projected_task_sha256": projected_task_sha256,
        "projection_sha256": projection_sha256,
        "schema": _PHASE_RESULT_SCHEMA,
        "worker_identity": worker_identity,
    }
    expected_shapes = {
        "baseline": {"records"},
        "hidden-marker": {"records"},
        "reference": {"records"},
        "malformed": {"handoff"},
        "unsafe": {"handoff"},
        "score-mismatch": {"score_mismatch"},
    }
    phases: dict[str, dict[str, object]] = {}
    for path in sorted(results_dir.glob("*.json")):
        try:
            data = path.read_bytes()
            value = json.loads(data)
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ScenarioPackageError(
                "invalid-qualification-aggregate", str(error)
            ) from error
        if not isinstance(value, dict) or canonical_json_bytes(value) != data:
            raise ScenarioPackageError(
                "invalid-qualification-aggregate",
                "qualification phase result is not canonical",
            )
        phase = value.get("phase")
        result = value.get("result")
        binding = {
            key: value.get(key) for key in expected_binding
        }
        if binding != expected_binding:
            raise ScenarioPackageError(
                "invalid-qualification-aggregate",
                "qualification phase result has a stale generation, mixed input, package, or worker",
            )
        if (
            phase not in expected_shapes
            or phase in phases
            or path.name != f"{phase}.json"
            or not isinstance(result, dict)
            or set(result) != expected_shapes[phase]
        ):
            raise ScenarioPackageError(
                "invalid-qualification-aggregate",
                "qualification phase result identity or payload is invalid",
            )
        phases[phase] = result
    if set(phases) != set(_QUALIFICATION_PHASES):
        raise ScenarioPackageError(
            "invalid-qualification-aggregate",
            "qualification phase result set is incomplete",
        )
    aggregate: dict[str, object] = {
        "binding": expected_binding,
        "phases": [
            {"name": name, "result": phases[name]}
            for name in sorted(phases)
        ],
        "schema": _PHASE_AGGREGATE_SCHEMA,
    }
    return aggregate, canonical_json_bytes(aggregate)


def _validate_aggregate_meaning(
    aggregate: dict[str, object],
    declared: dict[str, object],
) -> dict[str, dict[str, object]]:
    try:
        items = aggregate["phases"]
        if not isinstance(items, list):
            raise TypeError("aggregate phases are not a list")
        phase_results = {
            item["name"]: item["result"]
            for item in items
            if isinstance(item, dict)
        }
        baseline_records = phase_results["baseline"]["records"]
        hidden_records = phase_results["hidden-marker"]["records"]
        reference_records = phase_results["reference"]["records"]
        malformed_handoff = phase_results["malformed"]["handoff"]
        unsafe_handoff = phase_results["unsafe"]["handoff"]
        score_mismatch = phase_results["score-mismatch"]["score_mismatch"]
        if (
            not isinstance(baseline_records, list)
            or len(baseline_records) != 1
            or not isinstance(hidden_records, list)
            or len(hidden_records) != 1
            or not isinstance(reference_records, list)
            or len(reference_records) != 2
            or any(
                not isinstance(record, dict)
                for record in [
                    *baseline_records,
                    *hidden_records,
                    *reference_records,
                    malformed_handoff,
                    unsafe_handoff,
                    score_mismatch,
                ]
            )
        ):
            raise TypeError("aggregate phase payloads are incomplete")
        if (
            baseline_records[0]["structured_score_vector"]
            != declared["baseline_score_vector"]
        ):
            raise ValueError("measured baseline vector differs from the declared vector")
        if any(
            record["structured_score_vector"] != declared["reference_score_vector"]
            for record in reference_records
        ):
            raise ValueError("measured Reference vector differs from the declared vector")
        environment_ids = {
            baseline_records[0]["environment_id"],
            hidden_records[0]["environment_id"],
            *(record["environment_id"] for record in reference_records),
            malformed_handoff["environment_id"],
            unsafe_handoff["environment_id"],
            score_mismatch["environment_id"],
        }
        if (
            len(environment_ids) != 7
            or any(not isinstance(value, str) or not value for value in environment_ids)
        ):
            raise ValueError(
                "qualification did not use seven fresh Harbor environments"
            )
    except (KeyError, TypeError, ValueError) as error:
        raise ScenarioPackageError(
            "invalid-qualification-aggregate", str(error)
        ) from error
    return phase_results


def _execute_phase_tasks(
    tasks: dict[str, Callable[[], tuple[dict[str, object], str]]],
    *,
    max_parallel: int,
    cancel: threading.Event,
) -> dict[str, tuple[dict[str, object], str]]:
    if max_parallel not in {1, 2, 3}:
        raise ScenarioPackageError(
            "invalid-qualification-arguments",
            "max_parallel must be 1, 2, or 3",
        )

    def guarded(
        task: Callable[[], tuple[dict[str, object], str]],
    ) -> tuple[dict[str, object], str]:
        if cancel.is_set():
            raise ScenarioPackageError(
                "qualification-cancelled",
                "qualification phase was cancelled before execution",
            )
        return task()

    completed: dict[str, tuple[dict[str, object], str]] = {}
    if max_parallel == 1:
        try:
            for name, task in tasks.items():
                completed[name] = guarded(task)
        except BaseException:
            cancel.set()
            raise
        return completed

    with ThreadPoolExecutor(
        max_workers=max_parallel,
        thread_name_prefix="scenario-qualification",
    ) as executor:
        futures: dict[Future[tuple[dict[str, object], str]], str] = {
            executor.submit(guarded, task): name for name, task in tasks.items()
        }
        try:
            for future in as_completed(futures):
                completed[futures[future]] = future.result()
        except BaseException:
            cancel.set()
            for future in futures:
                future.cancel()
            raise
    return completed


def _trial_names(run_root: Path) -> set[str]:
    names: set[str] = set()
    for path in sorted(run_root.rglob("*.json")):
        if path.name not in {"config.json", "result.json"}:
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        trial_name = value.get("trial_name") if isinstance(value, dict) else None
        if isinstance(trial_name, str) and trial_name:
            names.add(trial_name)
    return names


def _owned_resources(
    run_root: Path,
    *,
    environment: dict[str, str],
) -> list[dict[str, str]]:
    trial_names = _trial_names(run_root)
    if not trial_names:
        return []
    agent_projects = {
        _compose_project_name(f"{trial_name}__env")
        for trial_name in trial_names
    }
    verifier_prefixes = {
        _compose_project_name(f"{trial_name}__verifier__")
        for trial_name in trial_names
    }
    commands = {
        "container": [
            "docker",
            "container",
            "ls",
            "--all",
            "--filter",
            "label=com.docker.compose.project",
            "--format",
            '{{.ID}}\t{{.Label "com.docker.compose.project"}}',
        ],
        "network": [
            "docker",
            "network",
            "ls",
            "--filter",
            "label=com.docker.compose.project",
            "--format",
            '{{.ID}}\t{{.Label "com.docker.compose.project"}}',
        ],
        "volume": [
            "docker",
            "volume",
            "ls",
            "--filter",
            "label=com.docker.compose.project",
            "--format",
            '{{.Name}}\t{{.Label "com.docker.compose.project"}}',
        ],
    }
    resources: list[dict[str, str]] = []
    for kind, command in commands.items():
        completed = _run(
            command,
            timeout=30,
            environment=environment,
            inherit_environment=False,
        )
        for line in completed.stdout.splitlines():
            identity, separator, project = line.partition("\t")
            if not separator or not identity or not project:
                continue
            if project in agent_projects or any(
                project.startswith(prefix) for prefix in verifier_prefixes
            ):
                resources.append(
                    {"id": identity, "kind": kind, "project": project}
                )
    order = {"container": 0, "network": 1, "volume": 2}
    return sorted(
        resources,
        key=lambda item: (order[item["kind"]], item["project"], item["id"]),
    )


def _cleanup_qualification_resources(
    run_root: Path,
    *,
    generation_id: str,
    environment: dict[str, str],
) -> None:
    try:
        resources = _owned_resources(run_root, environment=environment)
        removals = {
            "container": ["docker", "container", "rm", "--force"],
            "network": ["docker", "network", "rm"],
            "volume": ["docker", "volume", "rm", "--force"],
        }
        errors: list[str] = []
        for resource in resources:
            try:
                _run(
                    [*removals[resource["kind"]], resource["id"]],
                    timeout=30,
                    environment=environment,
                    inherit_environment=False,
                )
            except ScenarioPackageError as error:
                errors.append(str(error))
        remaining = _owned_resources(run_root, environment=environment)
    except ScenarioPackageError as error:
        resources = []
        remaining = []
        errors = [str(error)]
        enumeration_failed = True
    else:
        enumeration_failed = False
    if not enumeration_failed and not remaining:
        return
    quarantine = {
        "errors": errors,
        "generation_id": generation_id,
        "resources": remaining or resources,
        "status": "quarantined",
    }
    try:
        _immutable_verified_write(
            run_root / "quarantine.json", canonical_json_bytes(quarantine)
        )
    except OSError as error:
        raise ScenarioPackageError(
            "qualification-cleanup-failed",
            f"qualification resources could not be quarantined: {error}",
        ) from error
    raise ScenarioPackageError(
        "qualification-cleanup-failed",
        "qualification resources could not all be removed and were quarantined",
    )


def measure_scenario_package(
    package: Path,
    *,
    jobs_dir: Path,
    output: Path,
    worker_private_key: Path,
    provisioning_manifest: Path,
    preflight_output: Path,
    max_parallel: int = 1,
) -> dict[str, object]:
    """Run isolated Scenario Package qualification phases through Harbor."""
    if max_parallel not in {1, 2, 3}:
        raise ScenarioPackageError(
            "invalid-qualification-arguments",
            "max_parallel must be 1, 2, or 3",
        )
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
    if worker_private_key.is_relative_to(package):
        raise ScenarioPackageError(
            "invalid-qualification-input",
            "qualification worker credentials must remain outside the package payload",
        )
    if output.exists() or output.is_symlink():
        raise ScenarioPackageError(
            "qualification-publication-failed",
            f"technical qualification path already exists: {output}",
        )

    private_key = _load_private_key(worker_private_key)
    worker_identity = _worker_identity(private_key)
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
    guard_sha256 = hashlib.sha256(docker_guard.read_bytes()).hexdigest()
    docker_guard.chmod(0o555)
    expected_task_digest = str(receipt["projected_task_sha256"])
    if str(
        TypedDigest(
            DigestKind.HARBOR_TASK,
            _harbor_probe(execution_package)["content_hash"],
        )
    ) != expected_task_digest:
        raise ScenarioPackageError(
            "invalid-infrastructure",
            "preflight package projection changed before qualification",
        )
    _make_tree_read_only(execution_package)

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
                hashlib.sha256(marker.encode("utf-8")).hexdigest()
                for marker in markers
            )
        )
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ScenarioPackageError("invalid-infrastructure", str(error)) from error

    generation_id = uuid.uuid4().hex
    run_root = jobs_dir / "runs" / generation_id
    run_root.mkdir(parents=True)
    phases_root = run_root / "phases"
    results_root = run_root / "results"
    phases_root.mkdir()
    results_root.mkdir()
    docker_context = _inspect_docker_context(str(receipt["docker_context"]))
    docker_compose_plugin_directory = _docker_compose_plugin_directory()
    phase_environments = {
        name: _phase_environment(
            docker_context,
            run_root / "state" / name,
            docker_guard=docker_guard,
            docker_compose_plugin_directory=docker_compose_plugin_directory,
        )
        for name in _QUALIFICATION_PHASES
    }
    coordinator_environment = _phase_environment(
        docker_context,
        run_root / "state" / "coordinator",
        docker_guard=docker_guard,
        docker_compose_plugin_directory=docker_compose_plugin_directory,
    )
    package_payload_sha256 = str(lock["package"]["payload_sha256"])
    projection_sha256 = str(receipt["projection_sha256"])
    cancel = threading.Event()
    cleanup_attempted = False
    common_arguments = {
        "expected_score_names": expected_score_names,
        "expected_hidden_marker_digests": expected_hidden_marker_digests,
        "expected_groups": expected_groups,
    }

    def standard_phase(
        name: str,
        *,
        agent: str,
        attempts: int,
        expected_outcome: str,
    ) -> tuple[dict[str, object], str]:
        records, command_output = _run_phase(
            execution_package,
            phases_root,
            name=name,
            agent=agent,
            attempts=attempts,
            expected_outcome=expected_outcome,
            expected_task_digest=expected_task_digest,
            expected_capture_reason=None,
            environment=phase_environments[name],
            cancel=cancel,
            **common_arguments,
        )
        return {"records": records}, command_output

    def rejection_phase(kind: str) -> tuple[dict[str, object], str]:
        handoff, command_output = _run_rejection_phase(
            execution_package,
            phases_root,
            kind=kind,
            environment=phase_environments[kind],
            scratch_dir=Path(phase_environments[kind]["TMPDIR"]),
            cancel=cancel,
            **common_arguments,
        )
        return {"handoff": handoff}, command_output

    def score_mismatch_phase() -> tuple[dict[str, object], str]:
        score_mismatch, command_output = _run_score_mismatch_phase(
            execution_package,
            phases_root,
            expected_task_digest=expected_task_digest,
            environment=phase_environments["score-mismatch"],
            cancel=cancel,
            **common_arguments,
        )
        return {"score_mismatch": score_mismatch}, command_output

    phase_calls: dict[str, Callable[[], tuple[dict[str, object], str]]] = {
        "baseline": lambda: standard_phase(
            "baseline",
            agent="nop",
            attempts=1,
            expected_outcome="declared-failure",
        ),
        "hidden-marker": lambda: standard_phase(
            "hidden-marker",
            agent="nop",
            attempts=1,
            expected_outcome="declared-failure",
        ),
        "reference": lambda: standard_phase(
            "reference",
            agent="oracle",
            attempts=2,
            expected_outcome="passed",
        ),
        "malformed": lambda: rejection_phase("malformed"),
        "unsafe": lambda: rejection_phase("unsafe"),
        "score-mismatch": score_mismatch_phase,
    }

    def persist_phase(
        name: str,
        call: Callable[[], tuple[dict[str, object], str]],
    ) -> tuple[dict[str, object], str]:
        result, command_output = call()
        _write_phase_result(
            results_root / f"{name}.json",
            generation_id=generation_id,
            phase=name,
            package_payload_sha256=package_payload_sha256,
            projected_task_sha256=expected_task_digest,
            projection_sha256=projection_sha256,
            worker_identity=worker_identity,
            result=result,
        )
        return result, command_output

    tasks = {
        name: (lambda name=name, call=call: persist_phase(name, call))
        for name, call in phase_calls.items()
    }
    try:
        completed = _execute_phase_tasks(
            tasks,
            max_parallel=max_parallel,
            cancel=cancel,
        )
        pull_events = _docker_pull_events(
            sorted(run_root.rglob("docker-events-*.jsonl"))
        )
        combined_output = "".join(
            completed[name][1] for name in _QUALIFICATION_PHASES
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
        if str(
            TypedDigest(
                DigestKind.HARBOR_TASK,
                _harbor_probe(execution_package)["content_hash"],
            )
        ) != expected_task_digest:
            raise ScenarioPackageError(
                "invalid-infrastructure",
                "immutable qualification package changed during execution",
            )
        if hashlib.sha256(docker_guard.read_bytes()).hexdigest() != guard_sha256:
            raise ScenarioPackageError(
                "invalid-infrastructure",
                "preflight Docker guard changed during qualification",
            )
        aggregate, aggregate_bytes = _aggregate_phase_results(
            results_root,
            generation_id=generation_id,
            package_payload_sha256=package_payload_sha256,
            projected_task_sha256=expected_task_digest,
            projection_sha256=projection_sha256,
            worker_identity=worker_identity,
        )
        phase_results = _validate_aggregate_meaning(aggregate, declared)
        baseline_records = phase_results["baseline"]["records"]
        hidden_records = phase_results["hidden-marker"]["records"]
        reference_records = phase_results["reference"]["records"]
        malformed_handoff = phase_results["malformed"]["handoff"]
        unsafe_handoff = phase_results["unsafe"]["handoff"]
        score_mismatch = phase_results["score-mismatch"]["score_mismatch"]
        cleanup_attempted = True
        _cleanup_qualification_resources(
            run_root,
            generation_id=generation_id,
            environment=coordinator_environment,
        )
        aggregate_path = run_root / "aggregate.json"
        _immutable_verified_write(aggregate_path, aggregate_bytes)
        if aggregate_path.read_bytes() != aggregate_bytes:
            raise ScenarioPackageError(
                "qualification-publication-failed",
                "qualification aggregate digest read-back failed",
            )
    except BaseException as error:
        cancel.set()
        if not cleanup_attempted:
            try:
                _cleanup_qualification_resources(
                    run_root,
                    generation_id=generation_id,
                    environment=coordinator_environment,
                )
            except ScenarioPackageError as cleanup_error:
                raise cleanup_error from error
        raise

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
    identity = _sign_technical(technical, private_key)
    if identity != worker_identity:
        raise ScenarioPackageError(
            "invalid-technical-qualification",
            "qualification worker identity changed during aggregation",
        )
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
        "generation_id": generation_id,
        "jobs_dir": str(jobs_dir),
        "max_parallel": max_parallel,
        "message": f"measured technical qualification: {lock['scenario_id']}",
        "path": str(output),
        "scenario_id": lock["scenario_id"],
        "status": "technically-qualified",
        "technical_qualification_sha256": digest,
        "worker_identity": identity,
    }

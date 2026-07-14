from __future__ import annotations

import base64
import hashlib
import json
import os
import shlex
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
    _immutable_verified_write,
    check_scenario_package,
)


_TECHNICAL_SCHEMA_NAME = "model-benchmark/scenario-technical-qualification"
_SCHEMA_VERSION = 1


def _run(
    command: list[str],
    *,
    timeout: int,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ScenarioPackageError("qualification-runtime-failed", str(error)) from error
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
        manifest = yaml.safe_load((package / "scenario.yaml").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError, SchemaValidationError) as error:
        raise ScenarioPackageError("invalid-package-lock", str(error)) from error
    if not isinstance(lock, dict) or not isinstance(manifest, dict):
        raise ScenarioPackageError("invalid-package-lock", "invalid package declarations")
    return lock, manifest


def _image_references(lock: dict[str, Any]) -> list[str]:
    resolved = lock["resolved_inputs"]
    references = [entry["reference"] for entry in resolved["images"]]
    if not references or len(references) != len(set(references)):
        raise ScenarioPackageError(
            "qualification-input-unavailable",
            "locked image references are missing or duplicated",
        )
    return sorted(references)


def _inspect_local_images(references: list[str]) -> None:
    _run(["docker", "version", "--format", "{{.Server.Version}}"], timeout=30)
    missing: list[str] = []
    for reference in references:
        completed = subprocess.run(
            ["docker", "image", "inspect", reference, "--format", "{{.Id}}"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if completed.returncode != 0:
            missing.append(reference)
    if missing:
        raise ScenarioPackageError(
            "qualification-input-unavailable",
            "locked images are absent from the trusted cache: " + ", ".join(missing),
        )


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
        command.append("--install-only")
    return command


def provision_scenario_package(package: Path, *, jobs_dir: Path) -> dict[str, object]:
    """Populate immutable Docker/Harbor caches before the measured window."""
    package = package.resolve()
    jobs_dir = jobs_dir.resolve()
    if jobs_dir.is_relative_to(package):
        raise ScenarioPackageError(
            "invalid-qualification-output",
            "qualification jobs must remain outside the package payload",
        )
    lock, _ = _locked_package(package)
    references = _image_references(lock)
    for reference in references:
        _run(["docker", "pull", reference], timeout=600)
    jobs_dir.mkdir(parents=True, exist_ok=True)
    phase = jobs_dir / "provision"
    if phase.exists():
        raise ScenarioPackageError(
            "qualification-publication-failed",
            f"provisioning directory already exists: {phase}",
        )
    _run(
        _harbor_command(
            package,
            phase,
            agent="nop",
            attempts=1,
            install_only=True,
        ),
        timeout=900,
    )
    trial_path = _trial_results(phase, expected=1, agent="nop")[0]
    try:
        trial = json.loads(trial_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ScenarioPackageError("invalid-infrastructure", str(error)) from error
    if trial.get("exception_info") is not None:
        raise ScenarioPackageError(
            "qualification-runtime-failed",
            "Harbor provisioning recorded a trial exception",
        )
    _inspect_local_images(references)
    return {
        "images": len(references),
        "jobs_dir": str(phase),
        "message": f"provisioned locked inputs for {lock['scenario_id']}",
        "scenario_id": lock["scenario_id"],
        "status": "provisioned",
    }


def _normalized_score(value: object) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if not isinstance(value, (int, float, str)):
        raise ScenarioPackageError(
            "invalid-infrastructure",
            "score value is not numeric",
        )
    try:
        decimal = Decimal(str(value))
    except InvalidOperation as error:
        raise ScenarioPackageError("invalid-infrastructure", "invalid score value") from error
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
        if isinstance(value, dict) and value.get("task_name") and value.get("agent_info"):
            if not isinstance(value["agent_info"], dict) or value["agent_info"].get("name") != agent:
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


def _run_record(
    path: Path,
    *,
    expected_outcome: str,
    expected_capture_kind: str | None,
    expected_capture_reason: str | None,
    expected_task_digest: str,
    expected_score_names: tuple[str, ...],
    expected_hidden_marker_digests: tuple[str, ...],
) -> dict[str, object]:
    try:
        trial = json.loads(path.read_text(encoding="utf-8"))
        structured = json.loads(
            (path.parent / "verifier/verifier-result.json").read_text(encoding="utf-8")
        )
        native_reward = json.loads(
            (path.parent / "verifier/reward.json").read_text(encoding="utf-8")
        )
        native_lock = json.loads((path.parent / "lock.json").read_text(encoding="utf-8"))
        artifact_manifest = json.loads(
            (path.parent / "artifacts/manifest.json").read_text(encoding="utf-8")
        )
        capture = json.loads(
            (path.parent / "artifacts/capture/capture.json").read_text(encoding="utf-8")
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
    if collected.get("artifacts/capture/capture.json") != "ok":
        raise ScenarioPackageError(
            "invalid-infrastructure",
            "Harbor did not collect the trusted capture record",
        )
    if expected_capture_reason is not None:
        if capture.get("status") != "rejected" or capture.get("reason") != expected_capture_reason:
            raise ScenarioPackageError(
                "invalid-infrastructure",
                "trusted capture rejection does not match the diagnostic handoff",
            )
    elif capture.get("status") != "accepted" or capture.get("kind") != expected_capture_kind:
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
    outcome = "passed" if _normalized_score(rewards.get("task_success")) == "1" else "declared-failure"
    if outcome != expected_outcome:
        raise ScenarioPackageError(
            "invalid-technical-qualification",
            f"Harbor trial produced {outcome}, expected {expected_outcome}",
        )
    environment_id = trial.get("id")
    if not isinstance(environment_id, str) or not environment_id:
        raise ScenarioPackageError(
            "invalid-infrastructure",
            "Harbor trial environment identity is missing",
        )
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
    expected_capture_reason: str | None,
) -> tuple[list[dict[str, object]], str]:
    phase = jobs_dir / name
    if phase.exists():
        raise ScenarioPackageError(
            "qualification-publication-failed",
            f"qualification phase already exists: {phase}",
        )
    completed = _run(
        _harbor_command(package, phase, agent=agent, attempts=attempts),
        timeout=1200,
    )
    records = [
        _run_record(
            path,
            expected_outcome=expected_outcome,
            expected_capture_kind="patch" if agent == "oracle" else "no-op",
            expected_capture_reason=expected_capture_reason,
            expected_task_digest=expected_task_digest,
            expected_score_names=expected_score_names,
            expected_hidden_marker_digests=expected_hidden_marker_digests,
        )
        for path in _trial_results(phase, expected=attempts, agent=agent)
    ]
    return records, completed.stdout + completed.stderr


def _run_rejection_phase(
    package: Path,
    jobs_dir: Path,
    *,
    kind: str,
    expected_score_names: tuple[str, ...],
    expected_hidden_marker_digests: tuple[str, ...],
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
        checked = check_scenario_package(diagnostic)
        task_digest = checked["harbor_task_sha256"]
        if not isinstance(task_digest, str):
            raise ScenarioPackageError(
                "invalid-infrastructure",
                "diagnostic Harbor task identity is missing",
            )
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
            expected_capture_reason=expected_reason,
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
    expected_score_names: tuple[str, ...],
    expected_hidden_marker_digests: tuple[str, ...],
) -> tuple[dict[str, str], str]:
    reward = {name: 0 for name in expected_score_names}
    structured = dict(reward)
    structured["task_success"] = 1
    script = (
        "#!/bin/sh\nset -eu\nmkdir -p /logs/verifier\n"
        f"printf '%s\\n' {shlex.quote(json.dumps(structured, sort_keys=True))} "
        "> /logs/verifier/verifier-result.json\n"
        f"printf '%s\\n' {shlex.quote(json.dumps(reward, sort_keys=True))} "
        "> /logs/verifier/reward.json\n"
    )
    with tempfile.TemporaryDirectory(prefix="scenario-score-mismatch-") as temporary:
        diagnostic = Path(temporary) / "package"
        shutil.copytree(package, diagnostic, symlinks=True)
        (diagnostic / "scenario.lock.json").unlink(missing_ok=True)
        verifier_path = diagnostic / "tests/test.sh"
        verifier_path.write_text(script, encoding="utf-8")
        verifier_path.chmod(0o755)
        checked = check_scenario_package(diagnostic)
        task_digest = checked["harbor_task_sha256"]
        if not isinstance(task_digest, str):
            raise ScenarioPackageError(
                "invalid-infrastructure",
                "score-mismatch Harbor task identity is missing",
            )
        phase = jobs_dir / "score-mismatch"
        completed = _run(
            _harbor_command(diagnostic, phase, agent="nop", attempts=1),
            timeout=1200,
        )
        result_path = _trial_results(phase, expected=1, agent="nop")[0]
        try:
            _run_record(
                result_path,
                expected_outcome="declared-failure",
                expected_capture_kind="no-op",
                expected_capture_reason=None,
                expected_task_digest=task_digest,
                expected_score_names=expected_score_names,
                expected_hidden_marker_digests=expected_hidden_marker_digests,
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
        try:
            trial = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ScenarioPackageError("invalid-infrastructure", str(error)) from error
        environment_id = trial.get("id")
        if not isinstance(environment_id, str) or not environment_id:
            raise ScenarioPackageError(
                "invalid-infrastructure",
                "score-mismatch environment identity is missing",
            )
    return (
        {"environment_id": environment_id, "status": "passed"},
        completed.stdout + completed.stderr,
    )


def _docker_pull_events(started: int, finished: int) -> str:
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
        raise ScenarioPackageError("qualification-worker-key-invalid", str(error)) from error
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
) -> dict[str, object]:
    """Run baseline, hidden-marker, and Reference qualification through Harbor."""
    package = package.resolve()
    jobs_dir = jobs_dir.resolve()
    output = output.resolve()
    worker_private_key = worker_private_key.resolve()
    for candidate in (jobs_dir, output):
        if candidate.is_relative_to(package):
            raise ScenarioPackageError(
                "invalid-qualification-output",
                "qualification evidence must remain outside the package payload",
            )
    lock, manifest = _locked_package(package)
    references = _image_references(lock)
    _inspect_local_images(references)
    declared = manifest["verification"]["qualification"]
    expected_score_names = tuple(
        entry["name"] for entry in declared["baseline_score_vector"]
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
            sorted(hashlib.sha256(marker.encode("utf-8")).hexdigest() for marker in markers)
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
    expected_task_digest = lock["harbor"]["task_content_sha256"]
    baseline_records, baseline_output = _run_phase(
        package,
        jobs_dir,
        name="baseline",
        agent="nop",
        attempts=1,
        expected_outcome="declared-failure",
        expected_task_digest=expected_task_digest,
        expected_score_names=expected_score_names,
        expected_hidden_marker_digests=expected_hidden_marker_digests,
        expected_capture_reason=None,
    )
    hidden_records, hidden_output = _run_phase(
        package,
        jobs_dir,
        name="hidden-marker",
        agent="nop",
        attempts=1,
        expected_outcome="declared-failure",
        expected_task_digest=expected_task_digest,
        expected_score_names=expected_score_names,
        expected_hidden_marker_digests=expected_hidden_marker_digests,
        expected_capture_reason=None,
    )
    reference_records, reference_output = _run_phase(
        package,
        jobs_dir,
        name="reference",
        agent="oracle",
        attempts=2,
        expected_outcome="passed",
        expected_task_digest=expected_task_digest,
        expected_score_names=expected_score_names,
        expected_hidden_marker_digests=expected_hidden_marker_digests,
        expected_capture_reason=None,
    )
    malformed_handoff, malformed_output = _run_rejection_phase(
        package,
        jobs_dir,
        kind="malformed",
        expected_score_names=expected_score_names,
        expected_hidden_marker_digests=expected_hidden_marker_digests,
    )
    unsafe_handoff, unsafe_output = _run_rejection_phase(
        package,
        jobs_dir,
        kind="unsafe",
        expected_score_names=expected_score_names,
        expected_hidden_marker_digests=expected_hidden_marker_digests,
    )
    score_mismatch, score_mismatch_output = _run_score_mismatch_phase(
        package,
        jobs_dir,
        expected_score_names=expected_score_names,
        expected_hidden_marker_digests=expected_hidden_marker_digests,
    )
    finished = int(time.time())
    pull_events = _docker_pull_events(started, finished)
    combined_output = (
        baseline_output
        + hidden_output
        + reference_output
        + malformed_output
        + unsafe_output
        + score_mismatch_output
    ).lower()
    if pull_events or "pulling from" in combined_output or "downloading" in combined_output:
        raise ScenarioPackageError(
            "qualification-download-detected",
            "measured qualification downloaded an image or package",
        )
    if baseline_records[0]["structured_score_vector"] != declared["baseline_score_vector"]:
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
        "package_payload_sha256": package_record["payload_sha256"],
        "qualified_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
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
    _immutable_verified_write(output, data)
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

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable

from jsonschema import Draft202012Validator, FormatChecker

from verification.policy import Policy


class ProofError(RuntimeError):
    """A proof envelope is absent, stale, incomplete, or not live-current."""


_POINTER_PREFIX = "model-benchmark-proof-v1"


@dataclass(frozen=True)
class ProofPointer:
    gate_id: str
    policy_sha256: str
    run_id: int
    run_attempt: int
    generation_id: str
    envelope_sha256: str
    artifact_id: int


class GitHubApi:
    def __init__(self, token: str | None = None) -> None:
        self._token = token or _github_token()

    def get(self, repository: str, path: str) -> object:
        request = urllib.request.Request(
            f"https://api.github.com/repos/{repository}{path}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return _strict_json(response.read(), "GitHub response")
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
            raise ProofError(f"live GitHub currentness lookup failed: {error}") from error


def consume_proof(
    *,
    policy: Policy,
    project_root: Path,
    schema_path: Path,
    envelope_path: Path,
    bundle_root: Path,
    api_get: Callable[[str, str], object],
) -> dict[str, object]:
    schema_bytes = _read(schema_path, "proof-envelope schema")
    schema_sha256 = _sha256(schema_bytes)
    try:
        schema = _strict_json(schema_bytes, "proof-envelope schema")
        Draft202012Validator.check_schema(schema)
    except Exception as error:
        raise ProofError(f"invalid proof-envelope schema: {error}") from error

    envelope_bytes = _read(envelope_path, "proof envelope")
    envelope_sha256 = _sha256(envelope_bytes)
    envelope = _strict_json(envelope_bytes, "proof envelope")
    if not isinstance(envelope, dict):
        raise ProofError("proof envelope must be an object")
    errors = sorted(
        Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        ).iter_errors(envelope),
        key=lambda item: item.json_path,
    )
    if errors:
        raise ProofError(f"invalid proof envelope: {errors[0].json_path}: {errors[0].message}")

    gate_id = _string(envelope["gate_id"], "gate_id")
    try:
        gate = policy.fresh_gates[gate_id]
    except KeyError as error:
        raise ProofError(f"proof names an unknown gate: {gate_id}") from error
    if envelope["authority"] != "fresh_authoritative":
        raise ProofError("only fresh-authoritative envelopes are consumable")
    if envelope["repository"] != policy.repository:
        raise ProofError("proof repository does not match policy")
    if envelope["policy_sha256"] != policy.sha256:
        raise ProofError("proof policy digest is stale")
    if envelope["schema_sha256"] != schema_sha256:
        raise ProofError("proof-envelope schema digest is stale")

    candidate_sha = _string(envelope["candidate_sha"], "candidate_sha")
    current_head = _git_output(project_root, ["rev-parse", "HEAD"]).strip()
    if current_head != candidate_sha:
        raise ProofError("proof candidate is not the current fixed head")
    if envelope["source_tree_sha256"] != source_tree_sha256(
        project_root,
        candidate_sha,
    ):
        raise ProofError("proof source-tree identity is stale")

    worker = _object(envelope["worker"], "worker")
    worker_classes = gate["worker_classes"]
    assert isinstance(worker_classes, list)
    if worker["class"] not in worker_classes:
        raise ProofError("proof worker class is not allowed by policy")
    if gate["docker_required"] is True and not worker["docker_daemon"]:
        raise ProofError("Docker gate proof lacks a daemon identity")

    _verify_commands(envelope, gate, bundle_root)
    workflow = _object(envelope["workflow"], "workflow")
    if workflow["path"] != gate["workflow_path"]:
        raise ProofError("proof workflow path is not protected by policy")
    _verify_currentness(
        policy=policy,
        gate=gate,
        envelope=envelope,
        envelope_sha256=envelope_sha256,
        api_get=api_get,
    )

    return {
        "accepted": True,
        "authority": "fresh_authoritative",
        "candidate_sha": candidate_sha,
        "diagnostics": {
            "child_artifact_count": len(envelope["child_artifacts"]),
            "command_count": len(envelope["commands"]),
            "shape": "proof-consumption-diagnostics-v1",
        },
        "envelope_sha256": envelope_sha256,
        "gate_id": gate_id,
        "generation_id": envelope["generation_id"],
        "policy_sha256": policy.sha256,
        "schema": "proof-consumption-v1",
    }


def source_tree_sha256(project_root: Path, revision: str = "HEAD") -> str:
    """Hash the exact Git tree listing without consulting mutable worktree bytes."""
    try:
        completed = subprocess.run(
            ["git", "ls-tree", "-rz", "--full-tree", revision],
            cwd=project_root,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ProofError(f"cannot compute source-tree identity: {error}") from error
    if not completed.stdout:
        raise ProofError("source tree is empty")
    return _sha256(completed.stdout)


def encode_pointer(pointer: ProofPointer) -> str:
    fields = (
        _POINTER_PREFIX,
        pointer.gate_id,
        pointer.policy_sha256,
        str(pointer.run_id),
        str(pointer.run_attempt),
        pointer.generation_id,
        pointer.envelope_sha256,
        str(pointer.artifact_id),
    )
    if any("|" in field for field in fields):
        raise ProofError("proof pointer field contains a delimiter")
    return "|".join(fields)


def parse_pointer(value: object) -> ProofPointer:
    if not isinstance(value, str):
        raise ProofError("current Check Run lacks a proof pointer")
    fields = value.split("|")
    if len(fields) != 8 or fields[0] != _POINTER_PREFIX:
        raise ProofError("current Check Run proof pointer is malformed")
    try:
        run_id = int(fields[3])
        run_attempt = int(fields[4])
        artifact_id = int(fields[7])
    except ValueError as error:
        raise ProofError("current Check Run proof pointer has invalid IDs") from error
    if run_id < 1 or run_attempt < 1 or artifact_id < 1:
        raise ProofError("current Check Run proof pointer has invalid IDs")
    return ProofPointer(
        gate_id=fields[1],
        policy_sha256=fields[2],
        run_id=run_id,
        run_attempt=run_attempt,
        generation_id=fields[5],
        envelope_sha256=fields[6],
        artifact_id=artifact_id,
    )


def _verify_commands(
    envelope: dict[str, object],
    gate: dict[str, object],
    bundle_root: Path,
) -> None:
    raw_commands = envelope["commands"]
    expected_commands = gate["commands"]
    assert isinstance(raw_commands, list)
    assert isinstance(expected_commands, list)
    observed_identity = [
        (_object(command, "command")["id"], _object(command, "command")["command"])
        for command in raw_commands
    ]
    expected_identity = [
        (_object(command, "policy command")["id"], _object(command, "policy command")["command"])
        for command in expected_commands
    ]
    if observed_identity != expected_identity:
        raise ProofError("proof ordered commands drift from policy")

    artifacts = _artifact_map(envelope, bundle_root)
    for raw, expected in zip(raw_commands, expected_commands, strict=True):
        command = _object(raw, "command")
        policy_command = _object(expected, "policy command")
        if command["outcome"] != "passed" or command["exit_code"] != 0:
            raise ProofError(f"proof command did not pass: {command['id']}")
        started = _timestamp(command["started_at"], f"{command['id']}.started_at")
        completed = _timestamp(command["completed_at"], f"{command['id']}.completed_at")
        if completed < started:
            raise ProofError(f"proof command timestamps are reversed: {command['id']}")
        cases = command["cases"]
        assert isinstance(cases, list)
        case_ids = [
            _string(_object(case, "case")["id"], "case.id") for case in cases
        ]
        if len(case_ids) != len(set(case_ids)):
            raise ProofError(f"proof command has duplicate cases: {command['id']}")
        if any(_object(case, "case")["outcome"] != "passed" for case in cases):
            raise ProofError(f"proof command has a non-passing case: {command['id']}")
        if policy_command["case_inventory"] == "required":
            if not cases:
                raise ProofError(f"proof command has no mandatory cases: {command['id']}")
            artifact_path = _string(
                policy_command["acceptance_artifact"],
                "acceptance_artifact",
            )
            _verify_acceptance_artifact(
                artifact_path=artifact_path,
                artifacts=artifacts,
                expected_cases=cases,
                gate_id=_string(envelope["gate_id"], "gate_id"),
                bundle_root=bundle_root,
            )
        elif cases:
            raise ProofError(f"non-case command recorded cases: {command['id']}")


def _artifact_map(
    envelope: dict[str, object],
    bundle_root: Path,
) -> dict[str, str]:
    raw_artifacts = envelope["child_artifacts"]
    assert isinstance(raw_artifacts, list)
    result: dict[str, str] = {}
    resolved_root = bundle_root.resolve()
    for raw in raw_artifacts:
        artifact = _object(raw, "child_artifact")
        relative = _safe_relative(_string(artifact["path"], "child_artifact.path"))
        if relative in result:
            raise ProofError(f"duplicate child artifact: {relative}")
        resolved = (resolved_root / relative).resolve()
        if not resolved.is_relative_to(resolved_root):
            raise ProofError(f"child artifact escapes bundle: {relative}")
        actual = _sha256(_read(resolved, f"child artifact {relative}"))
        expected = _string(artifact["sha256"], "child_artifact.sha256")
        if actual != expected:
            raise ProofError(f"child artifact checksum mismatch: {relative}")
        result[relative] = expected
    return result


def _verify_acceptance_artifact(
    *,
    artifact_path: str,
    artifacts: dict[str, str],
    expected_cases: list[object],
    gate_id: str,
    bundle_root: Path,
) -> None:
    if artifact_path not in artifacts:
        raise ProofError(f"acceptance artifact is absent from the envelope: {artifact_path}")
    verification_path = bundle_root / artifact_path
    value = _strict_json(_read(verification_path, "acceptance artifact"), "acceptance artifact")
    artifact = _object(value, "acceptance artifact")
    expected_keys = {
        "case_results",
        "command",
        "input_identities",
        "issue",
        "output_paths",
        "schema",
    }
    if set(artifact) != expected_keys:
        raise ProofError("acceptance artifact has unknown or missing fields")
    if artifact["case_results"] != expected_cases:
        raise ProofError("proof cases differ from the child acceptance artifact")
    if artifact["issue"] != _issue_number(gate_id):
        raise ProofError("child acceptance artifact belongs to another gate")
    schema = _object(artifact["schema"], "acceptance artifact schema")
    if schema.get("name") != "model-benchmark/verification-artifact":
        raise ProofError("child artifact is not verification evidence")

    manifest_path = str(PurePosixPath(artifact_path).with_name("sha256sums.txt"))
    if manifest_path not in artifacts:
        raise ProofError("acceptance checksum manifest is absent from the envelope")
    manifest = _read(bundle_root / manifest_path, "acceptance checksum manifest")
    expected_line = f"{artifacts[artifact_path]}  {artifact_path}\n".encode("utf-8")
    if manifest != expected_line:
        raise ProofError("acceptance checksum manifest is malformed or stale")


def _verify_currentness(
    *,
    policy: Policy,
    gate: dict[str, object],
    envelope: dict[str, object],
    envelope_sha256: str,
    api_get: Callable[[str, str], object],
) -> None:
    candidate_sha = _string(envelope["candidate_sha"], "candidate_sha")
    check_name = _string(gate["check_name"], "check_name")
    query = urllib.parse.urlencode(
        {"check_name": check_name, "filter": "all", "per_page": "100"}
    )
    response = _object(
        api_get(
            policy.repository,
            f"/commits/{candidate_sha}/check-runs?{query}",
        ),
        "Check Runs response",
    )
    raw_runs = response.get("check_runs")
    if not isinstance(raw_runs, list):
        raise ProofError("live Check Runs response is incomplete")
    trusted_app = _string(gate["trusted_app_slug"], "trusted_app_slug")
    candidates: list[dict[str, object]] = []
    for raw in raw_runs:
        check = _object(raw, "Check Run")
        app = check.get("app")
        if (
            check.get("name") == check_name
            and isinstance(app, dict)
            and app.get("slug") == trusted_app
        ):
            if not isinstance(check.get("id"), int):
                raise ProofError("trusted Check Run is missing its ID")
            candidates.append(check)
    if not candidates:
        raise ProofError("no trusted current Check Run exists")
    current = max(candidates, key=lambda item: int(item["id"]))
    if current.get("status") != "completed" or current.get("conclusion") != "success":
        raise ProofError("newest trusted Check Run is not completed successfully")

    pointer = parse_pointer(current.get("external_id"))
    workflow = _object(envelope["workflow"], "workflow")
    expected = ProofPointer(
        gate_id=_string(envelope["gate_id"], "gate_id"),
        policy_sha256=policy.sha256,
        run_id=_integer(workflow["run_id"], "workflow.run_id"),
        run_attempt=_integer(workflow["run_attempt"], "workflow.run_attempt"),
        generation_id=_string(envelope["generation_id"], "generation_id"),
        envelope_sha256=envelope_sha256,
        artifact_id=pointer.artifact_id,
    )
    if pointer != expected or current["id"] != workflow["check_run_id"]:
        raise ProofError("current Check Run does not point to this exact proof")

    run = _object(
        api_get(policy.repository, f"/actions/runs/{pointer.run_id}"),
        "workflow run",
    )
    if (
        run.get("head_sha") != envelope["candidate_sha"]
        or run.get("path") != gate["workflow_path"]
        or run.get("run_attempt") != pointer.run_attempt
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
    ):
        raise ProofError("live workflow run does not match the proof")

    artifact = _object(
        api_get(policy.repository, f"/actions/artifacts/{pointer.artifact_id}"),
        "workflow artifact",
    )
    artifact_run = artifact.get("workflow_run")
    if (
        artifact.get("expired") is not False
        or not isinstance(artifact_run, dict)
        or artifact_run.get("id") != pointer.run_id
        or artifact_run.get("head_sha") != envelope["candidate_sha"]
    ):
        raise ProofError("proof artifact is unavailable or belongs to another run")


def _github_token() -> str:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token
    try:
        completed = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise ProofError("live GitHub currentness requires GITHUB_TOKEN, GH_TOKEN, or gh auth") from error
    token = completed.stdout.strip()
    if not token:
        raise ProofError("GitHub authentication returned an empty token")
    return token


def _git_output(project_root: Path, arguments: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ProofError(f"cannot inspect fixed Git head: {error}") from error
    return completed.stdout


def _issue_number(gate_id: str) -> int:
    prefix = "issue-"
    if not gate_id.startswith(prefix) or not gate_id[len(prefix) :].isdigit():
        raise ProofError(f"acceptance gate ID is not issue-owned: {gate_id}")
    return int(gate_id[len(prefix) :])


def _safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) in {"", "."}:
        raise ProofError(f"unsafe artifact path: {value}")
    return path.as_posix()


def _strict_json(data: bytes, field: str) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ProofError(f"{field} contains duplicate key: {key}")
            result[key] = value
        return result

    try:
        return json.loads(data, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProofError(f"{field} is not strict JSON: {error}") from error


def _timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ProofError(f"{field} is not a timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ProofError(f"{field} is not a timestamp") from error
    if parsed.tzinfo is None:
        raise ProofError(f"{field} lacks a timezone")
    return parsed


def _read(path: Path, field: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise ProofError(f"cannot read {field}: {path}") from error


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ProofError(f"{field} must be an object")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProofError(f"{field} must be a non-empty string")
    return value


def _integer(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ProofError(f"{field} must be a positive integer")
    return value

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shlex
import signal
import subprocess
import urllib.parse
import uuid
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Protocol

from jsonschema import Draft202012Validator, FormatChecker

from verification.policy import Policy
from verification.proof import ProofPointer, encode_pointer, parse_pointer, source_tree_sha256


class PublicationError(RuntimeError):
    """A fresh authoritative proof could not be published safely."""


class PublisherApi(Protocol):
    def get(self, repository: str, path: str) -> object: ...

    def post(self, repository: str, path: str, value: dict[str, object]) -> object: ...

    def patch(self, repository: str, path: str, value: dict[str, object]) -> object: ...

    def download(self, repository: str, path: str) -> bytes: ...


@dataclass(frozen=True)
class PublicationState:
    version: int
    repository: str
    gate_id: str
    candidate_sha: str
    policy_sha256: str
    generation_id: str
    check_run_id: int
    run_id: int
    run_attempt: int
    artifact_name: str
    publication_root: str
    bundle_path: str
    envelope_sha256: str
    workflow_path: str


_ATTEMPT_PREFIX = "model-benchmark-proof-attempt-v1"
_REVOCATION_PREFIX = "model-benchmark-proof-revocation-v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_STATE_FIELDS = {field.name for field in PublicationState.__dataclass_fields__.values()}


def prepare_proof(
    *,
    policy: Policy,
    project_root: Path,
    schema_path: Path,
    publication_root: Path,
    state_path: Path,
    gate_id: str,
    candidate_sha: str,
    run_id: int,
    run_attempt: int,
    requester: str,
    reason: str,
    worker_class: str,
    worker_identity: str,
    docker_daemon: str | None,
    api: PublisherApi,
    generation_id: str | None = None,
) -> PublicationState:
    gate = _fresh_gate(policy, gate_id)
    _git_sha(candidate_sha)
    _positive(run_id, "run_id")
    _positive(run_attempt, "run_attempt")
    for value, field in (
        (requester, "requester"),
        (reason, "reason"),
        (worker_class, "worker_class"),
        (worker_identity, "worker_identity"),
    ):
        _non_empty(value, field)

    generation = generation_id or str(uuid.uuid4())
    _generation_id(generation)
    pending_pointer = _attempt_pointer(
        gate_id=gate_id,
        policy_sha256=policy.sha256,
        run_id=run_id,
        run_attempt=run_attempt,
        generation_id=generation,
    )
    check = _object(
        api.post(
            policy.repository,
            "/check-runs",
            {
                "external_id": pending_pointer,
                "head_sha": candidate_sha,
                "name": gate["check_name"],
                "output": {
                    "summary": (
                        f"Fresh proof generation `{generation}` requested by "
                        f"`{requester}`: {reason}"
                    ),
                    "title": f"Fresh proof {gate_id} in progress",
                },
                "status": "in_progress",
            },
        ),
        "created Check Run",
    )
    check_run_id = _positive(check.get("id"), "check_run_id")

    try:
        if (
            check.get("name") != gate["check_name"]
            or check.get("head_sha") != candidate_sha
            or check.get("status") not in {"queued", "in_progress"}
            or check.get("external_id") != pending_pointer
        ):
            raise PublicationError("GitHub did not confirm the pending Check Run")
        state = _prepare_after_check(
            policy=policy,
            project_root=project_root,
            schema_path=schema_path,
            publication_root=publication_root,
            gate_id=gate_id,
            gate=gate,
            candidate_sha=candidate_sha,
            generation_id=generation,
            check_run_id=check_run_id,
            run_id=run_id,
            run_attempt=run_attempt,
            requester=requester,
            reason=reason,
            worker_class=worker_class,
            worker_identity=worker_identity,
            docker_daemon=docker_daemon,
        )
        _write_state(state_path, state)
        return state
    except BaseException as error:
        _best_effort_failure(
            api=api,
            repository=policy.repository,
            check_run_id=check_run_id,
            title=f"Fresh proof {gate_id} failed",
            summary=f"Generation `{generation}` failed before immutable upload: {type(error).__name__}",
            external_id=pending_pointer,
        )
        if isinstance(error, PublicationError):
            raise
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        raise PublicationError(f"fresh proof preparation failed: {error}") from error


def finalize_proof(
    *,
    policy: Policy,
    schema_path: Path,
    state_path: Path,
    artifact_id: int,
    artifact_digest: str,
    api: PublisherApi,
) -> ProofPointer:
    state = _read_state(state_path)
    gate = _validate_state_for_policy(policy, state)
    _positive(artifact_id, "artifact_id")
    digest = _artifact_digest(artifact_digest)

    try:
        _verify_pending_check(policy, gate, state, api)
        _verify_workflow_run(policy, state, api)
        artifact = _object(
            api.get(policy.repository, f"/actions/artifacts/{artifact_id}"),
            "uploaded artifact",
        )
        workflow_run = _object(artifact.get("workflow_run"), "artifact workflow_run")
        if (
            artifact.get("id") != artifact_id
            or artifact.get("name") != state.artifact_name
            or artifact.get("expired") is not False
            or _artifact_digest(artifact.get("digest")) != digest
            or workflow_run.get("id") != state.run_id
            or workflow_run.get("head_sha") != state.candidate_sha
        ):
            raise PublicationError("uploaded artifact identity does not match the generation")

        archive = api.download(
            policy.repository,
            f"/actions/artifacts/{artifact_id}/zip",
        )
        if hashlib.sha256(archive).hexdigest() != digest:
            raise PublicationError("uploaded artifact digest read-back failed")
        envelope = _verify_archive(
            archive=archive,
            schema_path=schema_path,
            state=state,
        )
        if envelope["policy_sha256"] != policy.sha256:
            raise PublicationError("uploaded envelope policy digest is stale")

        pointer = ProofPointer(
            gate_id=state.gate_id,
            policy_sha256=state.policy_sha256,
            run_id=state.run_id,
            run_attempt=state.run_attempt,
            generation_id=state.generation_id,
            envelope_sha256=state.envelope_sha256,
            artifact_id=artifact_id,
        )
        encoded = encode_pointer(pointer)
        response = _object(
            api.patch(
                policy.repository,
                f"/check-runs/{state.check_run_id}",
                {
                    "completed_at": _timestamp(),
                    "conclusion": "success",
                    "external_id": encoded,
                    "output": {
                        "summary": (
                            f"Immutable artifact `{artifact_id}` read back with envelope "
                            f"SHA-256 `{state.envelope_sha256}`."
                        ),
                        "title": f"Fresh proof {state.gate_id} published",
                    },
                    "status": "completed",
                },
            ),
            "successful Check Run update",
        )
        if (
            response.get("id") != state.check_run_id
            or response.get("status") != "completed"
            or response.get("conclusion") != "success"
            or response.get("external_id") != encoded
        ):
            raise PublicationError("GitHub did not confirm the successful Check Run update")
        return pointer
    except BaseException as error:
        _best_effort_failure(
            api=api,
            repository=policy.repository,
            check_run_id=state.check_run_id,
            title=f"Fresh proof {state.gate_id} failed",
            summary=(
                f"Generation `{state.generation_id}` failed upload/read-back: "
                f"{type(error).__name__}"
            ),
            external_id=_attempt_pointer(
                gate_id=state.gate_id,
                policy_sha256=state.policy_sha256,
                run_id=state.run_id,
                run_attempt=state.run_attempt,
                generation_id=state.generation_id,
            ),
        )
        if isinstance(error, PublicationError):
            raise
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        raise PublicationError(f"fresh proof finalization failed: {error}") from error


def fail_proof(
    *,
    policy: Policy,
    state_path: Path,
    reason: str,
    api: PublisherApi,
) -> None:
    state = _read_state(state_path)
    gate = _validate_state_for_policy(policy, state)
    _non_empty(reason, "failure reason")
    _verify_pending_check(policy, gate, state, api)
    response = _object(
        api.patch(
            policy.repository,
            f"/check-runs/{state.check_run_id}",
            {
                "completed_at": _timestamp(),
                "conclusion": "failure",
                "external_id": _attempt_pointer(
                    gate_id=state.gate_id,
                    policy_sha256=state.policy_sha256,
                    run_id=state.run_id,
                    run_attempt=state.run_attempt,
                    generation_id=state.generation_id,
                ),
                "output": {
                    "summary": reason,
                    "title": f"Fresh proof {state.gate_id} failed",
                },
                "status": "completed",
            },
        ),
        "failed Check Run update",
    )
    if response.get("id") != state.check_run_id or response.get("conclusion") != "failure":
        raise PublicationError("GitHub did not confirm the failed Check Run update")


def revoke_proof(
    *,
    policy: Policy,
    gate_id: str,
    candidate_sha: str,
    generation_id: str,
    requester: str,
    reason: str,
    api: PublisherApi,
) -> int:
    gate = _fresh_gate(policy, gate_id)
    _git_sha(candidate_sha)
    _generation_id(generation_id)
    _non_empty(requester, "requester")
    _non_empty(reason, "reason")
    current = _current_trusted_check(
        policy=policy,
        gate=gate,
        candidate_sha=candidate_sha,
        api=api,
    )
    if current.get("status") != "completed" or current.get("conclusion") != "success":
        raise PublicationError("only the exact current successful proof can be revoked")
    pointer = parse_pointer(current.get("external_id"))
    if (
        pointer.gate_id != gate_id
        or pointer.policy_sha256 != policy.sha256
        or pointer.generation_id != generation_id
    ):
        raise PublicationError("revocation target is not the exact current successful proof")

    external_id = "|".join(
        (_REVOCATION_PREFIX, gate_id, policy.sha256, generation_id)
    )
    response = _object(
        api.post(
            policy.repository,
            "/check-runs",
            {
                "completed_at": _timestamp(),
                "conclusion": "failure",
                "external_id": external_id,
                "head_sha": candidate_sha,
                "name": gate["check_name"],
                "output": {
                    "summary": (
                        f"Requester: `{requester}`\n\nReason: {reason}\n\n"
                        f"Revoked generation: `{generation_id}`"
                    ),
                    "title": f"Fresh proof {gate_id} revoked",
                },
                "status": "completed",
            },
        ),
        "revocation Check Run",
    )
    check_run_id = _positive(response.get("id"), "revocation check_run_id")
    if response.get("status") != "completed" or response.get("conclusion") != "failure":
        raise PublicationError("GitHub did not confirm the failed revocation Check Run")
    return check_run_id


def _prepare_after_check(
    *,
    policy: Policy,
    project_root: Path,
    schema_path: Path,
    publication_root: Path,
    gate_id: str,
    gate: dict[str, object],
    candidate_sha: str,
    generation_id: str,
    check_run_id: int,
    run_id: int,
    run_attempt: int,
    requester: str,
    reason: str,
    worker_class: str,
    worker_identity: str,
    docker_daemon: str | None,
) -> PublicationState:
    project_root = project_root.resolve()
    publication_root = publication_root.resolve()
    if publication_root.is_relative_to(project_root):
        raise PublicationError("publication root must be outside the candidate worktree")
    if worker_class not in gate["worker_classes"]:
        raise PublicationError(f"worker class is not authorized for {gate_id}: {worker_class}")
    if gate["docker_required"] is True and not docker_daemon:
        raise PublicationError(f"Docker gate {gate_id} requires a daemon identity")
    if _git(project_root, "rev-parse", "HEAD").strip() != candidate_sha:
        raise PublicationError("candidate SHA is not the checked-out fixed head")

    generation_root = publication_root / generation_id
    generation_root.mkdir(parents=True, exist_ok=False)
    execution_root = generation_root / "execution"
    staging_root = generation_root / "staging"
    bundle_root = staging_root / "bundle"
    published_root = generation_root / "published"
    bundle_root.mkdir(parents=True)

    commands = gate["commands"]
    assert isinstance(commands, list)
    declared_paths = _declared_artifact_paths(commands)
    command_results: list[dict[str, object]] = []
    child_artifacts: dict[str, str] = {}
    worktree_created = False
    command_error: BaseException | None = None
    try:
        _git(project_root, "worktree", "add", "--detach", str(execution_root), candidate_sha)
        worktree_created = True
        for relative in declared_paths:
            stale = execution_root / relative
            if stale.is_symlink():
                raise PublicationError(f"declared artifact is a symlink: {relative}")
            if stale.exists():
                if not stale.is_file():
                    raise PublicationError(f"declared artifact is not a file: {relative}")
                stale.unlink()

        for raw_command in commands:
            command = _object(raw_command, "policy command")
            started_at = _timestamp()
            exit_code, outcome = _run_command(
                literal=_string(command["command"], "command"),
                cwd=execution_root,
                timeout_seconds=_positive(command["timeout_seconds"], "timeout_seconds"),
            )
            completed_at = _timestamp()
            cases = _command_cases(command, execution_root) if exit_code == 0 else []
            command_results.append(
                {
                    "cases": cases,
                    "command": command["command"],
                    "completed_at": completed_at,
                    "exit_code": exit_code,
                    "id": command["id"],
                    "outcome": outcome,
                    "started_at": started_at,
                    "timeout_seconds": command["timeout_seconds"],
                }
            )
            if exit_code != 0:
                raise PublicationError(
                    f"fresh command {command['id']} {outcome} with exit code {exit_code}"
                )
            _verify_execution_tree(
                execution_root=execution_root,
                candidate_sha=candidate_sha,
                declared_paths=declared_paths,
            )
            _copy_declared_artifacts(
                command=command,
                execution_root=execution_root,
                bundle_root=bundle_root,
                child_artifacts=child_artifacts,
            )
    except BaseException as error:
        command_error = error
    finally:
        if worktree_created:
            try:
                _remove_worktree(project_root, execution_root)
            except BaseException as cleanup_error:
                if command_error is None:
                    command_error = cleanup_error
    if command_error is not None:
        raise command_error

    schema_bytes = _read_bytes(schema_path, "proof-envelope schema")
    schema = _json_object(schema_bytes, "proof-envelope schema")
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as error:
        raise PublicationError(f"invalid proof-envelope schema: {error}") from error

    envelope: dict[str, object] = {
        "authority": "fresh_authoritative",
        "candidate_sha": candidate_sha,
        "child_artifacts": [
            {"path": path, "sha256": digest}
            for path, digest in sorted(child_artifacts.items())
        ],
        "commands": command_results,
        "created_at": _timestamp(),
        "gate_id": gate_id,
        "generation_id": generation_id,
        "policy_sha256": policy.sha256,
        "repository": policy.repository,
        "schema_sha256": hashlib.sha256(schema_bytes).hexdigest(),
        "source_tree_sha256": source_tree_sha256(project_root, candidate_sha),
        "version": 1,
        "worker": {
            "class": worker_class,
            "docker_daemon": docker_daemon,
            "identity": worker_identity,
            "qualification_state": "qualified",
        },
        "workflow": {
            "check_run_id": check_run_id,
            "path": gate["workflow_path"],
            "reason": reason,
            "requester": requester,
            "run_attempt": run_attempt,
            "run_id": run_id,
        },
    }
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(envelope),
        key=lambda item: item.json_path,
    )
    if errors:
        raise PublicationError(
            f"generated proof envelope is invalid: {errors[0].json_path}: {errors[0].message}"
        )
    envelope_bytes = _canonical_json(envelope)
    envelope_sha256 = hashlib.sha256(envelope_bytes).hexdigest()
    _write_new(bundle_root / "proof-envelope.json", envelope_bytes)
    _write_new(
        bundle_root / "sha256sums.txt",
        f"{envelope_sha256}  proof-envelope.json\n".encode("utf-8"),
    )
    os.replace(staging_root, published_root)

    artifact_name = (
        f"fresh-proof-{gate_id}-{candidate_sha[:12]}-{generation_id}"
    )
    return PublicationState(
        version=1,
        repository=policy.repository,
        gate_id=gate_id,
        candidate_sha=candidate_sha,
        policy_sha256=policy.sha256,
        generation_id=generation_id,
        check_run_id=check_run_id,
        run_id=run_id,
        run_attempt=run_attempt,
        artifact_name=artifact_name,
        publication_root=str(publication_root),
        bundle_path=str(published_root / "bundle"),
        envelope_sha256=envelope_sha256,
        workflow_path=_string(gate["workflow_path"], "workflow_path"),
    )


def _verify_pending_check(
    policy: Policy,
    gate: dict[str, object],
    state: PublicationState,
    api: PublisherApi,
) -> None:
    check = _object(
        api.get(policy.repository, f"/check-runs/{state.check_run_id}"),
        "pending Check Run",
    )
    if (
        check.get("id") != state.check_run_id
        or check.get("name") != gate["check_name"]
        or check.get("head_sha") != state.candidate_sha
        or check.get("status") not in {"queued", "in_progress"}
        or check.get("external_id") != _attempt_pointer(
            gate_id=state.gate_id,
            policy_sha256=state.policy_sha256,
            run_id=state.run_id,
            run_attempt=state.run_attempt,
            generation_id=state.generation_id,
        )
    ):
        raise PublicationError("pending Check Run no longer matches the generation")


def _verify_workflow_run(
    policy: Policy, state: PublicationState, api: PublisherApi
) -> None:
    run = _object(
        api.get(policy.repository, f"/actions/runs/{state.run_id}"),
        "workflow run",
    )
    status = run.get("status")
    if (
        run.get("id") != state.run_id
        or run.get("head_sha") != state.candidate_sha
        or run.get("run_attempt") != state.run_attempt
        or run.get("path") != state.workflow_path
        or status not in {"in_progress", "completed"}
        or (status == "completed" and run.get("conclusion") != "success")
    ):
        raise PublicationError("workflow run identity does not match the generation")


def _verify_archive(
    *,
    archive: bytes,
    schema_path: Path,
    state: PublicationState,
) -> dict[str, object]:
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            files: dict[str, bytes] = {}
            for info in bundle.infolist():
                relative = _safe_relative(info.filename.rstrip("/"))
                if info.is_dir():
                    continue
                if relative in files:
                    raise PublicationError(f"uploaded artifact has duplicate member: {relative}")
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise PublicationError(f"uploaded artifact has symlink member: {relative}")
                files[relative] = bundle.read(info)
    except (OSError, zipfile.BadZipFile, RuntimeError) as error:
        if isinstance(error, PublicationError):
            raise
        raise PublicationError(f"uploaded artifact is not a readable ZIP: {error}") from error

    try:
        envelope_bytes = files["proof-envelope.json"]
        checksum_bytes = files["sha256sums.txt"]
    except KeyError as error:
        raise PublicationError("uploaded artifact lacks its outer envelope or checksum") from error
    if hashlib.sha256(envelope_bytes).hexdigest() != state.envelope_sha256:
        raise PublicationError("uploaded envelope digest differs from the published generation")
    expected_checksum = f"{state.envelope_sha256}  proof-envelope.json\n".encode("utf-8")
    if checksum_bytes != expected_checksum:
        raise PublicationError("uploaded outer checksum manifest is malformed")

    schema = _json_object(_read_bytes(schema_path, "proof-envelope schema"), "proof-envelope schema")
    envelope = _json_object(envelope_bytes, "uploaded proof envelope")
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(envelope),
        key=lambda item: item.json_path,
    )
    if errors:
        raise PublicationError(
            f"uploaded proof envelope is invalid: {errors[0].json_path}: {errors[0].message}"
        )
    workflow = _object(envelope["workflow"], "uploaded workflow")
    if (
        envelope["repository"] != state.repository
        or envelope["gate_id"] != state.gate_id
        or envelope["candidate_sha"] != state.candidate_sha
        or envelope["policy_sha256"] != state.policy_sha256
        or envelope["generation_id"] != state.generation_id
        or workflow["check_run_id"] != state.check_run_id
        or workflow["run_id"] != state.run_id
        or workflow["run_attempt"] != state.run_attempt
        or workflow["path"] != state.workflow_path
    ):
        raise PublicationError("uploaded envelope identity differs from publication state")
    artifacts = envelope["child_artifacts"]
    assert isinstance(artifacts, list)
    expected_files = {
        "proof-envelope.json",
        "sha256sums.txt",
        *(
            _safe_relative(_object(item, "child artifact")["path"])
            for item in artifacts
        ),
    }
    if set(files) != expected_files:
        raise PublicationError("uploaded artifact members differ from the envelope inventory")
    for item in artifacts:
        child = _object(item, "child artifact")
        relative = _safe_relative(child["path"])
        if hashlib.sha256(files[relative]).hexdigest() != child["sha256"]:
            raise PublicationError(f"uploaded child artifact digest mismatch: {relative}")
    return envelope


def _current_trusted_check(
    *,
    policy: Policy,
    gate: dict[str, object],
    candidate_sha: str,
    api: PublisherApi,
) -> dict[str, object]:
    query = urllib.parse.urlencode(
        {"check_name": gate["check_name"], "filter": "all", "per_page": "100"}
    )
    response = _object(
        api.get(policy.repository, f"/commits/{candidate_sha}/check-runs?{query}"),
        "Check Runs response",
    )
    raw_checks = response.get("check_runs")
    if not isinstance(raw_checks, list):
        raise PublicationError("live Check Runs response is incomplete")
    trusted: list[dict[str, object]] = []
    for raw in raw_checks:
        check = _object(raw, "Check Run")
        app = check.get("app")
        if (
            check.get("name") == gate["check_name"]
            and isinstance(app, dict)
            and app.get("slug") == gate["trusted_app_slug"]
        ):
            _positive(check.get("id"), "Check Run id")
            trusted.append(check)
    if not trusted:
        raise PublicationError("no trusted current Check Run exists")
    return max(trusted, key=lambda item: int(item["id"]))


def _command_cases(command: dict[str, object], execution_root: Path) -> list[object]:
    if command["case_inventory"] == "none":
        return []
    artifact_path = _safe_relative(command["acceptance_artifact"])
    artifact = _json_object(
        _read_bytes(execution_root / artifact_path, "acceptance artifact"),
        "acceptance artifact",
    )
    raw_cases = artifact.get("case_results")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise PublicationError(f"mandatory case inventory is absent: {command['id']}")
    cases: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in raw_cases:
        case = _object(raw, "mandatory case")
        if set(case) != {"id", "outcome"}:
            raise PublicationError("mandatory case has unknown or missing fields")
        case_id = _string(case["id"], "case.id")
        if case_id in seen:
            raise PublicationError(f"duplicate mandatory case: {case_id}")
        seen.add(case_id)
        if case["outcome"] != "passed":
            raise PublicationError(f"mandatory case did not pass: {case_id}")
        cases.append({"id": case_id, "outcome": "passed"})
    return cases


def _verify_execution_tree(
    *, execution_root: Path, candidate_sha: str, declared_paths: tuple[str, ...]
) -> None:
    if _git(execution_root, "rev-parse", "HEAD").strip() != candidate_sha:
        raise PublicationError("fresh command changed the fixed candidate HEAD")
    changed = {
        _safe_relative(path)
        for path in _git(
            execution_root, "diff", "--name-only", "-z", "HEAD", "--"
        ).split("\0")
        if path
    }
    unexpected = sorted(changed - set(declared_paths))
    if unexpected:
        raise PublicationError(
            "fresh command changed undeclared tracked paths: " + ", ".join(unexpected)
        )


def _copy_declared_artifacts(
    *,
    command: dict[str, object],
    execution_root: Path,
    bundle_root: Path,
    child_artifacts: dict[str, str],
) -> None:
    artifacts = command["artifacts"]
    assert isinstance(artifacts, list)
    for value in artifacts:
        relative = _safe_relative(value)
        source = execution_root / relative
        if source.is_symlink() or not source.is_file():
            raise PublicationError(f"declared child artifact is absent or unsafe: {relative}")
        data = _read_bytes(source, f"child artifact {relative}")
        destination = bundle_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        _write_new(destination, data)
        child_artifacts[relative] = hashlib.sha256(data).hexdigest()


def _declared_artifact_paths(commands: list[object]) -> tuple[str, ...]:
    paths: list[str] = []
    for raw in commands:
        command = _object(raw, "policy command")
        artifacts = command["artifacts"]
        assert isinstance(artifacts, list)
        paths.extend(_safe_relative(value) for value in artifacts)
    if len(paths) != len(set(paths)):
        raise PublicationError("fresh gate declares a child artifact more than once")
    return tuple(paths)


def _run_command(*, literal: str, cwd: Path, timeout_seconds: int) -> tuple[int, str]:
    try:
        argv = shlex.split(literal)
    except ValueError as error:
        raise PublicationError(f"invalid literal fresh command: {error}") from error
    if not argv:
        raise PublicationError("literal fresh command is empty")
    try:
        process = subprocess.Popen(argv, cwd=cwd, start_new_session=True)
    except OSError as error:
        raise PublicationError(f"cannot start fresh command: {error}") from error
    try:
        exit_code = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        _terminate_process_group(process)
        return 124, "timed_out"
    return exit_code, "passed" if exit_code == 0 else "failed"


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


def _remove_worktree(project_root: Path, execution_root: Path) -> None:
    try:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(execution_root)],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise PublicationError(f"cannot clean generation worktree: {error}") from error
    if execution_root.exists():
        raise PublicationError("generation worktree remains after cleanup")


def _fresh_gate(policy: Policy, gate_id: str) -> dict[str, object]:
    try:
        return policy.fresh_gates[gate_id]
    except KeyError as error:
        raise PublicationError(f"unknown fresh-authoritative gate: {gate_id}") from error


def _validate_state_for_policy(
    policy: Policy, state: PublicationState
) -> dict[str, object]:
    gate = _fresh_gate(policy, state.gate_id)
    if state.repository != policy.repository:
        raise PublicationError("publication state repository differs from policy")
    if state.policy_sha256 != policy.sha256:
        raise PublicationError("publication state policy digest is stale")
    if state.workflow_path != gate["workflow_path"]:
        raise PublicationError("publication state workflow differs from policy")
    return gate


def _attempt_pointer(
    *,
    gate_id: str,
    policy_sha256: str,
    run_id: int,
    run_attempt: int,
    generation_id: str,
) -> str:
    return "|".join(
        (
            _ATTEMPT_PREFIX,
            gate_id,
            policy_sha256,
            str(run_id),
            str(run_attempt),
            generation_id,
        )
    )


def _best_effort_failure(
    *,
    api: PublisherApi,
    repository: str,
    check_run_id: int,
    title: str,
    summary: str,
    external_id: str,
) -> None:
    try:
        api.patch(
            repository,
            f"/check-runs/{check_run_id}",
            {
                "completed_at": _timestamp(),
                "conclusion": "failure",
                "external_id": external_id,
                "output": {"summary": summary, "title": title},
                "status": "completed",
            },
        )
    except Exception:
        pass


def _write_state(path: Path, state: PublicationState) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{state.generation_id}.tmp")
    _write_new(temporary, _canonical_json(asdict(state)), mode=0o600)
    os.replace(temporary, path)


def _read_state(path: Path) -> PublicationState:
    value = _json_object(_read_bytes(path, "publication state"), "publication state")
    if (
        set(value) != _STATE_FIELDS
        or value.get("version") != 1
        or isinstance(value.get("version"), bool)
    ):
        raise PublicationError("publication state has unknown or missing fields")
    try:
        state = PublicationState(**value)
    except TypeError as error:
        raise PublicationError(f"publication state is malformed: {error}") from error
    _git_sha(state.candidate_sha)
    _generation_id(state.generation_id)
    _positive(state.check_run_id, "check_run_id")
    _positive(state.run_id, "run_id")
    _positive(state.run_attempt, "run_attempt")
    policy_sha256 = _string(state.policy_sha256, "publication state policy_sha256")
    envelope_sha256 = _string(state.envelope_sha256, "publication state envelope_sha256")
    if not _SHA256.fullmatch(policy_sha256) or not _SHA256.fullmatch(envelope_sha256):
        raise PublicationError("publication state has an invalid digest")
    for field in (
        "repository",
        "gate_id",
        "artifact_name",
        "publication_root",
        "bundle_path",
        "workflow_path",
    ):
        _string(getattr(state, field), f"publication state {field}")
    publication = Path(state.publication_root).resolve()
    bundle = Path(state.bundle_path).resolve()
    expected_bundle = publication / state.generation_id / "published" / "bundle"
    if bundle != expected_bundle:
        raise PublicationError("publication state bundle does not name its sealed generation")
    return state


def _write_new(path: Path, data: bytes, *, mode: int = 0o644) -> None:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as error:
        raise PublicationError(f"cannot write immutable publication file {path}: {error}") from error


def _git(project_root: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise PublicationError(f"Git setup failed: {error}") from error
    return completed.stdout


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _json_object(data: bytes, field: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise PublicationError(f"{field} contains duplicate key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(data, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PublicationError(f"{field} is not strict JSON: {error}") from error
    return _object(value, field)


def _read_bytes(path: Path, field: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise PublicationError(f"cannot read {field}: {path}") from error


def _artifact_digest(value: object) -> str:
    if not isinstance(value, str):
        raise PublicationError("artifact digest must be a SHA-256 string")
    digest = value.removeprefix("sha256:")
    if not _SHA256.fullmatch(digest):
        raise PublicationError("artifact digest is malformed")
    return digest


def _safe_relative(value: object) -> str:
    if not isinstance(value, str):
        raise PublicationError("artifact path must be a string")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) in {"", "."}:
        raise PublicationError(f"unsafe artifact path: {value}")
    return path.as_posix()


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _git_sha(value: object) -> str:
    if not isinstance(value, str) or not _GIT_SHA.fullmatch(value):
        raise PublicationError("candidate SHA must be 40 lowercase hexadecimal characters")
    return value


def _generation_id(value: object) -> str:
    if not isinstance(value, str):
        raise PublicationError("generation ID must be a UUID")
    try:
        parsed = uuid.UUID(value)
    except ValueError as error:
        raise PublicationError("generation ID must be a UUID") from error
    if str(parsed) != value:
        raise PublicationError("generation ID must use canonical lowercase UUID form")
    return value


def _positive(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise PublicationError(f"{field} must be a positive integer")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise PublicationError(f"{field} must be a non-empty string")
    return value


def _non_empty(value: object, field: str) -> str:
    return _string(value, field)


def _object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise PublicationError(f"{field} must be an object")
    return value

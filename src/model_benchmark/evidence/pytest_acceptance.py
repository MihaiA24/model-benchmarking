from __future__ import annotations

import hashlib
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from model_benchmark.declarations.identities import DigestKind, TypedDigest
from model_benchmark.declarations.schemas import SchemaRegistry
from model_benchmark.evidence.attestation import (
    LiveAttestationError,
    verify_live_attestation,
)
from model_benchmark.evidence.verification import (
    VerificationCase,
    VerificationInput,
    write_verification_artifacts,
)


_ISSUE_DIRECTORY = re.compile(r"^issue_([1-9][0-9]*)$")


@dataclass
class _AcceptanceState:
    project_root: Path
    issue_path: Path
    issue: int
    collected: set[str] = field(default_factory=set)
    results: dict[str, str] = field(default_factory=dict)
    invalid_mandatory_result: bool = False
    extra_inputs: list[VerificationInput] = field(default_factory=list)


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("model-benchmark acceptance")
    group.addoption(
        "--require-docker",
        action="store_true",
        default=False,
        help="fail unless a real Docker daemon responds",
    )
    group.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="run live cases only with a sealed prerequisite attestation",
    )


def _schema_root() -> Path:
    source_root = Path(__file__).resolve().parents[3] / "schemas"
    if source_root.is_dir():
        return source_root
    packaged_root = Path(__file__).resolve().parents[1] / "published_schemas"
    if packaged_root.is_dir():
        return packaged_root
    raise pytest.UsageError("published model-benchmark schemas are unavailable")


def _acceptance_state(config: pytest.Config) -> _AcceptanceState | None:
    project_root = Path(config.rootpath).resolve()
    acceptance_root = (project_root / "tests/acceptance").resolve()
    targets = [Path(argument).resolve() for argument in config.args]
    acceptance_targets = [path for path in targets if path.is_relative_to(acceptance_root)]
    if not acceptance_targets:
        return None
    if len(targets) != 1 or len(acceptance_targets) != 1:
        raise pytest.UsageError("acceptance proof must target exactly one issue directory")
    issue_path = acceptance_targets[0]
    match = _ISSUE_DIRECTORY.fullmatch(issue_path.name)
    if issue_path.parent != acceptance_root or match is None or not issue_path.is_dir():
        raise pytest.UsageError("acceptance proof path must be tests/acceptance/issue_N")
    if config.getoption("maxfail") != 1:
        raise pytest.UsageError("acceptance proof requires --maxfail=1")
    return _AcceptanceState(
        project_root=project_root,
        issue_path=issue_path,
        issue=int(match.group(1)),
    )


def _state(config: pytest.Config) -> _AcceptanceState | None:
    return getattr(config, "_model_benchmark_acceptance_state", None)


def _remove_authoritative_outputs(state: _AcceptanceState) -> None:
    root = state.project_root / f"artifacts/acceptance/issue-{state.issue}"
    for name in ("verification.json", "sha256sums.txt"):
        (root / name).unlink(missing_ok=True)


def _require_docker() -> bytes:
    docker = shutil.which("docker")
    if docker is None:
        raise pytest.UsageError("--require-docker requested but docker is not installed")
    try:
        completed = subprocess.run(
            [docker, "info", "--format", "{{json .ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise pytest.UsageError(f"Docker daemon probe failed: {error}") from error
    if completed.returncode != 0 or not completed.stdout.strip():
        detail = completed.stderr.strip() or "Docker daemon did not return a server version"
        raise pytest.UsageError(detail)
    return completed.stdout.strip().encode("utf-8")


def pytest_configure(config: pytest.Config) -> None:
    state = _acceptance_state(config)
    setattr(config, "_model_benchmark_acceptance_state", state)
    if state is not None:
        _remove_authoritative_outputs(state)

    if config.getoption("require_docker"):
        docker_identity = TypedDigest.from_bytes(DigestKind.ARTIFACT, _require_docker())
        if state is not None:
            state.extra_inputs.append(
                VerificationInput(name="docker-server-version", digest=docker_identity)
            )

    if config.getoption("run_live"):
        if state is None:
            raise pytest.UsageError("--run-live requires an exact issue acceptance path")
        attestation_value = os.environ.get("MODEL_BENCHMARK_LIVE_ATTESTATION")
        if not attestation_value:
            raise pytest.UsageError(
                "--run-live requires MODEL_BENCHMARK_LIVE_ATTESTATION"
            )
        attestation_path = Path(attestation_value)
        try:
            verify_live_attestation(
                path=attestation_path,
                schema_root=_schema_root(),
                issue=state.issue,
            )
            attestation_bytes = attestation_path.read_bytes()
        except (LiveAttestationError, OSError) as error:
            raise pytest.UsageError(f"invalid live prerequisite attestation: {error}") from error
        state.extra_inputs.append(
            VerificationInput(
                name="live-prerequisite-attestation",
                digest=TypedDigest.from_bytes(DigestKind.ARTIFACT, attestation_bytes),
            )
        )


def pytest_collection_finish(session: pytest.Session) -> None:
    state = _state(session.config)
    if state is None:
        return
    state.collected = {item.nodeid for item in session.items}
    if not state.collected:
        state.invalid_mandatory_result = True
    for item in session.items:
        if not Path(str(item.path)).resolve().is_relative_to(state.issue_path):
            state.invalid_mandatory_result = True


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[Any]):
    outcome = yield
    report = outcome.get_result()
    state = _state(item.config)
    if state is None:
        return
    if report.skipped or hasattr(report, "wasxfail"):
        state.invalid_mandatory_result = True
    if report.when == "call":
        state.results[item.nodeid] = report.outcome


def _tree_digest(paths: list[Path], project_root: Path) -> TypedDigest:
    digest = hashlib.sha256()
    files: list[Path] = []
    for root in paths:
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(
                path
                for path in root.rglob("*")
                if path.is_file() and "__pycache__" not in path.parts
            )
    for path in sorted(set(files)):
        relative = path.relative_to(project_root).as_posix().encode("utf-8")
        data = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return TypedDigest(kind=DigestKind.SOURCE_TREE, value=digest.hexdigest())


def _verification_inputs(state: _AcceptanceState) -> list[VerificationInput]:
    lock_path = state.project_root / "uv.lock"
    pyproject_path = state.project_root / "pyproject.toml"
    if not lock_path.is_file():
        raise RuntimeError("acceptance proof requires uv.lock")
    paths = [
        state.project_root / "src",
        state.project_root / "tests/conftest.py",
        state.issue_path,
    ]
    schema_registry = SchemaRegistry(_schema_root())
    inputs = [
        VerificationInput(
            name="acceptance-source-tree",
            digest=_tree_digest(paths, state.project_root),
        ),
        VerificationInput(
            name="canonicalization-contract",
            digest=TypedDigest.parse(schema_registry.canonicalization.sha256),
        ),
        VerificationInput(
            name="schema-catalog",
            digest=TypedDigest.from_bytes(
                DigestKind.ARTIFACT,
                (_schema_root() / "catalog.json").read_bytes(),
            ),
        ),
        VerificationInput(
            name="uv.lock",
            digest=TypedDigest.from_bytes(DigestKind.UV_LOCK, lock_path.read_bytes()),
        ),
    ]
    if pyproject_path.is_file():
        inputs.append(
            VerificationInput(
                name="pyproject.toml",
                digest=TypedDigest.from_bytes(
                    DigestKind.ARTIFACT,
                    pyproject_path.read_bytes(),
                ),
            )
        )
    return inputs + state.extra_inputs


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    state = _state(session.config)
    if state is None:
        return
    complete = (
        exitstatus == pytest.ExitCode.OK
        and not state.invalid_mandatory_result
        and state.collected == set(state.results)
        and all(result == "passed" for result in state.results.values())
    )
    if not complete:
        _remove_authoritative_outputs(state)
        if exitstatus == pytest.ExitCode.OK:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
        return

    command = "uv run --frozen pytest " + shlex.join(
        list(session.config.invocation_params.args)
    )
    try:
        write_verification_artifacts(
            project_root=state.project_root,
            schema_root=_schema_root(),
            issue=state.issue,
            command=command,
            inputs=_verification_inputs(state),
            cases=[
                VerificationCase(id=nodeid, outcome="passed")
                for nodeid in sorted(state.collected)
            ],
        )
    except BaseException as error:
        _remove_authoritative_outputs(state)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_line(f"acceptance artifact publication failed: {error}", red=True)

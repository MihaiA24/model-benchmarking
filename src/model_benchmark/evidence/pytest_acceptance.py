from __future__ import annotations

import hashlib
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from model_benchmark.declarations.canonical import canonical_json_bytes
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


_ISSUE_DIRECTORY = re.compile(r"^issue_([1-9][0-9]*)(?:_[a-z][a-z0-9_]*)?$")
_SELECTION_OPTIONS = (
    "keyword",
    "markexpr",
    "ignore",
    "ignore_glob",
    "deselect",
    "lf",
    "failedfirst",
    "newfirst",
    "stepwise",
    "collectonly",
)
_MANDATORY_DOCKER_ISSUES = {29, 55}


@dataclass
class _AcceptanceState:
    project_root: Path
    issue_path: Path
    issue: int
    collected: set[str] = field(default_factory=set)
    results: dict[str, str] = field(default_factory=dict)
    invalid_mandatory_result: bool = False
    extra_inputs: list[VerificationInput] = field(default_factory=list)
    input_paths: list[Path] = field(default_factory=list)
    launcher_command: str = ""


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
    group.addoption(
        "--acceptance-input",
        action="append",
        default=[],
        metavar="PROJECT_RELATIVE_PATH",
        help="include an additional file or directory in the Acceptance Source Tree",
    )


def _schema_root() -> Path:
    source_root = Path(__file__).resolve().parents[3] / "schemas"
    if source_root.is_dir():
        return source_root
    packaged_root = Path(__file__).resolve().parents[1] / "published_schemas"
    if packaged_root.is_dir():
        return packaged_root
    raise pytest.UsageError("published model-benchmark schemas are unavailable")


def _recognized_issue_states(
    project_root: Path,
    arguments: list[str],
) -> list[_AcceptanceState]:
    acceptance_root = (project_root / "tests/acceptance").resolve()
    states: dict[int, _AcceptanceState] = {}
    for argument in arguments:
        if argument.startswith("-"):
            continue
        target_text = argument.split("::", 1)[0]
        target = Path(target_text)
        if not target.is_absolute():
            target = project_root / target
        target = target.resolve()
        try:
            relative = target.relative_to(acceptance_root)
        except ValueError:
            continue
        if not relative.parts:
            continue
        issue_directory = relative.parts[0]
        match = _ISSUE_DIRECTORY.fullmatch(issue_directory)
        if match is None:
            continue
        issue = int(match.group(1))
        states[issue] = _AcceptanceState(
            project_root=project_root,
            issue_path=acceptance_root / issue_directory,
            issue=issue,
        )
    return list(states.values())


def pytest_load_initial_conftests(
    early_config: pytest.Config,
    parser: pytest.Parser,
    args: list[str],
) -> None:
    del parser
    project_root = Path(early_config.rootpath).resolve()
    for state in _recognized_issue_states(project_root, args):
        _remove_authoritative_outputs(state)


def _acceptance_state(config: pytest.Config) -> _AcceptanceState | None:
    project_root = Path(config.rootpath).resolve()
    acceptance_root = (project_root / "tests/acceptance").resolve()
    targets = [Path(argument.split("::", 1)[0]).resolve() for argument in config.args]
    acceptance_targets = [
        path for path in targets if path.is_relative_to(acceptance_root)
    ]
    if not acceptance_targets:
        return None
    states = _recognized_issue_states(project_root, list(config.args))
    if len(states) != 1 or not states[0].issue_path.is_dir():
        raise pytest.UsageError(
            "Acceptance Verification Artifact path must be a single "
            "tests/acceptance/issue_N[_slug] directory"
        )
    _assert_unambiguous_issue_directory(states[0])
    return states[0]


def _assert_unambiguous_issue_directory(state: _AcceptanceState) -> None:
    matches = sorted(
        entry.name
        for entry in state.issue_path.parent.iterdir()
        if entry.is_dir()
        and (found := _ISSUE_DIRECTORY.fullmatch(entry.name)) is not None
        and int(found.group(1)) == state.issue
    )
    if len(matches) > 1:
        raise pytest.UsageError(
            f"issue {state.issue} is claimed by multiple acceptance directories: "
            + ", ".join(matches)
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
        raise pytest.UsageError(
            "--require-docker requested but docker is not installed"
        )
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
        detail = (
            completed.stderr.strip() or "Docker daemon did not return a server version"
        )
        raise pytest.UsageError(detail)
    return completed.stdout.strip().encode("utf-8")


def _launcher_provenance(
    state: _AcceptanceState,
) -> tuple[str, list[VerificationInput]]:
    normalized: list[str] = []
    python_executable = Path(sys.executable)
    if not python_executable.is_file():
        raise pytest.UsageError("Python executable is unavailable for provenance")
    inputs: list[VerificationInput] = [
        VerificationInput(
            name="python-executable",
            digest=TypedDigest.from_bytes(
                DigestKind.ARTIFACT,
                python_executable.read_bytes(),
            ),
        )
    ]
    roots = (
        (Path(sys.prefix).absolute(), "@python-env"),
        (state.project_root.absolute(), "@project"),
    )
    for index, argument in enumerate(sys.orig_argv):
        path = Path(argument)
        normalized_argument = argument
        if path.is_absolute():
            for root, label in roots:
                try:
                    relative = path.relative_to(root)
                except ValueError:
                    continue
                normalized_argument = f"{label}/{relative.as_posix()}"
                break
            if path.is_file():
                inputs.append(
                    VerificationInput(
                        name=f"launcher-argv-{index}",
                        digest=TypedDigest.from_bytes(
                            DigestKind.ARTIFACT,
                            path.read_bytes(),
                        ),
                    )
                )
        normalized.append(normalized_argument)
    return shlex.join(normalized), inputs


def pytest_configure(config: pytest.Config) -> None:
    state = _acceptance_state(config)
    setattr(config, "_model_benchmark_acceptance_state", state)
    if state is not None:
        _remove_authoritative_outputs(state)
    try:
        if state is not None:
            exact_target = len(config.args) == 1 and "::" not in config.args[0]
            if not exact_target or Path(config.args[0]).resolve() != state.issue_path:
                raise pytest.UsageError(
                    "Acceptance Verification Artifact must target exactly one issue directory"
                )
            if config.getoption("maxfail") != 1:
                raise pytest.UsageError(
                    "Acceptance Verification Artifact requires --maxfail=1"
                )
            for option in _SELECTION_OPTIONS:
                if config.getoption(option, default=None):
                    raise pytest.UsageError(
                        f"Acceptance Verification Artifact forbids selection option: {option}"
                    )
            for value in config.getoption("acceptance_input") or []:
                relative = Path(value)
                resolved = (state.project_root / relative).resolve()
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or not resolved.is_relative_to(state.project_root)
                    or not resolved.exists()
                ):
                    raise pytest.UsageError(f"invalid acceptance input path: {value}")
                state.input_paths.append(resolved)
            state.launcher_command, launcher_inputs = _launcher_provenance(state)
            state.extra_inputs.extend(launcher_inputs)

        if config.getoption("require_docker") or (
            state is not None and state.issue in _MANDATORY_DOCKER_ISSUES
        ):
            docker_identity = TypedDigest.from_bytes(
                DigestKind.ARTIFACT, _require_docker()
            )
            if state is not None:
                state.extra_inputs.append(
                    VerificationInput(
                        name="docker-server-version", digest=docker_identity
                    )
                )

        if config.getoption("run_live"):
            if state is None:
                raise pytest.UsageError(
                    "--run-live requires an exact issue acceptance path"
                )
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
                raise pytest.UsageError(
                    f"invalid live prerequisite attestation: {error}"
                ) from error
            state.extra_inputs.append(
                VerificationInput(
                    name="live-prerequisite-attestation",
                    digest=TypedDigest.from_bytes(
                        DigestKind.ARTIFACT, attestation_bytes
                    ),
                )
            )
    except BaseException:
        if state is not None:
            _remove_authoritative_outputs(state)
        raise


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_collection_modifyitems(
    session: pytest.Session,
    config: pytest.Config,
    items: list[pytest.Item],
):
    state = _state(config)
    inventory = {item.nodeid for item in items}
    yield
    if state is None:
        return
    selected = {item.nodeid for item in items}
    state.collected = inventory
    if selected != inventory:
        state.invalid_mandatory_result = True


def pytest_deselected(items: list[pytest.Item]) -> None:
    if not items:
        return
    state = _state(items[0].config)
    if state is not None:
        state.invalid_mandatory_result = True


@pytest.fixture
def acceptance_observation(
    request: pytest.FixtureRequest,
) -> Any:
    state = _state(request.config)
    if state is None:
        raise RuntimeError("acceptance observations require an exact issue gate")

    def record(name: str, value: object) -> None:
        if not name or any(item.name == name for item in state.extra_inputs):
            raise RuntimeError(f"invalid or duplicate acceptance observation: {name!r}")
        state.extra_inputs.append(
            VerificationInput(
                name=name,
                digest=TypedDigest.from_bytes(
                    DigestKind.ARTIFACT, canonical_json_bytes(value)
                ),
            )
        )

    return record


def pytest_collection_finish(session: pytest.Session) -> None:
    state = _state(session.config)
    if state is None:
        return
    selected = {item.nodeid for item in session.items}
    if not state.collected:
        state.collected = selected
    if selected != state.collected:
        state.invalid_mandatory_result = True
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


def _is_tree_digest_excluded(path: Path) -> bool:
    return "__pycache__" in path.parts


def _tree_digest(paths: list[Path], project_root: Path) -> TypedDigest:
    digest = hashlib.sha256()
    files: list[Path] = []
    resolved_project_root = project_root.resolve()
    for root in paths:
        if _is_tree_digest_excluded(root):
            continue
        if root.is_symlink():
            raise RuntimeError(f"Acceptance Source Tree input cannot be a symlink: {root}")
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            for path in root.rglob("*"):
                if _is_tree_digest_excluded(path):
                    continue
                if path.is_symlink():
                    raise RuntimeError(
                        f"Acceptance Source Tree input cannot contain symlinks: {path}"
                    )
                if path.is_file():
                    files.append(path)
    for path in sorted(set(files)):
        resolved = path.resolve()
        if not resolved.is_relative_to(resolved_project_root):
            raise RuntimeError(f"Acceptance Source Tree input escapes project root: {path}")
        relative = path.relative_to(project_root).as_posix().encode("utf-8")
        data = resolved.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return TypedDigest(kind=DigestKind.SOURCE_TREE, value=digest.hexdigest())


def _acceptance_source_paths(state: _AcceptanceState) -> list[Path]:
    paths = [
        state.project_root / "src",
        state.project_root / "tests/conftest.py",
        state.issue_path,
    ]
    fixture_root = state.project_root / "tests/fixtures"
    if fixture_root.exists():
        paths.append(fixture_root)
    for production_root in ("profiles", "scaffolds"):
        candidate = state.project_root / production_root
        if candidate.exists():
            paths.append(candidate)
    return paths + state.input_paths


def _assert_clean_source_tree(state: _AcceptanceState) -> None:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("Acceptance Verification Artifact publication requires git")
    project_root = state.project_root.resolve()
    paths = sorted(
        {
            path.resolve().relative_to(project_root).as_posix()
            for path in _acceptance_source_paths(state)
        }
    )
    completed = subprocess.run(
        [
            git,
            "--literal-pathspecs",
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignore-submodules=none",
            "--",
            *paths,
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"git status exited {completed.returncode}"
        raise RuntimeError(f"Acceptance Source Tree cleanliness check failed: {detail}")
    if dirty := completed.stdout.strip():
        raise RuntimeError(f"Acceptance Source Tree is dirty:\n{dirty}")
    ignored = subprocess.run(
        [
            git,
            "--literal-pathspecs",
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
            "-z",
            "--",
            *paths,
        ],
        cwd=project_root,
        capture_output=True,
        check=False,
    )
    if ignored.returncode != 0:
        detail = ignored.stderr.decode(errors="replace").strip() or (
            f"git ls-files exited {ignored.returncode}"
        )
        raise RuntimeError(f"Acceptance Source Tree cleanliness check failed: {detail}")
    ignored_paths = []
    for encoded_path in ignored.stdout.split(b"\0"):
        if not encoded_path:
            continue
        path = os.fsdecode(encoded_path)
        if not _is_tree_digest_excluded(Path(path)):
            ignored_paths.append(path)
    if ignored_paths:
        dirty = "\n".join(f"!! {path}" for path in ignored_paths)
        raise RuntimeError(f"Acceptance Source Tree is dirty:\n{dirty}")

def _verification_inputs(state: _AcceptanceState) -> list[VerificationInput]:
    lock_path = state.project_root / "uv.lock"
    pyproject_path = state.project_root / "pyproject.toml"
    if not lock_path.is_file():
        raise RuntimeError("Acceptance Verification Artifact requires uv.lock")
    paths = _acceptance_source_paths(state)
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

    try:
        _assert_clean_source_tree(state)
        write_verification_artifacts(
            project_root=state.project_root,
            schema_root=_schema_root(),
            issue=state.issue,
            command=state.launcher_command,
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
            reporter.write_line(
                f"Acceptance Verification Artifact publication failed: {error}", red=True
            )

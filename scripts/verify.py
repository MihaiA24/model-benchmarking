from __future__ import annotations

import argparse
import json
import os
import resource
import shlex
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from verification.policy import (  # noqa: E402
    Policy,
    PolicyError,
    changes_from_file,
    changes_from_git,
    load_policy,
    tracked_paths,
)
class DevelopmentRunError(RuntimeError):
    """A Docker-free development command violated its execution contract."""


@dataclass(frozen=True)
class CommandDiagnostic:
    slice_id: str
    command: str
    duration_ms: int
    exit_code: int


_FORBIDDEN_COMMAND_TOKENS = {
    "--require-docker",
    "--run-live",
    "docker",
}
_SECRET_MARKERS = (
    "API_KEY",
    "TOKEN",
    "MODEL_BENCHMARK_LIVE_ATTESTATION",
    "OPENAI_",
    "ANTHROPIC_",
    "OPENROUTER_",
)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    policy_path = arguments.policy.resolve()
    try:
        policy = load_policy(policy_path)
        if arguments.action == "audit-policy":
            paths = tracked_paths(PROJECT_ROOT)
            missing = policy.audit_paths(paths)
            if missing:
                raise PolicyError(
                    "tracked paths lack policy classification: " + ", ".join(missing)
                )
            _emit(
                {
                    "authority": "none",
                    "classified_path_count": len(paths),
                    "policy_sha256": policy.sha256,
                    "schema": "verification-policy-audit-v1",
                }
            )
            return 0
        if arguments.action in {"select", "run-development"}:
            changes = _changes(arguments)
            selection = policy.select(changes)
            if arguments.action == "select":
                _emit(policy.selection_document(selection))
                return 0
            _emit(run_development(policy, selection))
            return 0
        parser.error(f"unsupported action: {arguments.action}")
    except (DevelopmentRunError, PolicyError) as error:
        print(f"verification failed: {error}", file=sys.stderr)
        return 2


def run_development(policy: Policy, selection: object) -> dict[str, object]:
    development_names = getattr(selection, "development")
    slices = policy.development_slices
    snapshot = _authoritative_snapshot(PROJECT_ROOT)
    diagnostics: list[CommandDiagnostic] = []
    started = time.monotonic()
    usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)

    with tempfile.TemporaryDirectory(prefix="model-benchmark-development-") as raw_guard:
        guard_root = Path(raw_guard)
        _write_guards(guard_root)
        environment = _development_environment(guard_root)
        for slice_id in development_names:
            raw_slice = slices[slice_id]
            commands = raw_slice["commands"]
            assert isinstance(commands, list)
            for command in commands:
                assert isinstance(command, str)
                argv = _development_argv(command)
                command_started = time.monotonic()
                completed = subprocess.run(
                    argv,
                    cwd=PROJECT_ROOT,
                    env=environment,
                    check=False,
                )
                diagnostics.append(
                    CommandDiagnostic(
                        slice_id=slice_id,
                        command=command,
                        duration_ms=round((time.monotonic() - command_started) * 1000),
                        exit_code=completed.returncode,
                    )
                )
                if completed.returncode != 0:
                    _restore_authoritative_snapshot(PROJECT_ROOT, snapshot)
                    raise DevelopmentRunError(
                        f"development command failed ({completed.returncode}): {command}"
                    )
                if _authoritative_snapshot(PROJECT_ROOT) != snapshot:
                    _restore_authoritative_snapshot(PROJECT_ROOT, snapshot)
                    raise DevelopmentRunError(
                        f"development command attempted authoritative publication: {command}"
                    )

    usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {
        "authority": "none",
        "commands": [
            {
                "command": item.command,
                "duration_ms": item.duration_ms,
                "exit_code": item.exit_code,
                "slice_id": item.slice_id,
            }
            for item in diagnostics
        ],
        "diagnostics": {
            "command_count": len(diagnostics),
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "max_rss_bytes": _rss_bytes(
                max(0, usage_after.ru_maxrss - usage_before.ru_maxrss)
            ),
            "shape": "development-run-diagnostics-v1",
        },
        "environment": {
            "acceptance_publication": "forbidden",
            "docker": "forbidden",
            "network": "forbidden",
            "provider_credentials": "removed",
        },
        "policy_sha256": policy.sha256,
        "schema": "development-run-v1",
    }


def _rss_bytes(value: float) -> int:
    return round(value if sys.platform == "darwin" else value * 1024)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit, select, and run Docker-free local development verification.",
    )
    default_policy = PROJECT_ROOT / "verification/policy.json"
    subparsers = parser.add_subparsers(dest="action", required=True)

    audit = subparsers.add_parser("audit-policy")
    audit.add_argument("--policy", type=Path, default=default_policy)

    for name in ("select", "run-development"):
        command = subparsers.add_parser(name)
        command.add_argument("--policy", type=Path, default=default_policy)
        command.add_argument("--base")
        command.add_argument("--head")
        command.add_argument("--changed-paths-file", type=Path)
    return parser


def _changes(arguments: argparse.Namespace) -> object:
    file = arguments.changed_paths_file
    uses_git = arguments.base is not None or arguments.head is not None
    if file is not None and uses_git:
        raise PolicyError(
            "use either --base/--head or --changed-paths-file, not both"
        )
    if file is not None:
        return changes_from_file(file.resolve())
    if arguments.base is None or arguments.head is None:
        raise PolicyError("selection requires --base/--head or --changed-paths-file")
    return changes_from_git(PROJECT_ROOT, arguments.base, arguments.head)


def _development_argv(command: str) -> list[str]:
    try:
        argv = shlex.split(command)
    except ValueError as error:
        raise DevelopmentRunError(f"invalid development command: {error}") from error
    if not argv:
        raise DevelopmentRunError("development command is empty")
    lowered = {token.lower() for token in argv}
    if lowered.intersection(_FORBIDDEN_COMMAND_TOKENS) or any(
        token.startswith("tests/acceptance/") for token in argv
    ):
        raise DevelopmentRunError(
            f"development command crosses an authoritative or Docker boundary: {command}"
        )
    if argv[:4] == ["uv", "run", "--offline", "--frozen"]:
        return argv
    if argv[:3] in (["uv", "lock", "--check"], ["python", "-m", "compileall"]):
        return argv
    raise DevelopmentRunError(f"development command is not an allowed offline shape: {command}")


def _development_environment(guard_root: Path) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not any(marker in key.upper() for marker in _SECRET_MARKERS)
    }
    existing_pythonpath = environment.get("PYTHONPATH")
    python_paths = [str(guard_root), str(PROJECT_ROOT)]
    if existing_pythonpath:
        python_paths.append(existing_pythonpath)
    environment.update(
        {
            "ALL_PROXY": "http://127.0.0.1:9",
            "DOCKER_HOST": f"unix://{guard_root / 'forbidden-docker.sock'}",
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "HTTP_PROXY": "http://127.0.0.1:9",
            "MODEL_BENCHMARK_DEVELOPMENT": "1",
            "NO_PROXY": "",
            "PATH": os.pathsep.join([str(guard_root), environment.get("PATH", "")]),
            "PYTHONPATH": os.pathsep.join(python_paths),
            "UV_OFFLINE": "1",
        }
    )
    return environment


def _write_guards(guard_root: Path) -> None:
    docker = guard_root / "docker"
    docker.write_text(
        "#!/bin/sh\nprintf '%s\\n' 'Docker is forbidden in development verification' >&2\nexit 97\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    (guard_root / "sitecustomize.py").write_text(
        """import socket


def _forbidden(*args, **kwargs):
    raise RuntimeError("network is forbidden in development verification")


socket.create_connection = _forbidden
socket.getaddrinfo = _forbidden
socket.socket.connect = _forbidden
socket.socket.connect_ex = _forbidden
""",
        encoding="utf-8",
    )


def _authoritative_snapshot(project_root: Path) -> dict[str, bytes]:
    root = project_root / "artifacts/acceptance"
    if not root.exists():
        return {}
    snapshot: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise DevelopmentRunError(f"authoritative output cannot be a symlink: {path}")
        if path.is_file():
            snapshot[path.relative_to(root).as_posix()] = path.read_bytes()
    return snapshot


def _restore_authoritative_snapshot(
    project_root: Path,
    snapshot: dict[str, bytes],
) -> None:
    root = project_root / "artifacts/acceptance"
    if root.exists():
        for path in sorted(root.rglob("*"), reverse=True):
            if path.is_file() or path.is_symlink():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass
    for relative, data in snapshot.items():
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)


def _emit(value: dict[str, object]) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())

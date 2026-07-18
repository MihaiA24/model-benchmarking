from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import stat
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Callable, Mapping

from model_benchmark.declarations.canonical import canonical_json_bytes
from model_benchmark.declarations.identities import DigestKind, IdentityError, TypedDigest
from model_benchmark.runtime.credential_proxy import PROVIDER_API_KEY_ENV


HARNESS_CONDITIONS = frozenset({"omp", "opencode", "hermes"})
WALL_TIME_SECONDS = 1_800
_SHUTDOWN_GRACE_SECONDS = 5
_REDACTION = b"[REDACTED]"


class ConditionRunnerError(ValueError):
    """A sealed Harness launch or fresh Trial boundary is invalid."""


class ConditionAdapterError(RuntimeError):
    """The pinned condition cannot be provisioned or qualified safely."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class ConditionQualification:
    qualified: bool
    reason_code: str
    evidence: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", MappingProxyType(dict(self.evidence)))


@dataclass(frozen=True)
class ConditionDefinition:
    """One Condition behind the seam.

    The typed verb callables are the adapter's entire host-side surface;
    ``kind`` distinguishes the three Harness Conditions from the Raw API
    Baseline, which shares the seam but provisions nothing host-side and
    is never qualified through RPC trials.
    """

    name: str
    kind: str
    lock_path: Callable[[], Path]
    load_lock: Callable[[], tuple[bytes, Mapping[str, object], TypedDigest]]
    launch_shim_path: Callable[[], Path]
    validate_lock: Callable[[bytes], TypedDigest] | None = None
    provision: Callable[..., object] | None = None
    seal_process: Callable[..., SealedConditionProcess] | None = None
    evaluate_qualification: Callable[..., ConditionQualification] | None = None
    image_base: str | None = None
    entrypoint_script: str | None = None
    requires_scenario_target: bool = False

    def __post_init__(self) -> None:
        if self.kind not in {"harness", "baseline"}:
            raise ConditionAdapterError(
                "invalid-condition-definition",
                f"{self.name} kind must be harness or baseline",
            )
        if self.kind == "harness" and None in (
            self.validate_lock,
            self.provision,
            self.seal_process,
            self.evaluate_qualification,
        ):
            raise ConditionAdapterError(
                "invalid-condition-definition",
                f"{self.name} harness definition is missing a verb",
            )


def publish_bytes(
    destination: Path, data: bytes, *, mode: int, condition: str
) -> None:
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        temporary.chmod(mode)
        os.link(temporary, destination)
    except FileExistsError:
        if read_regular_file(destination) != data:
            raise ConditionAdapterError(
                "immutable-cache-conflict",
                f"immutable {condition} cache path changed: {destination.name}",
            )
    finally:
        temporary.unlink(missing_ok=True)


def read_regular_file(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError("not a regular file")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def provider_events(path: Path) -> list[dict[str, object]]:
    try:
        lines = read_regular_file(path).splitlines()
    except OSError:
        return []
    events: list[dict[str, object]] = []
    for line in lines:
        try:
            value = json.loads(line.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError):
            return []
        if isinstance(value, dict) and value.get("event") == "provider-response":
            events.append(value)
    return events


@dataclass(frozen=True)
class SealedConditionProcess:
    """Internal launch facts produced by one of the three pinned adapters."""

    condition: str
    artifact_path: Path
    artifact_identity: str
    arguments: tuple[str, ...]
    environment: Mapping[str, str] = field(repr=False)
    native_artifact_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.condition not in HARNESS_CONDITIONS:
            raise ConditionRunnerError("only the three fixed Harness conditions are supported")
        try:
            identity = TypedDigest.parse(self.artifact_identity)
        except IdentityError as error:
            raise ConditionRunnerError(str(error)) from error
        if identity.kind is not DigestKind.ARTIFACT:
            raise ConditionRunnerError("Harness artifact must use artifact:sha256 identity")
        if any(not value or "\x00" in value for value in self.arguments):
            raise ConditionRunnerError("sealed Harness arguments must be non-empty and control-free")
        if PROVIDER_API_KEY_ENV in self.environment:
            raise ConditionRunnerError("real provider credential is forbidden in Trial environment")
        if any(
            not name or "=" in name or "\x00" in name or "\x00" in value
            for name, value in self.environment.items()
        ):
            raise ConditionRunnerError("sealed Trial environment is invalid")
        for value in self.native_artifact_paths:
            _safe_relative_path(value, label="native artifact")
        object.__setattr__(self, "environment", MappingProxyType(dict(self.environment)))


@dataclass(frozen=True)
class ConditionRunRequest:
    process: SealedConditionProcess
    repository_source: Path
    trial_root: Path
    developer_brief: bytes
    trial_proxy_token: str = field(repr=False)
    sensitive_values: tuple[str, ...] = field(repr=False)

    def __post_init__(self) -> None:
        try:
            text = self.developer_brief.decode("utf-8", errors="strict")
        except UnicodeError as error:
            raise ConditionRunnerError("Developer Brief must be strict UTF-8") from error
        if text.startswith("\ufeff"):
            raise ConditionRunnerError("Developer Brief must not contain a UTF-8 BOM")
        if not self.sensitive_values or any(not value for value in self.sensitive_values):
            raise ConditionRunnerError("all injected secrets must be registered for leak detection")
        if not self.trial_proxy_token or self.trial_proxy_token not in self.sensitive_values:
            raise ConditionRunnerError("opaque Trial token must be registered for leak detection")


@dataclass(frozen=True)
class FinalRepositoryHandoff:
    """One post-stop repository boundary consumed by trusted capture and verification."""

    condition: str
    repository: Path


@dataclass(frozen=True)
class ConditionProcessResult:
    condition: str
    exit_code: int | None
    signal: int | None
    duration_ns: int
    timed_out: bool
    reason_code: str
    infrastructure_valid: bool
    capture_root: Path
    artifact_digests: Mapping[str, str]
    environment_names: tuple[str, ...]
    process_tree_terminated: bool
    final_repository: FinalRepositoryHandoff | None

    def __post_init__(self) -> None:
        if self.condition not in HARNESS_CONDITIONS:
            raise ValueError("invalid Harness condition result")
        if self.reason_code in {"task-succeeded", "task-failed"}:
            raise ValueError("Condition Runner cannot interpret task success")
        object.__setattr__(self, "artifact_digests", MappingProxyType(dict(self.artifact_digests)))


class ConditionRunner:
    """Common process boundary; adapters own only sealed launch materialization."""

    def run(self, request: ConditionRunRequest) -> ConditionProcessResult:
        started_ns = time.monotonic_ns()
        process = request.process
        trial_root = request.trial_root
        try:
            trial_root.mkdir(parents=True, exist_ok=False, mode=0o700)
        except OSError as error:
            raise ConditionRunnerError("Trial root must be fresh and uniquely owned") from error
        home = trial_root / "home"
        scratch = trial_root / "tmp"
        repository = trial_root / "repository"
        home.mkdir(mode=0o700)
        scratch.mkdir(mode=0o700)
        _copy_repository(request.repository_source, repository)

        secrets = tuple(value.encode("utf-8") for value in request.sensitive_values)
        unsafe_launch = _contains_secret(
            "\x00".join((str(process.artifact_path), *process.arguments)).encode(),
            secrets,
        )
        if unsafe_launch:
            return self._prelaunch_failure(
                request,
                started_ns,
                "secret-in-command-arguments",
                b"",
                b"",
            )
        forbidden_environment_secrets = tuple(
            value.encode("utf-8")
            for value in request.sensitive_values
            if value != request.trial_proxy_token
        )
        if any(
            name == PROVIDER_API_KEY_ENV
            or _contains_secret(value.encode("utf-8"), forbidden_environment_secrets)
            for name, value in process.environment.items()
        ):
            return self._prelaunch_failure(
                request,
                started_ns,
                "real-credential-in-trial-environment",
                b"",
                b"",
            )
        try:
            _verify_executable(process.artifact_path, process.artifact_identity)
        except ConditionRunnerError:
            return self._prelaunch_failure(
                request,
                started_ns,
                "artifact-verification-failed",
                b"",
                b"",
            )

        environment = {
            "HOME": str(home),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "TMPDIR": str(scratch),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_DATA_HOME": str(home / ".local/share"),
            "XDG_STATE_HOME": str(home / ".local/state"),
            **process.environment,
        }
        for path in (".cache", ".config", ".local/share", ".local/state"):
            (home / path).mkdir(parents=True, mode=0o700)

        child = subprocess.Popen(
            [str(process.artifact_path), *process.arguments],
            cwd=repository,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        timed_out = False
        termination_signals: list[str] = []
        try:
            stdout, stderr = child.communicate(
                input=request.developer_brief,
                timeout=WALL_TIME_SECONDS,
            )
        except subprocess.TimeoutExpired:
            timed_out = True
            termination_signals.append("SIGTERM")
            _signal_group(child.pid, signal.SIGTERM)
            try:
                stdout, stderr = child.communicate(timeout=_SHUTDOWN_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                termination_signals.append("SIGKILL")
                _signal_group(child.pid, signal.SIGKILL)
                stdout, stderr = child.communicate(timeout=_SHUTDOWN_GRACE_SECONDS)
        tree_terminated = _terminate_remaining_group(child.pid, termination_signals)
        try:
            _verify_executable(process.artifact_path, process.artifact_identity)
        except ConditionRunnerError:
            return self._write_result(
                request,
                stdout,
                stderr,
                started_ns=started_ns,
                exit_code=child.returncode,
                timed_out=timed_out,
                tree_terminated=tree_terminated,
                termination_signals=termination_signals,
                forced_reason="artifact-mutated-during-run",
                force_invalid=True,
            )
        return self._write_result(
            request,
            stdout,
            stderr,
            started_ns=started_ns,
            exit_code=child.returncode,
            timed_out=timed_out,
            tree_terminated=tree_terminated,
            termination_signals=termination_signals,
            forced_reason=None,
            force_invalid=not tree_terminated,
        )

    def _prelaunch_failure(
        self,
        request: ConditionRunRequest,
        started_ns: int,
        reason_code: str,
        stdout: bytes,
        stderr: bytes,
    ) -> ConditionProcessResult:
        return self._write_result(
            request,
            stdout,
            stderr,
            started_ns=started_ns,
            exit_code=None,
            timed_out=False,
            tree_terminated=True,
            termination_signals=[],
            forced_reason=reason_code,
            force_invalid=True,
        )

    def _write_result(
        self,
        request: ConditionRunRequest,
        stdout: bytes,
        stderr: bytes,
        *,
        started_ns: int,
        exit_code: int | None,
        timed_out: bool,
        tree_terminated: bool,
        termination_signals: list[str],
        forced_reason: str | None,
        force_invalid: bool,
    ) -> ConditionProcessResult:
        process = request.process
        secrets = tuple(value.encode("utf-8") for value in request.sensitive_values)
        artifact_data: dict[str, bytes] = {}
        missing_artifact = False
        for relative in process.native_artifact_paths:
            try:
                artifact_data[relative] = _read_native_artifact(request.trial_root, relative)
            except (OSError, ConditionRunnerError):
                missing_artifact = True
        leaked = any(
            _contains_secret(data, secrets)
            for data in (stdout, stderr, *artifact_data.values())
        )
        invalid = force_invalid or missing_artifact or leaked
        if leaked:
            reason_code = "secret-leak-detected"
        elif forced_reason is not None:
            reason_code = forced_reason
        elif missing_artifact:
            reason_code = "missing-native-artifact"
        elif not tree_terminated:
            reason_code = "process-tree-not-terminated"
        elif timed_out:
            reason_code = "wall-time-limit"
        else:
            reason_code = "process-exited"
        capture_root = request.trial_root / ("quarantine" if leaked else "capture")
        capture_root.mkdir(mode=0o700)
        captured_stdout = _redact(stdout, secrets) if leaked else stdout
        captured_stderr = _redact(stderr, secrets) if leaked else stderr
        _atomic_write(capture_root / "stdout.bin", captured_stdout)
        _atomic_write(capture_root / "stderr.bin", captured_stderr)
        artifact_digests: dict[str, str] = {}
        for relative, data in artifact_data.items():
            captured = _redact(data, secrets) if leaked else data
            destination = capture_root / "native" / relative
            _atomic_write(destination, captured)
            artifact_digests[relative] = f"sha256:{hashlib.sha256(captured).hexdigest()}"
        signal_number = -exit_code if exit_code is not None and exit_code < 0 else None
        manifest = {
            "artifact_digests": artifact_digests,
            "condition": process.condition,
            "duration_ns": time.monotonic_ns() - started_ns,
            "environment_names": sorted(process.environment),
            "exit_code": exit_code if exit_code is None or exit_code >= 0 else None,
            "infrastructure_valid": not invalid,
            "process_tree_terminated": tree_terminated,
            "reason_code": reason_code,
            "schema_version": 1,
            "signal": signal_number,
            "termination_signals": termination_signals,
            "timed_out": timed_out,
        }
        manifest_bytes = canonical_json_bytes(manifest)
        if _contains_secret(manifest_bytes, secrets):
            raise RuntimeError("Condition capture manifest contains a credential")
        _atomic_write(capture_root / "process.json", manifest_bytes)
        return ConditionProcessResult(
            condition=process.condition,
            exit_code=manifest["exit_code"],
            signal=signal_number,
            duration_ns=manifest["duration_ns"],
            timed_out=timed_out,
            reason_code=reason_code,
            infrastructure_valid=not invalid,
            capture_root=capture_root,
            artifact_digests=artifact_digests,
            environment_names=tuple(sorted(process.environment)),
            process_tree_terminated=tree_terminated,
            final_repository=(
                FinalRepositoryHandoff(
                    condition=process.condition,
                    repository=request.trial_root / "repository",
                )
                if not invalid
                else None
            ),
        )


def _copy_repository(source: Path, destination: Path) -> None:
    if not source.is_dir() or source.is_symlink():
        raise ConditionRunnerError("repository source must be a real directory")
    for path in source.rglob("*"):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not (
            stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)
        ):
            raise ConditionRunnerError("repository source contains an unsafe entry")
    shutil.copytree(source, destination, copy_function=shutil.copy2)


def _verify_executable(path: Path, identity_text: str) -> None:
    try:
        metadata = path.lstat()
        identity = TypedDigest.parse(identity_text)
        data = path.read_bytes()
    except (OSError, IdentityError) as error:
        raise ConditionRunnerError("Harness artifact is unreadable") from error
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_mode & stat.S_IXUSR == 0
        or TypedDigest.from_bytes(DigestKind.ARTIFACT, data) != identity
    ):
        raise ConditionRunnerError("Harness artifact identity mismatch")


def _safe_relative_path(value: str, *, label: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or "." in path.parts
        or "" in path.parts
        or path.as_posix() != value
        or "\\" in value
        or ":" in value
        or "\x00" in value
    ):
        raise ConditionRunnerError(f"{label} must be a normalized relative path")
    return path


def _read_native_artifact(root: Path, relative: str) -> bytes:
    path = root.joinpath(*_safe_relative_path(relative, label="native artifact").parts)
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ConditionRunnerError("native artifact must be a regular file")
    return path.read_bytes()


def _contains_secret(data: bytes, secrets: tuple[bytes, ...]) -> bool:
    return any(secret in data for secret in secrets)


def _redact(data: bytes, secrets: tuple[bytes, ...]) -> bytes:
    redacted = data
    for secret in sorted(secrets, key=len, reverse=True):
        redacted = redacted.replace(secret, _REDACTION)
    return redacted


def _signal_group(process_group: int, selected_signal: signal.Signals) -> None:
    try:
        os.killpg(process_group, selected_signal)
    except ProcessLookupError:
        return


def _terminate_remaining_group(process_group: int, signals: list[str]) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return True
    signals.append("SIGTERM")
    _signal_group(process_group, signal.SIGTERM)
    deadline = time.monotonic() + _SHUTDOWN_GRACE_SECONDS
    while time.monotonic() < deadline:
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.01)
    signals.append("SIGKILL")
    _signal_group(process_group, signal.SIGKILL)
    deadline = time.monotonic() + _SHUTDOWN_GRACE_SECONDS
    while time.monotonic() < deadline:
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.01)
    return False


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise

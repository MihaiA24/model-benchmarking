from __future__ import annotations

import fcntl
import hashlib
import os
import re
import secrets
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Self

from model_benchmark.declarations.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    load_canonical_json,
)
from model_benchmark.declarations.functional_v1 import (
    CONDITIONS,
    SCENARIOS,
    FunctionalV1Manifest,
)
from model_benchmark.declarations.identities import (
    DigestKind,
    IdentityError,
    TypedDigest,
)


CELL_DISPOSITIONS = (
    "not_started",
    "valid_completed",
    "valid_harness_outcome",
    "valid_limit_outcome",
    "invalid_infrastructure",
    "invalid_integrity",
    "aborted_operator",
)
VALID_COMMAND_DISPOSITIONS = {
    "valid_completed",
    "valid_harness_outcome",
    "valid_limit_outcome",
}
CELL_SCHEDULE = tuple(
    {
        "cell_id": f"{index:02d}-{scenario}-{condition}",
        "condition": condition,
        "index": index,
        "scenario": scenario,
    }
    for index, (scenario, condition) in enumerate(
        ((scenario, condition) for scenario in SCENARIOS for condition in CONDITIONS),
        start=1,
    )
)
_CELL_IDS = frozenset(cell["cell_id"] for cell in CELL_SCHEDULE)
_REASON_CODE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$")


class FunctionalV1HomeError(RuntimeError):
    """Managed-home state is unavailable, conflicting, or corrupt."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code

    def summary(self, command: str) -> dict[str, object]:
        return {
            "command": command,
            "message": str(self),
            "outcome": "rejected",
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True)
class CommandResult:
    """One deterministic human and canonical-JSON command outcome."""

    exit_code: int
    human: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if self.exit_code not in {0, 1, 2, 3}:
            raise ValueError("Functional V1 command exit code must be 0, 1, 2, or 3")
        if not self.human:
            raise ValueError("Functional V1 human output must not be empty")
        canonical_json_bytes(dict(self.payload))


class FunctionalV1Runtime(Protocol):
    """Narrow callable seam for provision, coordinator, and evidence modules."""

    def provision(self, manifest: FunctionalV1Manifest) -> CommandResult: ...

    def preflight(self, manifest: FunctionalV1Manifest) -> CommandResult: ...

    def run(self, manifest: FunctionalV1Manifest) -> CommandResult: ...

    def resume(self, run_id: str) -> CommandResult: ...

    def inspect(self, run_id: str) -> CommandResult: ...


RuntimeFactory = Callable[["FunctionalV1Home"], FunctionalV1Runtime]


@dataclass(frozen=True)
class SealedRunRecord:
    identity: TypedDigest
    value: Mapping[str, object]


@dataclass
class _Lease:
    descriptors: list[int]

    def release(self) -> None:
        while self.descriptors:
            descriptor = self.descriptors.pop()
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.release()


def _immutable_write(path: Path, data: bytes, *, allow_identical: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if (
            allow_identical
            and not path.is_symlink()
            and path.is_file()
            and path.read_bytes() == data
        ):
            return
        raise FunctionalV1HomeError(
            "immutable-write-conflict",
            f"write-once path already exists: {path.name}",
        )
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp")
    published = False
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            view = memoryview(data)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.link(temporary, path)
        published = True
        os.chmod(path, 0o400)
        if path.read_bytes() != data:
            raise OSError("immutable write read-back mismatch")
    except FileExistsError as error:
        if allow_identical and path.is_file() and path.read_bytes() == data:
            return
        raise FunctionalV1HomeError(
            "immutable-write-conflict",
            f"write-once path already exists: {path.name}",
        ) from error
    except OSError as error:
        if published:
            path.unlink(missing_ok=True)
        raise FunctionalV1HomeError(
            "immutable-write-failed",
            f"cannot publish {path.name}: {error}",
        ) from error
    finally:
        temporary.unlink(missing_ok=True)


def _load_canonical_object(path: Path) -> dict[str, object]:
    try:
        data = path.read_bytes()
        value = load_canonical_json(data)
    except (OSError, CanonicalizationError) as error:
        raise FunctionalV1HomeError(
            "corrupt-managed-home",
            f"cannot validate {path.name}: {error}",
        ) from error
    if not isinstance(value, dict):
        raise FunctionalV1HomeError(
            "corrupt-managed-home",
            f"{path.name} is not a canonical JSON object",
        )
    return value


def _uuid7() -> uuid.UUID:
    timestamp_ms = time.time_ns() // 1_000_000
    random_bits = secrets.randbits(74)
    value = (timestamp_ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76
    value |= ((random_bits >> 62) & 0xFFF) << 64
    value |= 0b10 << 62
    value |= random_bits & ((1 << 62) - 1)
    return uuid.UUID(int=value)


def _validate_run_id(run_id: str) -> str:
    try:
        parsed = uuid.UUID(run_id)
    except (ValueError, AttributeError) as error:
        raise FunctionalV1HomeError(
            "invalid-run-id", "Run ID must be a UUIDv7"
        ) from error
    if parsed.version != 7 or str(parsed) != run_id:
        raise FunctionalV1HomeError(
            "invalid-run-id", "Run ID must be a canonical UUIDv7"
        )
    return run_id


def _validate_timestamp(value: str, *, field: str) -> None:
    if _UTC_TIMESTAMP.fullmatch(value) is None:
        raise FunctionalV1HomeError(
            "invalid-cell-record",
            f"{field} must be an RFC 3339 UTC timestamp",
        )


class FunctionalV1Home:
    """Managed content-addressed inputs and write-once run state."""

    def __init__(self, root: Path) -> None:
        if root.exists() and root.is_symlink():
            raise FunctionalV1HomeError(
                "invalid-home",
                "Functional V1 Home cannot be a symlink",
            )
        self.root = root.resolve(strict=False)

    def _lock(self, path: Path, operation: int, *, reason_code: str) -> int:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(descriptor, operation | fcntl.LOCK_NB)
        except BlockingIOError as error:
            os.close(descriptor)
            raise FunctionalV1HomeError(
                reason_code, f"managed-home lease is busy: {path.name}"
            ) from error
        return descriptor

    def provisioning_lease(self) -> _Lease:
        descriptor = self._lock(
            self.root / "leases/cache.lock",
            fcntl.LOCK_EX,
            reason_code="provisioning-lease-busy",
        )
        return _Lease([descriptor])

    def coordinator_lease(self) -> _Lease:
        cache_descriptor = self._lock(
            self.root / "leases/cache.lock",
            fcntl.LOCK_SH,
            reason_code="provisioning-lease-busy",
        )
        try:
            coordinator_descriptor = self._lock(
                self.root / "leases/coordinator.lock",
                fcntl.LOCK_EX,
                reason_code="coordinator-lease-busy",
            )
        except BaseException:
            fcntl.flock(cache_descriptor, fcntl.LOCK_UN)
            os.close(cache_descriptor)
            raise
        return _Lease([cache_descriptor, coordinator_descriptor])

    def store_manifest_inputs(self, manifest: FunctionalV1Manifest) -> None:
        entries: list[tuple[TypedDigest, bytes]] = [
            (manifest.identity, canonical_json_bytes(manifest.identity_value)),
            (manifest.resolved_identity, canonical_json_bytes(manifest.resolved_value)),
        ]
        for name in SCENARIOS:
            data = manifest.scenario_lock_bytes[name]
            entries.append(
                (TypedDigest.from_bytes(DigestKind.PACKAGE_LOCK, data), data)
            )
        for name in CONDITIONS:
            data = manifest.condition_lock_bytes[name]
            entries.append(
                (TypedDigest.from_bytes(DigestKind.FUNCTIONAL_V1_CONDITION, data), data)
            )
        for identity, data in entries:
            _immutable_write(
                self.root / "inputs" / identity.kind.value / f"{identity.value}.json",
                data,
                allow_identical=True,
            )

    def verify_manifest_inputs(self, manifest: FunctionalV1Manifest) -> None:
        expected: list[tuple[TypedDigest, bytes]] = [
            (manifest.identity, canonical_json_bytes(manifest.identity_value)),
            (manifest.resolved_identity, canonical_json_bytes(manifest.resolved_value)),
        ]
        expected.extend(
            (
                TypedDigest.from_bytes(
                    DigestKind.PACKAGE_LOCK,
                    manifest.scenario_lock_bytes[name],
                ),
                manifest.scenario_lock_bytes[name],
            )
            for name in SCENARIOS
        )
        expected.extend(
            (
                TypedDigest.from_bytes(
                    DigestKind.FUNCTIONAL_V1_CONDITION,
                    manifest.condition_lock_bytes[name],
                ),
                manifest.condition_lock_bytes[name],
            )
            for name in CONDITIONS
        )
        for identity, data in expected:
            path = self.root / "inputs" / identity.kind.value / f"{identity.value}.json"
            try:
                captured = path.read_bytes()
            except OSError as error:
                raise FunctionalV1HomeError(
                    "unprovisioned-input",
                    f"missing provisioned input: {identity}",
                ) from error
            if captured != data:
                raise FunctionalV1HomeError(
                    "provisioned-input-mismatch",
                    f"provisioned input changed: {identity}",
                )

    def create_workspace(self, manifest: FunctionalV1Manifest) -> "RunWorkspace":
        run_id = str(_uuid7())
        root = self.root / "runs" / run_id
        try:
            root.mkdir(parents=True, exist_ok=False)
        except OSError as error:
            raise FunctionalV1HomeError(
                "workspace-creation-failed",
                f"cannot create Run Workspace: {error}",
            ) from error
        header = {
            "manifest_identity": str(manifest.identity),
            "resolved_manifest_identity": str(manifest.resolved_identity),
            "run_id": run_id,
            "schedule": list(CELL_SCHEDULE),
            "schema_version": 1,
            "source_yaml_sha256": manifest.source_yaml_sha256,
        }
        try:
            _immutable_write(
                root / "input/source.yaml",
                manifest.source_bytes,
                allow_identical=False,
            )
            _immutable_write(
                root / "input/manifest.json",
                canonical_json_bytes(manifest.identity_value),
                allow_identical=False,
            )
            _immutable_write(
                root / "input/resolved-manifest.json",
                canonical_json_bytes(manifest.resolved_value),
                allow_identical=False,
            )
            _immutable_write(
                root / "header.json",
                canonical_json_bytes(header),
                allow_identical=False,
            )
        except BaseException:
            for path in sorted(root.rglob("*"), reverse=True):
                if path.is_file():
                    path.chmod(0o600)
                    path.unlink(missing_ok=True)
                elif path.is_dir():
                    path.rmdir()
            root.rmdir()
            raise
        return RunWorkspace.open(self, run_id)

    def workspace(self, run_id: str) -> "RunWorkspace":
        return RunWorkspace.open(self, run_id)

    def sealed_run(self, run_id: str) -> SealedRunRecord:
        return self.workspace(run_id).sealed_record()


@dataclass(frozen=True)
class RunWorkspace:
    home: FunctionalV1Home
    run_id: str
    root: Path
    header: Mapping[str, object]

    @classmethod
    def open(cls, home: FunctionalV1Home, run_id: str) -> "RunWorkspace":
        _validate_run_id(run_id)
        root = home.root / "runs" / run_id
        header = _load_canonical_object(root / "header.json")
        if (
            header.get("schema_version") != 1
            or header.get("run_id") != run_id
            or header.get("schedule") != list(CELL_SCHEDULE)
        ):
            raise FunctionalV1HomeError(
                "corrupt-run-workspace",
                "Run Workspace header does not match its Run ID and fixed schedule",
            )
        try:
            manifest_identity = TypedDigest.parse(str(header["manifest_identity"]))
            resolved_identity = TypedDigest.parse(
                str(header["resolved_manifest_identity"])
            )
        except (KeyError, IdentityError) as error:
            raise FunctionalV1HomeError(
                "corrupt-run-workspace",
                "Run Workspace header identities are invalid",
            ) from error
        if (
            manifest_identity.kind is not DigestKind.FUNCTIONAL_V1_MANIFEST
            or resolved_identity.kind is not DigestKind.RESOLVED_V1_MANIFEST
        ):
            raise FunctionalV1HomeError(
                "corrupt-run-workspace",
                "Run Workspace header identity kinds are invalid",
            )
        try:
            source_bytes = (root / "input/source.yaml").read_bytes()
            manifest_bytes = (root / "input/manifest.json").read_bytes()
            resolved_bytes = (root / "input/resolved-manifest.json").read_bytes()
        except OSError as error:
            raise FunctionalV1HomeError(
                "corrupt-run-workspace",
                f"Run Workspace input is unreadable: {error}",
            ) from error
        if (
            TypedDigest.from_bytes(
                DigestKind.FUNCTIONAL_V1_MANIFEST,
                manifest_bytes,
            )
            != manifest_identity
            or TypedDigest.from_bytes(
                DigestKind.RESOLVED_V1_MANIFEST,
                resolved_bytes,
            )
            != resolved_identity
            or header.get("source_yaml_sha256")
            != f"sha256:{hashlib.sha256(source_bytes).hexdigest()}"
        ):
            raise FunctionalV1HomeError(
                "corrupt-run-workspace",
                "Run Workspace input identity mismatch",
            )
        return cls(home=home, run_id=run_id, root=root, header=header)

    def _cell_path(self, cell_id: str, filename: str) -> Path:
        if cell_id not in _CELL_IDS:
            raise FunctionalV1HomeError(
                "invalid-cell-id",
                f"cell is not in the fixed schedule: {cell_id}",
            )
        return self.root / "cells" / cell_id / filename

    def write_cell_start(
        self,
        cell_id: str,
        *,
        started_at_utc: str,
        details: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        _validate_timestamp(started_at_utc, field="started_at_utc")
        payload = {
            "cell_id": cell_id,
            "details": dict(details or {}),
            "manifest_identity": self.header["manifest_identity"],
            "run_id": self.run_id,
            "schema_version": 1,
            "started_at_utc": started_at_utc,
        }
        _immutable_write(
            self._cell_path(cell_id, "start.json"),
            canonical_json_bytes(payload),
            allow_identical=False,
        )
        return payload

    def write_cell_execution(
        self,
        cell_id: str,
        *,
        disposition: str,
        terminal_phase: str,
        reason_code: str,
        ended_at_utc: str,
        duration_ns: int,
        evidence_valid: bool,
        details: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        start_path = self._cell_path(cell_id, "start.json")
        if not start_path.is_file() or start_path.is_symlink():
            raise FunctionalV1HomeError(
                "cell-not-started",
                f"cell has no durable start record: {cell_id}",
            )
        if disposition not in CELL_DISPOSITIONS:
            raise FunctionalV1HomeError(
                "invalid-cell-record",
                f"invalid execution disposition: {disposition}",
            )
        if not isinstance(terminal_phase, str) or not terminal_phase:
            raise FunctionalV1HomeError(
                "invalid-cell-record", "terminal_phase must be non-empty"
            )
        if _REASON_CODE.fullmatch(reason_code) is None:
            raise FunctionalV1HomeError(
                "invalid-cell-record",
                "reason_code must use lowercase kebab-case",
            )
        _validate_timestamp(ended_at_utc, field="ended_at_utc")
        if (
            not isinstance(duration_ns, int)
            or isinstance(duration_ns, bool)
            or duration_ns < 0
        ):
            raise FunctionalV1HomeError(
                "invalid-cell-record",
                "duration_ns must be a non-negative integer",
            )
        if not isinstance(evidence_valid, bool):
            raise FunctionalV1HomeError(
                "invalid-cell-record", "evidence_valid must be boolean"
            )
        payload = {
            "cell_id": cell_id,
            "details": dict(details or {}),
            "disposition": disposition,
            "duration_ns": duration_ns,
            "ended_at_utc": ended_at_utc,
            "evidence_valid": evidence_valid,
            "manifest_identity": self.header["manifest_identity"],
            "reason_code": reason_code,
            "run_id": self.run_id,
            "schema_version": 1,
            "terminal_phase": terminal_phase,
        }
        _immutable_write(
            self._cell_path(cell_id, "execution.json"),
            canonical_json_bytes(payload),
            allow_identical=False,
        )
        return payload

    def write_cell_terminal(
        self,
        cell_id: str,
        *,
        disposition: str,
        terminal_phase: str,
        reason_code: str,
        ended_at_utc: str,
        duration_ns: int,
        evidence_valid: bool,
        result_bundle_identity: str | None,
        details: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        start_path = self._cell_path(cell_id, "start.json")
        if not start_path.is_file() or start_path.is_symlink():
            raise FunctionalV1HomeError(
                "cell-not-started",
                f"cell has no durable start record: {cell_id}",
            )
        if disposition not in CELL_DISPOSITIONS:
            raise FunctionalV1HomeError(
                "invalid-cell-record",
                f"invalid terminal disposition: {disposition}",
            )
        if not isinstance(terminal_phase, str) or not terminal_phase:
            raise FunctionalV1HomeError(
                "invalid-cell-record",
                "terminal_phase must be non-empty",
            )
        if _REASON_CODE.fullmatch(reason_code) is None:
            raise FunctionalV1HomeError(
                "invalid-cell-record",
                "reason_code must use lowercase kebab-case",
            )
        _validate_timestamp(ended_at_utc, field="ended_at_utc")
        if (
            not isinstance(duration_ns, int)
            or isinstance(duration_ns, bool)
            or duration_ns < 0
        ):
            raise FunctionalV1HomeError(
                "invalid-cell-record",
                "duration_ns must be a non-negative integer",
            )
        if not isinstance(evidence_valid, bool):
            raise FunctionalV1HomeError(
                "invalid-cell-record",
                "evidence_valid must be boolean",
            )
        if result_bundle_identity is not None:
            try:
                bundle = TypedDigest.parse(result_bundle_identity)
            except IdentityError as error:
                raise FunctionalV1HomeError(
                    "invalid-cell-record", str(error)
                ) from error
            if bundle.kind is not DigestKind.RESULT_BUNDLE:
                raise FunctionalV1HomeError(
                    "invalid-cell-record",
                    "terminal bundle must use result-bundle identity",
                )
        payload = {
            "cell_id": cell_id,
            "details": dict(details or {}),
            "disposition": disposition,
            "duration_ns": duration_ns,
            "ended_at_utc": ended_at_utc,
            "evidence_valid": evidence_valid,
            "manifest_identity": self.header["manifest_identity"],
            "reason_code": reason_code,
            "result_bundle_identity": result_bundle_identity,
            "run_id": self.run_id,
            "schema_version": 1,
            "terminal_phase": terminal_phase,
        }
        _immutable_write(
            self._cell_path(cell_id, "terminal.json"),
            canonical_json_bytes(payload),
            allow_identical=False,
        )
        return payload

    def seal(self) -> SealedRunRecord:
        terminal_cells: list[dict[str, object]] = []
        unscheduled_cells: list[str] = []
        for cell in CELL_SCHEDULE:
            cell_id = cell["cell_id"]
            start_path = self._cell_path(cell_id, "start.json")
            terminal_path = self._cell_path(cell_id, "terminal.json")
            if not start_path.exists():
                if terminal_path.exists():
                    raise FunctionalV1HomeError(
                        "orphan-terminal-record",
                        f"terminal record exists without start: {cell_id}",
                    )
                unscheduled_cells.append(cell_id)
                continue
            if not terminal_path.exists():
                raise FunctionalV1HomeError(
                    "unterminated-start-record",
                    f"started cell has no terminal record: {cell_id}",
                )
            start = _load_canonical_object(start_path)
            terminal = _load_canonical_object(terminal_path)
            if (
                start.get("run_id") != self.run_id
                or start.get("cell_id") != cell_id
                or terminal.get("run_id") != self.run_id
                or terminal.get("cell_id") != cell_id
            ):
                raise FunctionalV1HomeError(
                    "mixed-run-cell-record",
                    f"cell record identity mismatch: {cell_id}",
                )
            details = terminal.get("details")
            if not isinstance(details, dict):
                details = {}
            score_vector = details.get("score_vector")
            scores: dict[str, object] = {
                "acceptance_score": None,
                "regression_score": None,
                "task_success": None,
            }
            if isinstance(score_vector, dict):
                scores = {key: score_vector.get(key) for key in scores}
            limitations = details.get("limitations")
            if not isinstance(limitations, list) or not all(
                isinstance(item, str) for item in limitations
            ):
                limitations = []
            terminal_cells.append(
                {
                    "cell_id": cell_id,
                    "condition": cell["condition"],
                    "cost_usd": details.get("cost_usd"),
                    "disposition": terminal.get("disposition"),
                    "duration_ns": terminal.get("duration_ns"),
                    "ended_at_utc": terminal.get("ended_at_utc"),
                    "evidence_valid": terminal.get("evidence_valid"),
                    "limitations": list(limitations),
                    "provider_requests": details.get("provider_requests"),
                    "provider_tokens": details.get("provider_tokens"),
                    "reason_code": terminal.get("reason_code"),
                    "result_bundle_identity": terminal.get("result_bundle_identity"),
                    "scenario": cell["scenario"],
                    "score_vector": (
                        dict(score_vector) if isinstance(score_vector, dict) else None
                    ),
                    "scores": scores,
                    "start_sha256": f"sha256:{hashlib.sha256(start_path.read_bytes()).hexdigest()}",
                    "started_at_utc": start.get("started_at_utc"),
                    "terminal_phase": terminal.get("terminal_phase"),
                    "terminal_sha256": f"sha256:{hashlib.sha256(terminal_path.read_bytes()).hexdigest()}",
                }
            )
        complete = len(terminal_cells) == len(CELL_SCHEDULE) and all(
            cell["disposition"] in VALID_COMMAND_DISPOSITIONS
            and cell["evidence_valid"] is True
            and cell["result_bundle_identity"] is not None
            for cell in terminal_cells
        )
        valid = complete and all(
            cell["disposition"] in VALID_COMMAND_DISPOSITIONS for cell in terminal_cells
        )
        header_bytes = (self.root / "header.json").read_bytes()
        provenance_path = self.root / "provenance.json"
        provenance = (
            _load_canonical_object(provenance_path)
            if provenance_path.exists()
            else None
        )
        record = {
            "cells": terminal_cells,
            "header_sha256": f"sha256:{hashlib.sha256(header_bytes).hexdigest()}",
            "manifest_identity": self.header["manifest_identity"],
            "provenance": provenance,
            "resolved_manifest_identity": self.header["resolved_manifest_identity"],
            "run_id": self.run_id,
            "schema_version": 1,
            "source_yaml_sha256": self.header["source_yaml_sha256"],
            "state": "complete" if complete else "incomplete",
            "unscheduled_cells": unscheduled_cells,
            "validity": "valid" if valid else "invalid",
        }
        data = canonical_json_bytes(record)
        identity = TypedDigest.from_bytes(DigestKind.FUNCTIONAL_V1_RUN_RECORD, data)
        _immutable_write(
            self.root / "run-record.json",
            data,
            allow_identical=False,
        )
        _immutable_write(
            self.root / "run-record.identity",
            (str(identity) + "\n").encode("ascii"),
            allow_identical=False,
        )
        return SealedRunRecord(identity=identity, value=record)

    def sealed_record(self) -> SealedRunRecord:
        record_path = self.root / "run-record.json"
        identity_path = self.root / "run-record.identity"
        try:
            data = record_path.read_bytes()
            identity_text = identity_path.read_text(encoding="ascii").removesuffix("\n")
            identity = TypedDigest.parse(identity_text)
            value = load_canonical_json(data)
        except (OSError, UnicodeError, IdentityError, CanonicalizationError) as error:
            raise FunctionalV1HomeError(
                "unsealed-or-corrupt-run",
                f"Run Record is unavailable or corrupt: {error}",
            ) from error
        if (
            identity.kind is not DigestKind.FUNCTIONAL_V1_RUN_RECORD
            or identity
            != TypedDigest.from_bytes(DigestKind.FUNCTIONAL_V1_RUN_RECORD, data)
            or not isinstance(value, dict)
            or value.get("run_id") != self.run_id
        ):
            raise FunctionalV1HomeError(
                "unsealed-or-corrupt-run",
                "Run Record identity does not match canonical bytes",
            )
        return SealedRunRecord(identity=identity, value=value)


class OperatorContractRuntime:
    """Functional V1 native provisioning, preflight, and execution coordinator."""

    def __init__(self, home: FunctionalV1Home) -> None:
        from model_benchmark.runtime.execution import NativeFunctionalV1Runtime

        self._native = NativeFunctionalV1Runtime(home)

    def provision(self, manifest: FunctionalV1Manifest) -> CommandResult:
        return self._native.provision(manifest)

    def preflight(self, manifest: FunctionalV1Manifest) -> CommandResult:
        return self._native.preflight(manifest)

    def run(self, manifest: FunctionalV1Manifest) -> CommandResult:
        return self._native.run(manifest)

    def resume(self, run_id: str) -> CommandResult:
        return self._native.resume(run_id)

    def inspect(self, run_id: str) -> CommandResult:
        return self._native.inspect(run_id)


def _score_text(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return "-"


def _count_text(value: object) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return "-"


def _human_table(record: Mapping[str, object]) -> str:
    columns = (
        "SCENARIO | CONDITION | DISPOSITION | TASK | ACCEPT | REGRESS | "
        "DURATION | REQUESTS | TOKENS | COST_USD | BUNDLE"
    )
    raw_cells = record.get("cells")
    if not isinstance(raw_cells, list):
        return columns
    schedule = {cell["cell_id"]: cell for cell in CELL_SCHEDULE}
    rows = [columns]
    for raw_cell in raw_cells:
        if not isinstance(raw_cell, dict):
            continue
        planned = schedule.get(raw_cell.get("cell_id"))
        scenario = raw_cell.get("scenario") or (
            planned["scenario"] if planned is not None else None
        )
        condition = raw_cell.get("condition") or (
            planned["condition"] if planned is not None else None
        )
        if scenario is None or condition is None:
            continue
        scores = raw_cell.get("scores")
        if not isinstance(scores, dict):
            scores = {}
        duration_ns = raw_cell.get("duration_ns")
        duration = (
            f"{duration_ns // 1_000_000_000}s"
            if isinstance(duration_ns, int) and not isinstance(duration_ns, bool)
            else "-"
        )
        cost_usd = raw_cell.get("cost_usd")
        rows.append(
            f"{scenario} | {condition} | "
            f"{raw_cell.get('disposition') or '-'} | "
            f"{_score_text(scores.get('task_success'))} | "
            f"{_score_text(scores.get('acceptance_score'))} | "
            f"{_score_text(scores.get('regression_score'))} | "
            f"{duration} | "
            f"{_count_text(raw_cell.get('provider_requests'))} | "
            f"{_count_text(raw_cell.get('provider_tokens'))} | "
            f"{cost_usd if isinstance(cost_usd, str) and cost_usd else '-'} | "
            f"{raw_cell.get('result_bundle_identity') or '-'}"
        )
    return "\n".join(rows)


def _inspect_result(record: SealedRunRecord) -> CommandResult:
    value = record.value
    success = value.get("state") == "complete" and value.get("validity") == "valid"
    payload = {
        "command": "inspect",
        "outcome": "complete" if success else "incomplete",
        "record": dict(value),
        "run_record_identity": str(record.identity),
    }
    return CommandResult(
        exit_code=0 if success else 1,
        human=_human_table(value),
        payload=payload,
    )


def default_runtime(home: FunctionalV1Home) -> FunctionalV1Runtime:
    return OperatorContractRuntime(home)

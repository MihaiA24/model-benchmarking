from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from model_benchmark.declarations.canonical import canonical_json_bytes
from model_benchmark.declarations.identities import DigestKind, TypedDigest


TRUSTED_CAPTURE_TOOL: Path = (
    Path(__file__).resolve().parents[1] / "evidence" / "capture.py"
)

_MIB = 1024 * 1024
_CAPTURE_SCHEMA_VERSION = "scenario-capture-v1"
_CAPTURE_TOOL_TIMEOUT_SECONDS = 60
_STABILITY_WINDOW_MS = "25"
_REDACTION = b"[REDACTED]"
_SANITIZED_RECORD_KEYS = (
    "artifact_sha256",
    "hidden_markers",
    "media_type",
    "mode",
    "schema_sha256",
    "status",
    "total_bytes",
)


class _CollectionFailed(Exception):
    """One artifact could not be collected safely."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _SealFailed(Exception):
    """The staged bundle could not be sealed atomically."""


@dataclass(frozen=True)
class _ArtifactSpec:
    path: str
    role: str
    media_type: str
    max_bytes: int
    source: str


_EXECUTION_RECORD_SPEC = _ArtifactSpec(
    path="coordinator/execution.json",
    role="coordinator-execution-record",
    media_type="application/json",
    max_bytes=4 * _MIB,
    source="coordinator",
)

_TRIAL_SPECS: tuple[tuple[_ArtifactSpec, str], ...] = (
    (
        _ArtifactSpec(
            path="harbor/result.json",
            role="harbor-trial-result",
            media_type="application/json",
            max_bytes=4 * _MIB,
            source="harbor",
        ),
        "result.json",
    ),
    (
        _ArtifactSpec(
            path="harbor/trial.log",
            role="harbor-trial-log",
            media_type="text/plain",
            max_bytes=32 * _MIB,
            source="harbor",
        ),
        "trial.log",
    ),
    (
        _ArtifactSpec(
            path="harbor/collect-manifest.json",
            role="harbor-collect-manifest",
            media_type="application/json",
            max_bytes=1 * _MIB,
            source="harbor",
        ),
        "artifacts/manifest.json",
    ),
    (
        _ArtifactSpec(
            path="capture/capture.json",
            role="trusted-capture-record",
            media_type="application/json",
            max_bytes=1 * _MIB,
            source="capture",
        ),
        "artifacts/capture/capture.json",
    ),
    (
        _ArtifactSpec(
            path="capture/submission.patch",
            role="submission-patch",
            media_type="text/x-diff",
            max_bytes=8 * _MIB,
            source="capture",
        ),
        "artifacts/capture/submission.patch",
    ),
    (
        _ArtifactSpec(
            path="verifier/verifier-result.json",
            role="verifier-structured-result",
            media_type="application/json",
            max_bytes=4 * _MIB,
            source="verifier",
        ),
        "verifier/verifier-result.json",
    ),
    (
        _ArtifactSpec(
            path="verifier/reward.json",
            role="verifier-reward",
            media_type="application/json",
            max_bytes=1 * _MIB,
            source="verifier",
        ),
        "verifier/reward.json",
    ),
)

_RAW_SPECS: tuple[tuple[_ArtifactSpec, str], ...] = (
    (
        _ArtifactSpec(
            path="proxy/proxy.jsonl",
            role="credential-proxy-events",
            media_type="application/x-ndjson",
            max_bytes=32 * _MIB,
            source="credential-proxy",
        ),
        "proxy-evidence/proxy.jsonl",
    ),
    (
        _ArtifactSpec(
            path="coordinator/overlay.yaml",
            role="coordinator-overlay",
            media_type="application/yaml",
            max_bytes=1 * _MIB,
            source="coordinator",
        ),
        "overlay.yaml",
    ),
)


@dataclass(frozen=True)
class CellSealOutcome:
    disposition: str
    terminal_phase: str
    reason_code: str
    evidence_valid: bool
    result_bundle_identity: str | None
    details: Mapping[str, object]


def _atomic_write(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)
    if path.read_bytes() != data:
        raise _SealFailed(f"read-back mismatch for {path.name}")


def _entry(
    spec: _ArtifactSpec,
    status: str,
    *,
    size: int | None = None,
    digest: str | None = None,
    reason: str | None = None,
    capture_record: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "bytes": size,
        "capture_record": capture_record,
        "media_type": spec.media_type,
        "path": spec.path,
        "reason": reason,
        "role": spec.role,
        "sensitivity": "public" if spec.role == "submission-patch" else "diagnostic",
        "sha256": f"sha256:{digest}" if digest is not None else None,
        "source": spec.source,
        "status": status,
    }


def _deterministic_canary(cell_id: str, role: str) -> str:
    token = hashlib.sha256(f"{cell_id}/{role}".encode("utf-8")).hexdigest()
    return f"model-benchmark-canary-{token}"


def _capture_json_artifact(
    spec: _ArtifactSpec,
    source: Path,
    destination: Path,
    *,
    cell_id: str,
    capture_tool: Path,
    records_dir: Path,
) -> dict[str, object]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    record_path = records_dir / f"{spec.path.replace('/', '__')}.record.json"
    argv = [
        sys.executable,
        str(capture_tool),
        "--artifact-source",
        str(source),
        "--artifact-output",
        str(destination),
        "--artifact-record",
        str(record_path),
        "--artifact-media-type",
        spec.media_type,
        "--artifact-schema-sha256",
        hashlib.sha256(spec.role.encode("utf-8")).hexdigest(),
        "--artifact-max-bytes",
        str(spec.max_bytes),
        "--visibility-root",
        str(source.parent),
        "--forbidden-marker",
        _deterministic_canary(cell_id, spec.role),
        "--stability-window-ms",
        _STABILITY_WINDOW_MS,
    ]
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            timeout=_CAPTURE_TOOL_TIMEOUT_SECONDS,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        destination.unlink(missing_ok=True)
        return _entry(spec, "collection_failed", reason="capture-tool-failed")
    if completed.returncode == 0:
        record = _load_json_object(record_path)
        if (
            record is None
            or record.get("status") != "accepted"
            or not isinstance(record.get("artifact_sha256"), str)
            or not isinstance(record.get("total_bytes"), int)
        ):
            destination.unlink(missing_ok=True)
            return _entry(spec, "collection_failed", reason="capture-tool-failed")
        sanitized = {
            key: record[key] for key in _SANITIZED_RECORD_KEYS if key in record
        }
        return _entry(
            spec,
            "present",
            size=record["total_bytes"],
            digest=record["artifact_sha256"],
            capture_record=sanitized,
        )
    destination.unlink(missing_ok=True)
    if completed.returncode == 2:
        record = _load_json_object(record_path)
        reason = record.get("reason") if record is not None else None
        if not isinstance(reason, str) or not reason:
            reason = "capture-tool-failed"
        return _entry(spec, "collection_failed", reason=reason)
    return _entry(spec, "collection_failed", reason="capture-tool-failed")


def _load_json_object(path: Path) -> dict[str, object] | None:
    try:
        loaded = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(loaded, dict):
        return None
    return loaded


def _copy_regular_file(
    spec: _ArtifactSpec, source: Path, destination: Path
) -> dict[str, object]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        metadata = os.lstat(source)
        if not stat.S_ISREG(metadata.st_mode):
            raise _CollectionFailed("unsafe-file")
        if metadata.st_size > spec.max_bytes:
            raise _CollectionFailed("size-limit")
        hasher = hashlib.sha256()
        total = 0
        source_descriptor = os.open(
            source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            with (
                os.fdopen(source_descriptor, "rb") as source_file,
                open(destination, "wb") as destination_file,
            ):
                while chunk := source_file.read(65536):
                    total += len(chunk)
                    if total > spec.max_bytes:
                        raise _CollectionFailed("size-limit")
                    hasher.update(chunk)
                    destination_file.write(chunk)
                destination_file.flush()
                os.fsync(destination_file.fileno())
        except _CollectionFailed:
            raise
    except _CollectionFailed as failure:
        destination.unlink(missing_ok=True)
        return _entry(spec, "collection_failed", reason=failure.reason)
    except OSError:
        destination.unlink(missing_ok=True)
        return _entry(spec, "collection_failed", reason="unsafe-file")
    return _entry(spec, "present", size=total, digest=hasher.hexdigest())


def _collect_artifact(
    spec: _ArtifactSpec,
    source: Path | None,
    staging: Path,
    *,
    cell_id: str,
    capture_tool: Path,
    records_dir: Path,
) -> dict[str, object]:
    if source is None or not os.path.lexists(source):
        return _entry(spec, "not_produced")
    destination = staging / spec.path
    if spec.media_type == "application/json":
        return _capture_json_artifact(
            spec,
            source,
            destination,
            cell_id=cell_id,
            capture_tool=capture_tool,
            records_dir=records_dir,
        )
    return _copy_regular_file(spec, source, destination)


def _discover_trial_root(raw_dir: Path, infrastructure_events: list[str]) -> Path | None:
    trials_dir = raw_dir / "trials"
    if not trials_dir.is_dir():
        return None
    results = sorted(trials_dir.rglob("result.json"))
    if len(results) == 1:
        return results[0].parent
    if len(results) > 1:
        infrastructure_events.append("harbor-result-ambiguous")
    return None


def _classify_handoff(
    staging: Path,
    entries: dict[str, dict[str, object]],
    trial_root: Path | None,
    *,
    integrity_events: list[str],
    infrastructure_events: list[str],
) -> tuple[str, str | None]:
    if trial_root is None:
        return "not-applicable", None
    capture_entry = entries["capture/capture.json"]
    if capture_entry["status"] == "not_produced":
        infrastructure_events.append("capture-incomplete")
        return "missing", None
    if capture_entry["status"] != "present":
        infrastructure_events.append("collector-failed")
        return "malformed", None
    record = _load_json_object(staging / "capture/capture.json")
    if (
        record is None
        or record.get("schema_version") != _CAPTURE_SCHEMA_VERSION
        or record.get("status") not in {"accepted", "rejected"}
    ):
        infrastructure_events.append("collector-failed")
        return "malformed", None
    if record["status"] == "rejected":
        reason = record.get("reason")
        rejection = reason if isinstance(reason, str) and reason else "unknown"
        if rejection == "hidden_marker_exposed":
            integrity_events.append("hidden-marker-exposed")
        return "rejected", rejection
    kind = record.get("kind")
    if kind == "no-op":
        return "no-op", None
    if kind != "patch":
        infrastructure_events.append("collector-failed")
        return "malformed", None
    patch_sha256 = record.get("patch_sha256")
    if not isinstance(patch_sha256, str):
        infrastructure_events.append("collector-failed")
        return "malformed", None
    patch_entry = entries["capture/submission.patch"]
    if (
        patch_entry["status"] == "present"
        and patch_entry["sha256"] != f"sha256:{patch_sha256}"
    ):
        integrity_events.append("capture-record-mismatch")
    return "patch", None


def _check_collect_manifest(
    staging: Path,
    entries: dict[str, dict[str, object]],
    infrastructure_events: list[str],
) -> None:
    if entries["harbor/collect-manifest.json"]["status"] != "present":
        return

    def fail() -> None:
        if "collector-failed" not in infrastructure_events:
            infrastructure_events.append("collector-failed")

    # Harbor 0.18 writes the collect manifest as an array of entry objects:
    # {source, destination, type, status, service} with status one of
    # ok | empty | failed | skipped.
    try:
        manifest = json.loads((staging / "harbor/collect-manifest.json").read_bytes())
    except (OSError, UnicodeDecodeError, ValueError):
        fail()
        return
    if not isinstance(manifest, list):
        fail()
        return
    for entry in manifest:
        if not isinstance(entry, dict):
            fail()
            return
        source = entry.get("source")
        status = entry.get("status")
        if not isinstance(source, str) or not isinstance(status, str):
            fail()
            return
        if "/capture/" in source and status == "failed":
            fail()
            return


def _mandatory_paths(
    execution: Mapping[str, object], handoff: str
) -> tuple[str, ...]:
    if execution.get("reason_code") == "wall-time-limit":
        return ()
    mandatory = [
        "harbor/result.json",
        "proxy/proxy.jsonl",
        "capture/capture.json",
    ]
    if handoff == "patch":
        mandatory.append("capture/submission.patch")
    if execution.get("disposition") == "valid_completed":
        mandatory.append("verifier/verifier-result.json")
    return tuple(mandatory)


def _scan_and_redact(root: Path, secrets: tuple[bytes, ...]) -> bool:
    hit = False
    live_secrets = tuple(secret for secret in secrets if secret)
    if not live_secrets:
        return False
    for path in sorted(root.rglob("*")):
        if not stat.S_ISREG(os.lstat(path).st_mode):
            continue
        data = path.read_bytes()
        redacted = data
        for secret in live_secrets:
            if secret in redacted:
                hit = True
                redacted = redacted.replace(secret, _REDACTION)
        if any(secret in redacted for secret in live_secrets):
            redacted = b""
        if redacted != data:
            path.write_bytes(redacted)
    return hit


def _assert_redacted(root: Path, secrets: tuple[bytes, ...]) -> None:
    for path in sorted(root.rglob("*")):
        if not stat.S_ISREG(os.lstat(path).st_mode):
            continue
        data = path.read_bytes()
        if any(secret and secret in data for secret in secrets):
            raise RuntimeError(f"secret survived redaction in {path}")


def _staged_regular_files(staging: Path) -> set[str]:
    return {
        path.relative_to(staging).as_posix()
        for path in staging.rglob("*")
        if stat.S_ISREG(os.lstat(path).st_mode)
    }


def _seal_bundle(
    cell_dir: Path,
    staging: Path,
    inventory_entries: list[dict[str, object]],
    *,
    cell_id: str,
    run_id: str,
    infrastructure_events: list[str],
) -> str | None:
    try:
        inventory = {
            "artifacts": inventory_entries,
            "cell_id": cell_id,
            "run_id": run_id,
            "schema_version": 1,
        }
        inventory_bytes = canonical_json_bytes(inventory)
        present_paths = {
            str(entry["path"])
            for entry in inventory_entries
            if entry["status"] == "present"
        }
        if _staged_regular_files(staging) != present_paths:
            infrastructure_events.append("bundle-inventory-mismatch")
            raise _SealFailed("staged files do not match the inventory")
        identity = TypedDigest.from_bytes(DigestKind.RESULT_BUNDLE, inventory_bytes)
        for entry in inventory_entries:
            if entry["status"] != "present":
                continue
            data = (staging / str(entry["path"])).read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if entry["sha256"] != f"sha256:{digest}" or entry["bytes"] != len(data):
                raise _SealFailed(f"read-back mismatch for {entry['path']}")
        for relative in present_paths:
            os.chmod(staging / relative, 0o400)
        inventory_path = staging / "inventory.json"
        _atomic_write(inventory_path, inventory_bytes)
        os.chmod(inventory_path, 0o400)
        os.replace(staging, cell_dir / "bundle")
        _atomic_write(
            cell_dir / "bundle.identity", f"{identity}\n".encode("utf-8")
        )
        return str(identity)
    except Exception:
        return None


def _build_details(
    execution: Mapping[str, object],
    entries: list[dict[str, object]],
    *,
    handoff: str,
    handoff_rejection: str | None,
    quarantined: bool,
    integrity_events: list[str],
    infrastructure_events: list[str],
    missing_evidence: list[str],
) -> dict[str, object]:
    base = execution.get("details")
    details: dict[str, object] = dict(base) if isinstance(base, Mapping) else {}
    present = [entry for entry in entries if entry["status"] == "present"]
    details["handoff"] = handoff
    details["handoff_rejection"] = handoff_rejection
    details["limitations"] = sorted(
        f"{entry['role']}:{entry['status']}"
        for entry in entries
        if entry["status"] != "present"
    )
    details["bundle_artifact_count"] = len(present)
    details["bundle_total_bytes"] = sum(
        entry["bytes"] for entry in present if isinstance(entry["bytes"], int)
    )
    details["quarantined"] = quarantined
    details["integrity_events"] = sorted(integrity_events)
    details["infrastructure_events"] = sorted(infrastructure_events)
    if missing_evidence:
        details["missing_evidence"] = sorted(missing_evidence)
    return details


def _fail_closed_details(
    execution: Mapping[str, object], infrastructure_events: list[str]
) -> dict[str, object]:
    base = execution.get("details")
    details: dict[str, object] = dict(base) if isinstance(base, Mapping) else {}
    details["quarantined"] = False
    details["integrity_events"] = []
    details["infrastructure_events"] = sorted(infrastructure_events)
    return details


def _reconcile(
    execution: Mapping[str, object],
    *,
    handoff: str,
    identity: str | None,
    seal_failed: bool,
    integrity_events: list[str],
    infrastructure_events: list[str],
    details: Mapping[str, object],
) -> CellSealOutcome:
    if integrity_events:
        return CellSealOutcome(
            disposition="invalid_integrity",
            terminal_phase="evidence",
            reason_code=integrity_events[0],
            evidence_valid=False,
            result_bundle_identity=identity,
            details=details,
        )
    if seal_failed:
        return CellSealOutcome(
            disposition="invalid_infrastructure",
            terminal_phase="evidence",
            reason_code="bundle-seal-failed",
            evidence_valid=False,
            result_bundle_identity=None,
            details=details,
        )
    if infrastructure_events:
        return CellSealOutcome(
            disposition="invalid_infrastructure",
            terminal_phase="evidence",
            reason_code=infrastructure_events[0],
            evidence_valid=False,
            result_bundle_identity=identity,
            details=details,
        )
    disposition = str(execution.get("disposition") or "")
    terminal_phase = str(execution.get("terminal_phase") or "")
    reason_code = str(execution.get("reason_code") or "")
    if disposition == "valid_limit_outcome":
        return CellSealOutcome(
            disposition=disposition,
            terminal_phase=terminal_phase,
            reason_code=reason_code,
            evidence_valid=True,
            result_bundle_identity=identity,
            details=details,
        )
    if disposition == "valid_completed":
        if handoff not in {"patch", "no-op"}:
            return CellSealOutcome(
                disposition="invalid_infrastructure",
                terminal_phase="evidence",
                reason_code="handoff-mismatch",
                evidence_valid=False,
                result_bundle_identity=identity,
                details=details,
            )
        return CellSealOutcome(
            disposition=disposition,
            terminal_phase="verification",
            reason_code=(
                "verifier-completed" if handoff == "patch" else "verifier-completed-no-op"
            ),
            evidence_valid=True,
            result_bundle_identity=identity,
            details=details,
        )
    if disposition == "valid_harness_outcome":
        if handoff == "rejected":
            return CellSealOutcome(
                disposition=disposition,
                terminal_phase="capture",
                reason_code="submission-rejected",
                evidence_valid=True,
                result_bundle_identity=identity,
                details=details,
            )
        return CellSealOutcome(
            disposition=disposition,
            terminal_phase=terminal_phase,
            reason_code=reason_code,
            evidence_valid=True,
            result_bundle_identity=identity,
            details=details,
        )
    return CellSealOutcome(
        disposition=disposition,
        terminal_phase=terminal_phase,
        reason_code=reason_code,
        evidence_valid=False,
        result_bundle_identity=identity,
        details=details,
    )


def seal_cell_evidence(
    cell_dir: Path,
    *,
    cell_id: str,
    run_id: str,
    execution: Mapping[str, object],
    injected_secrets: tuple[bytes, ...] = (),
    capture_tool: Path = TRUSTED_CAPTURE_TOOL,
) -> CellSealOutcome:
    """Seal the durable evidence of one executed cell into a Result Bundle."""
    bundle_dir = cell_dir / "bundle"
    if bundle_dir.exists():
        return CellSealOutcome(
            disposition="invalid_infrastructure",
            terminal_phase="evidence",
            reason_code="bundle-already-sealed",
            evidence_valid=False,
            result_bundle_identity=None,
            details=_fail_closed_details(execution, ["bundle-already-sealed"]),
        )
    raw_dir = cell_dir / "raw"
    if not raw_dir.is_dir():
        return CellSealOutcome(
            disposition="invalid_infrastructure",
            terminal_phase="evidence",
            reason_code="raw-evidence-missing",
            evidence_valid=False,
            result_bundle_identity=None,
            details=_fail_closed_details(execution, ["raw-evidence-missing"]),
        )

    integrity_events: list[str] = []
    infrastructure_events: list[str] = []
    staging = cell_dir / "bundle.staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    trial_root = _discover_trial_root(raw_dir, infrastructure_events)
    entries: dict[str, dict[str, object]] = {}

    execution_bytes = canonical_json_bytes(execution)
    execution_destination = staging / _EXECUTION_RECORD_SPEC.path
    execution_destination.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(execution_destination, execution_bytes)
    entries[_EXECUTION_RECORD_SPEC.path] = _entry(
        _EXECUTION_RECORD_SPEC,
        "present",
        size=len(execution_bytes),
        digest=hashlib.sha256(execution_bytes).hexdigest(),
    )

    with tempfile.TemporaryDirectory(prefix="model-benchmark-records-") as records:
        records_dir = Path(records)
        canonical_sources: set[Path] = set()
        for spec, relative in _TRIAL_SPECS:
            source = trial_root / relative if trial_root is not None else None
            if source is not None:
                canonical_sources.add(source)
            entries[spec.path] = _collect_artifact(
                spec,
                source,
                staging,
                cell_id=cell_id,
                capture_tool=capture_tool,
                records_dir=records_dir,
            )
        for spec, relative in _RAW_SPECS:
            entries[spec.path] = _collect_artifact(
                spec,
                raw_dir / relative,
                staging,
                cell_id=cell_id,
                capture_tool=capture_tool,
                records_dir=records_dir,
            )
        if trial_root is not None:
            for path in sorted(trial_root.rglob("*")):
                if path in canonical_sources:
                    continue
                if not stat.S_ISREG(os.lstat(path).st_mode):
                    continue
                relative_path = path.relative_to(trial_root).as_posix()
                spec = _ArtifactSpec(
                    path=f"diagnostics/{relative_path}",
                    role="native-diagnostics",
                    media_type="application/octet-stream",
                    max_bytes=32 * _MIB,
                    source="harbor",
                )
                entries[spec.path] = _copy_regular_file(
                    spec, path, staging / spec.path
                )

    handoff, handoff_rejection = _classify_handoff(
        staging,
        entries,
        trial_root,
        integrity_events=integrity_events,
        infrastructure_events=infrastructure_events,
    )
    _check_collect_manifest(staging, entries, infrastructure_events)

    missing_evidence = [
        path
        for path in _mandatory_paths(execution, handoff)
        if entries[path]["status"] != "present"
    ]
    if missing_evidence:
        infrastructure_events.append("missing-mandatory-evidence")
    if (
        execution.get("disposition") == "valid_harness_outcome"
        and execution.get("reason_code") == "submission-not-evaluable"
        and handoff in {"patch", "no-op"}
        and entries["verifier/verifier-result.json"]["status"] != "present"
    ):
        infrastructure_events.append("verifier-evidence-missing")

    inventory_entries = [entries[path] for path in sorted(entries)]

    if _scan_and_redact(staging, injected_secrets):
        quarantine = cell_dir / "quarantine"
        os.replace(staging, quarantine)
        _assert_redacted(quarantine, injected_secrets)
        return CellSealOutcome(
            disposition="invalid_infrastructure",
            terminal_phase="evidence",
            reason_code="secret-escaped-redaction",
            evidence_valid=False,
            result_bundle_identity=None,
            details=_build_details(
                execution,
                inventory_entries,
                handoff=handoff,
                handoff_rejection=handoff_rejection,
                quarantined=True,
                integrity_events=integrity_events,
                infrastructure_events=[
                    *infrastructure_events,
                    "secret-escaped-redaction",
                ],
                missing_evidence=missing_evidence,
            ),
        )

    identity = _seal_bundle(
        cell_dir,
        staging,
        inventory_entries,
        cell_id=cell_id,
        run_id=run_id,
        infrastructure_events=infrastructure_events,
    )
    seal_failed = identity is None
    if seal_failed and "bundle-seal-failed" not in infrastructure_events:
        infrastructure_events.append("bundle-seal-failed")

    details = _build_details(
        execution,
        inventory_entries,
        handoff=handoff,
        handoff_rejection=handoff_rejection,
        quarantined=False,
        integrity_events=integrity_events,
        infrastructure_events=infrastructure_events,
        missing_evidence=missing_evidence,
    )
    return _reconcile(
        execution,
        handoff=handoff,
        identity=identity,
        seal_failed=seal_failed,
        integrity_events=integrity_events,
        infrastructure_events=infrastructure_events,
        details=details,
    )

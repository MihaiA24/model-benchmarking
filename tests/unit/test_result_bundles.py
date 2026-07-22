from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

from model_benchmark.declarations.canonical import load_canonical_json
from model_benchmark.declarations.identities import DigestKind, TypedDigest
from model_benchmark.runtime.bundles import CellSealOutcome, seal_cell_evidence


CELL_ID = "run-0001-cell-0001"
RUN_ID = "functional-v1-run-0001"
DEFAULT_PATCH = b"--- a/src/app.py\n+++ b/src/app.py\n@@ -0,0 +1 @@\n+print()\n"
SECRET = b"sk-super-secret-0123456789abcdef"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _accepted_record(patch: bytes, kind: str) -> bytes:
    record = {
        "baseline_sha256": _sha256(b"baseline"),
        "collector": {
            "capture_source_sha256": _sha256(b"collector"),
            "policy_sha256": _sha256(b"policy"),
        },
        "file_count": 0 if kind == "no-op" else 1,
        "final_sha256": _sha256(b"final"),
        "hidden_markers": {"digests": [], "status": "absent"},
        "kind": kind,
        "patch_sha256": _sha256(patch),
        "schema_version": "scenario-capture-v1",
        "stability_window_ms": 250,
        "status": "accepted",
        "total_bytes": len(patch),
    }
    return json.dumps(record, sort_keys=True).encode("utf-8")


def _rejected_record(reason: str) -> bytes:
    record = {
        "collector": {
            "capture_source_sha256": _sha256(b"collector"),
            "policy_sha256": _sha256(b"policy"),
        },
        "reason": reason,
        "schema_version": "scenario-capture-v1",
        "status": "rejected",
    }
    return json.dumps(record, sort_keys=True).encode("utf-8")


def _harbor_collect_manifest(
    capture_status: str = "ok", patch_status: str | None = None
) -> bytes:
    entries = [
        {
            "source": "/logs/artifacts",
            "destination": "artifacts/logs/artifacts",
            "type": "directory",
            "status": "empty",
            "service": None,
        },
        {
            "source": "/capture/capture.json",
            "destination": "artifacts/capture/capture.json",
            "type": "file",
            "status": capture_status,
            "service": "capture",
        },
        {
            "source": "/capture/submission.patch",
            "destination": "artifacts/capture/submission.patch",
            "type": "file",
            "status": capture_status if patch_status is None else patch_status,
            "service": "capture",
        },
    ]
    return json.dumps(entries).encode("utf-8")


def _build_cell(
    root: Path,
    *,
    patch: bytes = DEFAULT_PATCH,
    capture: bytes | None = None,
    collect_manifest: bytes | None = None,
    include_trial: bool = True,
    include_capture: bool = True,
    include_patch: bool = True,
    include_verifier: bool = True,
    include_proxy: bool = True,
) -> Path:
    cell_dir = root / "cell"
    raw = cell_dir / "raw"
    _write(raw / "overlay.yaml", b"services: {}\n")
    if include_trial:
        trial = raw / "trials" / "t1"
        _write(
            trial / "result.json",
            json.dumps({"status": "completed", "trial": "t1"}).encode("utf-8"),
        )
        _write(trial / "trial.log", b"trial started\ntrial finished\n")
        if collect_manifest is not None:
            _write(trial / "artifacts" / "manifest.json", collect_manifest)
        if include_capture:
            capture_bytes = (
                capture
                if capture is not None
                else _accepted_record(patch, "no-op" if not patch else "patch")
            )
            _write(trial / "artifacts" / "capture" / "capture.json", capture_bytes)
        if include_patch:
            _write(trial / "artifacts" / "capture" / "submission.patch", patch)
        if include_verifier:
            _write(
                trial / "verifier" / "verifier-result.json",
                json.dumps({"disposition": "completed", "reward": 1}).encode("utf-8"),
            )
    else:
        (raw / "trials").mkdir(parents=True, exist_ok=True)
    if include_proxy:
        _write(raw / "proxy-evidence" / "proxy.jsonl", b'{"event":"request"}\n')
    return cell_dir


def _execution(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "cell_id": CELL_ID,
        "details": {"provider_requests": 2, "provider_tokens": 900},
        "disposition": "valid_completed",
        "duration_ns": 5_000_000,
        "ended_at_utc": "2026-07-16T00:00:00Z",
        "evidence_valid": True,
        "reason_code": "agent-completed",
        "run_id": RUN_ID,
        "terminal_phase": "execution",
    }
    record.update(overrides)
    return record


def _seal(cell_dir: Path, execution: dict[str, object], **kwargs: object) -> CellSealOutcome:
    return seal_cell_evidence(
        cell_dir,
        cell_id=CELL_ID,
        run_id=RUN_ID,
        execution=execution,
        **kwargs,  # type: ignore[arg-type]
    )


def _inventory(cell_dir: Path) -> dict[str, object]:
    loaded = load_canonical_json((cell_dir / "bundle" / "inventory.json").read_bytes())
    assert isinstance(loaded, dict)
    return loaded


def _entry_by_path(inventory: dict[str, object], path: str) -> dict[str, object]:
    artifacts = inventory["artifacts"]
    assert isinstance(artifacts, list)
    for entry in artifacts:
        if entry["path"] == path:
            return entry
    raise AssertionError(f"no inventory entry for {path}")


def test_valid_completion_seals_deterministic_read_only_bundle(tmp_path: Path) -> None:
    cell_dir = _build_cell(tmp_path / "a")
    outcome = _seal(cell_dir, _execution())

    assert outcome.disposition == "valid_completed"
    assert outcome.terminal_phase == "verification"
    assert outcome.reason_code == "verifier-completed"
    assert outcome.evidence_valid is True
    assert outcome.result_bundle_identity is not None
    parsed = TypedDigest.parse(outcome.result_bundle_identity)
    assert parsed.kind is DigestKind.RESULT_BUNDLE
    assert outcome.details["handoff"] == "patch"

    bundle = cell_dir / "bundle"
    assert bundle.is_dir()
    assert not (cell_dir / "bundle.staging").exists()
    identity_text = (cell_dir / "bundle.identity").read_text(encoding="utf-8")
    assert identity_text == f"{outcome.result_bundle_identity}\n"
    for file_path in sorted(bundle.rglob("*")):
        if stat.S_ISREG(os.lstat(file_path).st_mode):
            assert os.stat(file_path).st_mode & 0o222 == 0

    inventory = _inventory(cell_dir)
    artifacts = inventory["artifacts"]
    assert isinstance(artifacts, list)
    paths = [entry["path"] for entry in artifacts]
    assert paths == sorted(paths)
    assert inventory["schema_version"] == 1
    assert inventory["cell_id"] == CELL_ID
    assert inventory["run_id"] == RUN_ID
    patch_entry = _entry_by_path(inventory, "capture/submission.patch")
    assert patch_entry["sensitivity"] == "public"
    assert patch_entry["status"] == "present"

    other_cell = _build_cell(tmp_path / "b")
    other = _seal(other_cell, _execution())
    assert other.result_bundle_identity == outcome.result_bundle_identity


def test_no_op_handoff_completes_without_patch_content(tmp_path: Path) -> None:
    cell_dir = _build_cell(tmp_path, patch=b"")
    outcome = _seal(cell_dir, _execution())

    assert outcome.disposition == "valid_completed"
    assert outcome.reason_code == "verifier-completed-no-op"
    assert outcome.evidence_valid is True
    assert outcome.details["handoff"] == "no-op"
    assert outcome.result_bundle_identity is not None


def test_omp_provisioned_natives_are_excluded_from_diagnostics(tmp_path: Path) -> None:
    cell_id = "01-python-sales-by-genre-omp"
    cell_dir = _build_cell(tmp_path)
    trial = cell_dir / "raw/trials/t1"
    _write(trial / "agent/home/.omp/natives/16.4.0/omp", b"provisioned binary")
    _write(trial / "agent/home/.omp/logs/session.log", b"diagnostic log")

    outcome = seal_cell_evidence(
        cell_dir,
        cell_id=cell_id,
        run_id=RUN_ID,
        execution=_execution(cell_id=cell_id),
    )

    assert outcome.disposition == "valid_completed"
    inventory = _inventory(cell_dir)
    artifacts = inventory["artifacts"]
    assert isinstance(artifacts, list)
    paths = {entry["path"] for entry in artifacts}
    assert "diagnostics/agent/home/.omp/natives/16.4.0/omp" not in paths
    assert "diagnostics/agent/home/.omp/logs/session.log" in paths


def test_rejected_handoff_reconciles_to_submission_rejected(tmp_path: Path) -> None:
    cell_dir = _build_cell(
        tmp_path,
        capture=_rejected_record("undeclared_path"),
        include_patch=False,
        include_verifier=False,
    )
    execution = _execution(
        disposition="valid_harness_outcome",
        reason_code="submission-not-evaluable",
        terminal_phase="capture",
    )
    outcome = _seal(cell_dir, execution)

    assert outcome.disposition == "valid_harness_outcome"
    assert outcome.terminal_phase == "capture"
    assert outcome.reason_code == "submission-rejected"
    assert outcome.evidence_valid is True
    assert outcome.details["handoff"] == "rejected"
    assert outcome.details["handoff_rejection"] == "undeclared_path"
    assert outcome.result_bundle_identity is not None


def test_hidden_marker_rejection_is_integrity_but_still_sealed(tmp_path: Path) -> None:
    cell_dir = _build_cell(
        tmp_path,
        capture=_rejected_record("hidden_marker_exposed"),
        include_patch=False,
        include_verifier=False,
    )
    execution = _execution(
        disposition="valid_harness_outcome",
        reason_code="submission-not-evaluable",
        terminal_phase="capture",
    )
    outcome = _seal(cell_dir, execution)

    assert outcome.disposition == "invalid_integrity"
    assert outcome.terminal_phase == "evidence"
    assert outcome.reason_code == "hidden-marker-exposed"
    assert outcome.evidence_valid is False
    assert outcome.result_bundle_identity is not None
    assert (cell_dir / "bundle").is_dir()


def test_patch_digest_mismatch_is_integrity_event(tmp_path: Path) -> None:
    record = json.loads(_accepted_record(DEFAULT_PATCH, "patch"))
    record["patch_sha256"] = _sha256(b"a different patch body")
    cell_dir = _build_cell(
        tmp_path, capture=json.dumps(record, sort_keys=True).encode("utf-8")
    )
    outcome = _seal(cell_dir, _execution())

    assert outcome.disposition == "invalid_integrity"
    assert outcome.reason_code == "capture-record-mismatch"
    assert outcome.evidence_valid is False
    assert outcome.result_bundle_identity is not None


def test_missing_capture_record_is_capture_incomplete(tmp_path: Path) -> None:
    cell_dir = _build_cell(tmp_path, include_capture=False, include_patch=False)
    outcome = _seal(cell_dir, _execution())

    assert outcome.disposition == "invalid_infrastructure"
    assert outcome.terminal_phase == "evidence"
    assert outcome.reason_code == "capture-incomplete"
    assert outcome.evidence_valid is False
    assert outcome.details["handoff"] == "missing"


def test_malformed_capture_record_is_collector_failed(tmp_path: Path) -> None:
    cell_dir = _build_cell(tmp_path, capture=b"this is not json{")
    outcome = _seal(cell_dir, _execution())

    assert outcome.disposition == "invalid_infrastructure"
    assert outcome.reason_code == "collector-failed"
    assert outcome.evidence_valid is False


def test_missing_verifier_result_is_missing_mandatory_evidence(tmp_path: Path) -> None:
    cell_dir = _build_cell(tmp_path, include_verifier=False)
    outcome = _seal(cell_dir, _execution())

    assert outcome.disposition == "invalid_infrastructure"
    assert outcome.reason_code == "missing-mandatory-evidence"
    assert outcome.evidence_valid is False
    assert "verifier/verifier-result.json" in outcome.details["missing_evidence"]


def test_not_evaluable_with_accepted_patch_needs_verifier_evidence(tmp_path: Path) -> None:
    cell_dir = _build_cell(tmp_path, include_verifier=False)
    execution = _execution(
        disposition="valid_harness_outcome",
        reason_code="submission-not-evaluable",
        terminal_phase="verification",
    )
    outcome = _seal(cell_dir, execution)

    assert outcome.disposition == "invalid_infrastructure"
    assert outcome.reason_code == "verifier-evidence-missing"
    assert outcome.evidence_valid is False


def test_wall_time_limit_outcome_is_preserved(tmp_path: Path) -> None:
    cell_dir = _build_cell(tmp_path, include_trial=False, include_proxy=False)
    execution = _execution(
        disposition="valid_limit_outcome",
        reason_code="wall-time-limit",
        terminal_phase="execution",
    )
    outcome = _seal(cell_dir, execution)

    assert outcome.disposition == "valid_limit_outcome"
    assert outcome.terminal_phase == "execution"
    assert outcome.reason_code == "wall-time-limit"
    assert outcome.evidence_valid is True
    assert outcome.result_bundle_identity is not None
    assert outcome.details["handoff"] == "not-applicable"

    inventory = _inventory(cell_dir)
    for path in ("harbor/result.json", "capture/capture.json", "proxy/proxy.jsonl"):
        entry = _entry_by_path(inventory, path)
        assert entry["status"] == "not_produced"
        assert entry["sha256"] is None
        assert entry["bytes"] is None
    assert _entry_by_path(inventory, "coordinator/execution.json")["status"] == "present"


def test_escaped_secret_quarantines_redacted_evidence(tmp_path: Path) -> None:
    cell_dir = _build_cell(tmp_path)
    _write(
        cell_dir / "raw" / "trials" / "t1" / "agent-debug.log",
        b"request sent with " + SECRET + b" in the header\n",
    )
    outcome = _seal(cell_dir, _execution(), injected_secrets=(SECRET,))

    assert outcome.disposition == "invalid_infrastructure"
    assert outcome.terminal_phase == "evidence"
    assert outcome.reason_code == "secret-escaped-redaction"
    assert outcome.evidence_valid is False
    assert outcome.result_bundle_identity is None
    assert outcome.details["quarantined"] is True
    assert not (cell_dir / "bundle").exists()

    quarantine = cell_dir / "quarantine"
    assert quarantine.is_dir()
    quarantined = (quarantine / "diagnostics" / "agent-debug.log").read_bytes()
    assert b"[REDACTED]" in quarantined
    assert SECRET not in quarantined
    for file_path in sorted(quarantine.rglob("*")):
        if stat.S_ISREG(os.lstat(file_path).st_mode):
            assert SECRET not in file_path.read_bytes()


def test_sealed_bundle_bytes_match_inventory_exactly(tmp_path: Path) -> None:
    cell_dir = _build_cell(tmp_path)
    outcome = _seal(cell_dir, _execution())
    assert outcome.result_bundle_identity is not None

    bundle = cell_dir / "bundle"
    on_disk = {
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if stat.S_ISREG(os.lstat(path).st_mode)
    }
    inventory = _inventory(cell_dir)
    artifacts = inventory["artifacts"]
    assert isinstance(artifacts, list)
    present = {
        entry["path"] for entry in artifacts if entry["status"] == "present"
    }
    assert on_disk == present | {"inventory.json"}


def test_sealing_twice_is_forbidden(tmp_path: Path) -> None:
    cell_dir = _build_cell(tmp_path)
    first = _seal(cell_dir, _execution())
    assert first.result_bundle_identity is not None

    second = _seal(cell_dir, _execution())
    assert second.disposition == "invalid_infrastructure"
    assert second.reason_code == "bundle-already-sealed"
    assert second.evidence_valid is False
    assert second.result_bundle_identity is None


def test_symlinked_trial_result_fails_the_capture_seam(tmp_path: Path) -> None:
    cell_dir = _build_cell(tmp_path)
    trial = cell_dir / "raw" / "trials" / "t1"
    result_bytes = (trial / "result.json").read_bytes()
    (trial / "result.json").unlink()
    target = cell_dir / "raw" / "native-result.json"
    _write(target, result_bytes)
    (trial / "result.json").symlink_to(target)

    outcome = _seal(cell_dir, _execution())

    assert outcome.disposition == "invalid_infrastructure"
    assert outcome.reason_code == "missing-mandatory-evidence"
    assert outcome.evidence_valid is False
    assert "harbor/result.json" in outcome.details["missing_evidence"]
    inventory = _inventory(cell_dir)
    assert _entry_by_path(inventory, "harbor/result.json")["status"] == "collection_failed"


def test_harbor_array_collect_manifest_is_accepted(tmp_path: Path) -> None:
    # Harbor 0.18 writes artifacts/manifest.json as an array of entry
    # objects; a healthy collection must not be reported as a failure.
    cell_dir = _build_cell(tmp_path, collect_manifest=_harbor_collect_manifest())
    outcome = _seal(cell_dir, _execution())

    assert outcome.disposition == "valid_completed"
    assert outcome.reason_code == "verifier-completed"
    assert outcome.evidence_valid is True


def test_capture_collection_failure_in_array_manifest_is_collector_failed(
    tmp_path: Path,
) -> None:
    cell_dir = _build_cell(
        tmp_path, collect_manifest=_harbor_collect_manifest("failed")
    )
    outcome = _seal(cell_dir, _execution())

    assert outcome.disposition == "invalid_infrastructure"
    assert outcome.reason_code == "collector-failed"
    assert outcome.evidence_valid is False


def test_non_array_collect_manifest_fails_closed(tmp_path: Path) -> None:
    legacy_mapping = json.dumps({"/capture/capture.json": "ok"}).encode("utf-8")
    cell_dir = _build_cell(tmp_path, collect_manifest=legacy_mapping)
    outcome = _seal(cell_dir, _execution())

    assert outcome.disposition == "invalid_infrastructure"
    assert outcome.reason_code == "collector-failed"
    assert outcome.evidence_valid is False


def test_rejected_capture_patch_collection_failure_is_not_collector_failed(
    tmp_path: Path,
) -> None:
    # A rejected (or no-op) capture writes no submission.patch, so Harbor
    # reports its collection as failed; that expected failure must not
    # override the valid submission-rejected handoff.
    cell_dir = _build_cell(
        tmp_path,
        capture=_rejected_record("undeclared_path"),
        include_patch=False,
        include_verifier=False,
        collect_manifest=_harbor_collect_manifest("ok", patch_status="failed"),
    )
    execution = _execution(
        disposition="valid_harness_outcome",
        reason_code="submission-not-evaluable",
        terminal_phase="capture",
    )
    outcome = _seal(cell_dir, execution)

    assert outcome.disposition == "valid_harness_outcome"
    assert outcome.reason_code == "submission-rejected"
    assert outcome.evidence_valid is True
    assert outcome.details["handoff"] == "rejected"


def test_verifier_completed_with_rejected_capture_is_submission_rejected(
    tmp_path: Path,
) -> None:
    # The verifier can complete on a repo whose submission the capture
    # boundary rejected (undeclared path). That is a valid harness failure,
    # not a handoff-mismatch infrastructure failure.
    cell_dir = _build_cell(
        tmp_path,
        capture=_rejected_record("undeclared_path"),
        include_patch=False,
        collect_manifest=_harbor_collect_manifest("ok", patch_status="failed"),
    )
    outcome = _seal(cell_dir, _execution(disposition="valid_completed"))

    assert outcome.disposition == "valid_harness_outcome"
    assert outcome.reason_code == "submission-rejected"
    assert outcome.evidence_valid is True
    assert outcome.details["handoff"] == "rejected"

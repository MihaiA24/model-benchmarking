from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from model_benchmark.declarations.canonical import load_canonical_json
from model_benchmark.declarations.functional_v1 import FunctionalV1Manifest
from model_benchmark.declarations.identities import DigestKind, TypedDigest
from model_benchmark.runtime.execution import NativeFunctionalV1Runtime
from model_benchmark.runtime.functional_v1 import (
    CELL_SCHEDULE,
    FunctionalV1Home,
    OperatorContractRuntime,
    RunWorkspace,
)


_STARTED = "2026-07-16T12:00:00Z"
_ENDED = "2026-07-16T12:10:00Z"
_SCORES = {"acceptance_score": 1, "regression_score": 1, "task_success": True}


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def _capture_record(patch: bytes, *, kind: str) -> dict[str, object]:
    return {
        "baseline_sha256": "0" * 64,
        "collector": {
            "capture_source_sha256": "0" * 64,
            "policy_sha256": "0" * 64,
        },
        "file_count": 0 if kind == "no-op" else 1,
        "final_sha256": "0" * 64,
        "hidden_markers": {"digests": [], "status": "absent"},
        "kind": kind,
        "patch_sha256": hashlib.sha256(patch).hexdigest(),
        "schema_version": "scenario-capture-v1",
        "stability_window_ms": 250,
        "status": "accepted",
        "total_bytes": len(patch),
    }


def _raw_tree(
    cell_dir: Path,
    cell_id: str,
    *,
    handoff: str = "patch",
    verifier: bool = True,
    capture: bool = True,
) -> None:
    raw = cell_dir / "raw"
    trial = raw / "trials" / cell_id
    (raw / "proxy-evidence").mkdir(parents=True, exist_ok=True)
    (raw / "overlay.yaml").write_text("services: {}\n", encoding="utf-8")
    (raw / "proxy-evidence" / "proxy.jsonl").write_text(
        json.dumps(
            {
                "event": "provider-response",
                "provider_cost_usd": "0.10",
                "provider_tokens": 100,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _write_json(
        trial / "result.json",
        {
            "agent_result": {"metadata": {"exit_code": 0}},
            "exception_info": None,
            "trial_name": cell_id,
        },
    )
    if capture:
        patch = b"" if handoff == "no-op" else (
            b"diff --git a/src/app.py b/src/app.py\n"
            b"--- a/src/app.py\n+++ b/src/app.py\n"
            b"@@ -1 +1 @@\n-old\n+new\n"
        )
        if handoff == "rejected":
            _write_json(
                trial / "artifacts/capture/capture.json",
                {
                    "collector": {
                        "capture_source_sha256": "0" * 64,
                        "policy_sha256": "0" * 64,
                    },
                    "reason": "undeclared_path",
                    "schema_version": "scenario-capture-v1",
                    "status": "rejected",
                },
            )
        elif handoff == "hidden-marker":
            _write_json(
                trial / "artifacts/capture/capture.json",
                {
                    "collector": {
                        "capture_source_sha256": "0" * 64,
                        "policy_sha256": "0" * 64,
                    },
                    "reason": "hidden_marker_exposed",
                    "schema_version": "scenario-capture-v1",
                    "status": "rejected",
                },
            )
        else:
            _write_json(
                trial / "artifacts/capture/capture.json",
                _capture_record(patch, kind=handoff),
            )
            patch_path = trial / "artifacts/capture/submission.patch"
            patch_path.parent.mkdir(parents=True, exist_ok=True)
            patch_path.write_bytes(patch)
    if verifier:
        _write_json(
            trial / "verifier/verifier-result.json",
            {"domain_scores": {"behavior": 1}, **_SCORES},
        )


def _executed_cell(
    workspace: RunWorkspace,
    cell_id: str,
    *,
    disposition: str = "valid_completed",
    reason_code: str = "verifier-completed",
    terminal_phase: str = "verification",
    details: dict[str, Any] | None = None,
) -> None:
    workspace.write_cell_start(cell_id, started_at_utc=_STARTED)
    workspace.write_cell_execution(
        cell_id,
        disposition=disposition,
        terminal_phase=terminal_phase,
        reason_code=reason_code,
        ended_at_utc=_ENDED,
        duration_ns=600_000_000_000,
        evidence_valid=True,
        details=details
        if details is not None
        else {
            "cost_usd": "0.10",
            "provider_requests": 1,
            "provider_tokens": 100,
            "score_vector": _SCORES,
        },
    )


def test_full_run_drains_to_bundled_terminals_and_sealed_complete_record(
    manifest_bundle: tuple[Path, dict[str, object]],
    tmp_path: Path,
) -> None:
    manifest = FunctionalV1Manifest.load(manifest_bundle[0])
    home = FunctionalV1Home(tmp_path / "home")
    workspace = home.create_workspace(manifest)
    for cell in CELL_SCHEDULE:
        cell_id = str(cell["cell_id"])
        _executed_cell(workspace, cell_id)
        _raw_tree(workspace.root / "cells" / cell_id, cell_id)

    runtime = NativeFunctionalV1Runtime(home)
    runtime._drain_cell_evidence(workspace, CELL_SCHEDULE)

    for cell in CELL_SCHEDULE:
        cell_id = str(cell["cell_id"])
        cell_dir = workspace.root / "cells" / cell_id
        terminal = load_canonical_json((cell_dir / "terminal.json").read_bytes())
        assert isinstance(terminal, dict)
        assert terminal["disposition"] == "valid_completed"
        assert terminal["reason_code"] == "verifier-completed"
        assert terminal["evidence_valid"] is True
        identity = TypedDigest.parse(str(terminal["result_bundle_identity"]))
        assert identity.kind is DigestKind.RESULT_BUNDLE
        assert (cell_dir / "bundle" / "inventory.json").is_file()
        details = terminal["details"]
        assert isinstance(details, dict)
        assert details["handoff"] == "patch"

    result = runtime._seal_run(workspace, cells_executed=len(CELL_SCHEDULE))
    assert result.exit_code == 0
    assert result.payload["outcome"] == "sealed"
    assert result.payload["state"] == "complete"
    assert result.payload["validity"] == "valid"

    inspected = OperatorContractRuntime(home).inspect(workspace.run_id)
    assert inspected.exit_code == 0
    lines = inspected.human.splitlines()
    assert lines[0].startswith("SCENARIO | CONDITION | DISPOSITION | TASK")
    assert len(lines) == 1 + len(CELL_SCHEDULE)
    assert " valid_completed | true | 1 | 1 | 600s | 1 | 100 | 0.10 | " in lines[1]
    record = inspected.payload["record"]
    assert isinstance(record, dict)
    cells = record["cells"]
    assert isinstance(cells, list)
    assert all(cell["score_vector"] == _SCORES for cell in cells)


def test_distinguishable_outcomes_drain_to_distinct_terminal_facts(
    manifest_bundle: tuple[Path, dict[str, object]],
    tmp_path: Path,
) -> None:
    manifest = FunctionalV1Manifest.load(manifest_bundle[0])
    home = FunctionalV1Home(tmp_path / "home")
    workspace = home.create_workspace(manifest)
    cell_ids = [str(cell["cell_id"]) for cell in CELL_SCHEDULE]
    cases: dict[str, tuple[str, str]] = {}

    # Valid completion with an accepted patch.
    _executed_cell(workspace, cell_ids[0])
    _raw_tree(workspace.root / "cells" / cell_ids[0], cell_ids[0])
    cases[cell_ids[0]] = ("valid_completed", "verifier-completed")

    # Accepted no-op handoff.
    _executed_cell(workspace, cell_ids[1])
    _raw_tree(workspace.root / "cells" / cell_ids[1], cell_ids[1], handoff="no-op")
    cases[cell_ids[1]] = ("valid_completed", "verifier-completed-no-op")

    # Policy-rejected handoff stays a valid harness outcome.
    _executed_cell(
        workspace,
        cell_ids[2],
        disposition="valid_harness_outcome",
        reason_code="submission-not-evaluable",
        details={},
    )
    _raw_tree(
        workspace.root / "cells" / cell_ids[2],
        cell_ids[2],
        handoff="rejected",
        verifier=False,
    )
    cases[cell_ids[2]] = ("valid_harness_outcome", "submission-rejected")

    # Hidden-marker exposure is an integrity failure.
    _executed_cell(
        workspace,
        cell_ids[3],
        disposition="valid_harness_outcome",
        reason_code="submission-not-evaluable",
        details={},
    )
    _raw_tree(
        workspace.root / "cells" / cell_ids[3],
        cell_ids[3],
        handoff="hidden-marker",
        verifier=False,
    )
    cases[cell_ids[3]] = ("invalid_integrity", "hidden-marker-exposed")

    # Incomplete trusted capture invalidates infrastructure.
    _executed_cell(workspace, cell_ids[4])
    _raw_tree(
        workspace.root / "cells" / cell_ids[4],
        cell_ids[4],
        capture=False,
    )
    cases[cell_ids[4]] = ("invalid_infrastructure", "")

    # Declared wall-time limit with sparse evidence stays valid.
    _executed_cell(
        workspace,
        cell_ids[5],
        disposition="valid_limit_outcome",
        terminal_phase="condition",
        reason_code="wall-time-limit",
        details={"limit": "wall_time_seconds_per_trial"},
    )
    raw = workspace.root / "cells" / cell_ids[5] / "raw"
    (raw / "trials").mkdir(parents=True)
    (raw / "overlay.yaml").write_text("services: {}\n", encoding="utf-8")
    cases[cell_ids[5]] = ("valid_limit_outcome", "wall-time-limit")

    runtime = NativeFunctionalV1Runtime(home)
    runtime._drain_cell_evidence(workspace, CELL_SCHEDULE)

    observed: dict[str, tuple[str, str]] = {}
    for cell_id, (disposition, reason) in cases.items():
        terminal = load_canonical_json(
            (workspace.root / "cells" / cell_id / "terminal.json").read_bytes()
        )
        assert isinstance(terminal, dict)
        observed[cell_id] = (
            str(terminal["disposition"]),
            str(terminal["reason_code"]),
        )
        assert observed[cell_id][0] == disposition
        if reason:
            assert observed[cell_id][1] == reason
    assert len(set(observed.values())) == len(observed)

    # Integrity and infrastructure cells carry no valid evidence.
    for cell_id in (cell_ids[3], cell_ids[4]):
        terminal = load_canonical_json(
            (workspace.root / "cells" / cell_id / "terminal.json").read_bytes()
        )
        assert isinstance(terminal, dict)
        assert terminal["evidence_valid"] is False

    # Exactly one terminal record per started cell; the rest never started.
    for cell_id in cell_ids[:6]:
        assert (workspace.root / "cells" / cell_id / "terminal.json").is_file()
    for cell_id in cell_ids[6:]:
        assert not (workspace.root / "cells" / cell_id).exists()

    result = runtime._seal_run(workspace, cells_executed=6)
    assert result.exit_code == 1
    assert result.payload["state"] == "incomplete"
    assert result.payload["validity"] == "invalid"
    record = home.sealed_run(workspace.run_id)
    assert record.value["unscheduled_cells"] == cell_ids[6:]

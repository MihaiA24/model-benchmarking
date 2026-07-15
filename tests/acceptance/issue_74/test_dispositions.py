from __future__ import annotations

from pathlib import Path

from model_benchmark.declarations.functional_v1 import FunctionalV1Manifest
from model_benchmark.runtime.functional_v1 import CELL_SCHEDULE, FunctionalV1Home


def test_consumed_prelaunch_attempt_can_terminalize_as_not_started(
    manifest_bundle: tuple[Path, dict[str, object]],
    tmp_path: Path,
) -> None:
    manifest = FunctionalV1Manifest.load(manifest_bundle[0])
    workspace = FunctionalV1Home(tmp_path / "home").create_workspace(manifest)
    cell_id = CELL_SCHEDULE[0]["cell_id"]
    workspace.write_cell_start(
        cell_id,
        started_at_utc="2026-07-15T12:00:00Z",
    )

    terminal = workspace.write_cell_terminal(
        cell_id,
        disposition="not_started",
        terminal_phase="prelaunch",
        reason_code="control-drift",
        ended_at_utc="2026-07-15T12:00:01Z",
        duration_ns=1_000_000_000,
        evidence_valid=True,
        result_bundle_identity=None,
    )

    assert terminal["disposition"] == "not_started"

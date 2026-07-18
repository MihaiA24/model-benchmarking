from __future__ import annotations

from pathlib import Path

from model_benchmark.declarations.canonical import canonical_json_bytes
from model_benchmark.declarations.functional_v1 import FunctionalV1Manifest
from model_benchmark.declarations.identities import DigestKind, TypedDigest
from model_benchmark.runtime.functional_v1 import (
    CELL_SCHEDULE,
    FunctionalV1Home,
    RunWorkspace,
    _human_table,
)


_STARTED = "2026-07-15T12:00:00Z"
_ENDED = "2026-07-15T12:00:02Z"
_DETAILS: dict[str, object] = {
    "cost_usd": "0.12",
    "limitations": ["harbor-trial-log:not_produced"],
    "provider_requests": 3,
    "provider_tokens": 500,
    "score_vector": {
        "acceptance_score": 1,
        "regression_score": 1,
        "task_success": True,
    },
}


def _bundle_identity(cell_id: str) -> str:
    return str(TypedDigest.from_bytes(DigestKind.RESULT_BUNDLE, cell_id.encode()))


def _terminalize_all(
    workspace: RunWorkspace,
    details: dict[str, object] | None,
) -> None:
    for cell in CELL_SCHEDULE:
        cell_id = cell["cell_id"]
        workspace.write_cell_start(cell_id, started_at_utc=_STARTED)
        workspace.write_cell_terminal(
            cell_id,
            disposition="valid_completed",
            terminal_phase="cleanup",
            reason_code="completed",
            ended_at_utc=_ENDED,
            duration_ns=2_000_000_000,
            evidence_valid=True,
            result_bundle_identity=_bundle_identity(cell_id),
            details=details,
        )


def test_sealed_record_carries_enriched_cells_and_provenance(
    manifest_bundle: tuple[Path, dict[str, object]],
    tmp_path: Path,
) -> None:
    manifest = FunctionalV1Manifest.load(manifest_bundle[0])
    workspace = FunctionalV1Home(tmp_path / "home").create_workspace(manifest)
    _terminalize_all(workspace, _DETAILS)
    provenance = {
        "preflight_report_sha256": f"sha256:{'1' * 64}",
        "provisioning_manifest_identity": str(manifest.identity),
        "schema_version": 1,
    }
    (workspace.root / "provenance.json").write_bytes(canonical_json_bytes(provenance))

    sealed = workspace.seal()

    assert sealed.value["state"] == "complete"
    assert sealed.value["validity"] == "valid"
    assert sealed.value["provenance"] == provenance
    assert sealed.value["source_yaml_sha256"] == workspace.header["source_yaml_sha256"]
    planned = CELL_SCHEDULE[0]
    first = sealed.value["cells"][0]
    assert first["scenario"] == planned["scenario"]
    assert first["condition"] == planned["condition"]
    assert first["started_at_utc"] == _STARTED
    assert first["ended_at_utc"] == _ENDED
    assert first["duration_ns"] == 2_000_000_000
    assert first["reason_code"] == "completed"
    assert first["terminal_phase"] == "cleanup"
    assert first["scores"] == {
        "acceptance_score": 1,
        "regression_score": 1,
        "task_success": True,
    }
    assert first["score_vector"] == _DETAILS["score_vector"]
    assert first["provider_requests"] == 3
    assert first["provider_tokens"] == 500
    assert first["cost_usd"] == "0.12"
    assert first["limitations"] == ["harbor-trial-log:not_produced"]
    first_row = _human_table(sealed.value).splitlines()[1]
    assert first_row == (
        f"{planned['scenario']} | {planned['condition']} | valid_completed | "
        f"true | 1 | 1 | 2s | 3 | 500 | 0.12 | "
        f"{_bundle_identity(planned['cell_id'])}"
    )


def test_sealing_without_provenance_records_none(
    manifest_bundle: tuple[Path, dict[str, object]],
    tmp_path: Path,
) -> None:
    manifest = FunctionalV1Manifest.load(manifest_bundle[0])
    workspace = FunctionalV1Home(tmp_path / "home").create_workspace(manifest)
    _terminalize_all(workspace, _DETAILS)

    sealed = workspace.seal()

    assert sealed.value["state"] == "complete"
    assert sealed.value["validity"] == "valid"
    assert sealed.value["provenance"] is None


def test_empty_terminal_details_yield_null_scores_and_placeholders(
    manifest_bundle: tuple[Path, dict[str, object]],
    tmp_path: Path,
) -> None:
    manifest = FunctionalV1Manifest.load(manifest_bundle[0])
    workspace = FunctionalV1Home(tmp_path / "home").create_workspace(manifest)
    _terminalize_all(workspace, None)

    sealed = workspace.seal()

    planned = CELL_SCHEDULE[0]
    first = sealed.value["cells"][0]
    assert first["scores"] == {
        "acceptance_score": None,
        "regression_score": None,
        "task_success": None,
    }
    assert first["score_vector"] is None
    assert first["provider_requests"] is None
    assert first["provider_tokens"] is None
    assert first["cost_usd"] is None
    assert first["limitations"] == []
    first_row = _human_table(sealed.value).splitlines()[1]
    assert first_row == (
        f"{planned['scenario']} | {planned['condition']} | valid_completed | "
        f"- | - | - | 2s | - | - | - | "
        f"{_bundle_identity(planned['cell_id'])}"
    )

from __future__ import annotations

from pathlib import Path

import pytest

from model_benchmark.declarations.canonical import canonical_json_bytes
from model_benchmark.declarations.functional_v1 import FunctionalV1Manifest
from model_benchmark.declarations.identities import DigestKind, TypedDigest
from model_benchmark.runtime.execution import NativeFunctionalV1Runtime
from model_benchmark.runtime.functional_v1 import (
    CELL_SCHEDULE,
    FunctionalV1Home,
    FunctionalV1HomeError,
)


_TIMESTAMP = "2026-07-15T12:00:00Z"


def test_one_coordinator_and_provisioning_writer_are_mutually_exclusive(
    tmp_path: Path,
) -> None:
    home = FunctionalV1Home(tmp_path / "home")

    with home.coordinator_lease():
        with pytest.raises(FunctionalV1HomeError) as coordinator:
            home.coordinator_lease()
        with pytest.raises(FunctionalV1HomeError) as provisioning:
            home.provisioning_lease()

    assert coordinator.value.reason_code == "coordinator-lease-busy"
    assert provisioning.value.reason_code == "provisioning-lease-busy"

    with home.provisioning_lease():
        with pytest.raises(FunctionalV1HomeError) as coordinator:
            home.coordinator_lease()
    assert coordinator.value.reason_code == "provisioning-lease-busy"


def test_provisioned_inputs_are_content_addressed_and_immutable(
    manifest_bundle: tuple[Path, dict[str, object]],
    tmp_path: Path,
) -> None:
    manifest = FunctionalV1Manifest.load(manifest_bundle[0])
    home = FunctionalV1Home(tmp_path / "home")

    with home.provisioning_lease():
        home.store_manifest_inputs(manifest)
        home.store_manifest_inputs(manifest)
    home.verify_manifest_inputs(manifest)

    condition_data = manifest.condition_lock_bytes["omp"]
    identity = TypedDigest.from_bytes(DigestKind.FUNCTIONAL_V1_CONDITION, condition_data)
    stored = home.root / "inputs" / identity.kind.value / f"{identity.value}.json"
    stored.chmod(0o600)
    stored.write_bytes(b"corrupt")

    with pytest.raises(FunctionalV1HomeError) as captured:
        home.verify_manifest_inputs(manifest)
    assert captured.value.reason_code == "provisioned-input-mismatch"


def test_cell_start_and_terminal_records_are_one_attempt_write_once(
    manifest_bundle: tuple[Path, dict[str, object]],
    tmp_path: Path,
) -> None:
    manifest = FunctionalV1Manifest.load(manifest_bundle[0])
    home = FunctionalV1Home(tmp_path / "home")
    workspace = home.create_workspace(manifest)
    cell_id = CELL_SCHEDULE[0]["cell_id"]

    workspace.write_cell_start(cell_id, started_at_utc=_TIMESTAMP)
    with pytest.raises(FunctionalV1HomeError) as duplicate_start:
        workspace.write_cell_start(cell_id, started_at_utc=_TIMESTAMP)
    assert duplicate_start.value.reason_code == "immutable-write-conflict"

    bundle = str(TypedDigest.from_bytes(DigestKind.RESULT_BUNDLE, b"bundle"))
    workspace.write_cell_terminal(
        cell_id,
        disposition="valid_completed",
        terminal_phase="cleanup",
        reason_code="completed",
        ended_at_utc=_TIMESTAMP,
        duration_ns=1,
        evidence_valid=True,
        result_bundle_identity=bundle,
    )
    with pytest.raises(FunctionalV1HomeError) as duplicate_terminal:
        workspace.write_cell_terminal(
            cell_id,
            disposition="valid_completed",
            terminal_phase="cleanup",
            reason_code="completed",
            ended_at_utc=_TIMESTAMP,
            duration_ns=1,
            evidence_valid=True,
            result_bundle_identity=bundle,
        )
    assert duplicate_terminal.value.reason_code == "immutable-write-conflict"


def test_started_cell_must_be_terminalized_before_sealing(
    manifest_bundle: tuple[Path, dict[str, object]],
    tmp_path: Path,
) -> None:
    manifest = FunctionalV1Manifest.load(manifest_bundle[0])
    workspace = FunctionalV1Home(tmp_path / "home").create_workspace(manifest)
    workspace.write_cell_start(
        CELL_SCHEDULE[0]["cell_id"],
        started_at_utc=_TIMESTAMP,
    )

    with pytest.raises(FunctionalV1HomeError) as captured:
        workspace.seal()

    assert captured.value.reason_code == "unterminated-start-record"


def test_sealed_run_is_immutable_complete_and_path_independent(
    manifest_bundle: tuple[Path, dict[str, object]],
    tmp_path: Path,
) -> None:
    manifest = FunctionalV1Manifest.load(manifest_bundle[0])
    home = FunctionalV1Home(tmp_path / "machine-specific/home")
    workspace = home.create_workspace(manifest)

    for cell in CELL_SCHEDULE:
        cell_id = cell["cell_id"]
        workspace.write_cell_start(cell_id, started_at_utc=_TIMESTAMP)
        workspace.write_cell_terminal(
            cell_id,
            disposition="valid_completed",
            terminal_phase="cleanup",
            reason_code="completed",
            ended_at_utc=_TIMESTAMP,
            duration_ns=1,
            evidence_valid=True,
            result_bundle_identity=str(
                TypedDigest.from_bytes(DigestKind.RESULT_BUNDLE, cell_id.encode())
            ),
        )

    sealed = workspace.seal()

    assert sealed.identity.kind is DigestKind.FUNCTIONAL_V1_RUN_RECORD
    assert sealed.value["state"] == "complete"
    assert sealed.value["validity"] == "valid"
    assert sealed.value["unscheduled_cells"] == []
    assert str(home.root).encode() not in canonical_json_bytes(dict(sealed.value))
    assert home.sealed_run(workspace.run_id) == sealed
    inspected = NativeFunctionalV1Runtime(home).inspect(workspace.run_id)
    assert inspected.exit_code == 0
    assert inspected.human.startswith(
        "SCENARIO | CONDITION | DISPOSITION | TASK | ACCEPT | REGRESS | "
        "DURATION | REQUESTS | TOKENS | COST_USD | BUNDLE\n"
    )
    with pytest.raises(FunctionalV1HomeError) as duplicate_seal:
        workspace.seal()
    assert duplicate_seal.value.reason_code == "immutable-write-conflict"


def test_terminal_without_start_is_rejected(
    manifest_bundle: tuple[Path, dict[str, object]],
    tmp_path: Path,
) -> None:
    manifest = FunctionalV1Manifest.load(manifest_bundle[0])
    workspace = FunctionalV1Home(tmp_path / "home").create_workspace(manifest)

    with pytest.raises(FunctionalV1HomeError) as captured:
        workspace.write_cell_terminal(
            CELL_SCHEDULE[0]["cell_id"],
            disposition="invalid_infrastructure",
            terminal_phase="prelaunch",
            reason_code="control-drift",
            ended_at_utc=_TIMESTAMP,
            duration_ns=0,
            evidence_valid=False,
            result_bundle_identity=None,
        )

    assert captured.value.reason_code == "cell-not-started"

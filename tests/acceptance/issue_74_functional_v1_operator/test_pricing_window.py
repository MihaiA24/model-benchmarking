from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

import model_benchmark.runtime.execution as execution

from model_benchmark.declarations.canonical import canonical_json_bytes
from model_benchmark.declarations.functional_v1 import FunctionalV1Manifest
from model_benchmark.declarations.identities import DigestKind, TypedDigest
from model_benchmark.runtime.functional_v1 import FunctionalV1Home

_STAMP = "%Y-%m-%dT%H:%M:%SZ"
_EXPIRED_FROM = datetime(2025, 1, 1, tzinfo=UTC)
_EXPIRED_UNTIL = datetime(2025, 2, 1, tzinfo=UTC)


def _manifest_with_window(
    bundle: tuple[Path, dict[str, Any]],
    start: datetime,
    end: datetime,
) -> FunctionalV1Manifest:
    path, manifest = bundle
    pricing = dict(manifest["provider"]["pricing"])
    pricing["effective_from_utc"] = start.strftime(_STAMP)
    pricing["retrieved_at_utc"] = start.strftime(_STAMP)
    pricing["effective_until_utc"] = end.strftime(_STAMP)
    payload = {key: value for key, value in pricing.items() if key != "identity"}
    pricing["identity"] = str(
        TypedDigest.from_bytes(
            DigestKind.PRICING_RECORD, canonical_json_bytes(payload)
        )
    )
    manifest["provider"]["pricing"] = pricing
    path.write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return FunctionalV1Manifest.load(path)


def _forbid_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_docker(*arguments: object, **_: object) -> None:
        raise AssertionError(
            f"an expired pricing record must reject before docker: {arguments}"
        )

    monkeypatch.setattr(execution, "_docker", no_docker)


def test_run_rejects_expired_pricing_record_before_any_launch(
    manifest_bundle: tuple[Path, dict[str, Any]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The record is statically valid (retrieval inside its interval), so the
    # manifest loads; only the run-entry wall-clock gate may reject it.
    manifest = _manifest_with_window(manifest_bundle, _EXPIRED_FROM, _EXPIRED_UNTIL)
    _forbid_docker(monkeypatch)
    runtime = execution.NativeFunctionalV1Runtime(FunctionalV1Home(tmp_path / "home"))

    result = runtime.run(manifest)

    assert result.exit_code == 3
    assert result.payload["outcome"] == "rejected"
    assert result.payload["reason_code"] == "pricing-record-expired"
    assert "Run rejected before provider spend" in result.human


def test_pricing_gate_passes_within_the_effective_window(
    manifest_bundle: tuple[Path, dict[str, Any]],
) -> None:
    now = datetime.now(UTC)
    manifest = _manifest_with_window(
        manifest_bundle, now - timedelta(days=1), now + timedelta(days=1)
    )

    execution._check_pricing_window(manifest)


def test_resume_with_pending_cells_rejects_expired_pricing_record(
    manifest_bundle: tuple[Path, dict[str, Any]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A sealed run short-circuits to the inspect view before any manifest
    # handling and never reaches the gate; the pending-cell path re-executes
    # cells and spends provider money, so it must enforce the window.
    manifest = _manifest_with_window(manifest_bundle, _EXPIRED_FROM, _EXPIRED_UNTIL)
    home = FunctionalV1Home(tmp_path / "home")
    workspace = home.create_workspace(manifest)
    _forbid_docker(monkeypatch)
    monkeypatch.setattr(execution, "_cleanup_owned", lambda *_: None)
    monkeypatch.setattr(execution, "_resource_inventory", lambda *_: ())
    monkeypatch.setattr(
        execution,
        "_workspace_manifest",
        lambda *_: (manifest, tmp_path / "resume-root"),
    )
    runtime = execution.NativeFunctionalV1Runtime(home)

    result = runtime.resume(workspace.run_id)

    assert result.exit_code == 1
    assert result.payload["outcome"] == "rejected"
    assert result.payload["reason_code"] == "pricing-record-expired"

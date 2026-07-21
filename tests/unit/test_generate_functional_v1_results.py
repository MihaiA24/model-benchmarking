from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "generate-functional-v1-results"


def _record(run_id: str, manifest_hex: str) -> dict[str, object]:
    return {
        "cells": [
            {
                "cell_id": f"python--{condition}",
                "condition": condition,
                "cost_usd": "0.01",
                "disposition": "valid_completed",
                "duration_ns": 5_000_000_000,
                "evidence_valid": True,
                "provider_requests": 1,
                "provider_tokens": 100,
                "reason_code": "verifier-completed",
                "scenario": "python",
                "scores": {
                    "acceptance_score": 1,
                    "regression_score": 1,
                    "task_success": condition == "omp",
                },
            }
            for condition in ("omp", "raw-api")
        ],
        "manifest_identity": f"functional-v1-manifest:sha256:{manifest_hex}",
        "resolved_manifest_identity": f"resolved-v1-manifest:sha256:{manifest_hex}",
        "run_id": run_id,
        "schema_version": 1,
        "state": "complete",
        "validity": "valid",
    }


def _write_record(home: Path, run_id: str, manifest_hex: str) -> Path:
    path = home / "runs" / run_id / "run-record.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_record(run_id, manifest_hex)), encoding="utf-8")
    return path


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_discovers_runs_and_writes_one_readout_per_manifest(tmp_path: Path) -> None:
    home = tmp_path / "home"
    first_hex, second_hex = "a" * 64, "c" * 64
    _write_record(home, "run-a", first_hex)
    _write_record(home, "run-c", second_hex)
    output = home / "reports"
    output.mkdir(parents=True)
    stale = output / f"readout-{'d' * 64}.json"
    stale.write_text("stale", encoding="utf-8")
    note = output / "operator-notes.txt"
    note.write_text("keep", encoding="utf-8")

    completed = _run("--home", str(home), "--title", "Campaign")

    assert completed.returncode == 0, completed.stderr
    output = home / "reports"
    assert not stale.exists()
    assert note.read_text(encoding="utf-8") == "keep"
    assert (output / "dashboard.html").read_text().startswith("<!doctype html>")
    assert "Cross-version comparison" in (output / "dashboard.html").read_text()
    for manifest_hex in (first_hex, second_hex):
        payload = json.loads(
            (output / f"readout-{manifest_hex}.json").read_text(encoding="utf-8")
        )
        assert payload["authority"] == "none"
        assert (output / f"readout-{manifest_hex}.md").is_file()


def test_rejects_unsafe_manifest_identity_before_writing(tmp_path: Path) -> None:
    home = tmp_path / "home"
    record = _write_record(home, "run-a", "a" * 64)
    document = json.loads(record.read_text(encoding="utf-8"))
    document["manifest_identity"] = "../../outside"
    record.write_text(json.dumps(document), encoding="utf-8")
    output = tmp_path / "reports"

    completed = _run(str(record), "--output", str(output))

    assert completed.returncode == 2
    assert "invalid manifest_identity" in completed.stderr
    assert not output.exists()

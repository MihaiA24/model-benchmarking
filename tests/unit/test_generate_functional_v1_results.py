from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "generate-functional-v1-results"
_CONDITIONS = ("omp", "opencode", "hermes", "raw-api")
_SCENARIOS = (
    "python-sales-by-genre",
    "spring-petvalidator-whitespace",
    "angular-reading-time",
    "react-author-filter",
)


def _record(run_id: str, manifest_hex: str) -> dict[str, object]:
    return {
        "cells": [
            {
                "cell_id": f"{index:02d}-{scenario}-{condition}",
                "condition": condition,
                "cost_usd": "0.01",
                "disposition": "valid_completed",
                "duration_ns": 5_000_000_000,
                "evidence_valid": True,
                "provider_requests": 1,
                "provider_tokens": 100,
                "reason_code": "verifier-completed",
                "result_bundle_identity": "result-bundle:sha256:" + "d" * 64,
                "scenario": scenario,
                "scores": {
                    "acceptance_score": 1,
                    "regression_score": 1,
                    "task_success": condition == "omp",
                },
            }
            for index, (scenario, condition) in enumerate(
                ((scenario, condition) for scenario in _SCENARIOS for condition in _CONDITIONS),
                start=1,
            )
        ],
        "manifest_identity": f"functional-v1-manifest:sha256:{manifest_hex}",
        "resolved_manifest_identity": f"resolved-v1-manifest:sha256:{manifest_hex}",
        "run_id": run_id,
        "schema_version": 1,
        "state": "complete",
        "unscheduled_cells": [],
        "validity": "valid",
    }


def _write_record(home: Path, run_id: str, manifest_hex: str) -> Path:
    path = home / "runs" / run_id / "run-record.json"
    path.parent.mkdir(parents=True)
    data = (json.dumps(_record(run_id, manifest_hex), sort_keys=True) + "\n").encode()
    path.write_bytes(data)
    identity = "functional-v1-run-record:sha256:" + hashlib.sha256(data).hexdigest()
    path.with_suffix(".identity").write_text(identity + "\n", encoding="ascii")
    return path


def _reseal_record(path: Path, value: dict[str, object]) -> None:
    data = (json.dumps(value, sort_keys=True) + "\n").encode()
    path.write_bytes(data)
    identity = "functional-v1-run-record:sha256:" + hashlib.sha256(data).hexdigest()
    path.with_suffix(".identity").write_text(identity + "\n", encoding="ascii")


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


def test_rejects_tampered_run_record_before_writing(tmp_path: Path) -> None:
    home = tmp_path / "home"
    record = _write_record(home, "run-a", "a" * 64)
    document = json.loads(record.read_text(encoding="utf-8"))
    document["manifest_identity"] = "../../outside"
    record.write_text(json.dumps(document), encoding="utf-8")
    output = tmp_path / "reports"

    completed = _run(str(record), "--output", str(output))

    assert completed.returncode == 2
    assert "Run Record identity does not match its bytes" in completed.stderr
    assert not output.exists()


def test_rejects_run_record_without_adjacent_identity(tmp_path: Path) -> None:
    home = tmp_path / "home"
    record = _write_record(home, "run-a", "a" * 64)
    record.with_suffix(".identity").unlink()
    output = tmp_path / "reports"

    completed = _run(str(record), "--output", str(output))

    assert completed.returncode == 2
    assert "cannot read sealed Run Record" in completed.stderr
    assert not output.exists()


def test_rejects_rehashed_incomplete_schedule_before_writing(tmp_path: Path) -> None:
    home = tmp_path / "home"
    record = _write_record(home, "run-a", "a" * 64)
    document = json.loads(record.read_text(encoding="utf-8"))
    document["cells"].pop()
    _reseal_record(record, document)
    output = tmp_path / "reports"

    completed = _run(str(record), "--output", str(output))

    assert completed.returncode == 2
    assert "exact 16-cell schedule" in completed.stderr
    assert not output.exists()


def test_rejects_rehashed_duplicate_schedule_cell_before_writing(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    record = _write_record(home, "run-a", "a" * 64)
    document = json.loads(record.read_text(encoding="utf-8"))
    document["cells"][-1] = dict(document["cells"][0])
    _reseal_record(record, document)
    output = tmp_path / "reports"

    completed = _run(str(record), "--output", str(output))

    assert completed.returncode == 2
    assert "schedule identity mismatch" in completed.stderr
    assert not output.exists()

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.readout import (  # noqa: E402
    ReadoutError,
    build_readout,
    main,
    render_markdown,
)


_CONDITIONS = ("omp", "opencode", "hermes", "raw-api")
_SCENARIOS = ("python", "spring", "angular")


def _cell(
    scenario: str,
    condition: str,
    *,
    task_success: object = False,
    regression: object = 1,
    cost: object = "0.01",
    tokens: object = 1000,
) -> dict[str, object]:
    return {
        "cell_id": f"{scenario}--{condition}",
        "condition": condition,
        "cost_usd": cost,
        "disposition": "valid_completed",
        "duration_ns": 5_000_000_000,
        "evidence_valid": True,
        "provider_requests": 3,
        "provider_tokens": tokens,
        "reason_code": "verifier-completed",
        "scenario": scenario,
        "scores": {
            "acceptance_score": 1,
            "regression_score": regression,
            "task_success": task_success,
        },
    }


def _record(
    run_id: str,
    *,
    successes: dict[tuple[str, str], object] | None = None,
    manifest: str = "functional-v1-manifest:sha256:" + "a" * 64,
) -> dict[str, object]:
    lookup = successes or {}
    return {
        "cells": [
            _cell(
                scenario,
                condition,
                task_success=lookup.get((scenario, condition), False),
            )
            for scenario in _SCENARIOS
            for condition in _CONDITIONS
        ],
        "manifest_identity": manifest,
        "resolved_manifest_identity": "resolved-v1-manifest:sha256:" + "b" * 64,
        "run_id": run_id,
        "schema_version": 1,
        "state": "complete",
        "validity": "valid",
    }


def _write(tmp_path: Path, name: str, record: dict[str, object]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
    return path


def _three_runs(tmp_path: Path) -> list[Path]:
    # omp succeeds on python in every run; opencode succeeds on python in
    # one run; everything else fails -> omp-vs-opencode discordance 2:0
    # over 9 blocks.
    paths = []
    for index in range(3):
        successes: dict[tuple[str, str], object] = {("python", "omp"): True}
        if index == 0:
            successes[("python", "opencode")] = True
        paths.append(
            _write(
                tmp_path,
                f"run-{index}.json",
                _record(f"0198-run-{index}", successes=successes),
            )
        )
    return paths


def test_pooled_pair_discordance_and_difference(tmp_path: Path) -> None:
    readout = build_readout(_three_runs(tmp_path))

    assert readout["block_count"] == 9
    assert readout["claims"] == "none"
    pair = next(
        item
        for item in readout["pairs"]
        if (item["a"], item["b"]) == ("omp", "opencode")
    )
    task = pair["task_success"]
    assert (task["n10"], task["n01"], task["n11"]) == (2, 0, 1)
    assert task["a_successes"] == 3 and task["b_successes"] == 1
    assert task["difference_pp"] == pytest.approx(200 / 9, abs=1e-6)
    low, high = task["interval_95_pp"]
    assert low <= task["difference_pp"] <= high


def test_six_pairs_cover_the_baseline_arm(tmp_path: Path) -> None:
    readout = build_readout(_three_runs(tmp_path))

    labels = {(pair["a"], pair["b"]) for pair in readout["pairs"]}
    assert len(labels) == 6
    assert ("omp", "raw-api") in labels
    assert readout["conditions"] == ["hermes", "omp", "opencode", "raw-api"]


def test_output_bytes_are_deterministic(tmp_path: Path) -> None:
    paths = _three_runs(tmp_path)

    first = build_readout(paths)
    second = build_readout(paths)

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert render_markdown(first) == render_markdown(second)


def test_mixed_manifests_are_refused(tmp_path: Path) -> None:
    first = _write(tmp_path, "a.json", _record("0198-a"))
    second = _write(
        tmp_path,
        "b.json",
        _record(
            "0198-b", manifest="functional-v1-manifest:sha256:" + "c" * 64
        ),
    )

    with pytest.raises(ReadoutError, match="different manifests"):
        build_readout([first, second])


def test_invalid_or_incomplete_records_are_refused(tmp_path: Path) -> None:
    record = _record("0198-a")
    record["validity"] = "invalid"
    path = _write(tmp_path, "invalid.json", record)

    with pytest.raises(ReadoutError, match="complete, valid"):
        build_readout([path])


def test_duplicate_run_ids_are_refused(tmp_path: Path) -> None:
    first = _write(tmp_path, "a.json", _record("0198-a"))
    second = _write(tmp_path, "b.json", _record("0198-a"))

    with pytest.raises(ReadoutError, match="duplicate run_id"):
        build_readout([first, second])


def test_missing_task_success_counts_as_failure_and_is_disclosed(
    tmp_path: Path,
) -> None:
    record = _record("0198-a")
    record["cells"][0]["scores"]["task_success"] = None
    path = _write(tmp_path, "a.json", record)

    readout = build_readout([path])

    assert readout["data_quality"]["missing_task_success"] == 1
    scenario = record["cells"][0]["scenario"]
    condition = record["cells"][0]["condition"]
    entry = readout["per_scenario_task_success"][scenario][condition]
    assert entry == {"runs": 1, "successes": 0}


def test_markdown_carries_pairs_scenarios_and_disclaimer(tmp_path: Path) -> None:
    readout = build_readout(_three_runs(tmp_path))

    rendered = render_markdown(readout)

    assert "diagnostic - no claims" in rendered
    assert "omp vs opencode" in rendered
    assert "| python |" in rendered
    assert "counted as failures" in rendered


def test_token_advisory_is_derived_in_json_and_markdown(tmp_path: Path) -> None:
    record = _record("0198-warning")
    cell = record["cells"][0]
    cell["provider_tokens"] = 100_001
    path = _write(tmp_path, "warning.json", record)

    readout = build_readout([path])
    rendered = render_markdown(readout)

    assert readout["warnings"] == [
        {
            "cell_id": cell["cell_id"],
            "code": "provider-token-advisory-threshold-exceeded",
            "condition": cell["condition"],
            "provider_tokens": 100_001,
            "run_id": "0198-warning",
            "scenario": cell["scenario"],
            "threshold": 100_000,
        }
    ]
    assert "## Token warnings" in rendered
    assert "provider-token-advisory-threshold-exceeded" in rendered


def test_cli_writes_deterministic_json(tmp_path: Path) -> None:
    paths = _three_runs(tmp_path)
    first_out = tmp_path / "first.json"
    second_out = tmp_path / "second.json"

    assert main([*map(str, paths), "--json", str(first_out)]) == 0
    assert main([*map(str, paths), "--json", str(second_out)]) == 0

    assert first_out.read_bytes() == second_out.read_bytes()
    payload = json.loads(first_out.read_text(encoding="utf-8"))
    assert payload["schema"] == "measurement-readout-v1"
    assert payload["authority"] == "none"


def test_cli_reports_refusals_with_exit_2(tmp_path: Path) -> None:
    record = _record("0198-a")
    record["state"] = "incomplete"
    path = _write(tmp_path, "a.json", record)

    assert main([str(path)]) == 2

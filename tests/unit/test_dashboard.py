from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.dashboard import (  # noqa: E402
    DashboardError,
    build_dashboard,
    main,
)


_CONDITIONS = ("omp", "opencode", "hermes", "raw-api")
_SCENARIOS = ("python", "spring", "angular")


def _cell(
    scenario: str,
    condition: str,
    *,
    task_success: object = False,
) -> dict[str, object]:
    return {
        "cell_id": f"{scenario}--{condition}",
        "condition": condition,
        "cost_usd": "0.01",
        "disposition": "valid_completed",
        "duration_ns": 5_000_000_000,
        "evidence_valid": True,
        "provider_requests": 3,
        "provider_tokens": 1000,
        "reason_code": "verifier-completed",
        "scenario": scenario,
        "scores": {
            "acceptance_score": 1,
            "regression_score": 1,
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


def _two_runs(tmp_path: Path, manifest: str | None = None) -> list[Path]:
    keywords = {} if manifest is None else {"manifest": manifest}
    return [
        _write(
            tmp_path,
            f"run-{index}-{(manifest or 'a')[-8:]}.json",
            _record(
                f"0198-{(manifest or 'a')[-8:]}-{index}",
                successes={("python", "omp"): True},
                **keywords,
            ),
        )
        for index in range(2)
    ]


def test_page_carries_banner_runs_matrix_and_pairs(tmp_path: Path) -> None:
    page = build_dashboard(_two_runs(tmp_path), "Results")

    assert "no claims" in page
    assert "0198-a-0" in page and "0198-a-1" in page
    for condition in _CONDITIONS:
        assert f"<th>{condition}</th>" in page
    # omp succeeded on python in both runs: matrix entry 2/2 exists.
    assert ">2/2<" in page
    assert "omp vs opencode" in page
    assert "<summary>All cells</summary>" in page


def test_versions_render_as_one_section_per_manifest(tmp_path: Path) -> None:
    first = _two_runs(tmp_path, "functional-v1-manifest:sha256:" + "a" * 64)
    second = _two_runs(tmp_path, "functional-v1-manifest:sha256:" + "c" * 64)

    page = build_dashboard(first + second, "Results")

    assert "Version 1:" in page and "Version 2:" in page
    assert page.count("Paired contrasts") == 2
    assert ("a" * 64) in page and ("c" * 64) in page


def test_charts_render_as_inline_svg_per_version(tmp_path: Path) -> None:
    page = build_dashboard(_two_runs(tmp_path), "Results")

    # Rate bars + whisker chart, all inline SVG, zero JavaScript.
    assert page.count("<svg ") == 2
    assert "Task-success rate by condition" in page
    assert "Paired task-success differences" in page
    assert "<script" not in page
    # omp pooled 2/2 on python out of 6 blocks -> labeled 2/6 (33%).
    assert "2/6 (33%)" in page
    assert 'class="legend"' in page


def test_cross_version_comparison_appears_only_with_two_versions(
    tmp_path: Path,
) -> None:
    first = _two_runs(tmp_path, "functional-v1-manifest:sha256:" + "a" * 64)

    single = build_dashboard(first, "Results")
    assert "Cross-version comparison" not in single

    second = _two_runs(tmp_path, "functional-v1-manifest:sha256:" + "c" * 64)
    page = build_dashboard(first + second, "Results")

    assert "Cross-version comparison" in page
    assert "display-only" in page
    assert "omp · v1" in page and "omp · v2" in page
    assert 'href="#comparison"' in page


def test_presentation_template_elements_render(tmp_path: Path) -> None:
    page = build_dashboard(_two_runs(tmp_path), "Results")

    # Fixed brand nav with breadcrumb separators and an overview hero.
    assert "<nav>" in page and '<span class="sep">›</span>' in page
    assert 'class="hero"' in page and 'href="#overview"' in page
    assert '<div class="tag">Diagnostic · no claims</div>' in page
    # Hero stat strip totals: 2 runs x 12 cells, 24 requests, 24000 tokens.
    assert ">sealed runs<" in page and ">24000<" in page
    # Sealed runs wear green state chips; dispositions are class-colored.
    assert 'class="chip chip-green">complete/valid' in page
    assert 'class="ok">valid_completed' in page
    # The banner is a warn callout; viewport meta present for mobile.
    assert 'class="callout warn"' in page
    assert 'name="viewport"' in page


def test_hostile_record_fields_are_escaped(tmp_path: Path) -> None:
    record = _record("0198-a", manifest="functional-v1-manifest:sha256:" + "a" * 64)
    record["cells"][0]["reason_code"] = "<script>alert(1)</script>"  # type: ignore[index]
    path = _write(tmp_path, "hostile.json", record)

    page = build_dashboard([path], "<Results>")

    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "<title>&lt;Results&gt;</title>" in page


def test_output_bytes_are_deterministic(tmp_path: Path) -> None:
    paths = _two_runs(tmp_path)

    assert build_dashboard(paths, "Results") == build_dashboard(paths, "Results")


def test_invalid_records_are_refused_without_output(tmp_path: Path) -> None:
    record = _record("0198-a")
    record["validity"] = "invalid"
    path = _write(tmp_path, "invalid.json", record)
    output = tmp_path / "dashboard.html"

    assert main([str(path), "--output", str(output)]) == 2
    assert not output.exists()


def test_unreadable_input_is_a_dashboard_error(tmp_path: Path) -> None:
    path = tmp_path / "not-json.json"
    path.write_text("not json", encoding="utf-8")

    with pytest.raises(DashboardError):
        build_dashboard([path], "Results")


def test_cli_writes_the_page(tmp_path: Path) -> None:
    paths = _two_runs(tmp_path)
    output = tmp_path / "dashboard.html"

    assert main([*map(str, paths), "--output", str(output)]) == 0
    page = output.read_text(encoding="utf-8")
    assert page.startswith("<!doctype html>")
    assert "authority: none" in page

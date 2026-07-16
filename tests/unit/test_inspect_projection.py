from __future__ import annotations

from model_benchmark.runtime.functional_v1 import CELL_SCHEDULE, _human_table


_HEADER = (
    "SCENARIO | CONDITION | DISPOSITION | TASK | ACCEPT | REGRESS | "
    "DURATION | REQUESTS | TOKENS | COST_USD | BUNDLE"
)
_BUNDLE = f"result-bundle:sha256:{'0' * 64}"


def _enriched_cell() -> dict[str, object]:
    planned = CELL_SCHEDULE[0]
    return {
        "cell_id": planned["cell_id"],
        "condition": planned["condition"],
        "cost_usd": "0.12",
        "disposition": "valid_completed",
        "duration_ns": 2_000_000_000,
        "provider_requests": 3,
        "provider_tokens": 500,
        "result_bundle_identity": _BUNDLE,
        "scenario": planned["scenario"],
        "scores": {
            "acceptance_score": 1,
            "regression_score": 0,
            "task_success": True,
        },
    }


def test_enriched_cell_renders_every_column_with_real_values() -> None:
    cell = _enriched_cell()

    lines = _human_table({"cells": [cell]}).splitlines()

    assert lines[0] == _HEADER
    assert lines[1] == (
        f"{cell['scenario']} | {cell['condition']} | valid_completed | "
        f"true | 1 | 0 | 2s | 3 | 500 | 0.12 | {_BUNDLE}"
    )


def test_sparse_legacy_cell_renders_placeholders() -> None:
    planned = CELL_SCHEDULE[0]

    lines = _human_table(
        {
            "cells": [
                {
                    "cell_id": planned["cell_id"],
                    "disposition": "not_started",
                    "result_bundle_identity": None,
                }
            ]
        }
    ).splitlines()

    assert lines[1] == (
        f"{planned['scenario']} | {planned['condition']} | not_started | "
        "- | - | - | - | - | - | - | -"
    )


def test_header_line_matches_the_fixed_contract() -> None:
    assert _human_table({}) == (
        "SCENARIO | CONDITION | DISPOSITION | TASK | ACCEPT | REGRESS | "
        "DURATION | REQUESTS | TOKENS | COST_USD | BUNDLE"
    )


def test_record_without_cell_list_renders_header_only() -> None:
    assert _human_table({"cells": "not-a-list"}) == _HEADER
    assert _human_table({"run_id": "abc"}) == _HEADER

from __future__ import annotations

import runpy
from collections.abc import Callable

from types import SimpleNamespace
from typing import Any, cast

from decimal import Decimal
from pathlib import Path

import pytest

import model_benchmark.runtime.campaign_budget as campaign_budget

from model_benchmark.declarations.functional_v1 import FunctionalV1Manifest
from model_benchmark.runtime.campaign_budget import (
    CampaignBudgetError,
    _Rates,
    _rates_at,
    _sealed_cost,
    worst_case_run_cost_usd,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("manifest_name", "context_tokens", "output_tokens", "expected"),
    [
        (
            "functional-v1-manifest.yaml",
            1_000_000,
            384_000,
            Decimal("5.64032"),
        ),
        (
            "functional-v1-hy3.yaml",
            256_000,
            64_000,
            Decimal("4.64736"),
        ),
        (
            "functional-v1-minimax-m3.yaml",
            1_000_000,
            131_072,
            Decimal("21.8331648"),
        ),
    ],
)
def test_worst_case_run_bound_includes_one_full_response_overshoot(
    manifest_name: str,
    context_tokens: int,
    output_tokens: int,
    expected: Decimal,
) -> None:
    manifest = FunctionalV1Manifest.load(_REPOSITORY_ROOT / manifest_name)

    assert (
        worst_case_run_cost_usd(
            manifest,
            context_tokens=context_tokens,
            output_tokens=output_tokens,
        )
        == expected
    )


def test_pricing_tier_switch_is_strictly_greater_than_its_threshold() -> None:
    base = _Rates(Decimal("0.30"), Decimal("1.20"), Decimal("0.06"))
    high = _Rates(Decimal("0.60"), Decimal("2.40"), Decimal("0.12"))

    assert _rates_at(base, [(512_000, high)], 512_000) == base
    assert _rates_at(base, [(512_000, high)], 512_001) == high


def test_sealed_cost_requires_a_complete_per_cell_ledger() -> None:
    cells = [{"cost_usd": "0.10"} for _ in range(16)]
    record = {"cells": cells, "state": "complete", "validity": "valid"}

    assert _sealed_cost(record, "run-id") == Decimal("1.60")

    cells[0] = {"cost_usd": None}
    with pytest.raises(CampaignBudgetError, match="canonical decimal"):
        _sealed_cost(record, "run-id")


def _qualified_manifests() -> tuple[campaign_budget._QualifiedManifest, ...]:
    catalog_limits = {
        "functional-v1-manifest.yaml": (1_000_000, 384_000),
        "functional-v1-hy3.yaml": (256_000, 64_000),
        "functional-v1-minimax-m3.yaml": (1_000_000, 131_072),
    }
    return tuple(
        campaign_budget._QualifiedManifest(
            manifest=FunctionalV1Manifest.load(_REPOSITORY_ROOT / name),
            catalog={
                "catalog_context_tokens": catalog_limits[name][0],
                "catalog_output_tokens": catalog_limits[name][1],
            },
        )
        for name in campaign_budget.CAMPAIGN_MANIFESTS
    )


def _state(
    item: campaign_budget._QualifiedManifest,
    *,
    run_id: str,
    cell_cost: str | None,
) -> campaign_budget._RunState:
    record = (
        None
        if cell_cost is None
        else {
            "cells": [{"cost_usd": cell_cost} for _ in range(16)],
            "state": "complete",
            "validity": "valid",
        }
    )
    return campaign_budget._RunState(
        run_id=run_id,
        manifest_identity=str(item.manifest.identity),
        record=record,
        record_identity=(
            None if record is None else "functional-v1-run-record:sha256:" + "0" * 64
        ),
    )


def _status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    states: tuple[campaign_budget._RunState, ...],
) -> dict[str, object]:
    qualified = _qualified_manifests()
    monkeypatch.setattr(
        campaign_budget,
        "_load_qualified_manifests",
        lambda *_: ("dry-launch-qualification:sha256:" + "0" * 64, qualified),
    )
    monkeypatch.setattr(campaign_budget, "_run_states", lambda *_: states)
    return campaign_budget.campaign_status(
        project_root=_REPOSITORY_ROOT,
        home_path=tmp_path / "home",
        qualification_path=tmp_path / "qualification.json",
    )


def test_empty_campaign_starts_with_deepseek(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    status = _status(monkeypatch, tmp_path, ())

    assert status["action"] == "start"
    assert status["manifest"] == "functional-v1-manifest.yaml"
    assert status["candidate_worst_case_cost_usd"] == "5.64032"


def test_interrupted_campaign_resumes_the_same_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    qualified = _qualified_manifests()
    states = (_state(qualified[0], run_id="deepseek-run", cell_cost=None),)

    status = _status(monkeypatch, tmp_path, states)

    assert status["action"] == "resume"
    assert status["run_id"] == "deepseek-run"


@pytest.mark.parametrize(
    ("prior_cell_cost", "expected_action"),
    [("0.01", "start"), ("0.10", "blocked")],
)
def test_minimax_gate_uses_sealed_prior_cost_plus_its_full_bound(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    prior_cell_cost: str,
    expected_action: str,
) -> None:
    qualified = _qualified_manifests()
    states = (
        _state(qualified[0], run_id="deepseek-run", cell_cost=prior_cell_cost),
        _state(qualified[1], run_id="hy3-run", cell_cost=prior_cell_cost),
    )

    status = _status(monkeypatch, tmp_path, states)

    assert status["action"] == expected_action
    assert status["manifest"] == "functional-v1-minimax-m3.yaml"
    assert status["candidate_worst_case_cost_usd"] == "21.8331648"


def _failed_state(
    item: campaign_budget._QualifiedManifest,
    *,
    run_id: str,
    disposition: str = "invalid_infrastructure",
    cell_cost: str | None = None,
) -> campaign_budget._RunState:
    record = {
        "cells": [
            {
                "cell_id": campaign_budget.CELL_SCHEDULE[0]["cell_id"],
                "cost_usd": cell_cost,
                "disposition": disposition,
                "evidence_valid": False,
                "result_bundle_identity": None,
            }
        ],
        "state": "incomplete",
        "validity": "invalid",
    }
    return campaign_budget._RunState(
        run_id=run_id,
        manifest_identity=str(item.manifest.identity),
        record=record,
        record_identity="functional-v1-run-record:sha256:" + "1" * 64,
    )


def test_infrastructure_failure_requires_an_explicit_budgeted_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    qualified = _qualified_manifests()
    failed = _failed_state(qualified[0], run_id="failed-deepseek")

    status = _status(monkeypatch, tmp_path, (failed,))

    assert status["action"] == "retry"
    assert status["reason_code"] == "infrastructure-retry-required"
    assert status["failed_run_id"] == "failed-deepseek"
    assert status["cumulative_cost_usd"] == "0.35252"
    assert status["projected_max_cost_usd"] == "5.99284"
    attempts = status["infrastructure_attempts"]
    assert isinstance(attempts, list)
    assert attempts[0]["charged_cost_usd"] == "0.35252"


def test_approved_infrastructure_retry_resumes_its_new_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    qualified = _qualified_manifests()
    states = (
        _failed_state(qualified[0], run_id="failed-deepseek"),
        _state(qualified[0], run_id="replacement-deepseek", cell_cost=None),
    )

    status = _status(monkeypatch, tmp_path, states)

    assert status["action"] == "resume"
    assert status["run_id"] == "replacement-deepseek"
    assert status["cumulative_cost_usd"] == "0.35252"


def test_infrastructure_retry_is_blocked_when_its_full_bound_no_longer_fits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    qualified = _qualified_manifests()
    states = (
        _state(qualified[0], run_id="deepseek-run", cell_cost="0.10"),
        _state(qualified[1], run_id="hy3-run", cell_cost="0.10"),
        _failed_state(qualified[2], run_id="failed-minimax"),
    )

    status = _status(monkeypatch, tmp_path, states)

    assert status["action"] == "blocked"
    assert status["reason_code"] == "campaign-ceiling-insufficient"
    assert status["failed_run_id"] == "failed-minimax"
    assert status["cumulative_cost_usd"] == "4.5645728"
    assert status["projected_max_cost_usd"] == "26.3977376"


def test_non_infrastructure_invalid_run_is_never_retried(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    qualified = _qualified_manifests()
    failed = _failed_state(
        qualified[0], run_id="integrity-failure", disposition="invalid_integrity"
    )

    with pytest.raises(CampaignBudgetError, match="not eligible"):
        _status(monkeypatch, tmp_path, (failed,))


def _campaign_script() -> dict[str, Any]:
    namespace = runpy.run_path(
        str(_REPOSITORY_ROOT / "scripts/run-functional-v1-campaign.py"),
        run_name="campaign_runner_test",
    )
    main: Any = namespace["main"]
    return cast(dict[str, Any], main.__globals__)


def test_campaign_runner_does_not_retry_infrastructure_without_approval(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = _campaign_script()
    status = {
        "action": "retry",
        "failed_run_id": "failed-run",
        "manifest": "functional-v1-manifest.yaml",
    }
    runner_calls: list[object] = []
    monkeypatch.setitem(script, "_status", lambda *_: status)
    monkeypatch.setitem(script, "_emit", lambda *_: None)
    monkeypatch.setattr(
        script["subprocess"], "run", lambda *_args, **_kwargs: runner_calls.append(True)
    )
    main = cast(Callable[[list[str] | None], int], script["main"])

    exit_code = main(
        [
            "--home",
            str(tmp_path / "home"),
            "--qualification",
            str(tmp_path / "qualification.json"),
        ]
    )

    assert exit_code == 3
    assert runner_calls == []


def test_campaign_runner_starts_one_explicitly_approved_replacement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = _campaign_script()
    statuses = iter(
        (
            {
                "action": "retry",
                "failed_run_id": "failed-run",
                "manifest": "functional-v1-manifest.yaml",
            },
            {"action": "complete", "completed_runs": []},
        )
    )
    runner_calls: list[tuple[list[str], dict[str, str]]] = []

    def run(
        command: list[str], *, cwd: Path, env: dict[str, str], check: bool
    ) -> SimpleNamespace:
        assert cwd == _REPOSITORY_ROOT
        assert check is False
        runner_calls.append((command, env))
        return SimpleNamespace(returncode=0)

    monkeypatch.setitem(script, "_status", lambda *_: next(statuses))
    monkeypatch.setitem(script, "_emit", lambda *_: None)
    monkeypatch.setattr(script["subprocess"], "run", run)
    main = cast(Callable[[list[str] | None], int], script["main"])

    exit_code = main(
        [
            "--home",
            str(tmp_path / "home"),
            "--qualification",
            str(tmp_path / "qualification.json"),
            "--approve-infrastructure-retry",
            "failed-run",
        ]
    )

    assert exit_code == 0
    assert len(runner_calls) == 1
    command, environment = runner_calls[0]
    assert command == [str(_REPOSITORY_ROOT / "scripts/run-functional-v1")]
    assert environment["MODEL_BENCHMARK_MANIFEST"] == str(
        _REPOSITORY_ROOT / "functional-v1-manifest.yaml"
    )

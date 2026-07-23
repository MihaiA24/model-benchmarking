from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from model_benchmark.declarations.canonical import (
    canonical_json_bytes,
    load_canonical_json,
)
from model_benchmark.declarations.functional_v1 import FunctionalV1Manifest
from model_benchmark.runtime.dry_launch_qualification import inspect_qualification
from model_benchmark.runtime.functional_v1 import (
    CELL_SCHEDULE,
    VALID_COMMAND_DISPOSITIONS,
    FunctionalV1Home,
    FunctionalV1HomeError,
)

CAMPAIGN_CEILING_USD = Decimal("25.00")
CAMPAIGN_MANIFESTS = (
    "functional-v1-manifest.yaml",
    "functional-v1-hy3.yaml",
    "functional-v1-minimax-m3.yaml",
)
_MILLION = Decimal(1_000_000)
_CELL_IDS = frozenset(str(cell["cell_id"]) for cell in CELL_SCHEDULE)


class CampaignBudgetError(ValueError):
    """A paid Campaign cannot proceed from authoritative local state."""


@dataclass(frozen=True)
class _Rates:
    input: Decimal
    output: Decimal
    cache_read: Decimal

    @property
    def maximum(self) -> Decimal:
        return max(self.input, self.output, self.cache_read)


@dataclass(frozen=True)
class _QualifiedManifest:
    manifest: FunctionalV1Manifest
    catalog: Mapping[str, object]


@dataclass(frozen=True)
class _RunState:
    run_id: str
    manifest_identity: str
    record: Mapping[str, object] | None
    record_identity: str | None


@dataclass(frozen=True)
class _AttemptGroup:
    active: _RunState | None
    retries: tuple[tuple[_RunState, Decimal], ...]
    valid: _RunState | None


def _decimal(value: object, *, label: str) -> Decimal:
    if not isinstance(value, str):
        raise CampaignBudgetError(f"{label} is not a canonical decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise CampaignBudgetError(f"{label} is not a decimal") from error
    if not parsed.is_finite() or parsed < 0 or format(parsed, "f") != value:
        raise CampaignBudgetError(f"{label} is not a canonical non-negative decimal")
    return parsed


def _rates(value: Mapping[str, object], *, prefix: str = "") -> _Rates:
    return _Rates(
        input=_decimal(
            value[f"{prefix}input_usd_per_million_tokens"],
            label="input pricing",
        ),
        output=_decimal(
            value[f"{prefix}output_usd_per_million_tokens"],
            label="output pricing",
        ),
        cache_read=_decimal(
            value[f"{prefix}cache_read_usd_per_million_tokens"],
            label="cache-read pricing",
        ),
    )


def _tiered_rates(pricing: Mapping[str, object]) -> list[tuple[int, _Rates]]:
    raw_tiers = pricing.get("tiers")
    if not isinstance(raw_tiers, list):
        raise CampaignBudgetError("manifest pricing tiers are malformed")
    tiers: list[tuple[int, _Rates]] = []
    for raw_tier in raw_tiers:
        if not isinstance(raw_tier, Mapping):
            raise CampaignBudgetError("manifest pricing tier is malformed")
        threshold = raw_tier.get("input_tokens_gt")
        if (
            not isinstance(threshold, int)
            or isinstance(threshold, bool)
            or threshold <= 0
        ):
            raise CampaignBudgetError("manifest pricing tier threshold is malformed")
        tiers.append((threshold, _rates(raw_tier)))
    return tiers


def _rates_at(
    base: _Rates, tiers: Sequence[tuple[int, _Rates]], input_tokens: int
) -> _Rates:
    selected = base
    for threshold, rates in tiers:
        if input_tokens <= threshold:
            break
        selected = rates
    return selected


def worst_case_run_cost_usd(
    manifest: FunctionalV1Manifest,
    *,
    context_tokens: int,
    output_tokens: int,
) -> Decimal:
    """Bound one 16-cell Run, including one full-response proxy overshoot."""
    if any(
        not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0
        for limit in (context_tokens, output_tokens)
    ):
        raise CampaignBudgetError("catalog model limits must be positive integers")
    provider = manifest.value.get("provider")
    limits = manifest.value.get("limits")
    if not isinstance(provider, Mapping) or not isinstance(limits, Mapping):
        raise CampaignBudgetError("manifest provider or limits projection is malformed")
    pricing = provider.get("pricing")
    if not isinstance(pricing, Mapping):
        raise CampaignBudgetError("manifest pricing projection is malformed")
    base = _rates(pricing)
    tiers = _tiered_rates(pricing)
    provider_tokens = limits.get("provider_tokens_per_trial")
    if (
        not isinstance(provider_tokens, int)
        or isinstance(provider_tokens, bool)
        or provider_tokens <= 0
    ):
        raise CampaignBudgetError("provider token threshold is malformed")
    stop_after_cost = _decimal(
        limits.get("stop_after_cost_usd_per_trial"),
        label="per-Trial cost threshold",
    )

    pre_response_rates = [base]
    pre_response_rates.extend(
        rates for threshold, rates in tiers if threshold < provider_tokens
    )
    token_stop_bound = (
        Decimal(provider_tokens)
        * max(rates.maximum for rates in pre_response_rates)
        / _MILLION
    )
    pre_response_bound = min(stop_after_cost, token_stop_bound)

    final_rates = _rates_at(base, tiers, context_tokens)
    final_input_rate = max(final_rates.input, final_rates.cache_read)
    final_response_bound = (
        Decimal(context_tokens) * final_input_rate
        + Decimal(output_tokens) * final_rates.output
    ) / _MILLION
    return (pre_response_bound + final_response_bound) * Decimal(len(CELL_SCHEDULE))


def _load_qualified_manifests(
    project_root: Path, qualification_path: Path
) -> tuple[str, tuple[_QualifiedManifest, ...]]:
    inspected = inspect_qualification(qualification_path)
    raw = load_canonical_json(qualification_path.read_bytes())
    if not isinstance(raw, dict):
        raise CampaignBudgetError("qualification record is not an object")
    catalog_validation = raw.get("catalog_validation")
    if not isinstance(catalog_validation, Mapping):
        raise CampaignBudgetError("qualification catalog validation is absent")
    catalog_digest = catalog_validation.get("catalog_document_sha256")
    entries = catalog_validation.get("manifests")
    if not isinstance(catalog_digest, str) or not isinstance(entries, list):
        raise CampaignBudgetError("qualification catalog projection is malformed")
    entries_by_name = {
        entry.get("manifest"): entry
        for entry in entries
        if isinstance(entry, Mapping) and isinstance(entry.get("manifest"), str)
    }

    qualified: list[_QualifiedManifest] = []
    for name in CAMPAIGN_MANIFESTS:
        manifest = FunctionalV1Manifest.load(project_root / name)
        entry = entries_by_name.get(name)
        if not isinstance(entry, Mapping):
            raise CampaignBudgetError(f"qualification does not cover {name}")
        provider = manifest.value["provider"]
        if not isinstance(provider, Mapping):
            raise CampaignBudgetError(f"provider projection is malformed for {name}")
        pricing = provider["pricing"]
        if not isinstance(pricing, Mapping):
            raise CampaignBudgetError(f"pricing projection is malformed for {name}")
        expected = {
            "base_url": provider["base_url"],
            "manifest_identity": str(manifest.identity),
            "model": provider["model"],
            "pricing_identity": pricing["identity"],
            "pricing_source_snapshot_sha256": catalog_digest,
            "resolved_manifest_identity": str(manifest.resolved_identity),
            "source_yaml_sha256": manifest.source_yaml_sha256,
            "status": "passed",
        }
        if any(entry.get(field) != value for field, value in expected.items()):
            raise CampaignBudgetError(f"qualification is stale for {name}")
        context_tokens = entry.get("catalog_context_tokens")
        output_tokens = entry.get("catalog_output_tokens")
        if any(
            not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0
            for limit in (context_tokens, output_tokens)
        ):
            raise CampaignBudgetError(
                f"qualified catalog limits are invalid for {name}"
            )
        qualified.append(_QualifiedManifest(manifest=manifest, catalog=entry))
    return str(inspected["identity"]), tuple(qualified)


def _run_states(
    home: FunctionalV1Home, expected_identities: set[str]
) -> tuple[_RunState, ...]:
    runs_root = home.root / "runs"
    if not runs_root.exists():
        return ()
    states: list[_RunState] = []
    for path in sorted(runs_root.iterdir(), key=lambda item: item.name):
        if not path.is_dir() or path.is_symlink():
            raise CampaignBudgetError(
                f"unexpected entry in Campaign run home: {path.name}"
            )
        try:
            workspace = home.workspace(path.name)
        except FunctionalV1HomeError as error:
            raise CampaignBudgetError(str(error)) from error
        manifest_identity = str(workspace.header["manifest_identity"])
        if manifest_identity not in expected_identities:
            raise CampaignBudgetError(
                f"Campaign home contains an unrelated Run: {path.name}"
            )
        record_path = workspace.root / "run-record.json"
        identity_path = workspace.root / "run-record.identity"
        if record_path.exists() != identity_path.exists():
            raise CampaignBudgetError(f"Run sealing is ambiguous: {path.name}")
        record: Mapping[str, object] | None = None
        record_identity: str | None = None
        if record_path.exists():
            try:
                sealed = workspace.sealed_record()
            except FunctionalV1HomeError as error:
                raise CampaignBudgetError(str(error)) from error
            record = sealed.value
            record_identity = str(sealed.identity)
        states.append(
            _RunState(
                run_id=path.name,
                manifest_identity=manifest_identity,
                record=record,
                record_identity=record_identity,
            )
        )
    return tuple(states)


def _sealed_cost(record: Mapping[str, object], run_id: str) -> Decimal:
    if record.get("state") != "complete" or record.get("validity") != "valid":
        raise CampaignBudgetError(f"Run is not complete and valid: {run_id}")
    cells = record.get("cells")
    if not isinstance(cells, list) or len(cells) != len(CELL_SCHEDULE):
        raise CampaignBudgetError(f"Run cost ledger is incomplete: {run_id}")
    total = Decimal(0)
    for cell in cells:
        if not isinstance(cell, Mapping):
            raise CampaignBudgetError(f"Run cost ledger is malformed: {run_id}")
        total += _decimal(cell.get("cost_usd"), label=f"Run {run_id} cell cost")
    return total


def _retry_cell_cost(
    cell: object, run_id: str, *, per_cell_bound: Decimal
) -> tuple[str, Decimal, bool]:
    if not isinstance(cell, Mapping):
        raise CampaignBudgetError(f"Run cost ledger is malformed: {run_id}")
    cell_id = cell.get("cell_id")
    if not isinstance(cell_id, str) or cell_id not in _CELL_IDS:
        raise CampaignBudgetError(f"Run cell ledger is malformed: {run_id}")

    disposition = cell.get("disposition")
    is_infrastructure_failure = disposition == "invalid_infrastructure"
    if disposition in VALID_COMMAND_DISPOSITIONS:
        if cell.get("evidence_valid") is not True or not isinstance(
            cell.get("result_bundle_identity"), str
        ):
            raise CampaignBudgetError(
                f"Run has non-infrastructure-invalid evidence: {run_id}"
            )
    elif not is_infrastructure_failure:
        raise CampaignBudgetError(
            f"Run is not eligible for an infrastructure retry: {run_id}"
        )

    raw_cost = cell.get("cost_usd")
    if raw_cost is None:
        if not is_infrastructure_failure:
            raise CampaignBudgetError(f"Run cost ledger is incomplete: {run_id}")
        cost = per_cell_bound
    else:
        cost = _decimal(raw_cost, label=f"Run {run_id} cell cost")
    return cell_id, cost, is_infrastructure_failure


def _infrastructure_retry_cost(
    record: Mapping[str, object], run_id: str, *, per_cell_bound: Decimal
) -> Decimal | None:
    if record.get("state") == "complete" and record.get("validity") == "valid":
        return None
    if record.get("state") != "incomplete" or record.get("validity") != "invalid":
        raise CampaignBudgetError(f"Run state is malformed: {run_id}")
    cells = record.get("cells")
    if not isinstance(cells, list) or not 1 <= len(cells) <= len(CELL_SCHEDULE):
        raise CampaignBudgetError(f"Run cost ledger is incomplete: {run_id}")

    seen_ids: set[str] = set()
    saw_infrastructure_failure = False
    total = Decimal(0)
    for cell in cells:
        cell_id, cost, failed = _retry_cell_cost(
            cell, run_id, per_cell_bound=per_cell_bound
        )
        if cell_id in seen_ids:
            raise CampaignBudgetError(f"Run cell ledger is malformed: {run_id}")
        seen_ids.add(cell_id)
        total += cost
        saw_infrastructure_failure = saw_infrastructure_failure or failed
    if not saw_infrastructure_failure:
        raise CampaignBudgetError(
            f"Run is not eligible for an infrastructure retry: {run_id}"
        )
    return total


def _validate_run_order(
    states: Sequence[_RunState], identity_order: Mapping[str, int]
) -> None:
    last_index = -1
    for state in states:
        state_index = identity_order[state.manifest_identity]
        if state_index < last_index:
            raise CampaignBudgetError("Campaign run order is invalid")
        last_index = state_index


def _attempt_group(
    group: Sequence[_RunState], *, per_cell_bound: Decimal
) -> _AttemptGroup:
    active = [state for state in group if state.record is None]
    if len(active) > 1 or (active and active[0] is not group[-1]):
        raise CampaignBudgetError("Campaign has ambiguous active Runs")

    valid: list[_RunState] = []
    retries: list[tuple[_RunState, Decimal]] = []
    for state in group:
        if state.record is None:
            continue
        retry_cost = _infrastructure_retry_cost(
            state.record, state.run_id, per_cell_bound=per_cell_bound
        )
        if retry_cost is None:
            valid.append(state)
        else:
            retries.append((state, retry_cost))
    if len(valid) > 1 or (valid and valid[0] is not group[-1]):
        raise CampaignBudgetError("Campaign contains duplicate model Runs")
    if active and valid:
        raise CampaignBudgetError("Campaign run order is invalid")
    return _AttemptGroup(
        active=active[0] if active else None,
        retries=tuple(retries),
        valid=valid[0] if valid else None,
    )


def campaign_status(
    *,
    project_root: Path,
    home_path: Path,
    qualification_path: Path,
) -> dict[str, object]:
    project_root = project_root.resolve()
    qualification_path = qualification_path.resolve()
    qualification_identity, qualified = _load_qualified_manifests(
        project_root, qualification_path
    )
    identity_order = {
        str(item.manifest.identity): index for index, item in enumerate(qualified)
    }
    states = _run_states(FunctionalV1Home(home_path), set(identity_order))
    _validate_run_order(states, identity_order)
    grouped = {
        identity: [state for state in states if state.manifest_identity == identity]
        for identity in identity_order
    }

    cumulative = Decimal(0)
    completed: list[dict[str, object]] = []
    infrastructure_attempts: list[dict[str, object]] = []
    for index, item in enumerate(qualified):
        identity = str(item.manifest.identity)
        group = grouped[identity]
        later_identities = {
            str(later.manifest.identity) for later in qualified[index + 1 :]
        }
        later_runs_exist = any(
            state.manifest_identity in later_identities for state in states
        )
        context_tokens = int(item.catalog["catalog_context_tokens"])
        output_tokens = int(item.catalog["catalog_output_tokens"])
        bound = worst_case_run_cost_usd(
            item.manifest,
            context_tokens=context_tokens,
            output_tokens=output_tokens,
        )
        per_cell_bound = bound / Decimal(len(CELL_SCHEDULE))

        attempts = _attempt_group(group, per_cell_bound=per_cell_bound)
        if attempts.valid is None and later_runs_exist:
            raise CampaignBudgetError("Campaign run order is invalid")

        for state, retry_cost in attempts.retries:
            cumulative += retry_cost
            infrastructure_attempts.append(
                {
                    "charged_cost_usd": format(retry_cost, "f"),
                    "manifest": item.manifest.source_path.name,
                    "model": item.manifest.value["provider"]["model"],
                    "run_id": state.run_id,
                    "run_record_identity": state.record_identity,
                }
            )
        if cumulative > CAMPAIGN_CEILING_USD:
            raise CampaignBudgetError("Campaign ceiling has already been exceeded")

        if attempts.valid is not None:
            state = attempts.valid
            assert state.record is not None
            cost = _sealed_cost(state.record, state.run_id)
            cumulative += cost
            if cumulative > CAMPAIGN_CEILING_USD:
                raise CampaignBudgetError("Campaign ceiling has already been exceeded")
            completed.append(
                {
                    "cost_usd": format(cost, "f"),
                    "manifest": item.manifest.source_path.name,
                    "model": item.manifest.value["provider"]["model"],
                    "run_id": state.run_id,
                    "run_record_identity": state.record_identity,
                }
            )
            continue

        projected = cumulative + bound
        common = {
            "campaign_ceiling_usd": format(CAMPAIGN_CEILING_USD, "f"),
            "candidate_worst_case_cost_usd": format(bound, "f"),
            "completed_runs": completed,
            "cumulative_cost_usd": format(cumulative, "f"),
            "infrastructure_attempts": infrastructure_attempts,
            "manifest": item.manifest.source_path.name,
            "model": item.manifest.value["provider"]["model"],
            "projected_max_cost_usd": format(projected, "f"),
            "qualification_identity": qualification_identity,
        }
        if attempts.active is not None:
            action = "resume" if projected <= CAMPAIGN_CEILING_USD else "blocked"
            return {
                **common,
                "action": action,
                "reason_code": (
                    None if action == "resume" else "campaign-ceiling-insufficient"
                ),
                "run_id": attempts.active.run_id,
            }
        if attempts.retries:
            action = "retry" if projected <= CAMPAIGN_CEILING_USD else "blocked"
            return {
                **common,
                "action": action,
                "failed_run_id": attempts.retries[-1][0].run_id,
                "reason_code": (
                    "infrastructure-retry-required"
                    if action == "retry"
                    else "campaign-ceiling-insufficient"
                ),
                "run_id": None,
            }
        action = "start" if projected <= CAMPAIGN_CEILING_USD else "blocked"
        return {
            **common,
            "action": action,
            "reason_code": (
                None if action == "start" else "campaign-ceiling-insufficient"
            ),
            "run_id": None,
        }

    return {
        "action": "complete",
        "campaign_ceiling_usd": format(CAMPAIGN_CEILING_USD, "f"),
        "completed_runs": completed,
        "cumulative_cost_usd": format(cumulative, "f"),
        "infrastructure_attempts": infrastructure_attempts,
        "qualification_identity": qualification_identity,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect and gate the fixed three-model paid Campaign"
    )
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--qualification", required=True, type=Path)
    arguments = parser.parse_args(argv)
    try:
        result = campaign_status(
            project_root=arguments.project_root,
            home_path=arguments.home,
            qualification_path=arguments.qualification,
        )
    except (CampaignBudgetError, FunctionalV1HomeError, OSError, ValueError) as error:
        result = {
            "action": "blocked",
            "message": str(error),
            "reason_code": "campaign-state-invalid",
        }
        print(canonical_json_bytes(result).decode("utf-8"))
        return 2
    print(canonical_json_bytes(result).decode("utf-8"))
    return 0 if result["action"] != "blocked" else 3


if __name__ == "__main__":
    raise SystemExit(main())

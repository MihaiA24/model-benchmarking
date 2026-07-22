"""Paired, no-claims diagnostic readout over sealed Functional V1 Run Records.

Measurement MVP (#104): N repeated runs of one sealed manifest are N
replicates of three matched blocks — each scenario runs all four
Conditions under identical manifest, model, worker, and budgets. This
tool consumes the sealed ``run-record.json`` files and emits paired
per-Condition contrasts. It is stdlib-only and imports nothing from the
runtime tree, so it runs anywhere the JSON files are and lands outside
every proof closure.

It is diagnostic by decree: no ``supported`` claims, no multiplicity
control, no claim states. The frozen production margins (blueprint/
repetition-counts-and-precision-targets.md) appear as reference
annotations only. Identical inputs produce identical output bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from decimal import Decimal, InvalidOperation
from itertools import combinations
from pathlib import Path


VALID_DISPOSITIONS = frozenset(
    {"valid_completed", "valid_harness_outcome", "valid_limit_outcome"}
)
REFERENCE_MARGINS = {
    "regression_harm_pp": -5,
    "task_success_worthwhile_pp": 10,
}
BOOTSTRAP_RESAMPLES = 10_000
_NUMERIC_ENDPOINTS = (
    ("regression_score", "score"),
    ("acceptance_score", "score"),
    ("cost_usd", "cost"),
    ("provider_tokens", "count"),
    ("duration_seconds", "duration"),
)
PROVIDER_TOKENS_ADVISORY_THRESHOLD = 100_000
PROVIDER_TOKENS_ADVISORY_CODE = "provider-token-advisory-threshold-exceeded"


class ReadoutError(ValueError):
    """The readout inputs are unusable or mutually inconsistent."""


def _load_record(path: Path) -> dict[str, object]:
    try:
        data = path.read_bytes()
        value = json.loads(data)
    except (OSError, ValueError) as error:
        raise ReadoutError(f"cannot read Run Record {path}: {error}") from error
    if not isinstance(value, dict):
        raise ReadoutError(f"{path}: Run Record is not an object")
    if value.get("schema_version") != 1:
        raise ReadoutError(f"{path}: unsupported Run Record schema")
    if value.get("state") != "complete" or value.get("validity") != "valid":
        raise ReadoutError(
            f"{path}: only complete, valid Run Records are readable "
            f"(state={value.get('state')!r}, validity={value.get('validity')!r})"
        )
    cells = value.get("cells")
    if not isinstance(cells, list) or not cells:
        raise ReadoutError(f"{path}: Run Record has no cells")
    for cell in cells:
        if not isinstance(cell, dict):
            raise ReadoutError(f"{path}: malformed cell record")
        if (
            cell.get("disposition") not in VALID_DISPOSITIONS
            or cell.get("evidence_valid") is not True
        ):
            raise ReadoutError(
                f"{path}: cell {cell.get('cell_id')!r} is not a valid terminal"
            )
    return {
        "digest": "functional-v1-run-record:sha256:"
        + hashlib.sha256(data).hexdigest(),
        "path": str(path),
        "value": value,
    }


def _consistent(records: list[dict[str, object]]) -> tuple[str, str]:
    manifests = {str(record["value"]["manifest_identity"]) for record in records}
    resolved = {
        str(record["value"].get("resolved_manifest_identity"))
        for record in records
    }
    if len(manifests) != 1 or len(resolved) != 1:
        raise ReadoutError(
            "Run Records span different manifests; paired contrasts require "
            f"one condition set (manifests: {sorted(manifests)})"
        )
    run_ids = [str(record["value"]["run_id"]) for record in records]
    if len(set(run_ids)) != len(run_ids):
        raise ReadoutError("duplicate run_id across inputs")
    return manifests.pop(), resolved.pop()


def _blocks(
    records: list[dict[str, object]],
) -> tuple[tuple[str, ...], tuple[str, ...], dict[tuple[str, str], dict[str, dict]]]:
    conditions: set[str] = set()
    scenarios: set[str] = set()
    blocks: dict[tuple[str, str], dict[str, dict]] = {}
    for record in records:
        run_id = str(record["value"]["run_id"])
        for cell in record["value"]["cells"]:
            condition = str(cell["condition"])
            scenario = str(cell["scenario"])
            conditions.add(condition)
            scenarios.add(scenario)
            block = blocks.setdefault((run_id, scenario), {})
            if condition in block:
                raise ReadoutError(
                    f"run {run_id} has duplicate {scenario}/{condition} cells"
                )
            block[condition] = cell
    expected = tuple(sorted(conditions))
    for (run_id, scenario), block in sorted(blocks.items()):
        if tuple(sorted(block)) != expected:
            raise ReadoutError(
                f"run {run_id} scenario {scenario} is missing conditions"
            )
    return expected, tuple(sorted(scenarios)), blocks


def _success(cell: dict[str, object]) -> bool:
    scores = cell.get("scores")
    return isinstance(scores, dict) and scores.get("task_success") is True


def _missing_success(cell: dict[str, object]) -> bool:
    scores = cell.get("scores")
    return not isinstance(scores, dict) or scores.get("task_success") is None


def _token_warnings(records: list[dict[str, object]]) -> list[dict[str, object]]:
    warnings: list[dict[str, object]] = []
    for record in records:
        value = record["value"]
        run_id = value["run_id"]
        for cell in value["cells"]:
            provider_tokens = cell.get("provider_tokens")
            if (
                isinstance(provider_tokens, int)
                and not isinstance(provider_tokens, bool)
                and provider_tokens > PROVIDER_TOKENS_ADVISORY_THRESHOLD
            ):
                warnings.append(
                    {
                        "cell_id": cell.get("cell_id"),
                        "code": PROVIDER_TOKENS_ADVISORY_CODE,
                        "condition": cell.get("condition"),
                        "provider_tokens": provider_tokens,
                        "run_id": run_id,
                        "scenario": cell.get("scenario"),
                        "threshold": PROVIDER_TOKENS_ADVISORY_THRESHOLD,
                    }
                )
    return warnings


def _endpoint_value(cell: dict[str, object], endpoint: str) -> float | None:
    if endpoint in {"regression_score", "acceptance_score"}:
        scores = cell.get("scores")
        value = scores.get(endpoint) if isinstance(scores, dict) else None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)
    if endpoint == "cost_usd":
        value = cell.get("cost_usd")
        if value is None:
            return None
        try:
            return float(Decimal(str(value)))
        except (InvalidOperation, ValueError):
            return None
    if endpoint == "provider_tokens":
        value = cell.get("provider_tokens")
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return float(value)
    if endpoint == "duration_seconds":
        value = cell.get("duration_ns")
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value / 1_000_000_000
    raise ReadoutError(f"unknown endpoint {endpoint!r}")


def _seed(run_digests: list[str], label: str) -> int:
    basis = "|".join(sorted(run_digests)) + "|" + label
    return int.from_bytes(hashlib.sha256(basis.encode()).digest()[:8], "big")


def _bootstrap_interval(
    values: list[float], seed: int, scale: float = 1.0
) -> list[float] | None:
    if len(values) < 2:
        return None
    generator = random.Random(seed)
    count = len(values)
    means = sorted(
        sum(generator.choice(values) for _ in range(count)) / count
        for _ in range(BOOTSTRAP_RESAMPLES)
    )

    def percentile(q: float) -> float:
        position = q * (len(means) - 1)
        low = int(position)
        high = min(low + 1, len(means) - 1)
        weight = position - low
        return means[low] * (1 - weight) + means[high] * weight

    return [
        round(percentile(0.025) * scale, 6),
        round(percentile(0.975) * scale, 6),
    ]


def _pair_analysis(
    first: str,
    second: str,
    blocks: dict[tuple[str, str], dict[str, dict]],
    run_digests: list[str],
) -> dict[str, object]:
    keys = sorted(blocks)
    label = f"{first}-vs-{second}"
    counts = {"n00": 0, "n01": 0, "n10": 0, "n11": 0}
    success_diffs: list[float] = []
    first_successes = 0
    second_successes = 0
    for key in keys:
        a = _success(blocks[key][first])
        b = _success(blocks[key][second])
        first_successes += a
        second_successes += b
        counts[f"n{int(a)}{int(b)}"] += 1
        success_diffs.append(float(a) - float(b))
    analysis: dict[str, object] = {
        "a": first,
        "b": second,
        "blocks": len(keys),
        "task_success": {
            "a_successes": first_successes,
            "b_successes": second_successes,
            **counts,
            "difference_pp": round(
                (counts["n10"] - counts["n01"]) * 100 / len(keys), 6
            ),
            "interval_95_pp": _bootstrap_interval(
                success_diffs, _seed(run_digests, label + "|task_success"), 100
            ),
        },
    }
    for endpoint, _ in _NUMERIC_ENDPOINTS:
        deltas: list[float] = []
        missing = 0
        for key in keys:
            a_value = _endpoint_value(blocks[key][first], endpoint)
            b_value = _endpoint_value(blocks[key][second], endpoint)
            if a_value is None or b_value is None:
                missing += 1
                continue
            deltas.append(a_value - b_value)
        analysis[endpoint] = {
            "blocks": len(deltas),
            "interval_95": _bootstrap_interval(
                deltas, _seed(run_digests, label + "|" + endpoint)
            ),
            "mean_difference": (
                round(sum(deltas) / len(deltas), 6) if deltas else None
            ),
            "missing_blocks": missing,
        }
    return analysis


def build_readout(paths: list[Path]) -> dict[str, object]:
    if not paths:
        raise ReadoutError("at least one run-record.json path is required")
    records = [_load_record(path) for path in paths]
    manifest_identity, resolved_identity = _consistent(records)
    conditions, scenarios, blocks = _blocks(records)
    run_digests = [str(record["digest"]) for record in records]
    warnings = _token_warnings(records)
    pairs = [
        _pair_analysis(first, second, blocks, run_digests)
        for first, second in combinations(conditions, 2)
    ]
    per_scenario: dict[str, dict[str, dict[str, int]]] = {}
    missing_task_success = 0
    for (run_id, scenario), block in sorted(blocks.items()):
        del run_id
        for condition, cell in sorted(block.items()):
            entry = per_scenario.setdefault(scenario, {}).setdefault(
                condition, {"runs": 0, "successes": 0}
            )
            entry["runs"] += 1
            entry["successes"] += _success(cell)
            missing_task_success += _missing_success(cell)
    return {
        "authority": "none",
        "block_count": len(blocks),
        "claims": "none",
        "conditions": list(conditions),
        "data_quality": {
            "cells": sum(len(block) for block in blocks.values()),
            "missing_task_success": missing_task_success,
        },
        "inputs": [
            {
                "digest": record["digest"],
                "path": record["path"],
                "run_id": str(record["value"]["run_id"]),
            }
            for record in records
        ],
        "manifest_identity": manifest_identity,
        "pairs": pairs,
        "per_scenario_task_success": per_scenario,
        "reference_margins": REFERENCE_MARGINS,
        "resolved_manifest_identity": resolved_identity,
        "scenarios": list(scenarios),
        "schema": "measurement-readout-v1",
        "settings": {
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
            "seed_basis": "sha256(sorted run digests | pair | endpoint)",
        },
        "warnings": warnings,
    }


def _interval_text(interval: list[float] | None, unit: str = "") -> str:
    if interval is None:
        return "-"
    return f"[{interval[0]:+.2f}, {interval[1]:+.2f}]{unit}"


def render_markdown(readout: dict[str, object]) -> str:
    lines = [
        "# Measurement readout (diagnostic - no claims)",
        "",
        f"Manifest: `{readout['manifest_identity']}`",
        f"Blocks: {readout['block_count']} "
        f"(runs x scenarios; conditions: {', '.join(readout['conditions'])})",
        "",
        "Reference margins (production decisions, annotation only): "
        f"task_success +/-{readout['reference_margins']['task_success_worthwhile_pp']} pp, "
        f"regression harm {readout['reference_margins']['regression_harm_pp']} pp.",
        "",
        "## Inputs",
        "",
    ]
    for entry in readout["inputs"]:
        lines.append(f"- `{entry['run_id']}` `{entry['digest']}`")
    if readout["warnings"]:
        lines += ["", "## Token warnings", ""]
        for warning in readout["warnings"]:
            lines.append(
                f"- `{warning['run_id']}` `{warning['cell_id']}` "
                f"{warning['scenario']}/{warning['condition']}: "
                f"{warning['provider_tokens']} > {warning['threshold']} "
                f"(`{warning['code']}`)"
            )
    lines += [
        "",
        "## Paired contrasts (a vs b, pooled over blocks)",
        "",
        "| pair | blocks | success a:b | discordant n10:n01 | diff pp [95%] |"
        " d regression [95%] | d cost USD [95%] | d duration s [95%] |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for pair in readout["pairs"]:
        task = pair["task_success"]
        regression = pair["regression_score"]
        cost = pair["cost_usd"]
        duration = pair["duration_seconds"]
        lines.append(
            f"| {pair['a']} vs {pair['b']} | {pair['blocks']} "
            f"| {task['a_successes']}:{task['b_successes']} "
            f"| {task['n10']}:{task['n01']} "
            f"| {task['difference_pp']:+.1f} {_interval_text(task['interval_95_pp'])} "
            f"| {regression['mean_difference'] if regression['mean_difference'] is not None else '-'} "
            f"{_interval_text(regression['interval_95'])} "
            f"| {cost['mean_difference'] if cost['mean_difference'] is not None else '-'} "
            f"{_interval_text(cost['interval_95'])} "
            f"| {duration['mean_difference'] if duration['mean_difference'] is not None else '-'} "
            f"{_interval_text(duration['interval_95'])} |"
        )
    lines += ["", "## Task success by scenario (successes/runs)", ""]
    conditions = list(readout["conditions"])
    lines.append("| scenario | " + " | ".join(conditions) + " |")
    lines.append("|---|" + "---|" * len(conditions))
    for scenario, per_condition in sorted(
        readout["per_scenario_task_success"].items()
    ):
        row = [
            f"{per_condition[c]['successes']}/{per_condition[c]['runs']}"
            for c in conditions
        ]
        lines.append(f"| {scenario} | " + " | ".join(row) + " |")
    quality = readout["data_quality"]
    lines += [
        "",
        f"Data quality: {quality['cells']} valid cells; "
        f"{quality['missing_task_success']} without a task_success score "
        "(counted as failures per the valid-cell estimand).",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Paired diagnostic readout over sealed Functional V1 Run Records"
        ),
    )
    parser.add_argument("records", nargs="+", type=Path)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--markdown", type=Path, default=None)
    arguments = parser.parse_args(argv)
    try:
        readout = build_readout(list(arguments.records))
    except ReadoutError as error:
        print(f"readout failed: {error}", file=sys.stderr)
        return 2
    payload = json.dumps(readout, sort_keys=True, separators=(",", ":")) + "\n"
    rendered = render_markdown(readout)
    if arguments.json is not None:
        arguments.json.write_text(payload, encoding="utf-8")
    if arguments.markdown is not None:
        arguments.markdown.write_text(rendered, encoding="utf-8")
    if arguments.json is None and arguments.markdown is None:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

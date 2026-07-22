"""Static, no-claims results dashboard over sealed Functional V1 Run Records.

One self-contained HTML page from ``run-record.json`` paths (issue #109).
Records are grouped by ``manifest_identity`` — the benchmark's version key —
and every group is validated and analyzed by ``scripts/readout.py``'s
``build_readout`` (same fail-closed rules, same statistics); the dashboard
adds presentation only: a hero summary, tables, inline-SVG charts, and a
display-only cross-version comparison of observed rates. stdlib-only, zero
JavaScript, deterministic output bytes, every record field escaped.

Human-friendly version names come from an optional ``--names`` JSON file
mapping a manifest-identity prefix (>= 8 hex chars, with or without the
``functional-v1-manifest:sha256:`` prefix) to a display label::

    {"57e2ba7a": "deepseek-v4-flash — July campaign"}

Named versions show their label everywhere; runs render as "Run N". The
sealed identities are never dropped — every version carries a collapsed
"Internal identities" drawer with the full manifest, resolved-manifest,
run-id, and record digests, so traceability to the sealed evidence stays
one click away.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

try:  # imported as scripts.dashboard (tests) or executed from scripts/
    from scripts.readout import ReadoutError, build_readout
except ImportError:  # pragma: no cover - script-execution fallback
    from readout import ReadoutError, build_readout


_BANNER = "Diagnostic readout — no claims. Reference margins are annotation only."
_PAIR_ENDPOINTS = (
    ("regression_score", "Δ regression [95%]", ""),
    ("cost_usd", "Δ cost USD [95%]", ""),
    ("duration_seconds", "Δ duration s [95%]", " s"),
)
_KNOWN_COLORS = {
    "omp": "#2e86de",
    "opencode": "#d97706",
    "hermes": "#16a34a",
    "raw-api": "#8b5cf6",
}
_EXTRA_COLORS = ("#e15759", "#76b7b2", "#edc948", "#b07aa1")
_DISPOSITION_CLASS = {
    "valid_completed": "ok",
    "valid_limit_outcome": "warn",
    "valid_harness_outcome": "na",
}
_MIN_NAME_KEY_HEX = 8
_CHART_WIDTH = 720
_CHART_GUTTER = 190
_BAR_HEIGHT = 22
_BAR_GAP = 8


class DashboardError(ValueError):
    """The dashboard inputs are unusable."""


# --------------------------------------------------------------------------
# loading


def _load_value(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DashboardError(f"unreadable run record {path}: {error}") from error
    if not isinstance(value, dict) or not isinstance(
        value.get("manifest_identity"), str
    ):
        raise DashboardError(f"{path} is not a Run Record object")
    return value


def _grouped(paths: list[Path]) -> list[tuple[str, list[Path], list[dict[str, object]]]]:
    groups: dict[str, tuple[list[Path], list[dict[str, object]]]] = {}
    order: list[str] = []
    for path in paths:
        value = _load_value(path)
        manifest = str(value["manifest_identity"])
        if manifest not in groups:
            groups[manifest] = ([], [])
            order.append(manifest)
        groups[manifest][0].append(path)
        groups[manifest][1].append(value)
    return [(manifest, *groups[manifest]) for manifest in order]


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return Decimal(0)


# --------------------------------------------------------------------------
# version naming (presentation-only; sealed identities stay in the page)


def _identity_hex(identity: str) -> str:
    return identity.rsplit(":", 1)[-1]


def _load_names(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DashboardError(f"unreadable names file {path}: {error}") from error
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(label, str) and label.strip()
        for key, label in value.items()
    ):
        raise DashboardError(
            f"{path} must map manifest-identity prefixes to non-empty labels"
        )
    return {key: str(label).strip() for key, label in value.items()}


def _resolve_names(names: dict[str, str], manifests: list[str]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for key, label in names.items():
        key_hex = _identity_hex(key.strip())
        if len(key_hex) < _MIN_NAME_KEY_HEX:
            raise DashboardError(
                f"names key needs at least {_MIN_NAME_KEY_HEX} hex characters: {key!r}"
            )
        matches = [
            manifest
            for manifest in manifests
            if _identity_hex(manifest).startswith(key_hex)
        ]
        if not matches:
            raise DashboardError(f"names key matches no input manifest: {key!r}")
        if len(matches) > 1:
            raise DashboardError(f"names key is ambiguous: {key!r}")
        if matches[0] in resolved:
            raise DashboardError(f"manifest named twice: {matches[0]}")
        resolved[matches[0]] = label
    return resolved


class _Version:
    """Presentation bundle for one manifest identity."""

    def __init__(
        self,
        index: int,
        manifest: str,
        label: str | None,
        readout: dict[str, object],
        records: list[dict[str, object]],
    ) -> None:
        self.index = index
        self.manifest = manifest
        self.label = label
        self.readout = readout
        self.records = records
        self.totals = _version_totals(readout, records)

    @property
    def display(self) -> str:
        return self.label or f"v{self.index} ·…{_identity_hex(self.manifest)[-12:]}"

    @property
    def tag(self) -> str:
        return self.label or f"v{self.index}"

    @property
    def heading(self) -> str:
        if self.label:
            return html.escape(self.label)
        return f"<code>…{html.escape(_identity_hex(self.manifest)[-12:])}</code>"


def _condition_color(condition: str, conditions: list[str]) -> str:
    if condition in _KNOWN_COLORS:
        return _KNOWN_COLORS[condition]
    unknown = [item for item in conditions if item not in _KNOWN_COLORS]
    return _EXTRA_COLORS[unknown.index(condition) % len(_EXTRA_COLORS)]


def _success_by_condition(readout: dict[str, object]) -> list[tuple[str, int, int]]:
    per_scenario = readout["per_scenario_task_success"]
    totals = []
    for condition in readout["conditions"]:  # type: ignore[union-attr]
        successes = runs = 0
        for scenario in readout["scenarios"]:  # type: ignore[union-attr]
            entry = per_scenario[str(scenario)][str(condition)]  # type: ignore[index]
            successes += int(entry["successes"])
            runs += int(entry["runs"])
        totals.append((str(condition), successes, runs))
    return totals


def _version_totals(
    readout: dict[str, object], records: list[dict[str, object]]
) -> dict[str, object]:
    cells = [
        cell
        for record in records
        for cell in record["cells"]  # type: ignore[union-attr]
        if isinstance(cell, dict)
    ]
    return {
        "runs": len(records),
        "cells": len(cells),
        "requests": sum(int(cell.get("provider_requests") or 0) for cell in cells),
        "tokens": sum(int(cell.get("provider_tokens") or 0) for cell in cells),
        "cost": sum((_decimal(cell.get("cost_usd") or 0) for cell in cells), Decimal(0)),
        "rates": {
            condition: (successes, runs)
            for condition, successes, runs in _success_by_condition(readout)
        },
    }


# --------------------------------------------------------------------------
# SVG primitives (deterministic: fixed formats, no environment input)


def _svg_open(height: int) -> str:
    return (
        f'<svg viewBox="0 0 {_CHART_WIDTH} {height}" width="100%" '
        f'height="{height}" role="img" xmlns="http://www.w3.org/2000/svg">'
    )


def _svg_hbars(rows: list[tuple[str, float, str, str]]) -> str:
    """Horizontal bars: rows of (label, value 0..1, color, value text)."""
    height = len(rows) * (_BAR_HEIGHT + _BAR_GAP) + _BAR_GAP
    span = _CHART_WIDTH - _CHART_GUTTER - 70
    parts = [_svg_open(height)]
    for index, (label, value, color, text) in enumerate(rows):
        y = _BAR_GAP + index * (_BAR_HEIGHT + _BAR_GAP)
        width = max(value, 0.0) * span
        parts.append(
            f'<text x="{_CHART_GUTTER - 8}" y="{y + 15}" text-anchor="end" '
            f'class="lbl">{html.escape(label)}</text>'
            f'<rect x="{_CHART_GUTTER}" y="{y}" width="{span}" '
            f'height="{_BAR_HEIGHT}" class="track"/>'
            f'<rect x="{_CHART_GUTTER}" y="{y}" width="{width:.1f}" '
            f'height="{_BAR_HEIGHT}" fill="{color}" rx="3"/>'
            f'<text x="{_CHART_GUTTER + span + 6}" y="{y + 15}" class="val">'
            f"{html.escape(text)}</text>"
        )
    parts.append("</svg>")
    return "".join(parts)


def _svg_whiskers(rows: list[tuple[str, float, float, float]]) -> str:
    """Dot-and-whisker rows of (label, diff pp, lo pp, hi pp) on -100..100."""
    height = len(rows) * (_BAR_HEIGHT + _BAR_GAP) + _BAR_GAP + 18
    span = _CHART_WIDTH - _CHART_GUTTER - 70

    def x(value: float) -> float:
        clamped = max(-100.0, min(100.0, value))
        return _CHART_GUTTER + (clamped + 100.0) / 200.0 * span

    zero = x(0.0)
    parts = [_svg_open(height)]
    parts.append(
        f'<line x1="{zero:.1f}" y1="0" x2="{zero:.1f}" y2="{height - 18}" class="zero"/>'
    )
    for index, (label, diff, low, high) in enumerate(rows):
        y = _BAR_GAP + index * (_BAR_HEIGHT + _BAR_GAP) + _BAR_HEIGHT // 2
        parts.append(
            f'<text x="{_CHART_GUTTER - 8}" y="{y + 4}" text-anchor="end" '
            f'class="lbl">{html.escape(label)}</text>'
            f'<line x1="{x(low):.1f}" y1="{y}" x2="{x(high):.1f}" y2="{y}" class="ci"/>'
            f'<circle cx="{x(diff):.1f}" cy="{y}" r="5" class="dot"/>'
            f'<text x="{_CHART_GUTTER + span + 6}" y="{y + 4}" class="val">'
            f"{diff:+.1f} pp</text>"
        )
    parts.append(
        f'<text x="{zero:.1f}" y="{height - 4}" text-anchor="middle" class="lbl">0</text>'
        "</svg>"
    )
    return "".join(parts)


def _legend(conditions: list[str]) -> str:
    chips = "".join(
        f'<span class="chip"><i style="background:{_condition_color(item, conditions)}"></i>'
        f"{html.escape(item)}</span>"
        for item in conditions
    )
    return f'<div class="legend">{chips}</div>'


# --------------------------------------------------------------------------
# per-version fragments


def _minibar(value: Decimal | int, maximum: Decimal | int) -> str:
    percent = float(value) / float(maximum) * 100 if maximum else 0.0
    return f'<div class="mini"><i style="width:{percent:.1f}%"></i></div>'


def _token_warning_callout(readout: dict[str, object]) -> str:
    warnings = readout.get("warnings")
    if not isinstance(warnings, list) or not warnings:
        return ""
    items = []
    for warning in warnings:
        if not isinstance(warning, dict):
            continue
        detail = (
            f"{warning.get('run_id')} {warning.get('cell_id')} "
            f"{warning.get('scenario')}/{warning.get('condition')}: "
            f"{warning.get('provider_tokens')} > {warning.get('threshold')} "
            f"({warning.get('code')})"
        )
        items.append(f"<li>{html.escape(detail)}</li>")
    if not items:
        return ""
    return (
        '<div class="callout warn"><strong>Token warnings</strong><ul>'
        + "".join(items)
        + "</ul></div>"
    )


def _state_chip(record: dict[str, object]) -> str:
    state = f"{record['state']}/{record['validity']}"
    variant = (
        "chip-green"
        if record.get("state") == "complete" and record.get("validity") == "valid"
        else "chip-red"
    )
    return f'<span class="chip {variant}">{html.escape(state)}</span>'


def _run_started(record: dict[str, object]) -> str:
    stamps = sorted(
        str(cell["started_at_utc"])
        for cell in record["cells"]  # type: ignore[union-attr]
        if isinstance(cell, dict) and isinstance(cell.get("started_at_utc"), str)
    )
    return stamps[0][:10] if stamps else "—"


def _runs_table(records: list[dict[str, object]]) -> str:
    totals = []
    for record in records:
        cells = [cell for cell in record["cells"] if isinstance(cell, dict)]  # type: ignore[union-attr]
        totals.append(
            (
                record,
                sum(int(cell.get("provider_requests") or 0) for cell in cells),
                sum(int(cell.get("provider_tokens") or 0) for cell in cells),
                sum((_decimal(cell.get("cost_usd") or 0) for cell in cells), Decimal(0)),
            )
        )
    max_tokens = max((tokens for _, _, tokens, _ in totals), default=0)
    max_cost = max((cost for _, _, _, cost in totals), default=Decimal(0))
    rows = []
    for number, (record, requests, tokens, cost) in enumerate(totals, start=1):
        rows.append(
            "<tr>"
            f"<td><strong>Run {number}</strong></td>"
            f"<td>{html.escape(_run_started(record))}</td>"
            f"<td>{_state_chip(record)}</td>"
            f"<td>{requests}</td>"
            f"<td>{tokens}{_minibar(tokens, max_tokens)}</td>"
            f"<td>${cost}{_minibar(cost, max_cost)}</td>"
            "</tr>"
        )
    return (
        '<div class="tbl-wrap"><table><thead><tr><th>run</th><th>started</th>'
        "<th>state</th><th>requests</th><th>tokens</th><th>derived cost</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _internal_identities(version: _Version) -> str:
    digests = {
        str(entry["run_id"]): str(entry["digest"])
        for entry in version.readout["inputs"]  # type: ignore[union-attr]
        if isinstance(entry, dict)
    }
    rows = [
        "<tr><th>manifest</th>"
        f"<td colspan=\"2\"><code>{html.escape(version.manifest)}</code></td></tr>",
        "<tr><th>resolved manifest</th>"
        f"<td colspan=\"2\"><code>{html.escape(str(version.readout['resolved_manifest_identity']))}</code></td></tr>",
    ]
    for number, record in enumerate(version.records, start=1):
        run_id = str(record["run_id"])
        rows.append(
            f"<tr><th>Run {number}</th><td><code>{html.escape(run_id)}</code></td>"
            f"<td><code>{html.escape(digests.get(run_id, '-'))}</code></td></tr>"
        )
    return (
        '<details class="internal"><summary>Internal identities</summary>'
        f'<div class="tbl-wrap"><table><tbody>{"".join(rows)}</tbody></table></div>'
        "</details>"
    )


def _rate_style(successes: int, runs: int) -> str:
    rate = successes / runs if runs else 0.0
    return f"background:hsl({rate * 120:.0f} 65% 90%)"


def _matrix_table(readout: dict[str, object]) -> str:
    conditions = [str(item) for item in readout["conditions"]]  # type: ignore[index]
    per_scenario = readout["per_scenario_task_success"]
    header = "".join(f"<th>{html.escape(item)}</th>" for item in conditions)
    rows = []
    for scenario in readout["scenarios"]:  # type: ignore[union-attr]
        entries = per_scenario[str(scenario)]  # type: ignore[index]
        cells = []
        for condition in conditions:
            entry = entries[condition]
            successes, runs = int(entry["successes"]), int(entry["runs"])
            cells.append(
                f'<td style="{_rate_style(successes, runs)}">{successes}/{runs}</td>'
            )
        rows.append(f"<tr><th>{html.escape(str(scenario))}</th>{''.join(cells)}</tr>")
    return (
        f'<div class="tbl-wrap"><table><thead><tr><th>scenario</th>{header}</tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _interval(entry: dict[str, object], key: str, unit: str) -> str:
    interval = entry.get(key)
    if not isinstance(interval, list) or len(interval) != 2:
        return "-"
    return f"[{interval[0]:+.2f}, {interval[1]:+.2f}]{unit}"


def _pairs_table(readout: dict[str, object]) -> str:
    rows = []
    for pair in readout["pairs"]:  # type: ignore[union-attr]
        task = pair["task_success"]
        columns = [
            f"<td><strong>{html.escape(str(pair['a']))} vs {html.escape(str(pair['b']))}</strong></td>",
            f"<td>{pair['blocks']}</td>",
            f"<td>{task['a_successes']}:{task['b_successes']}</td>",
            f"<td>{task['n10']}:{task['n01']}</td>",
            f"<td>{task['difference_pp']:+.1f} {_interval(task, 'interval_95_pp', '')}</td>",
        ]
        for endpoint, _, unit in _PAIR_ENDPOINTS:
            entry = pair[endpoint]
            mean = entry.get("mean_difference")
            text = (
                "-"
                if mean is None
                else f"{mean:+.6g} {_interval(entry, 'interval_95', unit)}"
            )
            columns.append(f"<td>{text}</td>")
        rows.append(f"<tr>{''.join(columns)}</tr>")
    endpoint_headers = "".join(f"<th>{label}</th>" for _, label, _ in _PAIR_ENDPOINTS)
    return (
        '<div class="tbl-wrap"><table><thead><tr><th>pair</th><th>blocks</th>'
        "<th>success a:b</th><th>discordant n10:n01</th><th>diff pp [95%]</th>"
        f"{endpoint_headers}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def _pair_whisker_chart(readout: dict[str, object]) -> str:
    rows = []
    for pair in readout["pairs"]:  # type: ignore[union-attr]
        task = pair["task_success"]
        interval = task.get("interval_95_pp")
        diff = float(task["difference_pp"])
        low, high = (
            (float(interval[0]), float(interval[1]))
            if isinstance(interval, list) and len(interval) == 2
            else (diff, diff)
        )
        rows.append((f"{pair['a']} vs {pair['b']}", diff, low, high))
    return _svg_whiskers(rows)


def _rate_chart(readout: dict[str, object]) -> str:
    conditions = [str(item) for item in readout["conditions"]]  # type: ignore[index]
    rows = []
    for condition, successes, runs in _success_by_condition(readout):
        rate = successes / runs if runs else 0.0
        rows.append(
            (
                condition,
                rate,
                _condition_color(condition, conditions),
                f"{successes}/{runs} ({rate * 100:.0f}%)",
            )
        )
    return _svg_hbars(rows)


def _cells_table(records: list[dict[str, object]]) -> str:
    rows = []
    for number, record in enumerate(records, start=1):
        for cell in record["cells"]:  # type: ignore[union-attr]
            scores = cell.get("scores") if isinstance(cell, dict) else None
            success = scores.get("task_success") if isinstance(scores, dict) else None
            duration = int(cell.get("duration_ns") or 0) / 1e9
            disposition = str(cell.get("disposition"))
            klass = _DISPOSITION_CLASS.get(
                disposition, "fail" if disposition.startswith("invalid") else ""
            )
            rows.append(
                "<tr>"
                f"<td>Run {number}</td>"
                f"<td>{html.escape(str(cell.get('cell_id')))}</td>"
                f'<td class="{klass}">{html.escape(disposition)}</td>'
                f"<td>{html.escape(str(cell.get('reason_code')))}</td>"
                f"<td>{html.escape(str(success))}</td>"
                f"<td>{int(cell.get('provider_requests') or 0)}</td>"
                f"<td>{int(cell.get('provider_tokens') or 0)}</td>"
                f"<td>${_decimal(cell.get('cost_usd') or 0)}</td>"
                f"<td>{duration:.1f}</td>"
                "</tr>"
            )
    return (
        "<details><summary>All cells</summary>"
        '<div class="tbl-wrap"><table><thead><tr><th>run</th><th>cell</th>'
        "<th>disposition</th><th>reason</th><th>task_success</th><th>requests</th>"
        "<th>tokens</th><th>cost</th><th>duration s</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div></details>"
    )


# --------------------------------------------------------------------------
# cross-version comparison (observed rates only, display-only)


def _comparison_section(versions: list[_Version]) -> str:
    conditions = sorted(
        {
            str(condition)
            for version in versions
            for condition in version.readout["conditions"]  # type: ignore[union-attr]
        }
    )
    bar_rows = []
    for condition in conditions:
        color = _condition_color(condition, conditions)
        for version in versions:
            successes, runs = version.totals["rates"].get(condition, (0, 0))  # type: ignore[union-attr]
            rate = successes / runs if runs else 0.0
            bar_rows.append(
                (
                    f"{condition} · {version.tag}",
                    rate,
                    color,
                    f"{successes}/{runs} ({rate * 100:.0f}%)",
                )
            )
    header = "".join(
        f"<th>{html.escape(version.tag)}</th>" for version in versions
    )
    condition_rows = []
    for condition in conditions:
        cells = []
        for version in versions:
            successes, runs = version.totals["rates"].get(condition, (0, 0))  # type: ignore[union-attr]
            cells.append(
                f'<td style="{_rate_style(successes, runs)}">{successes}/{runs}</td>'
            )
        condition_rows.append(
            f"<tr><th>{html.escape(condition)}</th>{''.join(cells)}</tr>"
        )
    totals_row = "".join(
        f"<td>{version.totals['runs']} runs · {version.totals['tokens']} tok"
        f" · ${version.totals['cost']}</td>"
        for version in versions
    )
    return (
        '<section id="comparison"><h2>Cross-version comparison</h2>'
        '<div class="callout warn">Observed task-success rates, display-only — '
        "no cross-version statistics or claims.</div>"
        f"{_legend(conditions)}{_svg_hbars(bar_rows)}"
        f'<div class="tbl-wrap"><table><thead><tr><th>condition</th>{header}</tr></thead>'
        f"<tbody>{''.join(condition_rows)}"
        f"<tr><th>totals</th>{totals_row}</tr></tbody></table></div>"
        "</section>"
    )


# --------------------------------------------------------------------------
# page assembly

_STYLE = """
:root {
  --brand: #1e3a5f; --accent: #2e86de; --light: #f4f7fb; --muted: #6b7280;
  --green: #16a34a; --red: #dc2626; --warn: #d97706; --border: #dde3ec;
  --radius: 10px; --shadow: 0 2px 12px rgba(30,58,95,.08);
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
       background: #eef2f8; color: #1a2535; line-height: 1.6; }
nav { position: fixed; top: 0; left: 0; right: 0; z-index: 100;
      background: var(--brand); display: flex; align-items: center; gap: 8px;
      padding: 0 28px; height: 52px; box-shadow: 0 2px 8px rgba(0,0,0,.25);
      overflow-x: auto; }
nav a { color: rgba(255,255,255,.75); text-decoration: none; font-size: .78rem;
        font-weight: 500; white-space: nowrap; padding: 4px 10px;
        border-radius: 4px; }
nav a:hover { background: rgba(255,255,255,.12); color: #fff; }
nav .sep { color: rgba(255,255,255,.2); user-select: none; }
main { max-width: 1060px; margin: 0 auto; padding: 72px 24px 64px; }
section { background: #fff; border-radius: var(--radius); box-shadow: var(--shadow);
          padding: 40px 44px; margin-bottom: 30px;
          border-top: 4px solid var(--accent); scroll-margin-top: 64px; }
.hero { background: linear-gradient(135deg, var(--brand) 0%, #2557a7 100%);
        color: #fff; border-top: none; text-align: center; padding: 56px 44px; }
.hero .tag { display: inline-block; background: rgba(255,255,255,.15);
             border: 1px solid rgba(255,255,255,.25); border-radius: 20px;
             padding: 4px 16px; font-size: .8rem; letter-spacing: .06em;
             text-transform: uppercase; margin-bottom: 18px; }
.hero h1 { font-size: 2rem; font-weight: 700; line-height: 1.25; margin-bottom: 12px; }
.hero .subtitle { font-size: 1.02rem; opacity: .8; }
.hero .meta { display: flex; justify-content: center; gap: 38px; flex-wrap: wrap;
              border-top: 1px solid rgba(255,255,255,.2); padding-top: 26px;
              margin-top: 26px; }
.hero .meta-item .val { font-size: 1.5rem; font-weight: 700; }
.hero .meta-item .lbl { font-size: .78rem; opacity: .7; }
h2 { font-size: 1.4rem; color: var(--brand); font-weight: 700; margin-bottom: 18px; }
h3 { font-size: 1.05rem; color: var(--brand); font-weight: 600; margin: 26px 0 10px; }
.meta { color: var(--muted); font-size: .88em; margin: .2rem 0 .8rem; }
.callout { border-left: 4px solid var(--accent); background: var(--light);
           border-radius: 0 8px 8px 0; padding: 13px 18px; margin: 14px 0;
           font-size: .92rem; }
.callout.warn { border-color: var(--warn); background: #fffbeb; }
.chip { display: inline-flex; align-items: center; gap: .38rem;
        background: var(--light); border: 1px solid var(--border);
        border-radius: 6px; padding: 2px 10px; font-size: .78rem;
        font-weight: 600; color: var(--brand); margin: 2px; }
.chip i { width: .68rem; height: .68rem; border-radius: 3px; display: inline-block; }
.chip-green { background: #f0fdf4; border-color: #86efac; color: #15803d; }
.chip-red { background: #fef2f2; border-color: #fca5a5; color: #b91c1c; }
.chip-blue { background: #eff6ff; border-color: #93c5fd; color: #1d4ed8; }
.legend { display: flex; gap: .5rem; flex-wrap: wrap; margin: .5rem 0 .8rem; }
.tbl-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: .87rem; margin: .5rem 0; }
th { background: var(--brand); color: #fff; padding: 9px 13px; text-align: left;
     font-weight: 600; }
tbody th { background: #f8fafc; color: var(--brand); border-bottom: 1px solid var(--border); }
td { padding: 8px 13px; border-bottom: 1px solid var(--border); vertical-align: top; }
tr:nth-child(even) td { background: #f8fafc; }
.ok { color: var(--green); font-weight: 700; }
.warn { color: var(--warn); font-weight: 700; }
.fail { color: var(--red); font-weight: 700; }
.na { color: var(--muted); }
code { font-size: .8em; word-break: break-all; }
details { margin: 1rem 0 0; }
summary { cursor: pointer; font-weight: 600; color: var(--brand); }
details.internal summary { color: var(--muted); font-weight: 500; font-size: .85rem; }
.mini { background: #e5e7eb; border-radius: 3px; height: 5px; margin-top: 5px;
        width: 130px; }
.mini i { background: var(--accent); border-radius: 3px; height: 5px; display: block; }
svg .lbl { font: 12px 'Segoe UI', system-ui, sans-serif; fill: #374151; }
svg .val { font: 12px 'Segoe UI', system-ui, sans-serif; fill: var(--muted); }
svg .track { fill: #e8edf5; }
svg .zero { stroke: #9aa7bd; stroke-dasharray: 4 3; }
svg .ci { stroke: var(--accent); stroke-width: 2; }
svg .dot { fill: var(--brand); }
footer { color: var(--muted); font-size: .85em; text-align: center; margin-top: 8px; }
@media print { nav { display: none; } body { background: #fff; }
  section { box-shadow: none; border: 1px solid #ccc; page-break-inside: avoid; }
  main { padding: 0; } }
"""


def _hero(title: str, versions: list[_Version]) -> str:
    runs = sum(int(version.totals["runs"]) for version in versions)  # type: ignore[arg-type]
    cells = sum(int(version.totals["cells"]) for version in versions)  # type: ignore[arg-type]
    requests = sum(int(version.totals["requests"]) for version in versions)  # type: ignore[arg-type]
    tokens = sum(int(version.totals["tokens"]) for version in versions)  # type: ignore[arg-type]
    cost = sum((version.totals["cost"] for version in versions), Decimal(0))  # type: ignore[misc]
    items = (
        (str(len(versions)), "versions"),
        (str(runs), "sealed runs"),
        (str(cells), "valid cells"),
        (str(requests), "provider requests"),
        (str(tokens), "provider tokens"),
        (f"${cost}", "derived cost"),
    )
    meta = "".join(
        f'<div class="meta-item"><div class="val">{html.escape(value)}</div>'
        f'<div class="lbl">{html.escape(label)}</div></div>'
        for value, label in items
    )
    return (
        '<section class="hero" id="overview">'
        '<div class="tag">Diagnostic · no claims</div>'
        f"<h1>{html.escape(title)}</h1>"
        '<p class="subtitle">Sealed Functional V1 Run Records · grouped by manifest version</p>'
        f'<div class="meta">{meta}</div>'
        "</section>"
    )


def _version_section(version: _Version) -> str:
    readout = version.readout
    conditions = [str(item) for item in readout["conditions"]]  # type: ignore[index]
    margins = readout["reference_margins"]
    return (
        f'<section id="v{version.index}">'
        f"<h2>Version {version.index}: {version.heading}</h2>"
        f'<div class="legend">'
        f'<span class="chip chip-blue">blocks {readout["block_count"]}</span>'
        f'<span class="chip chip-blue">cells {readout["data_quality"]["cells"]}</span>'  # type: ignore[index]
        f'<span class="chip chip-blue">missing task_success {readout["data_quality"]["missing_task_success"]}</span>'  # type: ignore[index]
        f'<span class="chip">margins (annotation): task_success ±{margins["task_success_worthwhile_pp"]} pp'  # type: ignore[index]
        f' · regression harm {margins["regression_harm_pp"]} pp</span>'  # type: ignore[index]
        "</div>"
        f"{_token_warning_callout(readout)}"
        f"<h3>Runs</h3>{_runs_table(version.records)}"
        f"<h3>Task-success rate by condition</h3>{_legend(conditions)}{_rate_chart(readout)}"
        f"<h3>Task success by scenario</h3>{_matrix_table(readout)}"
        f"<h3>Paired task-success differences (pp, 95% interval)</h3>"
        f"{_pair_whisker_chart(readout)}"
        f"<h3>Paired contrasts (pooled over blocks)</h3>{_pairs_table(readout)}"
        f"{_cells_table(version.records)}"
        f"{_internal_identities(version)}"
        "</section>"
    )


def build_dashboard(
    paths: list[Path], title: str, names_path: Path | None = None
) -> str:
    if not paths:
        raise DashboardError("at least one run record is required")
    groups = _grouped(paths)
    labels = _resolve_names(
        _load_names(names_path), [manifest for manifest, _, _ in groups]
    )
    versions: list[_Version] = []
    sections = []
    for index, (manifest, group_paths, records) in enumerate(groups, start=1):
        readout = build_readout(group_paths)
        version = _Version(index, manifest, labels.get(manifest), readout, records)
        versions.append(version)
        sections.append(_version_section(version))
    links = ['<a href="#overview">Overview</a>']
    links.extend(
        f'<a href="#v{version.index}">{html.escape(version.display)}</a>'
        for version in versions
    )
    if len(versions) > 1:
        links.append('<a href="#comparison">Comparison</a>')
        sections.append(_comparison_section(versions))
    navigation = '<span class="sep">›</span>'.join(links)
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        f"<title>{html.escape(title)}</title><style>{_STYLE}</style></head><body>"
        f"<nav>{navigation}</nav><main>"
        f"{_hero(title, versions)}"
        f'<div class="callout warn">{html.escape(_BANNER)}</div>'
        f"{''.join(sections)}"
        "<footer>schema: measurement-readout-v1 · authority: none · claims: none</footer>"
        "</main></body></html>\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dashboard",
        description="Render sealed Run Records into one static no-claims HTML page.",
    )
    parser.add_argument("records", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--title", default="Functional V1 results")
    parser.add_argument(
        "--names",
        type=Path,
        default=None,
        help="JSON file mapping manifest-identity prefixes to display labels",
    )
    arguments = parser.parse_args(argv)
    try:
        page = build_dashboard(
            list(arguments.records), str(arguments.title), arguments.names
        )
        arguments.output.write_text(page, encoding="utf-8")
    except (DashboardError, ReadoutError, OSError) as error:
        print(f"dashboard: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

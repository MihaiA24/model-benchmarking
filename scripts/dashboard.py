"""Static, no-claims results dashboard over sealed Functional V1 Run Records.

One self-contained HTML page from ``run-record.json`` paths (issue #109).
Records are grouped by ``manifest_identity`` — the benchmark's version key —
and every group is validated and analyzed by ``scripts/readout.py``'s
``build_readout`` (same fail-closed rules, same statistics); the dashboard
adds presentation only: tables, inline-SVG charts, and a display-only
cross-version comparison of observed rates. stdlib-only, zero JavaScript,
deterministic output bytes, every record field escaped.
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
    "omp": "#4e79a7",
    "opencode": "#f28e2b",
    "hermes": "#59a14f",
    "raw-api": "#af7aa1",
}
_EXTRA_COLORS = ("#e15759", "#76b7b2", "#edc948", "#b07aa1")
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


def _runs_table(readout: dict[str, object], records: list[dict[str, object]]) -> str:
    digests = {
        str(entry["run_id"]): str(entry["digest"])
        for entry in readout["inputs"]  # type: ignore[union-attr]
        if isinstance(entry, dict)
    }
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
    for record, requests, tokens, cost in totals:
        run_id = str(record["run_id"])
        rows.append(
            "<tr>"
            f"<td><code>{html.escape(run_id)}</code></td>"
            f"<td><code>{html.escape(digests.get(run_id, '-'))}</code></td>"
            f"<td>{html.escape(str(record['state']))}/{html.escape(str(record['validity']))}</td>"
            f"<td>{requests}</td>"
            f"<td>{tokens}{_minibar(tokens, max_tokens)}</td>"
            f"<td>${cost}{_minibar(cost, max_cost)}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>run</th><th>record identity</th><th>state</th>"
        "<th>requests</th><th>tokens</th><th>derived cost</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _rate_style(successes: int, runs: int) -> str:
    rate = successes / runs if runs else 0.0
    return f"background:hsl({rate * 120:.0f} 70% 88%)"


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
        f"<table><thead><tr><th>scenario</th>{header}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
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
            f"<td>{html.escape(str(pair['a']))} vs {html.escape(str(pair['b']))}</td>",
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
        "<table><thead><tr><th>pair</th><th>blocks</th><th>success a:b</th>"
        f"<th>discordant n10:n01</th><th>diff pp [95%]</th>{endpoint_headers}"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
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
    for record in records:
        run_id = html.escape(str(record["run_id"]))
        for cell in record["cells"]:  # type: ignore[union-attr]
            scores = cell.get("scores") if isinstance(cell, dict) else None
            success = scores.get("task_success") if isinstance(scores, dict) else None
            duration = int(cell.get("duration_ns") or 0) / 1e9
            rows.append(
                "<tr>"
                f"<td><code>{run_id}</code></td>"
                f"<td>{html.escape(str(cell.get('cell_id')))}</td>"
                f"<td>{html.escape(str(cell.get('disposition')))}</td>"
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
        "<table><thead><tr><th>run</th><th>cell</th><th>disposition</th>"
        "<th>reason</th><th>task_success</th><th>requests</th><th>tokens</th>"
        "<th>cost</th><th>duration s</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></details>"
    )


# --------------------------------------------------------------------------
# cross-version comparison (observed rates only, display-only)


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
        "tokens": sum(int(cell.get("provider_tokens") or 0) for cell in cells),
        "cost": sum((_decimal(cell.get("cost_usd") or 0) for cell in cells), Decimal(0)),
        "rates": {
            condition: (successes, runs)
            for condition, successes, runs in _success_by_condition(readout)
        },
    }


def _comparison_section(
    versions: list[tuple[str, dict[str, object], dict[str, object]]],
) -> str:
    conditions = sorted(
        {
            str(condition)
            for _, readout, _ in versions
            for condition in readout["conditions"]  # type: ignore[union-attr]
        }
    )
    bar_rows = []
    for condition in conditions:
        color = _condition_color(condition, conditions)
        for index, (_, readout, totals) in enumerate(versions, start=1):
            successes, runs = totals["rates"].get(condition, (0, 0))  # type: ignore[union-attr]
            rate = successes / runs if runs else 0.0
            bar_rows.append(
                (
                    f"{condition} · v{index}",
                    rate,
                    color,
                    f"{successes}/{runs} ({rate * 100:.0f}%)",
                )
            )
    header = "".join(
        f"<th>v{index}<br><code>…{html.escape(manifest[-12:])}</code></th>"
        for index, (manifest, _, _) in enumerate(versions, start=1)
    )
    condition_rows = []
    for condition in conditions:
        cells = []
        for _, _, totals in versions:
            successes, runs = totals["rates"].get(condition, (0, 0))  # type: ignore[union-attr]
            cells.append(
                f'<td style="{_rate_style(successes, runs)}">{successes}/{runs}</td>'
            )
        condition_rows.append(
            f"<tr><th>{html.escape(condition)}</th>{''.join(cells)}</tr>"
        )
    totals_row = "".join(
        f"<td>{totals['runs']} runs · {totals['tokens']} tok · ${totals['cost']}</td>"
        for _, _, totals in versions
    )
    return (
        '<section id="comparison"><h2>Cross-version comparison</h2>'
        '<p class="meta">Observed task-success rates, display-only — no cross-version'
        " statistics or claims.</p>"
        f"{_legend(conditions)}{_svg_hbars(bar_rows)}"
        f"<table><thead><tr><th>condition</th>{header}</tr></thead>"
        f"<tbody>{''.join(condition_rows)}"
        f"<tr><th>totals</th>{totals_row}</tr></tbody></table>"
        "</section>"
    )


# --------------------------------------------------------------------------
# page assembly

_STYLE = """
:root { color-scheme: light; }
body { font: 14px/1.5 system-ui, -apple-system, sans-serif; margin: 0;
       background: #f4f5f7; color: #1c1e21; }
.wrap { max-width: 74rem; margin: 0 auto; padding: 1.4rem 1.2rem 3rem; }
h1 { font-size: 1.45rem; margin: .4rem 0; }
h2 { font-size: 1.15rem; margin: 0 0 .6rem; }
h3 { font-size: .95rem; margin: 1.3rem 0 .4rem; text-transform: uppercase;
     letter-spacing: .04em; color: #555; }
.banner { background: #fff3cd; border: 1px solid #e0c96a; border-radius: 8px;
          padding: .6rem .9rem; margin: .8rem 0 1.2rem; }
nav { display: flex; gap: .5rem; flex-wrap: wrap; margin-bottom: .4rem; }
nav a { background: #fff; border: 1px solid #d8dbe0; border-radius: 999px;
        padding: .25rem .8rem; text-decoration: none; color: #1c1e21;
        font-size: .85rem; }
section { background: #fff; border: 1px solid #e2e4e8; border-radius: 12px;
          padding: 1.2rem 1.4rem; margin: 1.1rem 0;
          box-shadow: 0 1px 3px rgba(20, 24, 40, .05); }
table { border-collapse: collapse; margin: .5rem 0; width: 100%; }
th, td { border: 1px solid #e3e5e9; padding: .3rem .55rem; text-align: left;
         vertical-align: top; }
thead th { background: #f6f7f9; }
code { font-size: .8em; word-break: break-all; }
.meta { color: #5a5f6a; font-size: .88em; margin: .2rem 0 .8rem; }
details { margin: .8rem 0 0; } summary { cursor: pointer; font-weight: 600; }
.legend { display: flex; gap: .9rem; flex-wrap: wrap; margin: .4rem 0; }
.chip { display: inline-flex; align-items: center; gap: .35rem; font-size: .85rem; }
.chip i { width: .7rem; height: .7rem; border-radius: 3px; display: inline-block; }
.mini { background: #eceef1; border-radius: 3px; height: 5px; margin-top: 4px;
        width: 120px; }
.mini i { background: #7a8699; border-radius: 3px; height: 5px; display: block; }
svg .lbl { font: 12px system-ui, sans-serif; fill: #3a3f47; }
svg .val { font: 12px system-ui, sans-serif; fill: #5a5f6a; }
svg .track { fill: #eef0f3; rx: 3; }
svg .zero { stroke: #b9bec7; stroke-dasharray: 4 3; }
svg .ci { stroke: #4e79a7; stroke-width: 2; }
svg .dot { fill: #274566; }
footer { color: #5a5f6a; font-size: .85em; margin-top: 1.6rem; }
"""


def _version_section(
    index: int,
    manifest: str,
    readout: dict[str, object],
    records: list[dict[str, object]],
) -> str:
    conditions = [str(item) for item in readout["conditions"]]  # type: ignore[index]
    margins = readout["reference_margins"]
    return (
        f'<section id="v{index}"><h2>Version {index}: <code>{html.escape(manifest)}</code></h2>'
        f'<p class="meta">resolved: <code>{html.escape(str(readout["resolved_manifest_identity"]))}</code>'
        f" · blocks: {readout['block_count']}"
        f" · cells: {readout['data_quality']['cells']}"  # type: ignore[index]
        f" · missing task_success: {readout['data_quality']['missing_task_success']}"  # type: ignore[index]
        f" · margins (annotation): task_success ±{margins['task_success_worthwhile_pp']} pp,"  # type: ignore[index]
        f" regression harm {margins['regression_harm_pp']} pp</p>"  # type: ignore[index]
        f"<h3>Runs</h3>{_runs_table(readout, records)}"
        f"<h3>Task-success rate by condition</h3>{_legend(conditions)}{_rate_chart(readout)}"
        f"<h3>Task success by scenario</h3>{_matrix_table(readout)}"
        f"<h3>Paired task-success differences (pp, 95% interval)</h3>"
        f"{_pair_whisker_chart(readout)}"
        f"<h3>Paired contrasts (pooled over blocks)</h3>{_pairs_table(readout)}"
        f"{_cells_table(records)}"
        "</section>"
    )


def build_dashboard(paths: list[Path], title: str) -> str:
    if not paths:
        raise DashboardError("at least one run record is required")
    versions: list[tuple[str, dict[str, object], dict[str, object]]] = []
    sections = []
    for index, (manifest, group_paths, records) in enumerate(_grouped(paths), start=1):
        readout = build_readout(group_paths)
        versions.append((manifest, readout, _version_totals(readout, records)))
        sections.append(_version_section(index, manifest, readout, records))
    navigation = "".join(
        f'<a href="#v{index}">v{index} <code>…{html.escape(manifest[-12:])}</code></a>'
        for index, (manifest, _, _) in enumerate(versions, start=1)
    )
    if len(versions) > 1:
        navigation += '<a href="#comparison">comparison</a>'
        sections.append(_comparison_section(versions))
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{html.escape(title)}</title><style>{_STYLE}</style></head><body>"
        '<div class="wrap">'
        f"<h1>{html.escape(title)}</h1>"
        f'<div class="banner">{html.escape(_BANNER)}</div>'
        f"<nav>{navigation}</nav>"
        f"{''.join(sections)}"
        "<footer>schema: measurement-readout-v1 · authority: none · claims: none</footer>"
        "</div></body></html>\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dashboard",
        description="Render sealed Run Records into one static no-claims HTML page.",
    )
    parser.add_argument("records", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--title", default="Functional V1 results")
    arguments = parser.parse_args(argv)
    try:
        page = build_dashboard(list(arguments.records), str(arguments.title))
        arguments.output.write_text(page, encoding="utf-8")
    except (DashboardError, ReadoutError, OSError) as error:
        print(f"dashboard: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

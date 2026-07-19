"""Static, no-claims results dashboard over sealed Functional V1 Run Records.

One self-contained HTML page from ``run-record.json`` paths (issue #109).
Records are grouped by ``manifest_identity`` — the benchmark's version key —
and every group is validated and analyzed by ``scripts/readout.py``'s
``build_readout`` (same fail-closed rules, same statistics); the dashboard
adds presentation only. Output bytes are deterministic: no timestamps, no
environment leakage, everything escaped.
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


class DashboardError(ValueError):
    """The dashboard inputs are unusable."""


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


def _interval(entry: dict[str, object], key: str, unit: str) -> str:
    interval = entry.get(key)
    if not isinstance(interval, list) or len(interval) != 2:
        return "-"
    return f"[{interval[0]:+.2f}, {interval[1]:+.2f}]{unit}"


def _rate_style(successes: int, runs: int) -> str:
    rate = successes / runs if runs else 0.0
    return f"background:hsl({rate * 120:.0f} 70% 88%)"


def _runs_table(readout: dict[str, object], records: list[dict[str, object]]) -> str:
    digests = {
        str(entry["run_id"]): str(entry["digest"])
        for entry in readout["inputs"]  # type: ignore[union-attr]
        if isinstance(entry, dict)
    }
    rows = []
    for record in records:
        cells = [cell for cell in record["cells"] if isinstance(cell, dict)]  # type: ignore[union-attr]
        requests = sum(int(cell.get("provider_requests") or 0) for cell in cells)
        tokens = sum(int(cell.get("provider_tokens") or 0) for cell in cells)
        cost = sum((_decimal(cell.get("cost_usd") or 0) for cell in cells), Decimal(0))
        run_id = str(record["run_id"])
        rows.append(
            "<tr>"
            f"<td><code>{html.escape(run_id)}</code></td>"
            f"<td><code>{html.escape(digests.get(run_id, '-'))}</code></td>"
            f"<td>{html.escape(str(record['state']))}/{html.escape(str(record['validity']))}</td>"
            f"<td>{requests}</td><td>{tokens}</td><td>${cost}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>run</th><th>record identity</th><th>state</th>"
        "<th>requests</th><th>tokens</th><th>derived cost</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


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
        rows.append(
            f"<tr><th>{html.escape(str(scenario))}</th>{''.join(cells)}</tr>"
        )
    return (
        f"<table><thead><tr><th>scenario</th>{header}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


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
            text = "-" if mean is None else f"{mean:+.6g} {_interval(entry, 'interval_95', unit)}"
            columns.append(f"<td>{text}</td>")
        rows.append(f"<tr>{''.join(columns)}</tr>")
    endpoint_headers = "".join(f"<th>{label}</th>" for _, label, _ in _PAIR_ENDPOINTS)
    return (
        "<table><thead><tr><th>pair</th><th>blocks</th><th>success a:b</th>"
        f"<th>discordant n10:n01</th><th>diff pp [95%]</th>{endpoint_headers}"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


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


_STYLE = """
body { font: 14px/1.45 system-ui, sans-serif; margin: 2rem auto; max-width: 72rem;
       padding: 0 1rem; color: #1a1a1a; }
h1 { font-size: 1.4rem; } h2 { font-size: 1.15rem; margin-top: 2.2rem; }
h3 { font-size: 1rem; margin-top: 1.4rem; }
.banner { background: #fff3cd; border: 1px solid #e0c96a; border-radius: 6px;
          padding: .6rem .9rem; margin: 1rem 0; }
table { border-collapse: collapse; margin: .6rem 0; }
th, td { border: 1px solid #d0d0d0; padding: .28rem .55rem; text-align: left; }
thead th { background: #f2f2f2; }
code { font-size: .82em; word-break: break-all; }
.meta { color: #555; font-size: .88em; }
details { margin: .6rem 0; } summary { cursor: pointer; }
"""


def build_dashboard(paths: list[Path], title: str) -> str:
    if not paths:
        raise DashboardError("at least one run record is required")
    sections = []
    for index, (manifest, group_paths, records) in enumerate(_grouped(paths), start=1):
        readout = build_readout(group_paths)
        margins = readout["reference_margins"]
        sections.append(
            f"<section><h2>Version {index}: <code>{html.escape(manifest)}</code></h2>"
            f'<p class="meta">resolved: <code>{html.escape(str(readout["resolved_manifest_identity"]))}</code>'
            f" · blocks: {readout['block_count']}"
            f" · cells: {readout['data_quality']['cells']}"  # type: ignore[index]
            f" · missing task_success: {readout['data_quality']['missing_task_success']}"  # type: ignore[index]
            f" · margins (annotation): task_success ±{margins['task_success_worthwhile_pp']} pp,"  # type: ignore[index]
            f" regression harm {margins['regression_harm_pp']} pp</p>"  # type: ignore[index]
            f"<h3>Runs</h3>{_runs_table(readout, records)}"
            f"<h3>Task success by scenario</h3>{_matrix_table(readout)}"
            f"<h3>Paired contrasts (pooled over blocks)</h3>{_pairs_table(readout)}"
            f"{_cells_table(records)}"
            "</section>"
        )
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<title>{html.escape(title)}</title><style>{_STYLE}</style></head><body>"
        f"<h1>{html.escape(title)}</h1>"
        f'<div class="banner">{html.escape(_BANNER)}</div>'
        f"{''.join(sections)}"
        '<p class="meta">schema: measurement-readout-v1 · authority: none · claims: none</p>'
        "</body></html>\n"
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

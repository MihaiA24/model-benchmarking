#!/usr/bin/env python3
"""Post-hoc local rescore from saved benchmark transcripts.

This script never invokes a model/API/agent harness. It only:
1. reads saved metrics and saved `_raw_response.txt` transcripts,
2. rebuilds candidates in fresh local workdirs from the original seeded baseline,
3. writes the hardened final-code extraction into the target file, and
4. runs the task's local build/test commands.
"""

from __future__ import annotations

import argparse
import collections
import csv
from pathlib import Path

from audit_results import audit_row, read_text_if_exists, resolve_path, row_transcript, row_workdir, truthy
from benchmark.adapters.raw_api import FormatError, extract_code
from benchmark.checks import run_checks
from benchmark.tasks import TASK_BY_NAME
from benchmark.util import safe_label
from benchmark.workdir import make_workdir

REPO_ROOT = Path(__file__).parent.resolve()
RESCORE_FIELDS = [
    "harness",
    "task",
    "model",
    "run",
    "original_build_ok",
    "original_test_ok",
    "rescored_build_ok",
    "rescored_test_ok",
    "posthoc_status",
    "source_workdir",
    "rescore_workdir",
    "notes",
]
FAIR_EXTRA_FIELDS = [
    "fair_build_ok",
    "fair_test_ok",
    "fair_included",
    "fair_status",
    "fair_notes",
]


def row_key(row: dict[str, str]) -> tuple[str, str, str, str]:
    return (row.get("harness") or "raw_api", row.get("task", ""), row.get("model", ""), str(row.get("run", "")))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def rescore_label(row: dict[str, str]) -> str:
    harness, task, model, run = row_key(row)
    return f"{safe_label(harness)}__{safe_label(task)}__{safe_label(model)}__r{safe_label(run)}"


def run_local_rescore(row: dict[str, str], *, results_dir: Path, check_timeout_s: int) -> dict[str, str]:
    task = TASK_BY_NAME[row["task"]]
    source_workdir = row_workdir(row)
    transcript = row_transcript(row, source_workdir)
    rescore_workdir = results_dir / "_rescore_workdirs" / rescore_label(row)

    result = {
        "harness": row.get("harness") or "raw_api",
        "task": row.get("task", ""),
        "model": row.get("model", ""),
        "run": row.get("run", ""),
        "original_build_ok": row.get("build_ok", ""),
        "original_test_ok": row.get("test_ok", ""),
        "rescored_build_ok": "",
        "rescored_test_ok": "",
        "posthoc_status": "",
        "source_workdir": str(source_workdir),
        "rescore_workdir": str(rescore_workdir),
        "notes": "",
    }

    try:
        extracted = extract_code(read_text_if_exists(transcript))
    except FormatError as exc:
        result.update({"posthoc_status": "format_error", "notes": str(exc)})
        return result

    make_workdir(task, rescore_workdir)
    target = rescore_workdir / task.target_file
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(extracted, encoding="utf-8")
    (rescore_workdir / "_rescore_source.txt").write_text(
        f"source_workdir={source_workdir}\nsource_transcript={transcript}\n",
        encoding="utf-8",
    )

    build_ok, test_ok = run_checks(rescore_workdir, task, timeout_s=check_timeout_s)
    result.update(
        {
            "rescored_build_ok": str(build_ok),
            "rescored_test_ok": str(test_ok),
            "posthoc_status": "pass" if build_ok and test_ok else "fail",
        }
    )
    return result


def fair_row(
    metrics_row: dict[str, str],
    audit: dict[str, str],
    rescore_by_key: dict[tuple[str, str, str, str], dict[str, str]],
) -> dict[str, str]:
    key = row_key(metrics_row)
    fair = dict(metrics_row)
    category = audit["category"]
    disposition = audit["suggested_disposition"]

    if category == "pass":
        fair.update({"fair_build_ok": "True", "fair_test_ok": "True", "fair_included": "True", "fair_status": "pass", "fair_notes": "original pass"})
    elif disposition == "exclude_infra":
        fair.update({"fair_build_ok": "", "fair_test_ok": "", "fair_included": "False", "fair_status": "excluded_infra", "fair_notes": audit["notes"]})
    elif disposition == "posthoc_rescore_candidate":
        rescored = rescore_by_key.get(key)
        if rescored:
            fair_build_ok = rescored["rescored_build_ok"]
            fair_test_ok = rescored["rescored_test_ok"]
            status = "pass" if truthy(fair_build_ok) and truthy(fair_test_ok) else "fail"
            fair.update(
                {
                    "fair_build_ok": fair_build_ok,
                    "fair_test_ok": fair_test_ok,
                    "fair_included": "True",
                    "fair_status": f"posthoc_rescore_{status}",
                    "fair_notes": f"rescored locally from saved transcript; workdir={rescored['rescore_workdir']}",
                }
            )
        else:
            fair.update({"fair_build_ok": "", "fair_test_ok": "", "fair_included": "False", "fair_status": "posthoc_rescore_missing", "fair_notes": "candidate was not rescored"})
    else:
        fair.update(
            {
                "fair_build_ok": metrics_row.get("build_ok", ""),
                "fair_test_ok": metrics_row.get("test_ok", ""),
                "fair_included": "True",
                "fair_status": category,
                "fair_notes": audit["notes"],
            }
        )
    return fair


def write_summary(path: Path, fair_rows: list[dict[str, str]], rescore_rows: list[dict[str, str]]) -> None:
    included = [row for row in fair_rows if row["fair_included"] == "True"]
    passes = [row for row in included if truthy(row["fair_build_ok"]) and truthy(row["fair_test_ok"])]
    excluded = [row for row in fair_rows if row["fair_included"] != "True"]
    rescore_passes = [row for row in rescore_rows if row["posthoc_status"] == "pass"]
    rescore_fails = [row for row in rescore_rows if row["posthoc_status"] == "fail"]

    by_status = collections.Counter(row["fair_status"] for row in fair_rows)
    by_harness_model: dict[tuple[str, str], list[dict[str, str]]] = collections.defaultdict(list)
    for row in included:
        by_harness_model[(row.get("harness", ""), row.get("model", ""))].append(row)

    lines = [
        "# Post-hoc fair benchmark summary",
        "",
        "This summary uses saved transcripts only. It does not invoke models, APIs, or agent harnesses.",
        "",
        f"Total rows: {len(fair_rows)}",
        f"Scored rows, excluding infrastructure: {len(included)}",
        f"Excluded infrastructure/unscored rows: {len(excluded)}",
        f"Fair pass rows: {len(passes)}/{len(included)}" if included else "Fair pass rows: 0/0",
        f"Post-hoc rescore candidates: {len(rescore_rows)}",
        f"Post-hoc rescore passes: {len(rescore_passes)}",
        f"Post-hoc rescore failures: {len(rescore_fails)}",
        "",
        "## Fair status counts",
        "",
    ]
    for status, count in by_status.most_common():
        lines.append(f"- {status}: {count}")
    lines.extend(["", "## Fair pass rate by harness/model", ""])
    for (harness, model), rows in sorted(by_harness_model.items()):
        ok = sum(1 for row in rows if truthy(row["fair_build_ok"]) and truthy(row["fair_test_ok"]))
        lines.append(f"- {harness} / {model}: {ok}/{len(rows)}")
    if rescore_rows:
        lines.extend(["", "## Post-hoc rescored rows", ""])
        for row in rescore_rows:
            lines.append(
                f"- {row['harness']} / {row['task']} / {row['model']} / run {row['run']}: "
                f"{row['original_build_ok']}/{row['original_test_ok']} -> "
                f"{row['rescored_build_ok']}/{row['rescored_test_ok']} ({row['posthoc_status']})"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Locally rescore saved benchmark transcripts without invoking models.")
    parser.add_argument("--results-dir", type=Path, default=Path("results/full_combined_v3"))
    parser.add_argument("--metrics", default="metrics_all.csv")
    parser.add_argument("--check-timeout", type=int, default=600)
    parser.add_argument("--dry-run", action="store_true", help="List candidates without running local build/test commands.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    results_dir = args.results_dir if args.results_dir.is_absolute() else REPO_ROOT / args.results_dir
    metrics_rows = read_csv(results_dir / args.metrics)
    audit_rows = [audit_row(row) for row in metrics_rows]
    audit_by_key = {row_key(row): row for row in audit_rows}
    candidates = [row for row in audit_rows if row["suggested_disposition"] == "posthoc_rescore_candidate"]
    metrics_by_key = {row_key(row): row for row in metrics_rows}

    if args.dry_run:
        for row in candidates:
            print("PLAN", " | ".join(row_key(row)))
        print(f"Planned local rescores: {len(candidates)}")
        return 0

    rescore_rows = [
        run_local_rescore(metrics_by_key[row_key(candidate)], results_dir=results_dir, check_timeout_s=args.check_timeout)
        for candidate in candidates
    ]
    rescore_by_key = {row_key(row): row for row in rescore_rows}
    fair_rows = [fair_row(row, audit_by_key[row_key(row)], rescore_by_key) for row in metrics_rows]

    write_csv(results_dir / "posthoc_rescore.csv", RESCORE_FIELDS, rescore_rows)
    fieldnames = list(metrics_rows[0].keys()) + FAIR_EXTRA_FIELDS if metrics_rows else FAIR_EXTRA_FIELDS
    write_csv(results_dir / "metrics_fair.csv", fieldnames, fair_rows)
    write_summary(results_dir / "metrics_fair_summary.md", fair_rows, rescore_rows)

    print(f"Rescored candidates: {len(rescore_rows)}")
    print(f"Wrote {results_dir / 'posthoc_rescore.csv'}")
    print(f"Wrote {results_dir / 'metrics_fair.csv'}")
    print(f"Wrote {results_dir / 'metrics_fair_summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

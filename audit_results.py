#!/usr/bin/env python3
"""Audit saved benchmark results without invoking models.

This script classifies existing metrics/workdir artifacts so infrastructure and
harness-evaluation defects do not get mistaken for model-quality failures. It is
read-only with respect to model execution: it reads saved transcripts, saved
workdirs, and metrics CSVs; it never calls an API or CLI harness.
"""

from __future__ import annotations

import argparse
import collections
import csv
from pathlib import Path

from benchmark.adapters.raw_api import FormatError, extract_code
from benchmark.tasks import TASK_BY_NAME

REPO_ROOT = Path(__file__).parent.resolve()
AUDIT_FIELDS = [
    "harness",
    "task",
    "model",
    "run",
    "build_ok",
    "test_ok",
    "category",
    "suggested_disposition",
    "extraction_mismatch",
    "format_error",
    "notes",
    "workdir",
]


def truthy(value: object) -> bool:
    return str(value).strip().lower() in {"true", "1"}


def resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_text_if_exists(path: Path, *, max_chars: int | None = None) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text if max_chars is None else text[:max_chars]


def row_workdir(row: dict[str, str]) -> Path:
    return resolve_path(row.get("workdir", ""))


def row_transcript(row: dict[str, str], workdir: Path) -> Path:
    transcript = row.get("transcript_path") or str(workdir / "_raw_response.txt")
    return resolve_path(transcript)


def extraction_status(row: dict[str, str], workdir: Path) -> tuple[bool, str]:
    if (row.get("harness") or "raw_api") != "raw_api":
        return False, ""
    task = TASK_BY_NAME.get(row.get("task", ""))
    if task is None:
        return False, "unknown task"
    transcript = row_transcript(row, workdir)
    target = workdir / task.target_file
    if not transcript.exists() or not target.exists():
        return False, "missing transcript or target file"
    try:
        extracted = extract_code(read_text_if_exists(transcript))
    except FormatError as exc:
        return False, str(exc)
    current = read_text_if_exists(target)
    return current != extracted, ""


def classify_failure(row: dict[str, str], outputs: str, extraction_mismatch: bool, format_error: str) -> tuple[str, str, str]:
    if truthy(row.get("build_ok")) and truthy(row.get("test_ok")):
        return "pass", "keep_pass", ""
    if "ng: command not found" in outputs:
        return "infra.angular_missing_ng", "exclude_infra", "Angular baseline lacks ng executable"
    if 'Could not resolve "realworld/assets/theme/styles.css"' in outputs:
        return "infra.angular_missing_theme_asset", "exclude_infra", "Angular baseline lacks RealWorld theme asset"
    if "spring-javaformat" in outputs and "PetControllerTests.java" in outputs:
        return "infra.clean_baseline_format_failure", "exclude_infra", "clean Spring feature baseline fails formatting before model output matters"
    if format_error:
        return "harness.raw_api_format_error", "exclude_or_rescore_from_transcript", format_error
    if extraction_mismatch:
        return "harness.raw_api_extraction_mismatch", "posthoc_rescore_candidate", "saved target differs from hardened extractor output"
    if "AssertionError" in outputs or "Expected output" in outputs or "DataFrame" in outputs:
        return "task.semantic_failure", "keep_task_failure", "verifier assertion failed"
    if "class, interface, enum, or record expected" in outputs or "SyntaxError" in outputs or "Unexpected token" in outputs:
        return "task.syntax_or_compile_failure", "keep_task_failure", "submitted file failed parser/compiler"
    return "task_or_harness_failure", "manual_review", "unclassified failure; inspect artifacts"


def audit_row(row: dict[str, str]) -> dict[str, str]:
    harness = row.get("harness") or "raw_api"
    workdir = row_workdir(row)
    outputs = "\n".join(
        read_text_if_exists(workdir / name, max_chars=2_000)
        for name in ("_error.txt", "_build_output.txt", "_test_output.txt")
    )
    mismatch, format_error = extraction_status({**row, "harness": harness}, workdir)
    category, disposition, notes = classify_failure(row, outputs, mismatch, format_error)
    return {
        "harness": harness,
        "task": row.get("task", ""),
        "model": row.get("model", ""),
        "run": row.get("run", ""),
        "build_ok": row.get("build_ok", ""),
        "test_ok": row.get("test_ok", ""),
        "category": category,
        "suggested_disposition": disposition,
        "extraction_mismatch": str(mismatch),
        "format_error": format_error,
        "notes": notes,
        "workdir": str(workdir),
    }


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=AUDIT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_summary(path: Path, rows: list[dict[str, str]]) -> None:
    total = len(rows)
    passes = sum(1 for row in rows if row["category"] == "pass")
    extraction_mismatches = sum(1 for row in rows if row["extraction_mismatch"] == "True")
    failing_extraction_mismatches = sum(
        1 for row in rows if row["extraction_mismatch"] == "True" and row["category"] != "pass"
    )
    format_errors = sum(1 for row in rows if row["format_error"])
    by_category = collections.Counter(row["category"] for row in rows)
    by_disposition = collections.Counter(row["suggested_disposition"] for row in rows)
    by_harness_model: dict[tuple[str, str], list[dict[str, str]]] = collections.defaultdict(list)
    for row in rows:
        by_harness_model[(row["harness"], row["model"])].append(row)

    lines = [
        "# Benchmark result audit",
        "",
        "This audit reads saved metrics/workdirs/transcripts only. It does not call models or rerun benchmark harnesses.",
        "",
        f"Total rows: {total}",
        f"Recorded pass rows: {passes}/{total}",
        f"Raw API extraction mismatches: {extraction_mismatches} total; {failing_extraction_mismatches} on non-passing rows",
        f"Raw API format errors: {format_errors}",
        "",
        "## Categories",
        "",
    ]
    for category, count in by_category.most_common():
        lines.append(f"- {category}: {count}")
    lines.extend(["", "## Suggested dispositions", ""])
    for disposition, count in by_disposition.most_common():
        lines.append(f"- {disposition}: {count}")
    lines.extend(["", "## Pass rate by harness/model", ""])
    for (harness, model), sample in sorted(by_harness_model.items()):
        ok = sum(1 for row in sample if row["category"] == "pass")
        lines.append(f"- {harness} / {model}: {ok}/{len(sample)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit saved benchmark results without invoking models.")
    parser.add_argument("--results-dir", type=Path, default=Path("results/full_combined_v3"))
    parser.add_argument("--metrics", default="metrics_all.csv")
    parser.add_argument("--out-csv", default="evaluation_audit.csv")
    parser.add_argument("--out-summary", default="evaluation_audit_summary.md")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    results_dir = args.results_dir if args.results_dir.is_absolute() else REPO_ROOT / args.results_dir
    metrics_path = results_dir / args.metrics
    with metrics_path.open(newline="", encoding="utf-8") as f:
        audit_rows = [audit_row(row) for row in csv.DictReader(f)]
    out_csv = results_dir / args.out_csv
    out_summary = results_dir / args.out_summary
    write_csv(out_csv, audit_rows)
    write_summary(out_summary, audit_rows)
    print(f"Wrote {out_csv}")
    print(f"Wrote {out_summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

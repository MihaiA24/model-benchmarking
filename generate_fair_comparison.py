#!/usr/bin/env python3
# pyright: reportReturnType=false, reportCallIssue=false, reportGeneralTypeIssues=false
"""Generate automatic benchmark comparison summaries from metrics_fair.csv."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).parent.resolve()
NUMERIC_COLUMNS = ["in_tok", "out_tok", "cost_usd", "model_calls", "latency_s", "run"]
LOW_DENOMINATOR_THRESHOLD = 30

REMEDIATION = {
    "infra.angular_missing_ng": "Run npm ci / restore node_modules in the Angular baseline so node_modules/.bin/ng exists before rerunning.",
    "infra.angular_missing_theme_asset": "Restore the RealWorld Angular theme asset realworld/assets/theme/styles.css in the clean baseline before rerunning.",
    "infra.clean_baseline_format_failure": "Fix the Spring feature clean baseline formatting/checkstyle failure before rerunning; do not count these rows as model quality.",
}


def truthy_series(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.lower().isin({"true", "1"})


def column_or_default(df: pd.DataFrame, column: str, default: str) -> pd.Series:
    return df[column] if column in df.columns else pd.Series(default, index=df.index)


def load_fair_metrics(results_dir: Path) -> pd.DataFrame:
    metrics = results_dir / "metrics_fair.csv"
    if not metrics.exists():
        raise FileNotFoundError(f"Missing fair metrics: {metrics}. Run rescore_results.py first.")
    df = pd.read_csv(metrics)
    for column in NUMERIC_COLUMNS:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    df["harness"] = df["harness"].fillna("").replace("", "raw_api")
    df["model_short"] = df["model"].astype(str).str.split("/").str[-1]
    df["fair_included_bool"] = truthy_series(column_or_default(df, "fair_included", "True"))
    df["fair_passed"] = truthy_series(column_or_default(df, "fair_build_ok", "")) & truthy_series(column_or_default(df, "fair_test_ok", ""))
    df["fair_failed"] = df["fair_included_bool"] & ~df["fair_passed"]
    df["cohort"] = df["capability_mode"].fillna("") + " / " + df["telemetry_trust"].fillna("") + " / " + df["provider_backend"].fillna("")
    cost_series = df["cost_usd"] if "cost_usd" in df.columns else pd.Series(index=df.index, dtype=float)
    in_tok_series = df["in_tok"] if "in_tok" in df.columns else pd.Series(index=df.index, dtype=float)
    out_tok_series = df["out_tok"] if "out_tok" in df.columns else pd.Series(index=df.index, dtype=float)
    df["has_cost"] = cost_series.notna()
    df["has_tokens"] = in_tok_series.notna() & out_tok_series.notna()
    return df


def load_audit_by_key(results_dir: Path) -> dict[tuple[str, str, str, str], dict[str, str]]:
    audit_path = results_dir / "evaluation_audit.csv"
    if not audit_path.exists():
        return {}
    with audit_path.open(newline="", encoding="utf-8") as f:
        return {(row["harness"], row["task"], row["model"], str(row["run"])): row for row in csv.DictReader(f)}


def load_rescore_by_key(results_dir: Path) -> dict[tuple[str, str, str, str], dict[str, str]]:
    rescore_path = results_dir / "posthoc_rescore.csv"
    if not rescore_path.exists():
        return {}
    with rescore_path.open(newline="", encoding="utf-8") as f:
        return {(row["harness"], row["task"], row["model"], str(row["run"])): row for row in csv.DictReader(f)}


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (math.nan, math.nan)
    p = successes / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    margin = z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def denominator_warning(n: int) -> str:
    if n < LOW_DENOMINATOR_THRESHOLD:
        return f"low_n<{LOW_DENOMINATOR_THRESHOLD}; directional only"
    return ""


def summary_tables(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    scored = df[df["fair_included_bool"]].copy()
    by_harness_model = (
        scored.groupby(["harness", "model", "model_short"], dropna=False)
        .agg(
            scored_runs=("fair_passed", "count"),
            fair_passes=("fair_passed", "sum"),
            fair_pass_rate=("fair_passed", "mean"),
            median_cost_usd=("cost_usd", "median"),
            cost_samples=("has_cost", "sum"),
            token_samples=("has_tokens", "sum"),
            median_latency_s=("latency_s", "median"),
            telemetry_trust=("telemetry_trust", lambda values: ", ".join(sorted({str(v) for v in values if str(v) != "nan"}))),
        )
        .reset_index()
        .sort_values(["harness", "fair_pass_rate", "model_short"], ascending=[True, False, True])
    )
    intervals = [wilson_interval(int(row["fair_passes"]), int(row["scored_runs"])) for _, row in by_harness_model.iterrows()]
    by_harness_model["pass_rate_ci_low"] = [low for low, _ in intervals]
    by_harness_model["pass_rate_ci_high"] = [high for _, high in intervals]
    by_harness_model["denominator_warning"] = [denominator_warning(int(n)) for n in by_harness_model["scored_runs"]]
    by_harness_model["cost_note"] = by_harness_model.apply(
        lambda row: "cost unavailable" if int(row["cost_samples"]) == 0 else f"{int(row['cost_samples'])}/{int(row['scored_runs'])} cost rows",
        axis=1,
    )

    by_task = (
        scored.groupby(["harness", "model", "task"], dropna=False)
        .agg(scored_runs=("fair_passed", "count"), fair_passes=("fair_passed", "sum"), fair_pass_rate=("fair_passed", "mean"))
        .reset_index()
        .sort_values(["harness", "model", "task"])
    )
    by_status = (
        df.groupby(["fair_status"], dropna=False)
        .size()
        .reset_index(name="rows")
        .sort_values(["rows", "fair_status"], ascending=[False, True])
    )
    telemetry = (
        scored.groupby(["harness", "model"], dropna=False)
        .agg(
            scored_runs=("fair_passed", "count"),
            cost_rows=("has_cost", "sum"),
            token_rows=("has_tokens", "sum"),
            telemetry_trust=("telemetry_trust", lambda values: ", ".join(sorted({str(v) for v in values if str(v) != "nan"}))),
            telemetry_note=("telemetry_note", lambda values: " | ".join(sorted({str(v) for v in values if str(v) and str(v) != "nan"}))[:500]),
        )
        .reset_index()
    )
    telemetry["cost_missing_rows"] = telemetry["scored_runs"] - telemetry["cost_rows"]
    telemetry["token_missing_rows"] = telemetry["scored_runs"] - telemetry["token_rows"]
    telemetry["telemetry_gap"] = (telemetry["cost_missing_rows"] > 0) | (telemetry["token_missing_rows"] > 0)
    return by_harness_model, by_task, by_status, telemetry


def format_rate(value: float) -> str:
    if pd.isna(value):
        return ""
    return f"{value:.0%}"


def format_ci(low: float, high: float) -> str:
    if pd.isna(low) or pd.isna(high):
        return ""
    return f"{format_rate(low)}–{format_rate(high)}"


def md_escape(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", "<br>")


def make_path(value: object) -> Path | None:
    if not value or pd.isna(value):
        return None
    path = Path(str(value))
    return path if path.is_absolute() else REPO_ROOT / path


def relative(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def evidence_excerpt(path: Path, max_chars: int = 500) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    interesting = [line for line in lines if any(token in line.lower() for token in ["error", "failed", "failure", "assert", "expected", "cannot find", "not found"])]
    chosen = interesting[:4] if interesting else lines[:4]
    return " / ".join(chosen)[:max_chars]


def failure_rows(df: pd.DataFrame, rescore_by_key: dict[tuple[str, str, str, str], dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    failures = df[df["fair_failed"]].copy().sort_values(["harness", "model", "task", "run"])
    for row in failures.to_dict(orient="records"):
        key = (str(row.get("harness", "")), str(row.get("task", "")), str(row.get("model", "")), str(row.get("run", "")))
        rescore = rescore_by_key.get(key, {})
        workdir = make_path(rescore.get("rescore_workdir") or row.get("workdir"))
        evidence_file: Path | None = None
        excerpt = ""
        if workdir:
            for name in ["_error.txt", "_test_output.txt", "_build_output.txt"]:
                candidate = workdir / name
                excerpt = evidence_excerpt(candidate)
                if excerpt:
                    evidence_file = candidate
                    break
        rows.append(
            {
                "harness": str(row.get("harness", "")),
                "model": str(row.get("model", "")),
                "task": str(row.get("task", "")),
                "run": str(row.get("run", "")),
                "fair_status": str(row.get("fair_status", "")),
                "fair_notes": str(row.get("fair_notes", "")),
                "workdir": relative(workdir),
                "transcript_path": relative(make_path(row.get("transcript_path"))),
                "evidence_file": relative(evidence_file),
                "evidence_excerpt": excerpt,
            }
        )
    return rows


def infra_rows(df: pd.DataFrame, audit_by_key: dict[tuple[str, str, str, str], dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    excluded = df[~df["fair_included_bool"]].copy().sort_values(["harness", "model", "task", "run"])
    for row in excluded.to_dict(orient="records"):
        key = (str(row.get("harness", "")), str(row.get("task", "")), str(row.get("model", "")), str(row.get("run", "")))
        audit = audit_by_key.get(key, {})
        category = audit.get("category") or str(row.get("fair_status", ""))
        rows.append(
            {
                "category": category,
                "harness": str(row.get("harness", "")),
                "model": str(row.get("model", "")),
                "task": str(row.get("task", "")),
                "run": str(row.get("run", "")),
                "notes": audit.get("notes") or str(row.get("fair_notes", "")),
                "remediation": REMEDIATION.get(category, "Inspect saved workdir/audit row before rerun."),
                "workdir": relative(make_path(row.get("workdir"))),
            }
        )
    return rows


def write_dict_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_failure_markdown(path: Path, rows: list[dict[str, str]]) -> None:
    lines = [
        "# Fair scored failure evidence",
        "",
        "Rows here are scored failures after infrastructure exclusions and post-hoc rescore. They are candidates for human inspection, not infrastructure exclusions.",
        "",
        f"Total scored failures: {len(rows)}",
        "",
        "| Harness | Model | Task | Run | Status | Evidence file | Evidence excerpt |",
        "|---|---|---|---:|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {md_escape(row['harness'])} | {md_escape(row['model'])} | {md_escape(row['task'])} | {md_escape(row['run'])} | {md_escape(row['fair_status'])} | {md_escape(row['evidence_file'])} | {md_escape(row['evidence_excerpt'])} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_infra_markdown(path: Path, rows: list[dict[str, str]]) -> None:
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (row["category"], row["remediation"])
        counts[key] = counts.get(key, 0) + 1
    lines = [
        "# Infrastructure remediation report",
        "",
        "Rows here were excluded from model-quality scoring. Fix the baseline/setup issue before any future rerun; do not reinterpret these as model failures.",
        "",
        f"Total excluded rows: {len(rows)}",
        "",
        "| Category | Rows | Remediation |",
        "|---|---:|---|",
    ]
    for (category, remediation), count in sorted(counts.items(), key=lambda item: (-item[1], item[0][0])):
        lines.append(f"| {md_escape(category)} | {count} | {md_escape(remediation)} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_markdown(path: Path, df: pd.DataFrame, by_harness_model: pd.DataFrame, by_status: pd.DataFrame, telemetry: pd.DataFrame) -> None:
    scored = df[df["fair_included_bool"]]
    excluded = df[~df["fair_included_bool"]]
    fair_passes = int(scored["fair_passed"].sum())
    lines = [
        "# Fair automatic benchmark comparison",
        "",
        "Source: `metrics_fair.csv` generated from saved `results/full_combined_v3` artifacts.",
        "This summary excludes infrastructure rows and applies local post-hoc rescore results from saved transcripts only; it does not invoke models or agent harnesses.",
        "",
        f"Total merged rows: {len(df)}",
        f"Scored rows: {len(scored)}",
        f"Excluded infrastructure/unscored rows: {len(excluded)}",
        f"Fair automatic passes: {fair_passes}/{len(scored)} ({format_rate(fair_passes / len(scored)) if len(scored) else 'n/a'})",
        "",
        "## Status counts",
        "",
        "| Fair status | Rows |",
        "|---|---:|",
    ]
    for _, row in by_status.iterrows():
        lines.append(f"| {row['fair_status']} | {int(row['rows'])} |")

    lines.extend(
        [
            "",
            "## Fair pass rate by harness/model",
            "",
            f"All current harness/model denominators are below {LOW_DENOMINATOR_THRESHOLD}; use the pass-rate ranking as directional until more runs are added or human review confirms the ordering.",
            "",
            "| Harness | Model | Scored runs | Passes | Pass rate | 95% CI | Median cost | Cost coverage | Median latency | Warning |",
            "|---|---|---:|---:|---:|---:|---:|---|---:|---|",
        ]
    )
    for _, row in by_harness_model.iterrows():
        median_cost = row["median_cost_usd"]
        median_latency = row["median_latency_s"]
        pass_rate = float(row["fair_pass_rate"])
        cost = "unavailable" if pd.isna(median_cost) else f"${float(median_cost):.4f}"
        latency = "" if pd.isna(median_latency) else f"{float(median_latency):.1f}s"
        lines.append(
            f"| {row['harness']} | {row['model']} | {int(row['scored_runs'])} | {int(row['fair_passes'])} | {format_rate(pass_rate)} | {format_ci(float(row['pass_rate_ci_low']), float(row['pass_rate_ci_high']))} | {cost} | {row['cost_note']} | {latency} | {row['denominator_warning']} |"
        )

    gaps = telemetry[telemetry["telemetry_gap"]]
    lines.extend(
        [
            "",
            "## Telemetry gaps",
            "",
            "Rows with missing token/cost telemetry remain valid for pass-rate comparison but must be excluded from quality/cost conclusions until exact usage is available.",
            "",
            "| Harness | Model | Scored runs | Missing cost rows | Missing token rows | Telemetry trust | Note |",
            "|---|---|---:|---:|---:|---|---|",
        ]
    )
    for _, row in gaps.iterrows():
        lines.append(
            f"| {row['harness']} | {row['model']} | {int(row['scored_runs'])} | {int(row['cost_missing_rows'])} | {int(row['token_missing_rows'])} | {md_escape(row['telemetry_trust'])} | {md_escape(row['telemetry_note'])} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate fair automatic comparison summaries from metrics_fair.csv.")
    parser.add_argument("--results-dir", type=Path, default=Path("results/full_combined_v3"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    results_dir = args.results_dir if args.results_dir.is_absolute() else REPO_ROOT / args.results_dir
    df = load_fair_metrics(results_dir)
    audit_by_key = load_audit_by_key(results_dir)
    rescore_by_key = load_rescore_by_key(results_dir)
    by_harness_model, by_task, by_status, telemetry = summary_tables(df)
    failures = failure_rows(df, rescore_by_key)
    infra = infra_rows(df, audit_by_key)

    by_harness_model.to_csv(results_dir / "fair_comparison_by_harness_model.csv", index=False)
    by_task.to_csv(results_dir / "fair_comparison_by_task.csv", index=False)
    by_status.to_csv(results_dir / "fair_comparison_status_counts.csv", index=False)
    telemetry.to_csv(results_dir / "fair_comparison_telemetry_gaps.csv", index=False)
    write_dict_csv(results_dir / "fair_failure_evidence.csv", failures)
    write_failure_markdown(results_dir / "fair_failure_evidence.md", failures)
    write_dict_csv(results_dir / "infra_remediation_report.csv", infra)
    write_infra_markdown(results_dir / "infra_remediation_report.md", infra)
    write_markdown(results_dir / "fair_comparison_summary.md", df, by_harness_model, by_status, telemetry)

    print(f"Wrote {results_dir / 'fair_comparison_summary.md'}")
    print(f"Wrote {results_dir / 'fair_comparison_by_harness_model.csv'}")
    print(f"Wrote {results_dir / 'fair_comparison_by_task.csv'}")
    print(f"Wrote {results_dir / 'fair_comparison_status_counts.csv'}")
    print(f"Wrote {results_dir / 'fair_comparison_telemetry_gaps.csv'}")
    print(f"Wrote {results_dir / 'fair_failure_evidence.md'}")
    print(f"Wrote {results_dir / 'infra_remediation_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
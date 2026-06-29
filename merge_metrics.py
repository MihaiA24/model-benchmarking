#!/usr/bin/env python3
"""Combina metrics CSV de uno o varios results dirs."""

from __future__ import annotations

import argparse
import csv
import pathlib
import random
import shutil
import string
from collections import defaultdict

from benchmark.models import opencode_go_selector

DEFAULT_RESULTS = pathlib.Path("results/2_run")
METRIC_FILENAMES = [
    "metrics.csv",  # piloto Spring Boot bugs (legacy)
    "metrics_springboot.csv",
    "metrics_angular.csv",
    "metrics_react.csv",
    "metrics_data.csv",
]

FIELDNAMES = [
    "harness",
    "task",
    "model",
    "adapter_model",
    "provider_backend",
    "api_backend",
    "pricing_model",
    "run",
    "capability_mode",
    "telemetry_trust",
    "tool_set",
    "build_ok",
    "test_ok",
    "in_tok",
    "out_tok",
    "cost_usd",
    "model_calls",
    "telemetry_note",
    "latency_s",
    "workdir",
    "transcript_path",
    "error",
]

def default_adapter_model(harness: str, model: str, telemetry_note: str = "") -> str:
    if harness != "raw_api" or "opencode_go" in telemetry_note:
        return opencode_go_selector(model) or model
    return model


def default_provider_backend(harness: str, adapter_model: str, telemetry_note: str = "") -> str:
    if adapter_model.startswith("opencode-go/") or "opencode_go" in telemetry_note:
        return "opencode-go"
    if harness == "raw_api" and "openrouter" in telemetry_note:
        return adapter_model.split("/", 1)[0] if "/" in adapter_model else "openrouter"
    return adapter_model.split("/", 1)[0] if "/" in adapter_model else ""


def default_api_backend(harness: str, provider_backend: str, telemetry_note: str = "") -> str:
    if "opencode_go_chat" in telemetry_note:
        return "opencode_go_chat"
    if "openrouter_usage" in telemetry_note:
        return "openrouter_chat"
    if harness == "raw_api":
        return "opencode_go_chat" if provider_backend == "opencode-go" else "openrouter_chat"
    if harness in {"omp", "opencode", "hermes"}:
        return f"{harness}_cli"
    return ""


def default_pricing_model(harness: str, model: str, adapter_model: str, provider_backend: str) -> str:
    if provider_backend == "opencode-go":
        return opencode_go_selector(adapter_model) or opencode_go_selector(model) or adapter_model or model
    return adapter_model or model


def normalize(row: dict[str, str]) -> dict[str, str]:
    out = {field: row.get(field, "") for field in FIELDNAMES}
    out["harness"] = out["harness"] or "raw_api"
    if not out["adapter_model"]:
        out["adapter_model"] = default_adapter_model(out["harness"], out["model"], out.get("telemetry_note", ""))
    if not out["provider_backend"]:
        out["provider_backend"] = default_provider_backend(out["harness"], out["adapter_model"], out.get("telemetry_note", ""))
    if not out["api_backend"]:
        out["api_backend"] = default_api_backend(out["harness"], out["provider_backend"], out.get("telemetry_note", ""))
    if not out["pricing_model"]:
        out["pricing_model"] = default_pricing_model(out["harness"], out["model"], out["adapter_model"], out["provider_backend"])
    if not out["transcript_path"] and out.get("workdir"):
        out["transcript_path"] = str(pathlib.Path(out["workdir"]) / "_raw_response.txt")
    if not out["capability_mode"]:
        out["capability_mode"] = "single_shot" if out["harness"] == "raw_api" else "agent_iterated"
    if not out["telemetry_trust"]:
        out["telemetry_trust"] = {"raw_api": "exact", "omp": "parsed", "opencode": "parsed", "hermes": "blank"}.get(out["harness"], "")
    if not out["tool_set"] and out["harness"] == "omp":
        out["tool_set"] = "read,bash,edit,write,grep,find,lsp"
    if not out["tool_set"] and out["harness"] == "hermes":
        out["tool_set"] = "terminal,file"
    if (
        not out["model_calls"]
        and out["harness"] == "raw_api"
        and out.get("test_ok") not in ("", "ERROR", None)
    ):
        out["model_calls"] = "1"
        out["telemetry_note"] = (
            out["telemetry_note"] or "legacy raw_api row; one OpenRouter request"
        )
    return out


def row_key(row: dict[str, str]) -> tuple[str, str, str, int]:
    try:
        run = int(row.get("run", "0"))
    except ValueError:
        run = 0
    return (
        row.get("harness", "raw_api"),
        row.get("task", ""),
        row.get("model", ""),
        run,
    )


def metric_sources(results_dirs: list[pathlib.Path]) -> list[pathlib.Path]:
    return [results_dir / filename for results_dir in results_dirs for filename in METRIC_FILENAMES]


def copy_artifacts(row: dict[str, str], out_dir: pathlib.Path) -> dict[str, str]:
    workdir_value = row.get("workdir", "")
    if not workdir_value:
        return row
    workdir = pathlib.Path(workdir_value)
    if not workdir.exists() or not workdir.is_dir():
        return row

    dest = out_dir / workdir.name
    if workdir.resolve() != dest.resolve() and not dest.exists() and not dest.is_symlink():
        shutil.copytree(workdir, dest, symlinks=True)

    transcript_value = row.get("transcript_path", "")
    if transcript_value:
        transcript = pathlib.Path(transcript_value)
        try:
            row["transcript_path"] = str(dest / transcript.relative_to(workdir))
        except ValueError:
            row["transcript_path"] = str(dest / transcript.name)
    else:
        row["transcript_path"] = str(dest / "_raw_response.txt")
    row["workdir"] = str(dest)
    return row


def load_rows(results_dirs: list[pathlib.Path], out_dir: pathlib.Path, *, copy_workdirs: bool) -> tuple[list[dict[str, str]], dict[str, list[dict[str, str]]]]:
    by_key: dict[tuple[str, str, str, int], dict[str, str]] = {}
    key_to_metric: dict[tuple[str, str, str, int], str] = {}
    for src in metric_sources(results_dirs):
        if not src.exists():
            print(f"  SKIP (no existe): {src}")
            continue
        count = 0
        with open(src, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                normalized = normalize(row)
                if copy_workdirs:
                    normalized = copy_artifacts(normalized, out_dir)
                key = row_key(normalized)
                by_key[key] = normalized
                key_to_metric[key] = src.name
                count += 1
        print(f"  OK: {src} ({count} filas leidas)")

    rows_by_metric: dict[str, list[dict[str, str]]] = defaultdict(list)
    rows = []
    for key in sorted(by_key):
        row = by_key[key]
        rows.append(row)
        rows_by_metric[key_to_metric[key]].append(row)
    return rows, rows_by_metric


def write_csv(path: pathlib.Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def truthy(value) -> bool:
    return value in ("True", True, "true", "1", 1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Merge benchmark metrics from one or more result dirs.")
    parser.add_argument("--results-dir", nargs="+", type=pathlib.Path, default=[DEFAULT_RESULTS], help="One or more source result directories")
    parser.add_argument("--out-dir", type=pathlib.Path, help="Combined output directory; defaults to the only source dir or results/combined")
    parser.add_argument("--copy-artifacts", action="store_true", help="Copy per-run workdirs into --out-dir and rewrite workdir/transcript_path columns")
    return parser


def output_dir_for(results_dirs: list[pathlib.Path], out_dir: pathlib.Path | None) -> pathlib.Path:
    if out_dir:
        return out_dir
    if len(results_dirs) == 1:
        return results_dirs[0]
    return pathlib.Path("results/combined")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out_dir = output_dir_for(args.results_dir, args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows, rows_by_metric = load_rows(args.results_dir, out_dir, copy_workdirs=args.copy_artifacts)
    if not rows:
        print("No hay datos que mergear.")
        return 1

    for filename, metric_rows in sorted(rows_by_metric.items()):
        write_csv(out_dir / filename, metric_rows)

    out_all = out_dir / "metrics_all.csv"
    out_anon = out_dir / "metrics_anon.csv"
    out_map = out_dir / "model_mapping.csv"  # NO mostrar hasta el final

    write_csv(out_all, rows)
    print(f"\nMerge completo: {out_all} ({len(rows)} filas)")

    models = sorted({row["model"] for row in rows})
    letters = list(string.ascii_uppercase[: len(models)])
    random.shuffle(letters)
    mapping = {model: f"Modelo {letter}" for model, letter in zip(models, letters)}

    anon_rows = [{**row, "model": mapping[row["model"]]} for row in rows]
    write_csv(out_anon, anon_rows)
    print(f"Anonimizado:    {out_anon}")

    with open(out_map, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["alias", "model_real"])
        for model, alias in mapping.items():
            writer.writerow([alias, model])
    print(
        f"Mapping guardado en {out_map} — NO revelar hasta el final de la evaluacion humana"
    )

    print("\nResumen por harness/modelo:")
    for harness in sorted({row["harness"] for row in rows}):
        for model in models:
            sample = [
                row
                for row in rows
                if row["harness"] == harness and row["model"] == model
            ]
            if not sample:
                continue
            ok = sum(1 for row in sample if truthy(row.get("test_ok")))
            costs = [
                float(row["cost_usd"])
                for row in sample
                if row.get("cost_usd") not in ("", "ERROR", "0", 0)
            ]
            latencies = [
                float(row["latency_s"])
                for row in sample
                if row.get("latency_s") not in ("", "ERROR", "0", 0)
            ]
            call_counts = [
                int(row["model_calls"])
                for row in sample
                if row.get("model_calls", "").isdigit()
            ]
            avg_cost = sum(costs) / len(costs) if costs else 0
            avg_lat = sum(latencies) / len(latencies) if latencies else 0
            avg_calls = sum(call_counts) / len(call_counts) if call_counts else 0
            print(
                f"  {harness:8} | {mapping[model]} ({model}): {ok}/{len(sample)} tests ok | coste medio ${avg_cost:.4f} | llamadas medias {avg_calls:.1f} | latencia media {avg_lat:.1f}s"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

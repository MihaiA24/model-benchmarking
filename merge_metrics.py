#!/usr/bin/env python3
"""Combina metrics CSV en results/metrics_all.csv con modelos anonimizados."""

from __future__ import annotations

import csv
import pathlib
import random
import string

RESULTS = pathlib.Path("results")
SOURCES = [
    RESULTS / "metrics.csv",            # piloto Spring Boot bugs (legacy)
    RESULTS / "metrics_springboot.csv",
    RESULTS / "metrics_angular.csv",
    RESULTS / "metrics_react.csv",
    RESULTS / "metrics_data.csv",
]
OUT_ALL = RESULTS / "metrics_all.csv"
OUT_ANON = RESULTS / "metrics_anon.csv"
OUT_MAP = RESULTS / "model_mapping.csv"  # NO mostrar hasta el final

FIELDNAMES = [
    "harness",
    "task",
    "model",
    "run",
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


def normalize(row: dict[str, str]) -> dict[str, str]:
    out = {field: row.get(field, "") for field in FIELDNAMES}
    out["harness"] = out["harness"] or "raw_api"
    if not out["transcript_path"] and out.get("workdir"):
        out["transcript_path"] = str(pathlib.Path(out["workdir"]) / "_raw_response.txt")
    if not out["model_calls"] and out["harness"] == "raw_api" and out.get("test_ok") not in ("", "ERROR", None):
        out["model_calls"] = "1"
        out["telemetry_note"] = out["telemetry_note"] or "legacy raw_api row; one OpenRouter request"
    return out


def row_key(row: dict[str, str]) -> tuple[str, str, str, int]:
    try:
        run = int(row.get("run", "0"))
    except ValueError:
        run = 0
    return (row.get("harness", "raw_api"), row.get("task", ""), row.get("model", ""), run)


def load_rows() -> list[dict[str, str]]:
    by_key: dict[tuple[str, str, str, int], dict[str, str]] = {}
    for src in SOURCES:
        if not src.exists():
            print(f"  SKIP (no existe): {src}")
            continue
        count = 0
        with open(src, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                normalized = normalize(row)
                by_key[row_key(normalized)] = normalized
                count += 1
        print(f"  OK: {src.name} ({count} filas leidas)")
    return [by_key[key] for key in sorted(by_key)]


def write_csv(path: pathlib.Path, rows: list[dict[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def truthy(value) -> bool:
    return value in ("True", True, "true", "1", 1)


def main():
    rows = load_rows()
    if not rows:
        print("No hay datos que mergear.")
        return

    write_csv(OUT_ALL, rows)
    print(f"\nMerge completo: {OUT_ALL} ({len(rows)} filas)")

    models = sorted({row["model"] for row in rows})
    letters = list(string.ascii_uppercase[:len(models)])
    random.shuffle(letters)
    mapping = {model: f"Modelo {letter}" for model, letter in zip(models, letters)}

    anon_rows = [{**row, "model": mapping[row["model"]]} for row in rows]
    write_csv(OUT_ANON, anon_rows)
    print(f"Anonimizado:    {OUT_ANON}")

    with open(OUT_MAP, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["alias", "model_real"])
        for model, alias in mapping.items():
            writer.writerow([alias, model])
    print(f"Mapping guardado en {OUT_MAP} — NO revelar hasta el final de la evaluacion humana")

    print("\nResumen por harness/modelo:")
    for harness in sorted({row["harness"] for row in rows}):
        for model in models:
            sample = [row for row in rows if row["harness"] == harness and row["model"] == model]
            if not sample:
                continue
            ok = sum(1 for row in sample if truthy(row.get("test_ok")))
            costs = [float(row["cost_usd"]) for row in sample if row.get("cost_usd") not in ("", "ERROR", "0", 0)]
            latencies = [float(row["latency_s"]) for row in sample if row.get("latency_s") not in ("", "ERROR", "0", 0)]
            call_counts = [int(row["model_calls"]) for row in sample if row.get("model_calls", "").isdigit()]
            avg_cost = sum(costs) / len(costs) if costs else 0
            avg_lat = sum(latencies) / len(latencies) if latencies else 0
            avg_calls = sum(call_counts) / len(call_counts) if call_counts else 0
            print(f"  {harness:8} | {mapping[model]} ({model}): {ok}/{len(sample)} tests ok | coste medio ${avg_cost:.4f} | llamadas medias {avg_calls:.1f} | latencia media {avg_lat:.1f}s")


if __name__ == "__main__":
    main()

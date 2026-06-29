#!/usr/bin/env python3
"""Genera el paquete de revisión humana CIEGO desde métricas justas.

Por defecto usa `results/full_combined_v3/metrics_fair.csv` si existe; si no,
cae a `metrics_all.csv` para compatibilidad con tandas antiguas. Las filas de
infraestructura excluidas por `fair_included=False` no se envían a revisión
humana salvo que se pase `--include-excluded`.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
import re
import shutil

REPO_ROOT = Path(__file__).parent.resolve()
DEFAULT_RESULTS_DIR = Path("results/full_combined_v3")
HR = REPO_ROOT / "human_review"
DEFAULT_BLIND = HR / "respuestas_ciegas"
DEFAULT_OUT = HR / "plantilla_puntuacion.csv"

STACK_DIR = {
    "Spring Boot": "springboot",
    "Angular": "angular",
    "React": "react",
    "Datos": "datos",
}

TASK_META = {
    "bug1-petvalidator": ("Spring Boot", "Bug-fix"),
    "bug2-ownercontroller": ("Spring Boot", "Bug-fix"),
    "sb-feat1-name-length": ("Spring Boot", "Feature"),
    "ng-bug1-missing-input": ("Angular", "Bug-fix"),
    "ng-feat1-reading-time": ("Angular", "Feature"),
    "ng-feat2-service-search": ("Angular", "Feature"),
    "re-bug1-favorite-count": ("React", "Bug-fix"),
    "re-feat1-reading-time": ("React", "Feature"),
    "re-feat2-author-filter": ("React", "Feature"),
    "data-bug1-sales-genre": ("Datos", "Bug-fix"),
    "data-feat1-customer-ranking": ("Datos", "Feature"),
}


def truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"true", "1", "yes"}


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def default_results_dir() -> Path:
    preferred = resolve_path(DEFAULT_RESULTS_DIR)
    return preferred if preferred.exists() else REPO_ROOT / "results"


def resolve_metrics_path(results_dir: Path, metrics_arg: Path | None) -> Path:
    if metrics_arg is not None:
        return resolve_path(metrics_arg)
    fair = results_dir / "metrics_fair.csv"
    if fair.exists():
        return fair
    return results_dir / "metrics_all.csv"


def load_mapping(results_dir: Path) -> dict[str, str]:
    mapping_path = results_dir / "model_mapping.csv"
    if not mapping_path.exists():
        mapping_path = REPO_ROOT / "results" / "model_mapping.csv"
    real2alias: dict[str, str] = {}
    with mapping_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            real2alias[row["model_real"]] = row["alias"]
    return real2alias


def metric_build_ok(row: dict[str, str]) -> str:
    return row.get("fair_build_ok") or row.get("build_ok") or ""


def metric_test_ok(row: dict[str, str]) -> str:
    return row.get("fair_test_ok") or row.get("test_ok") or ""


def fair_included(row: dict[str, str]) -> bool:
    if "fair_included" in row and row.get("fair_included") != "":
        return truthy(row.get("fair_included"))
    return row.get("test_ok") not in {"ERROR", "", None}


def fair_status(row: dict[str, str]) -> str:
    if row.get("fair_status"):
        return row["fair_status"]
    return "pass" if truthy(metric_build_ok(row)) and truthy(metric_test_ok(row)) else "task_or_harness_failure"


def pick_run(rows: list[dict[str, str]]) -> dict[str, str]:
    """Prefiere estado justo verde; a igualdad, run más bajo."""

    def key(row: dict[str, str]) -> tuple[int, int]:
        passed = 0 if truthy(metric_build_ok(row)) and truthy(metric_test_ok(row)) else 1
        try:
            run = int(row.get("run", "99"))
        except ValueError:
            run = 99
        return (passed, run)

    return sorted(rows, key=key)[0]


def candidate_path(value: str) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def response_path(row: dict[str, str], results_dir: Path) -> Path:
    transcript = candidate_path(row.get("transcript_path", ""))
    if transcript:
        return transcript
    workdir = candidate_path(row.get("workdir", ""))
    if workdir:
        return workdir / "_raw_response.txt"

    task = row["task"]
    model = row["model"]
    run = row["run"]
    harness = row.get("harness") or "raw_api"
    legacy_label = f"{task}__{model.replace('/', '_')}__r{run}"
    harness_label = f"{harness}__{task}__{model.replace('/', '_')}__r{run}"
    legacy = results_dir / legacy_label / "_raw_response.txt"
    return legacy if legacy.exists() else results_dir / harness_label / "_raw_response.txt"


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def display_note(note: str) -> str:
    return note.replace(str(REPO_ROOT) + "/", "")


def load_review_rows(metrics_path: Path, *, include_excluded: bool) -> list[dict[str, str]]:
    with metrics_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    review_rows: list[dict[str, str]] = []
    for row in rows:
        if not include_excluded and not fair_included(row):
            continue
        if metric_test_ok(row) in {"ERROR", "", None} and not row.get("fair_status"):
            continue
        row["harness"] = row.get("harness") or "raw_api"
        review_rows.append(row)
    return review_rows


def write_review_pack(
    rows: list[dict[str, str]],
    *,
    results_dir: Path,
    metrics_path: Path,
    out_path: Path,
    blind_dir: Path,
) -> list[dict[str, str]]:
    real2alias = load_mapping(results_dir)
    groups: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    for row in rows:
        groups.setdefault((row["harness"], row["model"], row["task"]), []).append(row)

    if blind_dir.exists():
        shutil.rmtree(blind_dir)
    blind_dir.mkdir(parents=True)

    out_rows: list[dict[str, str]] = []
    for (harness, model, task), group in groups.items():
        alias = real2alias.get(model, model)
        chosen = pick_run(group)
        src = response_path(chosen, results_dir)
        stack, tipo = TASK_META.get(task, ("?", "?"))
        subdir = STACK_DIR.get(stack, "otros")
        blind_name = f"{slug(alias)}__{slug(harness)}__{task}.txt"
        dst_dir = blind_dir / subdir
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / blind_name
        if src.exists():
            shutil.copyfile(src, dst)
        else:
            dst.write_text(f"[respuesta no encontrada: {src}]\n", encoding="utf-8")

        out_rows.append(
            {
                "modelo": alias,
                "harness": harness,
                "tarea": task,
                "stack": stack,
                "tipo": tipo,
                "build_ok_auto": metric_build_ok(chosen),
                "test_ok_auto": metric_test_ok(chosen),
                "fair_status": fair_status(chosen),
                "fair_included": str(fair_included(chosen)),
                "automatic_source": display_path(metrics_path),
                "fair_notes": display_note(chosen.get("fair_notes", "")),
                "archivo_respuesta": display_path(dst),
                "eje1_correctitud": "",
                "eje2_calidad": "",
                "eje3_seguridad": "",
                "eje4_instrucciones": "",
                "eje5_esfuerzo": "",
                "comentarios": "",
            }
        )

    out_rows.sort(key=lambda row: (row["tarea"], row["harness"], row["modelo"]))
    fields = [
        "modelo",
        "harness",
        "tarea",
        "stack",
        "tipo",
        "build_ok_auto",
        "test_ok_auto",
        "fair_status",
        "fair_included",
        "automatic_source",
        "fair_notes",
        "archivo_respuesta",
        "eje1_correctitud",
        "eje2_calidad",
        "eje3_seguridad",
        "eje4_instrucciones",
        "eje5_esfuerzo",
        "comentarios",
    ]
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(out_rows)
    return out_rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Genera la plantilla de revisión humana desde métricas justas.")
    parser.add_argument("--results-dir", type=Path, default=None, help="Directorio de resultados; por defecto results/full_combined_v3 si existe.")
    parser.add_argument("--metrics", type=Path, default=None, help="CSV explícito; por defecto metrics_fair.csv si existe, si no metrics_all.csv.")
    parser.add_argument("--include-excluded", action="store_true", help="Incluye filas fair_included=False (infraestructura) en la revisión humana.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--blind-dir", type=Path, default=DEFAULT_BLIND)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    results_dir = resolve_path(args.results_dir) if args.results_dir else default_results_dir()
    metrics_path = resolve_metrics_path(results_dir, args.metrics)
    rows = load_review_rows(metrics_path, include_excluded=args.include_excluded)
    out_rows = write_review_pack(
        rows,
        results_dir=results_dir,
        metrics_path=metrics_path,
        out_path=resolve_path(args.out),
        blind_dir=resolve_path(args.blind_dir),
    )

    n_models = len({row["modelo"] for row in out_rows})
    n_harnesses = len({row["harness"] for row in out_rows})
    print(f"Fuente automática: {display_path(metrics_path)}")
    print(f"Plantilla: {display_path(resolve_path(args.out))} ({len(out_rows)} filas, {n_models} modelos, {n_harnesses} harnesses)")
    print(f"Respuestas ciegas: {display_path(resolve_path(args.blind_dir))}/ ({len(list(resolve_path(args.blind_dir).rglob('*.txt')))} ficheros)")
    print("Las rutas NO contienen el nombre real del modelo -> doble ciego correcto.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
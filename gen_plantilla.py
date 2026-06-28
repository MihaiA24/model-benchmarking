#!/usr/bin/env python3
"""Genera el paquete de revision humana CIEGO a partir de metrics_all.csv.

- Lee el mapping real -> alias de results/model_mapping.csv (lo crea merge_metrics.py).
- Por cada (harness, modelo, tarea) elige UN run representativo.
- Copia el artefacto de respuesta a human_review/respuestas_ciegas/.
- Escribe human_review/plantilla_puntuacion.csv con columnas de rubrica vacias.

Ejecutar DESPUES de merge_metrics.py:
    python gen_plantilla.py
"""
from __future__ import annotations

import csv
import pathlib
import re
import shutil

RESULTS = pathlib.Path("results")
HR = pathlib.Path("human_review")
BLIND = HR / "respuestas_ciegas"
METRICS = RESULTS / "metrics_all.csv"
MAPPING = RESULTS / "model_mapping.csv"
OUT = HR / "plantilla_puntuacion.csv"

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


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")


def load_mapping():
    real2alias = {}
    with open(MAPPING, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            real2alias[row["model_real"]] = row["alias"]
    return real2alias


def pick_run(rows):
    """Prefiere test verde; a igualdad, run mas bajo."""
    def key(row):
        passed = 0 if row.get("test_ok") in ("True", True, "true", "1") else 1
        try:
            run = int(row["run"])
        except (ValueError, KeyError):
            run = 99
        return (passed, run)
    return sorted(rows, key=key)[0]


def response_path(row: dict[str, str]) -> pathlib.Path:
    if row.get("transcript_path"):
        return pathlib.Path(row["transcript_path"])
    if row.get("workdir"):
        return pathlib.Path(row["workdir"]) / "_raw_response.txt"
    task = row["task"]
    model = row["model"]
    run = row["run"]
    harness = row.get("harness") or "raw_api"
    legacy_label = f"{task}__{model.replace('/', '_')}__r{run}"
    harness_label = f"{harness}__{task}__{model.replace('/', '_')}__r{run}"
    legacy = RESULTS / legacy_label / "_raw_response.txt"
    return legacy if legacy.exists() else RESULTS / harness_label / "_raw_response.txt"


def main():
    real2alias = load_mapping()
    rows = list(csv.DictReader(open(METRICS, newline="", encoding="utf-8")))

    groups = {}
    for row in rows:
        if row.get("test_ok") in ("ERROR", "", None):
            continue
        row["harness"] = row.get("harness") or "raw_api"
        groups.setdefault((row["harness"], row["model"], row["task"]), []).append(row)

    if BLIND.exists():
        shutil.rmtree(BLIND)
    BLIND.mkdir(parents=True)

    out_rows = []
    for (harness, model, task), group in groups.items():
        alias = real2alias.get(model, model)
        chosen = pick_run(group)
        src = response_path(chosen)
        stack, tipo = TASK_META.get(task, ("?", "?"))
        subdir = STACK_DIR.get(stack, "otros")
        blind_name = f"{slug(alias)}__{slug(harness)}__{task}.txt"
        (BLIND / subdir).mkdir(parents=True, exist_ok=True)
        dst = BLIND / subdir / blind_name
        if src.exists():
            shutil.copyfile(src, dst)
        else:
            dst.write_text(f"[respuesta no encontrada: {src}]\n", encoding="utf-8")
        out_rows.append({
            "modelo": alias,
            "harness": harness,
            "tarea": task,
            "stack": stack,
            "tipo": tipo,
            "test_ok_auto": chosen.get("test_ok"),
            "archivo_respuesta": f"human_review/respuestas_ciegas/{subdir}/{blind_name}",
            "eje1_correctitud": "",
            "eje2_calidad": "",
            "eje3_seguridad": "",
            "eje4_instrucciones": "",
            "eje5_esfuerzo": "",
            "comentarios": "",
        })

    out_rows.sort(key=lambda row: (row["tarea"], row["harness"], row["modelo"]))
    fields = [
        "modelo",
        "harness",
        "tarea",
        "stack",
        "tipo",
        "test_ok_auto",
        "archivo_respuesta",
        "eje1_correctitud",
        "eje2_calidad",
        "eje3_seguridad",
        "eje4_instrucciones",
        "eje5_esfuerzo",
        "comentarios",
    ]
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(out_rows)

    n_models = len({row["modelo"] for row in out_rows})
    n_harnesses = len({row["harness"] for row in out_rows})
    print(f"Plantilla: {OUT} ({len(out_rows)} filas, {n_models} modelos, {n_harnesses} harnesses)")
    print(f"Respuestas ciegas: {BLIND}/ ({len(list(BLIND.rglob('*.txt')))} ficheros)")
    print("Las rutas NO contienen el nombre real del modelo -> doble ciego correcto.")


if __name__ == "__main__":
    main()

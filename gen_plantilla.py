#!/usr/bin/env python3
"""Genera el paquete de revision humana CIEGO a partir de metrics_all.csv.

- Lee el mapping real -> alias de results/model_mapping.csv (lo crea merge_metrics.py).
- Por cada (modelo, tarea) elige UN run representativo (prefiere test verde, run mas bajo).
- Copia su _raw_response.txt a human_review/respuestas_ciegas/<Alias>__<tarea>.txt
  (nombre SIN el modelo real -> doble ciego de verdad; la ruta original lo filtraba).
- Escribe human_review/plantilla_puntuacion.csv: una fila por (alias, tarea) con las
  5 columnas de la rubrica vacias para que las rellenen los revisores.

Ejecutar DESPUES de merge_metrics.py:
    python gen_plantilla.py
"""
import csv, pathlib, shutil, re

RESULTS = pathlib.Path("results")
HR = pathlib.Path("human_review")
BLIND = HR / "respuestas_ciegas"
METRICS = RESULTS / "metrics_all.csv"
MAPPING = RESULTS / "model_mapping.csv"
OUT = HR / "plantilla_puntuacion.csv"

# stack -> nombre de subcarpeta (una carpeta de respuestas por framework)
STACK_DIR = {
    "Spring Boot": "springboot",
    "Angular": "angular",
    "React": "react",
    "Datos": "datos",
}

# Metadatos de las 11 tareas (stack, tipo) para contexto del revisor.
TASK_META = {
    "bug1-petvalidator":          ("Spring Boot", "Bug-fix"),
    "bug2-ownercontroller":       ("Spring Boot", "Bug-fix"),
    "sb-feat1-name-length":       ("Spring Boot", "Feature"),
    "ng-bug1-missing-input":      ("Angular",     "Bug-fix"),
    "ng-feat1-reading-time":      ("Angular",     "Feature"),
    "ng-feat2-service-search":    ("Angular",     "Feature"),
    "re-bug1-favorite-count":     ("React",       "Bug-fix"),
    "re-feat1-reading-time":      ("React",       "Feature"),
    "re-feat2-author-filter":     ("React",       "Feature"),
    "data-bug1-sales-genre":      ("Datos",       "Bug-fix"),
    "data-feat1-customer-ranking":("Datos",       "Feature"),
}


def load_mapping():
    real2alias = {}
    with open(MAPPING, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            real2alias[row["model_real"]] = row["alias"]
    return real2alias


def pick_run(rows):
    """De los runs de un (modelo, tarea), elige el representativo:
    prefiere test verde; a igualdad, el run mas bajo."""
    def key(r):
        passed = 0 if r.get("test_ok") in ("True", True) else 1
        try:
            rn = int(r["run"])
        except (ValueError, KeyError):
            rn = 99
        return (passed, rn)
    return sorted(rows, key=key)[0]


def main():
    real2alias = load_mapping()
    rows = list(csv.DictReader(open(METRICS, newline="", encoding="utf-8")))

    # agrupar por (modelo_real, tarea)
    groups = {}
    for r in rows:
        if r.get("test_ok") in ("ERROR", "", None):
            continue
        groups.setdefault((r["model"], r["task"]), []).append(r)

    if BLIND.exists():
        shutil.rmtree(BLIND)
    BLIND.mkdir(parents=True)

    out_rows = []
    for (model, task), grp in groups.items():
        alias = real2alias.get(model, model)
        chosen = pick_run(grp)
        run = chosen["run"]
        # ruta del raw response original (contiene el nombre real -> NO se entrega)
        label = f"{task}__{model.replace('/', '_')}__r{run}"
        src = RESULTS / label / "_raw_response.txt"
        stack, tipo = TASK_META.get(task, ("?", "?"))
        subdir = STACK_DIR.get(stack, "otros")
        alias_slug = alias.replace(" ", "")
        blind_name = f"{alias_slug}__{task}.txt"
        (BLIND / subdir).mkdir(parents=True, exist_ok=True)
        dst = BLIND / subdir / blind_name
        if src.exists():
            shutil.copyfile(src, dst)
        out_rows.append({
            "modelo": alias,
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

    # orden: por tarea y luego por alias, para que el revisor no agrupe por modelo
    out_rows.sort(key=lambda r: (r["tarea"], r["modelo"]))
    fields = ["modelo", "tarea", "stack", "tipo", "test_ok_auto", "archivo_respuesta",
              "eje1_correctitud", "eje2_calidad", "eje3_seguridad",
              "eje4_instrucciones", "eje5_esfuerzo", "comentarios"]
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out_rows)

    n_models = len({r["modelo"] for r in out_rows})
    print(f"Plantilla: {OUT} ({len(out_rows)} filas, {n_models} modelos)")
    print(f"Respuestas ciegas: {BLIND}/ ({len(list(BLIND.glob('*.txt')))} ficheros)")
    print("Las rutas NO contienen el nombre real del modelo -> doble ciego correcto.")


if __name__ == "__main__":
    main()

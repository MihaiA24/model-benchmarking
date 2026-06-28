#!/usr/bin/env python3
"""Genera human_review/form_data.json para el Apps Script que crea los Google Forms.

Lee la plantilla (anonimizada) + los ficheros ciegos y produce un JSON con:
- objetivo + instrucciones + rubrica
- frameworks -> lista de respuestas {modelo, harness, tarea, tipo, test_ok, codigo}

Ejecutar despues de gen_plantilla.py:
    python gen_form_data.py
"""
import csv, json, pathlib
from collections import defaultdict

HR = pathlib.Path("human_review")
PLANTILLA = HR / "plantilla_puntuacion.csv"
OUT = HR / "form_data.json"

OBJETIVO = (
    "Estamos eligiendo qué combinación de modelo y harness de IA adoptará la empresa "
    "para el desarrollo diario. La capa automática ya midió si el código compila y pasa "
    "los tests; tú vas a medir lo que los tests NO capturan: calidad, idiomaticidad "
    "y seguridad. Tu criterio decide el resultado final."
)

INSTRUCCIONES = (
    "Cómo puntuar:\n"
    "• Para cada respuesta verás el código o artefacto que generó una combinación modelo+harness.\n"
    "• Puntúa los 5 ejes de 1 (muy malo) a 5 (excelente).\n"
    "• Si el test automático falló, tenlo en cuenta en el eje 1 (correctitud).\n"
    "• No intentes adivinar qué modelo real hay detrás del alias. Sé consistente entre respuestas.\n"
    "• Si algo te chirría, déjalo en el comentario final de cada respuesta."
)

RUBRICA = [
    ("1. Correctitud funcional", "¿Hace lo pedido? ¿Cubre los casos borde?"),
    ("2. Calidad / idiomaticidad", "¿Sigue las convenciones del stack? ¿Legible, sin code smells?"),
    ("3. Seguridad", "¿Introduce vulnerabilidades? ¿Gestiona bien input no confiable?"),
    ("4. Cumplimiento de instrucciones", "¿Hizo exactamente lo pedido, sin cambios no solicitados?"),
    ("5. Esfuerzo de arreglo", "¿Cuánto trabajo para dejarlo production-ready? (5 = se integra tal cual)"),
]

TASK_DESC = {
    "bug1-petvalidator": "Bug-fix: un nombre de mascota con solo espacios se aceptaba como válido.",
    "bug2-ownercontroller": "Bug-fix: con varios resultados redirige al detalle en vez de mostrar la lista.",
    "sb-feat1-name-length": "Feature: rechazar nombres de más de 50 caracteres (error 'tooLong').",
    "ng-bug1-missing-input": "Bug-fix: faltaba @Input() en la propiedad 'config' (rompe el binding).",
    "ng-feat1-reading-time": "Feature: método getReadingTime() para mostrar el tiempo de lectura.",
    "ng-feat2-service-search": "Feature: implementar search() en el servicio de artículos.",
    "re-bug1-favorite-count": "Bug-fix: el reducer no actualiza favoritesCount al marcar favorito.",
    "re-feat1-reading-time": "Feature: función getReadingTime(body) (mínimo 1 minuto).",
    "re-feat2-author-filter": "Feature: acción FILTER_BY_AUTHOR en el reducer (la tarea más difícil).",
    "data-bug1-sales-genre": "Bug-fix: JOIN incorrecto en el cálculo de ventas por género.",
    "data-feat1-customer-ranking": "Feature: ranking de clientes por país con window functions.",
}

FRAMEWORK_ORDER = ["Spring Boot", "Angular", "React", "Datos"]


def main():
    rows = list(csv.DictReader(open(PLANTILLA, newline="", encoding="utf-8")))
    frameworks = defaultdict(list)
    for row in rows:
        code = pathlib.Path(row["archivo_respuesta"]).read_text(encoding="utf-8")
        frameworks[row["stack"]].append({
            "modelo": row["modelo"],
            "harness": row.get("harness", "raw_api"),
            "tarea": row["tarea"],
            "tarea_desc": TASK_DESC.get(row["tarea"], ""),
            "tipo": row["tipo"],
            "test_ok": row["test_ok_auto"],
            "codigo": code,
        })
    for framework in frameworks:
        frameworks[framework].sort(key=lambda item: (item["tarea"], item["harness"], item["modelo"]))

    data = {
        "objetivo": OBJETIVO,
        "instrucciones": INSTRUCCIONES,
        "rubrica": RUBRICA,
        "frameworks": {framework: frameworks[framework] for framework in FRAMEWORK_ORDER if framework in frameworks},
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(len(items) for items in data["frameworks"].values())
    print(f"{OUT} generado: {len(data['frameworks'])} frameworks, {total} respuestas")
    for framework, items in data["frameworks"].items():
        print(f"  {framework}: {len(items)} respuestas")


if __name__ == "__main__":
    main()

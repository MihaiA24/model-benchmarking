# Revisión humana ciega — Guía operativa

Cada fila representa una combinación **modelo anonimizado + harness + tarea**. Esta guía
explica cómo montar la recogida con **Google Forms** (vuelca solo a una Google Sheet)
y cómo coordinar a los revisores.

---

## 1. Montar los formularios (lo hace el coordinador, una vez)

1. Sube **`human_review/form_data.json`** a tu Google Drive (cualquier carpeta).
2. Abre <https://script.google.com> → **Nuevo proyecto**.
3. Pega el contenido de **`human_review/build_forms.gs`** y guarda.
4. Ejecuta estas 4 funciones **una a una** (no `buildAll`, para no tocar el límite de 6 min):
   `buildSpringBoot`, `buildAngular`, `buildReact`, `buildDatos`.
   La primera vez te pedirá autorizar permisos (Drive, Forms, Sheets).
5. En **Ver → Registros** aparecen las URLs de los 4 formularios y de la hoja
   **«Resultados revisión modelos IA»** (todas las respuestas caen ahí, una pestaña por framework).

Cada formulario empieza con el **objetivo + instrucciones + rúbrica**, y luego una sección por
respuesta: el código/transcript a evaluar + las 5 preguntas (escala 1–5) + un comentario opcional.

---

## 2. Repartir el trabajo (clave para que no sea tedioso)

El número de respuestas depende de cuántos harnesses y modelos hayas ejecutado. Reparte
**por framework** con **2 revisores por framework** (doble ciego = dos personas
independientes puntúan lo mismo):

| Framework | Revisor sugerido |
|-----------|------------------|
| Spring Boot | Perfil backend/Java |
| Angular | Perfil front |
| React | Perfil front |
| Datos | Perfil SQL/datos |

Cada revisor solo recibe el link de **su** formulario.

---

## 3. Reglas para los revisores

- Puntúa cada eje **1 (muy malo) – 5 (excelente)**. Los 5 ejes están en la rúbrica del formulario.
- **No intentes adivinar** qué modelo real hay detrás del alias. Sé consistente entre respuestas.
- Si el **estado automático justo** (`fair_status` / `test_ok_auto`) falla, refléjalo en el eje 1 (correctitud). Las filas excluidas por infraestructura no deberían estar en este paquete salvo que el coordinador las haya incluido explícitamente.
- Dudas o algo que chirríe → al comentario de esa respuesta.

---

## 4. Reconciliación y resultado

1. Cuando las dos personas de un framework terminen, en la hoja tendrás 2 filas por respuesta.
2. Donde difieran **> 1 punto** en algún eje, que lo discutan y fijen una nota consensuada.
3. Solo cuando TODO esté puntuado y reconciliado, revela el mapping real:
   **`results/model_mapping.csv`** (alias → modelo real). **No lo abras antes.**
4. Resultado final = combinar **% tests verdes (auto)** desde
   `results/full_combined_v3/metrics_fair.csv` / `fair_comparison_summary.md` +
   **media de calidad (humana)** + **coste/tarea** + **latencia**.
   No uses `metrics_all.csv` para calidad: es el merge bruto/auditable. Usa `fair_comparison_telemetry_gaps.csv` para detectar combinaciones sin coste/tokens exactos antes de calcular calidad/coste. Fija un umbral mínimo de calidad y luego mira el precio.
   Lo normal no es un único ganador, sino **routing**: modelo barato por defecto + uno potente
   para el % de tareas difíciles.

---

## Ficheros de este paquete

- `form_data.json` — datos para el Apps Script (respuestas + objetivo/instrucciones/rúbrica).
- `build_forms.gs` — script que crea los 4 formularios + la hoja.
- `respuestas_ciegas/<framework>/` — el código ciego, por si se quiere revisar fuera del formulario.
- `plantilla_puntuacion.csv` — alternativa en CSV (mismo contenido) si no se usan los formularios; debe traer `automatic_source=results/full_combined_v3/metrics_fair.csv` y columnas `fair_status` / `fair_included`.
- `INDICE_por_framework.md` — qué fichero pertenece a qué framework.
- `instrucciones.md` — rúbrica detallada.

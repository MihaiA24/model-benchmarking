# Instrucciones para la revisión humana — PoC Evaluación de Modelos de IA

## Contexto

Hemos ejecutado 99 evaluaciones automáticas (3 modelos × 11 tareas × 3 runs) sobre cuatro stacks:
Spring Boot, Angular, React y Datos (Chinook SQLite).

La capa automática mide si el código **compila y pasa los tests**. Esta revisión humana mide
**calidad, idiomaticidad y seguridad** — dimensiones que los tests no capturan.

Los modelos están **anonimizados como Modelo A, B y C**. No intentes deducir cuál es cuál
hasta que se revele el mapping al final.

---

## Tu rol como revisor

1. Leer la respuesta del modelo en el archivo `_raw_response.txt` indicado.
2. Puntuar en los 5 ejes de la rúbrica (escala 1–5).
3. Registrar la puntuación en `plantilla_puntuacion.csv`.
4. **No consultes** a otros revisores hasta que ambos hayáis terminado vuestra hoja.

---

## Rúbrica (1 = muy malo, 5 = excelente)

| Eje | Qué mide | 1 | 5 |
|-----|---------|---|---|
| **1. Correctitud funcional** | ¿El código hace lo pedido? ¿Cubre los bordes? | No funciona en absoluto | Correcto en todos los casos |
| **2. Calidad e idiomaticidad** | ¿Sigue las convenciones del stack? ¿Es legible, sin code smells? | Requiere reescritura completa | Listo para merge sin tocar |
| **3. Seguridad** | ¿Introduce vulnerabilidades? ¿Gestiona bien inputs no confiables? | Vulnerabilidad crítica | Seguro por diseño |
| **4. Cumplimiento de instrucciones** | ¿Hizo exactamente lo pedido? ¿Añadió cambios no solicitados? | Ignoró las instrucciones | Cumplimiento exacto |
| **5. Esfuerzo de arreglo** | ¿Cuánto trabajo para llevarlo a producción? | Más rápido escribirlo de cero | Se integra sin tocar nada |

---

## Proceso paso a paso

### Paso 1 — Preparación
- Descarga/clona el repositorio `model-benchmarking`.
- Abre `human_review/plantilla_puntuacion.csv` en Excel o Google Sheets.
- Haz una copia con tu nombre: `plantilla_puntuacion_TUNOMBRE.csv`.

### Paso 2 — Revisión
Para cada fila de tu copia:
1. Abre la ruta en la columna `archivo_respuesta` (está bajo `poc-run/results/`).
2. Lee el diff generado: ¿qué cambió respecto al fichero original?
3. Puntúa los 5 ejes. Si el test automático falló (`test_ok=False`), descuenta en eje 1.
4. Añade notas libres en la columna `comentarios`.

### Paso 3 — Reconciliación (dos revisores por tarea)
- Cuando ambos revisores terminen, comparan eje a eje.
- Si la diferencia en cualquier eje es > 1 punto, discuten y acuerdan una nota final.
- Registran la nota consensuada en `plantilla_puntuacion_FINAL.csv`.

### Paso 4 — Revelación del mapping
- Solo cuando `plantilla_puntuacion_FINAL.csv` esté completo, abre `results/model_mapping.csv`.
- Ese fichero dice qué modelo real corresponde a A, B y C.
- **No lo abras antes.** El doble ciego es lo que da validez al resultado.

### Paso 5 — Interpretación
Usa el prompt en `human_review/prompt_resultado_final.md` para que un LLM calcule
la puntuación combinada (automática + humana + coste + latencia) y sugiera la estrategia
de adopción.

---

## Tareas incluidas (11 en total)

| ID | Stack | Tipo | Descripción breve |
|----|-------|------|-------------------|
| bug1-petvalidator | Spring Boot | Bug-fix | Validar nombre con solo espacios (hasText) |
| bug2-ownercontroller | Spring Boot | Bug-fix | Redirigir solo si hay exactamente 1 resultado |
| sb-feat1-name-length | Spring Boot | Feature | Rechazar nombres > 50 chars (error "tooLong") |
| ng-bug1-missing-input | Angular | Bug-fix | Añadir `[required]` faltante en formulario |
| ng-feat1-reading-time | Angular | Feature | Mostrar tiempo de lectura estimado en artículos |
| ng-feat2-service-search | Angular | Feature | Añadir búsqueda por texto en servicio de artículos |
| re-bug1-favorite-count | React | Bug-fix | Sincronizar contador de favoritos en el reducer |
| re-feat1-reading-time | React | Feature | Calcular y mostrar tiempo de lectura |
| re-feat2-author-filter | React | Feature | Filtrar artículos por autor (tarea más difícil) |
| data-bug1-sales-genre | Datos | Bug-fix | Corregir JOIN incorrecto en ventas por género |
| data-feat1-customer-ranking | Datos | Feature | Ranking de clientes por país con window functions |

---

## Notas importantes

- La tarea `re-feat2-author-filter` fue la más difícil: ningún modelo tuvo 3/3 en tests.
  Lee con cuidado los intentos que fallaron para valorar el eje 5 (esfuerzo de arreglo).
- Las tareas de Angular se verifican **solo con build** (los tests Vitest tienen un problema
  de compatibilidad con zone.js en este entorno). El build en verde es condición necesaria
  pero no suficiente — el eje 1 requiere criterio humano.
- El fichero `model_mapping.csv` está en `poc-run/results/`. Guárdalo bajo llave hasta el final.

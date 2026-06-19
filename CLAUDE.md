# CLAUDE.md — PoC de evaluación de modelos de IA para desarrollo

> Contexto persistente del proyecto. Léelo entero al empezar una sesión.
> Para el estado más reciente, lee también `results/metrics.csv` y `BUGS.md` si existen.

## Objetivo

La empresa (~300-400 desarrolladores) debe decidir qué modelo de IA adoptar, vía API,
para uso diario de desarrollo. Esta prueba de concepto mide **calidad real sobre
nuestros stacks** (Spring Boot, Angular, React, Datos/Power BI) frente a **coste** y
**latencia**, para llevar una recomendación con datos a la reunión de decisión.

## Estado actual

- **Piloto completado** con `spring-petclinic`.
- `baseline-limpio` (commit `b3ee2c5`): repo correcto, la "hoja de respuestas". **No tocar.**
- `baseline-buggy` (commit `59693a7`): 2 bugs sembrados; es el punto de partida que reciben los modelos.
  - **Bug 1** — `PetValidator.java` (L41): usa `hasLength` en vez de `hasText`, así un nombre
    solo de espacios se acepta como válido. Tests que deben volver a verde:
    `PetControllerTests` → `processCreationFormWithBlankName`, `processUpdateFormWithBlankName`.
  - **Bug 2** — `OwnerController.java` (L111): usa `>= 1` en vez de `== 1`, así redirige al
    detalle aunque haya varios resultados. Test: `OwnerControllerTests#processFindFormSuccess`.
- **Harness**: `poc_harness.py` (modo single-shot; lee la key de `openrouter_key.txt`).
  Resultados en `results/metrics.csv` y `results/<tarea>__<modelo>__rN/_raw_response.txt`.
- **Próximo paso**: escalar a Angular, React y Datos.

## Decisiones ya tomadas (no re-litigar)

- **API vía gateway, NO self-hosting** (no sale a presupuesto de ~4.500 €/mes para la plantilla).
- **Gateway**: OpenRouter (un endpoint; cambiar de modelo = cambiar el string).
- **Modelos a comparar** (verifica los slugs exactos en https://openrouter.ai/models):
  - `minimax/minimax-m3` — 0.30 / 1.20 $ por 1M tokens (in/out)
  - `deepseek/deepseek-v4` — 1.74 / 3.48
  - `z-ai/glm-4.7` — 0.60 / 2.20
- Sin modelo "frontera" de referencia en esta tanda (se puede añadir luego sin rehacer nada).

## Seguridad de la API key (estricto)

- La key vive en `openrouter_key.txt`, que rellena el usuario a mano.
- **Nunca** la pidas por chat, **nunca** la imprimas en logs, **nunca** la commitees.
  Asegúrate de que está en `.gitignore`.

## Principios metodológicos (innegociables)

1. **Aislamiento**: cada `(modelo × tarea × run)` parte de una **copia limpia** del baseline.
   Ningún run ve los cambios de otro.
2. **Prompts congelados**: el mismo prompt para todos los modelos dentro de una tarea.
3. **3 runs por tarea** (los modelos no son deterministas).
4. **Bugs que rompen un test concreto** → "test verde" es señal fiable. Un fichero por bug;
   arreglo correcto documentado en `BUGS.md`.
5. **Dos capas de evaluación**: automática (la haces tú) y humana de calidad (la hacen las
   personas; tú solo guías y preparas).
6. **Doble ciego**: anonimiza el modelo en todo lo que se entregue para puntuación humana.

## Tu rol vs. la validación humana

- **TÚ haces**: setup de repos, siembra de bugs, harness por stack, ejecución, capa automática
  (compila / tests / lint), métricas (coste y latencia), diffs, raw responses, y **preparar** la
  plantilla de puntuación anonimizada.
- **TÚ NO haces**: puntuar la calidad ni decidir el "ganador". Eso introduciría una IA juzgando
  a otras IAs y rompería el doble ciego.
- **Sobre la validación humana: GUÍA al usuario.** Ayúdale a montar el proceso paso a paso,
  hazle las preguntas necesarias (cuántos revisores, tiempo disponible), y explícale el porqué de
  cada decisión. Pero no inventes las notas. (Ver "Guion de validación humana" al final.)

## Stacks y repos

- **Spring Boot** (Java/Maven): `spring-petclinic`. Ya hecho en el piloto. Amplía con 2-3 tareas
  más si conviene. Build/test: `mvn -q -DskipTests compile` / `mvn -q -Dtest=<Clase> test`.
- **Angular**: RealWorld/Conduit Angular (`github.com/gothinkster/realworld`). Build/test con npm
  (`npm ci`; `npm run build`; `npm test`).
- **React**: RealWorld/Conduit React. `npm ci`; `npm run build`; `npm test`.
- **Datos**: dataset público (p. ej. Chinook o Northwind en SQLite). Tareas de SQL y de
  transformación con pandas, **con output esperado definido** para verificar automáticamente.
  DAX/Power BI es lo menos automatizable: genera la medida y **márcala para revisión humana**;
  no inventes un verificador automático poco fiable.

## Tipos de tarea (≈5-6 por stack)

Greenfield (crear de cero) · Bug-fix (arreglar fallo sembrado) · Feature sobre código existente ·
Generación de tests · Explicación/review. El aislamiento solo importa para bug-fix y feature;
greenfield nace de cero.

## Convenciones del harness

Reutiliza el patrón de `poc_harness.py`: lee la key de `openrouter_key.txt`, bucle
`modelos × tareas × runs`, copia limpia por run (`shutil.copytree`), `build_cmd` + `test_cmd`,
registro en CSV con `build_ok, test_ok, tokens, coste, latencia`, y guarda `_raw_response.txt`.
Para extenderlo a un stack: cambia `build_cmd`/`test_cmd` (mvn → npm donde toque). Si un baseline
tiene varios bugs, ejecuta **solo** el test del bug de esa tarea. Maneja errores por llamada
(una fila `ERROR`, no abortes la tanda).

## Cómo proceder (por stack, con checkpoints)

Para cada stack nuevo (orden sugerido: Angular → React → Datos):
- **A.** Clona el repo en una carpeta de baselines aislada.
- **B.** Verifica que compila y testea en verde (esa es la "hoja de respuestas").
- **C.** Propón los bugs/tareas. **[CHECKPOINT]** Enséñaselos al usuario y ESPERA aprobación.
- **D.** Aplica lo aprobado, documenta en `BUGS.md`, crea el baseline con bugs.
- **E.** Verifica que el/los test(s) objetivo fallan. **[CHECKPOINT]** Reporta el resultado.
- **F.** Extiende el harness y ejecútalo.
- **G.** Entrega el `metrics.csv` parcial y el resumen objetivo del stack.

## Entregables finales

- `results/metrics.csv` consolidado (todos los stacks).
- `results/` con diffs y `_raw_response.txt` por run.
- `plantilla_puntuacion.csv` anonimizada (modelo como A/B/C, columnas de rúbrica vacías).
- Resumen objetivo por modelo y stack: % tests verdes, coste medio/tarea, latencia media.
- La **decisión** la toman las personas combinando calidad/coste; tú ayudas a construir la matriz.

## Rúbrica de calidad (para la plantilla y para guiar a los humanos)

Ejes 1-5: **correctitud funcional**, **calidad/idiomático**, **seguridad**,
**cumplimiento de instrucciones**, **facilidad de arreglo** (esfuerzo para dejarlo
production-ready). Se combinan con la capa automática (% tests verdes), el coste/tarea y la latencia.

## Guion de validación humana (cómo guiar al usuario, sin puntuar tú)

Cuando el usuario esté listo para la fase humana, guíale así:
1. Genera `plantilla_puntuacion.csv`: una fila por `(modelo_anonimizado, tarea, run)` con las
   columnas de la rúbrica vacías. Guarda el mapping real en un `mapping.csv` aparte que **no se
   mira hasta el final**.
2. Explica el doble ciego: cada revisor puntúa sin ver el modelo; **dos revisores independientes**
   por tarea.
3. Reconciliación: donde difieran más de 1 punto, que lo discutan y acuerden.
4. Revela el mapping **solo al final**.
5. Interpretación: combina % tests verdes (auto) + media de calidad (humana) + coste/tarea +
   latencia. Calcula **calidad/coste**. Fija un umbral mínimo de calidad antes de mirar el precio.
6. Recuerda al usuario que el resultado típico es una **estrategia de routing** (modelo barato por
   defecto + uno más potente reservado para el % pequeño de tareas difíciles), no un único ganador.
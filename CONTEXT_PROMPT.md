# Contexto para continuar el proyecto en otro PC con Claude Code

Pega este bloque como primer mensaje al abrir Claude Code en un PC nuevo.
Claude leerá el `CLAUDE.md` del repo automáticamente, pero este fichero le da el estado
exacto del proyecto y las instrucciones de setup que no están en el código.

---

## PROMPT DE CONTEXTO

Estoy continuando un PoC de evaluación de modelos de IA para desarrollo en empresa.
El repositorio es https://github.com/Ufransa/model-benchmarking.git

Clónalo y posiciónate en la carpeta:
```
git clone https://github.com/Ufransa/model-benchmarking.git
cd model-benchmarking
```

Lee el `CLAUDE.md` del repo — contiene la metodología completa del proyecto.
Luego lee este fichero entero antes de hacer nada.

---

## Estado del proyecto

### Ya completado
- `results/metrics_all.csv` tiene 362 filas `raw_api` para los presets `original` + `new`; falta la fila legacy `minimax/minimax-m3` / `ng-bug1-missing-input` / run 3
- Materiales de revisión humana en `human_review/` como snapshot ciego; regenerar si se puntúan nuevos harnesses
- Presentación ejecutiva en `presentacion.html`
- Runner central con adapters `raw_api`, `omp`, `opencode`, `hermes`
- Runbook operativo en `RUNBOOK.md`

### Pendiente de ejecutar
- Comparativa de harnesses de agente con modelos OpenCode Go:
  ```bash
  python run_benchmark.py --stack all --harness agent --models opencode-go --runs 3
  ```

---

## Setup completo desde cero

### Paso 1 — API keys

El runner carga `.env` desde la raíz del repo antes de invocar tests, builds o CLIs:
```dotenv
OPENROUTER_API_KEY=sk-or-v1-TUKEY
OPENCODE_API_KEY=opencode-go-key
```

También acepta los ficheros legacy `openrouter_key.txt` y `opencode_key.txt`.
`.env` y esos ficheros están en `.gitignore` — nunca se commitean.

### Paso 2 — Dependencias Python

```bash
pip install requests pandas
```

### Paso 3 — Baseline de Datos

El baseline de Datos (Chinook SQLite) **ya está en el repo** bajo `baselines/data-chinook/`.
No necesitas hacer nada.

### Paso 4 — Baseline de Spring Boot

Clona spring-petclinic y aplica los bugs y el test de feature:

```bash
# Baseline con 2 bugs sembrados (punto de partida para los modelos)
git clone https://github.com/spring-projects/spring-petclinic baselines/petclinic
```

**Bug 1 — PetValidator.java (línea ~41):**
En `baselines/petclinic/src/main/java/org/springframework/samples/petclinic/owner/PetValidator.java`
cambia `hasText` por `hasLength` en la validación del nombre:
```java
// ANTES (correcto):
if (!StringUtils.hasText(pet.getName())) {

// DESPUÉS (buggy — lo que debe recibir el modelo):
if (!StringUtils.hasLength(pet.getName())) {
```

**Bug 2 — OwnerController.java (línea ~111):**
En `baselines/petclinic/src/main/java/org/springframework/samples/petclinic/owner/OwnerController.java`
cambia `== 1` por `>= 1`:
```java
// ANTES (correcto):
if (results.size() == 1) {

// DESPUÉS (buggy — lo que debe recibir el modelo):
if (results.size() >= 1) {
```

Verifica que los tests fallan:
```bash
cd baselines/petclinic
mvn -q -Dtest=PetControllerTests#processCreationFormWithBlankName test  # debe FALLAR
mvn -q -Dtest=OwnerControllerTests#processFindFormSuccess test          # debe FALLAR
```

```bash
# Baseline para la tarea de feature (feat1 — validación de longitud)
git clone https://github.com/spring-projects/spring-petclinic baselines/petclinic-feat1
```

Añade este test en `baselines/petclinic-feat1/src/test/java/org/springframework/samples/petclinic/owner/PetControllerTests.java`
(dentro de la clase, antes del último `}`):

```java
@Test
void processCreationFormWithTooLongName() throws Exception {
    mockMvc.perform(post("/owners/{ownerId}/pets/new", TEST_OWNER_ID)
            .param("name", "A".repeat(51))
            .param("type", "hamster")
            .param("birthDate", "2015-02-12"))
        .andExpect(model().attributeHasFieldErrorCode("pet", "name", "tooLong"));
}
```

Verifica que el test falla (la validación no existe aún):
```bash
cd baselines/petclinic-feat1
mvn -q -Dtest=PetControllerTests#processCreationFormWithTooLongName test  # debe FALLAR
```

### Paso 5 — Baseline de Angular

```bash
git clone https://github.com/gothinkster/angular-realworld-example-app baselines/angular-conduit
cd baselines/angular-conduit
npm ci
cd ../..
```

> `npm ci` solo se ejecuta una vez. El harness usa junction links para referenciar
> los node_modules sin copiarlos (~300 MB) en cada run.

Los bugs/features de Angular son **seed_patches** que el harness aplica automáticamente
en cada run antes de enviar al modelo. No necesitas modificar el baseline manualmente.
Puedes verificar que el baseline compila en verde:
```bash
cd baselines/angular-conduit
npm run build  # debe compilar sin errores
```

**Referencia de los seed patches (aplicados por el harness):**

- **ng-bug1**: En `src/app/features/article/components/article-list.component.ts`
  el harness elimina `@Input()` de la propiedad `config`, rompiendo el template binding.

- **ng-feat1**: En `src/app/features/article/components/article-preview.component.ts`
  el harness añade `<span class="reading-time">{{ getReadingTime(article().body) }} min read</span>`
  al template, llamando a un método que aún no existe en la clase.

- **ng-feat2**: En `src/app/features/article/services/articles.service.ts`
  el harness añade la interfaz `ArticlesRepository` con el método `search()` y hace que
  `ArticlesService implements ArticlesRepository`, pero sin implementar `search()`.

### Paso 6 — Baseline de React

```bash
git clone https://github.com/gothinkster/react-redux-realworld-example-app baselines/react-conduit
cd baselines/react-conduit
npm ci
cd ../..
```

Verifica que el baseline compila:
```bash
cd baselines/react-conduit
CI=true npm test -- --watchAll=false  # deben pasar los tests existentes
```

**Referencia de los seed patches (aplicados por el harness):**

- **re-bug1**: En `src/reducers/articleList.js`, el harness elimina la línea
  `favoritesCount: action.payload.article.favoritesCount` del case `ARTICLE_FAVORITED`,
  haciendo que el contador de favoritos no se actualice en el reducer.
  El harness también añade el fichero de test `src/reducers/articleList.test.js`.

- **re-feat1**: El harness añade `src/utils/readingTime.js` (stub con `return 0`)
  y `src/utils/readingTime.test.js` (tests que fallan mientras no se implemente).

- **re-feat2**: El harness añade `src/reducers/feat2-author-filter.test.js`
  con un test para la acción `FILTER_BY_AUTHOR` que aún no existe en el reducer.

---

## Ejecutar modelos o harnesses

Con los baselines configurados:

```bash
# Verifica primero que los slugs OpenRouter responden
python test_slugs.py

# Legacy raw API: lanza los 4 stacks en paralelo
python run_all.py

# Harness benchmark: todos los modelos OpenCode Go en OMP, OpenCode y Hermes
python run_benchmark.py \
  --stack all \
  --harness agent \
  --models opencode-go \
  --runs 3

# Cuando terminen, consolida los resultados
python merge_metrics.py
```

El runner central usa modo **resume** por defecto: no repite filas ya completadas con la
clave `(harness, task, model, run)`. Los CSV añaden `harness`, `model_calls` y
`telemetry_note`: `raw_api` registra 1 llamada OpenRouter; `omp`/`opencode` rellenan
tokens/coste/llamadas si su JSON lo expone; `hermes` queda marcado como no disponible.
El backlog técnico vive en `docs/backlog.md`; el item abierto actual es capturar telemetry real de Hermes desde una fuente machine-readable.

---

## Restricciones técnicas conocidas (Windows)

| Restricción | Causa | Cómo está resuelto |
|------------|-------|-------------------|
| `UnicodeEncodeError` en subprocess | Windows usa cp1252 por defecto | Todos los subprocess usan `encoding="utf-8", errors="replace"` |
| Angular build sale error con caracteres raros | Build output contiene UTF-8 | Mismo fix de encoding |
| React tests se quedan colgados | Jest en modo watch | Se lanza con `env CI=true` y `--watchAll=false` |
| Copiar baseline tarda mucho | Copiaba node_modules (~300 MB) por run | `shutil.ignore_patterns('node_modules')` + junction link: `mklink /J dst src` |
| Spring Boot copiar tarda | Copiaba target/ compilado por run | `shutil.ignore_patterns('target', '.git')` |
| `glm-5.2` responde vacío | Modelo necesita más tokens | `max_tokens >= 200` en los harnesses |
| `hy3-preview` responde vacío | Igual | `max_tokens >= 50` (ya está en los harnesses) |
| React seed patch indentación | articleList.js usa 14 espacios | El patch usa exactamente 14 espacios |
| Angular verificación solo build | Vitest + zone.js incompatibilidad en este entorno | `test_ok_equals_build = True` en las tareas Angular |

---

## Ficheros clave del repo

```
model-benchmarking/
├── CLAUDE.md                     ← Metodología completa (lo lee Claude Code automáticamente)
├── CONTEXT_PROMPT.md             ← Este fichero
├── openrouter_key.txt.example    ← Plantilla — crea openrouter_key.txt con tu key real
│
├── run_benchmark.py               ← Runner central (`raw_api`, `omp`, `opencode`, `hermes`)
├── benchmark/                     ← Tareas, adapters, workdirs y checks
├── run_springboot.py              ← Wrapper legacy Spring Boot vía raw_api
├── run_angular.py                 ← Wrapper legacy Angular vía raw_api
├── run_react.py                   ← Wrapper legacy React vía raw_api
├── run_data.py                    ← Wrapper legacy Datos vía raw_api
├── run_all.py                     ← Lanza los 4 stacks en paralelo
├── merge_metrics.py               ← Fusiona CSVs con columna harness
├── test_slugs.py                  ← Verifica que los slugs de OpenRouter funcionan
│
├── baselines/data-chinook/       ← EN EL REPO: Chinook SQLite + scripts Python
│   (petclinic, angular, react)   ← NO EN EL REPO: ver pasos 4-6 arriba
│
├── human_review/
│   ├── instrucciones.md          ← Protocolo para revisores humanos
│   ├── plantilla_puntuacion.csv  ← Filas por (modelo, harness, tarea)
│   └── prompt_resultado_final.md ← Prompt LLM para calcular puntuación combinada
│
└── results/
    ├── metrics_all.csv           ← Consolidado por stack/harness/modelo
    ├── metrics_anon.csv          ← Igual con aliases Modelo A/B/C
    ├── model_mapping.csv         ← Mapping real — NO abrir hasta final de revisión
    └── <harness>__<task>__<model>__r<n>/
        └── _raw_response.txt     ← Respuesta cruda o transcript + cambios finales
```

---

## Próximos pasos sugeridos

1. Configurar baselines según pasos 4-6 (si quieres re-ejecutar el harness)
2. Ejecutar raw API (`python run_all.py`) o agentes (`python run_benchmark.py --harness omp,opencode,hermes ...`)
3. Consolidar: `python merge_metrics.py`
4. Iniciar revisión humana: `human_review/instrucciones.md`
5. Calcular puntuación final: `human_review/prompt_resultado_final.md`

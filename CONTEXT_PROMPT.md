# Contexto para continuar el proyecto en otro PC con Claude Code

> **Estado histórico.** Este prompt reproduce el piloto directo-modelo anterior. No debe usarse como handoff para implementar el nuevo benchmark autónomo. Para ese trabajo, empieza por [`CONTEXT.md`](CONTEXT.md), [`blueprint/final-validation-and-implementation-handoff.md`](blueprint/final-validation-and-implementation-handoff.md) y los demás contratos aceptados en [`blueprint/`](blueprint/).

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
- **3 modelos originales evaluados** con 11 tareas × 3 runs = 99 evaluaciones automáticas
- Resultados en `results/metrics_all.csv`
- Materiales de revisión humana en `human_review/`
- Presentación ejecutiva en `presentacion.html`

### Pendiente de ejecutar
- **5 modelos nuevos** ya añadidos a todos los harnesses, pero faltan sus runs:
  - `qwen/qwen3.7-plus` ($0.32/$1.28)
  - `google/gemini-3.1-flash-lite` ($0.25/$1.50)
  - `qwen/qwen3-coder-next` ($0.11/$0.80)
  - `tencent/hy3-preview` ($0.066/$0.26) — necesita max_tokens >= 200
  - `z-ai/glm-5.2` ($1.20/$4.10) — necesita max_tokens >= 200

---

## Setup completo desde cero

### Paso 1 — API key

Crea el fichero `openrouter_key.txt` en la raíz del repo con tu key de OpenRouter:
```
sk-or-v1-TUKEY
```
Este fichero está en `.gitignore` — nunca se commitea.

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

## Ejecutar los modelos nuevos

Con los baselines configurados, lanza los harnesses:

```bash
# Verifica primero que los slugs responden
python test_slugs.py

# Lanza los 4 harnesses en paralelo (abre 4 ventanas cmd en Windows)
python run_all.py

# Cuando terminen, consolida los resultados
python merge_metrics.py
```

Los harnesses usan modo **append**: las filas de los 3 modelos originales ya están en los CSV,
solo añadirán las de los 5 modelos nuevos.

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
├── run_springboot.py             ← Harness Spring Boot
├── run_angular.py                ← Harness Angular
├── run_react.py                  ← Harness React
├── run_data.py                   ← Harness Datos
├── run_all.py                    ← Lanza los 4 en paralelo (Windows)
├── merge_metrics.py              ← Fusiona CSVs → metrics_all + anon + mapping
├── test_slugs.py                 ← Verifica que los slugs de OpenRouter funcionan
│
├── baselines/data-chinook/       ← EN EL REPO: Chinook SQLite + scripts Python
│   (petclinic, angular, react)   ← NO EN EL REPO: ver pasos 4-6 arriba
│
├── human_review/
│   ├── instrucciones.md          ← Protocolo para revisores humanos
│   ├── plantilla_puntuacion.csv  ← 33 filas vacías para puntuar (sin mapping)
│   └── prompt_resultado_final.md ← Prompt LLM para calcular puntuación combinada
│
└── results/
    ├── metrics_all.csv           ← Consolidado de los 3 modelos originales
    ├── metrics_anon.csv          ← Igual con Modelo A/B/C (para revisión ciega)
    ├── model_mapping.csv         ← Mapping real — NO abrir hasta final de revisión
    └── <task>__<model>__r<n>/
        └── _raw_response.txt     ← Respuesta cruda de cada run (para revisores)
```

---

## Próximos pasos sugeridos

1. Configurar baselines según pasos 4-6 (si quieres re-ejecutar el harness)
2. Ejecutar los 5 modelos nuevos: `python run_all.py`
3. Consolidar: `python merge_metrics.py`
4. Iniciar revisión humana: `human_review/instrucciones.md`
5. Calcular puntuación final: `human_review/prompt_resultado_final.md`

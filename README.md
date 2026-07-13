# PoC — Evaluación de modelos de IA para desarrollo

> **Estado histórico.** Este README documenta el piloto directo-modelo existente y conserva sus instrucciones para reproducirlo. No es la arquitectura de implementación vigente. El nuevo benchmark autónomo de OMP, OpenCode y Hermes está definido por [`CONTEXT.md`](CONTEXT.md) y los contratos aceptados en [`blueprint/`](blueprint/); no amplíes los runners por stack ni sus baselines como camino de implementación del nuevo benchmark.

Benchmark automatizado para elegir qué modelo de IA adoptar vía API en un equipo de
~300–400 desarrolladores. Compara calidad, coste y latencia sobre los cuatro stacks reales
de la empresa: **Spring Boot, Angular, React y Datos (Chinook SQLite)**.

---

## Índice

1. [Estado actual](#1-estado-actual)
2. [Primeros pasos en un PC nuevo](#2-primeros-pasos-en-un-pc-nuevo)
3. [Dónde meter la API key](#3-dónde-meter-la-api-key)
4. [Ejecutar los modelos (capa automática)](#4-ejecutar-los-modelos-capa-automática)
5. [Revisar los resultados humanos (capa de calidad)](#5-revisar-los-resultados-humanos-capa-de-calidad)
6. [Continuar con Claude Code en otro PC](#6-continuar-con-claude-code-en-otro-pc)
7. [Estructura del repositorio](#7-estructura-del-repositorio)
8. [Modelos evaluados](#8-modelos-evaluados)
9. [Resultados automáticos actuales](#9-resultados-automáticos-actuales)
10. [Gobernanza y adopción](#10-gobernanza-y-adopción)

---

## 1. Estado actual

| Capa | Estado |
|------|--------|
| Harness automático (3 modelos originales × 11 tareas × 3 runs) | **Completado** — 99 evaluaciones |
| 5 modelos nuevos añadidos a todos los harnesses | **Pendiente de ejecutar** |
| Resultados automáticos consolidados | `results/metrics_all.csv` |
| Materiales de revisión humana | `human_review/` — listos |
| Presentación ejecutiva | `presentacion.html` — con datos reales |

**Modelos originales evaluados:** minimax-m3, deepseek-v4-flash, glm-4.7

**Modelos nuevos pendientes de ejecutar:**
- `qwen/qwen3.7-plus` ($0.32 / $1.28 por 1M tok in/out)
- `google/gemini-3.1-flash-lite` ($0.25 / $1.50)
- `qwen/qwen3-coder-next` ($0.11 / $0.80)
- `tencent/hy3-preview` ($0.066 / $0.26)
- `z-ai/glm-5.2` ($1.20 / $4.10)

---

## 2. Primeros pasos en un PC nuevo

### 2.1 Clonar el repositorio

```bash
git clone https://github.com/Ufransa/model-benchmarking.git
cd model-benchmarking
```

### 2.2 Instalar dependencias Python

```bash
pip install requests pandas
```

### 2.3 Crear la API key (ver sección 3)

### 2.4 Configurar los baselines de Angular y React

Los baselines de Angular y React no están en el repo (node_modules pesa ~300 MB).
Solo es necesario si quieres **re-ejecutar el harness**; para la revisión humana no hace falta.

```bash
# Angular
git clone https://github.com/gothinkster/angular-realworld-example-app baselines/angular-conduit
cd baselines/angular-conduit
npm ci
cd ../..

# React
git clone https://github.com/gothinkster/react-redux-realworld-example-app baselines/react-conduit
cd baselines/react-conduit
npm ci
cd ../..
```

> **Nota:** `node_modules` solo se instala una vez. El harness usa junction links de Windows
> (`mklink /J`) para referenciarlos sin copiarlos en cada run. No necesitas volver a instalarlos.

### 2.5 Configurar los baselines de Spring Boot

```bash
# Clona spring-petclinic en versión con bugs sembrados
git clone <url-del-baseline-buggy> baselines/petclinic
git clone <url-del-baseline-feat1> baselines/petclinic-feat1
```

> Si no tienes las URLs exactas de los baselines con bugs, consulta `BUGS.md` o habla con
> quien ejecutó el piloto original. Los detalles de los bugs están documentados en el `CLAUDE.md`.

---

## 3. Dónde meter la API key

El harness lee la API key de OpenRouter desde un fichero de texto plano:

```
openrouter_key.txt
```

Este fichero **no está en el repo** (está en `.gitignore`). Debes crearlo tú:

```bash
# Windows PowerShell
"sk-or-v1-TUKEY" | Out-File -Encoding ascii openrouter_key.txt

# O simplemente crea el fichero con cualquier editor y pega la key
```

El fichero debe contener solo la key, sin espacios ni saltos de línea extra.
El repo incluye `openrouter_key.txt.example` como referencia del formato.

> **Consigue tu key en:** https://openrouter.ai/keys
> La key nunca se commitea. Si accidentalmente la commiteas, revócala inmediatamente desde OpenRouter.

---

## 4. Ejecutar los modelos (capa automática)

### 4.1 Verificar que los slugs de modelos funcionan

Antes de lanzar el benchmark completo, verifica que los modelos responden:

```bash
python test_slugs.py
```

Deberías ver algo como:

```
SLUG                                     PRECIO          RESULTADO
-----------------------------------------------------------------------
qwen/qwen3.7-plus               $0.32/$1.28  OK (5.1s) -> 'OK'
google/gemini-3.1-flash-lite    $0.25/$1.50  OK (0.7s) -> 'OK'
...
```

### 4.2 Lanzar todos los harnesses en paralelo (recomendado)

```bash
python run_all.py
```

Esto abre **4 ventanas de terminal** en Windows, una por stack:
- Ventana 1: Spring Boot (`run_springboot.py`)
- Ventana 2: Angular (`run_angular.py`)
- Ventana 3: React (`run_react.py`)
- Ventana 4: Datos (`run_data.py`)

Cada ventana muestra el progreso en tiempo real y se queda abierta al terminar.

> Los harnesses usan modo **append**: si el CSV ya existe, añaden filas nuevas.
> Esto permite añadir modelos nuevos sin re-ejecutar los que ya están.
> Si quieres re-ejecutar todo desde cero, borra los CSV en `results/` antes.

### 4.3 Lanzar un stack concreto

```bash
python run_springboot.py   # Solo Spring Boot
python run_angular.py      # Solo Angular
python run_react.py        # Solo React
python run_data.py         # Solo Datos
```

### 4.4 Consolidar resultados

Cuando terminen los harnesses, fusiona todos los CSV:

```bash
python merge_metrics.py
```

Genera:
- `results/metrics_all.csv` — todos los runs con nombre real del modelo
- `results/metrics_anon.csv` — igual pero con Modelo A/B/C (para revisión ciega)
- `results/model_mapping.csv` — mapping real A→modelo (no revelar hasta el final)

### 4.5 Duración estimada por stack

| Stack | Tiempo estimado (8 modelos × 3 tareas × 3 runs) |
|-------|--------------------------------------------------|
| Spring Boot | ~30–45 min (Maven compila cada vez) |
| Angular | ~15–25 min (solo build, más rápido) |
| React | ~20–35 min (Jest tests) |
| Datos | ~10–15 min (Python scripts, muy rápido) |

---

## 5. Revisar los resultados humanos (capa de calidad)

La revisión humana es **ciega**: los revisores no saben qué modelo generó cada respuesta.

### 5.1 Lee las instrucciones completas

```
human_review/instrucciones.md
```

Explica el protocolo paso a paso, la rúbrica con los 5 ejes de evaluación,
y cómo hacer la reconciliación entre revisores.

### 5.2 Descarga la plantilla de puntuación

```
human_review/plantilla_puntuacion.csv
```

Contiene 33 filas (3 modelos × 11 tareas) con las columnas:
- `modelo` — Modelo A, B o C (sin revelar el nombre real)
- `tarea` — ID de la tarea
- `test_ok_auto` — si el test automático pasó
- `archivo_respuesta` — ruta al `_raw_response.txt` que debes leer
- `eje1_correctitud` ... `eje5_esfuerzo` — columnas vacías para que el revisor puntúe (1–5)
- `comentarios` — notas libres

**Proceso recomendado:**
1. Cada revisor hace una copia con su nombre: `plantilla_puntuacion_NOMBRE.csv`
2. Lee el `_raw_response.txt` de cada fila (están en `results/`)
3. Puntúa los 5 ejes
4. Cuando ambos revisores terminen, comparan y reconcilian diferencias > 1 punto
5. Guardan el resultado final en `plantilla_puntuacion_FINAL.csv`

### 5.3 Calcular la puntuación combinada

Una vez terminada la revisión humana y revelado el mapping:

```
human_review/prompt_resultado_final.md
```

Este fichero contiene un prompt listo para pegar en cualquier LLM (Claude, GPT-4, etc.)
que calcula la puntuación combinada (automática + humana + coste + latencia) y da
una recomendación de qué modelo(s) adoptar.

### 5.4 Revelar el mapping real

Solo al final, cuando todas las puntuaciones estén registradas:

```
results/model_mapping.csv
```

Este fichero dice qué modelo real corresponde a A, B y C.
**No lo abras antes.** El doble ciego es lo que da validez al resultado.

---

## 6. Continuar con Claude Code en otro PC

Si abres Claude Code en un PC nuevo y quieres retomar el proyecto con contexto completo:

### 6.1 Usa el archivo de contexto

```
CONTEXT_PROMPT.md
```

Copia el bloque de texto que hay dentro y pégalo como primer mensaje en Claude Code.
Incluye el estado del proyecto, los modelos evaluados, las decisiones técnicas tomadas,
y las restricciones conocidas (encoding Windows, junction links, etc.).

### 6.2 El `CLAUDE.md` ya está en el repo

El fichero `CLAUDE.md` en la raíz contiene las instrucciones de metodología del proyecto
(principios innegociables, tipos de tarea, convenciones del harness, rol del LLM vs.
validación humana, etc.). Claude Code lo lee automáticamente al iniciar la sesión.

### 6.3 Comandos útiles para ponerse al día

```bash
# Ver métricas actuales
python -c "import csv; rows=list(csv.DictReader(open('results/metrics_all.csv'))); print(f'{len(rows)} runs. Modelos: {set(r[\"model\"] for r in rows)}')"

# Ver últimas 5 filas del CSV
python -c "import csv; rows=list(csv.DictReader(open('results/metrics_all.csv'))); [print(r) for r in rows[-5:]]"
```

---

## 7. Estructura del repositorio

```
model-benchmarking/
│
├── README.md                       ← Este fichero
├── CLAUDE.md                       ← Instrucciones de metodología para Claude Code
├── CONTEXT_PROMPT.md               ← Prompt para retomar el proyecto en otro PC
├── openrouter_key.txt.example      ← Ejemplo del fichero de API key (no commitear la real)
│
├── run_springboot.py               ← Harness Spring Boot (sb-feat1-name-length)
├── run_angular.py                  ← Harness Angular (3 tareas: bug1, feat1, feat2)
├── run_react.py                    ← Harness React (3 tareas: bug1, feat1, feat2)
├── run_data.py                     ← Harness Datos (2 tareas: bug1, feat1)
├── run_all.py                      ← Lanza los 4 harnesses en paralelo (Windows)
├── run_data_feat1only.py           ← Re-run solo data-feat1 (fix encoding)
├── merge_metrics.py                ← Fusiona los 4 CSV → metrics_all + anon + mapping
├── test_slugs.py                   ← Verifica que los slugs de OpenRouter responden
├── poc_harness.py                  ← Harness original del piloto Spring Boot (referencia)
├── presentacion.html               ← Presentación ejecutiva con resultados reales
│
├── baselines/
│   ├── data-chinook/               ← Dataset Chinook SQLite + scripts Python (EN REPO)
│   │   ├── Chinook.db
│   │   ├── bug1_sales_genre.py     ← Script con el bug sembrado (JOIN incorrecto)
│   │   ├── feat1_customer_ranking.py ← Script con placeholder (window functions)
│   │   ├── verify_bug1.py          ← Verificador automático bug1
│   │   ├── verify_feat1.py         ← Verificador automático feat1
│   │   └── expected/               ← Outputs esperados para comparación
│   ├── petclinic/                  ← Spring Boot con 2 bugs sembrados (NO EN REPO)
│   ├── petclinic-feat1/            ← Spring Boot con test feat1 (NO EN REPO)
│   ├── angular-conduit/            ← Angular Conduit (NO EN REPO — node_modules grande)
│   └── react-conduit/              ← React Conduit (NO EN REPO — node_modules grande)
│
├── human_review/
│   ├── instrucciones.md            ← Protocolo completo para revisores humanos
│   ├── plantilla_puntuacion.csv    ← Template vacío (33 filas, 5 ejes por fila)
│   └── prompt_resultado_final.md   ← Prompt LLM para calcular puntuación combinada
│
└── results/
    ├── metrics_springboot.csv      ← Métricas Spring Boot (modelos originales)
    ├── metrics_angular.csv         ← Métricas Angular
    ├── metrics_react.csv           ← Métricas React
    ├── metrics_data.csv            ← Métricas Datos
    ├── metrics_all.csv             ← Consolidado de todos los stacks
    ├── metrics_anon.csv            ← Igual con Modelo A/B/C (para revisión ciega)
    ├── metrics.csv                 ← CSV del piloto original (referencia)
    ├── model_mapping.csv           ← Mapping A/B/C → modelo real (NO ABRIR hasta el final)
    │
    ├── bug1-petvalidator__<modelo>__r<n>/
    │   └── _raw_response.txt       ← Respuesta cruda del modelo (lo que puntuarán los revisores)
    ├── bug2-ownercontroller__<modelo>__r<n>/
    │   └── _raw_response.txt
    ├── sb-feat1-name-length__<modelo>__r<n>/
    │   └── _raw_response.txt
    ├── ng-*/                       ← Angular (bug1, feat1, feat2)
    ├── re-*/                       ← React (bug1, feat1, feat2)
    └── data-*/                     ← Datos (bug1, feat1)
```

---

## 8. Modelos evaluados

### Modelos originales (ya ejecutados)

| Slug OpenRouter | Precio in/out (1M tok) | Alias en métricas |
|-----------------|----------------------|-------------------|
| `minimax/minimax-m3` | $0.30 / $1.20 | minimax-m3 |
| `deepseek/deepseek-v4-flash` | $0.09 / $0.18 | deepseek-v4-flash |
| `z-ai/glm-4.7` | $0.40 / $1.75 | glm-4.7 |

### Modelos nuevos (añadidos, pendientes de ejecutar)

| Slug OpenRouter | Precio in/out (1M tok) | Estado |
|-----------------|----------------------|--------|
| `qwen/qwen3.7-plus` | $0.32 / $1.28 | Pendiente |
| `google/gemini-3.1-flash-lite` | $0.25 / $1.50 | Pendiente |
| `qwen/qwen3-coder-next` | $0.11 / $0.80 | Pendiente |
| `tencent/hy3-preview` | $0.066 / $0.26 | Pendiente |
| `z-ai/glm-5.2` | $1.20 / $4.10 | Pendiente |

> **Nota técnica:** `tencent/hy3-preview` y `z-ai/glm-5.2` necesitan `max_tokens >= 200`
> para responder. Esto ya está configurado en los harnesses.

Para añadir un modelo nuevo en el futuro: edita la lista `MODELS` y el dict `PRICES`
en `run_springboot.py`, `run_angular.py`, `run_react.py` y `run_data.py`.

---

## 9. Resultados automáticos actuales

**3 modelos × 11 tareas × 3 runs = 99 evaluaciones completadas.**

### Resumen ejecutivo

| Modelo | % Tests verdes | Coste medio/tarea | Latencia media |
|--------|---------------|-------------------|----------------|
| deepseek-v4-flash | **97%** | **$0.00022** | **11.9 s** |
| minimax-m3 | 94% | $0.0016 | 16.1 s |
| glm-4.7 | 91% | $0.0038 | 38.8 s |

### Detalle por tarea

| Stack | Tarea | Tipo | minimax-m3 | deepseek-v4-flash | glm-4.7 |
|-------|-------|------|-----------|------------------|---------|
| Spring Boot | Bug-fix: nombre con espacios | Bug-fix | 3/3 ✓ | 3/3 ✓ | 3/3 ✓ |
| Spring Boot | Bug-fix: redirección múltiples owners | Bug-fix | 3/3 ✓ | 3/3 ✓ | 3/3 ✓ |
| Spring Boot | Feat: validación longitud nombre | Feature | 3/3 ✓ | 3/3 ✓ | 2/3 ~ |
| Angular | Bug-fix: input requerido faltante | Bug-fix | 3/3 ✓ | 3/3 ✓ | 3/3 ✓ |
| Angular | Feat: tiempo de lectura | Feature | 3/3 ✓ | 3/3 ✓ | 3/3 ✓ |
| Angular | Feat: búsqueda en servicio | Feature | 3/3 ✓ | 3/3 ✓ | 3/3 ✓ |
| React | Bug-fix: contador favoritos | Bug-fix | 3/3 ✓ | 3/3 ✓ | 3/3 ✓ |
| React | Feat: tiempo de lectura | Feature | 3/3 ✓ | 3/3 ✓ | 3/3 ✓ |
| React | Feat: filtro por autor | Feature | 1/3 ✗ | 2/3 ~ | 1/3 ✗ |
| Datos | Bug-fix: JOIN incorrecto géneros | Bug-fix | 3/3 ✓ | 3/3 ✓ | 3/3 ✓ |
| Datos | Feat: ranking clientes por país | Feature | 3/3 ✓ | 3/3 ✓ | 3/3 ✓ |

> La tarea `re-feat2-author-filter` (filtro por autor en React) fue la más difícil del piloto.
> Requiere coordinar reducer, action y componente en un codebase React/Redux antiguo.
> Todos los modelos rindieron por debajo de su media — señal de que la complejidad de
> integración es el verdadero diferenciador, no los bugs de una línea.

---

## 10. Gobernanza y adopción

Sea cual sea el modelo ganador, necesitamos un mecanismo de control para 300–400 desarrolladores.

### Opción recomendada para arrancar: OpenRouter Organization

1. Crear una **organización** en https://openrouter.ai
2. La API key maestra queda en la empresa
3. Emitir **sub-keys por usuario o equipo** con límite de crédito mensual
4. Configurar **allowlist de modelos** (solo los aprobados)
5. Dashboard de uso por clave; alertas al 80% del límite

### El resultado habitual de este tipo de benchmarks

No hay un único ganador: la estrategia óptima es **routing por complejidad**:
- Modelo **barato** por defecto para el 80% de tareas simples
- Modelo **más potente** reservado para el 20% de tareas difíciles

Consulta la sección "Gobernanza" de `presentacion.html` para las tres opciones
(OpenRouter Organization, proxy interno, contrato Enterprise).

---

## Notas técnicas (troubleshooting)

| Problema | Causa | Solución |
|----------|-------|----------|
| `UnicodeEncodeError` en subprocess | Windows cp1252 vs. UTF-8 | Todos los subprocess usan `encoding="utf-8", errors="replace"` |
| Angular build falla en tests | Vitest + zone.js incompatibilidad | Verificación solo por build (`npm run build`) |
| React tests colgados | Jest en modo watch | Se lanza con `CI=true --watchAll=false` |
| Copiar baseline tarda mucho | Se copiaba `target/` o `node_modules/` | `shutil.ignore_patterns('target', 'node_modules')` + junction links |
| `glm-5.2` responde vacío | `max_tokens` demasiado bajo | Usar `max_tokens >= 200` |
| `hy3-preview` responde vacío | Igual | Usar `max_tokens >= 50` |
| Error al aplicar seed patch | Indentación incorrecta en el string | Los patches usan exactamente 14 espacios en `articleList.js` |

---

*Generado por el piloto de evaluación — junio 2026.*

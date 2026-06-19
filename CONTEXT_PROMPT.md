# Contexto para continuar el proyecto en otro PC

Pega este bloque como primer mensaje al abrir una nueva sesión de Claude Code
(o cualquier LLM con acceso a herramientas de ficheros).

---

## PROMPT DE CONTEXTO

Estoy evaluando modelos de IA vía API (OpenRouter) para adopción empresarial.
Tenemos un benchmark ya ejecutado y quiero continuar el trabajo.

### Repositorio

El proyecto está en `poc-run/`. Ya está en git, remoto: https://github.com/Ufransa/model-benchmarking.git

Clona con:
```
git clone https://github.com/Ufransa/model-benchmarking.git
cd model-benchmarking
```

Necesitas crear `openrouter_key.txt` con tu API key de OpenRouter (NO está en el repo — en .gitignore).

### Estado actual

- **3 modelos ya evaluados**: minimax/minimax-m3, deepseek/deepseek-v4-flash, z-ai/glm-4.7
- **11 tareas × 3 runs = 99 evaluaciones** completadas (Spring Boot, Angular, React, Datos)
- **5 modelos nuevos** añadidos a los harnesses pero **pendientes de ejecutar**:
  - qwen/qwen3.7-plus ($0.32/$1.28 por 1M tok)
  - google/gemini-3.1-flash-lite ($0.25/$1.50)
  - qwen/qwen3-coder-next ($0.11/$0.80)
  - tencent/hy3-preview ($0.066/$0.26)
  - z-ai/glm-5.2 ($1.20/$4.10)
- Los resultados de los 3 modelos originales están en `results/metrics_all.csv`
- El mapping real (A=?, B=?, C=?) está en `results/model_mapping.csv` — NO lo reveles hasta el final

### Ficheros clave

```
poc-run/
├── run_springboot.py       # Harness Spring Boot (1 tarea: sb-feat1-name-length)
├── run_angular.py          # Harness Angular (3 tareas)
├── run_react.py            # Harness React (3 tareas)
├── run_data.py             # Harness Datos (2 tareas)
├── run_all.py              # Lanza los 4 harnesses en paralelo (Windows)
├── merge_metrics.py        # Fusiona los 4 CSVs → metrics_all.csv + metrics_anon.csv
├── test_slugs.py           # Verifica que los slugs de modelos funcionan en OpenRouter
├── presentacion.html       # Presentación ejecutiva con resultados reales
├── human_review/
│   ├── instrucciones.md       # Protocolo para los revisores humanos
│   ├── plantilla_puntuacion.csv  # Template vacío para puntuar (sin mapping)
│   └── prompt_resultado_final.md # Prompt para calcular la puntuación combinada
├── results/
│   ├── metrics_springboot.csv
│   ├── metrics_angular.csv
│   ├── metrics_react.csv
│   ├── metrics_data.csv
│   ├── metrics_all.csv        # Consolidado de los 3 modelos originales
│   ├── metrics_anon.csv       # Igual pero con A/B/C en vez del nombre real
│   └── model_mapping.csv      # Mapping real — NO compartir hasta final de revisión humana
└── baselines/
    ├── petclinic-feat1/       # Spring Boot baseline (con test sb-feat1)
    ├── petclinic-buggy/       # Spring Boot baseline (con 2 bugs sembrados)
    ├── angular-conduit/       # Angular Conduit
    ├── react-conduit/         # React Conduit (CRA 1.x)
    └── data-chinook/          # Chinook SQLite + scripts Python
```

### Próximos pasos sugeridos

1. **Ejecutar los 5 modelos nuevos**: `python run_all.py` (abre 4 ventanas en paralelo)
   - Solo ejecutará los 5 modelos nuevos si los CSVs ya existen (modo append)
   - Si quieres re-ejecutar todos: borra los 4 CSVs de `results/` antes
2. **Fusionar resultados**: `python merge_metrics.py`
3. **Iniciar la revisión humana**: ver `human_review/instrucciones.md`
4. **Calcular puntuación final**: usar `human_review/prompt_resultado_final.md`

### Restricciones técnicas conocidas

- Windows: todos los subprocess usan `encoding="utf-8", errors="replace"` para evitar crash cp1252
- Angular: verificación solo por build (Vitest + zone.js roto en este entorno)
- React: test con `CI=true npm test -- --watchAll=false --testPathPattern=<pattern>`
- node_modules: se copia vía junction (`mklink /J`) para evitar copiar 400MB por run
- Datos: los scripts Python generados necesitan `PYTHONIOENCODING=utf-8` en el entorno
- Spring Boot: `shutil.copytree` ignora `target/` para no copiar 200MB por run
- glm-5.2 y tencent/hy3-preview necesitan `max_tokens` > 50 para responder (usar >= 200)

### Seguridad

- `openrouter_key.txt` está en `.gitignore`. Nunca commitear la key real.
- El fichero del repo es `openrouter_key.txt` (vacío, con placeholder "PEGA_AQUI_TU_KEY").
- El mapping real `model_mapping.csv` no se comparte con revisores hasta el final del proceso.

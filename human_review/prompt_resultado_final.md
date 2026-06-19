# Prompt para calcular la puntuación final combinada

Pega este prompt en cualquier LLM (Claude, GPT-4, etc.) **después de revelar el mapping real**
y de rellenar `plantilla_puntuacion_FINAL.csv`. Sustituye los bloques marcados con `[...]`.

---

## PROMPT

Eres un analista que ayuda a una empresa de ~300-400 desarrolladores a elegir
el modelo de IA que adoptará vía API para uso diario de desarrollo.

A continuación te proporciono los datos de un benchmark ejecutado sobre 4 stacks
(Spring Boot, Angular, React, Datos). La evaluación tiene dos capas:
1. Automática: % de tests que pasan, coste por tarea, latencia.
2. Humana: rúbrica de calidad en 5 ejes (1-5), evaluada con doble ciego.

### Datos automáticos (por modelo)

| Modelo | % Tests verdes | Coste medio/tarea | Latencia media |
|--------|---------------|-------------------|----------------|
[PEGA AQUÍ LA FILA DE CADA MODELO CON SUS DATOS REALES — YA TIENES EL MAPPING]

### Puntuaciones humanas (media de los 5 ejes, por modelo)

[PEGA AQUÍ LAS MEDIAS POR MODELO DE plantilla_puntuacion_FINAL.csv]
Formato: Modelo X: eje1=Y, eje2=Y, eje3=Y, eje4=Y, eje5=Y, media_global=Y

### Preguntas que quiero que respondas

1. **Ranking global**: Combina la capa automática y la humana con estos pesos:
   - Tests verdes: 30%
   - Calidad humana media: 40%
   - Coste: 20%
   - Latencia: 10%
   Normaliza cada dimensión (0-1) antes de ponderar. Muestra la puntuación final de cada modelo.

2. **Umbral de calidad mínima**: ¿Hay algún modelo con media humana < 3 en algún eje crítico
   (correctitud o seguridad)? Si es así, descártalo antes de mirar el precio.

3. **Estrategia de routing** (la más probable en benchmarks de este tipo):
   Propón qué modelo usar por defecto para el 80% de tareas simples y cuál reservar
   para el 20% de tareas difíciles, justificando con los datos.

4. **Coste proyectado a 12 meses** si el equipo hace ~50 llamadas/desarrollador/día
   con un prompt medio de 1.000 tokens de entrada y 500 de salida:
   - Calcula el coste anual por modelo.
   - Calcula el ahorro vs. el modelo más caro.

5. **Recomendación ejecutiva** (máx. 150 palabras): qué modelo(s) adoptar, con qué
   condiciones de gobernanza (ver sección Gobernanza en la presentación) y cuándo
   revisar la decisión.

Responde en español, con tablas donde sea útil.

---

## Cómo usar este prompt

1. Abre `results/model_mapping.csv` para saber qué es A, B y C.
2. Copia la tabla de datos automáticos de `results/metrics_all.csv` (ya calculada en la presentación).
3. Calcula las medias por eje de `human_review/plantilla_puntuacion_FINAL.csv`.
4. Pega todo en el prompt y envíalo a un LLM.
5. La decisión final la tomáis las personas, usando el análisis del LLM como apoyo.

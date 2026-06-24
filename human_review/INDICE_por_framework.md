# Índice de respuestas ciegas por framework

Cada modelo está anonimizado (Modelo A–K). El framework se identifica por el **prefijo** del nombre del fichero:

| Prefijo | Framework |
|---------|-----------|
| `bug1-` / `bug2-` / `sb-` | Spring Boot (Java) |
| `ng-` | Angular |
| `re-` | React |
| `data-` | Datos (SQL/pandas, Chinook) |

## Spring Boot (33 respuestas)
- `*__bug1-petvalidator.txt` — Bug-fix: nombre solo-espacios se acepta como válido
- `*__bug2-ownercontroller.txt` — Bug-fix: redirige con varios resultados en vez de mostrar lista
- `*__sb-feat1-name-length.txt` — Feature: rechazar nombre > 50 chars (error `tooLong`)

## Angular (33 respuestas)
- `*__ng-bug1-missing-input.txt` — Bug-fix: falta `@Input()` en `config`
- `*__ng-feat1-reading-time.txt` — Feature: método `getReadingTime()` (tiempo de lectura)
- `*__ng-feat2-service-search.txt` — Feature: implementar `search()` en el servicio

## React (33 respuestas)
- `*__re-bug1-favorite-count.txt` — Bug-fix: el reducer no actualiza `favoritesCount`
- `*__re-feat1-reading-time.txt` — Feature: función `getReadingTime(body)`
- `*__re-feat2-author-filter.txt` — Feature: acción `FILTER_BY_AUTHOR` en el reducer

## Datos (22 respuestas)
- `*__data-bug1-sales-genre.txt` — Bug-fix: JOIN incorrecto en ventas por género
- `*__data-feat1-customer-ranking.txt` — Feature: ranking de clientes por país (window functions)

> Para cada respuesta, las 5 preguntas (rúbrica 1–5) están en `instrucciones.md`:
> correctitud · calidad/idiomaticidad · seguridad · cumplimiento · esfuerzo de arreglo.

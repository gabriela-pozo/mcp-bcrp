# mcp-bcrp

Servidor MCP (FastMCP) con las series oficiales del Banco Central de Reserva del Perú (BCRP): busca series en el
catálogo, descarga sus datos de la API y calcula variaciones, siempre con el código, el periodo y la fuente.

- **Herramientas:** `buscar_series`, `serie`, `resumen`, `comparar` y `ultimo_dato`.
- **Recurso:** `bcrp://serie/{codigo}`, con la ficha de la serie (nombre, categoría, frecuencia, desde cuándo hay datos).
- **Prompt:** `informe(tema)`, que pide un informe breve citando código, periodo y fuente de cada cifra. El tema debe
  ser una sola palabra, porque Claude Code separa los argumentos por espacios (`/mcp__bcrp__informe inflación`).

## Cómo correrlo

```bash
uv run pytest -q test_server.py                              # pruebas con datos reales del BCRP
claude mcp add --scope project bcrp -- uv run server.py      # conectar a Claude Code (.mcp.json)
uv run evaluar.py                                            # memoria contra mcp, con Haiku
uv run grafico.py                                            # regenera grafico.png
```

En Windows, antes de `evaluar.py`: `$env:PYTHONUTF8 = "1"`. Para el modo web y la corrida sin null:
`uv run evaluar.py --modos web --salida resultados_web.csv` y `uv run evaluar.py --sin-null --salida resultados_sin_null.csv`.

## Resultados

Con Haiku y 10 preguntas, memoria acertó 0 (10 «no sabe»), web 9 y MCP 10. Detalle en [informe.md](informe.md).

## Archivos

| Archivo | Qué es |
|---|---|
| `server.py` | El servidor MCP |
| `test_server.py`, `test_mia.py` | Pruebas del curso y pruebas propias |
| `.mcp.json` | Servidores `bcrp` y `fetch` para Claude Code |
| `preguntas.csv` | 10 preguntas con la cifra oficial y su tolerancia |
| `evaluar.py` | Hace cada pregunta con `claude -p` en modo memoria, web o mcp y califica |
| `resultados_base.csv`, `resultados_sin_null.csv`, `resultados_web.csv` | Corridas de la evaluación (`resultados.csv` es igual a la base) |
| `grafico.py`, `grafico.png` | Gráfico de resultados por modo y corrida |
| `informe.md` | Resultados, fallos, experimento sin null, verificación a mano y conclusión |

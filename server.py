"""Servidor MCP del BCRP. Empiecen aquí: buscar_series ya funciona; completen los TODO hasta que pasen las pruebas.

    uv run pytest                                           # el contrato: las 8 pruebas deben pasar
    uv run server.py                                        # el servidor, por stdio
    claude mcp add --scope project bcrp -- uv run server.py # conectarlo a Claude Code

Las cuentas las hace Python, no el modelo: así cada cifra sale de una llamada que se puede repetir.
"""
import json
import re
import time
import unicodedata
from functools import cache
from pathlib import Path

import httpx
import pandas as pd
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

AQUI = Path(__file__).parent
CATALOGO = AQUI / "datos" / "catalogo_bcrp.csv"
URL_CATALOGO = "https://estadisticas.bcrp.gob.pe/estadisticas/series/metadata"
API = "https://estadisticas.bcrp.gob.pe/estadisticas/series/api"
SOLO_LECTURA = {"readOnlyHint": True, "openWorldHint": True}

mcp = FastMCP("bcrp", instructions=(
    "Series oficiales del Banco Central de Reserva del Perú (BCRP). Primero busca el código con buscar_series; "
    "luego usa resumen para variaciones, promedios y extremos, y serie para los datos. No calcules a mano: "
    "cita siempre el código de la serie y el periodo."))


def _sin_tildes(s):
    return unicodedata.normalize("NFD", str(s).lower()).encode("ascii", "ignore").decode()


@cache
def catalogo():
    """El catálogo oficial: 17 mil series en unos 7 MB. Se baja una vez y queda en datos/."""
    if not CATALOGO.exists():
        CATALOGO.parent.mkdir(exist_ok=True)
        r = httpx.get(URL_CATALOGO, timeout=120)
        r.raise_for_status()
        CATALOGO.write_text(r.content.decode("latin-1"), encoding="utf-8")
    df = pd.read_csv(CATALOGO, sep=";", dtype=str).fillna("")
    df = df.rename(columns={"Código de serie": "codigo", "Categoría de serie": "categoria", "Grupo de serie": "grupo",
                            "Nombre de serie": "nombre", "Frecuencia": "frecuencia",
                            "Fecha de actualización": "actualizada", "Fecha de inicio": "inicio"})
    df["texto"] = (df.categoria + " " + df.grupo + " " + df.nombre).map(_sin_tildes)
    return df


def _ficha(codigo):
    fila = catalogo().query("codigo == @codigo")
    if fila.empty:
        raise ToolError(f"No existe el código de serie {codigo!r}. Búsquenlo con buscar_series.")
    f = fila.iloc[0]
    return {"codigo": f.codigo, "nombre": f"{f.grupo} - {f.nombre}", "categoria": f.categoria,
            "frecuencia": f.frecuencia, "inicio": f.inicio, "actualizada": f.actualizada}


@mcp.tool(annotations=SOLO_LECTURA)
def buscar_series(texto: str, frecuencia: str | None = None, limite: int = 10) -> list[dict]:
    """Busca series del BCRP por palabras: todas deben aparecer en la categoría, el grupo o el nombre.

    Ejemplos: "ipc 12 meses", "tipo de cambio interbancario venta", "reservas internacionales netas",
    "tasa de referencia", "cobre precio". frecuencia: "Diaria", "Mensual", "Trimestral" o "Anual".
    Devuelve el código, el nombre completo, la frecuencia y desde cuándo hay datos. Si no hay resultados,
    prueben con menos palabras.
    """
    df = catalogo()
    m = pd.Series(True, index=df.index)
    for palabra in _sin_tildes(texto).split():
        m &= df.texto.str.contains(re.escape(palabra))
    if frecuencia:
        m &= df.frecuencia.str.lower() == frecuencia.lower()
    # primero las series vigentes y, entre ellas, las de nombre más corto (las más generales)
    sel = df[m]
    orden = sel.assign(vieja=sel.actualizada < "2025", largo=(sel.grupo + sel.nombre).str.len())
    return [_ficha(c) for c in orden.sort_values(["vieja", "largo"]).head(limite).codigo]


MESES = {"Ene": 1, "Feb": 2, "Mar": 3, "Abr": 4, "May": 5, "Jun": 6,
         "Jul": 7, "Ago": 8, "Sep": 9, "Set": 9, "Oct": 10, "Nov": 11, "Dic": 12}   # setiembre llega como Sep o Set
EJEMPLOS = {"Mensual": "2025-01", "Trimestral": "2025-T1", "Diaria": "2026-10-15", "Anual": "2025"}


def _fecha_api(fecha, frecuencia):
    """Fecha del usuario -> fecha que pide la API: 2025-01 -> 2025-1, 2025-T1 -> 2025-1, 2026-10-15 y 2025 igual."""
    if frecuencia not in EJEMPLOS:
        raise ToolError(f"Frecuencia {frecuencia!r} no soportada: solo {', '.join(EJEMPLOS)}.")
    patrones = {"Mensual": r"(\d{4})-(0?[1-9]|1[0-2])", "Trimestral": r"(\d{4})-T?([1-4])",
                "Diaria": r"(\d{4})-(\d{2})-(\d{2})", "Anual": r"(\d{4})"}
    m = re.fullmatch(patrones[frecuencia], str(fecha).strip())
    if not m:
        raise ToolError(f"Fecha {fecha!r} inválida para una serie {frecuencia.lower()}: usen {EJEMPLOS[frecuencia]!r}.")
    if frecuencia == "Diaria":
        return m.group(0)
    return "-".join(str(int(g)) for g in m.groups())


def _año(yy):
    """La API diaria y trimestral da el año en 2 dígitos: 26 -> 2026, 97 -> 1997."""
    return 2000 + int(yy) if int(yy) < 50 else 1900 + int(yy)


def _periodo(nombre, frecuencia):
    """Nombre de periodo de la API -> Ene.2025: 2025-01, 01.Oct.26: 2026-10-01, T1.25: 2025-T1, 2025: 2025."""
    partes = nombre.split(".")
    if frecuencia == "Mensual":
        mes, año = partes
        return f"{año}-{MESES[mes]:02d}"
    if frecuencia == "Diaria":
        dia, mes, yy = partes
        return f"{_año(yy)}-{MESES[mes]:02d}-{int(dia):02d}"
    if frecuencia == "Trimestral":
        trimestre, yy = partes
        return f"{_año(yy)}-{trimestre}"
    return nombre


def _decodificar(contenido):
    """La API declara UTF-8, pero a veces manda latin-1."""
    try:
        return contenido.decode("utf-8")
    except UnicodeDecodeError:
        return contenido.decode("latin-1")


@cache
def _bajar(url, intentos=4, espera=3):
    """GET con caché. Si la API está saturada responde HTML en vez de JSON: espera y reintenta."""
    for i in range(intentos):
        try:
            r = httpx.get(url, timeout=60)
            r.raise_for_status()
            return json.loads(_decodificar(r.content))
        except (httpx.HTTPError, json.JSONDecodeError):
            if i < intentos - 1:
                time.sleep(espera * (i + 1))
    raise ToolError(f"La API del BCRP no devolvió datos tras {intentos} intentos: {url}")


@mcp.tool(annotations=SOLO_LECTURA)
def serie(codigo: str, desde: str, hasta: str) -> dict:
    """Datos oficiales de una serie del BCRP entre dos fechas (inclusive).

    desde y hasta van en el formato de la frecuencia de la serie: "2025-01" (mensual), "2025-T1" (trimestral),
    "2026-10-15" (diaria) o "2025" (anual). Busquen antes el código con buscar_series.
    Devuelve el código, el nombre, la frecuencia, los datos como [{periodo, valor}] y la URL de la fuente.
    Los periodos sin dato ("n.d.", como feriados) se omiten.
    """
    ficha = _ficha(codigo)
    frecuencia = ficha["frecuencia"]
    url = f"{API}/{codigo}/json/{_fecha_api(desde, frecuencia)}/{_fecha_api(hasta, frecuencia)}"
    datos = [{"periodo": _periodo(p["name"], frecuencia), "valor": float(p["values"][0])}
             for p in _bajar(url)["periods"] if p["values"][0] != "n.d."]
    if not datos:
        raise ToolError(f"La serie {codigo} no tiene datos entre {desde!r} y {hasta!r}.")
    return {"codigo": codigo, "nombre": ficha["nombre"], "frecuencia": frecuencia, "datos": datos, "fuente": url}

# TODO 2 · resumen(codigo, desde, hasta): primero, ultimo, cambio, variacion_pct, promedio, maximo y minimo
#   (los tres últimos con su periodo). Úsenla para que el modelo nunca haga cuentas a mano.

# TODO 3 · Una herramienta suya, bien descrita. Ideas:
#   - comparar_paises con la API del Banco Mundial, que tampoco pide clave:
#     https://api.worldbank.org/v2/country/PER;CHL;COL/indicator/NY.GDP.MKTP.KD.ZG?format=json&date=2015:2025
#   - correlacion(codigo_a, codigo_b, desde, hasta)
#   - grafico(codigo, desde, hasta) que guarde un PNG en salidas/ y devuelva la ruta

# TODO 4 · Un recurso, por ejemplo la plantilla bcrp://serie/{codigo} con la ficha de la serie.

# TODO 5 · Un prompt, por ejemplo informe(tema) que pida citar el código y el periodo de cada cifra.


if __name__ == "__main__":
    mcp.run()

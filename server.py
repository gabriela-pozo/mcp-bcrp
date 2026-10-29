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
from datetime import date, timedelta
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


class SinDatos(ToolError):
    """La consulta funcionó pero el rango no trae datos (distinto de una caída de la API)."""


def _datos_serie(codigo, desde, hasta):
    """Lo que comparten serie y resumen: ficha, fechas, descarga y periodos normalizados."""
    ficha = _ficha(codigo)
    frecuencia = ficha["frecuencia"]
    url = f"{API}/{codigo}/json/{_fecha_api(desde, frecuencia)}/{_fecha_api(hasta, frecuencia)}"
    datos = [{"periodo": _periodo(p["name"], frecuencia), "valor": float(p["values"][0])}
             for p in _bajar(url)["periods"] if p["values"][0] != "n.d."]
    if not datos:
        raise SinDatos(f"La serie {codigo} no tiene datos entre {desde!r} y {hasta!r}.")
    return {"codigo": codigo, "nombre": ficha["nombre"], "frecuencia": frecuencia, "datos": datos, "fuente": url}


@mcp.tool(annotations=SOLO_LECTURA)
def serie(codigo: str, desde: str, hasta: str) -> dict:
    """Datos oficiales de una serie del BCRP entre dos fechas (inclusive).

    desde y hasta van en el formato de la frecuencia de la serie: "2025-01" (mensual), "2025-T1" (trimestral),
    "2026-10-15" (diaria) o "2025" (anual). Busquen antes el código con buscar_series.
    Devuelve el código, el nombre, la frecuencia, los datos como [{periodo, valor}] y la URL de la fuente.
    Los periodos sin dato ("n.d.", como feriados) se omiten.
    """
    return _datos_serie(codigo, desde, hasta)


def _punto(d):
    return {"periodo": d["periodo"], "valor": round(d["valor"], 4)}


def _resumir(datos):
    """Las cuentas del resumen, sobre [{periodo, valor}] ya ordenado por periodo."""
    primero, ultimo = datos[0], datos[-1]
    cambio = ultimo["valor"] - primero["valor"]
    return {"n": len(datos), "primero": _punto(primero), "ultimo": _punto(ultimo),
            "maximo": _punto(max(datos, key=lambda d: d["valor"])),
            "minimo": _punto(min(datos, key=lambda d: d["valor"])),
            "cambio": round(cambio, 4),
            "variacion_pct": round(cambio / primero["valor"] * 100, 4) if primero["valor"] else None,
            "promedio": round(sum(d["valor"] for d in datos) / len(datos), 4)}


@mcp.tool(annotations=SOLO_LECTURA)
def resumen(codigo: str, desde: str, hasta: str) -> dict:
    """Resume una serie del BCRP entre dos fechas: primero, último, máximo y mínimo (con su periodo), cambio,
    variación porcentual, promedio y número de datos.

    Úsenla siempre que la pregunta pida variaciones, promedios o extremos: no hagan esas cuentas a mano.
    Las fechas van como en serie: "2025-01", "2025-T1", "2026-10-15" o "2025".
    cambio = último - primero, en la unidad de la serie. Para series que ya son porcentajes (inflación, tasas
    de interés, variaciones del PBI) el dato útil es cambio, en puntos porcentuales; variacion_pct sería un
    porcentaje de un porcentaje. variacion_pct es None si el primer valor es 0.
    Citen el código, los periodos y la fuente que devuelve.
    """
    s = _datos_serie(codigo, desde, hasta)
    return {"codigo": s["codigo"], "nombre": s["nombre"], "frecuencia": s["frecuencia"],
            **_resumir(s["datos"]), "fuente": s["fuente"]}


def _alinear(listas):
    """Periodos comunes a todas las listas [{periodo, valor}], en orden, y los valores de cada una en ellos."""
    por_periodo = [{d["periodo"]: d["valor"] for d in datos} for datos in listas]
    periodos = [p for p in por_periodo[0] if all(p in otra for otra in por_periodo[1:])]
    return periodos, [[serie[p] for p in periodos] for serie in por_periodo]


def _validar_codigos(codigos):
    if not 2 <= len(codigos) <= 5:
        raise ToolError(f"comparar necesita de 2 a 5 códigos y recibió {len(codigos)}: {codigos}.")
    repetidos = sorted({c for c in codigos if codigos.count(c) > 1})
    if repetidos:
        raise ToolError(f"Códigos repetidos: {repetidos}. Pongan cada serie una sola vez.")


def _misma_frecuencia(frecuencias):
    """frecuencias: {codigo: frecuencia}."""
    if len(set(frecuencias.values())) > 1:
        detalle = ", ".join(f"{c} ({f})" for c, f in frecuencias.items())
        raise ToolError(f"Las series tienen frecuencias distintas: {detalle}. Comparen series de la misma frecuencia.")


def _comparar(series):
    """Las cuentas de comparar, sobre salidas de _datos_serie de la misma frecuencia."""
    periodos, valores = _alinear([s["datos"] for s in series])
    if len(periodos) < 2:
        codigos = [s["codigo"] for s in series]
        raise ToolError(f"Las series {codigos} tienen {len(periodos)} periodo(s) en común: {periodos}. Se necesitan 2.")
    resultado = []
    for s, v in zip(series, valores):
        r = _resumir([{"periodo": p, "valor": x} for p, x in zip(periodos, v)])
        resultado.append({"codigo": s["codigo"], "nombre": s["nombre"], "valores": [round(x, 4) for x in v],
                          "indice_base_100": [round(x / v[0] * 100, 4) for x in v] if v[0] > 0 else None,
                          "cambio": r["cambio"], "variacion_pct": r["variacion_pct"], "fuente": s["fuente"]})
    return {"frecuencia": series[0]["frecuencia"], "periodos": periodos, "series": resultado}


@mcp.tool(annotations=SOLO_LECTURA)
def comparar(codigos: list[str], desde: str, hasta: str) -> dict:
    """Compara la evolución de 2 a 5 series del BCRP de la misma frecuencia en los periodos que tienen en común.

    Para cada serie devuelve sus valores, un índice con base 100 en el primer periodo común, el cambio y la
    variación % entre el primer y el último periodo común, y su fuente.
    Cuándo usarla: con series en niveles (índices, tipo de cambio, reservas, precios), para ver cuál creció más
    aunque estén en unidades distintas (millones de US$, soles por dólar), mirando indice_base_100 o variacion_pct.
    Cuándo no: con series que ya son porcentajes o tasas (inflación, tasa de referencia, crecimiento del PBI):
    para esas usen resumen en cada una y comparen sus "cambio", en puntos porcentuales. Para una sola serie, usen
    resumen. No sirve para medir una relación estadística (correlación) entre series. Si el primer valor común
    es 0 o negativo, indice_base_100 es None.
    Ejemplo: comparar(["PN00027MM", "PN38784BM"], "2025-01", "2026-08") compara las reservas internacionales netas
    con el precio del cobre. Las fechas van como en serie. Citen los códigos, los periodos y las fuentes.
    """
    _validar_codigos(codigos)
    _misma_frecuencia({c: _ficha(c)["frecuencia"] for c in codigos})
    return _comparar([_datos_serie(c, desde, hasta) for c in codigos])


def _ultimo(datos):
    """El último {periodo, valor} con valor no nulo de [{periodo, valor}] ordenado por periodo, o None."""
    return next(({"periodo": d["periodo"], "valor": d["valor"]} for d in reversed(datos) if d["valor"] is not None),
                None)


def _ventana(frecuencia, hoy):
    """(desde, hasta) que terminan hoy: 45 días, 24 meses, 12 trimestres o 5 años, en el formato de serie."""
    if frecuencia == "Diaria":
        return (hoy - timedelta(days=45)).isoformat(), hoy.isoformat()
    if frecuencia == "Mensual":
        m = hoy.year * 12 + hoy.month - 1 - 23
        return f"{m // 12}-{m % 12 + 1:02d}", f"{hoy.year}-{hoy.month:02d}"
    if frecuencia == "Trimestral":
        q = hoy.year * 4 + (hoy.month - 1) // 3 - 11
        return f"{q // 4}-T{q % 4 + 1}", f"{hoy.year}-T{(hoy.month - 1) // 3 + 1}"
    if frecuencia == "Anual":
        return str(hoy.year - 4), str(hoy.year)
    raise ToolError(f"Frecuencia {frecuencia!r} no soportada: solo {', '.join(EJEMPLOS)}.")


@mcp.tool(annotations=SOLO_LECTURA)
def ultimo_dato(codigo: str) -> dict:
    """El dato más reciente publicado de una serie del BCRP, con su periodo.

    Cuándo usarla: cuando pregunten por el "último dato", el valor "más reciente" o "actual" de una serie
    (la inflación actual, el tipo de cambio de hoy, la última tasa de referencia).
    Cuándo no: si piden un periodo concreto ("en marzo de 2025", "entre 2024 y 2025"), usen serie o resumen.
    Devuelve el código, el nombre, la frecuencia, el periodo y el valor del último dato, la fuente y la fecha
    de la consulta (consultado). Ejemplo: ultimo_dato("PN01273PM") da la inflación a 12 meses más reciente.
    Citen el código, el periodo y la fuente.
    """
    ficha = _ficha(codigo)
    hoy = date.today()
    desde, hasta = _ventana(ficha["frecuencia"], hoy)
    try:
        s = _datos_serie(codigo, desde, hasta)
    except SinDatos:
        s = {"datos": []}
    ultimo = _ultimo(s["datos"])
    if ultimo is None:
        raise ToolError(f"La serie {codigo} no tiene datos entre {desde!r} y {hasta!r}: puede estar discontinuada "
                        f"(datos desde {ficha['inicio']}, última actualización del catálogo: {ficha['actualizada']}).")
    return {"codigo": codigo, "nombre": s["nombre"], "frecuencia": s["frecuencia"], **ultimo,
            "fuente": s["fuente"], "consultado": hoy.isoformat()}


@mcp.resource("bcrp://serie/{codigo}", mime_type="application/json")
def ficha_serie(codigo: str) -> str:
    """Ficha de una serie del BCRP: nombre, categoría, frecuencia, desde cuándo hay datos, última actualización
    y el formato de fecha que piden serie, resumen y comparar. Sale del catálogo oficial, sin consultar datos."""
    ficha = _ficha(codigo)
    return json.dumps({**ficha, "formato_fecha": EJEMPLOS.get(ficha["frecuencia"]), "fuente": URL_CATALOGO},
                      ensure_ascii=False)

@mcp.prompt
def informe(tema: str) -> str:
    """Pide un informe breve sobre un tema económico del Perú con cifras oficiales del BCRP, cada una citada."""
    return (f"Escribe un informe breve sobre: {tema}.\n\n"
            "Reglas:\n"
            "1. Toda cifra sale de las herramientas del servidor bcrp, nunca de tu memoria. Primero busca los códigos "
            "con buscar_series.\n"
            "2. No hagas cuentas a mano: para variaciones, promedios y extremos usa resumen; para ver la evolución de "
            "varias series en niveles usa comparar; para los datos, serie.\n"
            "3. En series que ya son porcentajes o tasas (inflación, tasa de referencia, crecimiento del PBI), "
            "reporta los cambios en puntos porcentuales.\n"
            "4. Junto a cada cifra cita el código de la serie, el periodo y la fuente (la URL que devuelve la "
            "herramienta).\n"
            "5. Si no encuentras una serie o un dato, dilo: no estimes.")


if __name__ == "__main__":
    mcp.run()

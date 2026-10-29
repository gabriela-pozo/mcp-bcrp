"""Pruebas propias: los helpers puros sin red y, al final, una con datos reales del BCRP.

    uv run pytest -q test_mia.py
"""
import json

import pytest
from fastmcp.exceptions import ToolError

from server import (_alinear, _comparar, _fecha_api, _misma_frecuencia, _periodo, _resumir, _validar_codigos,
                    ficha_serie, serie)


@pytest.mark.parametrize("fecha, frecuencia, api", [
    ("2025-01", "Mensual", "2025-1"), ("2025-12", "Mensual", "2025-12"), ("2025-1", "Mensual", "2025-1"),
    ("2025-T1", "Trimestral", "2025-1"), ("2026-10-01", "Diaria", "2026-10-01"), ("2025", "Anual", "2025"),
])
def test_fecha_api(fecha, frecuencia, api):
    assert _fecha_api(fecha, frecuencia) == api


@pytest.mark.parametrize("fecha, frecuencia", [("2025-13", "Mensual"), ("2025-T5", "Trimestral"),
                                               ("01/10/2026", "Diaria"), ("25", "Anual")])
def test_fecha_invalida_nombra_el_valor(fecha, frecuencia):
    with pytest.raises(ToolError, match=fecha):
        _fecha_api(fecha, frecuencia)


def test_frecuencia_no_soportada():
    with pytest.raises(ToolError, match="Semanal"):
        _fecha_api("2025-01", "Semanal")


@pytest.mark.parametrize("nombre, frecuencia, periodo", [
    ("Ene.2025", "Mensual", "2025-01"), ("Sep.2025", "Mensual", "2025-09"), ("Set.2025", "Mensual", "2025-09"),
    ("01.Oct.26", "Diaria", "2026-10-01"), ("15.Dic.97", "Diaria", "1997-12-15"),
    ("T1.25", "Trimestral", "2025-T1"), ("2025", "Anual", "2025"),
])
def test_periodo(nombre, frecuencia, periodo):
    assert _periodo(nombre, frecuencia) == periodo


def test_resumir():
    datos = [{"periodo": "2025-01", "valor": 2.0}, {"periodo": "2025-02", "valor": 5.0},
             {"periodo": "2025-03", "valor": 1.0}, {"periodo": "2025-04", "valor": 3.0}]
    r = _resumir(datos)
    assert r["n"] == 4
    assert r["primero"] == {"periodo": "2025-01", "valor": 2.0}
    assert r["ultimo"] == {"periodo": "2025-04", "valor": 3.0}
    assert r["maximo"] == {"periodo": "2025-02", "valor": 5.0}
    assert r["minimo"] == {"periodo": "2025-03", "valor": 1.0}
    assert (r["cambio"], r["variacion_pct"], r["promedio"]) == (1.0, 50.0, 2.75)


def test_resumir_redondea_y_no_divide_entre_cero():
    r = _resumir([{"periodo": "2025-01", "valor": 0.0}, {"periodo": "2025-02", "valor": 0.1 + 0.2}])
    assert r["variacion_pct"] is None
    assert r["cambio"] == 0.3 and r["ultimo"]["valor"] == 0.3


def _s(codigo, pares, frecuencia="Mensual"):
    """Una salida de _datos_serie inventada."""
    return {"codigo": codigo, "nombre": f"Serie {codigo}", "frecuencia": frecuencia, "fuente": f"https://x/{codigo}",
            "datos": [{"periodo": p, "valor": v} for p, v in pares]}


def test_alinear_deja_solo_periodos_comunes_en_orden():
    a = [{"periodo": p, "valor": v} for p, v in [("2025-01", 1), ("2025-02", 2), ("2025-03", 3)]]
    b = [{"periodo": p, "valor": v} for p, v in [("2025-02", 20), ("2025-03", 30), ("2025-04", 40)]]
    assert _alinear([a, b]) == (["2025-02", "2025-03"], [[2, 3], [20, 30]])


def test_comparar():
    r = _comparar([_s("A", [("2025-01", 200.0), ("2025-02", 210.0), ("2025-03", 250.0)]),
                   _s("B", [("2025-01", 4.0), ("2025-02", 3.0), ("2025-03", 3.0), ("2025-04", 9.0)])])
    assert r["periodos"] == ["2025-01", "2025-02", "2025-03"]
    a, b = r["series"]
    assert a == {"codigo": "A", "nombre": "Serie A", "valores": [200.0, 210.0, 250.0],
                 "indice_base_100": [100.0, 105.0, 125.0], "cambio": 50.0, "variacion_pct": 25.0,
                 "fuente": "https://x/A"}
    assert (b["indice_base_100"], b["cambio"], b["variacion_pct"]) == ([100.0, 75.0, 75.0], -1.0, -25.0)


def test_comparar_redondea_y_base_no_positiva_da_none():
    r = _comparar([_s("A", [("2025-01", 3.0), ("2025-02", 1.0)]), _s("B", [("2025-01", -0.5), ("2025-02", 0.1 + 0.2)])])
    a, b = r["series"]
    assert a["indice_base_100"] == [100.0, 33.3333]
    assert b["indice_base_100"] is None and b["valores"] == [-0.5, 0.3]


def test_comparar_pocos_periodos_comunes():
    with pytest.raises(ToolError, match="2025-02"):
        _comparar([_s("A", [("2025-01", 1.0), ("2025-02", 2.0)]), _s("B", [("2025-02", 1.0), ("2025-03", 2.0)])])


@pytest.mark.parametrize("codigos, nombrado", [(["A"], "A"), (["A", "B", "C", "D", "E", "F"], "F"),
                                               (["A", "B", "A"], "'A'")])
def test_validar_codigos(codigos, nombrado):
    with pytest.raises(ToolError, match=nombrado):
        _validar_codigos(codigos)


def test_misma_frecuencia():
    _misma_frecuencia({"A": "Mensual", "B": "Mensual"})
    with pytest.raises(ToolError, match=r"B \(Diaria\)"):
        _misma_frecuencia({"A": "Mensual", "B": "Diaria"})


def test_serie_anual_pbi_2025():   # con red: la frecuencia anual, que test_server.py no cubre
    r = serie("PM04923AA", "2025", "2025")
    assert r["frecuencia"] == "Anual"
    assert r["datos"] == [{"periodo": "2025", "valor": pytest.approx(3.4306, abs=0.05)}]
    assert r["fuente"].startswith("https://estadisticas.bcrp.gob.pe")


def test_ficha_serie():   # lee el catálogo local, no la API
    f = json.loads(ficha_serie("PN01271PM"))
    assert (f["codigo"], f["frecuencia"], f["formato_fecha"]) == ("PN01271PM", "Mensual", "2025-01")
    assert f["fuente"].startswith("https://estadisticas.bcrp.gob.pe")
    with pytest.raises(ToolError, match="XX999"):
        ficha_serie("XX999")

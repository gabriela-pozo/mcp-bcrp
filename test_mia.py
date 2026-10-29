"""Pruebas propias: los helpers de fechas, sin red.

    uv run pytest -q test_mia.py
"""
import pytest
from fastmcp.exceptions import ToolError

from server import _fecha_api, _periodo, _resumir


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

"""Pruebas propias: los helpers de fechas, sin red.

    uv run pytest -q test_mia.py
"""
import pytest
from fastmcp.exceptions import ToolError

from server import _fecha_api, _periodo


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

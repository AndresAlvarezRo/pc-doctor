"""Pruebas que solo tienen sentido en la PC de desarrollo: leen sensores y procesos REALES. Se saltean en CI (-m "not local")."""

import pytest

import actividad
import consultas
import salud

pytestmark = pytest.mark.local


def test_se_leen_sensores_reales():
    nombres = {l["nombre"] for l in salud.leer_lecturas()}
    assert "cpu/uso" in nombres and "memoria/ram_pct" in nombres


def test_el_estado_en_vivo_con_sensores_reales(con):
    e = consultas.estado_en_vivo(con, {"umbrales": {}})
    assert e["lecturas"] and e["contexto"] in ("reposo", "carga", "juego")


def test_la_deteccion_de_juegos_con_procesos_reales_no_falla():
    assert isinstance(actividad.detectar(), list)

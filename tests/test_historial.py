"""historial(): métricas de siempre y, además, cualquier sensor de `lecturas` completado con el registro diario permanente.
Rescatadas de las pruebas de la Fase 2 (BITACORA.md)."""

import time

import pytest

import db
import server

D = 86400


@pytest.fixture
def datos(con):
    """10 días crudos (reposo ~50, juego 75) y 60 días de registro diario más antiguos."""
    T = db.ahora()
    for d in range(10):
        for k in range(4):
            ts = T - d * D - k * 5 * 3600
            for ctx, v in (("reposo", 50 + d * 0.1), ("juego", 75)):
                con.execute("INSERT INTO lecturas (metrica_id, ts, categoria, nombre, valor, unidad, contexto) VALUES (0,?,?,?,?,?,?)",
                            (ts - (60 if ctx == "juego" else 0), "cpu", "k10temp/Tctl", v, "°C", ctx))
    for d in range(11, 70):
        dia = time.strftime("%Y-%m-%d", time.localtime(T - d * D))
        con.execute("INSERT INTO lecturas_diarias VALUES (?,?,?,?,?,?,?,?,?)", (dia, "k10temp/Tctl", "reposo", "cpu", "°C", 90, 45.0, 40, 60))
    con.execute("INSERT INTO metricas (id, workspace_id, ts, cpu_pct) VALUES (1,1,?,5)", (T - 60,))
    con.commit()


def test_un_sensor_en_el_rango_de_las_lecturas_crudas(datos):
    r = server.historial("k10temp/Tctl", "7d")
    assert r["fuente"] == "lecturas" and r["unidad"] == "°C"
    assert len(r["puntos"]) > 10


def test_completa_lo_antiguo_con_el_registro_diario(datos):
    r = server.historial("k10temp/Tctl", "60d")
    assert r["fuente"] == "lecturas + lecturas_diarias" and "nota" in r and r["min"] <= 45.0 and r["max"] == 75.0


def test_filtra_por_contexto(datos):
    r = server.historial("k10temp/Tctl", "60d", "juego")
    assert all(v == 75.0 for _, v in r["puntos"]) and len(r["puntos"]) == 40 and r["fuente"] == "lecturas"
    r = server.historial("k10temp/Tctl", "60d", "reposo")
    assert 45 <= r["promedio"] < 50 and r["fuente"].endswith("lecturas_diarias")


def test_un_sensor_inexistente_sugiere_nombres_parecidos(datos):
    assert server.historial("k10temp/Nada", "7d")["mensaje"] == "Sin datos de ese sensor en el rango."
    assert server.historial("k10temp/Tc", "7d")["parecidos"] == ["k10temp/Tctl"]


def test_las_metricas_de_siempre_siguen_funcionando(datos):
    assert server.historial("cpu_pct", "1h")["puntos"][0][1] == 5.0


@pytest.mark.parametrize("metrica,desde", [("foo", "1h"), ("cpu_pct", "ayer")])
def test_entradas_invalidas_dan_error(datos, metrica, desde):
    assert "error" in server.historial(metrica, desde)

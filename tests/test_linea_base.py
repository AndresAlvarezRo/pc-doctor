"""Aprendizaje de valores normales: migración de bases viejas, contexto (reposo, carga, juego), línea base por contexto,
anomalías, ventiladores, resolución de alertas aprendidas, deriva lenta y los límites compartidos con el dashboard.

Rescatadas de las comprobaciones de "Umbrales aprendidos y registro histórico" (BITACORA.md)."""

import datetime as dt
import random
import sqlite3

import pytest
from ayudas import L

import db
import linea_base
import salud


# ---------- migración ----------

def test_migracion_de_una_base_con_el_esquema_anterior(tmp_path, monkeypatch):
    ruta = tmp_path / "vieja.db"
    viejo = sqlite3.connect(ruta)
    viejo.execute("CREATE TABLE lecturas (metrica_id INTEGER NOT NULL, ts INTEGER NOT NULL, categoria TEXT NOT NULL, nombre TEXT NOT NULL, "
                  "valor REAL NOT NULL, unidad TEXT, limite_crit REAL)")
    viejo.execute("INSERT INTO lecturas VALUES (1, 1, 'cpu', 'x', 1.0, '°C', NULL)")
    viejo.commit()
    viejo.close()
    monkeypatch.setattr(db, "RUTA_DB", ruta)
    c = db.conectar()
    assert "contexto" in {r["name"] for r in c.execute("PRAGMA table_info(lecturas)")}  # columna agregada
    assert c.execute("SELECT COUNT(*) FROM lecturas").fetchone()[0] == 1               # fila vieja conservada
    c.close()


# ---------- contexto ----------

@pytest.mark.parametrize("cpu,gpu,juego,esperado", [
    (10, 5, False, "reposo"), (10, 90, False, "carga"), (60, 5, False, "carga"), (10, 5, True, "juego"), (90, 90, True, "juego"),
])
def test_contexto(cpu, gpu, juego, esperado):
    assert linea_base.contexto_de([L("cpu/uso", cpu, "cpu", "%"), L("amdgpu/uso", gpu, "gpu", "%")], juego) == esperado


def test_sin_dato_de_cpu_no_hay_contexto():
    assert linea_base.contexto_de([L("amdgpu/uso", 5, "gpu", "%")]) is None
    assert linea_base.contexto_de([L("amdgpu/uso", 5, "gpu", "%")], juego=True) is None


# ---------- historial sintético ----------

class Historial:
    """10 días de lecturas cada 15 min: reposo ~52 °C y carga ~72 °C (una de cada 4 muestras bajo carga)."""

    def __init__(self, con):
        self.con = con
        self.mid = 0
        random.seed(7)
        ahora = db.ahora()
        for dia in range(10, 0, -1):
            for i in range(96):
                self.mid += 1
                carga = i % 4 == 0
                ls = [L("amdgpu/junction", random.gauss(72 if carga else 52, 1.5), "gpu"), L("cpu/uso", 60 if carga else 8, "cpu", "%"),
                      L("amdgpu/fan1", random.gauss(900 if carga else 0, 20), "gpu", "RPM")]
                salud.guardar_lecturas(con, self.mid, ahora - dia * 86400 + i * 900, ls, linea_base.contexto_de(ls))
        con.commit()
        self.mantenimiento = linea_base.mantener(con)

    def inyectar(self, temp, cpu, nombre="amdgpu/junction", unidad="°C", cat="gpu"):
        """Guarda una lectura 'de ahora' y devuelve (lecturas, contexto)."""
        self.mid += 1
        ls = [L(nombre, temp, cat, unidad), L("cpu/uso", cpu, "cpu", "%")]
        ctx = linea_base.contexto_de(ls)
        salud.guardar_lecturas(self.con, self.mid, db.ahora(), ls, ctx)
        return ls, ctx


@pytest.fixture
def hist(con):
    return Historial(con)


def test_aprende_cada_contexto_por_separado(hist, con):
    assert hist.mantenimiento["dias_resumidos"] > 0 and hist.mantenimiento["base_recalculada"] > 0
    b = {(f["nombre"], f["contexto"]): f for f in con.execute("SELECT * FROM linea_base")}
    assert abs(b[("amdgpu/junction", "reposo")]["p50"] - 52) < 1
    assert abs(b[("amdgpu/junction", "carga")]["p50"] - 72) < 1
    assert b[("amdgpu/junction", "reposo")]["n"] >= linea_base.MIN_MUESTRAS  # base madura


def test_el_resumen_diario_es_idempotente_y_la_base_no_se_recalcula_antes_de_6_h(hist, con):
    antes = con.execute("SELECT COUNT(*) FROM lecturas_diarias").fetchone()[0]
    linea_base.rollup_diario(con)
    assert con.execute("SELECT COUNT(*) FROM lecturas_diarias").fetchone()[0] == antes
    assert linea_base.mantener(con)["base_recalculada"] == 0


def test_70_grados_es_normal_bajo_carga_pero_anomalo_en_reposo(hist, con):
    ls, ctx = hist.inyectar(70, 60)
    assert not linea_base.condiciones_anomalias(con, ls, ctx)                      # bajo carga: normal
    ls, ctx = hist.inyectar(70, 5)
    assert not linea_base.condiciones_anomalias(con, ls, ctx)                      # en reposo, la primera lectura no avisa
    ls, ctx = hist.inyectar(71, 5)
    c = linea_base.condiciones_anomalias(con, ls, ctx)
    assert list(c) == ["anomalia:amdgpu/junction:reposo"]                            # la segunda seguida sí
    assert c["anomalia:amdgpu/junction:reposo"]["severidad"] == "aviso"              # las aprendidas nunca son críticas


def test_variacion_pequena_y_valores_mas_frios_no_avisan(hist, con):
    ls, ctx = hist.inyectar(55, 5)
    assert not linea_base.condiciones_anomalias(con, ls, ctx)                      # +3 °C: variación pequeña
    hist.inyectar(30, 5)
    ls, ctx = hist.inyectar(30, 5)
    assert not linea_base.condiciones_anomalias(con, ls, ctx)                      # la temperatura solo se vigila hacia arriba


def test_ventilador_mucho_mas_lento_de_lo_habitual_es_anomalia(hist, con):
    hist.inyectar(300, 60, "amdgpu/fan1", "RPM")
    ls, ctx = hist.inyectar(300, 60, "amdgpu/fan1", "RPM")
    assert any("fan1" in k for k in linea_base.condiciones_anomalias(con, ls, ctx))   # los ventiladores se vigilan hacia ambos lados


def test_la_alerta_aprendida_se_resuelve_al_volver_a_lo_normal(hist, con):
    hist.inyectar(70, 5)
    ls, ctx = hist.inyectar(71, 5)
    vistos = {l["nombre"] for l in ls}
    salud.aplicar_condiciones(con, linea_base.condiciones_anomalias(con, ls, ctx), vistos, 100)
    ls, ctx = hist.inyectar(52, 5)
    r = salud.aplicar_condiciones(con, linea_base.condiciones_anomalias(con, ls, ctx), vistos, 1000)
    assert any(k.startswith("anomalia:") for k in r["resueltas"])


# ---------- deriva lenta ----------

def _diaria(con, nombre, contexto, cat, unidad, edades, media_de):
    hoy = dt.date.today()
    for edad in edades:
        m = media_de(edad)
        con.execute("INSERT INTO lecturas_diarias VALUES (?,?,?,?,?,?,?,?,?)",
                    ((hoy - dt.timedelta(days=edad)).isoformat(), nombre, contexto, cat, unidad, 96, m, m - 2, m + 2))
    con.commit()


def test_deriva_de_temperatura_en_reposo(con):
    _diaria(con, "amdgpu/junction", "reposo", "gpu", "°C", range(1, 46), lambda e: 52.0 if e > 7 else 60.0)
    _diaria(con, "memoria/ram_pct", "reposo", "memoria", "%", range(1, 46), lambda e: 38.0)
    d = linea_base.condiciones_deriva(con)
    assert list(d) == ["deriva:amdgpu/junction"]                                    # +8 °C y solo esa
    assert d["deriva:amdgpu/junction"]["repetir_s"] == 7 * 86400                    # como mucho una vez por semana


def test_deriva_no_adivina_con_poco_historial(con):
    _diaria(con, "amdgpu/junction", "reposo", "gpu", "°C", range(1, 21), lambda e: 52.0 if e > 7 else 60.0)
    assert not linea_base.condiciones_deriva(con)                                   # con ~3 semanas no hay datos suficientes


def test_deriva_exige_14_dias_de_referencia(con):
    _diaria(con, "amdgpu/junction", "reposo", "gpu", "°C", range(1, 22), lambda e: 52.0 if e > 7 else 60.0)  # 14 recientes+referencia justos
    _diaria(con, "amdgpu/edge", "reposo", "gpu", "°C", range(1, 21), lambda e: 52.0 if e > 7 else 60.0)      # 13 días de referencia
    d = linea_base.condiciones_deriva(con)
    assert "deriva:amdgpu/junction" in d and "deriva:amdgpu/edge" not in d


def test_deriva_de_espacio_libre(con):
    _diaria(con, "fs:/home/libre_pct", "reposo", "disco", "%", range(1, 46), lambda e: 80.0 if e > 7 else 68.0)
    assert "deriva:fs:/home/libre_pct" in linea_base.condiciones_deriva(con)


# ---------- límites compartidos entre la detección y el gráfico ----------

def _original(v, b, pf):
    """La detección tal como era antes de extraer `limites()`."""
    escala = max(1.4826 * b["mad"], pf["piso"])
    delta, z = v - b["p50"], (v - b["p50"]) / escala
    minimo = pf["delta"](b["p50"])
    alto = z >= linea_base.Z_ANOMALIA and delta >= minimo
    bajo = z <= -linea_base.Z_ANOMALIA and -delta >= minimo
    return (alto and pf["lados"] in ("alto", "ambos")) or (bajo and pf["lados"] in ("bajo", "ambos"))


@pytest.mark.parametrize("unidad,nombre", [("°C", "x"), ("RPM", "x"), ("W", "x"), ("mV", "x"), ("%", "m/ram_pct"), ("%", "d/libre_pct")])
def test_limites_dan_la_misma_deteccion_que_la_version_original(unidad, nombre):
    pf = linea_base.perfil(nombre, unidad)
    azar = random.Random(7)
    for _ in range(2000):
        b = {"p50": azar.uniform(0, 4000), "mad": azar.choice([0, 0.1, 1, 5, 50])}
        v = b["p50"] + azar.uniform(-400, 400) * azar.choice([0.01, 1, 10])
        assert _original(v, b, pf) == linea_base._anomalo(v, b, pf)
    b = {"p50": 50.0, "mad": 2.0}
    bajo, alto = linea_base.limites(b, pf)
    for limite, fuera, dentro in ((bajo, -1e-6, 1e-6), (alto, 1e-6, -1e-6)):
        if limite is not None:  # un poco fuera es anómalo y un poco dentro no (justo en el borde depende de la coma flotante)
            assert linea_base._anomalo(limite + fuera, b, pf) and not linea_base._anomalo(limite + dentro, b, pf)


def test_sensores_sin_perfil_no_se_aprenden():
    assert linea_base.perfil("sda/smart_ok", "bool") is None
    assert linea_base.perfil("cpu/uso", "%") is None


def test_estadisticas_robustas_resisten_un_valor_atipico():
    e = linea_base.estadisticas([50.0] * 99 + [500.0])
    assert e["p50"] == 50.0 and e["mad"] == 0.0 and e["maximo"] == 500.0

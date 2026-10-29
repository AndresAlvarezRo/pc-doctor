"""Autonomía, límites y flujos completos de la remediación (fase 5).

Punta a punta con `claude` falso y base temporal: alerta → diagnóstico → plan → aprobación → ejecución → verificación → receta; el plan
que no resuelve; la segunda alerta igual que usa la receta; el nivel 2 con y sin receta madura; el bucle; y cada límite."""

import json
import os
from pathlib import Path

import pytest

import alertas
import db
import diagnostico
import planes
import recetas
import remediacion
from test_diagnostico import alerta as alerta_diag, config, disparar, filas, modelo, plan_valido
from test_planes import AHORA, con, fake_log  # noqa: F401  (`con` es un fixture)

CLAVE = "temp_cpu:k10temp/Tctl"
CACHE = {"accion": "limpiar_cache_miniaturas", "parametros": {}, "porque": "x"}
PERFIL = {"accion": "cambiar_perfil_energia", "parametros": {"perfil": "performance"}, "porque": "baja la carga"}


@pytest.fixture(autouse=True)
def sin_programas_en_marcha(monkeypatch):
    monkeypatch.setattr(remediacion, "_en_uso", lambda nombres: None)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)


def con_cache():
    ruta = Path.home() / ".cache" / "thumbnails" / "a.png"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(b"x" * 4096)


def diagnosticar_nueva(con, monkeypatch, acciones, clave=CLAVE):
    """Dispara y corre un diagnóstico con el modelo falso (que propone `acciones`). Devuelve (diag_id, plan_id)."""
    alerta_diag(con, clave)
    d = disparar(con, lanzar=lambda i: True)["creados"][0]
    modelo(monkeypatch, plan_valido(acciones=list(acciones)))
    r = diagnostico.diagnosticar(d)
    return d, r["plan_id"]


def cambios_de_perfil():
    """Los `powerprofilesctl set`: simular solo consulta (`get`)."""
    return [x for x in fake_log("powerprofilesctl") if x["argv"][:1] != ["get"]]


def estado(con, p):
    return con.execute("SELECT * FROM planes WHERE id=?", (p,)).fetchone()


def resolver(con, clave=CLAVE):
    con.execute("UPDATE alertas_salud SET activa=0, resuelta_en=? WHERE clave=?", (db.ahora() + 1, clave)); con.commit()


def madura(con, acciones, firma=CLAVE, n=2):
    """Deja una receta con n éxitos (planes verificados de mentira, sin ejecutar nada)."""
    for _ in range(n):
        d = con.execute("INSERT INTO diagnosticos (ts, ref, disparador, firma, estado) VALUES (?,?,?,?,?)", (AHORA, f"alerta:{firma}:{_}", "critica_nueva", firma, "completo")).lastrowid
        p = con.execute("INSERT INTO planes (diagnostico_id, ts, acciones, estado) VALUES (?,?,?,?)", (d, AHORA, json.dumps(acciones), "verificado")).lastrowid
        con.commit()
        recetas.registrar_resultado(con, p, True)


@pytest.fixture(autouse=True)
def dia_amplio():
    config(max_diagnosticos_dia=50)


# ---------- flujo completo ----------

def test_alerta_diagnostico_plan_aprobacion_ejecucion_verificacion_y_receta(con, monkeypatch):
    d, p = diagnosticar_nueva(con, monkeypatch, [PERFIL])
    assert estado(con, p)["estado"] == "propuesto" and cambios_de_perfil() == []     # nivel 1: propone, no ejecuta
    assert estado(con, p)["origen"] is None
    r = planes.aprobar(p, "dashboard")
    assert r["ok"] and estado(con, p)["estado"] == "aplicado" and cambios_de_perfil()
    for _ in range(2):
        assert planes.verificar_pendientes(con)["esperando"] == [p]       # la alerta sigue
    resolver(con)
    assert planes.verificar_pendientes(con)["verificados"] == [p]
    r, = recetas.lista(con)
    assert r["firma"] == CLAVE and r["funciono"] == 1 and r["acciones"][0]["accion"] == "cambiar_perfil_energia"
    assert con.execute("SELECT estado FROM changelog").fetchone()["estado"] == "resuelto"


def test_el_plan_que_no_resuelve_escala_y_no_crea_receta(con, monkeypatch):
    d, p = diagnosticar_nueva(con, monkeypatch, [PERFIL])
    planes.aprobar(p, "dashboard")
    for _ in range(4):
        planes.verificar_pendientes(con)
    f = estado(con, p)
    assert f["estado"] == "fallido" and f["escalado_en"] and recetas.lista(con) == []
    assert con.execute("SELECT tipo, estado FROM changelog WHERE tipo='error'").fetchone()["estado"] == "abierto"
    assert any("no resolvió" in json.dumps(x, ensure_ascii=False) for x in fake_log("notify-send"))


def test_la_segunda_alerta_igual_usa_la_receta(con, monkeypatch, tmp_path):
    d, p = diagnosticar_nueva(con, monkeypatch, [PERFIL])
    planes.aprobar(p, "dashboard"); resolver(con); planes.verificar_pendientes(con)
    con.execute("UPDATE alertas_salud SET activa=1, resuelta_en=NULL, desde=?", (AHORA + 5,)); con.commit()    # vuelve la misma alerta
    nuevo = disparar(con, lanzar=lambda i: True)["creados"][0]
    registro = tmp_path / "c.json"
    monkeypatch.setenv("FAKE_CLAUDE_REGISTRO", str(registro)); modelo(monkeypatch, plan_valido())
    diagnostico.diagnosticar(nuevo)
    bloque = json.loads(registro.read_text())["stdin"].split("RECETAS PREVIAS")[1].split("CATÁLOGO DE ACCIONES")[0]
    assert "cambiar_perfil_energia" in bloque and '"veces_funciono": 1' in bloque


# ---------- niveles ----------

def nivel(n, preaprobadas=("limpiar_cache_miniaturas",), **mas):
    config(nivel=n, preaprobadas=list(preaprobadas), max_diagnosticos_dia=50, **mas)


def test_nivel_2_con_receta_madura_aplica_solo_y_avisa_despues(con, monkeypatch):
    nivel(2); con_cache(); madura(con, [CACHE])
    d, p = diagnosticar_nueva(con, monkeypatch, [CACHE])
    f = estado(con, p)
    assert f["estado"] == "aplicado" and f["origen"] == "automatico" and not (Path.home() / ".cache/thumbnails/a.png").exists()
    avisos = json.dumps(fake_log("notify-send"), ensure_ascii=False)
    assert "apliqué un plan solo" in avisos and "para revisar" not in avisos
    resolver(con); assert planes.verificar_pendientes(con)["verificados"] == [p]
    assert recetas.lista(con)[0]["funciono"] == 3


def test_nivel_2_sin_receta_madura_deja_el_plan_propuesto(con, monkeypatch):
    nivel(2); con_cache()
    d, p = diagnosticar_nueva(con, monkeypatch, [CACHE])
    assert estado(con, p)["estado"] == "propuesto" and (Path.home() / ".cache/thumbnails/a.png").exists()
    assert "para revisar" in json.dumps(fake_log("notify-send"), ensure_ascii=False)
    madura(con, [CACHE], n=1)                                                       # un solo éxito no alcanza
    assert planes.autoaplicar(con, p)["aplicado"] is False


@pytest.mark.parametrize("cfg,motivo", [
    ({"nivel": 1, "preaprobadas": ["limpiar_cache_miniaturas"]}, "nivel"),
    ({"nivel": 2, "preaprobadas": []}, "preaprobada"),
    ({"nivel": 2, "preaprobadas": ["limpiar_cache_uv"]}, "preaprobada"),
])
def test_solo_se_aplica_sola_una_accion_que_el_usuario_preaprobo_y_en_nivel_2(con, monkeypatch, cfg, motivo):
    madura(con, [CACHE]); con_cache()
    d, p = diagnosticar_nueva(con, monkeypatch, [CACHE])
    config(max_diagnosticos_dia=50, **cfg)
    r = planes.autoaplicar(con, p)
    assert r["aplicado"] is False and motivo in r["motivo"] and estado(con, p)["estado"] == "propuesto"


def test_una_accion_no_preaprobable_no_se_aplica_sola_ni_figurando_en_la_lista(con, monkeypatch):
    nivel(2, preaprobadas=("cambiar_perfil_energia", "cerrar_proceso", "inventada"))
    assert diagnostico.configuracion()["preaprobadas"] == []                          # el catálogo manda, no la lista
    madura(con, [PERFIL])
    d, p = diagnosticar_nueva(con, monkeypatch, [PERFIL])
    assert estado(con, p)["estado"] == "propuesto" and cambios_de_perfil() == []


def test_el_modelo_no_puede_cambiar_la_configuracion(con, monkeypatch):
    nivel(1)
    modelo(monkeypatch, plan_valido(nivel=2, preaprobadas=["limpiar_cache_miniaturas"], acciones=[CACHE]))
    alerta_diag(con); d = disparar(con, lanzar=lambda i: True)["creados"][0]
    diagnostico.diagnosticar(d)
    c = diagnostico.configuracion()
    assert c["nivel"] == 1 and c["preaprobadas"] == ["limpiar_cache_miniaturas"] and json.loads((db.DIR_DATOS / "config.json").read_text())["remediacion"]["nivel"] == 1
    assert any("claves desconocidas" in x for x in json.loads(con.execute("SELECT descartes FROM planes").fetchone()["descartes"]))


def test_nivel_0_solo_diagnostica(con, monkeypatch):
    config(nivel=0, max_diagnosticos_dia=50)
    d, p = diagnosticar_nueva(con, monkeypatch, [PERFIL])
    r = planes.aprobar(p, "dashboard")
    assert r["ok"] is False and "nivel de autonomía es 0" in r["error"] and estado(con, p)["estado"] == "propuesto" and cambios_de_perfil() == []


# ---------- configuración por defecto y validación ----------

def test_configuracion_por_defecto_es_la_prudente():
    (db.DIR_DATOS / "config.json").unlink()      # el autouse deja uno con el tope de diagnósticos ampliado
    c = diagnostico.configuracion()
    assert (c["nivel"], c["preaprobadas"], c["max_diagnosticos_dia"], c["max_intentos_por_firma"], c["espera_entre_intentos_min"], c["usar_modelo"]) == \
        (1, [], 3, 2, 60, True)
    assert not (db.DIR_DATOS / "config.json").exists(), "leer la configuración no escribe nada"


@pytest.mark.parametrize("malo", [3, -1, "2", True, 1.0, None])
def test_nivel_invalido_vuelve_al_1(malo):
    config(nivel=malo)
    assert diagnostico.configuracion()["nivel"] == 1


def test_valores_invalidos_de_limites_vuelven_al_defecto():
    config(max_intentos_por_firma=0, espera_entre_intentos_min=-5, max_diagnosticos_dia="mucho", preaprobadas="todas")
    c = diagnostico.configuracion()
    assert (c["max_intentos_por_firma"], c["espera_entre_intentos_min"], c["max_diagnosticos_dia"], c["preaprobadas"]) == (2, 60, 3, [])
    config(espera_entre_intentos_min=0)
    assert diagnostico.configuracion()["espera_entre_intentos_min"] == 0


# ---------- límites ----------

def test_maximo_de_intentos_por_firma_y_espera_entre_intentos(con, monkeypatch):
    nivel(2, max_intentos_por_firma=2, espera_entre_intentos_min=60); con_cache(); madura(con, [CACHE])
    d, p1 = diagnosticar_nueva(con, monkeypatch, [CACHE])
    assert estado(con, p1)["estado"] == "aplicado"
    con.execute("UPDATE alertas_salud SET desde=desde+1"); con.commit()
    _, p2 = _otro(con, monkeypatch)
    r = planes.autoaplicar(con, p2)
    assert not r["aplicado"] and "esperar 60 min" in r["motivo"]
    con.execute("UPDATE planes SET aplicado_en=aplicado_en-4000"); con.commit()      # pasó la espera
    config(nivel=2, preaprobadas=["limpiar_cache_miniaturas"], max_diagnosticos_dia=50, max_intentos_por_firma=2, espera_entre_intentos_min=60)
    con_cache()
    assert planes.autoaplicar(con, p2)["aplicado"] is True
    _, p3 = _otro(con, monkeypatch)
    con.execute("UPDATE planes SET aplicado_en=aplicado_en-4000"); con.commit()
    r = planes.autoaplicar(con, p3)
    assert not r["aplicado"] and "máximo 2" in r["motivo"]


def _otro(con, monkeypatch):
    """Otro diagnóstico de la misma firma (la alerta se resuelve y vuelve)."""
    con.execute("UPDATE alertas_salud SET activa=0, resuelta_en=? WHERE clave=?", (db.ahora(), CLAVE))
    con.execute("UPDATE diagnosticos SET ref=ref||'x'"); con.execute("UPDATE alertas_salud SET activa=1, resuelta_en=NULL, desde=?", (db.ahora() + 10,)); con.commit()
    d = disparar(con, lanzar=lambda i: True)["creados"][0]
    modelo(monkeypatch, plan_valido(acciones=[CACHE]))
    return d, diagnostico.diagnosticar(d)["plan_id"]


def test_tope_de_diagnosticos_por_dia(con):
    config(max_diagnosticos_dia=2)
    for i in range(4):
        alerta_diag(con, f"temp_cpu:s{i}")
    r = disparar(con, lanzar=lambda i: True)
    assert len(r["creados"]) == 2 and len(filas(con, "diagnosticos")) == 2


def test_sin_modelo_el_diagnostico_es_solo_correlacion_y_no_llama_a_claude(con, monkeypatch, tmp_path):
    config(usar_modelo=False, max_diagnosticos_dia=50)
    registro = tmp_path / "c.json"; monkeypatch.setenv("FAKE_CLAUDE_REGISTRO", str(registro))
    alerta_diag(con); d = disparar(con, lanzar=lambda i: True)["creados"][0]
    assert diagnostico.diagnosticar(d)["modo"] == "sin_redactar" and not registro.exists()
    assert nivel_plan_sin_acciones(con)


def nivel_plan_sin_acciones(con):
    return json.loads(con.execute("SELECT acciones FROM planes").fetchone()["acciones"]) == []


def test_limites_del_modelo_llegan_al_comando(con, monkeypatch, tmp_path):
    config(modelo="opus", max_turns=7, timeout_s=90, max_diagnosticos_dia=50)
    registro = tmp_path / "c.json"; monkeypatch.setenv("FAKE_CLAUDE_REGISTRO", str(registro)); modelo(monkeypatch, plan_valido())
    alerta_diag(con); diagnostico.diagnosticar(disparar(con, lanzar=lambda i: True)["creados"][0])
    a = json.loads(registro.read_text())["argv"]
    assert a[a.index("--model") + 1] == "opus" and a[a.index("--max-turns") + 1] == "7"


# ---------- bucle ----------

def test_una_alerta_nueva_tras_aplicar_corta_lo_automatico_y_escala(con, monkeypatch):
    nivel(2); con_cache(); madura(con, [CACHE])
    d, p = diagnosticar_nueva(con, monkeypatch, [CACHE])
    assert estado(con, p)["estado"] == "aplicado"
    alerta_diag(con, "disco_lleno:/", sev="critico", cat="disco", desde=db.ahora() + 5)          # la acción trajo otra alerta
    r = planes.verificar_pendientes(con)
    assert r["cortados"] == [p] and estado(con, p)["estado"] == "escalado" and estado(con, p)["escalado_en"]
    assert "disco_lleno" in estado(con, p)["resultado"]
    assert planes.corte_vigente(con, CLAVE) and recetas.lista(con)[0]["fallo"] == 1
    assert any("no resolvió" in json.dumps(x, ensure_ascii=False) for x in fake_log("notify-send"))
    # lo automático de esa alerta quedó cortado, aunque haya receta madura y límites libres
    con_cache(); madura(con, [CACHE], n=3)
    con.execute("UPDATE planes SET aplicado_en=aplicado_en-90000"); con.commit()
    _, p2 = _otro(con, monkeypatch)
    r = planes.autoaplicar(con, p2)
    assert not r["aplicado"] and "corte por bucle" in r["motivo"] and estado(con, p2)["estado"] == "propuesto"
    assert planes.aprobar(p2, "dashboard")["ok"]                                                 # a mano sigue pudiendo


def test_el_corte_vence(con, monkeypatch):
    nivel(2); con_cache(); madura(con, [CACHE])
    d, p = diagnosticar_nueva(con, monkeypatch, [CACHE])
    alerta_diag(con, "otra:cosa", desde=db.ahora() + 5)
    planes.verificar_pendientes(con)
    con.execute("UPDATE cortes_auto SET ts=ts-?", ((planes.CORTE_DIAS + 1) * 86400,)); con.commit()
    assert planes.corte_vigente(con, CLAVE) is None


def test_una_alerta_anterior_a_aplicar_no_es_un_bucle(con, monkeypatch):
    alerta_diag(con, "vieja:cosa", desde=AHORA - 5000)
    d, p = diagnosticar_nueva(con, monkeypatch, [PERFIL])
    planes.aprobar(p, "dashboard")
    assert planes.verificar_pendientes(con)["cortados"] == [] and estado(con, p)["estado"] == "aplicado"


# ---------- reporte semanal ----------

def test_el_reporte_semanal_lee_diagnosticos_y_planes_pero_el_diagnostico_no():
    import inspect, reporte, server
    assert {"diagnosticos", "planes"} <= set(reporte.HERRAMIENTAS_REPORTE) and not {"diagnosticos", "planes"} & set(reporte.PROHIBIDAS_REPORTE)
    assert not {"diagnosticos", "planes", "detalle_plan", "recetas"} & set(reporte.HERRAMIENTAS_LECTURA)       # el diagnóstico no las recibe
    assert {"detalle_plan", "recetas", "aprobar_plan", "rechazar_plan"} <= set(reporte.PROHIBIDAS_REPORTE)
    assert set(reporte.HERRAMIENTAS_REPORTE) & set(reporte.PROHIBIDAS_REPORTE) == set()
    for f in (server.diagnosticos, server.planes_tool):
        fuente = inspect.getsource(f)
        assert not any(e in fuente for e in ("INSERT", "UPDATE ", "DELETE", ".commit()", "escribir=True", "aprobar("))
    a = reporte.construir_comando("claude", reporte.configuracion(False))
    assert "mcp__pc-doctor__diagnosticos" in a[a.index("--allowedTools") + 1] and "detalle_plan" in a[a.index("--disallowedTools") + 1]

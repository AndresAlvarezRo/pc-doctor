"""Planes de remediación (fase 3): aprobar, rechazar, deshacer, verificar, escalar, avisos, tools del MCP y los endpoints que escriben.

Todo en la base temporal, con `systemctl`, `powerprofilesctl` y `notify-send` falsos (tests/falsos/)."""

import json
import os
import stat
import time
from pathlib import Path

import pytest

import alertas
import dashboard
import db
import memoria
import planes
import remediacion
import reporte
import server
from conftest import PUERTO_PRUEBAS

AHORA = int(time.time())
HOST = f"127.0.0.1:{PUERTO_PRUEBAS}"
ORIGEN = f"http://127.0.0.1:{PUERTO_PRUEBAS}"
PERFIL = {"accion": "cambiar_perfil_energia", "parametros": {"perfil": "performance"}, "porque": "x", "simulacion": "pasaría de balanced a performance"}


def fake_log(cmd):
    return [r for r in map(json.loads, Path(os.environ["FAKE_LOG"]).read_text().splitlines()) if r.get("cmd") == cmd]


def config(**cambios):
    (db.DIR_DATOS / "config.json").write_text(json.dumps({"remediacion": cambios}))


@pytest.fixture
def con():
    c = db.conectar(escribir=True)
    yield c
    c.close()


def hacer_plan(con, acciones=(PERFIL,), estado="propuesto", clave="temp_cpu:k10temp/Tctl", ref=None, hipotesis="La CPU se calienta", modo="modelo",
               changelog=True, **extra):
    cl = memoria.registrar_changelog(con, "observacion", "cpu", "Diagnóstico automático #1", "abierto", "Diagnóstico #1")["id"] if changelog else None
    d = con.execute("INSERT INTO diagnosticos (ts, ref, disparador, alerta_clave, componente, firma, modo, hipotesis, evidencia, confianza, sospechoso, estado, changelog_id) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (AHORA, ref or f"alerta:{clave}:{AHORA - 600}", "critica_nueva", clave, "cpu", clave, modo, hipotesis,
                     json.dumps([{"referencia": "historial", "dato": "95 °C"}]), "media", "[]", "completo", cl)).lastrowid
    p = con.execute("INSERT INTO planes (diagnostico_id, ts, acciones, pasos_manuales, verificar, estado, redactado) VALUES (?,?,?,?,?,?,?)",
                    (d, AHORA, json.dumps(list(acciones)), json.dumps(["Limpiar el polvo"]), "que baje la temperatura", estado, int(modo == "modelo"))).lastrowid
    for k, v in extra.items():
        con.execute(f"UPDATE planes SET {k}=? WHERE id=?", (v, p))
    con.commit()
    return p


def alerta(con, clave="temp_cpu:k10temp/Tctl", activa=1, resuelta_en=None):
    con.execute("INSERT INTO alertas_salud (clave, categoria, nombre, severidad, mensaje, valor, desde, ultima_vez, activa, resuelta_en) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (clave, "cpu", "Tctl", "critico", "CPU caliente", 95, AHORA - 600, AHORA, activa, resuelta_en))
    con.commit()


def fila(con, tabla, ident):
    return dict(con.execute(f"SELECT * FROM {tabla} WHERE id=?", (ident,)).fetchone())


# ---------- lectura ----------

def test_la_lista_va_sin_texto_del_modelo_y_el_detalle_lo_trae(con):
    p = hacer_plan(con, hipotesis="TEXTO_LIBRE_DEL_MODELO")
    l, = planes.lista(con)
    assert l["id"] == p and l["acciones"] == ["cambiar_perfil_energia"] and "TEXTO_LIBRE" not in json.dumps(l) and "hipotesis" not in l
    d = planes.detalle(con, p)
    assert d["hipotesis"] == "TEXTO_LIBRE_DEL_MODELO" and d["acciones"][0]["simulacion"] and d["pasos_manuales"] == ["Limpiar el polvo"] and d["evidencia"]
    assert planes.detalle(con, 999) is None
    assert planes.lista(con, "aplicado") == [] and planes.lista(con, "propuesto")
    with pytest.raises(ValueError):
        planes.lista(con, "inventado")


def test_las_tools_de_lectura_no_traen_el_texto_libre_salvo_detalle_plan(con):
    p = hacer_plan(con, hipotesis="TEXTO_LIBRE_DEL_MODELO")
    assert "TEXTO_LIBRE" not in json.dumps(server.diagnosticos(7)) and "TEXTO_LIBRE" not in json.dumps(server.planes_tool("propuesto"))
    assert server.diagnosticos(7)["diagnosticos"][0]["estado_del_plan"] == "propuesto"
    assert "TEXTO_LIBRE" in json.dumps(server.detalle_plan(p)) and "NO confiable" in server.detalle_plan.__doc__
    assert "error" in server.planes_tool("raro") and "error" in server.detalle_plan(999)


# ---------- aprobar ----------

def test_aprobar_aplica_las_acciones_y_queda_aplicado(con):
    p = hacer_plan(con)
    r = planes.aprobar(p, "dashboard")
    assert r["ok"] and r["estado"] == "aplicado" and r["acciones"] == [{"accion": "cambiar_perfil_energia", "ok": True, "resumen": "perfil de energía: balanced → performance"}]
    f = fila(con, "planes", p)
    assert f["estado"] == "aplicado" and f["origen"] == "dashboard" and f["aprobado_en"] and f["aplicado_en"] and f["corridas"] == 0
    ids = json.loads(f["ejecuciones"])
    assert len(ids) == 1 and fila(con, "ejecuciones", ids[0])["plan_id"] == p and ["set", "performance"] in [x["argv"] for x in fake_log("powerprofilesctl")]


def test_un_plan_no_se_aprueba_dos_veces_ni_en_otro_estado(con):
    p = hacer_plan(con)
    assert planes.aprobar(p, "dashboard")["ok"]
    r = planes.aprobar(p, "claude")
    assert r["ok"] is False and "«aplicado»" in r["error"]
    assert sum(1 for x in fake_log("powerprofilesctl") if x["argv"][:1] == ["set"]) == 1
    assert planes.aprobar(999, "claude")["ok"] is False
    assert planes.aprobar(hacer_plan(con, estado="rechazado"), "claude")["ok"] is False


def test_un_plan_sin_acciones_no_se_aprueba(con):
    r = planes.aprobar(hacer_plan(con, acciones=[]), "dashboard")
    assert r["ok"] is False and "solo diagnóstico" in r["error"]


def test_aprobar_vuelve_a_validar_y_una_accion_manipulada_en_la_base_no_corre(con):
    mala = {"accion": "cerrar_proceso", "parametros": {"pid": 1, "nombre_esperado": "systemd"}, "porque": "x", "simulacion": "x"}
    p = hacer_plan(con, acciones=[PERFIL, mala, PERFIL])
    # el plan empieza bien y la segunda acción es inválida: se detiene ahí, queda fallido y se escala
    r = planes.aprobar(p, "dashboard")
    assert r["ok"] is False and r["estado"] == "fallido" and [a["ok"] for a in r["acciones"]] == [True, False]
    f = fila(con, "planes", p)
    assert f["estado"] == "fallido" and f["escalado_en"] and "cerrar_proceso" in f["resultado"]
    assert sum(1 for x in fake_log("powerprofilesctl") if x["argv"][:1] == ["set"]) == 1       # la tercera no corrió
    assert [fila(con, "ejecuciones", i)["estado"] for i in json.loads(f["ejecuciones"])] == ["aplicada", "rechazada"]
    assert any("no resolvió" in json.dumps(x, ensure_ascii=False) for x in fake_log("notify-send"))
    c, = [x for x in con.execute("SELECT * FROM changelog WHERE tipo='error'")]
    assert c["estado"] == "abierto" and "cambiar_perfil_energia(perfil=performance): ok" in c["detalle"] and "cerrar_proceso" in c["detalle"]


def test_dos_aprobaciones_a_la_vez_aplican_una_sola_vez(con):
    from concurrent.futures import ThreadPoolExecutor
    p = hacer_plan(con)
    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(lambda _: planes.aprobar(p, "dashboard")["ok"], range(4)))
    assert res.count(True) == 1 and sum(1 for x in fake_log("powerprofilesctl") if x["argv"][:1] == ["set"]) == 1


# ---------- rechazar y deshacer ----------

def test_rechazar_no_ejecuta_nada(con):
    p = hacer_plan(con)
    r = planes.rechazar(p, "claude")
    assert r["ok"] and fila(con, "planes", p)["estado"] == "rechazado" and fila(con, "planes", p)["origen"] == "claude"
    assert fake_log("powerprofilesctl") == [] and con.execute("SELECT COUNT(*) FROM ejecuciones").fetchone()[0] == 0
    assert planes.rechazar(p, "claude")["ok"] is False and planes.rechazar(999, "claude")["ok"] is False


def test_deshacer_revierte_lo_reversible(con):
    p = hacer_plan(con)
    planes.aprobar(p, "dashboard")
    r = planes.deshacer(p, "dashboard")
    assert r["ok"] and r["estado"] == "rechazado" and r["deshecho"] and ["set", "balanced"] in [x["argv"] for x in fake_log("powerprofilesctl")]
    assert fila(con, "planes", p)["resultado"] == "deshecho por el usuario" and planes.deshacer(p, "dashboard")["ok"] is False   # ya no hay nada aplicado


def test_deshacer_un_plan_no_aplicado_se_rechaza(con):
    assert planes.deshacer(hacer_plan(con), "dashboard")["ok"] is False and planes.deshacer(999, "dashboard")["ok"] is False


def test_deshacer_informa_lo_irreversible(con):
    config(servicios_permitidos=["mi-servicio"])
    p = hacer_plan(con, acciones=[{"accion": "reiniciar_servicio_usuario", "parametros": {"nombre": "mi-servicio"}, "porque": "x", "simulacion": "x"}])
    planes.aprobar(p, "dashboard")
    r = planes.deshacer(p, "dashboard")
    assert r["pendiente"] == ["«reiniciar_servicio_usuario» no se puede deshacer"] and r["deshecho"] == []


# ---------- verificación ----------

def aplicado(con, **kw):
    p = hacer_plan(con, **kw)
    planes.aprobar(p, "dashboard")
    con.execute("UPDATE planes SET aplicado_en=? WHERE id=?", (AHORA - 100, p)); con.commit()
    return p


def test_verificado_si_la_alerta_se_resolvio_y_el_efecto_se_cumplio_y_cierra_el_changelog(con):
    p = aplicado(con)
    alerta(con, activa=0, resuelta_en=AHORA)
    r = planes.verificar_pendientes(con)
    assert r["verificados"] == [p]
    f = fila(con, "planes", p)
    assert f["estado"] == "verificado" and f["verificado_en"] and f["corridas"] == 1
    cl, = con.execute("SELECT * FROM changelog").fetchall()
    assert cl["estado"] == "resuelto" and f"Plan #{p} verificado" in cl["detalle"]
    assert planes.verificar_pendientes(con) == {"verificados": [], "fallidos": [], "esperando": []}    # ya no se mira


def test_espera_las_corridas_configuradas_y_despues_falla_y_escala(con):
    p = aplicado(con)
    alerta(con, activa=1)
    for i in range(3):
        assert planes.verificar_pendientes(con)["esperando"] == [p], i
    r = planes.verificar_pendientes(con)                                              # 4.ª corrida: se acabó la espera (por defecto 4)
    assert r["fallidos"] == [p]
    f = fila(con, "planes", p)
    assert f["estado"] == "fallido" and "sigue activa" in f["resultado"] and f["escalado_en"]
    cl = [x for x in con.execute("SELECT * FROM changelog ORDER BY id")]
    assert [c["estado"] for c in cl] == ["abierto", "abierto"] and cl[1]["tipo"] == "error" and "no resolvió" in cl[1]["detalle"]   # la observación sigue abierta
    assert any("no resolvió" in json.dumps(x, ensure_ascii=False) for x in fake_log("notify-send"))
    planes.verificar_pendientes(con)
    assert con.execute("SELECT COUNT(*) FROM changelog").fetchone()[0] == 2           # el escalado no se repite


def test_las_corridas_de_verificacion_son_configurables(con):
    config(verificar_corridas=2)
    p = aplicado(con); alerta(con, activa=1)
    assert planes.verificar_pendientes(con)["esperando"] == [p] and planes.verificar_pendientes(con)["fallidos"] == [p]


def test_alerta_resuelta_pero_efecto_sin_cumplir_no_es_verificado(con, monkeypatch):
    config(verificar_corridas=2)
    p = aplicado(con); alerta(con, activa=0, resuelta_en=AHORA)
    monkeypatch.setenv("FAKE_PERFIL", "power-saver")                                   # el fake lee el último `set` del registro: se lo borramos
    Path(os.environ["FAKE_LOG"]).write_text("")
    assert planes.verificar_pendientes(con)["esperando"] == [p]
    r = planes.verificar_pendientes(con)
    assert r["fallidos"] == [p] and "perfil" in fila(con, "planes", p)["resultado"]


def test_una_alerta_que_se_resolvio_antes_de_aplicar_no_cuenta(con):
    p = aplicado(con); alerta(con, activa=0, resuelta_en=AHORA - 500)
    assert planes.verificar_pendientes(con)["verificados"] == []                       # se resolvió sola antes: no es mérito del plan


def test_hallazgo_visto_otra_vez_despues_de_aplicar_no_se_resolvio(con):
    con.execute("INSERT INTO hallazgos_seguridad (huella, categoria, regla, severidad, nombre, detalle, primera_vez, ultima_vez) VALUES ('h1','minero','r','alta','x','d',?,?)", (AHORA - 900, AHORA))
    p = aplicado(con, clave="hallazgo:minero:r", ref="hallazgo:h1")
    assert planes.verificar_pendientes(con)["esperando"] == [p]
    con.execute("UPDATE hallazgos_seguridad SET ultima_vez=?", (AHORA - 500,)); con.commit()
    assert planes.verificar_pendientes(con)["verificados"] == [p]


# ---------- avisos ----------

def test_el_aviso_del_plan_tiene_hipotesis_resumida_y_boton_ver_el_plan_sin_aplicar(con, monkeypatch):
    vistos = []
    monkeypatch.setattr(alertas, "notificar", lambda *a, **k: vistos.append((a, k)) or True)
    p = hacer_plan(con, hipotesis="Hipótesis \x1b[31mlarga\x1b[0m " + "x" * 300)
    assert planes.avisar_plan(con, p)
    (titulo, mensaje), k = vistos[0][0][:2], vistos[0][1]
    assert k.get("seccion") == f"plan:{p}" or vistos[0][0][3] == f"plan:{p}"
    assert "Hipótesis (sin verificar)" in mensaje and "\x1b" not in mensaje and len(mensaje) < 400 and "Aplicar" not in mensaje and "aprobación" in mensaje
    sin_modelo = hacer_plan(con, modo="sin_redactar", hipotesis="Sin redactar: x")
    planes.avisar_plan(con, sin_modelo)
    assert "sin modelo" in vistos[1][0][1] and "Hipótesis" not in vistos[1][0][1]


def test_el_boton_del_plan_dice_ver_el_plan_y_abre_la_pagina_del_plan():
    assert dashboard.texto_boton("plan:3") == "Ver el plan" and dashboard.texto_boton("alerta:3") == "Ver en el dashboard" and dashboard.texto_boton(None) == "Ver en el dashboard"
    assert dashboard.url_de("plan:3") == f"{dashboard.BASE}/plan/3"
    assert "--action=ver=Ver el plan" in alertas._comando("t", "m", False, con_boton=True, seccion="plan:3")
    assert "--action=ver=Ver en el dashboard" in alertas._comando("t", "m", False, con_boton=True, seccion="alerta:3")
    with pytest.raises(ValueError):
        dashboard.url_de("plan:3;rm")


def test_sin_notificaciones_no_se_avisa(con, monkeypatch):
    (db.DIR_DATOS / "config.json").write_text(json.dumps({"notificaciones": False}))
    monkeypatch.setattr(alertas, "notificar", lambda *a, **k: pytest.fail("no debería avisar"))
    assert planes.avisar_plan(con, hacer_plan(con)) is False


# ---------- tools del MCP ----------

def test_aprobar_y_rechazar_plan_del_mcp_exigen_pedido_explicito_y_no_estan_al_alcance_del_modelo(con):
    for t in (server.aprobar_plan, server.rechazar_plan):
        assert "de forma explícita" in t.__doc__
    p = hacer_plan(con)
    assert server.rechazar_plan(p)["ok"] and fila(con, "planes", p)["origen"] == "claude"
    p2 = hacer_plan(con)
    assert server.aprobar_plan(p2)["estado"] == "aplicado"
    for nombre in ("aprobar_plan", "rechazar_plan", "diagnosticos", "planes", "detalle_plan"):
        assert nombre in reporte.HERRAMIENTAS_PROHIBIDAS and nombre not in reporte.HERRAMIENTAS_LECTURA
    reales = {t.name for t in server.mcp._tool_manager.list_tools()}
    assert {"diagnosticos", "planes", "detalle_plan", "aprobar_plan", "rechazar_plan"} <= reales


def test_nada_fuera_de_los_puntos_de_entrada_llama_a_aprobar():
    import re
    from pathlib import Path as P
    raiz = P(planes.__file__).parent
    usos = {f.name for f in list(raiz.glob("*.py")) + list((raiz / "web").glob("*.py")) if re.search(r"planes\.aprobar\(", f.read_text())}
    assert usos == {"server.py", "api.py"}, "solo el MCP (a pedido del usuario) y el dashboard (con token) aprueban planes"


# ---------- dashboard: los primeros endpoints que escriben ----------

pytestmark_api = pytest.mark.lento


@pytest.fixture
def api(cliente_api):
    con = db.conectar(escribir=True)
    p = hacer_plan(con)
    con.close()
    cliente_api.plan = p
    cliente_api.token = cliente_api.get("/api/token", headers={"Host": HOST}).json()["token"]
    return cliente_api


def post(api, ruta, token="si", origen=ORIGEN, host=HOST, tipo="application/json", extra=None):
    h = {"Host": host, "Content-Type": tipo}
    if token:
        h["X-PC-Doctor-Token"] = api.token if token == "si" else token
    if origen:
        h["Origin"] = origen
    h.update(extra or {})
    return api.post(ruta, headers=h, content=b"{}")


def estado_plan(api):
    con = db.conectar()
    try:
        return con.execute("SELECT estado FROM planes WHERE id=?", (api.plan,)).fetchone()["estado"]
    finally:
        con.close()


@pytest.mark.lento
def test_el_token_se_guarda_con_permisos_600_y_es_estable(api):
    ruta = db.DIR_DATOS / "web_token"
    assert stat.S_IMODE(ruta.stat().st_mode) == 0o600 and len(ruta.read_text().strip()) >= 32 and ruta.read_text().strip() == api.token
    assert api.get("/api/token", headers={"Host": HOST}).json()["token"] == api.token


@pytest.mark.lento
@pytest.mark.parametrize("caso,kw,codigo", [
    ("sin token", {"token": None}, 403), ("token inválido", {"token": "x" * 43}, 403), ("token vacío", {"token": ""}, 403),
    ("Origin ajeno", {"origen": "http://evil.com"}, 403), ("Origin con otro puerto", {"origen": "http://127.0.0.1:9999"}, 403),
    ("sin Origin", {"origen": None}, 403), ("Origin null", {"origen": "null"}, 403),
    ("Host ajeno", {"host": "evil.com"}, 421), ("Host con otro puerto", {"host": "127.0.0.1:9999"}, 421),
    ("entre sitios", {"extra": {"Sec-Fetch-Site": "cross-site"}}, 403), ("mismo sitio pero otro origen", {"extra": {"Sec-Fetch-Site": "same-site"}}, 403),
    ("formulario HTML", {"tipo": "application/x-www-form-urlencoded"}, 415), ("texto plano", {"tipo": "text/plain"}, 415)])
def test_un_post_que_no_cumple_todo_no_llega_a_escribir(api, caso, kw, codigo):
    for accion in ("aprobar", "rechazar", "deshacer"):
        assert post(api, f"/api/planes/{api.plan}/{accion}", **kw).status_code == codigo, caso
    assert estado_plan(api) == "propuesto" and fake_log("powerprofilesctl") == []


@pytest.mark.lento
@pytest.mark.parametrize("metodo", ["GET", "PUT", "DELETE", "PATCH"])
def test_las_rutas_que_escriben_solo_aceptan_post(api, metodo):
    r = api.request(metodo, f"/api/planes/{api.plan}/aprobar", headers={"Host": HOST, "Origin": ORIGEN, "X-PC-Doctor-Token": api.token, "Content-Type": "application/json"})
    assert r.status_code in (404, 405) and estado_plan(api) == "propuesto"


@pytest.mark.lento
@pytest.mark.parametrize("ruta", ["/api/estado", "/api/planes", f"/api/planes/1", "/api/planes/1/borrar", "/api/planes/1/aprobar/x", "/api/planes/abc/aprobar",
                                  "/api/token", "/api/hechos", "/api/config"])
def test_ningun_otro_endpoint_acepta_post_ni_con_token_valido(api, ruta):
    assert post(api, ruta).status_code == 405


@pytest.mark.lento
def test_con_todo_en_regla_aprobar_aplica_y_deshacer_revierte(api):
    r = post(api, f"/api/planes/{api.plan}/aprobar")
    assert r.status_code == 200 and r.json()["estado"] == "aplicado" and estado_plan(api) == "aplicado"
    assert post(api, f"/api/planes/{api.plan}/aprobar").status_code == 409                       # no se aplica dos veces
    d = post(api, f"/api/planes/{api.plan}/deshacer")
    assert d.status_code == 200 and d.json()["estado"] == "rechazado" and ["set", "balanced"] in [x["argv"] for x in fake_log("powerprofilesctl")]
    detalle = api.get(f"/api/planes/{api.plan}", headers={"Host": HOST}).json()
    assert detalle["estado"] == "rechazado" and detalle["ejecuciones"][0]["deshecha_en"]


@pytest.mark.lento
def test_rechazar_y_errores_del_endpoint(api):
    assert post(api, f"/api/planes/{api.plan}/rechazar").json()["estado"] == "rechazado"
    assert post(api, f"/api/planes/{api.plan}/rechazar").status_code == 409
    assert post(api, "/api/planes/99999/aprobar").status_code == 404
    assert api.get("/api/planes/99999", headers={"Host": HOST}).status_code == 404


@pytest.mark.lento
def test_la_lectura_de_planes_y_la_base_sigue_de_solo_lectura(api):
    l = api.get("/api/planes", headers={"Host": HOST}).json()["planes"]
    assert l and "hipotesis" not in l[0] and api.get("/api/planes?estado=raro", headers={"Host": HOST}).status_code == 400
    d = api.get(f"/api/planes/{api.plan}", headers={"Host": HOST}).json()
    assert d["hipotesis"] and d["acciones"][0]["simulacion"]
    assert db.SOLO_LECTURA is True                                  # escribir se pide solo dentro de los POST
    con = db.conectar()
    with pytest.raises(Exception, match="readonly"):
        con.execute("UPDATE planes SET estado='aplicado'")
    con.close()

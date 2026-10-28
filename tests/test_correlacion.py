"""Correlación de eventos y línea de tiempo: posibles causas de una alerta, relación fuerte para la notificación,
herramientas de monitoreo, ventana configurable y orden cronológico. Rescatadas de las pruebas de la Fase 2 (BITACORA.md)."""

import json
import time

import pytest

import correlacion
import db
import salud
import server

H = 3600


@pytest.fixture
def escenario(con):
    """4 snapshots (kernel, mesa, fuentes, smartmontools), eventos, 2 alertas, un hallazgo, una sesión y una acción."""
    T = db.ahora()
    con.execute("INSERT INTO workspace (id, hostname, machine_id, creado_en) VALUES (1,'h','m',?)", (T - 100 * H,))

    def snap(sid, horas, kernel, mesa, extra):
        con.execute("INSERT INTO snapshot_entorno (id, workspace_id, tomado_en, distro, kernel, escritorio, hash) VALUES (?,?,?,?,?,?,?)",
                    (sid, 1, T - horas * H, "Zorin", kernel, "gnome", f"h{sid}"))
        con.execute("INSERT INTO hardware VALUES (?,?,?,?,?)", (sid, "gpu", "AMD", "Navi",
                    json.dumps({"driver": "amdgpu", "version_driver": f"kernel {kernel} (in-tree)", "mesa": mesa})))
        for n, v in extra.items():
            con.execute("INSERT INTO software VALUES (?,?,?,?)", (sid, n, v, "apt"))
    base = {"bash": "5", "fonts-liberation": "1", "libreoffice": "7"}
    snap(1, 60, "K1", "25.0", {**base, "mesa-vulkan-drivers": "25.0"})
    snap(2, 30, "K1", "25.1", {**base, "mesa-vulkan-drivers": "25.1", "fonts-foo": "1", "fonts-liberation": "2"})
    snap(3, 5, "K2", "25.1", {**base, "mesa-vulkan-drivers": "25.1", "fonts-foo": "1", "fonts-liberation": "2"})
    snap(4, 1, "K2", "25.1", {**base, "mesa-vulkan-drivers": "25.1", "fonts-foo": "1", "fonts-liberation": "2", "smartmontools": "7.4"})
    for ts, o, sv, m in [(T - 20 * H, "kernel", "err", "amdgpu: ring gfx_0.0.0 timeout"), (T - 2 * H, "smartd", "crit", "Device: /dev/sdb 2 Offline uncorrectable sectors"),
                         (T + 1800, "kernel", "err", "amdgpu: ring gfx timeout"), (T + 1900, "kernel", "err", "amdgpu: ring gfx timeout")]:
        con.execute("INSERT INTO eventos (ts, origen, severidad, mensaje) VALUES (?,?,?,?)", (ts, o, sv, m))
    con.execute("INSERT INTO alertas_salud (clave, categoria, nombre, severidad, mensaje, valor, desde, ultima_vez, ultima_notif, activa) VALUES ('temp_gpu:amdgpu/junction','gpu','amdgpu/junction','aviso','GPU caliente',95,?,?,0,1)", (T, T))
    con.execute("INSERT INTO alertas_salud (clave, categoria, nombre, severidad, mensaje, valor, desde, ultima_vez, ultima_notif, activa) VALUES ('smart:sdb','disco','sdb','aviso','Sectores',2,?,?,0,1)", (T - 1800, T))
    con.execute("INSERT INTO hallazgos_seguridad (huella, categoria, regla, severidad, nombre, detalle, primera_vez, ultima_vez) VALUES ('x','minero','nombre','alta','xmrig','proceso sospechoso',?,?)", (T - 4 * H, T - 4 * H))
    con.execute("INSERT INTO sesiones_actividad (tipo, detalle, inicio, fin, ultima_vez) VALUES ('juego','Slay the Spire',?,?,?)", (T - 3 * H, T - 1 * H, T - 1 * H))
    con.execute("INSERT INTO acciones (ts, tool, resultado) VALUES (?,?,?)", (T - 6 * H, "limpiar_descargas_viejas", "3 movidos"))
    con.commit()
    return T


def test_posibles_causas_de_una_alerta_de_gpu(escenario):
    r = server.correlacionar("1")
    causas = r["posibles_causas"]
    assert [c["puntaje"] for c in causas] == sorted((c["puntaje"] for c in causas), reverse=True)    # ordenadas de mayor a menor
    assert not any("GPU caliente" in c["que"] for c in causas)                                        # la alerta no se cita a sí misma
    assert sum(1 for c in causas if "amdgpu: ring" in c["que"] and "x2" in c["que"]) <= 1             # eventos repetidos, agrupados
    assert "no causas demostradas" in r["aviso"]                                                       # nunca se afirma causalidad
    primero = causas[0]
    assert primero["tipo"] == "kernel" and "incluye el driver de GPU" in primero["que"]               # el kernel que trae el driver, fusionado


def test_el_cambio_de_kernel_y_el_de_driver_en_el_kernel_son_un_solo_elemento(escenario):
    causas = server.correlacionar("1")["posibles_causas"]
    assert [c["tipo"] for c in causas].count("kernel") == 1
    # el driver de GPU viene con el kernel (in-tree): no aparece además como un "cambio de driver" aparte
    assert not any(c["tipo"] == "driver_gpu" and "version_driver" in c["que"] for c in causas)


def test_las_herramientas_de_monitoreo_destapan_pero_no_causan(escenario):
    causas = server.correlacionar("2")["posibles_causas"]
    sm = [c for c in causas if "smartmontools" in c["que"]]
    assert sm and "destapado" in sm[0]["que"] and sm[0]["relevancia"] != "alta"


def test_posibles_causas_de_un_hallazgo(escenario):
    r = server.correlacionar("hallazgo:1")
    assert r["posibles_causas"] and r["alerta"]["tipo"] == "hallazgo de seguridad"


@pytest.mark.parametrize("ident", ["99", "hallazgo:99", "abc", "1;drop table"])
def test_identificadores_invalidos_dan_error_sin_romper(escenario, ident):
    assert "error" in server.correlacionar(ident)


def test_relacion_fuerte_solo_con_un_cambio_de_entorno_afin(escenario, con):
    T = escenario
    assert "kernel" in correlacion.relacion_fuerte(con, "gpu", T)
    assert correlacion.relacion_fuerte(con, "disco", T) is None     # un kernel nuevo no se cita en una alerta de disco
    assert correlacion.relacion_fuerte(con, None, T) is None
    assert correlacion.relacion_fuerte(con, "gpu", T - 35 * H) is None   # nada en las 24 h previas


def test_la_notificacion_agrega_la_relacion_solo_si_hay_candidato_fuerte(escenario, con):
    T = escenario
    enviados = []
    cond = lambda clave, cat, msg: {"clave": clave, "categoria": cat, "severidad": "aviso", "mensaje": msg}
    salud.enviar_aviso(con, [cond("temp_gpu:amdgpu/junction", "gpu", "GPU caliente")], T, lambda t, m, **k: enviados.append(m) or True)
    assert "posible relación" in enviados[-1]
    con.execute("INSERT INTO alertas_salud (clave, categoria, nombre, severidad, mensaje, valor, desde, ultima_vez, ultima_notif, activa) VALUES ('ram','memoria','ram','aviso','RAM alta',90,?,?,0,1)", (T - 40 * H, T))
    salud.enviar_aviso(con, [cond("ram", "memoria", "RAM alta")], T, lambda t, m, **k: enviados.append(m) or True)
    assert enviados[-1] == "• RAM alta"        # sin candidato: el texto queda exactamente como antes


def test_un_fallo_en_la_correlacion_nunca_bloquea_el_aviso(escenario, con, monkeypatch):
    monkeypatch.setattr(correlacion, "relacion_fuerte", lambda *a: 1 / 0)
    cond = [{"clave": "ram", "categoria": "memoria", "severidad": "aviso", "mensaje": "RAM alta"}]
    assert salud.enviar_aviso(con, cond, escenario, lambda *a, **k: True) is True


def test_linea_de_tiempo_en_orden_cronologico(escenario):
    lt = server.linea_de_tiempo("12h")
    horas = [f[0] for f in lt["cronologia"]]
    assert horas == sorted(horas) and lt["total"] == len(lt["cronologia"])


def test_linea_de_tiempo_filtra_por_tipo_y_desempata_de_forma_estable(escenario, con):
    T = escenario
    r = correlacion.linea_de_tiempo(con, T - 12 * H, T + H, {"alerta"}, estructurado=True)
    assert {i["tipo"] for i in r["items"]} == {"alerta"} and all(i["ref"].startswith("alerta:") for i in r["items"])
    a = correlacion.linea_de_tiempo(con, T - 12 * H, T + H)["cronologia"]
    assert a == correlacion.linea_de_tiempo(con, T - 12 * H, T + H)["cronologia"]   # mismo resultado siempre


def test_la_linea_de_tiempo_sigue_si_falta_alguna_tabla(escenario, con):
    con.execute("DROP TABLE sesiones_actividad")
    con.commit()
    assert correlacion.linea_de_tiempo(con, escenario - 12 * H, escenario + H)["total"] > 0


def test_ventana_configurable_en_config_json(escenario):
    (db.DIR_DATOS / "config.json").write_text(json.dumps({"correlacion": {"horas_antes": 4}}))
    causas = server.correlacionar("1")["posibles_causas"]
    assert not any("25.0 -> 25.1" in c["que"] for c in causas)          # el cambio de hace 30 h queda fuera de la ventana


def test_plural_de_paquetes_sin_relacion(escenario, con):
    # el snapshot 2 agrega 1 paquete irrelevante (fonts-foo) y actualiza otro (fonts-liberation): "2 paquetes más"
    textos = [i["titulo"] for i in correlacion.cambios_de_entorno(con, escenario - 40 * H, escenario - 20 * H) if i["tipo"] == "paquete_otros"]
    assert any(t.startswith("2 paquetes más") for t in textos)
    con.execute("DELETE FROM software WHERE snapshot_id=2 AND nombre='fonts-liberation'")
    con.execute("INSERT INTO software VALUES (2,'fonts-liberation','1','apt')")
    textos = [i["titulo"] for i in correlacion.cambios_de_entorno(con, escenario - 40 * H, escenario - 20 * H) if i["tipo"] == "paquete_otros"]
    assert any(t.startswith("1 paquete más") for t in textos)

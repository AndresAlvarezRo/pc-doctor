"""mostrar_en_pantalla: banner o solo bandeja, en Linux (gsettings falso) y en Windows (PowerShell falso). Ninguna notificación real."""

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

import actividad
import alertas
import db
import reputacion
from plataforma import windows_notificaciones as wn
from test_windows_notificaciones import PS, descifrar


def fake_log(cmd):
    return [r for r in map(json.loads, Path(os.environ["FAKE_LOG"]).read_text().splitlines()) if r.get("cmd") == cmd]


def poner_modo(modo):
    (db.DIR_DATOS).mkdir(parents=True, exist_ok=True)
    reputacion.RUTA_CONFIG.write_text(json.dumps({"mostrar_en_pantalla": modo}))


def juego(con, en_curso):
    con.execute("DELETE FROM sesiones_actividad")
    if en_curso:
        ahora = db.ahora()
        con.execute("INSERT INTO sesiones_actividad (tipo, detalle, inicio, ultima_vez) VALUES ('juego','Juego',?,?)", (ahora - 60, ahora))
    con.commit()


def sets(_=None):
    return [e["argv"] for e in fake_log("gsettings") if e["argv"][0] == "set"]


def test_el_modo_por_defecto_es_nunca_e_invalido_cae_a_nunca():
    assert alertas.modo_pantalla() == "nunca"
    poner_modo("a veces")
    assert alertas.modo_pantalla() == "nunca"


@pytest.mark.parametrize("modo,hay_juego,banner", [("nunca", False, False), ("nunca", True, False), ("siempre", False, True),
                                                   ("siempre", True, True), ("fuera_de_juego", False, True), ("fuera_de_juego", True, False)])
def test_banner_deseado_segun_modo_y_juego(con, modo, hay_juego, banner):
    poner_modo(modo)
    juego(con, hay_juego)
    assert alertas.banner_deseado() is banner


def test_nunca_escribe_una_sola_vez_y_solo_la_ruta_de_pc_doctor(con):
    poner_modo("nunca")
    alertas.sincronizar_banners()
    alertas.sincronizar_banners()
    s = sets()
    assert s == [["set", alertas.ESQUEMA_APP, "show-banners", "false"]]
    assert all(e["argv"][1] == alertas.ESQUEMA_APP for e in fake_log("gsettings"))  # nada global, nada de otras apps


def test_fuera_de_juego_apaga_al_empezar_y_enciende_al_terminar(con):
    poner_modo("fuera_de_juego")
    juego(con, False)
    alertas.sincronizar_banners()                      # primera vez: ya está en true, no escribe
    assert sets() == []
    juego(con, True)
    alertas.sincronizar_banners()
    juego(con, False)
    alertas.sincronizar_banners()
    assert [x[-1] for x in sets()] == ["false", "true"]


def test_siempre_no_toca_nada_si_nunca_se_apago(con):
    poner_modo("siempre")
    assert alertas.sincronizar_banners()["accion"] == "nada" and sets() == []


def test_siempre_restaura_si_pc_doctor_lo_habia_apagado(con):
    poner_modo("nunca"); alertas.sincronizar_banners()
    poner_modo("siempre"); alertas.sincronizar_banners()
    assert [x[-1] for x in sets()] == ["false", "true"]


def test_un_cambio_manual_se_respeta_hasta_que_cambie_la_opcion(con):
    poner_modo("fuera_de_juego"); juego(con, True)
    alertas.sincronizar_banners()                      # escribe false
    db_set = ["gsettings", "set", alertas.ESQUEMA_APP, "show-banners", "true"]  # el usuario lo enciende desde GNOME
    subprocess.run(db_set, check=True)
    n = len(sets())
    assert alertas.sincronizar_banners()["accion"] == "manual"
    juego(con, False); juego(con, True)
    assert alertas.sincronizar_banners()["accion"] == "manual" and len(sets()) == n
    poner_modo("nunca")                                # cambia la opción: se retoma el control
    assert alertas.sincronizar_banners()["accion"] == "escrito"


def test_sin_gnome_no_hace_nada(con, monkeypatch):
    monkeypatch.setenv("FAKE_GSETTINGS_FALLA", "1")
    assert alertas.sincronizar_banners()["accion"] == "sin_gnome"


def test_la_notificacion_lleva_app_y_desktop_entry_y_no_es_transitoria():
    cmd = alertas._comando("t", "m", False)
    assert "-a" in cmd and cmd[cmd.index("-a") + 1] == "pc-doctor"
    assert "--hint=string:desktop-entry:pc-doctor" in cmd and not any("transient" in a for a in cmd)


def test_notificar_sigue_enviando_y_con_boton(con):
    poner_modo("nunca")
    assert alertas.notificar("t", "m", seccion="alerta:1", forzar_boton=True)
    time.sleep(0.3)
    assert any(True for e in fake_log("notify-send")) or fake_log("systemd-run")


@pytest.mark.parametrize("modo,hay_juego,suprime", [("nunca", False, True), ("nunca", True, True), ("siempre", True, False),
                                                    ("fuera_de_juego", True, True), ("fuera_de_juego", False, False)])
def test_windows_suppresspopup_segun_modo(con, modo, hay_juego, suprime):
    poner_modo(modo)
    juego(con, hay_juego)
    ps = PS("ok")
    assert wn.notificar(ps, "t", "m", False, "alertas", False)
    assert ("SuppressPopup" in ps.scripts[0]) is suprime
    assert "<toast" in descifrar(ps.scripts[0])


def urgencia_enviada():
    return [e["argv"][e["argv"].index("-u") + 1] for e in fake_log("notify-send")]


@pytest.mark.parametrize("modo,hay_juego,esperada", [("nunca", False, "normal"), ("nunca", True, "normal"), ("siempre", False, "critical"),
                                                     ("fuera_de_juego", True, "normal"), ("fuera_de_juego", False, "critical")])
def test_sin_banner_la_critica_se_envia_como_normal(con, modo, hay_juego, esperada):
    poner_modo(modo)
    juego(con, hay_juego)
    assert alertas.notificar("t", "m", critica=True)
    assert urgencia_enviada() == [esperada]


def test_windows_sin_popup_no_marca_el_toast_como_recordatorio(con):
    poner_modo("nunca")
    ps = PS("ok")
    wn.notificar(ps, "t", "m", True, "alertas", True)
    assert "scenario" not in descifrar(ps.scripts[0])
    poner_modo("siempre")
    ps = PS("ok")
    wn.notificar(ps, "t", "m", True, "alertas", True)
    assert 'scenario="reminder"' in descifrar(ps.scripts[0])

"""Notificaciones (toast con botón por protocolo), apertura del dashboard y arranque de su tarea en Windows, con PowerShell falso.
Ninguna prueba muestra una notificación real."""

import base64
import re
import xml.etree.ElementTree as ET

import dashboard
import reputacion
from plataforma import windows_notificaciones as wn


def descifrar(script: str) -> str:
    return base64.b64decode(re.search(r"FromBase64String\('([^']+)'\)", script).group(1)).decode("utf-8")


class PS:
    """PowerShell falso: guarda los scripts que le pasan y devuelve lo que se le indique."""
    def __init__(self, salida=""):
        self.salida, self.scripts = salida, []

    def __call__(self, script, timeout=None):
        self.scripts.append(script)
        return self.salida


def test_el_toast_es_xml_valido_y_escapa_el_texto():
    x = wn.xml_toast('Alerta <1> & "2"', "GPU > 90 °C & subiendo", "http://localhost:8787/alerta/4")
    raiz = ET.fromstring(x)
    assert [t.text for t in raiz.iter("text")] == ['Alerta <1> & "2"', "GPU > 90 °C & subiendo"]


def test_el_boton_abre_el_dashboard_por_activacion_de_protocolo_sin_proceso_residente():
    raiz = ET.fromstring(wn.xml_toast("t", "m", "http://localhost:8787/alerta/4"))
    accion = raiz.find("actions/action")
    assert accion.get("content") == "Ver en el dashboard" and accion.get("arguments") == "http://localhost:8787/alerta/4"
    assert accion.get("activationType") == "protocol" and raiz.get("activationType") == "protocol"


def test_sin_seccion_no_hay_boton_y_una_critica_con_boton_se_queda_en_pantalla():
    assert ET.fromstring(wn.xml_toast("t", "m", None)).find("actions") is None
    assert ET.fromstring(wn.xml_toast("t", "m", None, critica=True)).get("scenario") is None   # "reminder" exige botón
    assert ET.fromstring(wn.xml_toast("t", "m", "http://localhost:8787/", critica=True)).get("scenario") == "reminder"


def test_el_script_registra_la_identidad_en_hkcu_y_lleva_el_xml_sin_escapes_de_powershell():
    xml = wn.xml_toast("Título con 'comillas' y $variables", "m", None)
    s = wn.script_toast(xml)
    assert descifrar(s) == xml
    assert r"HKCU:\Software\Classes\AppUserModelId\pc-doctor" in s and "HKLM" not in s and "CreateToastNotifier('pc-doctor')" in s


def test_notificar_manda_el_script_y_devuelve_si_se_pudo():
    ps = PS("")
    assert wn.notificar(ps, "t", "m", False, "alerta:7", False) is True
    assert 'arguments="' + dashboard.BASE + '/alerta/7"' in descifrar(ps.scripts[0])
    assert wn.notificar(lambda *a: None, "t", "m", False, None, False) is False


def test_una_seccion_invalida_envia_la_notificacion_sin_boton(caplog):
    ps = PS("")
    assert wn.notificar(ps, "t", "m", False, "http://evil.com", False) is True
    assert "evil" not in ps.scripts[0] and "<action" not in descifrar(ps.scripts[0])


def test_el_boton_viene_activo_y_se_apaga_solo_si_la_configuracion_lo_dice(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    monkeypatch.setattr(reputacion, "RUTA_CONFIG", cfg)
    assert wn.boton_activo()                                   # sin archivo
    cfg.write_text("{}")
    assert wn.boton_activo()
    cfg.write_text('{"boton_dashboard": false}')
    assert not wn.boton_activo()
    ps = PS("")
    wn.notificar(ps, "t", "m", False, "alertas", False)
    assert "<action" not in descifrar(ps.scripts[0])
    wn.notificar(ps, "t", "m", False, "alertas", True)   # forzar_boton: la prueba manual lo pide aunque esté apagado
    assert "<action" in descifrar(ps.scripts[1])


def test_iniciar_el_dashboard_en_sus_cuatro_estados(monkeypatch):
    vivo = [True]
    monkeypatch.setattr(dashboard, "activo", lambda *a, **k: vivo[0])
    assert wn.iniciar_dashboard(PS(), 1) == "activo"
    vivo[0] = False
    assert wn.iniciar_dashboard(PS("no_instalado\r\n"), 1) == "no_instalado"
    assert wn.iniciar_dashboard(lambda *a: None, 1) == "no_arranco"
    assert wn.iniciar_dashboard(PS("ok"), 0.5) == "no_arranco"      # la tarea arrancó pero el dashboard no responde
    ps = PS("ok")
    monkeypatch.setattr(dashboard, "activo", lambda *a, **k: len(ps.scripts) > 0)
    assert wn.iniciar_dashboard(ps, 2) == "iniciado" and "pc-doctor-web" in ps.scripts[0]


def test_abrir_url_usa_startfile_de_windows_y_si_no_el_navegador(monkeypatch):
    abiertas = []
    monkeypatch.setattr(wn.os, "startfile", lambda u: abiertas.append(u), raising=False)
    wn.abrir_url("http://localhost:8787/")
    assert abiertas == ["http://localhost:8787/"]
    monkeypatch.delattr(wn.os, "startfile")
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", lambda u: abiertas.append(("web", u)) or True)
    wn.abrir_url("http://localhost:8787/x")
    assert abiertas[-1] == ("web", "http://localhost:8787/x")


def test_los_mensajes_cuando_no_hay_dashboard_hablan_de_la_tarea_programada():
    assert "pc-doctor-web" in wn.MENSAJES["no_instalado"] and "Programador de tareas" in wn.MENSAJES["no_arranco"]

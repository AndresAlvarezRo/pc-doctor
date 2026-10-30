"""Notificaciones de escritorio con el botón "Ver en el dashboard".

`notify-send`, `systemd-run`, `systemctl`, `gdbus` y `xdg-open` son reemplazos que registran qué se les pidió (nada aparece en
pantalla); un servidor HTTP mínimo hace de dashboard. Rescatadas de las pruebas de la Fase 3 (BITACORA.md)."""

import json
import subprocess
import sys

import pytest
from ayudas import FALSOS, comandos, esperar, matar_servidores_falsos

import alertas
import dashboard
import db
import salud

pytestmark = pytest.mark.lento
B = dashboard.BASE


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    """Botón activado en la configuración, y limpieza de los servidores falsos al terminar."""
    (db.DIR_DATOS / "config.json").write_text(json.dumps({"boton_dashboard": True}))
    yield
    matar_servidores_falsos()


def sin_boton():
    return [c for c in comandos("notify-send") if not any(a.startswith("--action") for a in c["argv"])]


def con_boton():
    return [c for c in comandos("notify-send") if any(a.startswith("--action") for a in c["argv"])]


@pytest.fixture
def dashboard_activo():
    subprocess.Popen([sys.executable, str(FALSOS / "servidor_falso.py")], start_new_session=True, stdout=subprocess.DEVNULL)
    assert esperar(dashboard.activo, 5)


def test_boton_con_clic_abre_la_alerta_con_el_dashboard_activo(monkeypatch, dashboard_activo):
    (db.DIR_DATOS / "config.json").write_text('{"mostrar_en_pantalla": "siempre"}')   # con banner la urgencia crítica se conserva
    monkeypatch.setenv("FAKE_CLIC", "1")
    assert alertas.notificar("pc-doctor: 1 valor(es) fuera de lo normal", "• GPU caliente", critica=True, seccion="alerta:4") is True
    sr = comandos("systemd-run")
    assert len(sr) == 1 and any(o.startswith("RuntimeMaxSec=") for o in sr[0]["opciones"])           # una unidad con tope de vida
    assert any(o.startswith("--unit=pc-doctor-notif-") for o in sr[0]["opciones"])
    assert esperar(lambda: comandos("xdg-open")) and comandos("xdg-open")[0]["argv"] == [f"{B}/alerta/4"]
    n = con_boton()[0]["argv"]
    assert "--action=ver=Ver en el dashboard" in n and "critical" in n                                 # la urgencia crítica se conserva
    assert not [c for c in comandos("systemctl") if "start" in c["argv"]]                              # ya estaba activo


def test_sin_clic_no_se_abre_nada():
    alertas.notificar("t", "m", seccion="alertas")
    assert esperar(con_boton)
    import time; time.sleep(1.0)
    assert not comandos("xdg-open")


@pytest.mark.parametrize("entorno_falso", [{"FAKE_CAPS": "sin"}, {"FAKE_GDBUS_FALLA": "1"}, {"FAKE_ESCUCHAS": "10"}, {"FAKE_SYSTEMD_RUN_FALLA": "1"}],
                         ids=["sin acciones", "gdbus falla", "10 escuchas vivos", "systemd-run falla"])
def test_si_el_boton_no_se_puede_ofrecer_la_notificacion_sale_igual(monkeypatch, entorno_falso):
    for k, v in entorno_falso.items():
        monkeypatch.setenv(k, v)
    assert alertas.notificar("t", "m", seccion="alertas") is True
    assert len(sin_boton()) == 1 and not con_boton()


def test_con_9_escuchas_todavia_se_ofrece_el_boton(monkeypatch):
    monkeypatch.setenv("FAKE_ESCUCHAS", "9")
    alertas.notificar("t", "m", seccion="alertas")
    assert len(comandos("systemd-run")) == 1


def test_el_boton_esta_apagado_por_defecto_y_se_puede_forzar():
    (db.DIR_DATOS / "config.json").unlink()
    alertas.notificar("t", "m", seccion="alertas")
    assert not comandos("systemd-run") and len(sin_boton()) == 1
    alertas.notificar("t", "m", seccion="alertas", forzar_boton=True)
    assert len(comandos("systemd-run")) == 1


def test_boton_desactivado_en_la_configuracion():
    (db.DIR_DATOS / "config.json").write_text(json.dumps({"boton_dashboard": False}))
    assert alertas.notificar("t", "m", seccion="alertas") is True and not comandos("systemd-run")


def test_seccion_invalida_sale_simple_y_no_lanza_nada():
    assert alertas.notificar("t", "m", seccion="http://evil.com") is True
    assert not comandos("systemd-run") and len(sin_boton()) == 1


def test_sin_seccion_es_el_comportamiento_de_siempre_y_no_cuesta_nada_extra():
    assert alertas.notificar("titulo", "mensaje", critica=False) is True
    c = comandos("notify-send")
    assert len(c) == 1 and c[0]["argv"][-2:] == ["titulo", "mensaje"] and not comandos("systemd-run") and not comandos("systemctl")


def test_si_notify_send_esta_roto_devuelve_false_para_reintentar(monkeypatch):
    monkeypatch.setenv("FAKE_NOTIFY_FALLA", "1")
    assert alertas.notificar("t", "m") is False


def test_si_el_dashboard_esta_apagado_al_hacer_clic_se_arranca(monkeypatch):
    monkeypatch.setenv("FAKE_CLIC", "1")
    alertas.notificar("t", "m", seccion="hallazgo:7")
    assert esperar(lambda: comandos("xdg-open"), 12)
    assert any(c["argv"] == ["--user", "start", "pc-doctor-web.service"] for c in comandos("systemctl"))
    assert comandos("xdg-open")[0]["argv"] == [f"{B}/hallazgo/7"]


def test_si_el_servicio_no_esta_instalado_se_avisa_y_no_se_abre_el_navegador(monkeypatch):
    monkeypatch.setenv("FAKE_CLIC", "1")
    monkeypatch.setenv("FAKE_SERVICIO", "ausente")
    alertas.notificar("t", "m", seccion="alerta:1")
    assert esperar(lambda: [c for c in comandos("notify-send") if "No se pudo abrir pc-doctor" in c["argv"]], 8)
    aviso = [c for c in comandos("notify-send") if "No se pudo abrir pc-doctor" in c["argv"]][0]
    assert "no está instalado" in aviso["argv"][-1] and not comandos("xdg-open")


def test_el_texto_con_caracteres_especiales_llega_intacto():
    titulo = '--evil "comillas" $(echo hackeado) `ls` ; rm -rf ~'
    mensaje = "• línea uno\n• línea dos ñ 日本 <b>negrita</b> & %s %d\n   ↳ posible relación: kernel 1 -> 2"
    alertas.notificar(titulo, mensaje, seccion="alertas")
    assert esperar(con_boton)
    argv = con_boton()[0]["argv"]
    assert argv[-2] == titulo and argv[-1] == mensaje        # nada se interpreta por el camino


def test_si_la_version_con_boton_falla_dentro_del_escucha_se_manda_la_simple(monkeypatch):
    (db.DIR_DATOS / "config.json").write_text('{"mostrar_en_pantalla": "siempre"}')   # con banner la urgencia crítica se conserva
    monkeypatch.setenv("FAKE_ACCION_FALLA", "1")
    alertas.notificar("titulo O", "mensaje O", critica=True, seccion="alertas")
    assert esperar(sin_boton)
    assert sin_boton()[0]["argv"][-2:] == ["titulo O", "mensaje O"] and "critical" in sin_boton()[0]["argv"]   # no se pierde un aviso


# ---------- quién pide qué sección ----------

def test_salud_pide_el_boton_de_la_alerta_mas_grave(con):
    for clave, sev in (("a1", "aviso"), ("a2", "critico")):
        con.execute("INSERT INTO alertas_salud (clave, categoria, nombre, severidad, mensaje, valor, desde, ultima_vez, ultima_notif, activa) VALUES (?,?,?,?,?,1,1,1,0,1)",
                    (clave, "cpu", "x", sev, f"alerta {clave}"))
    conds = [{"clave": "a1", "severidad": "aviso", "mensaje": "aviso 1", "categoria": "cpu"}, {"clave": "a2", "severidad": "critico", "mensaje": "crítica 2", "categoria": "gpu"}]
    pedidos = []
    salud.enviar_aviso(con, conds, db.ahora(), lambda t, m, **k: pedidos.append(k) or True)
    rowid = con.execute("SELECT rowid FROM alertas_salud WHERE clave='a2'").fetchone()[0]
    assert pedidos[0]["seccion"] == f"alerta:{rowid}"


def test_seguridad_pide_el_boton_del_hallazgo(con, monkeypatch):
    con.execute("INSERT INTO hallazgos_seguridad (huella, categoria, regla, severidad, nombre, pid, detalle, primera_vez, ultima_vez, veces, estado) VALUES ('hh','minero','r','alta','xmrig',1,'d',?,?,1,'nuevo')", (db.ahora(), db.ahora()))
    pedidos = []
    monkeypatch.setattr(alertas, "notificar", lambda t, m, **k: pedidos.append(k) or True)
    alertas.avisar(con, 0)
    assert pedidos[0]["seccion"] == f"hallazgo:{con.execute('SELECT id FROM hallazgos_seguridad').fetchone()[0]}"

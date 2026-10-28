"""dashboard.py: URLs de las secciones, arranque del servicio y apertura del navegador, y la tool `abrir_dashboard` del MCP.

`systemctl`, `xdg-open` y `gdbus` son reemplazos; un servidor HTTP mínimo (tests/falsos/servidor_falso.py) hace de dashboard
en el puerto de pruebas. Rescatadas de las pruebas de la Fase 3 (BITACORA.md)."""

import json
import os
import subprocess
import sys

import pytest
from ayudas import FALSOS, comandos, esperar, matar_servidores_falsos

import dashboard
import server

B = dashboard.BASE


@pytest.fixture(autouse=True)
def sin_servidores_falsos():
    yield
    matar_servidores_falsos()


def levantar_servidor_falso():
    p = subprocess.Popen([sys.executable, str(FALSOS / "servidor_falso.py")], start_new_session=True, stdout=subprocess.DEVNULL)
    assert esperar(dashboard.activo, 5)
    return p


def test_el_puerto_de_las_pruebas_nunca_es_el_del_dashboard_real():
    assert dashboard.PUERTO == 8795 and B == "http://localhost:8795"


@pytest.mark.parametrize("seccion,esperada", [
    ("", f"{B}/"), ("inicio", f"{B}/"), ("alertas", f"{B}/#alertas"), ("linea_de_tiempo", f"{B}/#linea-de-tiempo"),
    ("linea de tiempo", f"{B}/#linea-de-tiempo"), ("Reportes", f"{B}/#reportes"), ("alerta:4", f"{B}/alerta/4"),
    ("hallazgo/12", f"{B}/hallazgo/12"), ("componente:gpu", f"{B}/componente/gpu"), ("componente:disco:sdb", f"{B}/componente/disco?id=sdb"),
])
def test_url_de_secciones_validas(seccion, esperada):
    assert dashboard.url_de(seccion) == esperada


@pytest.mark.parametrize("malo", ["http://evil.com", "alerta:abc", "alerta:4;rm", "componente:../../etc", "javascript:alert(1)",
                                  "alerta:" + "9" * 20, "//evil.com", "componente:gpu:" + "x" * 60, "alerta:4 --evil", "estado\nSet-Cookie: x"])
def test_url_de_rechaza_cualquier_cosa_que_no_sea_una_seccion_conocida(malo):
    with pytest.raises(ValueError):
        dashboard.url_de(malo)


def test_iniciar_con_el_dashboard_ya_activo_no_toca_systemd():
    levantar_servidor_falso()
    assert dashboard.iniciar() == "activo"
    assert not [c for c in comandos("systemctl") if "start" in c["argv"]]


def test_iniciar_arranca_el_servicio_si_esta_apagado():
    assert dashboard.iniciar(espera_s=8) == "iniciado"
    assert any(c["argv"] == ["--user", "start", "pc-doctor-web.service"] for c in comandos("systemctl"))


def test_servicio_no_instalado(monkeypatch):
    monkeypatch.setenv("FAKE_SERVICIO", "ausente")
    assert dashboard.iniciar() == "no_instalado"


def test_servicio_que_dice_arrancar_pero_no_responde(monkeypatch):
    monkeypatch.setenv("FAKE_SERVICIO", "roto")
    assert dashboard.iniciar(espera_s=1) == "no_arranco"


def test_abrir_arranca_el_servicio_y_abre_la_url():
    r = dashboard.abrir("alerta:3")
    assert r == {"url": f"{B}/alerta/3", "servicio": "iniciado", "abierto": True}
    assert esperar(lambda: comandos("xdg-open")) and comandos("xdg-open")[0]["argv"] == [f"{B}/alerta/3"]


def test_abrir_sin_servicio_no_abre_el_navegador_y_explica(monkeypatch):
    monkeypatch.setenv("FAKE_SERVICIO", "ausente")
    r = dashboard.abrir("estado")
    assert r["abierto"] is False and "no está instalado" in r["error"] and not comandos("xdg-open")


def test_la_tool_abrir_dashboard_del_mcp():
    assert server.abrir_dashboard("estado")["servicio"] == "iniciado"
    assert server.abrir_dashboard("estado")["servicio"] == "activo"
    assert esperar(lambda: len(comandos("xdg-open")) >= 2)
    for malo in ("https://evil.com", "alerta:x", "../../etc/passwd"):
        r = server.abrir_dashboard(malo)
        assert "error" in r and "abierto" not in r
    assert len(comandos("xdg-open")) == 2                       # las secciones inválidas no abrieron nada


def test_la_cli_abrir_avisa_con_una_notificacion_si_no_puede(monkeypatch):
    monkeypatch.setenv("FAKE_SERVICIO", "ausente")
    r = subprocess.run([sys.executable, "dashboard.py", "abrir", "alertas"], capture_output=True, text=True, env=os.environ)
    assert r.returncode == 1
    assert any("No se pudo abrir pc-doctor" in c["argv"] for c in comandos("notify-send"))

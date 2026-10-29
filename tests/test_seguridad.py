"""Escaneo de seguridad en Linux: lo que no debe cambiar al pasar por la capa de plataforma (no había pruebas del módulo)."""

import socket
from types import SimpleNamespace

import psutil
import pytest

import plataforma
import seguridad
from plataforma import linux


def sock(tipo, familia, ip, puerto, estado, pid, remoto=None):
    return SimpleNamespace(type=tipo, family=familia, laddr=SimpleNamespace(ip=ip, port=puerto) if ip else None,
                           raddr=SimpleNamespace(ip=remoto[0], port=remoto[1]) if remoto else None, status=estado, pid=pid)


def falso_psutil(monkeypatch, **cambios):
    """Reemplaza `psutil` solo dentro de seguridad.py (el real lo usa también la limpieza de las pruebas)."""
    base = {n: getattr(psutil, n) for n in ("NoSuchProcess", "AccessDenied", "Error", "CONN_LISTEN", "CONN_ESTABLISHED")}
    monkeypatch.setattr(seguridad, "psutil", SimpleNamespace(**base, **cambios))


def test_linux_deriva_el_escaneo_de_procesos_a_la_funcion_de_siempre(monkeypatch):
    monkeypatch.setattr(seguridad, "_escanear_procesos_linux", lambda: ([{"x": 1}], {"procesos": 3, "sin_acceso": 1}))
    assert seguridad.escanear_procesos() == ([{"x": 1}], {"procesos": 3, "sin_acceso": 1})
    assert linux.escanear_extra(object()) == [] and linux.describir_procesos([1, 2]) == {}


def test_un_proceso_con_nombre_de_minero_sigue_dando_el_mismo_hallazgo(monkeypatch):
    falso_psutil(monkeypatch, process_iter=lambda attrs: [SimpleNamespace(
        info={"pid": 99999999, "name": "xmrig"}, cmdline=lambda: ["xmrig", "-o", "stratum+tcp://x:3333"])])
    h, stats = seguridad.escanear_procesos()
    assert [(x["categoria"], x["regla"], x["severidad"]) for x in h] == [("minero", "nombre_conocido", "alta")] and stats["procesos"] == 1


def test_las_escuchas_externas_se_informan_igual_y_ipv6_se_reconoce_con_la_familia_del_sistema(monkeypatch):
    falso_psutil(monkeypatch, net_connections=lambda kind: [
        sock(socket.SOCK_STREAM, socket.AF_INET, "0.0.0.0", 27036, psutil.CONN_LISTEN, 1),
        sock(socket.SOCK_STREAM, socket.AF_INET6, "::", 8080, psutil.CONN_LISTEN, 2),
        sock(socket.SOCK_STREAM, socket.AF_INET, "127.0.0.1", 7681, psutil.CONN_LISTEN, 3)],
        Process=lambda pid: SimpleNamespace(name=lambda: f"proc{pid}"))
    h, escuchas = seguridad.escanear_red()
    assert sorted((e["proto"], e["puerto"]) for e in escuchas) == [("tcp", 7681), ("tcp", 27036), ("tcp6", 8080)]
    assert sorted(x["detalle"] for x in h) == ["Escucha en 0.0.0.0:27036 (accesible desde la red)", "Escucha en :::8080 (accesible desde la red)"]


def test_la_firma_del_programa_se_suma_al_detalle_solo_si_la_plataforma_la_da(monkeypatch):
    falso_psutil(monkeypatch, net_connections=lambda kind: [sock(socket.SOCK_STREAM, socket.AF_INET, "0.0.0.0", 3389, psutil.CONN_LISTEN, 7)],
                 Process=lambda pid: SimpleNamespace(name=lambda: "svc"))
    huella_sin = seguridad.escanear_red()[0][0]
    monkeypatch.setattr(linux, "describir_procesos", lambda pids: {7: "sin firma digital"})
    con_firma = seguridad.escanear_red()[0][0]
    assert huella_sin["detalle"].endswith("(accesible desde la red)") and con_firma["detalle"].endswith("[sin firma digital]")
    assert huella_sin["huella"] == con_firma["huella"]                      # agregar la firma no cambia la identidad del hallazgo


def test_el_escaneo_completo_suma_lo_extra_de_la_plataforma_y_ordena_por_severidad(monkeypatch):
    monkeypatch.setattr(seguridad, "escanear_procesos", lambda con=None: ([seguridad._h("minero", "a", "baja", "a", 1, "", "d")], {"procesos": 1, "sin_acceso": 0}))
    monkeypatch.setattr(seguridad, "escanear_red", lambda: ([], []))
    monkeypatch.setattr(linux, "escanear_extra", lambda con=None: [seguridad._h("postura", "b", "alta", "b", None, "", "d")])
    r = seguridad.escanear()
    assert [h["severidad"] for h in r["hallazgos"]] == ["alta", "baja"]


def test_guardar_deduplica_por_huella_y_cuenta_las_veces(con):
    h = seguridad._h("red", "escucha_externa", "baja", "steam", 1, "", "d", clave="tcp:1")
    assert seguridad.guardar(con, {"hallazgos": [h], "escuchas": []})["nuevos"] == 1
    assert seguridad.guardar(con, {"hallazgos": [h], "escuchas": []})["nuevos"] == 0
    assert con.execute("SELECT veces FROM hallazgos_seguridad").fetchone()["veces"] == 2

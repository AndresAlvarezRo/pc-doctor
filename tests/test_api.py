"""API local del dashboard: protección (Host, métodos, encabezados), parámetros inválidos, recorrido de rutas, solo lectura,
degradación sin fuentes de datos y concurrencia con un proceso que escribe. Rescatadas de las pruebas de la Fase 1 del dashboard.

Usa los datos sintéticos de web/datos_de_prueba.py y sensores en vivo sintéticos: no depende del hardware."""

import hashlib
import http.client
import json
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse

import pytest

import db
from conftest import PUERTO_PRUEBAS, RAIZ

pytestmark = pytest.mark.lento
HOST = f"127.0.0.1:{PUERTO_PRUEBAS}"
ENDPOINTS = ["/api/estado", "/api/componentes/cpu", "/api/componentes/gpu", "/api/componentes/ram", "/api/componentes/disco",
             "/api/componentes/ventiladores", "/api/componentes/voltajes", "/api/componentes/placa",
             "/api/series?sensor=k10temp/Tctl&desde=24h", "/api/series?sensor=k10temp/Tctl&desde=7d",
             "/api/series?sensor=k10temp/Tctl&desde=30d&contexto=juego", "/api/series?sensor=k10temp/Tctl&desde=180d",
             "/api/alertas", "/api/alertas?estado=todas&dias=30", "/api/hallazgos", "/api/linea_de_tiempo?desde=48h",
             "/api/linea_de_tiempo?desde=48h&tipos=entorno,alertas", "/api/correlacion/4", "/api/correlacion/hallazgo:3",
             "/api/reportes", "/api/diagnosticos", "/api/entorno", "/api/limitaciones", "/api/sesiones?dias=14", "/api/acciones", "/api/config"]


# ---------- todos los endpoints responden ----------

@pytest.mark.parametrize("ruta", ENDPOINTS)
def test_cada_endpoint_responde_200_con_json(cliente_api, ruta):
    r = cliente_api.get(ruta)
    assert r.status_code == 200 and isinstance(r.json(), (dict, list))


def test_estado_resume_el_equipo_las_alertas_y_las_tarjetas(cliente_api):
    e = cliente_api.get("/api/estado").json()
    assert e["contexto"] in ("reposo", "carga", "juego") and e["equipo"]["cpu"] and e["alertas"]["total"] == 4
    tipos = {t["tipo"] for t in e["tarjetas"]}
    assert {"cpu", "gpu", "ram", "disco", "ventiladores", "voltajes", "placa"} <= tipos
    assert all(t["segun_linea_base"] in ("dentro", "fuera", "aprendiendo", "sin_referencia") for t in e["tarjetas"])


def test_el_titulo_de_la_gpu_y_los_discos_vienen_del_hardware(cliente_api):
    t = {(x["tipo"], x["id"]): x["titulo"] for x in cliente_api.get("/api/estado").json()["tarjetas"]}
    assert t[("gpu", "gpu")] == "Radeon RX 7600" and "Patriot" in t[("disco", "sdb")]


def test_serie_con_banda_de_la_linea_base_y_puntos_fuera(cliente_api):
    s = cliente_api.get("/api/series?sensor=amdgpu/junction&desde=24h").json()
    assert s["bandas"]["reposo"]["madura"] and s["bandas"]["reposo"]["limite"][1] > s["bandas"]["reposo"]["mediana"]
    assert sum(p["f"] for p in s["puntos"]) == 6          # los 6 puntos anómalos que inyecta el generador
    assert any(p["a"] for p in cliente_api.get("/api/series?sensor=k10temp/Tctl&desde=7d").json()["puntos"])   # el juego en curso


def test_un_rango_largo_usa_el_registro_diario(cliente_api):
    s = cliente_api.get("/api/series?sensor=k10temp/Tctl&desde=180d").json()
    assert "diaria" in s["resolucion"] and s["n_diarios"] > 0 and len(s["puntos"]) < 400


def test_los_secretos_de_la_configuracion_no_salen(cliente_api):
    cfg = cliente_api.get("/api/config").json()
    assert cfg["malwarebazaar_key"] == {"cargada": True}
    assert "esto-es-un-secreto" not in json.dumps(cfg)


def test_diagnosticos_dice_no_disponible_todavia(cliente_api):
    r = cliente_api.get("/api/diagnosticos").json()
    assert r["disponible"] is False and "todavía" in r["mensaje"]


# ---------- protección ----------

def pedir(cliente, metodo, ruta, host=HOST):
    return cliente.request(metodo, ruta, headers={"Host": host})


@pytest.mark.parametrize("host,esperado", [(HOST, 200), (f"localhost:{PUERTO_PRUEBAS}", 200), (f"LOCALHOST:{PUERTO_PRUEBAS}", 200),
                                           ("evil.com", 421), (f"evil.com:{PUERTO_PRUEBAS}", 421), ("localhost:9999", 421), ("127.0.0.1", 421),
                                           (f"localhost.evil.com:{PUERTO_PRUEBAS}", 421)])
def test_solo_se_aceptan_los_host_locales_contra_dns_rebinding(cliente_api, host, esperado):
    assert pedir(cliente_api, "GET", "/api/config", host).status_code == esperado


@pytest.mark.parametrize("metodo", ["POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
def test_solo_se_acepta_get(cliente_api, metodo):
    assert pedir(cliente_api, metodo, "/api/estado").status_code == 405


@pytest.mark.parametrize("ruta,esperado", [
    ("/api/series", 422), ("/api/series?sensor=k10temp/Tctl&desde=ayer", 400), ("/api/series?sensor=k10temp/Tctl&contexto=turbo", 400),
    ("/api/series?sensor=k10temp/Tctl&desde=2026-10-20&hasta=2026-10-01", 400), ("/api/series?sensor=k10temp/Tctl&desde=2000-01-01", 400),
    ("/api/series?sensor=" + "x" * 500, 422), ("/api/series?sensor=k10temp/Tctl&max_puntos=99999", 422),
    ("/api/alertas?estado=raras", 400), ("/api/alertas?dias=0", 422), ("/api/alertas?dias=99999", 422), ("/api/hallazgos?estado=x", 400),
    ("/api/componentes/foo", 404), ("/api/componentes/..%2fetc", 404), ("/api/correlacion/abc", 400), ("/api/correlacion/1;drop", 400),
    ("/api/correlacion/9999", 404), ("/api/correlacion/hallazgo:9999", 404), ("/api/linea_de_tiempo?tipos=rarotipo", 400),
    ("/api/reportes/2026-99-99", 404), ("/api/reportes/..%2f..%2fetc%2fpasswd", 404),
    ("/api/reportes/doctor", 404), ("/api/no_existe", 404)])
def test_parametros_invalidos_y_recorrido_de_rutas(cliente_api, ruta, esperado):
    assert cliente_api.get(ruta).status_code == esperado


@pytest.mark.parametrize("ruta", ["/etc/passwd", "/../../etc/passwd", "/..%2f..%2fetc%2fpasswd", "/%2e%2e/%2e%2e/etc/passwd",
                                  "/assets/..%2f..%2f..%2f..%2fetc%2fpasswd", "/api/reportes/..%2f..%2f..%2fetc%2fpasswd"])
def test_ninguna_ruta_sirve_archivos_del_sistema(cliente_api, ruta):
    r = cliente_api.get(ruta)
    assert "root:" not in r.text and "/bin/bash" not in r.text     # con el frontend compilado devuelve la página; sin él, 404


def test_la_inyeccion_sql_en_el_nombre_del_sensor_no_devuelve_datos_ajenos(cliente_api):
    r = cliente_api.get("/api/series?sensor=" + urllib.parse.quote("x' OR '1'='1"))
    assert r.status_code == 200 and r.json()["puntos"] == []


def test_encabezados_de_seguridad(cliente_api):
    h = cliente_api.get("/api/estado").headers
    assert h["cache-control"] == "no-store" and h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
    assert "access-control-allow-origin" not in h        # otro origen no puede leer la respuesta


# ---------- solo lectura de verdad ----------

def test_la_conexion_de_la_api_rechaza_cualquier_escritura(cliente_api):
    con = db.conectar()
    for sql in ("INSERT INTO acciones (ts, tool) VALUES (1, 'x')", "UPDATE alertas_salud SET activa=0", "DELETE FROM lecturas",
                "DROP TABLE acciones", "CREATE TABLE x (a)"):
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            con.execute(sql)
    con.close()


def test_recorrer_todos_los_endpoints_no_cambia_la_base(cliente_api):
    huella = lambda: hashlib.sha256(db.RUTA_DB.read_bytes()).hexdigest()
    antes = huella()
    for ruta in ENDPOINTS:
        cliente_api.get(ruta)
    assert huella() == antes


# ---------- degradación ----------

def test_una_base_de_una_version_anterior_degrada_solo_las_secciones_afectadas(con_datos_ricos, cliente_api):
    viejo = sqlite3.connect(db.RUTA_DB)
    for t in ("sesiones_actividad", "reportes", "reputacion"):
        viejo.execute(f"DROP TABLE {t}")
    viejo.commit()
    viejo.close()
    for ruta in ("/api/estado", "/api/alertas", "/api/linea_de_tiempo?desde=48h", "/api/entorno"):
        assert "disponible" not in cliente_api.get(ruta).json() or cliente_api.get(ruta).json().get("disponible") is not False
    for ruta in ("/api/hallazgos", "/api/reportes", "/api/sesiones"):
        r = cliente_api.get(ruta)
        assert r.status_code == 200 and r.json()["disponible"] is False and "todavía" in r.json()["mensaje"]


def test_sin_base_de_datos_todo_dice_no_disponible_todavia(cliente_api, tmp_path, monkeypatch):
    monkeypatch.setattr(db, "RUTA_DB", tmp_path / "no-existe.db")
    for ruta in ("/api/estado", "/api/componentes/cpu", "/api/series?sensor=x", "/api/alertas", "/api/hallazgos", "/api/linea_de_tiempo",
                 "/api/correlacion/4", "/api/reportes", "/api/entorno", "/api/limitaciones", "/api/sesiones", "/api/acciones"):
        r = cliente_api.get(ruta)
        assert r.status_code == 200 and r.json()["disponible"] is False, ruta


# ---------- concurrencia con un proceso que escribe (como el recolector) ----------

def puerto_libre():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_la_api_lee_mientras_otro_proceso_escribe(con_datos_ricos, tmp_path):
    puerto = puerto_libre()
    env = {**__import__("os").environ, "PC_DOCTOR_DATOS": str(con_datos_ricos), "PC_DOCTOR_PUERTO": str(puerto)}
    servidor = subprocess.Popen([sys.executable, "-m", "uvicorn", "web.api:app", "--host", "127.0.0.1", "--port", str(puerto), "--log-level", "error"],
                                cwd=RAIZ, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", puerto), 0.3).close()
                break
            except OSError:
                time.sleep(0.1)
        parar, estados = threading.Event(), []

        def escritor():
            c = sqlite3.connect(con_datos_ricos / "doctor.db", timeout=10)
            while not parar.is_set():
                c.execute("INSERT INTO eventos (ts, origen, severidad, mensaje) VALUES (?,?,?,?)", (int(time.time()), "prueba", "err", "evento de concurrencia"))
                c.commit()
                time.sleep(0.01)

        def cliente():
            con = http.client.HTTPConnection("127.0.0.1", puerto, timeout=60)
            for r in ["/api/alertas", "/api/series?sensor=k10temp/Tctl&desde=7d", "/api/linea_de_tiempo?desde=48h", "/api/hallazgos", "/api/sesiones", "/api/reportes"] * 5:
                con.putrequest("GET", r, skip_host=True)
                con.putheader("Host", f"127.0.0.1:{puerto}")
                con.endheaders()
                x = con.getresponse()
                x.read()
                estados.append(x.status)
        w = threading.Thread(target=escritor)
        w.start()
        hilos = [threading.Thread(target=cliente) for _ in range(6)]
        [h.start() for h in hilos]
        [h.join() for h in hilos]
        parar.set()
        w.join()
        assert len(estados) == 180 and set(estados) == {200}
    finally:
        servidor.terminate()
        servidor.wait(10)

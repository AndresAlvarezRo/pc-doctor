"""Agrupación de lecturas en componentes, nombres legibles y retención de datos del recolector."""

import time

import pytest
from ayudas import L, lecturas_vivas

import collector
import consultas
import db
import reputacion

NOMBRES_GPU = [
    ("Advanced Micro Devices, Inc. [AMD/ATI] Navi 33 [Radeon RX 7700S/7600/7600S/7600M XT/PRO W7600] [1002:7480] (rev c0)", "Radeon RX 7700S/7600/7600S/7600M XT/PRO W7600"),
    ("NVIDIA Corporation GA104 [GeForce RTX 3070] [10de:2484] (rev a1)", "GeForce RTX 3070"),
    ("Intel Corporation UHD Graphics 630 (rev 02)", "Intel Corporation UHD Graphics 630"),
    ("", "Placa de video"),
]


@pytest.mark.parametrize("modelo,esperado", NOMBRES_GPU)
def test_nombre_de_gpu_independiente_del_fabricante(modelo, esperado):
    assert consultas.nombre_gpu(modelo) == esperado


@pytest.mark.parametrize("nombre,esperado", [
    ("k10temp/Tctl", "Temperatura del procesador (Tctl)"), ("nct6798/fan3", "Ventilador 3"), ("nct6798/in7", "Entrada de voltaje 7"),
    ("fs:/home/libre_pct", "Espacio libre"), ("algo/raro_de_prueba", "Raro de prueba")])
def test_etiquetas_legibles(nombre, esperado):
    assert consultas.etiqueta(nombre) == esperado


def estado(lecturas, contexto="reposo"):
    return {"lecturas": lecturas, "conds": {}, "contexto": contexto, "juego": [], "no_disponible": []}


def test_las_lecturas_se_agrupan_en_componentes(con):
    c = consultas.componentes(con, estado(lecturas_vivas()))
    assert {k for k, v in c.items() if v} == {"cpu", "gpu", "ram", "disco", "ventiladores", "voltajes", "placa"}
    discos = {x["id"] for x in c["disco"]}
    assert {"particiones", "sda", "sdb", "nvme"} <= discos or {"particiones", "sda", "sdb"} <= discos   # los drivetemp se asignan a su disco
    assert [s["etiqueta"] for x in c["cpu"] for s in x["sensores"]][0]


def test_un_ventilador_en_0_se_distingue_entre_vacio_y_parado(con):
    con.execute("INSERT INTO lecturas (metrica_id, ts, categoria, nombre, valor, unidad, contexto) VALUES (0,1,'placa','nct6798/fan7',1200,'RPM','reposo')")
    ls = [L("nct6798/fan1", 0, "placa", "RPM"), L("nct6798/fan7", 0, "placa", "RPM"), L("nct6798/fan2", 1500, "placa", "RPM")]
    por = {s["nombre"]: s for x in consultas.componentes(con, estado(ls))["ventiladores"] for s in x["sensores"]}
    assert por["nct6798/fan1"]["giro"] == "vacio" and por["nct6798/fan7"]["giro"] == "parado" and por["nct6798/fan2"]["giro"] == "gira"


def test_una_condicion_activa_marca_el_estado_del_sensor_y_del_componente(con):
    st = estado([L("k10temp/Tctl", 96.0)])
    st["conds"] = {"x": {"nombre": "k10temp/Tctl", "severidad": "critico", "mensaje": "caliente"}}
    cpu = consultas.componentes(con, st)["cpu"][0]
    assert cpu["estado"] == "critico" and cpu["sensores"][0]["mensaje"] == "caliente"


# ---------- retención ----------

def test_la_retencion_borra_lo_crudo_viejo_pero_conserva_el_resumen_diario(con):
    viejo = db.ahora() - 40 * 86400
    reciente = db.ahora() - 3600
    con.execute("INSERT INTO workspace (id, hostname, machine_id, creado_en) VALUES (1,'h','m',1)")
    for ts in (viejo, reciente):
        con.execute("INSERT INTO metricas (workspace_id, ts, cpu_pct) VALUES (1,?,10)", (ts,))
        con.execute("INSERT INTO lecturas (metrica_id, ts, categoria, nombre, valor, unidad, contexto) VALUES (1,?,'cpu','k10temp/Tctl',60,'°C','reposo')", (ts,))
    con.commit()
    assert collector.aplicar_retencion(con) == 1
    assert con.execute("SELECT COUNT(*) FROM lecturas").fetchone()[0] == 1                # la cruda de hace 40 días se borró
    assert con.execute("SELECT COUNT(*) FROM lecturas_diarias WHERE nombre='k10temp/Tctl'").fetchone()[0] == 1   # pero su resumen quedó
    assert con.execute("SELECT COUNT(*) FROM metricas_diarias").fetchone()[0] == 1


# ---------- configuración ----------

def test_consultar_la_configuracion_no_crea_el_archivo_salvo_que_se_pida():
    assert reputacion.cargar_config(crear=False)["consulta_online"] is True
    assert not (db.DIR_DATOS / "config.json").exists()
    reputacion.cargar_config()
    assert (db.DIR_DATOS / "config.json").exists()


def test_los_valores_por_defecto_son_seguros():
    cfg = reputacion.cargar_config(crear=False)
    assert cfg["boton_dashboard"] is False and cfg["malwarebazaar_key"] == ""      # el botón se activa a mano; sin clave de abuse.ch

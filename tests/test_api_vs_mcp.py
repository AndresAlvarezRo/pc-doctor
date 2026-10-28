"""El dashboard y el MCP tienen que mostrar exactamente lo mismo: se compara la API (HTTP) con las tools (llamadas directas)
sobre la misma base. Rescatada de las pruebas de la Fase 1 del dashboard."""

import pytest

import db
import server

pytestmark = pytest.mark.lento


def test_alertas(cliente_api):
    a = cliente_api.get("/api/alertas?estado=todas&dias=30").json()["alertas"]
    m = server.alertas_salud(False, 30)["alertas"]
    assert sorted((x["id"], x["severidad"], x["mensaje"], x["estado"]) for x in a) == sorted((x["id"], x["severidad"], x["mensaje"], x["estado"]) for x in m)
    assert sorted((x["id"], db.iso(x["desde"])) for x in a) == sorted((x["id"], x["desde"]) for x in m)


def test_hallazgos(cliente_api):
    a = cliente_api.get("/api/hallazgos?estado=todos&dias=30").json()["hallazgos"]
    m = server.hallazgos_seguridad("todos", 30)["hallazgos"]
    assert [(x["id"], x["severidad"], x["proceso"], x["estado"]) for x in a] == [(x["id"], x["severidad"], x["proceso"], x["estado"]) for x in m]


def test_sesiones(cliente_api):
    a = cliente_api.get("/api/sesiones?dias=30").json()["sesiones"][:30]
    m = server.sesiones_actividad("", 30)["sesiones"]
    assert [(x["id"], x["detalle"], x["duracion_min"], x["cpu_max_c"], x["gpu_max_c"]) for x in a] == \
           [(x["id"], x["detalle"], x["duracion_min"], x["cpu_max_c"], x["gpu_max_c"]) for x in m]


def test_correlacion_linea_de_tiempo_entorno_y_reportes(cliente_api):
    assert cliente_api.get("/api/correlacion/4").json()["posibles_causas"] == server.correlacionar("4")["posibles_causas"]
    assert cliente_api.get("/api/linea_de_tiempo?desde=48h&limite=80").json()["cronologia"] == server.linea_de_tiempo("48h")["cronologia"]
    assert cliente_api.get("/api/entorno").json()["perfil"] == server.perfil_entorno()
    lista = cliente_api.get("/api/reportes").json()["reportes"]
    assert [(x["modo"], x["resumen"]) for x in lista] == [(x["modo"], x["resumen"]) for x in server.reportes(10)["reportes"]]
    assert cliente_api.get("/api/reportes/" + lista[0]["fecha"]).json()["contenido"] == server.ultimo_reporte()["contenido"]


def test_estado_en_vivo(cliente_api):
    a = sorted(x["mensaje"] for x in cliente_api.get("/api/estado").json()["fuera_de_lo_normal"])
    m = server.estado_salud()["fuera_de_lo_normal"]
    assert a == (sorted(x["mensaje"] for x in m) if isinstance(m, list) else [])


def test_serie_y_linea_base(cliente_api):
    s = cliente_api.get("/api/series?sensor=k10temp/Tctl&desde=7d").json()["puntos"]
    h = server.historial("k10temp/Tctl", "7d")
    assert (len(s), round(sum(p["v"] for p in s) / len(s), 1)) == (h["puntos"], h["promedio"])
    b = cliente_api.get("/api/series?sensor=k10temp/Tctl&desde=24h").json()["bandas"]["reposo"]
    l = [x for x in server.linea_base_aprendida("cpu", "reposo")["sensores"] if x["sensor"] == "k10temp/Tctl"][0]
    assert (round(b["mediana"], 1), round(b["p95"], 1), b["n"]) == (l["mediana"], l["p95"], l["n"])

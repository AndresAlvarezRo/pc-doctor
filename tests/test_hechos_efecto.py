"""Fase 2 de la memoria: los hechos conocidos silencian lo conocido, no lo nuevo.

Se prueban las alertas (silencio, empeoramiento, escalada, vencimiento, retiro), lo que muestra el dashboard y el MCP, el reporte
semanal (prompt y plan B) y que el modelo del reporte solo pueda LEER hechos. Todo en la base temporal."""

from datetime import date, timedelta

import pytest
from ayudas import L
from test_salud import Simulador

import consultas
import db
import memoria
import reporte
import server

AYER = (date.today() - timedelta(days=1)).isoformat()
MANANA = (date.today() + timedelta(days=1)).isoformat()


def smart(**valores):
    """Lecturas SMART de sdb, por ejemplo smart(sectores_pendientes=1)."""
    return [L(f"sdb/{k}", v, "disco", "") for k, v in valores.items()]


@pytest.fixture
def sim(con):
    s = Simulador(con)
    s.t = db.ahora() - 3 * 86400        # tiempo real y reciente: las consultas del dashboard y del reporte miran los últimos días
    return s


def alertas_activas(con):
    return {f["clave"]: f for f in con.execute("SELECT * FROM alertas_salud WHERE activa=1")}


# ---------- sin hechos, todo igual que siempre ----------

def test_sin_hechos_las_alertas_avisan_como_siempre_y_no_se_crean_tablas(sim, con):
    _, _, n = sim.corrida(smart(sectores_pendientes=1))
    assert n == 1
    assert not memoria.existe(con, "hechos_referencia") and not memoria.existe(con, "hechos_conocidos")


# ---------- silencio de lo conocido ----------

def test_un_hecho_conocido_silencia_la_alerta_nueva_pero_la_deja_registrada(sim, con):
    memoria.agregar_hecho_conocido(con, "sdb es un disco descartable", "sdb")
    _, _, n = sim.corrida(smart(sectores_pendientes=1))
    assert n == 0 and "smart_pendientes:sdb/sectores_pendientes" in alertas_activas(con)       # se ve en el dashboard, pero no molesta
    for _ in range(40):                                                                       # ni siquiera pasadas 10 horas
        _, _, n = sim.corrida(smart(sectores_pendientes=1))
        assert n == 0


def test_el_hecho_solo_silencia_lo_que_cubre(sim, con):
    memoria.agregar_hecho_conocido(con, "sdb anda mal", "sdb")
    _, _, n = sim.corrida(smart(sectores_pendientes=1) + [L("sda/sectores_pendientes", 1, "disco", "")])
    assert n == 1 and "sda" in sim.enviados[-1][1] and "sdb" not in sim.enviados[-1][1]      # sda es otro disco: sí avisa


def test_un_hecho_por_regla_y_disco_no_silencia_los_otros_contadores(sim, con):
    memoria.agregar_hecho_conocido(con, "los CRC de sdb son del cable", "sdb/errores_crc")
    _, _, n = sim.corrida(smart(errores_crc=20, sectores_pendientes=1))
    assert n == 1 and "pendientes" in sim.enviados[-1][1].lower() and "CRC" not in sim.enviados[-1][1]


# ---------- lo nuevo y lo que empeora sigue avisando ----------

def test_un_contador_de_smart_que_sube_avisa_aclarando_el_hecho_conocido(sim, con):
    h = memoria.agregar_hecho_conocido(con, "sdb anda mal", "sdb")["id"]
    sim.corrida(smart(sectores_pendientes=1))
    _, _, n = sim.corrida(smart(sectores_pendientes=1))
    assert n == 0
    _, _, n = sim.corrida(smart(sectores_pendientes=2))                                       # un sector más ya es novedad
    assert n == 1 and f"hecho conocido #{h}: empeoró (antes 1)" in sim.enviados[-1][1]
    _, _, n = sim.corrida(smart(sectores_pendientes=2))                                       # el nuevo valor pasa a ser lo conocido
    assert n == 0
    _, _, n = sim.corrida(smart(sectores_pendientes=3))
    assert n == 1 and "(antes 2)" in sim.enviados[-1][1]


def test_la_escalada_de_aviso_a_critico_avisa(sim, con):
    memoria.agregar_hecho_conocido(con, "sdb anda mal", "sdb")
    sim.corrida(smart(sectores_pendientes=1))
    _, _, n = sim.corrida(smart(sectores_pendientes=10))                                      # 10 = crítico
    assert n == 1 and sim.enviados[-1][2] is True and "empeoró" in sim.enviados[-1][1]


def test_una_temperatura_solo_empeora_si_cambia_mas_del_5_por_ciento(sim, con):
    memoria.agregar_hecho_conocido(con, "la CPU anda caliente por la pasta", "k10temp/Tctl")
    sim.corrida([L("k10temp/Tctl", 93.0)])
    _, _, n = sim.corrida([L("k10temp/Tctl", 96.0)])                                          # +3 %: ruido
    assert n == 0
    _, _, n = sim.corrida([L("k10temp/Tctl", 99.0)])                                          # +6 %: empeoró
    assert n == 1


def test_un_valor_que_baja_es_mejora_y_en_las_reglas_de_minimo_bajar_es_empeorar(sim, con):
    memoria.agregar_hecho_conocido(con, "el disco está lleno y lo sé", "fs:/home/libre_pct")
    sim.corrida([L("fs:/home/libre_pct", 5.0, "disco", "%")])                                 # crítico (menos de 7 %)
    _, _, n = sim.corrida([L("fs:/home/libre_pct", 6.0, "disco", "%")])                       # más libre: mejora
    assert n == 0
    _, _, n = sim.corrida([L("fs:/home/libre_pct", 2.0, "disco", "%")])                       # menos libre: empeoró
    assert n == 1


def test_los_eventos_conocidos_se_silencian_y_solo_empeoran_si_escala_la_severidad(con):
    import salud
    memoria.agregar_hecho_conocido(con, "esa limitación térmica ya la conozco", "evento:termico")

    def ev(t, sev):
        return {"evento:termico": {"clave": "evento:termico", "categoria": "cpu", "nombre": "termico", "severidad": sev,
                                   "valor": t, "evento": True, "mensaje": "Limitación térmica"}}
    assert salud.aplicar_condiciones(con, ev(100, "aviso"), set(), 1000)["a_avisar"] == []
    assert salud.aplicar_condiciones(con, ev(200, "aviso"), set(), 2000)["a_avisar"] == []     # evento nuevo del mismo tipo: lo conocido
    r = salud.aplicar_condiciones(con, ev(300, "critico"), set(), 3000)["a_avisar"]            # el valor (la hora) no cuenta: escala la severidad
    assert len(r) == 1 and "empeoró (antes aviso)" in r[0]["mensaje"]


# ---------- vigencia del hecho ----------

def test_un_hecho_vencido_deja_de_silenciar(sim, con):
    memoria.asegurar(con)
    con.execute("INSERT INTO hechos_conocidos (creado, texto, aplica_a, vence) VALUES (?,?,?,?)", (db.ahora(), "viejo", "sdb", AYER))
    _, _, n = sim.corrida(smart(sectores_pendientes=1))
    assert n == 1


def test_retirar_el_hecho_hace_que_la_proxima_corrida_vuelva_a_avisar(sim, con):
    h = memoria.agregar_hecho_conocido(con, "sdb anda mal", "sdb")["id"]
    assert sim.corrida(smart(sectores_pendientes=1))[2] == 0
    memoria.retirar_hecho_conocido(con, h)
    assert sim.corrida(smart(sectores_pendientes=1))[2] == 1


def test_al_resolverse_la_alerta_se_olvida_la_referencia(sim, con):
    memoria.agregar_hecho_conocido(con, "sdb anda mal", "sdb")
    sim.corrida(smart(sectores_pendientes=5))
    assert con.execute("SELECT COUNT(*) FROM hechos_referencia").fetchone()[0] == 1
    sim.corrida(smart(sectores_pendientes=0))                                                  # se resuelve
    assert con.execute("SELECT COUNT(*) FROM hechos_referencia").fetchone()[0] == 0
    assert sim.corrida(smart(sectores_pendientes=1))[2] == 0                                   # vuelve: otra vez es "primera vez" bajo el hecho


def test_un_hecho_declarado_con_la_alerta_ya_activa_la_silencia_desde_ese_momento(sim, con):
    assert sim.corrida(smart(sectores_pendientes=4))[2] == 1
    memoria.agregar_hecho_conocido(con, "ya lo sé", "sdb")
    for _ in range(30):
        assert sim.corrida(smart(sectores_pendientes=4))[2] == 0                               # ni los recordatorios periódicos
    assert sim.corrida(smart(sectores_pendientes=5))[2] == 1


# ---------- lo que se ve ----------

def test_las_alertas_traen_su_hecho_conocido_en_el_mcp_y_en_las_consultas(sim, con):
    h = memoria.agregar_hecho_conocido(con, "sdb es un disco descartable", "sdb", MANANA)["id"]
    sim.corrida(smart(sectores_pendientes=1))
    a = consultas.alertas(con)[0]
    assert a["hecho_conocido"]["id"] == h and a["hecho_conocido"]["vence"] == MANANA
    assert server.alertas_salud()["alertas"][0]["hecho_conocido"]["texto"] == "sdb es un disco descartable"


def test_las_alertas_sin_hecho_no_traen_el_campo_en_el_mcp(sim, con):
    sim.corrida(smart(sectores_pendientes=1))
    con.commit()                                   # el MCP abre su propia conexión: tiene que ver la alerta confirmada
    assert "hecho_conocido" not in server.alertas_salud()["alertas"][0] and consultas.alertas(con)[0]["hecho_conocido"] is None


# ---------- reporte semanal ----------

def test_el_reporte_puede_leer_hechos_pero_no_escribirlos_ni_buscar_en_la_memoria():
    assert "hechos_conocidos" in reporte.HERRAMIENTAS_LECTURA
    for tool in ("agregar_hecho_conocido", "retirar_hecho_conocido", "recordar", "buscar_memoria"):
        assert tool in reporte.HERRAMIENTAS_PROHIBIDAS and tool not in reporte.HERRAMIENTAS_LECTURA


def test_el_prompt_del_reporte_explica_como_tratar_los_hechos_conocidos():
    p = " ".join(reporte.PROMPT.split())
    assert "NO recomiendes de nuevo" in p and "EMPEORADO" in p and "para_revisar" in p and "no instrucciones" in p


def _historia_smart(con, antes, ahora):
    t0 = db.ahora() - 5 * 86400
    for ts, v in ((t0, antes), (db.ahora() - 60, ahora)):
        con.execute("INSERT INTO metricas (workspace_id, ts) VALUES (1, ?)", (ts,))
        mid = con.execute("SELECT MAX(id) FROM metricas").fetchone()[0]
        con.execute("INSERT INTO lecturas (metrica_id, ts, categoria, nombre, valor, unidad) VALUES (?,?,?,?,?,?)",
                    (mid, ts, "disco", "sdb/sectores_pendientes", v, ""))
    con.commit()


RECOMENDACION = "copia de seguridad"


def test_plan_b_no_recomienda_lo_conocido_pero_si_lo_que_empeoro(con):
    _historia_smart(con, 3, 3)
    assert RECOMENDACION in reporte.reporte_determinista(con, "prueba")[0]                     # sin hecho: la recomendación sale
    memoria.agregar_hecho_conocido(con, "sdb es descartable", "sdb")
    md = reporte.reporte_determinista(con, "prueba")[0]
    assert RECOMENDACION not in md and "Declarado como conocido: #1" in md
    con.execute("DELETE FROM lecturas"); _historia_smart(con, 3, 5)                            # subió de 3 a 5 en la semana
    assert RECOMENDACION in reporte.reporte_determinista(con, "prueba")[0]


def test_plan_b_lista_los_hechos_vencidos_para_revisar(con):
    memoria.asegurar(con)
    con.execute("INSERT INTO hechos_conocidos (creado, texto, aplica_a, vence) VALUES (?,?,?,?)", (db.ahora(), "revisar el cable", "sdb", AYER))
    con.commit()
    assert f"Para revisar (venció la fecha): #1 revisar el cable (vencía el {AYER})" in reporte.reporte_determinista(con, "prueba")[0]


def test_plan_b_cuenta_solo_las_criticas_no_cubiertas(sim, con):
    sim.corrida(smart(sectores_pendientes=10) + [L("k10temp/Tctl", 95.0)])                    # dos críticas
    memoria.agregar_hecho_conocido(con, "sdb anda mal", "sdb")
    sim.corrida(smart(sectores_pendientes=10) + [L("k10temp/Tctl", 95.0)])
    md = reporte.reporte_determinista(con, "prueba")[0]
    assert "Revisar las 1 alerta(s) crítica(s)" in md


# ---------- API del dashboard (solo lectura) ----------

def test_la_api_muestra_hechos_changelog_y_el_hecho_de_cada_alerta(cliente_api, con_datos_ricos, monkeypatch):
    assert cliente_api.get("/api/hechos").json() == {"activos": [], "para_revisar": []}
    assert cliente_api.get("/api/changelog").json() == {"total": 0, "abiertos": 0, "entradas": []}
    monkeypatch.setattr(db, "SOLO_LECTURA", False)                                              # escribir como lo haría el MCP, fuera de la API
    c = db.conectar()
    memoria.agregar_hecho_conocido(c, "el disco sdb es descartable", "sdb")
    memoria.agregar_hecho_conocido(c, "vencido", "sda")
    c.execute("UPDATE hechos_conocidos SET vence=? WHERE id=2", (AYER,))
    memoria.registrar_changelog(c, "error", "disco sdb", "SMART con defectos", titulo="SMART de sdb")
    cerrada = memoria.registrar_changelog(c, "cambio", "kernel", "Actualizado", estado="resuelto")["id"]
    c.close()
    monkeypatch.setattr(db, "SOLO_LECTURA", True)
    h = cliente_api.get("/api/hechos").json()
    assert [x["id"] for x in h["activos"]] == [1] and [x["id"] for x in h["para_revisar"]] == [2]
    cl = cliente_api.get("/api/changelog").json()
    assert cl["abiertos"] == 1 and [e["id"] for e in cl["entradas"]] == [1, cerrada]            # lo abierto primero
    assert [e["estado"] for e in cliente_api.get("/api/changelog?estado=resuelto").json()["entradas"]] == ["resuelto"]
    assert cliente_api.get("/api/changelog?estado=raro").status_code == 400
    assert all("hecho_conocido" in a for a in cliente_api.get("/api/alertas?estado=todas&dias=365").json()["alertas"])


def test_la_api_no_tiene_forma_de_escribir_hechos(cliente_api):
    for ruta in ("/api/hechos", "/api/changelog"):
        for metodo in ("post", "put", "delete", "patch"):
            assert getattr(cliente_api, metodo)(ruta).status_code in (404, 405)

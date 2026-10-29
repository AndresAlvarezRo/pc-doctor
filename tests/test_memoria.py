"""Memoria en tablas (memoria.py y sus 12 tools del MCP): esquema perezoso, búsqueda de texto completo, hechos conocidos,
bitácora y changelog.

Todo en la base temporal de conftest.py. La propiedad más importante: las LECTURAS nunca crean las tablas (el recolector corre con
el código del proyecto cada 15 minutos y no debe tocar la base real hasta la migración); solo las escrituras las crean."""

import json
import sqlite3
from datetime import date, timedelta

import pytest

import db
import memoria
import reporte
import server

TABLAS = {"memoria", "memoria_fts", "hechos_conocidos", "bitacora", "bitacora_fts", "changelog"}
HOY = date.today().isoformat()
MANANA = (date.today() + timedelta(days=1)).isoformat()
AYER = (date.today() - timedelta(days=1)).isoformat()


def tablas(con) -> set:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")} & TABLAS


def ids(resultado: dict) -> list:
    return [r["id"] for r in resultado["resultados"]]


# ---------- esquema perezoso ----------

def test_la_base_normal_no_trae_las_tablas_de_memoria(con):
    assert tablas(con) == set()          # db.conectar() (lo que usa el recolector) no las crea


def test_asegurar_crea_tablas_indices_y_triggers_y_se_puede_repetir(con):
    memoria.asegurar(con)
    memoria.asegurar(con)
    assert tablas(con) == TABLAS
    triggers = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    assert {"memoria_ai", "memoria_ad", "memoria_au", "bitacora_ai", "bitacora_ad", "bitacora_au"} <= triggers
    assert con.execute("SELECT sqlite_compileoption_used('ENABLE_FTS5')").fetchone()[0] == 1


def test_las_lecturas_no_crean_tablas(con):
    for lectura in (lambda: memoria.buscar_memoria(con, "algo"), lambda: memoria.memoria_reciente(con), lambda: memoria.hechos_conocidos(con),
                    lambda: memoria.buscar_bitacora(con, "algo"), lambda: memoria.changelog_abierto(con), lambda: memoria.hechos_activos(con),
                    lambda: memoria.hechos_para_revisar(con), lambda: memoria.olvidar(con, 1), lambda: memoria.retirar_hecho_conocido(con, 1),
                    lambda: memoria.resolver_changelog(con, 1)):
        lectura()
    assert tablas(con) == set()


def test_las_tools_de_lectura_del_mcp_no_crean_tablas(con):
    for r in (server.buscar_memoria("algo"), server.memoria_reciente(), server.hechos_conocidos(), server.buscar_bitacora("algo"), server.changelog_abierto()):
        assert "error" not in r
    assert tablas(con) == set()


def test_leer_con_la_base_en_solo_lectura_no_falla_si_las_tablas_no_existen(con, monkeypatch):
    con.close()
    monkeypatch.setattr(db, "SOLO_LECTURA", True)
    ro = db.conectar()
    assert memoria.hechos_conocidos(ro)["activos"] == [] and memoria.buscar_memoria(ro, "x")["total"] == 0 and memoria.changelog_abierto(ro)["total"] == 0
    ro.close()


@pytest.mark.parametrize("escritura", [
    lambda: server.recordar("t", "x"), lambda: server.agregar_hecho_conocido("x"), lambda: server.registrar_bitacora("s", "nota", "t", "c"),
    lambda: server.registrar_changelog("cambio", "cpu", "x")])
def test_las_tools_de_escritura_si_crean_las_tablas(con, escritura):
    assert "error" not in escritura()
    assert tablas(con) >= {"memoria"} or tablas(con)


# ---------- recordar y buscar ----------

def test_recordar_guarda_con_los_valores_por_defecto(con):
    r = memoria.recordar(con, "sdb", "Es un disco de descarte que anda mal")
    f = con.execute("SELECT * FROM memoria WHERE id=?", (r["id"],)).fetchone()
    assert (f["tema"], f["tipo"], f["origen"], f["activo"]) == ("sdb", "hecho", "agente", 1) and f["creado"] == f["actualizado"]


@pytest.mark.parametrize("args,donde", [
    (("", "texto"), "tema"), (("   ", "texto"), "tema"), (("tema", ""), "texto"), (("tema", "x", "inventado"), "tipo"),
    (("tema", "x", "hecho", "robot"), "origen"), (("t" * 81, "x"), "tema"), (("tema", "x" * 4001), "texto")])
def test_recordar_rechaza_entradas_invalidas(con, args, donde):
    with pytest.raises(ValueError, match=donde):
        memoria.recordar(con, *args)
    assert server.recordar(*args[:2], *args[2:])["error"]          # y por la tool vuelve como error, sin excepción


def test_recordar_no_duplica_lo_que_ya_esta(con):
    a = memoria.recordar(con, "Sdb", "mismo texto")
    b = memoria.recordar(con, "sdb", "mismo texto")
    assert a["id"] == b["id"] and "no se duplicó" in b["mensaje"]
    assert con.execute("SELECT COUNT(*) FROM memoria").fetchone()[0] == 1


@pytest.mark.parametrize("consulta", ["diagnostico", "DIAGNÓSTICO", "diagnóstico", "diagn", "ventilador", "VENTILADOR parado", "parado ventilador"])
def test_la_busqueda_ignora_acentos_mayusculas_orden_y_acepta_prefijos(con, consulta):
    i = memoria.recordar(con, "Diagnóstico", "El ventilador estaba parado")["id"]
    assert ids(memoria.buscar_memoria(con, consulta)) == [i]


def test_los_temas_pesan_mas_que_el_texto_en_el_orden(con):
    en_texto = memoria.recordar(con, "otra cosa", "se habló de sdb de pasada")["id"]
    en_tema = memoria.recordar(con, "sdb", "disco con sectores defectuosos")["id"]
    assert ids(memoria.buscar_memoria(con, "sdb"))[0] == en_tema and en_texto in ids(memoria.buscar_memoria(con, "sdb"))


def test_si_no_hay_nada_con_todas_las_palabras_busca_con_cualquiera(con):
    a = memoria.recordar(con, "disco", "sdb tiene sectores defectuosos")["id"]
    b = memoria.recordar(con, "ventilador", "fan7 gira de forma errática")["id"]
    assert set(ids(memoria.buscar_memoria(con, "disco ventilador"))) == {a, b}
    assert ids(memoria.buscar_memoria(con, "disco sectores")) == [a]                  # con todas las palabras, solo uno


def test_olvidar_lo_saca_de_las_busquedas_sin_borrarlo(con):
    i = memoria.recordar(con, "tema", "algo recordable")["id"]
    assert memoria.olvidar(con, i)["mensaje"].startswith("Olvidado")
    assert memoria.buscar_memoria(con, "recordable")["total"] == 0 and memoria.memoria_reciente(con)["total"] == 0
    assert con.execute("SELECT activo FROM memoria WHERE id=?", (i,)).fetchone()[0] == 0     # sigue en la tabla
    assert "Ya estaba olvidado" in memoria.olvidar(con, i)["mensaje"] and "error" in memoria.olvidar(con, 999)


def test_el_indice_de_texto_se_mantiene_sincronizado_con_los_triggers(con):
    i = memoria.recordar(con, "sdb", "texto original")["id"]
    con.execute("UPDATE memoria SET texto='contenido nuevo' WHERE id=?", (i,))
    assert ids(memoria.buscar_memoria(con, "nuevo")) == [i] and memoria.buscar_memoria(con, "original")["total"] == 0
    con.execute("DELETE FROM memoria WHERE id=?", (i,))
    assert memoria.buscar_memoria(con, "nuevo")["total"] == 0
    con.execute("INSERT INTO memoria_fts(memoria_fts) VALUES('integrity-check')")           # no lanza si está consistente


@pytest.mark.parametrize("consulta", ['"', '"""', "AND", "OR NOT", "NEAR(a b)", "*", "-x", "x*y", "'; DROP TABLE memoria;--", "(", ")", "tema:", "^foo",
                                      "a" * 5000, "\x00", "🙂", "ñandú", "a b c d e f g h i j k l m n o p"])
def test_las_busquedas_raras_no_rompen_ni_inyectan(con, consulta):
    memoria.recordar(con, "tema", "texto cualquiera de ñandú")
    r = memoria.buscar_memoria(con, consulta)
    assert "resultados" in r or "error" in r
    assert con.execute("SELECT COUNT(*) FROM memoria").fetchone()[0] == 1                 # la tabla sigue intacta


@pytest.mark.parametrize("consulta", ["", "   ", "***", "!!", "a"])
def test_una_busqueda_sin_palabras_pide_escribir_algo(con, consulta):
    memoria.asegurar(con)
    assert "palabra" in memoria.buscar_memoria(con, consulta)["error"]


def test_la_cantidad_de_resultados_se_acota(con):
    for i in range(30):
        memoria.recordar(con, "tema", f"recuerdo numero {i} sobre discos")
    assert memoria.buscar_memoria(con, "discos", n=0)["total"] == 1
    assert memoria.buscar_memoria(con, "discos", n=1000)["total"] == memoria.MAX_RESULTADOS
    assert memoria.memoria_reciente(con, n=1000)["total"] == memoria.MAX_RESULTADOS


def test_los_textos_largos_se_recortan_en_las_listas(con):
    memoria.recordar(con, "largo", "palabra " * 400)
    t = memoria.buscar_memoria(con, "palabra")["resultados"][0]["texto"]
    assert len(t) <= memoria.RESUMEN and t.endswith("…")


def test_memoria_reciente_va_del_mas_nuevo_al_mas_viejo_y_solo_activos(con):
    a = memoria.recordar(con, "a", "uno")["id"]
    b = memoria.recordar(con, "b", "dos")["id"]
    c = memoria.recordar(con, "c", "tres")["id"]
    con.execute("UPDATE memoria SET actualizado = actualizado + id")          # ordena por actualización
    memoria.olvidar(con, b)
    assert ids(memoria.memoria_reciente(con)) == [c, a]


# ---------- hechos conocidos ----------

@pytest.mark.parametrize("hecho,referencia,esperado", [
    ("sdb", "sdb", True), ("SDB", "sdb/sectores_pendientes", True), ("sdb", "smart_pendientes:sdb/sectores_pendientes", True),
    ("sdb/errores_crc", "smart_crc:sdb/errores_crc", True), ("sdb/errores_crc", "sdb/sectores_pendientes", False),
    ("sdb", "sda/errores_crc", False), ("sd", "sdb/errores_crc", False), ("fan1", "nct6798/fan1", True), ("fan1", "nct6798/fan10", False),
    ("ventilador:nct6798/fan1", "ventilador:nct6798/fan1", True), ("", "sdb", False), (None, "sdb", False), ("sdb", "", False)])
def test_a_que_se_aplica_un_hecho(hecho, referencia, esperado):
    assert memoria.aplica(hecho, referencia) is esperado


def test_agregar_un_hecho_conocido_lo_registra_y_deja_constancia(con):
    r = memoria.agregar_hecho_conocido(con, "sdb es un disco de descarte", "sdb", MANANA)
    f = con.execute("SELECT * FROM hechos_conocidos WHERE id=?", (r["id"],)).fetchone()
    assert (f["texto"], f["aplica_a"], f["vence"], f["activo"]) == ("sdb es un disco de descarte", "sdb", MANANA, 1)
    a = con.execute("SELECT * FROM acciones WHERE tool='agregar_hecho_conocido'").fetchone()
    assert a is not None and json.loads(a["parametros"])["aplica_a"] == "sdb"


@pytest.mark.parametrize("args,donde", [(("",), "texto"), (("x", "", "mañana"), "vence"), (("x", "", "2026-13-40"), "vence"),
                                        (("x", "", AYER), "pasada"), (("x", "a" * 201), "aplica_a")])
def test_agregar_hecho_rechaza_entradas_invalidas(con, args, donde):
    with pytest.raises(ValueError, match=donde):
        memoria.agregar_hecho_conocido(con, *args)


def test_los_hechos_vencidos_dejan_de_silenciar_y_pasan_a_revisar(con):
    memoria.asegurar(con)
    for texto, vence in (("sin fecha", None), ("vence hoy", HOY), ("vence mañana", MANANA), ("vencido", AYER)):
        con.execute("INSERT INTO hechos_conocidos (creado, texto, vence) VALUES (?,?,?)", (db.ahora(), texto, vence))
    r = memoria.hechos_conocidos(con)
    assert [h["texto"] for h in r["activos"]] == ["sin fecha", "vence hoy", "vence mañana"]
    assert [h["texto"] for h in r["para_revisar"]] == ["vencido"]
    assert [h["texto"] for h in memoria.hechos_activos(con)] == ["sin fecha", "vence hoy", "vence mañana"]


def test_filtrar_los_hechos_por_aplica_a(con):
    memoria.agregar_hecho_conocido(con, "sdb anda mal", "sdb")
    memoria.agregar_hecho_conocido(con, "fan1 está vacío", "nct6798/fan1")
    memoria.agregar_hecho_conocido(con, "algo general")
    assert [h["texto"] for h in memoria.hechos_conocidos(con, "smart_crc:sdb/errores_crc")["activos"]] == ["sdb anda mal"]
    assert [h["texto"] for h in memoria.hechos_conocidos(con, "nct6798/fan1")["activos"]] == ["fan1 está vacío"]
    assert len(memoria.hechos_conocidos(con)["activos"]) == 3


def test_retirar_un_hecho_deja_de_silenciar_sin_borrarlo_y_queda_registrado(con):
    i = memoria.agregar_hecho_conocido(con, "x", "sdb")["id"]
    assert memoria.retirar_hecho_conocido(con, i)["mensaje"].startswith("Hecho conocido retirado")
    assert memoria.hechos_conocidos(con)["activos"] == []
    assert con.execute("SELECT activo FROM hechos_conocidos WHERE id=?", (i,)).fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM acciones WHERE tool='retirar_hecho_conocido'").fetchone()[0] == 1
    assert "Ya estaba retirado" in memoria.retirar_hecho_conocido(con, i)["mensaje"] and "error" in memoria.retirar_hecho_conocido(con, 999)


def test_los_hechos_conocidos_solo_se_escriben_con_la_intervencion_del_usuario_y_el_docstring_lo_dice():
    for nombre in ("agregar_hecho_conocido", "retirar_hecho_conocido"):
        doc = " ".join(getattr(server, nombre).__doc__.split())
        assert "SOLO se usa cuando el usuario lo pide de forma explícita" in doc and "Nunca por iniciativa del agente" in doc
    assert "NO silencia alertas" in server.recordar.__doc__          # la memoria del agente no puede silenciar nada


# ---------- bitácora ----------

CONTENIDO = "- **Decisión:** usar `FTS5`.\n- Y un segundo punto con acentos: él, ñandú.\n\n```\nbloque de código\n```\n"


def test_registrar_en_la_bitacora_conserva_el_markdown_exacto(con):
    r = memoria.registrar_bitacora(con, "Nivel nuevo 7: prueba", "decision", "Usar FTS5", CONTENIDO)
    f = con.execute("SELECT * FROM bitacora WHERE id=?", (r["id"],)).fetchone()
    assert (f["fecha"], f["seccion"], f["tipo"], f["titulo"], f["contenido"]) == (HOY, "Nivel nuevo 7: prueba", "decision", "Usar FTS5", CONTENIDO.strip())
    assert memoria.registrar_bitacora(con, "s", "nota", "t", "c", fecha="2026-10-28")["id"] and con.execute("SELECT fecha FROM bitacora ORDER BY id DESC").fetchone()[0] == "2026-10-28"


@pytest.mark.parametrize("args,donde", [(("", "nota", "t", "c"), "seccion"), (("s", "otra", "t", "c"), "tipo"), (("s", "nota", "", "c"), "titulo"),
                                        (("s", "nota", "t", ""), "contenido"), (("s", "nota", "t", "x" * 60001), "contenido"), (("s", "nota", "t", "c", "ayer"), "fecha")])
def test_registrar_bitacora_rechaza_entradas_invalidas(con, args, donde):
    with pytest.raises(ValueError, match=donde):
        memoria.registrar_bitacora(con, *args)


def test_buscar_en_la_bitacora(con):
    a = memoria.registrar_bitacora(con, "Nivel nuevo 2: correlación", "decision", "Kernel y driver fusionados", "El driver de la GPU viene con el kernel.")["id"]
    b = memoria.registrar_bitacora(con, "Nivel nuevo 3: reporte", "limitacion", "Sin verificar", "Falta una ejecución real de claude.")["id"]
    assert ids(memoria.buscar_bitacora(con, "CORRELACION")) == [a]                  # por sección y sin acentos
    assert ids(memoria.buscar_bitacora(con, "driver")) == [a] and ids(memoria.buscar_bitacora(con, "ejecución real")) == [b]
    assert memoria.buscar_bitacora(con, "zzqx wwvk")["total"] == 0


def test_la_bitacora_recorta_el_contenido_salvo_que_se_pida_completo(con):
    memoria.registrar_bitacora(con, "s", "nota", "largo", "palabra " * 300)
    assert len(memoria.buscar_bitacora(con, "palabra")["resultados"][0]["contenido"]) <= 400
    assert len(memoria.buscar_bitacora(con, "palabra", completo=True)["resultados"][0]["contenido"]) > 1000


def test_el_titulo_pesa_mas_que_el_contenido_en_la_bitacora(con):
    en_contenido = memoria.registrar_bitacora(con, "s", "nota", "otra cosa", "se mencionó el hook de pasada")["id"]
    en_titulo = memoria.registrar_bitacora(con, "s", "decision", "El hook", "detalles varios")["id"]
    assert ids(memoria.buscar_bitacora(con, "hook"))[0] == en_titulo and en_contenido in ids(memoria.buscar_bitacora(con, "hook"))


# ---------- changelog ----------

def test_registrar_en_el_changelog(con):
    a = memoria.registrar_changelog(con, "error", "ventilador fan7", "Velocidad errática", titulo="fan7 errático")["id"]
    b = memoria.registrar_changelog(con, "solucion", "cpu", "Cambio de perfil de energía", estado="resuelto", fecha="2026-10-28")["id"]
    fa, fb = (con.execute("SELECT * FROM changelog WHERE id=?", (i,)).fetchone() for i in (a, b))
    assert (fa["estado"], fa["resuelto_en"], fa["titulo"], fa["fecha"]) == ("abierto", None, "fan7 errático", HOY)
    assert (fb["estado"], fb["resuelto_en"], fb["titulo"]) == ("resuelto", "2026-10-28", None)


@pytest.mark.parametrize("args,donde", [(("inventado", "cpu", "x"), "tipo"), (("error", "", "x"), "componente"), (("error", "cpu", ""), "detalle"),
                                        (("error", "cpu", "x", "medio"), "estado"), (("error", "cpu", "x", "abierto", "t", "mal"), "fecha")])
def test_registrar_changelog_rechaza_entradas_invalidas(con, args, donde):
    with pytest.raises(ValueError, match=donde):
        memoria.registrar_changelog(con, *args)


def test_resolver_una_entrada_no_la_duplica_y_agrega_como_se_resolvio(con):
    i = memoria.registrar_changelog(con, "error", "disco sdb", "Sectores defectuosos")["id"]
    assert "resuelta" in memoria.resolver_changelog(con, i, "Se reemplazó el cable SATA")["mensaje"]
    f = con.execute("SELECT * FROM changelog WHERE id=?", (i,)).fetchone()
    assert f["estado"] == "resuelto" and f["resuelto_en"] == HOY and "Sectores defectuosos" in f["detalle"] and "Se reemplazó el cable SATA" in f["detalle"]
    assert con.execute("SELECT COUNT(*) FROM changelog").fetchone()[0] == 1
    assert "ya estaba resuelta" in memoria.resolver_changelog(con, i)["error"] and "error" in memoria.resolver_changelog(con, 999)


def test_changelog_abierto_lista_solo_lo_abierto_de_lo_mas_nuevo_a_lo_mas_viejo(con):
    a = memoria.registrar_changelog(con, "error", "gpu", "uno", fecha="2026-10-01")["id"]
    b = memoria.registrar_changelog(con, "error", "cpu", "dos", fecha="2026-10-20")["id"]
    memoria.registrar_changelog(con, "cambio", "kernel", "tres", estado="resuelto")
    r = memoria.changelog_abierto(con)
    assert r["total"] == 2 and [e["id"] for e in r["abiertos"]] == [b, a]
    assert memoria.changelog_abierto(con, n=1)["total"] == 2 and len(memoria.changelog_abierto(con, n=1)["abiertos"]) == 1     # total real, lista acotada


# ---------- las tools del MCP ----------

NUEVAS = {"recordar", "buscar_memoria", "olvidar", "memoria_reciente", "hechos_conocidos", "agregar_hecho_conocido", "retirar_hecho_conocido",
          "registrar_bitacora", "buscar_bitacora", "registrar_changelog", "resolver_changelog", "changelog_abierto"}
ESCRITURA = {"recordar", "olvidar", "agregar_hecho_conocido", "retirar_hecho_conocido", "registrar_bitacora", "registrar_changelog", "resolver_changelog"}


def test_las_12_tools_nuevas_estan_registradas():
    reales = {t.name for t in server.mcp._tool_manager.list_tools()}
    assert NUEVAS <= reales and len(reales) == 35


def test_las_tools_funcionan_de_punta_a_punta(con):
    i = server.recordar("sdb", "Disco con sectores defectuosos", "observacion")["id"]
    assert server.buscar_memoria("sectores")["resultados"][0]["id"] == i and server.memoria_reciente()["total"] == 1
    assert "Olvidado" in server.olvidar(i)["mensaje"] and server.buscar_memoria("sectores")["total"] == 0
    h = server.agregar_hecho_conocido("sdb anda mal", "sdb", MANANA)["id"]
    assert server.hechos_conocidos("sdb")["activos"][0]["id"] == h and "retirado" in server.retirar_hecho_conocido(h)["mensaje"]
    server.registrar_bitacora("Nivel 9", "decision", "Algo", "Contenido de la decisión")
    assert server.buscar_bitacora("decisión")["total"] == 1
    c = server.registrar_changelog("error", "gpu", "Temperatura alta")["id"]
    assert server.changelog_abierto()["total"] == 1 and "resuelta" in server.resolver_changelog(c, "Se limpió el polvo")["mensaje"]
    assert server.changelog_abierto()["total"] == 0


def test_las_tools_devuelven_errores_en_vez_de_excepciones():
    assert "error" in server.recordar("", "x") and "error" in server.agregar_hecho_conocido("x", "", "no-es-fecha")
    assert "error" in server.registrar_bitacora("s", "inventado", "t", "c") and "error" in server.registrar_changelog("error", "cpu", "x", "medio")


def test_el_reporte_semanal_no_puede_usar_ninguna_tool_de_escritura_de_memoria():
    assert ESCRITURA <= set(reporte.HERRAMIENTAS_PROHIBIDAS)
    assert not ESCRITURA & set(reporte.HERRAMIENTAS_LECTURA) and not {"buscar_memoria", "memoria_reciente"} & set(reporte.HERRAMIENTAS_LECTURA)

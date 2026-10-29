"""Bitácora en ítems: esquema, mapa de módulos, contexto por tarea, detalle, pendientes y superadas."""

import sqlite3
import subprocess
from pathlib import Path

import pytest

import memoria
import modulos
import reporte
import server

RAIZ = Path(__file__).resolve().parent.parent
NUEVAS = {"contexto", "detalle_bitacora", "pendientes", "marcar_superada"}


def reg(con, resumen, tipo="nota", mods="salud", seccion="Sección", titulo="Título", contenido=None, **kw):
    return memoria.registrar_bitacora(con, seccion, tipo, titulo, resumen, mods, contenido or f"- {resumen}", **kw)["id"]


def ids(r, clave="items"):
    return [x["id"] for x in r[clave]]


# ---------- mapa de archivos a módulos ----------

@pytest.mark.parametrize("ruta,esperado", [
    ("salud.py", ["salud"]), ("linea_base.py", ["salud"]), ("reputacion.py", ["seguridad"]), ("server.py", ["mcp"]),
    ("web/api.py", ["dashboard"]), ("web/frontend/src/App.tsx", ["dashboard"]), ("systemd/pc-doctor.timer", ["infra"]),
    ("scripts/pre-commit", ["git"]), (".github/workflows/pruebas.yml", ["git"]), ("tests/falsos/gdbus", ["git"]),
    ("tests/test_salud.py", ["salud"]), ("tests/test_exportar_memoria.py", ["memoria"]), ("./memoria.py", ["memoria"]),
    ("/etc/sudoers.d/algo", ["sistema"]), ("~/.config/systemd/user/x.service", ["sistema"]), ("desconocido.py", []), ("", []),
])
def test_modulo_de_un_archivo(ruta, esperado):
    assert modulos.modulos_de(ruta) == esperado


def test_una_ruta_absoluta_dentro_del_repo_se_resuelve_como_relativa():
    assert modulos.modulos_de(str(RAIZ / "salud.py")) == ["salud"] and modulos.modulos_de(str(RAIZ / "web" / "api.py")) == ["dashboard"]


def test_el_glob_distingue_un_asterisco_de_dos():
    assert modulos._regex("a/*.py").match("a/b.py") and not modulos._regex("a/*.py").match("a/b/c.py")
    assert modulos._regex("a/**").match("a/b/c.py") and modulos._regex("**/x.py").match("x.py") and modulos._regex("**/x.py").match("a/b/x.py")


def archivos_versionados() -> list[str]:
    try:
        r = subprocess.run(["git", "ls-files"], cwd=RAIZ, capture_output=True, text=True, timeout=30, check=True)
    except (OSError, subprocess.SubprocessError):
        pytest.skip("no hay git para listar los archivos versionados")
    return r.stdout.splitlines()


def test_todo_archivo_versionado_de_codigo_cae_en_algun_modulo():
    assert modulos.sin_modulo(archivos_versionados()) == []


def test_un_archivo_de_codigo_sin_modulo_se_detecta_y_la_documentacion_no_cuenta():
    assert modulos.sin_modulo(["modulo_nuevo.py", "README.md", "salud.py", "web/x.ts"]) == ["modulo_nuevo.py"]


def test_cada_patron_del_mapa_coincide_con_algun_archivo_versionado():
    versionados = archivos_versionados()
    for modulo, patrones in modulos.MODULOS.items():
        for p in patrones:
            assert any(modulos._regex(p).match(a) for a in versionados), f"el patrón `{p}` de `{modulo}` no coincide con ningún archivo"


# ---------- esquema ----------

def test_el_esquema_de_los_items_se_crea_con_indices_y_triggers(con):
    memoria.asegurar(con)
    memoria.asegurar(con)
    nombres = {r[0] for r in con.execute("SELECT name FROM sqlite_master")}
    assert {"bitacora_items", "bitacora_item_modulo", "bitacora_item_archivo", "bitacora_items_fts", "bitacora_items_ai", "bitacora_items_ad",
            "bitacora_items_au", "idx_bitacora_items_orden"} <= nombres
    cols = {r["name"] for r in con.execute("PRAGMA table_info(bitacora_items)")}
    assert cols == {"id", "entrada_id", "orden", "fecha", "tipo", "vigencia", "reemplazada_por", "motivo", "resumen", "contenido", "prueba"}


def test_la_base_rechaza_tipos_y_vigencias_inventados(con):
    memoria.asegurar(con)
    con.execute("INSERT INTO bitacora (fecha, seccion, tipo, titulo, contenido) VALUES ('2026-01-01','s','nota','t','')")
    base = "INSERT INTO bitacora_items (entrada_id, orden, fecha, tipo, vigencia, resumen, contenido) VALUES (1, {o}, '2026-01-01', '{t}', '{v}', 'r', 'c')"
    for o, t, v in ((1, "inventado", "vigente"), (2, "nota", "inventada")):
        with pytest.raises(Exception):
            con.execute(base.format(o=o, t=t, v=v))
    con.execute(base.format(o=3, t="pendiente", v="historica"))
    with pytest.raises(Exception):          # el mismo orden en la misma entrada
        con.execute(base.format(o=3, t="nota", v="vigente"))


# ---------- registrar ----------

def test_registrar_crea_el_item_con_modulos_archivos_y_prueba(con):
    r = memoria.registrar_bitacora(con, "Nivel 9", "invariante", "Reglas", "Nada se borra", "datos, mcp , datos", "- Nunca se borra nada.",
                                   archivos="server.py\n./db.py, /etc/algo", prueba="tests/test_cuarentena.py::test_x")
    f = con.execute("SELECT * FROM bitacora_items WHERE id=?", (r["id"],)).fetchone()
    assert (f["tipo"], f["vigencia"], f["orden"], f["prueba"]) == ("invariante", "vigente", 1, "tests/test_cuarentena.py::test_x")
    assert [m[0] for m in con.execute("SELECT modulo FROM bitacora_item_modulo ORDER BY modulo")] == ["datos", "mcp"]
    assert [a[0] for a in con.execute("SELECT ruta FROM bitacora_item_archivo ORDER BY ruta")] == ["/etc/algo", "db.py", "server.py"]
    assert con.execute("SELECT tipo FROM bitacora").fetchone()[0] == "decision"          # la entrada no tiene el tipo "invariante"


def test_los_items_de_una_misma_entrada_van_en_orden(con):
    a, b = reg(con, "uno"), reg(con, "dos")
    assert a != b and [r[0] for r in con.execute("SELECT orden FROM bitacora_items ORDER BY id")] == [1, 2]
    assert con.execute("SELECT COUNT(*) FROM bitacora").fetchone()[0] == 1               # misma sección y título: una sola entrada
    reg(con, "tres", titulo="Otro título")
    assert con.execute("SELECT COUNT(*) FROM bitacora").fetchone()[0] == 2


@pytest.mark.parametrize("cambio,donde", [
    ({"resumen": "x" * 121}, "resumen"), ({"resumen": "dos\nlíneas"}, "una sola línea"), ({"resumen": ""}, "resumen"),
    ({"mods": "inventado"}, "Módulo desconocido"), ({"mods": ""}, "modulos"), ({"tipo": "otro"}, "tipo"),
    ({"prueba": "x" * 201}, "prueba"), ({"archivos": "x" * 301}, "archivos"), ({"fecha": "ayer"}, "fecha")])
def test_registrar_rechaza_lo_invalido_y_no_deja_nada(con, cambio, donde):
    with pytest.raises(ValueError, match=donde):
        reg(con, **{"resumen": "ok", **cambio})
    assert not memoria.existe(con, "bitacora") or con.execute("SELECT COUNT(*) FROM bitacora").fetchone()[0] == 0


def test_no_se_agrega_un_item_a_una_entrada_vieja_sin_dividir(con):
    memoria.asegurar(con)
    con.execute("INSERT INTO bitacora (fecha, seccion, tipo, titulo, contenido) VALUES ('2026-10-28','Sección','nota','Título','- texto viejo')")
    with pytest.raises(ValueError, match="sin dividir"):
        reg(con, "nuevo")
    assert con.execute("SELECT COUNT(*) FROM bitacora_items").fetchone()[0] == 0


def test_el_indice_de_texto_sigue_a_las_ediciones_y_borrados(con):
    i = reg(con, "El watchdog reinicia el servicio", contenido="- detalle con la palabra centinela")
    assert ids(memoria.buscar_bitacora(con, "centinela"), "resultados") == [i]
    con.execute("UPDATE bitacora_items SET contenido='- detalle con la palabra faro' WHERE id=?", (i,))
    assert memoria.buscar_bitacora(con, "centinela")["total"] == 0 and ids(memoria.buscar_bitacora(con, "faro"), "resultados") == [i]
    con.execute("DELETE FROM bitacora_items WHERE id=?", (i,))
    assert memoria.buscar_bitacora(con, "faro")["total"] == 0


def test_buscar_devuelve_resumenes_no_bloques(con):
    i = reg(con, "Resumen corto del hallazgo", contenido="- " + "palabra larga " * 200)
    r = memoria.buscar_bitacora(con, "palabra")
    assert r["resultados"] == [{"id": i, "tipo": "nota", "modulos": ["salud"], "resumen": "Resumen corto del hallazgo"}]
    assert len(str(r)) < 300


# ---------- contexto ----------

@pytest.fixture
def surtido(con):
    """Ítems de dos módulos con todos los tipos; devuelve {clave: id}."""
    d = {}
    for clave, tipo, mods, extra in (
            ("nota", "nota", "salud", {}), ("prueba", "prueba", "salud", {}), ("error", "error", "salud", {}), ("decision", "decision", "salud", {}),
            ("limitacion", "limitacion", "salud", {}), ("pendiente", "pendiente", "salud", {}), ("inv", "invariante", "salud", {}),
            ("inv_seg", "invariante", "seguridad", {}), ("seg", "decision", "seguridad", {}), ("multi", "decision", "salud,reporte", {}),
            ("archivo", "nota", "datos", {"archivos": "salud.py"})):
        d[clave] = reg(con, f"Ítem {clave}", tipo, mods, titulo=f"T {clave}", **extra)
    return d


def test_sin_filtros_trae_todo_lo_vigente_con_las_invariantes_primero(con, surtido):
    r = memoria.contexto(con, n=50)
    assert r["total"] == 11 and [x["tipo"] for x in r["items"]][:2] == ["invariante", "invariante"]
    assert [x["tipo"] for x in r["items"]] == sorted((x["tipo"] for x in r["items"]), key=memoria.ORDEN_TIPOS.index)
    assert set(r["items"][0]) == {"id", "tipo", "modulos", "resumen"}


def test_el_orden_es_invariantes_pendientes_limitaciones_decisiones_errores_pruebas_notas(con, surtido):
    r = memoria.contexto(con, modulo="salud", n=50)
    assert [x["tipo"] for x in r["items"]] == ["invariante", "pendiente", "limitacion", "decision", "decision", "error", "prueba", "nota"]


def test_las_invariantes_se_incluyen_siempre_aunque_se_pase_de_n(con):
    for k in range(5):
        reg(con, f"invariante {k}", "invariante", titulo=f"I{k}")
    reg(con, "una decisión", "decision")
    r = memoria.contexto(con, modulo="salud", n=2)
    assert [x["tipo"] for x in r["items"]] == ["invariante"] * 5 and r["omitidos"] == 1 and r["total"] == 6


def test_n_limita_lo_que_no_es_invariante_y_avisa_cuantos_faltan(con, surtido):
    r = memoria.contexto(con, modulo="salud", n=4)
    assert len(r["items"]) == 4 and r["omitidos"] == 4 and [x["tipo"] for x in r["items"]] == ["invariante", "pendiente", "limitacion", "decision"]
    assert "omitidos" not in memoria.contexto(con, modulo="salud", n=50)


def test_filtra_por_modulo_y_un_item_de_varios_modulos_aparece_en_cada_uno(con, surtido):
    assert surtido["multi"] in ids(memoria.contexto(con, modulo="reporte")) and surtido["multi"] in ids(memoria.contexto(con, modulo="salud", n=50))
    assert surtido["seg"] not in ids(memoria.contexto(con, modulo="salud", n=50))
    assert {x["id"] for x in memoria.contexto(con, modulo="reporte")["items"]} == {surtido["multi"]}
    assert next(x for x in memoria.contexto(con, modulo="reporte")["items"])["modulos"] == ["reporte", "salud"]


def test_filtra_por_tipo_y_no_mezcla_invariantes_ajenas(con, surtido):
    assert ids(memoria.contexto(con, modulo="salud", tipo="error")) == [surtido["error"]]
    assert ids(memoria.contexto(con, modulo="salud", tipo="invariante")) == [surtido["inv"]]
    assert len(memoria.contexto(con, tipo="invariante", n=1)["items"]) == 2          # con tipo=invariante no hay tope


def test_el_archivo_se_resuelve_a_su_modulo_y_suma_los_items_que_lo_nombran(con, surtido):
    r = memoria.contexto(con, archivo="salud.py", n=50)
    assert r["modulos"] == ["salud"] and surtido["inv"] in ids(r) and surtido["archivo"] in ids(r)         # este último es de `datos`, pero nombra salud.py
    assert surtido["seg"] not in ids(r)
    assert ids(memoria.contexto(con, archivo="./salud.py", n=50)) == ids(r)
    assert surtido["inv"] in ids(memoria.contexto(con, archivo=str(RAIZ / "salud.py"), n=50))


def test_un_archivo_fuera_del_repo_es_del_modulo_sistema(con):
    i = reg(con, "El sudoers de otro proyecto no se toca", "invariante", "sistema")
    assert ids(memoria.contexto(con, archivo="/etc/sudoers.d/otro")) == [i] and ids(memoria.contexto(con, modulo="sistema")) == [i]


def test_un_archivo_que_no_esta_en_el_mapa_pide_el_modulo(con, surtido):
    with pytest.raises(ValueError, match="pasá `modulo`"):
        memoria.contexto(con, archivo="cosa_rara.py")
    assert memoria.contexto(con, archivo="cosa_rara.py", modulo="salud")["total"] > 0


def test_modulo_o_tipo_inventados_dan_error(con, surtido):
    for kw in ({"modulo": "inventado"}, {"tipo": "inventado"}):
        with pytest.raises(ValueError):
            memoria.contexto(con, **kw)


def test_lo_superado_solo_aparece_si_se_pide(con, surtido):
    memoria.marcar_superada(con, surtido["decision"], surtido["multi"], "lo reemplaza")
    assert surtido["decision"] not in ids(memoria.contexto(con, modulo="salud", n=50))
    r = memoria.contexto(con, modulo="salud", n=50, incluir_superadas=True)
    vieja = next(x for x in r["items"] if x["id"] == surtido["decision"])
    assert vieja["vigencia"] == "superada" and vieja["reemplazada_por"] == surtido["multi"] and r["items"][-1]["id"] == surtido["decision"]   # la historia va al final
    assert "vigencia" not in next(x for x in r["items"] if x["id"] == surtido["multi"])


def test_una_invariante_superada_deja_de_ser_obligatoria(con, surtido):
    memoria.marcar_superada(con, surtido["inv"], surtido["multi"], "el usuario la cambió")
    assert surtido["inv"] not in ids(memoria.contexto(con, modulo="salud", n=50))


def test_los_items_historicos_no_salen_por_defecto(con):
    i = reg(con, "algo de otra época")
    con.execute("UPDATE bitacora_items SET vigencia='historica' WHERE id=?", (i,))
    assert memoria.contexto(con)["total"] == 0 and ids(memoria.contexto(con, incluir_superadas=True)) == [i]


def test_sin_items_el_contexto_esta_vacio_y_no_crea_nada(con):
    for r in (memoria.contexto(con), memoria.pendientes(con), memoria.buscar_bitacora(con, "algo")):
        assert r["total"] == 0 and "error" not in r
    assert not memoria.existe(con, "bitacora_items")
    with pytest.raises(ValueError, match="No existe"):
        memoria.detalle_bitacora(con, 1)


# ---------- detalle ----------

def test_el_detalle_trae_todo_del_item(con):
    i = reg(con, "Resumen", "decision", "salud,datos", seccion="Nivel 3 / Fase 2", titulo="Decisiones", contenido="- Texto\n  - con subpunto",
            archivos="salud.py,db.py", prueba="tests/test_salud.py::test_a", fecha="2026-10-20")
    d = memoria.detalle_bitacora(con, i)
    assert d == {"id": i, "seccion": "Nivel 3 / Fase 2", "entrada": "Decisiones", "fecha": "2026-10-20", "tipo": "decision", "vigencia": "vigente",
                 "modulos": ["datos", "salud"], "archivos": ["db.py", "salud.py"], "resumen": "Resumen", "contenido": "- Texto\n  - con subpunto",
                 "prueba": "tests/test_salud.py::test_a"}


def test_el_detalle_de_un_item_superado_dice_por_cual_y_el_nuevo_dice_a_cuales_reemplaza(con):
    viejo, otro, nuevo = reg(con, "viejo"), reg(con, "otro"), reg(con, "nuevo")
    memoria.marcar_superada(con, viejo, nuevo, "cambió el criterio")
    memoria.marcar_superada(con, otro, nuevo, "idem")
    d = memoria.detalle_bitacora(con, viejo)
    assert d["vigencia"] == "superada" and d["reemplazada_por"] == {"id": nuevo, "resumen": "nuevo"} and d["motivo"] == "cambió el criterio"
    assert memoria.detalle_bitacora(con, nuevo)["reemplaza"] == [viejo, otro] and "reemplazada_por" not in memoria.detalle_bitacora(con, nuevo)


# ---------- pendientes ----------

def test_pendientes_son_solo_los_vigentes_y_se_filtran_por_modulo(con):
    a = reg(con, "probar el botón", "pendiente", "alertas", titulo="a", fecha="2026-10-01")
    b = reg(con, "bajar el mínimo de muestras", "pendiente", "salud", titulo="b", fecha="2026-10-02")
    hecho = reg(con, "ya resuelto", "pendiente", "salud", titulo="c")
    reg(con, "no es pendiente", "decision", "salud", titulo="d")
    memoria.marcar_superada(con, hecho, b, "se resolvió")
    r = memoria.pendientes(con)
    assert r["total"] == 2 and ids(r, "pendientes") == [b, a] and r["pendientes"][0]["fecha"] == "2026-10-02"
    assert ids(memoria.pendientes(con, "alertas"), "pendientes") == [a]
    with pytest.raises(ValueError, match="Módulo desconocido"):
        memoria.pendientes(con, "inventado")


# ---------- marcar superada ----------

def test_marcar_superada_no_borra_deja_constancia_y_exige_motivo(con):
    viejo, nuevo = reg(con, "viejo"), reg(con, "nuevo")
    with pytest.raises(ValueError, match="motivo"):
        memoria.marcar_superada(con, viejo, nuevo, " ")
    assert memoria.marcar_superada(con, viejo, nuevo, "motivo")["mensaje"].endswith(f"#{nuevo}.")
    f = con.execute("SELECT vigencia, reemplazada_por, motivo, contenido FROM bitacora_items WHERE id=?", (viejo,)).fetchone()
    assert tuple(f) == ("superada", nuevo, "motivo", "- viejo")
    assert "marcar_superada" in con.execute("SELECT tool FROM acciones").fetchone()[0]
    assert con.execute("SELECT COUNT(*) FROM bitacora_items").fetchone()[0] == 2


def test_marcar_superada_rechaza_lo_incoherente(con):
    a, b, c = reg(con, "a"), reg(con, "b"), reg(con, "c")
    memoria.marcar_superada(con, a, b, "m")
    for args, donde in (((a, a, "m"), "sí mismo"), ((a, c, "m"), "ya está superado"), ((c, a, "m"), "no está vigente"),
                        ((999, c, "m"), "No existe"), ((c, 999, "m"), "No existe"), ((c, b, "x" * 301), "motivo")):
        with pytest.raises(ValueError, match=donde):
            memoria.marcar_superada(con, *args)
    assert con.execute("SELECT vigencia FROM bitacora_items WHERE id=?", (c,)).fetchone()[0] == "vigente"


def test_la_busqueda_marca_lo_superado(con):
    viejo, nuevo = reg(con, "criterio viejo de temperatura"), reg(con, "criterio nuevo de temperatura")
    memoria.marcar_superada(con, viejo, nuevo, "m")
    r = {x["id"]: x for x in memoria.buscar_bitacora(con, "temperatura")["resultados"]}
    assert r[viejo]["vigencia"] == "superada" and "vigencia" not in r[nuevo]


# ---------- tools del MCP ----------

def test_las_tools_nuevas_funcionan_de_punta_a_punta(con):
    i = server.registrar_bitacora("Nivel 9", "invariante", "Reglas", "Nada se borra", "datos", "- Nunca se borra nada.", archivos="db.py")["id"]
    n = server.registrar_bitacora("Nivel 9", "pendiente", "Pendientes", "Probar el botón", "alertas", "- Probar el botón")["id"]
    assert ids(server.contexto(archivo="db.py")) == [i] and ids(server.contexto(modulo="alertas", tipo="pendiente")) == [n]
    assert server.detalle_bitacora(i)["contenido"] == "- Nunca se borra nada." and ids(server.pendientes(), "pendientes") == [n]
    assert "superado" in server.marcar_superada(n, i, "prueba")["mensaje"] and server.pendientes()["total"] == 0
    assert server.buscar_bitacora("borra")["resultados"][0]["id"] == i


def test_las_tools_nuevas_devuelven_errores_en_vez_de_excepciones(con):
    for r in (server.contexto(modulo="inventado"), server.contexto(archivo="raro.py"), server.detalle_bitacora(99), server.pendientes("x"),
              server.marcar_superada(1, 2, "m"), server.registrar_bitacora("s", "nota", "t", "r" * 200, "salud", "c")):
        assert "error" in r


def test_las_tools_de_lectura_nuevas_no_crean_tablas(con):
    for r in (server.contexto(), server.pendientes(), server.buscar_bitacora("algo")):
        assert "error" not in r
    assert not memoria.existe(con, "bitacora_items")


def test_las_tools_nuevas_estan_registradas_y_el_reporte_semanal_no_las_usa():
    assert NUEVAS <= {t.name for t in server.mcp._tool_manager.list_tools()}
    asunto = NUEVAS | {"buscar_bitacora", "registrar_bitacora"}
    assert asunto <= set(reporte.HERRAMIENTAS_PROHIBIDAS) and not asunto & set(reporte.HERRAMIENTAS_LECTURA)


# ---------- exportación ----------

def test_una_entrada_con_items_se_exporta_con_los_items_en_orden(con):
    reg(con, "primero", contenido="- Primero\n  - subpunto")
    reg(con, "párrafo", contenido="Un párrafo suelto.")
    reg(con, "tercero", contenido="- Tercero")
    md = sin_comentarios(memoria.exportar_bitacora(con))
    assert md.rstrip().endswith("### Título\n_" + memoria.hoy() + " · nota_\n\n- Primero\n  - subpunto\n\nUn párrafo suelto.\n- Tercero")


# ---------- exportación (fase 2): marcas sin perder ni reordenar nada ----------

import re

import migrar_memoria as mm


def migrar_a_items(con, texto: str, tipos=None):
    """Parte un BITACORA.md en entradas e ítems dentro de la base temporal, como lo hará la migración (metadatos neutros)."""
    memoria.asegurar(con)
    _, entradas = mm.parsear_bitacora(texto)
    creados = []
    for e in entradas:
        m = re.match(r"_(\d{4}-\d{2}-\d{2}) · (\w+)_\n+", e["contenido"])       # la línea de fecha y tipo la pone el exportador, no es contenido
        if m:
            e = {**e, "fecha": m.group(1), "tipo": m.group(2), "contenido": e["contenido"][m.end():]}
        eid = con.execute("INSERT INTO bitacora (fecha, seccion, tipo, titulo, contenido) VALUES (?,?,?,?,?)",
                          (e["fecha"], e["seccion"], e["tipo"], e["titulo"], e["contenido"])).lastrowid
        for k, t in enumerate(mm.dividir_en_items(e["contenido"]), 1):
            creados.append(memoria.crear_item(con, eid, e["fecha"], (tipos or {}).get(len(creados), "nota"), f"Ítem {len(creados)}", t, ["memoria"], orden=k))
    con.commit()
    return creados


RX_MARCA = re.compile(r"^\s*(\*\*\(invariante( · prueba: .+)?\)\*\*|\(superada por #\d+: .+\))$")


def crudo(md: str) -> str:
    """El markdown sin lo que agrega el exportador a los ítems: los comentarios de metadatos y las marcas."""
    return "\n".join(l for l in md.split("\n") if not memoria.RX_COMENTARIO.match(l) and not RX_MARCA.match(l))


def sin_comentarios(md: str) -> str:
    return "\n".join(l for l in md.split("\n") if not memoria.RX_COMENTARIO.match(l))


def con_texto(md: str) -> list[str]:
    return [l for l in md.splitlines() if l.strip()]


def es_subsecuencia(pocas: list[str], muchas: list[str]) -> bool:
    it = iter(muchas)
    return all(any(l == m for m in it) for l in pocas)


def test_dividir_en_items_separa_viñetas_con_sus_subviñetas_y_parrafos():
    texto = "Párrafo de dos\nlíneas.\n- uno\n  - sub\n  - sub2\n- dos\n\n```\n- no es ítem\n\ncódigo\n```\n1. numerada\nOtro párrafo"
    assert mm.dividir_en_items(texto) == ["Párrafo de dos\nlíneas.", "- uno\n  - sub\n  - sub2", "- dos", "```\n- no es ítem\n\ncódigo\n```", "1. numerada", "Otro párrafo"]


def test_exportar_los_items_migrados_conserva_el_bitacora_actual_linea_por_linea(con):
    original = crudo((RAIZ / "BITACORA.md").read_text(encoding="utf-8"))
    migrar_a_items(con, original)
    assert crudo(memoria.exportar_bitacora(con)) == original      # igual, no solo las líneas con texto


def test_las_marcas_son_lineas_nuevas_y_no_pierden_ni_reordenan_ninguna_linea_del_original(con):
    original = crudo((RAIZ / "BITACORA.md").read_text(encoding="utf-8"))
    creados = migrar_a_items(con, original)
    for i in creados[::7]:
        con.execute("UPDATE bitacora_items SET tipo='invariante' WHERE id=?", (i,))
    con.execute("UPDATE bitacora_items SET prueba='tests/test_x.py::test_y' WHERE id=?", (creados[0],))
    for viejo, nuevo in zip(creados[1::11], creados[2::11]):
        memoria.marcar_superada(con, viejo, nuevo, "lo reemplazó\n la instalación")
    exportado = con_texto(memoria.exportar_bitacora(con))
    base = con_texto(original)
    assert es_subsecuencia(base, exportado)
    nuevas = [l for l in exportado if l not in set(base) and not memoria.RX_COMENTARIO.match(l)]
    assert nuevas and all(RX_MARCA.match(l) for l in nuevas)


def test_formato_de_las_marcas(con):
    inv = reg(con, "Nada se borra", "invariante", contenido="- Nunca se borra nada.\n  - ni cuarentena", prueba="tests/test_cuarentena.py::test_nunca_borra", titulo="A")
    sin_prueba = reg(con, "Solo local", "invariante", contenido="- Solo en 127.0.0.1", titulo="A")
    viejo, nuevo = reg(con, "viejo", contenido="- sin instalar", titulo="A"), reg(con, "nuevo", contenido="Párrafo nuevo.", titulo="A")
    memoria.marcar_superada(con, viejo, nuevo, "ya se instaló")
    cuerpo = sin_comentarios(memoria.exportar_bitacora(con)).split("### A\n", 1)[1].split("\n\n", 1)[1]
    assert cuerpo.rstrip() == ("- Nunca se borra nada.\n  - ni cuarentena\n  **(invariante · prueba: tests/test_cuarentena.py::test_nunca_borra)**\n"
                               "- Solo en 127.0.0.1\n  **(invariante)**\n"
                               f"- sin instalar\n  (superada por #{nuevo}: ya se instaló)\n\nPárrafo nuevo.")
    assert inv and sin_prueba


def test_una_invariante_superada_lleva_las_dos_marcas(con):
    a, b = reg(con, "vieja regla", "invariante", contenido="- Regla vieja"), reg(con, "regla nueva", "invariante", contenido="- Regla nueva")
    memoria.marcar_superada(con, a, b, "el usuario la cambió")
    md = sin_comentarios(memoria.exportar_bitacora(con))
    assert "- Regla vieja\n  **(invariante)**\n  (superada por #" + str(b) + ": el usuario la cambió)\n- Regla nueva\n  **(invariante)**" in md


def test_el_markdown_marcado_sigue_siendo_valido_una_marca_no_abre_otro_item(con):
    reg(con, "inv", "invariante", contenido="- Regla")
    reg(con, "otra", "nota", contenido="- Otra")
    lineas = sin_comentarios(memoria.exportar_bitacora(con)).split("\n")
    marca = next(i for i, l in enumerate(lineas) if "(invariante)" in l)
    assert lineas[marca].startswith("  ") and lineas[marca - 1] == "- Regla" and lineas[marca + 1] == "- Otra"


# ---------- migración a ítems (fase 3) ----------

import json as _json

import db

BITACORA_SINTETICA = {
    1: ("Nivel 1", "Decisiones", "decision", "- **Uno:** primera decisión.\n  - con subpunto\n- **Dos:** segunda."),
    2: ("Nivel 1", "Limitaciones", "limitacion", "Un párrafo suelto.\n- Y una viñeta después.\n- Pendiente: hacer algo."),
    3: ("Nivel 2", "Pruebas", "prueba", "- Corrida vieja de una vez."),
}


def sembrar_entradas(con):
    memoria.asegurar(con)
    for i, (sec, tit, tipo, cont) in BITACORA_SINTETICA.items():
        con.execute("INSERT INTO bitacora (id, fecha, seccion, tipo, titulo, contenido) VALUES (?,?,?,?,?,?)", (i, "2026-10-28", sec, tipo, tit, cont))
    con.commit()


def propuesta_sintetica():
    p, n = [], 0
    for eid, (sec, tit, tipo, cont) in BITACORA_SINTETICA.items():
        for t in mm.dividir_en_items(cont):
            n += 1
            p.append({"n": n, "entrada": eid, "seccion": sec, "titulo": tit, "fecha": "2026-10-28", "tipo": tipo, "modulos": ["memoria"], "archivos": [],
                      "vigencia": "vigente", "reemplazada_por": None, "motivo": None, "resumen": f"Resumen {n}", "prueba": "", "nuevo": False, "texto": t})
    return p


@pytest.fixture
def propuesta(con):
    sembrar_entradas(con)
    return propuesta_sintetica()


def hechos(con):
    return con.execute("SELECT COUNT(*) FROM bitacora_items").fetchone()[0]


def test_migrar_items_escribe_con_el_id_igual_al_n_y_deja_constancia(con, propuesta):
    propuesta[0].update(tipo="invariante", prueba="tests/x.py::test_y")
    propuesta[1].update(vigencia="superada", reemplazada_por=5, motivo="porque sí")   # 5 = la viñeta «Y una viñeta después»
    propuesta[2].update(vigencia="historica", archivos=["salud.py"], modulos=["salud", "datos"])
    propuesta.append({**propuesta[0], "n": 7, "tipo": "pendiente", "vigencia": "vigente", "prueba": "", "nuevo": True, "entrada": 3,
                      "texto": "- Un pendiente nuevo.", "resumen": "Pendiente nuevo"})
    antes = memoria.exportar_bitacora(con)
    r = mm.migrar_items(con, propuesta)
    assert r == {"items": 7, "nuevos": 1, "superadas": 1, "historicas": 1, "invariantes": 1, "pendientes": 1}
    f = {x["id"]: x for x in con.execute("SELECT * FROM bitacora_items")}
    assert sorted(f) == [1, 2, 3, 4, 5, 6, 7] and f[1]["tipo"] == "invariante" and f[1]["prueba"] == "tests/x.py::test_y"
    assert (f[2]["vigencia"], f[2]["reemplazada_por"], f[2]["motivo"]) == ("superada", 5, "porque sí") and f[3]["vigencia"] == "historica"
    assert [x["orden"] for x in con.execute("SELECT orden FROM bitacora_items WHERE entrada_id=1 ORDER BY id")] == [1, 2]
    assert [x[0] for x in con.execute("SELECT modulo FROM bitacora_item_modulo WHERE item_id=3 ORDER BY modulo")] == ["datos", "salud"]
    assert con.execute("SELECT ruta FROM bitacora_item_archivo WHERE item_id=3").fetchone()[0] == "salud.py"
    assert con.execute("SELECT COUNT(*) FROM acciones WHERE tool='migrar_memoria'").fetchone()[0] == 1
    despues = con_texto(memoria.exportar_bitacora(con))
    assert es_subsecuencia(con_texto(antes), despues) and any("(superada por #5: porque sí)" in l for l in despues)         # no pierde líneas
    assert memoria.contexto(con, tipo="invariante")["items"][0]["id"] == 1 and ids(memoria.pendientes(con), "pendientes") == [7]


def test_migrar_items_no_se_repite(con, propuesta):
    mm.migrar_items(con, propuesta)
    with pytest.raises(RuntimeError, match="ya tiene datos"):
        mm.migrar_items(con, propuesta)
    assert hechos(con) == len(propuesta)


@pytest.mark.parametrize("cambio,donde", [
    (lambda p: p[0].update(texto="- otra cosa"), "no dan su texto actual"),
    (lambda p: p.pop(), "no tiene ítems"),
    (lambda p: p[0].update(modulos=["inventado"]), "módulos inválidos"),
    (lambda p: p[0].update(resumen="x" * 121), "resumen"),
    (lambda p: p[0].update(tipo="otro"), "tipo o vigencia"),
    (lambda p: p[0].update(vigencia="superada", reemplazada_por=2, motivo="m") or p[1].update(vigencia="historica"), "no está vigente"),
    (lambda p: p[0].update(vigencia="superada", reemplazada_por=2), "falta el motivo"),
    (lambda p: p[0].update(vigencia="superada"), "van juntos"),
    (lambda p: p[1].update(n=9), "sin saltos"),
    (lambda p: p[0].update(entrada=99), "no existe"),
])
def test_una_propuesta_invalida_no_escribe_nada(con, propuesta, cambio, donde):
    cambio(propuesta)
    with pytest.raises(ValueError, match=donde):
        mm.migrar_items(con, propuesta)
    assert hechos(con) == 0


def test_si_algo_falla_a_mitad_no_queda_nada_a_medias(con, propuesta, monkeypatch):
    original, llamadas = memoria.crear_item, []

    def falla_en_el_tercero(*a, **k):
        llamadas.append(1)
        if len(llamadas) == 3:
            raise sqlite3.IntegrityError("falla de prueba")
        return original(*a, **k)

    monkeypatch.setattr(memoria, "crear_item", falla_en_el_tercero)
    with pytest.raises(sqlite3.IntegrityError):
        mm.migrar_items(con, propuesta)
    assert hechos(con) == 0 and con.execute("SELECT COUNT(*) FROM bitacora_item_modulo").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM acciones WHERE tool='migrar_memoria'").fetchone()[0] == 0


@pytest.fixture
def archivo_propuesta(tmp_path, con, propuesta):
    con.close()
    ruta = tmp_path / "propuesta.json"
    ruta.write_text(_json.dumps(propuesta), encoding="utf-8")
    return str(ruta)


def test_la_simulacion_de_items_no_escribe(archivo_propuesta, capsys):
    assert mm.main(["--items", archivo_propuesta]) == 0 and "Simulación" in capsys.readouterr().out
    c = db.conectar()
    assert hechos(c) == 0
    c.close()


def test_la_simulacion_de_items_avisa_de_los_problemas(archivo_propuesta, tmp_path, capsys):
    p = _json.loads(open(archivo_propuesta, encoding="utf-8").read())
    p[0]["texto"] = "- cambiado"
    malo = tmp_path / "malo.json"
    malo.write_text(_json.dumps(p), encoding="utf-8")
    assert mm.main(["--items", str(malo)]) == 1 and "no dan su texto actual" in capsys.readouterr().out


def test_sin_copia_previa_de_items_no_escribe(archivo_propuesta, capsys):
    assert mm.main(["--items", archivo_propuesta, "--ejecutar"]) == 1 and "antes-de-items" in capsys.readouterr().err
    c = db.conectar()
    assert hechos(c) == 0
    c.close()


def test_con_copia_previa_de_items_escribe_y_no_se_repite(archivo_propuesta, capsys):
    (db.DIR_DATOS / "doctor.db.antes-de-items-1").write_text("")
    assert mm.main(["--items", archivo_propuesta, "--ejecutar"]) == 0 and "'items': 6" in capsys.readouterr().out
    c = db.conectar()
    assert hechos(c) == 6
    c.close()
    assert mm.main(["--items", archivo_propuesta, "--ejecutar"]) == 1

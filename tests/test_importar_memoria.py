"""El markdown como respaldo completo: metadatos en comentarios HTML, `memoria.py --importar` y la ida y vuelta exportar -> importar -> exportar."""

import re
import sqlite3
from pathlib import Path

import pytest

import db
import memoria
from conftest import RAIZ

FENCE = "```"
RARO = 'Dice "comillas" y \\barras\\, usa -- guiones --> y <etiquetas> & más; ñandú ✓ \U0001F600 y un separador de línea'
CALCULADAS = ("hostname", "so", "kernel", "cpu", "gpu", "ram", "discos", "placa madre", "paquetes", "_snapshot_")


def base_vacia(tmp_path: Path, nombre: str = "otra.db"):
    con = sqlite3.connect(tmp_path / nombre)
    con.row_factory = sqlite3.Row
    con.executescript(db.ESQUEMA)
    return con


def reg(con, resumen, tipo="nota", mods="salud", seccion="Sección", titulo="Título", contenido=None, **kw):
    return memoria.registrar_bitacora(con, seccion, tipo, titulo, resumen, mods, contenido or f"- {resumen}", **kw)["id"]


def sembrar_rico(con):
    """Una bitácora y un changelog con todo lo que el formato tiene que aguantar."""
    a = reg(con, "Una invariante con prueba", "invariante", "datos,mcp", seccion="Nivel 1 / Fase 1", titulo="Decisiones",
            contenido="- **Regla:** nunca se borra.\n  - ni cuarentena\n  - ni olvidar", archivos="db.py,~/.local/share/x y/z", prueba="tests/t.py::test_a", fecha="2026-10-20")
    b = reg(con, RARO, "decision", "salud", seccion="Nivel 1 / Fase 1", titulo="Decisiones", contenido="Un párrafo suelto con " + RARO)
    c = reg(con, "Con un bloque de código", "error", "git", seccion="Nivel 1 / Fase 1", titulo="Decisiones",
            contenido=f"- Mirá esto:\n{FENCE}\n# no es un encabezado\n<!-- item {{\"id\":1}} -->\n\n- ni una viñeta\n{FENCE}\n- y sigue.")
    x = reg(con, "Efímero", titulo="Efímera", seccion="Nivel 1 / Fase 1")           # se borra: deja un hueco en los ids de ítems y de entradas
    d, e = reg(con, "Vieja", "limitacion", "reporte", seccion="Nivel 2", titulo="Limitaciones"), reg(con, "Nueva", "decision", "reporte", seccion="Nivel 2", titulo="Limitaciones", contenido="1. Una numerada\n2. Otra")
    f = reg(con, "Pendiente de otro título", "pendiente", "alertas", seccion="Nivel 2", titulo="Pendientes", fecha="2026-11-01")
    memoria.marcar_superada(con, d, e, "Motivo con -- raro --> y <b>etiquetas</b>\ny dos líneas")
    con.execute("DELETE FROM bitacora_item_modulo WHERE item_id=?", (x,))
    con.execute("DELETE FROM bitacora_items WHERE id=?", (x,))
    con.execute("DELETE FROM bitacora WHERE titulo='Efímera'")
    con.execute("UPDATE bitacora_items SET vigencia='historica' WHERE id=?", (f,))
    con.execute("INSERT INTO bitacora (fecha, seccion, tipo, titulo, contenido) VALUES ('2026-10-28','Nivel 2','nota','Introducción','Una introducción sin ítems.')")
    con.execute("INSERT INTO bitacora (fecha, seccion, tipo, titulo, contenido) VALUES ('2026-10-28','Vieja','nota','Entrada de antes','- Texto de antes de los ítems.\n- Otro.')")
    con.commit()
    memoria.registrar_changelog(con, "error", "gpu", "Línea 1\n- **Estado:** falso\nLínea 3 con | pipe", titulo="Un error con título")
    r = memoria.registrar_changelog(con, "cambio", "kernel", "Se actualizó " + RARO)["id"]
    memoria.resolver_changelog(con, r, "Quedó bien")
    memoria.registrar_changelog(con, "observacion", "cpu", "Detalle que termina con salto\n", estado="resuelto")
    memoria.registrar_identidad(con, "Energía", "Perfil `balanced` | con pipe\ny salto")
    memoria.registrar_identidad(con, "Node.js", RARO)
    return {"a": a, "b": b, "c": c, "d": d, "e": e, "f": f}


def exportar_a(con, carpeta: Path) -> dict:
    memoria.exportar(con, carpeta)
    return {n: (carpeta / n).read_text(encoding="utf-8") for n in ("BITACORA.md", "CHANGELOG.md")}


def tablas(con) -> dict:
    return {t: [tuple(r) for r in con.execute(f"SELECT * FROM {t} ORDER BY 1, 2")] for t in
            ("bitacora_items", "bitacora_item_modulo", "bitacora_item_archivo", "changelog", "identidad_manual")}


# ---------- el formato ----------

def test_cada_comentario_de_metadatos_es_una_linea_html_valida_que_no_se_puede_cerrar_antes(con, tmp_path):
    sembrar_rico(con)
    for md in exportar_a(con, tmp_path).values():
        for linea in md.split("\n"):
            if "<!--" in linea:
                m = memoria.RX_COMENTARIO.match(linea)
                assert m, linea
                adentro = linea.strip()[len("<!-- "):-len(" -->")]
                assert "--" not in adentro and "-->" not in adentro and "<" not in adentro and ">" not in adentro
                assert not any(c in linea for c in "  \x85\r")


def test_los_metadatos_van_en_comentarios_y_lo_visible_sigue_siendo_markdown(con, tmp_path):
    ids = sembrar_rico(con)
    md = exportar_a(con, tmp_path)["BITACORA.md"]
    assert re.search(rf'^#### Decisiones\n_2026-10-20 · decision_\n<!-- entrada \{{"id":1,.*"titulo":"Decisiones".*\}} -->\n\n<!-- item \{{"id":{ids["a"]},"tipo":"invariante"', md, re.M)
    assert f'<!-- item {{"id":{ids["a"]},"tipo":"invariante","vigencia":"vigente","fecha":"2026-10-20"' in md and '"prueba":"tests/t.py::test_a"' in md
    assert '"reemplazada_por":%d' % ids["e"] in md and "(superada por #%d:" % ids["e"] in md          # la marca visible sigue estando
    assert "\n  <!-- item " in md and "\n<!-- item " in md              # dentro de una viñeta va sangrado (la lista sigue siendo una); el primero, no
    ch = exportar_a(con, tmp_path)["CHANGELOG.md"]
    assert ch.count("<!-- changelog ") == 3 and ch.count("<!-- identidad_manual ") == 2


def test_memoria_y_hechos_conocidos_siguen_sin_exportarse(con, tmp_path):
    memoria.recordar(con, "privado", "un dato personal")
    memoria.agregar_hecho_conocido(con, "algo que sé", "sdb")
    sembrar_rico(con)
    todo = "".join(exportar_a(con, tmp_path).values())
    assert "dato personal" not in todo and "algo que sé" not in todo and "hechos_conocidos" not in todo


@pytest.mark.parametrize("malo", ["## un título", "### otro", "<!-- item {\"id\":9} -->", "  <!-- entrada {} -->"])
def test_un_item_no_puede_traer_lineas_que_romperian_la_importacion(con, malo):
    with pytest.raises(ValueError, match="no puede tener"):
        reg(con, "malo", contenido=f"- bien\n{malo}")


def test_dentro_de_un_bloque_de_codigo_si_se_admiten(con):
    assert reg(con, "ok", contenido=f"- código:\n{FENCE}\n## no es un encabezado\n<!-- item {{}} -->\n{FENCE}")


# ---------- ida y vuelta ----------

def test_exportar_importar_exportar_da_archivos_identicos_byte_a_byte(con, tmp_path):
    sembrar_rico(con)
    a = exportar_a(con, tmp_path / "a")
    otra = base_vacia(tmp_path)
    r = memoria.importar(otra, a["BITACORA.md"], a["CHANGELOG.md"])
    assert r == {"bitacora": 5, "items": 6, "changelog": 3, "identidad": 2}
    b = exportar_a(otra, tmp_path / "b")
    assert b["BITACORA.md"].encode() == a["BITACORA.md"].encode() and b["CHANGELOG.md"].encode() == a["CHANGELOG.md"].encode()


def test_la_importacion_restaura_las_tablas_con_los_mismos_ids_y_valores(con, tmp_path):
    ids = sembrar_rico(con)
    a = exportar_a(con, tmp_path / "a")
    otra = base_vacia(tmp_path)
    memoria.importar(otra, a["BITACORA.md"], a["CHANGELOG.md"])
    assert tablas(otra) == tablas(con)
    assert [r[0] for r in otra.execute("SELECT id FROM bitacora_items ORDER BY id")] == [r[0] for r in con.execute("SELECT id FROM bitacora_items ORDER BY id")] != list(range(1, 7))
    assert [r[0] for r in otra.execute("SELECT id FROM bitacora ORDER BY id")] == [r[0] for r in con.execute("SELECT id FROM bitacora ORDER BY id")]
    assert [tuple(r) for r in otra.execute("SELECT id, seccion, titulo, fecha, tipo FROM bitacora ORDER BY id")] == \
           [tuple(r) for r in con.execute("SELECT id, seccion, titulo, fecha, tipo FROM bitacora ORDER BY id")]
    d = memoria.detalle_bitacora(otra, ids["d"])
    assert d["vigencia"] == "superada" and d["reemplazada_por"]["id"] == ids["e"] and d["motivo"] == "Motivo con -- raro --> y <b>etiquetas</b> y dos líneas".replace("</b> y", "</b>\ny")
    assert memoria.detalle_bitacora(otra, ids["b"])["resumen"] == RARO and memoria.detalle_bitacora(otra, ids["a"])["prueba"] == "tests/t.py::test_a"
    assert memoria.contexto(otra, modulo="datos")["items"][0]["id"] == ids["a"] and memoria.buscar_bitacora(otra, "nunca se borra")["resultados"][0]["id"] == ids["a"]


def test_las_entradas_sin_items_y_las_introducciones_vuelven_con_su_texto(con, tmp_path):
    sembrar_rico(con)
    a = exportar_a(con, tmp_path / "a")
    otra = base_vacia(tmp_path)
    memoria.importar(otra, a["BITACORA.md"], a["CHANGELOG.md"])
    f = {r["titulo"]: r["contenido"] for r in otra.execute("SELECT * FROM bitacora")}
    assert f["Introducción"] == "Una introducción sin ítems." and f["Entrada de antes"] == "- Texto de antes de los ítems.\n- Otro."
    assert otra.execute("SELECT COUNT(*) FROM bitacora_items WHERE entrada_id=(SELECT id FROM bitacora WHERE titulo='Entrada de antes')").fetchone()[0] == 0


def test_con_los_markdown_reales_del_repo_la_ida_y_vuelta_es_identica(tmp_path):
    bit = (RAIZ / "BITACORA.md").read_text(encoding="utf-8")
    cl = (RAIZ / "CHANGELOG.md").read_text(encoding="utf-8")
    otra = base_vacia(tmp_path)
    r = memoria.importar(otra, bit, cl)
    assert r["bitacora"] >= 83 and r["items"] >= 378 and r["changelog"] >= 21 and r["identidad"] >= 4
    b = exportar_a(otra, tmp_path / "b")
    assert b["BITACORA.md"].encode() == bit.encode()                                       # la bitácora, idéntica
    # el changelog, idéntico salvo la identidad calculada: sale del último snapshot de entorno, que no está en el markdown
    sin_calculadas = lambda t: [l for l in t.split("\n") if l.strip() and not (l.startswith("| ") and l.split("|")[1].strip().lower() in CALCULADAS)
                                and l != "_Todavía no hay un snapshot de entorno._"]
    assert sin_calculadas(b["CHANGELOG.md"]) == sin_calculadas(cl)
    assert otra.execute("SELECT COUNT(*) FROM bitacora_items WHERE vigencia='superada' AND reemplazada_por IS NOT NULL").fetchone()[0] >= 16


# ---------- seguridad de la importación ----------

def test_no_pisa_tablas_con_datos(con, tmp_path):
    sembrar_rico(con)
    a = exportar_a(con, tmp_path)
    antes = tablas(con)
    with pytest.raises(RuntimeError, match="ya tienen datos"):
        memoria.importar(con, a["BITACORA.md"], a["CHANGELOG.md"])
    assert tablas(con) == antes


def test_con_reemplazar_vacia_y_reconstruye(con, tmp_path):
    sembrar_rico(con)
    a = exportar_a(con, tmp_path)
    antes = tablas(con)
    reg(con, "Xilofono sobrante", titulo="Otra cosa")
    memoria.importar(con, a["BITACORA.md"], a["CHANGELOG.md"], reemplazar=True)
    assert tablas(con) == antes
    assert con.execute("SELECT COUNT(*) FROM bitacora_items_fts WHERE bitacora_items_fts MATCH 'que'").fetchone()[0] >= 0      # el índice no quedó roto
    assert memoria.buscar_bitacora(con, "xilofono")["total"] == 0


@pytest.mark.parametrize("dano,donde", [
    (lambda t: t.replace('"tipo":"invariante"', '"tipo":"inventado"', 1), "CHECK|constraint"),
    (lambda t: t.replace("<!-- item {", "<!-- item {roto", 1), "no es JSON válido"),
    (lambda t: t.replace("**(invariante · prueba: tests/t.py::test_a)**", "", 1), "le falta la marca"),
    (lambda t: t.replace('<!-- item {"id":2,', '<!-- item {"id":1,', 1), "UNIQUE|constraint"),
])
def test_un_archivo_danado_no_escribe_nada_ni_borra_lo_que_habia(con, tmp_path, dano, donde):
    sembrar_rico(con)
    a = exportar_a(con, tmp_path)
    antes = tablas(con)
    with pytest.raises((ValueError, sqlite3.IntegrityError), match=donde):
        memoria.importar(con, dano(a["BITACORA.md"]), None, reemplazar=True)
    assert tablas(con) == antes                      # incluso con `reemplazar`: la transacción se deshace


def test_un_markdown_de_antes_de_la_fase_5_se_rechaza_con_un_mensaje_claro(con):
    with pytest.raises(ValueError, match="es de antes de la Fase 5"):
        memoria.importar(con, "# Bitácora\n\n## Sección\n\n### Título\n_2026-10-28 · nota_\n\n- texto\n")
    with pytest.raises(ValueError, match="No hay nada"):
        memoria.importar(con)
    assert not memoria.existe(con, "bitacora")


def test_se_puede_importar_solo_uno_de_los_dos_archivos(con, tmp_path):
    sembrar_rico(con)
    a = exportar_a(con, tmp_path)
    otra = base_vacia(tmp_path)
    assert memoria.importar(otra, a["BITACORA.md"]) == {"bitacora": 5, "items": 6}
    assert otra.execute("SELECT COUNT(*) FROM changelog").fetchone()[0] == 0
    assert memoria.importar(otra, changelog_md=a["CHANGELOG.md"]) == {"changelog": 3, "identidad": 2}


# ---------- línea de comandos ----------

def test_la_linea_de_comandos_importa_en_una_base_vacia_y_se_niega_si_hay_datos(con, tmp_path, capsys):
    sembrar_rico(con)
    memoria.exportar(con, tmp_path / "origen")
    for t in ("bitacora_item_modulo", "bitacora_item_archivo", "bitacora_items", "bitacora", "changelog", "identidad_manual"):
        con.execute(f"DELETE FROM {t}")
    con.commit()
    assert memoria.main(["--importar", "--origen", str(tmp_path / "origen")]) == 0 and "Importado" in capsys.readouterr().out
    assert con.execute("SELECT COUNT(*) FROM bitacora_items").fetchone()[0] == 6
    assert memoria.main(["--importar", "--origen", str(tmp_path / "origen")]) == 1 and "--reemplazar" in capsys.readouterr().err


def test_reemplazar_por_linea_de_comandos_hace_primero_una_copia_de_la_base(con, tmp_path, capsys):
    sembrar_rico(con)
    memoria.exportar(con, tmp_path / "origen")
    reg(con, "Se pierde al reemplazar", titulo="Otro")
    assert memoria.main(["--importar", "--origen", str(tmp_path / "origen"), "--reemplazar"]) == 0
    copias = list(db.DIR_DATOS.glob("doctor.db.antes-de-importar-*"))
    assert len(copias) == 1 and "Copia previa" in capsys.readouterr().out
    vieja = sqlite3.connect(copias[0])
    assert vieja.execute("SELECT COUNT(*) FROM bitacora_items").fetchone()[0] == 7           # la copia conserva lo anterior
    vieja.close()
    assert con.execute("SELECT COUNT(*) FROM bitacora_items").fetchone()[0] == 6


def test_la_linea_de_comandos_avisa_si_faltan_los_archivos(tmp_path, capsys):
    (tmp_path / "vacia").mkdir()
    assert memoria.main(["--importar", "--origen", str(tmp_path / "vacia")]) == 1 and "No hay BITACORA.md" in capsys.readouterr().err
    assert memoria.main(["--importar", "--origen"]) == 2

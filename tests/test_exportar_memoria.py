"""Exportación de la bitácora y el changelog a markdown (memoria.py --exportar) y su paso en el hook pre-commit.

La exportación es de SOLO LECTURA sobre la base y nunca incluye `memoria` ni `hechos_conocidos` (datos personales)."""

import json
import os
import re
import subprocess
import sys

import pytest

import db
import memoria
import migrar_memoria as mm
from conftest import RAIZ
from test_migracion_memoria import BITACORA, CHANGELOG


def sembrar(con):
    pre, bit = mm.parsear_bitacora(BITACORA)
    mm.migrar(con, {"preambulo": pre, "bitacora": bit, "changelog": mm.parsear_changelog(CHANGELOG), "identidad": mm.hechos_de_identidad(CHANGELOG), "memoria": mm.HECHOS_DE_CLAUDE_MD})


def snapshot(con):
    """Un snapshot de entorno con hardware, como lo deja el recolector."""
    con.execute("INSERT INTO snapshot_entorno (workspace_id, tomado_en, distro, kernel, escritorio, hash) VALUES (1, ?, 'Zorin OS 18.1', '7.0.0-38-generic', 'zorin:GNOME', 'h')", (db.ahora(),))
    sid = con.execute("SELECT MAX(id) FROM snapshot_entorno").fetchone()[0]
    for tipo, marca, modelo, det in [
        ("cpu", "AMD", "AMD Ryzen 5 5600X 6-Core Processor", {"arquitectura": "x86_64", "nucleos_fisicos": 6, "hilos": 12}),
        ("gpu", "AMD", "Advanced Micro Devices, Inc. [AMD/ATI] Navi 33 [Radeon RX 7600] (rev c0)", {"driver": "amdgpu", "mesa": "26.2.5~kisak1"}),
        ("ram", "", "", {"total_gb": 31.2, "swap_gb": 0.0}),
        ("disco", "Patriot", "Patriot Burst Elite 240GB", {"dev": "sdb", "tamano": "223,6G"}),
        ("mother", "ASUSTeK", "PRIME B550-PLUS", {"bios": "3404"})]:
        con.execute("INSERT INTO hardware (snapshot_id, tipo, marca, modelo, detalle) VALUES (?,?,?,?,?)", (sid, tipo, marca, modelo, json.dumps(det)))
    con.execute("INSERT INTO software (snapshot_id, origen, nombre, version) VALUES (?, 'apt', 'bash', '5')", (sid,))
    con.commit()


# ---------- bitácora ----------

def test_la_bitacora_exportada_conserva_cada_linea_en_orden_y_agrega_fecha_y_tipo(con):
    sembrar(con)
    md = memoria.exportar_bitacora(con)
    assert md.startswith("# Bitácora de pc-doctor\n\n> Archivo **generado**") and "No se edita a mano" in md
    cuerpo = lambda t: [l.rstrip() for l in t.splitlines() if l.strip() and not re.match(r"^#{1,4} ", l)]
    original = [l for l in cuerpo(BITACORA) if not l.startswith("Texto del preámbulo")]
    exportado = [l for l in cuerpo(md) if not re.match(r"^_\d{4}-\d{2}-\d{2} · \w+_$", l) and not l.startswith(("> Archivo", "Registro cronológico"))]
    assert exportado == original
    assert "_2026-10-28 · decision_" in md and "_2026-10-28 · error_" in md


def test_los_niveles_de_encabezado_siguen_a_la_seccion(con):
    sembrar(con)
    heads = [l for l in memoria.exportar_bitacora(con).splitlines() if re.match(r"^#{2,4} ", l) and "esto no es un encabezado" not in l]
    assert heads == ["## Construcción inicial (2026-10-28)", "### Estructura y datos", "### Servidor MCP", "## Nivel nuevo 1: línea base",
                     "### Decisiones", "### Errores encontrados y corregidos", "## Nivel nuevo 2: dashboard", "### Fase 1", "#### Decisiones",
                     "#### Pruebas (base temporal)", "### Fase 2", "#### Limitaciones"]


def test_una_entrada_nueva_aparece_con_su_fecha_y_tipo(con):
    sembrar(con)
    memoria.registrar_bitacora(con, "Nivel nuevo 3: otra cosa", "decision", "Usar tablas", "Usar tablas", "memoria", "Se decidió usar tablas.", fecha="2026-11-02")
    md = memoria.exportar_bitacora(con)
    assert md.rstrip().endswith("## Nivel nuevo 3: otra cosa\n\n### Usar tablas\n_2026-11-02 · decision_\n\nSe decidió usar tablas.")


# ---------- changelog ----------

def test_la_identidad_se_calcula_desde_el_snapshot_y_el_hardware(con):
    sembrar(con)
    snapshot(con)
    md = memoria.exportar_changelog(con)
    for esperado in ("| SO | Zorin OS 18.1, escritorio zorin:GNOME |", "| Kernel | 7.0.0-38-generic |", "| CPU | AMD Ryzen 5 5600X (6 núcleos, 12 hilos, x86_64) |",
                     "| GPU | Navi 33 [Radeon RX 7600], driver `amdgpu`, Mesa 26.2.5 |", "| RAM | 31,2 GB (sin swap) |",
                     "| Discos | Patriot Burst Elite 240GB 223,6G (sdb) |", "| Placa madre | ASUSTeK PRIME B550-PLUS, BIOS 3404 |", "| Paquetes | 1 (apt 1) |"):
        assert esperado in md


def test_las_filas_declaradas_a_mano_salen_en_la_identidad_actual(con):
    sembrar(con)
    snapshot(con)
    md = memoria.exportar_changelog(con)
    tabla = md.split("## Identidad actual")[1].split("## Entradas")[0]
    assert tabla.index("| Paquetes |") < tabla.index("| Energía | Perfil `balanced` |") < tabla.index("| Red expuesta | Solo Steam |") \
        < tabla.index("| Sensores extra | `smartmontools` |") < tabla.index("| Node.js | 24.22.2 |")      # después de las calculadas, en orden
    assert "Energía, Red expuesta, Sensores extra, Node.js: declarados a mano (`registrar_identidad`), no calculados; última actualización: 2026-10-27." in tabla


def test_sin_filas_manuales_no_hay_nota_y_sin_snapshot_las_manuales_igual_salen(con):
    snapshot(con)
    memoria.asegurar(con)
    assert "declarados a mano" not in memoria.exportar_changelog(con)
    memoria.registrar_identidad(con, "Energía", "balanced")
    con.execute("DELETE FROM hardware"); con.execute("DELETE FROM snapshot_entorno")
    md = memoria.exportar_changelog(con)
    assert "| Energía | balanced |" in md and "Todavía no hay un snapshot de entorno" in md


def test_registrar_identidad_crea_actualiza_y_rechaza_lo_calculado(con):
    assert memoria.registrar_identidad(con, "Node.js", "24")["mensaje"] == "Identidad agregada: Node.js."
    assert memoria.registrar_identidad(con, "node.js", "25")["mensaje"] == "Identidad actualizada: node.js."
    assert [(f["campo"], f["valor"]) for f in memoria.identidad_declarada(con)] == [("node.js", "25")]          # sin duplicar
    for malo in ("Kernel", "CPU", "  gpu ", "Placa madre", "_Snapshot_", ""):
        with pytest.raises(ValueError):
            memoria.registrar_identidad(con, malo, "x")
    with pytest.raises(ValueError, match="valor"):
        memoria.registrar_identidad(con, "Algo", "x" * 1501)


def test_la_tool_del_mcp_y_su_efecto_en_la_exportacion(con):
    import reporte
    import server
    assert "error" not in server.registrar_identidad("Red expuesta", "Solo Steam") and "error" in server.registrar_identidad("Kernel", "x")
    assert "| Red expuesta | Solo Steam |" in memoria.exportar_changelog(con)
    assert "registrar_identidad" in reporte.HERRAMIENTAS_PROHIBIDAS and "registrar_identidad" not in reporte.HERRAMIENTAS_LECTURA


def test_un_valor_con_barra_vertical_o_salto_de_linea_no_rompe_la_tabla(con):
    memoria.registrar_identidad(con, "Red", "a | b\nc")
    assert "| Red | a / b c |" in memoria.exportar_changelog(con)


def test_si_cambia_el_snapshot_cambia_la_identidad_sin_tocar_las_tablas(con):
    sembrar(con)
    snapshot(con)
    con.execute("UPDATE snapshot_entorno SET kernel='8.0.0-1-generic'")
    assert "| Kernel | 8.0.0-1-generic |" in memoria.exportar_changelog(con)


def test_sin_snapshot_la_identidad_lo_dice(con):
    sembrar(con)
    assert "Todavía no hay un snapshot de entorno" in memoria.exportar_changelog(con)


def test_las_entradas_van_de_la_mas_nueva_a_la_mas_vieja_con_tipo_acentuado_y_estado(con):
    sembrar(con)
    md = memoria.exportar_changelog(con)
    titulos = re.findall(r"^### (.+)$", md, re.M)
    assert [t[:10] for t in titulos] == ["2026-10-28", "2026-10-27", "2026-10-26"]
    assert "- **Tipo:** solución" in md and "- **Estado:** resuelto (2026-10-27)" in md and "- **Estado:** abierto" in md
    assert "- **Componente:** cpu (energía)" in md


def test_una_entrada_sin_titulo_usa_la_primera_linea_del_detalle(con):
    memoria.registrar_changelog(con, "cambio", "kernel", "Se actualizó el kernel.\nSegunda línea.")
    assert "### " + memoria.hoy() + " — Se actualizó el kernel." in memoria.exportar_changelog(con)


# ---------- lo que NO se exporta ----------

def test_memoria_y_hechos_conocidos_no_salen_de_la_base_pero_la_identidad_manual_si(con, tmp_path):
    sembrar(con)
    memoria.recordar(con, "privado", "dato personal SECRETO-123")
    memoria.agregar_hecho_conocido(con, "otro dato personal SECRETO-456", "sdb")
    memoria.registrar_identidad(con, "Energía", "SECRETO-789 es identidad, esto sí sale")
    memoria.exportar(con, tmp_path)
    assert "SECRETO-789" in (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")                  # identidad_manual SÍ se exporta
    todo = "".join(p.read_text(encoding="utf-8") for p in tmp_path.iterdir())
    assert "SECRETO-123" not in todo and "SECRETO-456" not in todo and sorted(p.name for p in tmp_path.iterdir()) == ["BITACORA.md", "CHANGELOG.md"]


# ---------- exportar() y la línea de comandos ----------

def test_exportar_escribe_los_dos_archivos_y_no_toca_lo_que_no_cambio(con, tmp_path):
    sembrar(con)
    assert memoria.exportar(con, tmp_path) == {"BITACORA.md": 9, "CHANGELOG.md": 3}
    antes = (tmp_path / "BITACORA.md").stat().st_mtime_ns
    memoria.exportar(con, tmp_path)
    assert (tmp_path / "BITACORA.md").stat().st_mtime_ns == antes


def test_sin_tablas_no_se_exporta_nada_y_no_se_crean(con, tmp_path):
    assert memoria.exportar(con, tmp_path) == {} and list(tmp_path.iterdir()) == []
    assert not memoria.existe(con, "bitacora")


def test_la_linea_de_comandos_exporta_en_solo_lectura(con, tmp_path, capsys):
    sembrar(con)
    con.commit()
    assert memoria.main(["--exportar", "--destino", str(tmp_path)]) == 0 and "BITACORA.md (9 entradas)" in capsys.readouterr().out
    assert memoria.main([]) == 2 and memoria.main(["--exportar", "--destino"]) == 2


def test_sin_base_la_linea_de_comandos_no_crea_ninguna(tmp_path, capsys):
    assert not db.RUTA_DB.exists()
    assert memoria.main(["--exportar", "--destino", str(tmp_path)]) == 0 and "nada que exportar" in capsys.readouterr().out
    assert not db.RUTA_DB.exists() and list(tmp_path.iterdir()) == []


# ---------- el hook regenera y agrega al commit ----------

@pytest.fixture
def repo_con_memoria(tmp_path):
    """Repositorio con el hook, un `memoria.py` falso (escribe un BITACORA.md) y un `uv` falso que lo ejecuta."""
    r = tmp_path / "repo"
    (r / "scripts").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    for k, v in (("user.name", "Prueba"), ("user.email", "p@example.com"), ("commit.gpgsign", "false")):
        subprocess.run(["git", "config", k, v], cwd=r, check=True)
    (r / "scripts" / "pre-commit").write_text((RAIZ / "scripts" / "pre-commit").read_text())
    (r / "memoria.py").write_text("import os, sys\nopen('BITACORA.md','w').write(os.environ.get('CONTENIDO','regenerado\\n'))\nsys.exit(int(os.environ.get('SALIDA','0')))\n")
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    (fakes / "uv").write_text(f"#!/bin/sh\nexec {sys.executable} \"$2\" \"$3\"\n")
    (fakes / "uv").chmod(0o755)
    return r


def correr_hook(repo, **env):
    e = {**os.environ, "PC_DOCTOR_HOOK_SIN_PRUEBAS": "1", "PATH": f"{repo.parent / 'fakes'}:{os.environ['PATH']}", **env}
    return subprocess.run([sys.executable, "scripts/pre-commit"], cwd=repo, capture_output=True, text=True, env=e)


@pytest.mark.lento
def test_el_hook_regenera_la_memoria_y_la_agrega_al_commit(repo_con_memoria):
    r = repo_con_memoria
    (r / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "a.py"], cwd=r, check=True)
    p = correr_hook(r)
    assert p.returncode == 0, p.stderr
    staged = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=r, capture_output=True, text=True).stdout.split()
    assert sorted(staged) == ["BITACORA.md", "a.py"]


@pytest.mark.lento
def test_lo_exportado_tambien_pasa_por_la_revision_de_secretos(repo_con_memoria):
    r = repo_con_memoria
    (r / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "a.py"], cwd=r, check=True)
    token = "gh" + "p_" + "A1b2C3d4E5" * 3 + "F6g7H8"
    p = correr_hook(r, CONTENIDO=f"clave {token}\n")
    assert p.returncode == 1 and "BITACORA.md" in p.stderr and "token de GitHub" in p.stderr


@pytest.mark.lento
def test_si_la_exportacion_falla_avisa_pero_no_bloquea(repo_con_memoria):
    r = repo_con_memoria
    (r / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "a.py"], cwd=r, check=True)
    p = correr_hook(r, SALIDA="1")
    assert p.returncode == 0 and "aviso: la exportación de la memoria falló" in p.stderr


@pytest.mark.lento
def test_con_la_variable_no_exporta_y_sin_memoria_py_tampoco(repo_con_memoria):
    r = repo_con_memoria
    (r / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "a.py"], cwd=r, check=True)
    assert correr_hook(r, PC_DOCTOR_HOOK_SIN_EXPORTAR="1").returncode == 0 and not (r / "BITACORA.md").exists()
    (r / "memoria.py").unlink()
    assert correr_hook(r).returncode == 0 and not (r / "BITACORA.md").exists()

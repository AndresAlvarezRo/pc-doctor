"""Actualización en el lugar (actualizar.py): mezcla de config, CLAUDE.md del usuario, respaldo y migración de una instalación 1.0 REAL.

La prueba con la 1.0 usa el .zip publicado (variable PC_DOCTOR_ZIP_1_0 o paquetes/pc-doctor-Win-v1.0.zip; se baja con
`gh release download Win-v1.0`); si no está, se saltea. Todo corre en carpetas temporales y en procesos aparte, como en producción."""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import actualizar

RAIZ = Path(__file__).resolve().parent.parent
ZIP_1_0 = Path(os.environ.get("PC_DOCTOR_ZIP_1_0") or RAIZ / "paquetes" / "pc-doctor-Win-v1.0.zip")
SHA_1_0 = "1895fb60568083046154ab93307b8a8e1fc89496e6c7cf65b645c2158e1279a4"   # el que figura en la release publicada
BLOQUE_1_0 = (RAIZ / "tests" / "datos_actualizar" / "CLAUDE.usuario.1.0.md").read_text(encoding="utf-8")


# ---------- mezcla de config ----------

def test_mezclar_agrega_lo_que_falta_y_no_pisa_nada():
    defecto = {"a": 1, "b": {"x": 1, "y": 2}, "c": [1], "nueva": "nunca", "vacio": {}}
    actual = {"a": 9, "b": {"x": 7}, "c": [], "vacio": {"propio": 1}, "extra": True}
    nuevo, agregadas = actualizar.mezclar_config(actual, defecto)
    assert nuevo == {"a": 9, "b": {"x": 7, "y": 2}, "c": [], "nueva": "nunca", "vacio": {"propio": 1}, "extra": True}
    assert sorted(agregadas) == ["b.y", "nueva"]
    assert actualizar.mezclar_config(nuevo, defecto) == (nuevo, [])               # idempotente


# ---------- CLAUDE.md del usuario ----------

PLANTILLA = (RAIZ / "plantillas" / "CLAUDE.usuario.md").read_text(encoding="utf-8")


def test_claude_md_nuevo_o_sin_el_bloque_lo_agrega_al_final_sin_tocar_lo_del_usuario():
    assert actualizar.actualizar_claude_md("", PLANTILLA) == (PLANTILLA.strip("\n") + "\n", "agregado")
    propio = "# Mis reglas\n- usar tabs\n"
    nuevo, accion = actualizar.actualizar_claude_md(propio, PLANTILLA)
    assert accion == "agregado" and nuevo.startswith(propio) and actualizar.MARCA_FIN in nuevo


def test_claude_md_del_instalador_10_se_actualiza_y_conserva_lo_que_el_usuario_escribio_antes_y_despues():
    actual = "# Mío\n- regla antes\n\n" + BLOQUE_1_0.strip() + "\n\n## Más cosas mías\n- regla después\n"
    nuevo, accion = actualizar.actualizar_claude_md(actual, PLANTILLA)
    assert accion == "actualizado"
    assert nuevo.startswith("# Mío\n- regla antes\n\n") and nuevo.endswith("## Más cosas mías\n- regla después\n")
    assert "aprobar_plan" in nuevo and nuevo.count(actualizar.ENCABEZADO) == 1
    assert actualizar.actualizar_claude_md(nuevo, PLANTILLA) == (nuevo, "igual")     # idempotente


def test_claude_md_del_instalador_10_con_saltos_de_linea_de_windows_tambien_se_reconoce():
    actual = ("# Mío\r\n\r\n" + BLOQUE_1_0.strip() + "\r\n").replace("\n", "\r\n").replace("\r\r", "\r")
    assert actualizar.actualizar_claude_md(actual, PLANTILLA)[1] == "actualizado"


def test_un_bloque_10_editado_por_el_usuario_no_se_pisa():
    editado = BLOQUE_1_0.strip() + "\n- una regla que agregué yo adentro\n"
    nuevo, accion = actualizar.actualizar_claude_md("# Mío\n" + editado, PLANTILLA)
    assert accion == "bloque_editado" and nuevo == "# Mío\n" + editado


def test_entre_las_marcas_se_reemplaza_y_fuera_no_se_toca():
    actual = "antes\n" + actualizar.MARCA_INICIO + "\nviejo\n" + actualizar.MARCA_FIN + "\ndespués\n"
    nuevo, accion = actualizar.actualizar_claude_md(actual, PLANTILLA)
    assert accion == "actualizado" and nuevo.startswith("antes\n") and nuevo.endswith("\ndespués\n") and "viejo" not in nuevo


# ---------- versión y respaldo ----------

def test_version_instalada(tmp_path):
    assert actualizar.version_de(tmp_path) is None
    (tmp_path / "collector.py").write_text("")
    assert actualizar.version_de(tmp_path) == "1.0"                                # sin version.txt es la 1.0
    (tmp_path / "version.txt").write_text("1.1.0\n")
    assert actualizar.version_de(tmp_path) == "1.1.0"


def test_el_respaldo_copia_la_base_con_sus_datos_aunque_haya_wal(tmp_path):
    con = sqlite3.connect(tmp_path / "doctor.db")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE t (x)")
    con.execute("INSERT INTO t VALUES (42)")
    con.commit()                                                                   # queda en el -wal, la conexión sigue abierta
    (tmp_path / "config.json").write_text('{"a": 1}')
    copia = actualizar.respaldar(tmp_path, "1.0")
    con.close()
    assert copia.parent == tmp_path / "copias" and copia.name.startswith("antes-de-1.0-")
    assert sqlite3.connect(copia / "doctor.db").execute("SELECT x FROM t").fetchone() == (42,)
    assert (copia / "config.json").read_text() == '{"a": 1}'
    assert actualizar.respaldar(tmp_path / "vacia", "1.0") is None


# ---------- con la 1.0 real ----------

@pytest.fixture
def instalacion_10(tmp_path):
    if not ZIP_1_0.is_file():
        pytest.skip("no está el .zip de la 1.0 (gh release download Win-v1.0)")
    assert hashlib.sha256(ZIP_1_0.read_bytes()).hexdigest() == SHA_1_0, "el zip no es el de la release 1.0 publicada"
    programa, datos, home = tmp_path / "programa", tmp_path / "datos", tmp_path / "home"
    zipfile.ZipFile(ZIP_1_0).extractall(programa)
    datos.mkdir()
    home.mkdir()
    # la base, con el esquema y el código de la 1.0 (proceso aparte, con su propio db.py)
    sembrar = ("import db, memoria\ncon = db.conectar()\n"
               "con.execute(\"INSERT INTO workspace (hostname, machine_id, creado_en) VALUES ('equipo-de-ejemplo', 'id-de-ejemplo', 1)\")\n"
               "memoria.registrar_changelog(con, 'observacion', 'sistema', 'Dato de la instalación 1.0', 'resuelto')\n"
               "memoria.agregar_hecho_conocido(con, 'Hecho de ejemplo de la 1.0')\ncon.commit()\n")
    entorno = {**os.environ, "PC_DOCTOR_DATOS": str(datos), "HOME": str(home)}
    r = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(programa)!r})\n" + sembrar], cwd=tmp_path,
                       env=entorno, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    (datos / "config.json").write_text(json.dumps({"consulta_online": False, "malwarebazaar_key": "", "notificaciones": True, "salud": True,
                                                   "umbrales": {"cpu": 90}, "boton_dashboard": False}, indent=2) + "\n")
    (datos / "web_token").write_text("token-de-ejemplo")
    return programa, datos, home


def correr(*args, cwd, entorno_extra=None):
    r = subprocess.run([sys.executable, "-I", str(RAIZ / "actualizar.py"), *map(str, args)], cwd=cwd, capture_output=True, text=True,
                       env={**os.environ, **(entorno_extra or {})})
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def tablas(ruta):
    con = sqlite3.connect(ruta)
    return {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for (t,) in
            con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def test_actualizar_una_instalacion_10_real_conserva_migra_mezcla_y_es_idempotente(instalacion_10, tmp_path):
    programa10, datos, home = instalacion_10
    nuevo = tmp_path / "nuevo"
    nuevo.mkdir()
    for n in ("config.ejemplo.json", "pyproject.toml"):
        (nuevo / n).write_bytes((RAIZ / n).read_bytes())
    for p in RAIZ.glob("*.py"):
        (nuevo / p.name).write_bytes(p.read_bytes())
    for carpeta in ("plataforma", "plantillas"):
        (nuevo / carpeta).mkdir()
        for p in (RAIZ / carpeta).glob("*"):
            if p.is_file():
                (nuevo / carpeta / p.name).write_bytes(p.read_bytes())
    (nuevo / "version.txt").write_text("1.1.0\n")
    antes_tablas = tablas(datos / "doctor.db")
    config_antes = json.loads((datos / "config.json").read_text())
    comun = ("--datos", datos, "--programa", nuevo, "--instalado", programa10)

    plan = correr("plan", *comun, cwd=tmp_path)                                    # solo informa
    assert (plan["version_actual"], plan["version_nueva"], plan["actualiza"]) == ("1.0", "1.1.0", True)
    assert {"tabla planes", "tabla recetas", "tabla diagnosticos", "tabla cortes_auto"} <= set(plan["migraciones"])
    assert {"mostrar_en_pantalla", "remediacion"} <= set(plan["opciones_nuevas"])
    assert tablas(datos / "doctor.db") == antes_tablas and json.loads((datos / "config.json").read_text()) == config_antes

    copia = Path(correr("respaldar", *comun, cwd=tmp_path)["copia"])
    assert copia.parent == datos / "copias" and tablas(copia / "doctor.db") == antes_tablas

    r = correr("aplicar", *comun, cwd=tmp_path)
    assert {"tabla planes", "tabla recetas"} <= set(r["migraciones"])
    despues = tablas(datos / "doctor.db")
    assert all(despues[t] == n for t, n in antes_tablas.items())                  # ni una fila de la 1.0 se perdió
    assert {"planes", "ejecuciones", "diagnosticos", "recetas", "cortes_auto"} <= set(despues)
    cfg = json.loads((datos / "config.json").read_text())
    assert cfg["consulta_online"] is False and cfg["boton_dashboard"] is False and cfg["umbrales"] == {"cpu": 90}   # lo del usuario, intacto
    assert cfg["mostrar_en_pantalla"] == "nunca" and cfg["remediacion"]["nivel"] == 1 and cfg["remediacion"]["preaprobadas"] == []
    assert (datos / "web_token").read_text() == "token-de-ejemplo"

    contenido = (datos / "config.json").read_bytes()
    r2 = correr("aplicar", *comun, cwd=tmp_path)                                   # segunda pasada: nada cambia
    assert r2 == {"migraciones": [], "opciones_nuevas": []} and (datos / "config.json").read_bytes() == contenido
    assert tablas(datos / "doctor.db") == despues
    assert correr("plan", *comun, cwd=tmp_path)["migraciones"] == []


def test_el_plan_no_crea_ni_cambia_nada_en_la_carpeta_de_datos(instalacion_10, tmp_path):
    """`plan` solo lee: no crea archivos nuevos en la carpeta de datos."""
    programa10, datos, _ = instalacion_10
    antes = sorted(p.name for p in datos.iterdir())
    correr("plan", "--datos", datos, "--programa", RAIZ, "--instalado", programa10, cwd=tmp_path)
    assert sorted(p.name for p in datos.iterdir()) == antes

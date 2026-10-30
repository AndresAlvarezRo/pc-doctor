"""Actualización en el lugar de una instalación de pc-doctor (la usa instalar.ps1; se puede probar en cualquier sistema).

Subcomandos (todos con `--datos CARPETA`, la carpeta de datos del usuario; nunca se borra nada de ahí):
  plan       muestra qué cambiaría: versión instalada -> nueva, migraciones de esquema y opciones nuevas de config.json. No cambia nada.
  respaldar  copia la base (consistente, con la API de respaldo de SQLite) y config.json a `copias/antes-de-<versión>-<fecha>/`.
  aplicar    migra el esquema (idempotente) y agrega a config.json las opciones que falten, sin pisar ninguna que ya exista.
  claude-md  agrega o actualiza el bloque de pc-doctor del CLAUDE.md del usuario, sin tocar lo que el usuario escribió fuera de él.

Todo lo que hace es idempotente: correrlo dos veces seguidas no cambia nada la segunda vez.
Respaldar usa solo la biblioteca estándar (corre con el Python de la instalación vieja, antes de copiar el código nuevo).
"""

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time
import tomllib
from pathlib import Path

VERSION_SIN_ARCHIVO = "1.0"                  # el paquete 1.0 no traía version.txt
MARCA_INICIO = "<!-- pc-doctor:inicio (no edites entre las marcas: se actualiza solo) -->"
MARCA_FIN = "<!-- pc-doctor:fin -->"
ENCABEZADO = "## Memoria de la PC (pc-doctor)"
# SHA-256 del bloque que agregó el instalador 1.0 (sin marcas): solo un bloque idéntico a ese se reemplaza sin preguntar.
HASH_BLOQUE_1_0 = "978568f664e0c52bb15ce1a175baee968ec127523cc4141ec564a4209e4cd7db"


# ---------- versiones ----------

def version_de(programa: Path) -> str | None:
    """Versión de una carpeta de programa: version.txt; sin él pero con collector.py es la 1.0; sin nada, None (no hay instalación)."""
    try:
        return (programa / "version.txt").read_text(encoding="utf-8").strip() or None
    except OSError:
        pass
    return VERSION_SIN_ARCHIVO if (programa / "collector.py").is_file() else None


def version_del_paquete(programa: Path) -> str:
    v = version_de(programa)
    if v and (programa / "version.txt").is_file():
        return v
    return tomllib.loads((programa / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


# ---------- config.json ----------

def opciones_por_defecto(programa: Path) -> dict:
    """Las opciones que trae el paquete (config.ejemplo.json) más el bloque `remediacion` con sus valores por defecto."""
    base = json.loads((programa / "config.ejemplo.json").read_text(encoding="utf-8"))
    sys.path.insert(0, str(programa))
    try:
        import diagnostico
        base["remediacion"] = dict(diagnostico.CONFIG_BASE)
    finally:
        sys.path.remove(str(programa))
    return base


def mezclar_config(actual: dict, defecto: dict, prefijo: str = "") -> tuple[dict, list[str]]:
    """(config nueva, claves agregadas). Solo agrega lo que falta; ningún valor existente se cambia (ni dentro de los bloques)."""
    nuevo, agregadas = dict(actual), []
    for k, v in defecto.items():
        if k not in actual:
            nuevo[k] = v
            agregadas.append(prefijo + k)
        elif isinstance(v, dict) and isinstance(actual[k], dict) and v:
            nuevo[k], sub = mezclar_config(actual[k], v, prefijo + k + ".")
            agregadas += sub
    return nuevo, agregadas


def _leer_config(datos: Path) -> dict | None:
    try:
        c = json.loads((datos / "config.json").read_text(encoding="utf-8"))
        return c if isinstance(c, dict) else None
    except (OSError, ValueError):
        return None


# ---------- esquema de la base ----------

def _estructura(con: sqlite3.Connection) -> dict[str, set[str]]:
    tablas = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    return {t: {r[1] for r in con.execute(f'PRAGMA table_info("{t}")')} for t in tablas}


def migraciones_pendientes(programa: Path, ruta_db: Path) -> list[str]:
    """Qué tablas y columnas le faltan a la base real respecto del esquema del programa nuevo. Solo lee (la base se abre en modo ro)."""
    if not ruta_db.is_file():
        return []
    sys.path.insert(0, str(programa))
    try:
        import db
        esperado = sqlite3.connect(":memory:")
        esperado.row_factory = sqlite3.Row
        esperado.executescript(db.ESQUEMA)
        db._migrar(esperado)
        quiero = _estructura(esperado)
    finally:
        sys.path.remove(str(programa))
    # sin -wal pendiente se abre inmutable: así ni siquiera aparecen archivos auxiliares (-wal/-shm) junto a la base
    modo = "mode=ro" if ruta_db.with_name(ruta_db.name + "-wal").exists() else "immutable=1"
    real = sqlite3.connect(f"file:{ruta_db}?{modo}", uri=True)
    try:
        tengo = _estructura(real)
    finally:
        real.close()
    res = [f"tabla {t}" for t in sorted(quiero) if t not in tengo]
    res += [f"columna {t}.{c}" for t in sorted(quiero) if t in tengo for c in sorted(quiero[t] - tengo[t])]
    return res


def migrar(programa: Path, datos: Path) -> list[str]:
    """Aplica el esquema del programa nuevo a la base real. Devuelve lo que se agregó (vacío si ya estaba al día)."""
    ruta = datos / "doctor.db"
    if not ruta.is_file():
        return []
    antes = migraciones_pendientes(programa, ruta)
    sys.path.insert(0, str(programa))
    try:
        import db
        db.conectar().close()
    finally:
        sys.path.remove(str(programa))
    return antes


# ---------- respaldo ----------

def respaldar(datos: Path, version: str, ahora: float | None = None) -> Path | None:
    """Copia la base y config.json a datos/copias/antes-de-<versión>-<fecha>/. Devuelve la carpeta (None si no había nada que copiar)."""
    db_, cfg = datos / "doctor.db", datos / "config.json"
    if not db_.is_file() and not cfg.is_file():
        return None
    marca = time.strftime("%Y%m%d-%H%M%S", time.localtime(ahora or time.time()))
    destino = datos / "copias" / f"antes-de-{version}-{marca}"
    destino.mkdir(parents=True, exist_ok=False)
    if db_.is_file():
        origen = sqlite3.connect(f"file:{db_}?mode=ro", uri=True)
        copia = sqlite3.connect(destino / "doctor.db")
        try:
            origen.backup(copia)       # consistente aunque haya un -wal pendiente
        finally:
            copia.close()
            origen.close()
    if cfg.is_file():
        shutil.copy2(cfg, destino / "config.json")
    return destino


# ---------- CLAUDE.md del usuario ----------

def _normal(t: str) -> str:
    return t.replace("\r\n", "\n")


def actualizar_claude_md(actual: str, plantilla: str) -> tuple[str, str]:
    """(texto nuevo, acción) con acción en: agregado, actualizado, igual, bloque_editado.
    La plantilla trae las marcas de inicio y fin. Lo que está fuera del bloque nunca se toca."""
    actual_n, bloque = _normal(actual), _normal(plantilla).strip("\n")
    ini, fin = actual_n.find(MARCA_INICIO.split(" (")[0]), actual_n.find(MARCA_FIN)
    if ini != -1 and fin > ini:                               # ya tiene marcas: se reemplaza lo que hay entre ellas
        fin += len(MARCA_FIN)
        nuevo = actual_n[:ini] + bloque + actual_n[fin:]
        return (actual, "igual") if nuevo == actual_n else (nuevo, "actualizado")
    pos = actual_n.find(ENCABEZADO)
    if pos != -1:                                             # el de la 1.0: sin marcas
        resto = actual_n[pos:]
        corte = resto.find("\n## ", 1)
        viejo = resto if corte == -1 else resto[:corte]
        if hashlib.sha256(viejo.strip().encode()).hexdigest() != HASH_BLOQUE_1_0:
            return actual, "bloque_editado"                   # el usuario lo cambió: no se pisa
        return actual_n[:pos] + bloque + "\n" + (resto[corte:] if corte != -1 else ""), "actualizado"
    sep = "" if not actual_n else ("\n" if actual_n.endswith("\n") else "\n\n")
    return actual_n + sep + bloque + "\n", "agregado"


# ---------- línea de comandos ----------

def _plan(programa: Path, datos: Path, instalado: Path | None) -> dict:
    nueva = version_del_paquete(programa)
    actual = version_de(instalado) if instalado else None
    cfg = _leer_config(datos)
    nuevas = mezclar_config(cfg, opciones_por_defecto(programa))[1] if cfg is not None else ["(se crea config.json con los valores por defecto)"]
    return {"version_actual": actual, "version_nueva": nueva, "migraciones": migraciones_pendientes(programa, datos / "doctor.db"),
            "opciones_nuevas": nuevas, "actualiza": actual is not None and actual != nueva}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("accion", choices=["plan", "respaldar", "aplicar", "claude-md"])
    ap.add_argument("--datos", type=Path, required=True)
    ap.add_argument("--programa", type=Path, default=Path(__file__).resolve().parent, help="carpeta del programa nuevo")
    ap.add_argument("--instalado", type=Path, help="carpeta del programa ya instalado (para saber la versión actual)")
    ap.add_argument("--claude-md", type=Path, help="ruta del CLAUDE.md del usuario")
    a = ap.parse_args(argv)
    os.environ["PC_DOCTOR_DATOS"] = str(a.datos)   # antes de importar db: así la carpeta de datos es esta y no otra
    if a.accion == "plan":
        print(json.dumps(_plan(a.programa, a.datos, a.instalado), ensure_ascii=False))
    elif a.accion == "respaldar":
        v = version_de(a.instalado) if a.instalado else None
        destino = respaldar(a.datos, v or "desconocida")
        print(json.dumps({"copia": str(destino) if destino else None}, ensure_ascii=False))
    elif a.accion == "aplicar":
        migradas = migrar(a.programa, a.datos)
        cfg, nuevas = _leer_config(a.datos), []
        if cfg is None:
            if (a.datos / "config.json").exists():       # existe pero no se puede leer: no se toca
                print(json.dumps({"migraciones": migradas, "opciones_nuevas": [], "aviso": "config.json inválido: no se tocó"}, ensure_ascii=False))
                return 0
            cfg = {}
        nuevo, nuevas = mezclar_config(cfg, opciones_por_defecto(a.programa))
        if nuevas:
            (a.datos / "config.json").write_text(json.dumps(nuevo, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({"migraciones": migradas, "opciones_nuevas": nuevas}, ensure_ascii=False))
    else:
        destino = a.claude_md
        actual = destino.read_text(encoding="utf-8") if destino.is_file() else ""
        nuevo, accion = actualizar_claude_md(actual, (a.programa / "plantillas" / "CLAUDE.usuario.md").read_text(encoding="utf-8"))
        if nuevo != actual:
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(nuevo, encoding="utf-8")
        print(json.dumps({"claude_md": accion}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

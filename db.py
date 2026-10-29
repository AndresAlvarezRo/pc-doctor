"""Esquema, conexión y helpers compartidos entre el recolector y el servidor MCP."""

import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime
from pathlib import Path

import psutil

import plataforma

log = logging.getLogger("pc-doctor")

# PC_DOCTOR_DATOS permite apuntar a otra carpeta (las pruebas usan una base temporal, nunca la real)
DIR_DATOS = Path(os.environ.get("PC_DOCTOR_DATOS") or plataforma.actual().dir_datos())
RUTA_DB = DIR_DATOS / "doctor.db"
DIR_CUARENTENA = DIR_DATOS / "cuarentena"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS workspace (
    id INTEGER PRIMARY KEY,
    hostname TEXT NOT NULL,
    machine_id TEXT NOT NULL UNIQUE,
    etiqueta TEXT,
    creado_en INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshot_entorno (
    id INTEGER PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspace(id),
    tomado_en INTEGER NOT NULL,
    distro TEXT, kernel TEXT, escritorio TEXT,
    hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshot_ts ON snapshot_entorno(tomado_en);
CREATE TABLE IF NOT EXISTS hardware (
    snapshot_id INTEGER NOT NULL REFERENCES snapshot_entorno(id),
    tipo TEXT NOT NULL CHECK (tipo IN ('cpu','gpu','ram','disco','mother')),
    marca TEXT, modelo TEXT,
    detalle TEXT  -- JSON
);
CREATE INDEX IF NOT EXISTS idx_hardware_snap ON hardware(snapshot_id);
CREATE TABLE IF NOT EXISTS software (
    snapshot_id INTEGER NOT NULL REFERENCES snapshot_entorno(id),
    nombre TEXT NOT NULL, version TEXT,
    origen TEXT NOT NULL CHECK (origen IN ('apt','flatpak','snap','registro','winget'))
);
CREATE INDEX IF NOT EXISTS idx_software_snap ON software(snapshot_id);
CREATE TABLE IF NOT EXISTS metricas (
    id INTEGER PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspace(id),
    ts INTEGER NOT NULL,
    cpu_pct REAL, ram_pct REAL, swap_pct REAL,
    temp_cpu REAL, temp_gpu REAL,
    disco_libre_gb REAL, load_1m REAL
);
CREATE INDEX IF NOT EXISTS idx_metricas_ts ON metricas(ts);
CREATE TABLE IF NOT EXISTS top_procesos (
    metrica_id INTEGER NOT NULL REFERENCES metricas(id),
    nombre TEXT, cpu_pct REAL, ram_mb REAL
);
CREATE INDEX IF NOT EXISTS idx_top_metrica ON top_procesos(metrica_id);
CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY,
    ts INTEGER NOT NULL,
    origen TEXT, severidad TEXT, mensaje TEXT
);
CREATE INDEX IF NOT EXISTS idx_eventos_ts ON eventos(ts);
CREATE TABLE IF NOT EXISTS acciones (
    id INTEGER PRIMARY KEY,
    ts INTEGER NOT NULL,
    tool TEXT NOT NULL,
    parametros TEXT,  -- JSON
    resultado TEXT
);
CREATE INDEX IF NOT EXISTS idx_acciones_ts ON acciones(ts);
CREATE TABLE IF NOT EXISTS ejecuciones (
    id INTEGER PRIMARY KEY,
    ts INTEGER NOT NULL,
    plan_id INTEGER,           -- el plan que la pidió (NULL si fue a mano)
    accion TEXT NOT NULL,      -- nombre del catálogo de remediacion.py (o lo que se intentó, si fue rechazada)
    parametros TEXT,           -- JSON
    estado TEXT NOT NULL CHECK (estado IN ('aplicada','fallida','rechazada')),
    resultado TEXT,            -- JSON
    deshacer TEXT,             -- JSON con lo necesario para deshacerla; NULL si no es reversible
    deshecha_en INTEGER
);
CREATE INDEX IF NOT EXISTS idx_ejecuciones_ts ON ejecuciones(ts);
CREATE TABLE IF NOT EXISTS cuarentena (
    id INTEGER PRIMARY KEY,
    ruta_original TEXT NOT NULL,
    ruta_nueva TEXT NOT NULL,
    tamano_bytes INTEGER,
    movido_en INTEGER NOT NULL,
    restaurado INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_cuarentena_ts ON cuarentena(movido_en);
CREATE TABLE IF NOT EXISTS metricas_diarias (
    dia TEXT NOT NULL,  -- YYYY-MM-DD (hora local)
    workspace_id INTEGER NOT NULL REFERENCES workspace(id),
    muestras INTEGER,
    cpu_prom REAL, cpu_max REAL,
    ram_prom REAL, ram_max REAL,
    swap_prom REAL, swap_max REAL,
    temp_cpu_prom REAL, temp_cpu_max REAL,
    temp_gpu_prom REAL, temp_gpu_max REAL,
    disco_libre_min_gb REAL,
    load_prom REAL, load_max REAL,
    PRIMARY KEY (workspace_id, dia)
);
CREATE TABLE IF NOT EXISTS hallazgos_seguridad (
    id INTEGER PRIMARY KEY,
    huella TEXT NOT NULL UNIQUE,  -- identifica el hallazgo sin depender del pid
    categoria TEXT NOT NULL CHECK (categoria IN ('minero','fantasma','keylogger','red','lista_online','persistencia','postura','vulnerabilidad')),
    regla TEXT NOT NULL,
    severidad TEXT NOT NULL CHECK (severidad IN ('alta','media','baja')),
    nombre TEXT, pid INTEGER, ruta_exe TEXT, detalle TEXT,
    primera_vez INTEGER NOT NULL,
    ultima_vez INTEGER NOT NULL,
    veces INTEGER NOT NULL DEFAULT 1,
    estado TEXT NOT NULL DEFAULT 'nuevo' CHECK (estado IN ('nuevo','revisado','falso_positivo'))
);
CREATE INDEX IF NOT EXISTS idx_hallazgos_ts ON hallazgos_seguridad(ultima_vez);
CREATE TABLE IF NOT EXISTS escuchas (
    id INTEGER PRIMARY KEY,
    proto TEXT NOT NULL, direccion TEXT NOT NULL, puerto INTEGER NOT NULL,
    proceso TEXT NOT NULL, pid INTEGER,
    primera_vez INTEGER NOT NULL,
    ultima_vez INTEGER NOT NULL,
    UNIQUE (proto, direccion, puerto, proceso)
);
CREATE INDEX IF NOT EXISTS idx_escuchas_ts ON escuchas(ultima_vez);
CREATE TABLE IF NOT EXISTS listas_seguridad (
    nombre TEXT PRIMARY KEY, url TEXT NOT NULL,
    descargada_en INTEGER NOT NULL, entradas INTEGER
);
CREATE TABLE IF NOT EXISTS reputacion (
    huella TEXT PRIMARY KEY,  -- la del hallazgo al que pertenece
    sha256 TEXT NOT NULL, sha1 TEXT NOT NULL, ruta_exe TEXT,
    veredicto TEXT NOT NULL CHECK (veredicto IN
        ('malicioso','sospechoso','sin_registro','conocido_limpio','sin_consultar','error')),
    fuente TEXT, detalle TEXT,
    consultado_en INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reputacion_sha ON reputacion(sha256);
CREATE INDEX IF NOT EXISTS idx_reputacion_ts ON reputacion(consultado_en);
CREATE TABLE IF NOT EXISTS notificaciones (
    huella TEXT PRIMARY KEY,  -- hallazgo ya avisado: no se vuelve a notificar
    ts INTEGER NOT NULL,
    titulo TEXT
);
CREATE INDEX IF NOT EXISTS idx_notificaciones_ts ON notificaciones(ts);
CREATE TABLE IF NOT EXISTS lecturas (
    metrica_id INTEGER NOT NULL REFERENCES metricas(id),
    ts INTEGER NOT NULL,
    categoria TEXT NOT NULL,   -- cpu, gpu, disco, memoria, placa
    nombre TEXT NOT NULL,      -- chip/etiqueta, por ejemplo amdgpu/junction
    valor REAL NOT NULL,
    unidad TEXT,
    limite_crit REAL,          -- límite crítico que informa el hardware, si lo hay
    contexto TEXT              -- reposo, carga o juego, según la actividad en ese momento
);
CREATE INDEX IF NOT EXISTS idx_lecturas_ts ON lecturas(ts);
CREATE TABLE IF NOT EXISTS sesiones_actividad (
    id INTEGER PRIMARY KEY,
    tipo TEXT NOT NULL,        -- juego
    detalle TEXT NOT NULL,     -- nombre del juego (o del proceso si no se pudo averiguar)
    inicio INTEGER NOT NULL,   -- inicio real del proceso cuando se conoce
    fin INTEGER,               -- NULL mientras sigue en curso; si no, la última vez que se la vio
    ultima_vez INTEGER NOT NULL,
    origen TEXT NOT NULL DEFAULT 'detectada'  -- detectada (en vivo) o reconstruida (del historial de procesos)
);
CREATE INDEX IF NOT EXISTS idx_sesiones_inicio ON sesiones_actividad(tipo, inicio);
CREATE TABLE IF NOT EXISTS reportes (
    id INTEGER PRIMARY KEY,
    ts INTEGER NOT NULL,
    ruta TEXT NOT NULL,        -- archivo en datos/reportes/
    modo TEXT NOT NULL CHECK (modo IN ('claude','determinista')),
    motivo TEXT,               -- por qué se usó el plan B (reporte sin redactar); NULL si lo redactó Claude
    duracion_s REAL,
    resumen TEXT
);
CREATE INDEX IF NOT EXISTS idx_lecturas_nombre ON lecturas(nombre, ts);
CREATE TABLE IF NOT EXISTS alertas_salud (
    clave TEXT PRIMARY KEY,    -- regla:nombre, por ejemplo temp_cpu:k10temp/Tctl
    categoria TEXT, nombre TEXT,
    severidad TEXT NOT NULL CHECK (severidad IN ('aviso','critico')),
    mensaje TEXT, valor REAL,
    desde INTEGER NOT NULL,
    ultima_vez INTEGER NOT NULL,
    ultima_notif INTEGER NOT NULL DEFAULT 0,
    activa INTEGER NOT NULL DEFAULT 1,
    resuelta_en INTEGER,
    veces INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_alertas_salud_ts ON alertas_salud(ultima_vez);
CREATE TABLE IF NOT EXISTS lecturas_diarias (
    dia TEXT NOT NULL,         -- AAAA-MM-DD (hora local); registro permanente, no se borra a los 30 días
    nombre TEXT NOT NULL, contexto TEXT NOT NULL,
    categoria TEXT, unidad TEXT,
    n INTEGER NOT NULL, media REAL, minimo REAL, maximo REAL,
    PRIMARY KEY (dia, nombre, contexto)
);
CREATE INDEX IF NOT EXISTS idx_lecturas_diarias_nombre ON lecturas_diarias(nombre, dia);
CREATE TABLE IF NOT EXISTS linea_base (
    nombre TEXT NOT NULL, contexto TEXT NOT NULL,
    categoria TEXT, unidad TEXT,
    n INTEGER NOT NULL,
    media REAL, desviacion REAL, minimo REAL, maximo REAL,
    p50 REAL, mad REAL, p95 REAL, p99 REAL,   -- mediana y desvío robusto: resisten datos atípicos
    desde INTEGER, hasta INTEGER, actualizada_en INTEGER NOT NULL,
    PRIMARY KEY (nombre, contexto)
);
"""


def _migrar(con: sqlite3.Connection) -> None:
    """Agrega columnas nuevas a bases creadas con un esquema anterior."""
    if "contexto" not in {r["name"] for r in con.execute("PRAGMA table_info(lecturas)")}:
        con.execute("ALTER TABLE lecturas ADD COLUMN contexto TEXT")


# El dashboard activa este modo: ninguna función de consulta puede escribir (SQLite lo rechaza). Las acciones que
# modifican algo piden `escribir=True` de forma explícita.
SOLO_LECTURA = False


def conectar(escribir: bool = False) -> sqlite3.Connection:
    """Abre la base (creándola si hace falta) con el esquema aplicado.

    Con `SOLO_LECTURA` activo y sin `escribir=True`, abre la base en modo de solo lectura y no toca el esquema.
    """
    if SOLO_LECTURA and not escribir:
        con = sqlite3.connect(f"file:{RUTA_DB}?mode=ro", uri=True, timeout=10)
        con.row_factory = sqlite3.Row
        return con
    DIR_DATOS.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(RUTA_DB, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(ESQUEMA)
    _migrar(con)
    return con


def ahora() -> int:
    """Epoch UTC actual en segundos."""
    return int(time.time())


def iso(ts: int) -> str:
    """Convierte un epoch a texto legible en hora local."""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def parsear_desde(texto: str) -> int:
    """Interpreta '7d', '24h', '30m', '2026-10-01' o '2026-10-01 12:00' como epoch.

    Lanza ValueError si el formato no se reconoce.
    """
    t = (texto or "").strip().lower()
    m = re.fullmatch(r"(\d+)\s*([mhdsw])", t)
    if m:
        n, u = int(m.group(1)), m.group(2)
        seg = {"m": 60, "h": 3600, "d": 86400, "w": 604800, "s": 1}[u]
        return ahora() - n * seg
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(t, fmt).timestamp())
        except ValueError:
            pass
    raise ValueError(f"Formato de fecha no válido: {texto!r} (usá '7d', '24h' o 'AAAA-MM-DD')")


def ejecutar(cmd: list[str], timeout: int = 20) -> str | None:
    """Corre un comando externo y devuelve su stdout, o None si no existe o falla (se loguea)."""
    if shutil.which(cmd[0]) is None:
        log.warning("comando no encontrado: %s", cmd[0])
        return None
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError) as e:
        log.warning("falló %s: %s", cmd[0], e)
        return None
    if r.returncode != 0:
        log.warning("%s terminó con código %s: %s", cmd[0], r.returncode, r.stderr.strip()[:200])
        return None
    return r.stdout


def _max_temp_chip(chip: dict) -> float | None:
    """Máxima lectura temp*_input de un chip de `sensors -j`."""
    vals = [v for sub in chip.values() if isinstance(sub, dict)
            for k, v in sub.items() if k.startswith("temp") and k.endswith("_input")]
    return max(vals) if vals else None


def temperatura_cpu() -> float | None:
    """Temperatura actual de la CPU en °C, o None si el sistema no la expone (Linux: `sensors -j`; Windows: LibreHardwareMonitor)."""
    return plataforma.actual().temperatura_cpu()


def _temperatura_cpu_linux() -> float | None:
    """Temperatura actual de la CPU en °C, vía `sensors -j` (o psutil como respaldo)."""
    salida = ejecutar(["sensors", "-j"])
    if salida:
        try:
            datos = json.loads(salida)
            for nombre, chip in datos.items():
                if nombre.startswith(("coretemp", "k10temp", "zenpower")):
                    for etiqueta in ("Package id 0", "Tctl", "Tdie"):
                        if etiqueta in chip:
                            for k, v in chip[etiqueta].items():
                                if k.endswith("_input"):
                                    return float(v)
                    t = _max_temp_chip(chip)
                    if t is not None:
                        return float(t)
        except (ValueError, TypeError, AttributeError) as e:
            log.warning("no pude interpretar sensors -j: %s", e)
    try:
        for nombre, lecturas in psutil.sensors_temperatures().items():
            if nombre in ("coretemp", "k10temp", "zenpower") and lecturas:
                return float(max(l.current for l in lecturas))
    except (AttributeError, OSError):
        pass
    return None


def temperatura_gpu() -> float | None:
    """Temperatura de la GPU NVIDIA en °C, o None si no hay `nvidia-smi`."""
    salida = ejecutar(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"])
    try:
        return float(salida.strip().splitlines()[0]) if salida else None
    except (ValueError, IndexError):
        return None


def top_procesos(n: int = 5, espera: float = 0.5) -> list[dict]:
    """Los n procesos que más CPU usan (mide durante `espera` segundos)."""
    procs = []
    for p in psutil.process_iter(["name"]):
        try:
            p.cpu_percent(None)
            procs.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    time.sleep(espera)
    filas = []
    for p in procs:
        try:
            filas.append({
                "nombre": p.info["name"] or "?",
                "cpu_pct": round(p.cpu_percent(None), 1),
                "ram_mb": round(p.memory_info().rss / 1048576, 1),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    filas.sort(key=lambda f: (f["cpu_pct"], f["ram_mb"]), reverse=True)
    return filas[:n]


def carpeta_descargas() -> Path | None:
    """Carpeta de descargas del usuario, o None si no existe (Linux: ~/Descargas o ~/Downloads; Windows: la carpeta Descargas)."""
    return plataforma.actual().carpeta_descargas()


def _carpeta_descargas_linux() -> Path | None:
    """Devuelve ~/Descargas o ~/Downloads, el que exista (prioriza Descargas)."""
    for nombre in ("Descargas", "Downloads"):
        p = Path.home() / nombre
        if p.is_dir():
            return p
    return None


def inicio_dia_local(ts: int) -> str:
    """Fecha local (AAAA-MM-DD) de un epoch."""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def dia_a_epoch(dia: str) -> int:
    """Epoch del inicio del día local indicado."""
    return int(datetime.strptime(dia, "%Y-%m-%d").timestamp())


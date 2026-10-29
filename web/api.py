"""API local del dashboard de pc-doctor. Fase 1: solo lectura.

Reutiliza las mismas funciones que el servidor MCP (consultas.py, salud.py, correlacion.py...): el dashboard y las
tools muestran exactamente lo mismo. La base se abre en modo de solo lectura, así que ningún endpoint puede escribir.

Seguridad: escucha solo en 127.0.0.1 y rechaza cualquier petición cuyo encabezado Host no sea localhost:PUERTO o
127.0.0.1:PUERTO (así una página web externa no puede leer los datos por DNS rebinding). Solo acepta GET.

Arranque: `uv run uvicorn web.api:app --host 127.0.0.1 --port 8787` desde la carpeta del proyecto.
"""

import mimetypes
import os
import re
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import db  # noqa: E402
import memoria  # noqa: E402

db.SOLO_LECTURA = True  # ninguna función de consulta puede escribir

import consultas  # noqa: E402
import correlacion  # noqa: E402
import reporte  # noqa: E402
import reputacion  # noqa: E402
import server  # noqa: E402  (las tools del MCP son funciones normales; se reutilizan tal cual)
from fastapi import FastAPI, HTTPException, Query, Request  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

mimetypes.add_type("application/manifest+json", ".webmanifest")  # el manifest de la PWA
PUERTO = int(os.environ.get("PC_DOCTOR_PUERTO", "8787"))
HOSTS_PERMITIDOS = {f"localhost:{PUERTO}", f"127.0.0.1:{PUERTO}"}
DIST = Path(__file__).resolve().parent / "frontend" / "dist"
CACHE_VIVO_S = 20          # la lectura de sensores en vivo (con SMART por sudo) se reutiliza este tiempo
MAX_RANGO_DIAS = 800
CONTEXTOS = ("reposo", "carga", "juego")
TIPOS_LINEA = {  # grupos de la línea de tiempo -> tipos de elemento
    "entorno": {"kernel", "driver_gpu", "paquete", "paquete_otros"}, "eventos": {"evento"}, "alertas": {"alerta"},
    "seguridad": {"hallazgo"}, "acciones": {"accion"}, "sesiones": {"sesion"}}
CLAVES_SECRETAS = re.compile(r"key|token|secret|clave|password", re.I)

app = FastAPI(title="pc-doctor", docs_url=None, redoc_url=None, openapi_url=None)


# ---------- protección y manejo de errores ----------

class NoDisponible(Exception):
    """La fuente de datos de esta sección todavía no existe (tabla ausente, sin base, sin datos)."""


@app.middleware("http")
async def proteger(request: Request, call_next):
    if request.headers.get("host", "").lower() not in HOSTS_PERMITIDOS:
        return JSONResponse({"error": "host no permitido"}, status_code=421)
    if request.method != "GET":
        return JSONResponse({"error": "método no permitido (esta API es de solo lectura)"}, status_code=405)
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.exception_handler(NoDisponible)
async def _no_disponible(_, e: NoDisponible):
    return JSONResponse({"disponible": False, "mensaje": f"No disponible todavía: {e}"})


@app.exception_handler(sqlite3.OperationalError)
async def _error_sqlite(_, e: sqlite3.OperationalError):
    if re.search(r"no such (table|column)", str(e)):  # base de una versión anterior: esa sección todavía no existe
        return JSONResponse({"disponible": False, "mensaje": "No disponible todavía: falta una tabla en la base"})
    return JSONResponse({"error": "la base está ocupada o no se pudo leer"}, status_code=503)


@app.exception_handler(ValueError)
async def _valor_invalido(_, e: ValueError):
    return JSONResponse({"error": str(e)}, status_code=400)


@contextmanager
def conexion():
    if not db.RUTA_DB.exists():
        raise NoDisponible("todavía no hay base de datos (el recolector aún no corrió)")
    con = db.conectar()
    try:
        yield con
    finally:
        con.close()


def rango(desde: str, hasta: str) -> tuple[int, int]:
    t0 = db.parsear_desde(desde or "24h")
    t1 = db.ahora()
    if hasta:
        t1 = db.parsear_desde(hasta)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", hasta.strip()):
            t1 += 86399  # una fecha sola incluye el día entero
    if t1 < t0:
        raise ValueError("'hasta' es anterior a 'desde'")
    if t1 - t0 > MAX_RANGO_DIAS * 86400:
        raise ValueError(f"el rango máximo es de {MAX_RANGO_DIAS} días")
    return t0, t1


# ---------- lectura en vivo con caché ----------

_vivo = {"t": 0.0, "v": None}
_candado = threading.Lock()


def estado_vivo(con) -> dict:
    """Lectura de sensores en vivo; se reutiliza unos segundos para que varias pestañas no repitan el SMART por sudo."""
    with _candado:
        if _vivo["v"] is None or time.time() - _vivo["t"] > CACHE_VIVO_S:
            _vivo["v"], _vivo["t"] = consultas.estado_en_vivo(con, reputacion.cargar_config(crear=False)), time.time()
        return _vivo["v"]


def _equipo() -> dict:
    p = server.perfil_entorno()
    if "error" in p or "hardware" not in p:
        return {}
    hw = {h["tipo"]: h for h in p["hardware"]}
    return {"cpu": hw.get("cpu", {}).get("modelo"), "gpu": consultas.nombre_gpu(hw["gpu"]["modelo"]) if "gpu" in hw else None,
            "ram_gb": hw.get("ram", {}).get("total_gb"), "placa": hw.get("mother", {}).get("modelo"),
            "so": p.get("distro"), "kernel": p.get("kernel"), "escritorio": p.get("escritorio"), "snapshot": p.get("tomado_en")}


def _segun_linea_base(principal: dict | None) -> str:
    """'dentro', 'fuera', 'aprendiendo' o 'sin_referencia': cómo está el valor principal frente a lo normal de este contexto."""
    if not principal or principal["referencia"] in ("ninguna", "fija"):
        return "sin_referencia"
    if principal["referencia"] == "aprendiendo":
        return "aprendiendo"
    return "dentro" if principal["dentro_de_banda"] else "fuera"


# ---------- endpoints ----------

@app.get("/api/estado")
def estado():
    """Resumen actual: identidad, contexto, alertas activas, una tarjeta por componente y lo que está fuera de lo normal."""
    with conexion() as con:
        vivo = estado_vivo(con)
        comp = consultas.componentes(con, vivo)
        activas = consultas.alertas(con, True, 365, 500)
        return {
            "hora": db.ahora(), "contexto": vivo["contexto"],
            "actividad": [{"tipo": j["tipo"], "detalle": j["detalle"], "desde": j["desde"]} for j in vivo["juego"]],
            "equipo": _equipo(),
            "alertas": {"critico": sum(a["severidad"] == "critico" for a in activas), "aviso": sum(a["severidad"] == "aviso" for a in activas),
                        "total": len(activas)},
            "fuera_de_lo_normal": [{"severidad": c["severidad"], "mensaje": c["mensaje"], "categoria": c.get("categoria"), "nombre": c.get("nombre")}
                                   for c in vivo["conds"].values()],
            "tarjetas": [{k: c[k] for k in ("tipo", "id", "titulo", "estado", "principal", "aprendiendo")}
                         | {"sensores": len(c["sensores"]), "segun_linea_base": _segun_linea_base(c["principal"])}
                         for lista in comp.values() for c in lista],
            "no_disponible": vivo["no_disponible"], "aprendizaje": consultas.aprendizaje(con)["resumen"]}


@app.get("/api/componentes/{tipo}")
def componente(tipo: str):
    """Detalle de un tipo de componente: cada entrada con todos sus sensores, su estado y la banda aprendida."""
    if tipo not in consultas.TIPOS_COMPONENTE:
        raise HTTPException(404, f"tipo desconocido; opciones: {', '.join(consultas.TIPOS_COMPONENTE)}")
    with conexion() as con:
        vivo = estado_vivo(con)
        return {"tipo": tipo, "titulo": consultas.TITULOS[tipo], "contexto": vivo["contexto"],
                "componentes": consultas.componentes(con, vivo)[tipo]}


@app.get("/api/series")
def series(sensor: str = Query(..., min_length=1, max_length=120), desde: str = "24h", hasta: str = "", contexto: str = "",
           max_puntos: int = Query(800, ge=50, le=2000)):
    """Puntos de un sensor para graficar, con la banda de la línea base (mediana ± desvío robusto) y la actividad."""
    if contexto and contexto not in CONTEXTOS:
        raise ValueError(f"contexto debe ser uno de: {', '.join(CONTEXTOS)}")
    t0, t1 = rango(desde, hasta)
    with conexion() as con:
        return consultas.serie(con, sensor, t0, t1, contexto, max_puntos)


@app.get("/api/alertas")
def alertas(estado: str = "activas", dias: int = Query(7, ge=1, le=365)):
    """Alertas de salud. `estado`: activas, resueltas o todas. Incluye la posible relación si hay un candidato fuerte."""
    if estado not in ("activas", "resueltas", "todas"):
        raise ValueError("estado debe ser activas, resueltas o todas")
    with conexion() as con:
        filas = consultas.alertas(con, estado == "activas", dias, 300)
        if estado == "resueltas":
            filas = [f for f in filas if not f["activa"]]
        for f in filas:
            try:
                f["relacion"] = correlacion.relacion_fuerte(con, f["categoria"], f["desde"])
            except Exception:  # la relación es un extra: nunca rompe el listado
                f["relacion"] = None
            f["estado"] = "activa" if f["activa"] else "resuelta"
        return {"total": len(filas), "alertas": filas}


@app.get("/api/hallazgos")
def hallazgos(estado: str = "todos", dias: int = Query(30, ge=1, le=365)):
    """Hallazgos de seguridad. `estado`: nuevo, revisado, falso_positivo o todos."""
    if estado not in ("nuevo", "revisado", "falso_positivo", "todos"):
        raise ValueError("estado debe ser nuevo, revisado, falso_positivo o todos")
    with conexion() as con:
        total, filas = consultas.hallazgos(con, estado, dias, 300)
        return {"total": total, "hallazgos": [
            {"id": f["id"], "severidad": f["severidad"], "categoria": f["categoria"], "regla": f["regla"], "proceso": f["nombre"],
             "detalle": f["detalle"], "estado": f["estado"], "veces": f["veces"], "primera_vez": f["primera_vez"],
             "ultima_vez": f["ultima_vez"],
             "reputacion": {"veredicto": f["veredicto"], "fuente": f["fuente"], "detalle": f["rep_detalle"]} if f["veredicto"] else None}
            for f in filas]}


@app.get("/api/linea_de_tiempo")
def linea_de_tiempo(desde: str = "48h", hasta: str = "", tipos: str = "", limite: int = Query(200, ge=1, le=500)):
    """Cambios de entorno, eventos, alertas, seguridad, acciones y sesiones en orden cronológico.
    `tipos`: lista separada por comas de entorno, eventos, alertas, seguridad, acciones, sesiones."""
    t0, t1 = rango(desde, hasta)
    elegidos = set()
    for g in filter(None, (x.strip() for x in tipos.split(","))):
        if g not in TIPOS_LINEA:
            raise ValueError(f"tipo desconocido {g!r}; opciones: {', '.join(TIPOS_LINEA)}")
        elegidos |= TIPOS_LINEA[g]
    with conexion() as con:
        return correlacion.linea_de_tiempo(con, t0, t1, elegidos or None, limite, estructurado=True)


@app.get("/api/correlacion/{alerta_id}")
def correlacion_de(alerta_id: str):
    """Posibles causas de una alerta (su `id`) o de un hallazgo (`hallazgo:N`). Son coincidencias, no causas demostradas."""
    if not re.fullmatch(r"\d{1,9}|hallazgo:\d{1,9}", alerta_id):
        raise ValueError("alerta_id debe ser un número o hallazgo:N")
    with conexion():  # sin base: "no disponible todavía" en vez de un error
        r = server.correlacionar(alerta_id)
    if "error" in r:
        raise HTTPException(404, r["error"])
    return r


@app.get("/api/reportes")
def reportes(n: int = Query(30, ge=1, le=200)):
    with conexion() as con:
        return {"reportes": [{k: r[k] for k in ("fecha", "ts", "modo", "motivo", "duracion_s", "resumen")} for r in reporte.listar(con, n)]}


@app.get("/api/reportes/{fecha}")
def reporte_de(fecha: str):
    with conexion() as con:
        r = reporte.leer(con, fecha)
    if not r:
        raise HTTPException(404, "no existe ese reporte")
    return {k: r[k] for k in ("fecha", "ts", "modo", "motivo", "duracion_s", "resumen", "contenido")}


@app.get("/api/diagnosticos")
def diagnosticos(dias: int = Query(30, ge=1, le=365)):
    """Diagnósticos automáticos disparados por alertas. La tabla se crea cuando esa función exista."""
    with conexion() as con:
        if not consultas.tabla_existe(con, "diagnosticos"):
            raise NoDisponible("el diagnóstico automático aún no está implementado")
        filas = con.execute("SELECT * FROM diagnosticos WHERE ts >= ? ORDER BY ts DESC LIMIT 100", (db.ahora() - dias * 86400,)).fetchall()
        return {"diagnosticos": [dict(f) for f in filas]}


@app.get("/api/hechos")
def hechos():
    """Hechos conocidos declarados por el usuario: los vigentes y los vencidos que hay que revisar (solo lectura)."""
    with conexion() as con:
        r = memoria.hechos_conocidos(con)
        r.pop("nota", None)
        return r


@app.get("/api/changelog")
def changelog(estado: str = "todos", n: int = Query(100, ge=1, le=300)):
    """Changelog de la PC con lo abierto primero. `estado`: abierto, resuelto o todos (solo lectura)."""
    if estado not in ("abierto", "resuelto", "todos"):
        raise ValueError("estado debe ser abierto, resuelto o todos")
    with conexion() as con:
        if not memoria.existe(con, "changelog"):
            return {"total": 0, "abiertos": 0, "entradas": []}
        filtro, par = ("", ()) if estado == "todos" else ("WHERE estado=?", (estado,))
        filas = con.execute(f"SELECT * FROM changelog {filtro} ORDER BY estado='resuelto', fecha DESC, id DESC LIMIT ?", (*par, n)).fetchall()
        abiertos = con.execute("SELECT COUNT(*) FROM changelog WHERE estado='abierto'").fetchone()[0]
        return {"total": len(filas), "abiertos": abiertos, "entradas": [dict(f) for f in filas]}


@app.get("/api/entorno")
def entorno(desde: str = "7d"):
    """Perfil actual del equipo y cambios de paquetes y kernel desde `desde`."""
    with conexion():
        return {"perfil": server.perfil_entorno(), "cambios": server.cambios_entorno(desde)}


@app.get("/api/limitaciones")
def limitaciones():
    """Qué no se puede medir y por qué, qué sensores siguen aprendiendo y cuánto les falta."""
    with conexion() as con:
        return {"no_disponible": estado_vivo(con)["no_disponible"], "fijas": consultas.LIMITACIONES_FIJAS,
                "aprendizaje": consultas.aprendizaje(con)}


@app.get("/api/sesiones")
def sesiones(tipo: str = "", dias: int = Query(30, ge=1, le=365)):
    """Sesiones de actividad (juegos) con la temperatura máxima de CPU y GPU de cada una."""
    with conexion() as con:
        filas, resumen = consultas.sesiones(con, tipo, dias, 200)
        return {"sesiones": filas, "por_juego": resumen}


@app.get("/api/acciones")
def acciones(dias: int = Query(30, ge=1, le=365), limite: int = Query(100, ge=1, le=500)):
    """Historial de acciones que modificaron algo (limpiezas, restauraciones, marcas de revisión...)."""
    import json
    with conexion() as con:
        filas = con.execute("SELECT rowid AS id, * FROM acciones WHERE ts >= ? ORDER BY ts DESC, id DESC LIMIT ?",
                            (db.ahora() - dias * 86400, limite)).fetchall()
        res = []
        for f in filas:
            d = dict(f)
            try:
                d["parametros"] = json.loads(d["parametros"]) if d.get("parametros") else None
            except ValueError:
                pass
            res.append(d)
        return {"acciones": res}


@app.get("/api/config")
def config():
    """Configuración actual. Las claves y tokens no se devuelven: solo si están cargadas o no."""
    def limpiar(x, clave=""):
        if isinstance(x, dict):
            return {k: limpiar(v, k) for k, v in x.items()}
        return {"cargada": bool(x)} if CLAVES_SECRETAS.search(clave) else x
    return limpiar(reputacion.cargar_config(crear=False)) | {"reporte_efectivo": limpiar(reporte.configuracion(crear=False))}


# ---------- frontend compilado ----------

if DIST.is_dir():
    if (DIST / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{ruta:path}")
    def pagina(ruta: str):
        """Sirve la app de una sola página; las rutas directas (/alerta/3, /componente/gpu) abren la misma página."""
        if ruta.startswith("api/"):
            raise HTTPException(404)
        archivo = (DIST / ruta).resolve()
        if ruta and archivo.is_file() and DIST.resolve() in archivo.parents:
            return FileResponse(archivo)
        return FileResponse(DIST / "index.html")

"""Remediación asistida: el catálogo CERRADO de acciones que pc-doctor sabe aplicar, su validación y su ejecutor.

Principios (ver la bitácora, módulo `remediacion`):
- El modelo nunca ejecuta nada: propone un nombre del catálogo y parámetros. Acá se validan y se corren.
- Lo que no está en `CATALOGO`, o trae parámetros que no validan, se rechaza y el rechazo queda registrado.
- Todo lo que llega (nombres de procesos, rutas, parámetros) es no confiable. Ningún texto se interpreta como orden ni se pasa a un shell.
- Nada se borra: las limpiezas mueven a cuarentena y se pueden restaurar.
- Sin root. Los comandos externos pasan por `db.ejecutar()`.
"""

import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import psutil

import db
import plataforma
import reputacion
from db import ejecutar, log

MAX_LISTA = 20                # máximo de elementos listados en una simulación
DIAS_MAX = 3650
PERFILES = ("balanced", "power-saver", "performance")
ESPERA_CIERRE_S = 5           # cuánto se espera a que un proceso cierre tras SIGTERM (nunca se fuerza)

# Procesos que `cerrar_proceso` nunca toca: la sesión gráfica, los servicios de la sesión, pc-doctor y Claude Code.
PROTEGIDOS_EXACTOS = {"claude", "init", "login", "sshd", "cron", "Xorg", "Xwayland", "mutter", "kwin_wayland", "kwin_x11",
                      "plasmashell", "cinnamon", "xfwm4", "openbox", "i3", "sway", "Hyprland", "polkitd", "NetworkManager",
                      "dbus-daemon", "dbus-broker", "upowerd", "udisksd", "bluetoothd", "tmux", "screen"}
PROTEGIDOS_PREFIJOS = ("gnome-", "gsd-", "gdm", "systemd", "xdg-", "pipewire", "wireplumber", "pulse", "dbus", "at-spi", "ibus",
                       "kded", "ksmserver", "xfce4-", "polkit", "gvfs", "evolution-", "fcitx", "tracker-", "pc-doctor")


class Rechazo(Exception):
    """Una acción o sus parámetros no pasan la validación. El texto es el motivo (se registra y se muestra)."""


# ---------- parámetros ----------

@dataclass(frozen=True)
class Param:
    """Un parámetro de una acción con su validación estricta: nada se convierte ni se completa por el camino."""
    tipo: str                         # 'entero', 'texto' u 'opcion'
    descripcion: str
    minimo: int | None = None
    maximo: int | None = None
    patron: str | None = None         # para 'texto': expresión que tiene que coincidir entera
    largo_max: int = 64
    opciones: tuple = ()

    def validar(self, nombre: str, valor):
        if self.tipo == "entero":
            if type(valor) is not int:   # ni bool ni "5" ni 5.0
                raise Rechazo(f"`{nombre}` debe ser un entero")
            if (self.minimo is not None and valor < self.minimo) or (self.maximo is not None and valor > self.maximo):
                raise Rechazo(f"`{nombre}` fuera de rango ({self.minimo} a {self.maximo})")
        elif self.tipo == "opcion":
            if not isinstance(valor, str) or valor not in self.opciones:
                raise Rechazo(f"`{nombre}` debe ser una de: {', '.join(self.opciones)}")
        elif self.tipo == "texto":
            if not isinstance(valor, str) or not 1 <= len(valor) <= self.largo_max:
                raise Rechazo(f"`{nombre}` debe ser un texto de 1 a {self.largo_max} caracteres")
            if self.patron and not re.fullmatch(self.patron, valor, re.ASCII):
                raise Rechazo(f"`{nombre}` tiene caracteres no permitidos")
        else:
            raise Rechazo(f"tipo de parámetro desconocido: {self.tipo}")
        return valor

    def describir(self) -> dict:
        d = {"tipo": self.tipo, "descripcion": self.descripcion}
        if self.tipo == "entero":
            d.update(minimo=self.minimo, maximo=self.maximo)
        if self.tipo == "opcion":
            d["opciones"] = list(self.opciones)
        return d


@dataclass(frozen=True)
class Accion:
    """Una entrada del catálogo. `ejecutar` devuelve {"ok", "resumen", "deshacer": dict|None, ...datos}; `simular` no cambia nada."""
    nombre: str
    descripcion: str                  # la que lee el modelo
    parametros: dict
    riesgo: str                       # 'bajo' o 'medio'
    preaprobable: bool
    efecto: str                       # qué debería pasar si funcionó (texto para el usuario)
    simular: Callable
    ejecutar: Callable
    verificar: Callable               # (parametros, resultado) -> (bool, texto): ¿se cumplió el efecto esperado?
    deshacer: Callable | None = None  # (info, con) -> {"ok", "resumen"}; None si no es reversible
    como_deshacer: str = "no se puede deshacer"
    plataformas: tuple = ("linux",)
    reutilizable: bool = True         # False si sus parámetros solo valen una vez (un pid): nunca entra en una receta

    @property
    def reversible(self) -> bool:
        return self.deshacer is not None


# ---------- utilidades comunes ----------

def _tamano(ruta: Path) -> int:
    """Bytes de un archivo o de una carpeta (sin seguir enlaces simbólicos)."""
    try:
        if ruta.is_symlink():
            return 0
        if ruta.is_file():
            return ruta.stat().st_size
    except OSError:
        return 0
    total = 0
    for dirpath, _, nombres in os.walk(ruta, followlinks=False):
        for n in nombres:
            p = Path(dirpath) / n
            try:
                if not p.is_symlink():
                    total += p.stat().st_size
            except OSError:
                pass
    return total


def _mb(n: int) -> float:
    return round(n / 1048576, 1)


def _destino_libre(destino: Path) -> Path:
    """Si `destino` ya existe agrega `.1`, `.2`... antes de la extensión (a una carpeta, al final): nunca pisa nada."""
    if not destino.exists():
        return destino
    n = 1
    while True:
        if destino.is_dir():
            nuevo = destino.with_name(f"{destino.name}.{n}")
        else:
            nuevo = destino.with_name(f"{destino.stem}.{n}{destino.suffix}")
        if not nuevo.exists():
            return nuevo
        n += 1


def _registrar_accion(con, tool: str, parametros, resultado: str) -> None:
    """Deja constancia en la tabla `acciones` (los parámetros pueden ser basura: se serializan sin fallar y se acortan)."""
    try:
        texto = json.dumps(parametros, ensure_ascii=False, default=repr)
    except (TypeError, ValueError):
        texto = repr(parametros)
    con.execute("INSERT INTO acciones (ts, tool, parametros, resultado) VALUES (?,?,?,?)",
                (db.ahora(), tool, texto[:500], resultado[:500]))
    con.commit()


def _guardar(con, plan_id, accion: str, parametros, estado: str, resultado: dict, deshacer: dict | None) -> int:
    """Registra una ejecución (o un rechazo) en `ejecuciones` y en `acciones`. Devuelve el id de la ejecución."""
    def js(x):
        try:
            return json.dumps(x, ensure_ascii=False, default=repr)
        except (TypeError, ValueError):
            return json.dumps(repr(x))
    cur = con.execute(
        "INSERT INTO ejecuciones (ts, plan_id, accion, parametros, estado, resultado, deshacer) VALUES (?,?,?,?,?,?,?)",
        (db.ahora(), plan_id, str(accion)[:80], js(parametros)[:2000], estado, js(resultado)[:4000],
         js(deshacer) if deshacer else None))
    con.commit()
    _registrar_accion(con, f"remediacion:{str(accion)[:60]}", parametros, f"{estado}: {resultado.get('resumen') or resultado.get('error') or ''}")
    return cur.lastrowid


def mover_a_cuarentena(con, origen: Path, destino_base: Path, rel: Path) -> tuple[Path, int]:
    """Mueve `origen` (archivo o carpeta) a `destino_base/rel` sin pisar nada y lo anota en `cuarentena`. Devuelve (destino, id)."""
    tam = _tamano(origen)
    destino = _destino_libre(destino_base / rel)
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(origen), str(destino))
    cur = con.execute("INSERT INTO cuarentena (ruta_original, ruta_nueva, tamano_bytes, movido_en) VALUES (?,?,?,?)",
                      (str(origen), str(destino), tam, db.ahora()))
    con.commit()
    return destino, cur.lastrowid


def restaurar_cuarentena(con, id: int) -> dict:
    """Devuelve a su ruta original lo que está en cuarentena con ese `id` (archivo o carpeta). No pisa nada existente."""
    r = con.execute("SELECT * FROM cuarentena WHERE id=?", (id,)).fetchone()
    if not r:
        return {"error": f"No existe el registro de cuarentena {id}."}
    if r["restaurado"]:
        return {"error": "Ese archivo ya fue restaurado."}
    origen, destino = Path(r["ruta_nueva"]), Path(r["ruta_original"])
    if origen.is_symlink() or not origen.exists():
        return {"error": f"El archivo en cuarentena no existe: {origen}"}
    if destino.exists() or destino.is_symlink():
        return {"error": f"Ya existe un archivo en la ruta original, no lo piso: {destino}"}
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(origen), str(destino))
    except OSError as e:
        return {"error": f"No se pudo restaurar: {e}"}
    con.execute("UPDATE cuarentena SET restaurado=1 WHERE id=?", (id,))
    con.commit()
    return {"restaurado": str(destino)}


def _restaurar_ids(con, info: dict) -> dict:
    """Deshacer común de las limpiezas: restaura cada id de cuarentena de la ejecución (los ya restaurados no cuentan como error)."""
    ids = info.get("cuarentena_ids")
    if not isinstance(ids, list) or not all(type(i) is int for i in ids):
        return {"ok": False, "resumen": "no hay con qué deshacer (ids de cuarentena inválidos)"}
    hechos, omitidos = 0, []
    for i in ids:
        r = restaurar_cuarentena(con, i)
        if "restaurado" in r:
            hechos += 1
        elif "ya fue restaurado" not in r["error"]:
            omitidos.append(r["error"][:120])
    ok = not omitidos
    return {"ok": ok, "completo": ok, "resumen": f"restaurados {hechos} de {len(ids)}" + (f"; omitidos {len(omitidos)}" if omitidos else ""),
            "omitidos": omitidos[:5]}


# ---------- limpiar_descargas_viejas (la lógica de la tool del MCP vive acá) ----------

def _limpiar_descargas(dias: int, simular: bool, raiz: Path | None = None, tool: str = "limpiar_descargas_viejas",
                       sub: str = "") -> tuple[dict, list[int]]:
    """Devuelve (respuesta, ids de cuarentena). La respuesta es la que muestra la tool `limpiar_descargas_viejas`.
    Con `raiz` limpia esa carpeta (ya validada por quien llama) en vez de Descargas, anotando `tool` en las acciones."""
    raiz = raiz or db.carpeta_descargas()
    if raiz is None:
        return {"error": "No existe ~/Descargas ni ~/Downloads."}, []
    raiz_real = raiz.resolve()
    corte = time.time() - dias * 86400

    candidatos = []
    for dirpath, _, nombres in os.walk(raiz_real, followlinks=False):
        for nombre in nombres:
            p = Path(dirpath) / nombre
            try:
                if p.is_symlink() or not p.is_file():
                    continue
                st = p.stat()
                if plataforma.actual().fecha_archivo(st) < corte and p.resolve().is_relative_to(raiz_real):
                    candidatos.append((p, st.st_size))
            except OSError:
                continue
    candidatos.sort(key=lambda c: c[1], reverse=True)
    total_mb = round(sum(s for _, s in candidatos) / 1048576, 1)
    # Resumen por elemento de primer nivel (carpeta o archivo suelto) para mantener la respuesta compacta
    grupos: dict[str, list[float]] = {}
    for p, tam in candidatos:
        g = grupos.setdefault(p.relative_to(raiz_real).parts[0], [0, 0.0])
        g[0] += 1
        g[1] += tam / 1048576
    muestra = [{"elemento": k, "archivos": v[0], "mb": round(v[1], 1)}
               for k, v in sorted(grupos.items(), key=lambda kv: kv[1][1], reverse=True)[:MAX_LISTA]]

    if simular:
        return {"modo": "simulación", "carpeta": str(raiz_real), "archivos": len(candidatos),
                "total_mb": total_mb, "elementos": len(grupos), "por_elemento": muestra,
                "nota": "No se movió nada. Llamá con simular=False para mover a cuarentena."}, []

    destino_base = db.DIR_CUARENTENA / datetime.now().strftime("%Y-%m-%d") / sub
    con = db.conectar(escribir=True)
    movidos, errores, ids = 0, [], []
    try:
        for p, tam in candidatos:
            rel = p.relative_to(raiz_real)
            try:
                destino, id_c = mover_a_cuarentena(con, p, destino_base, rel)
            except OSError as e:
                errores.append(f"{rel}: {e}")
                continue
            ids.append(id_c)
            _registrar_accion(con, tool, {"archivo": str(p), "dias": dias}, f"movido a {destino}")
            movidos += 1
    finally:
        con.close()
    return {"modo": "ejecución", "movidos": movidos, "total_mb": total_mb, "cuarentena": str(destino_base),
            "errores": errores[:5], "no_movidos": len(errores), "restaurar": "usá restaurar_cuarentena(id)"}, ids


def limpiar_descargas(dias: int, simular: bool) -> dict:
    """La tool `limpiar_descargas_viejas` del MCP (con `dias` ya validado como mínimo 1)."""
    return _limpiar_descargas(dias, simular)[0]


def _descargas_simular(p: dict) -> dict:
    r, _ = _limpiar_descargas(p["dias"], True)
    if "error" in r:
        return r
    return {"modo": "simulación", "resumen": f"movería {r['archivos']} archivos ({r['total_mb']} MB) de {r['carpeta']} a cuarentena",
            "archivos": r["archivos"], "mb": r["total_mb"], "por_elemento": r["por_elemento"][:5]}


def _descargas_ejecutar(p: dict) -> dict:
    r, ids = _limpiar_descargas(p["dias"], False)
    if "error" in r:
        return {"ok": False, "resumen": r["error"]}
    return {"ok": not r["errores"] or r["movidos"] > 0, "resumen": f"movidos {r['movidos']} archivos ({r['total_mb']} MB) a cuarentena",
            "movidos": r["movidos"], "errores": r["errores"], "deshacer": {"cuarentena_ids": ids} if ids else None}


def _descargas_verificar(p: dict, resultado: dict) -> tuple[bool, str]:
    r, _ = _limpiar_descargas(p["dias"], True)
    if "error" in r:
        return False, r["error"]
    return r["archivos"] == 0, f"quedan {r['archivos']} archivos más viejos que {p['dias']} días"


# ---------- cachés (miniaturas, uv, pip) ----------

def _raiz_cache() -> Path:
    """~/.cache, o $XDG_CACHE_HOME si apunta adentro del HOME (cualquier otra ruta se ignora)."""
    home = Path.home().resolve()
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        p = Path(xdg).expanduser()
        if p.is_absolute() and p.resolve().is_relative_to(home):
            return p.resolve()
    return home / ".cache"


def _carpetas_cache(clave: str) -> list[Path]:
    """Las carpetas de caché de cada tipo que existen de verdad, dentro del HOME y sin ser enlaces simbólicos."""
    home = Path.home().resolve()
    if plataforma.NOMBRE == "windows":   # la caché de miniaturas de Windows la bloquea el Explorador: no se ofrece
        local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
        rutas = {"uv": [local / "uv" / "cache"], "pip": [local / "pip" / "Cache"]}.get(clave, [])
    else:
        rutas = {"miniaturas": [_raiz_cache() / "thumbnails", home / ".thumbnails"],
                 "uv": [_raiz_cache() / "uv"], "pip": [_raiz_cache() / "pip"]}[clave]
    return [r for r in rutas if r.is_dir() and not r.is_symlink() and r.resolve().is_relative_to(home)]


def _entradas_cache(carpeta: Path) -> list[Path]:
    """Lo que se mueve de una caché: sus elementos de primer nivel, sin ocultos (candados) ni enlaces simbólicos."""
    try:
        return sorted(e for e in carpeta.iterdir() if not e.name.startswith(".") and e.name != "CACHEDIR.TAG" and not e.is_symlink())
    except OSError:
        return []


def _en_uso(nombres: set[str]) -> str | None:
    """Nombre del primer proceso en marcha de `nombres` (una caché en uso no se toca).

    Los ancestros de pc-doctor no cuentan: el recolector y el dashboard corren bajo `uv run`, y se bloquearían a sí mismos."""
    propios = {os.getpid()} | {a.pid for a in psutil.Process().parents()}
    for p in psutil.process_iter(["name"]):
        if p.pid not in propios and (p.info.get("name") or "").lower().removesuffix(".exe") in nombres:
            return p.info["name"]
    return None


_PROCESOS_CACHE = {"miniaturas": set(), "uv": {"uv", "uvx"}, "pip": {"pip", "pip3"}}


def _carpeta_temporal() -> Path | None:
    """La carpeta de temporales del usuario (%TEMP%), solo si está dentro de su perfil, no es un enlace y existe. Nada del sistema."""
    crudo = os.environ.get("TEMP") or os.environ.get("TMP")
    if not crudo:
        return None
    t = Path(crudo)
    home = Path.home().resolve()
    if not t.is_absolute() or t.is_symlink() or not t.is_dir() or not t.resolve().is_relative_to(home) or t.resolve() == home:
        return None
    return t


def _temporales(p: dict, simular: bool) -> tuple[dict, list[int]]:
    t = _carpeta_temporal()
    if t is None:
        return {"error": "La carpeta de temporales no está dentro de tu perfil: no se toca."}, []
    return _limpiar_descargas(p["dias"], simular, raiz=t, tool="limpiar_temporales_usuario", sub="temporales")


def _temporales_simular(p: dict) -> dict:
    r, _ = _temporales(p, True)
    if "error" in r:
        return r
    return {"modo": "simulación", "resumen": f"movería {r['archivos']} archivos ({r['total_mb']} MB) de {r['carpeta']} a cuarentena "
            "(los que Windows tenga en uso se saltean)", "archivos": r["archivos"], "mb": r["total_mb"], "por_elemento": r["por_elemento"][:5]}


def _temporales_ejecutar(p: dict) -> dict:
    r, ids = _temporales(p, False)
    if "error" in r:
        return {"ok": False, "resumen": r["error"]}
    return {"ok": r["movidos"] > 0 or not r["errores"], "resumen": f"movidos {r['movidos']} archivos ({r['total_mb']} MB) a cuarentena; "
            f"{r['no_movidos']} en uso o sin permiso se dejaron", "movidos": r["movidos"], "no_movidos": r["no_movidos"], "errores": r["errores"],
            "deshacer": {"cuarentena_ids": ids} if ids else None}


def _temporales_verificar(p: dict, resultado: dict) -> tuple[bool, str]:
    r, _ = _temporales(p, True)
    if "error" in r:
        return False, r["error"]
    return r["archivos"] <= resultado.get("no_movidos", 0), f"quedan {r['archivos']} archivos más viejos que {p['dias']} días"


def _cache_simular(clave: str) -> dict:
    carpetas = _carpetas_cache(clave)
    if not carpetas:
        return {"modo": "simulación", "resumen": "no hay caché que mover", "mb": 0.0, "elementos": 0}
    entradas = [e for c in carpetas for e in _entradas_cache(c)]
    tam = sum(_tamano(e) for e in entradas)
    uso = _en_uso(_PROCESOS_CACHE[clave])
    nota = f" (ahora hay un proceso {uso} en marcha: no se movería)" if uso else ""
    return {"modo": "simulación", "resumen": f"movería {len(entradas)} elementos ({_mb(tam)} MB) de {', '.join(str(c) for c in carpetas)} a cuarentena{nota}",
            "mb": _mb(tam), "elementos": len(entradas)}


def _cache_tamano(clave: str) -> int:
    return sum(_tamano(e) for c in _carpetas_cache(clave) for e in _entradas_cache(c))


def _cache_ejecutar(clave: str) -> dict:
    uso = _en_uso(_PROCESOS_CACHE[clave])
    if uso:
        return {"ok": False, "resumen": f"hay un proceso {uso} en marcha; no se toca su caché"}
    carpetas = _carpetas_cache(clave)
    antes = _cache_tamano(clave)
    destino_base = db.DIR_CUARENTENA / datetime.now().strftime("%Y-%m-%d") / f"cache-{clave}"
    con = db.conectar(escribir=True)
    ids, errores = [], []
    try:
        for c in carpetas:
            for e in _entradas_cache(c):
                try:
                    _, id_c = mover_a_cuarentena(con, e, destino_base, Path(c.name) / e.name)
                    ids.append(id_c)
                except OSError as ex:
                    errores.append(f"{e.name}: {ex}")
    finally:
        con.close()
    return {"ok": bool(ids) or (not errores), "resumen": f"movidos {len(ids)} elementos ({_mb(antes)} MB) a cuarentena",
            "bytes_antes": antes, "errores": errores[:5], "deshacer": {"cuarentena_ids": ids} if ids else None}


def _cache_verificar(clave: str):
    def verificar(p: dict, resultado: dict) -> tuple[bool, str]:
        antes, ahora = resultado.get("bytes_antes", 0), _cache_tamano(clave)
        return ahora < antes or antes == 0, f"la caché pesa {_mb(ahora)} MB (antes {_mb(antes)} MB)"
    return verificar


def _accion_cache(clave: str, etiqueta: str, donde: str, plataformas: tuple = ("linux",)) -> Accion:
    return Accion(
        nombre=f"limpiar_cache_{clave}", descripcion=f"Mueve a cuarentena la caché de {etiqueta} ({donde}). Se regenera sola; no borra nada.",
        parametros={}, riesgo="bajo", preaprobable=True, efecto=f"la caché de {etiqueta} pesa menos que antes",
        simular=lambda p: _cache_simular(clave), ejecutar=lambda p: _cache_ejecutar(clave), verificar=_cache_verificar(clave),
        deshacer=lambda info, con: _restaurar_ids(con, info), como_deshacer="restaura lo movido a su lugar (si no se regeneró ahí)", plataformas=plataformas)


# ---------- reiniciar_servicio_usuario ----------

_PATRON_SERVICIO = r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,63}"


def _unidad(nombre: str) -> str:
    return nombre if nombre.endswith(".service") else f"{nombre}.service"


def _servicios_permitidos() -> set[str]:
    """La lista de `config.json -> remediacion -> servicios_permitidos` (vacía por defecto); lo que no sea texto válido se ignora."""
    cfg = reputacion.cargar_config(crear=False).get("remediacion")
    lista = cfg.get("servicios_permitidos") if isinstance(cfg, dict) else None
    if not isinstance(lista, list):
        return set()
    return {_unidad(s) for s in lista if isinstance(s, str) and re.fullmatch(_PATRON_SERVICIO, s, re.ASCII)}


def _unidad_permitida(p: dict) -> str:
    unidad = _unidad(p["nombre"])
    if unidad not in _servicios_permitidos():
        raise Rechazo(f"el servicio `{p['nombre']}` no está en la lista permitida de config.json (remediacion.servicios_permitidos)")
    return unidad


def _servicio_activo(unidad: str) -> bool:
    salida = ejecutar(["systemctl", "--user", "is-active", unidad])
    return bool(salida) and salida.strip() == "active"


def _servicio_simular(p: dict) -> dict:
    unidad = _unidad_permitida(p)
    return {"modo": "simulación", "resumen": f"reiniciaría el servicio de usuario {unidad} (ahora: {'activo' if _servicio_activo(unidad) else 'no activo'})"}


def _servicio_ejecutar(p: dict) -> dict:
    unidad = _unidad_permitida(p)
    if ejecutar(["systemctl", "--user", "restart", unidad], timeout=60) is None:
        return {"ok": False, "resumen": f"no se pudo reiniciar {unidad}"}
    return {"ok": True, "resumen": f"reiniciado {unidad}", "unidad": unidad, "deshacer": None}


def _servicio_verificar(p: dict, resultado: dict) -> tuple[bool, str]:
    unidad = _unidad(p["nombre"])
    for _ in range(10):   # un servicio puede tardar unos segundos en volver
        if _servicio_activo(unidad):
            return True, f"{unidad} está activo"
        time.sleep(0.5)
    return False, f"{unidad} no está activo"


# ---------- cambiar_perfil_energia ----------

# Windows: planes de energía estándar por su GUID (los alias de powercfg SCHEME_MIN/MAX confunden: se usan los identificadores).
PLANES_WINDOWS = {"balanced": "381b4222-f694-41f0-9685-ff5bb260df2e", "power-saver": "a1841308-3541-4fab-bc81-f71556f20b4a",
                  "performance": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"}
_GUID = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}")


def _plan_activo_windows() -> str | None:
    salida = ejecutar(["powercfg", "/getactivescheme"])
    m = _GUID.search(salida or "")
    return m.group().lower() if m else None


def _planes_existentes_windows() -> set[str]:
    return {g.lower() for g in _GUID.findall(ejecutar(["powercfg", "/list"]) or "")}


def _perfil_actual() -> str | None:
    if plataforma.NOMBRE == "windows":   # un plan que no es de los tres estándar (p. ej. el del fabricante) se trata como "no pude leerlo"
        guid = _plan_activo_windows()
        return next((n for n, g in PLANES_WINDOWS.items() if g == guid), None)
    salida = ejecutar(["powerprofilesctl", "get"])
    perfil = salida.strip() if salida else None
    return perfil if perfil in PERFILES else None


def _perfil_poner(perfil: str) -> bool:
    """Pone el perfil (Linux: powerprofilesctl; Windows: powercfg /setactive solo con el plan estándar si existe en esta PC)."""
    if plataforma.NOMBRE == "windows":
        guid = PLANES_WINDOWS.get(perfil)
        if guid is None or guid not in _planes_existentes_windows():
            log.warning("el plan de energía %s no existe en esta PC", perfil)
            return False
        return ejecutar(["powercfg", "/setactive", guid]) is not None
    return ejecutar(["powerprofilesctl", "set", perfil]) is not None


def _perfil_simular(p: dict) -> dict:
    actual = _perfil_actual()
    if actual is None:
        return {"modo": "simulación", "resumen": f"pasaría el perfil de energía a {p['perfil']} (no pude leer el actual)"}
    return {"modo": "simulación", "resumen": f"pasaría el perfil de energía de {actual} a {p['perfil']}" if actual != p["perfil"]
            else f"el perfil de energía ya es {actual}: no cambiaría nada"}


def _perfil_ejecutar(p: dict) -> dict:
    anterior = _perfil_actual()
    if anterior is None:
        return {"ok": False, "resumen": "no pude leer el perfil de energía actual (¿power-profiles-daemon? en Windows, un plan que no es estándar tampoco se toca)"}
    if anterior == p["perfil"]:
        return {"ok": True, "resumen": f"el perfil ya era {anterior}", "deshacer": None}
    if not _perfil_poner(p["perfil"]):
        return {"ok": False, "resumen": f"no se pudo poner el perfil {p['perfil']}" + (" (ese plan no existe en esta PC)" if plataforma.NOMBRE == "windows" else "")}
    return {"ok": True, "resumen": f"perfil de energía: {anterior} → {p['perfil']}", "anterior": anterior, "deshacer": {"perfil": anterior}}


def _perfil_deshacer(info: dict, con) -> dict:
    anterior = info.get("perfil")
    if anterior not in PERFILES:
        return {"ok": False, "resumen": "no hay con qué deshacer (perfil anterior inválido)"}
    if not _perfil_poner(anterior):
        return {"ok": False, "resumen": f"no se pudo volver al perfil {anterior}"}
    return {"ok": True, "resumen": f"perfil de energía devuelto a {anterior}"}


def _perfil_verificar(p: dict, resultado: dict) -> tuple[bool, str]:
    actual = _perfil_actual()
    return actual == p["perfil"], f"el perfil es {actual}"


# ---------- cerrar_proceso ----------

def _proceso_a_cerrar(p: dict) -> psutil.Process:
    """Devuelve el proceso si es de este usuario, no está protegido y su nombre coincide con el esperado; si no, lanza Rechazo."""
    pid, esperado = p["pid"], p["nombre_esperado"]
    propio = psutil.Process()
    if pid in (propio.pid, os.getpid()) or pid in {a.pid for a in propio.parents()}:
        raise Rechazo("ese proceso es pc-doctor o lo que lo ejecuta (terminal, shell, Claude Code)")
    try:
        proc = psutil.Process(pid)
        with proc.oneshot():
            nombre, uid, cmd = proc.name(), proc.uids().real, proc.cmdline()
    except psutil.NoSuchProcess:
        raise Rechazo(f"no existe el proceso {pid}")
    except psutil.AccessDenied:
        raise Rechazo(f"sin permiso para ver el proceso {pid}")
    if uid != os.getuid():
        raise Rechazo("el proceso no es de tu usuario")
    if nombre != esperado:
        raise Rechazo(f"el proceso {pid} se llama `{nombre[:40]}` y no `{esperado}`")
    linea = " ".join(cmd).lower()
    if (nombre in PROTEGIDOS_EXACTOS or nombre.startswith(PROTEGIDOS_PREFIJOS) or "pc-doctor" in linea
            or re.search(r"(^|/)claude(\s|$)", linea)):
        raise Rechazo(f"`{nombre[:40]}` es un proceso protegido (sesión gráfica, servicios de la sesión, pc-doctor o Claude Code)")
    return proc


def _proceso_simular(p: dict) -> dict:
    proc = _proceso_a_cerrar(p)
    try:
        ram = _mb(proc.memory_info().rss)
    except psutil.Error:
        ram = None
    return {"modo": "simulación", "resumen": f"cerraría (SIGTERM, sin forzar) el proceso {p['nombre_esperado']} (pid {p['pid']}), ram {ram} MB",
            "ram_mb": ram, "linea_de_comandos": " ".join(proc.cmdline())[:120]}


def _proceso_ejecutar(p: dict) -> dict:
    proc = _proceso_a_cerrar(p)
    inicio = proc.create_time()
    try:
        proc.terminate()   # psutil comprueba que el pid no se haya reutilizado
        proc.wait(ESPERA_CIERRE_S)
    except psutil.TimeoutExpired:
        return {"ok": False, "resumen": f"el proceso {p['nombre_esperado']} no cerró en {ESPERA_CIERRE_S} s (no se fuerza)", "inicio": inicio}
    except psutil.NoSuchProcess:
        pass
    except psutil.AccessDenied:
        return {"ok": False, "resumen": "sin permiso para cerrarlo"}
    return {"ok": True, "resumen": f"cerrado {p['nombre_esperado']} (pid {p['pid']})", "inicio": inicio, "deshacer": None}


def _proceso_verificar(p: dict, resultado: dict) -> tuple[bool, str]:
    try:
        vivo = psutil.Process(p["pid"]).create_time() == resultado.get("inicio") and psutil.Process(p["pid"]).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        vivo = False
    except psutil.Error:
        vivo = True
    return not vivo, "el proceso ya no está" if not vivo else "el proceso sigue vivo"


# ---------- el catálogo ----------

_P_DIAS = Param("entero", "Archivos más viejos que estos días (1 a 3650)", minimo=1, maximo=DIAS_MAX)

CATALOGO: dict[str, Accion] = {a.nombre: a for a in (
    _accion_cache("miniaturas", "miniaturas", "~/.cache/thumbnails"),
    _accion_cache("uv", "uv", "~/.cache/uv", ("linux", "windows")),
    _accion_cache("pip", "pip", "~/.cache/pip", ("linux", "windows")),
    Accion(
        nombre="limpiar_descargas_viejas", descripcion="Mueve a cuarentena los archivos de Descargas más viejos que `dias`. No borra nada.",
        parametros={"dias": _P_DIAS}, riesgo="bajo", preaprobable=False, efecto="no quedan archivos más viejos que `dias` en Descargas",
        simular=_descargas_simular, ejecutar=_descargas_ejecutar, verificar=_descargas_verificar,
        deshacer=lambda info, con: _restaurar_ids(con, info), como_deshacer="restaura cada archivo a su ruta original (restaurar_cuarentena)",
        plataformas=("linux", "windows")),
    Accion(
        nombre="limpiar_temporales_usuario", descripcion="Mueve a cuarentena los archivos de la carpeta de temporales del usuario más viejos que `dias` "
                                                          "(los que Windows tiene en uso se saltean). No borra nada.",
        parametros={"dias": _P_DIAS}, riesgo="bajo", preaprobable=False, efecto="no quedan archivos más viejos que `dias` en los temporales (salvo los en uso)",
        simular=_temporales_simular, ejecutar=_temporales_ejecutar, verificar=_temporales_verificar,
        deshacer=lambda info, con: _restaurar_ids(con, info), como_deshacer="restaura cada archivo a su ruta original (restaurar_cuarentena)",
        plataformas=("windows",)),
    Accion(
        nombre="reiniciar_servicio_usuario", descripcion="Reinicia un servicio systemd del usuario, solo si está en la lista permitida de config.json.",
        parametros={"nombre": Param("texto", "Nombre del servicio (de la lista permitida)", patron=_PATRON_SERVICIO)},
        riesgo="medio", preaprobable=False, efecto="el servicio queda activo", simular=_servicio_simular,
        ejecutar=_servicio_ejecutar, verificar=_servicio_verificar),
    Accion(
        nombre="cambiar_perfil_energia", descripcion="Cambia el perfil de energía (balanced, power-saver o performance); guarda el anterior.",
        parametros={"perfil": Param("opcion", "Perfil de energía", opciones=PERFILES)}, riesgo="bajo", preaprobable=False,
        efecto="el perfil de energía es el pedido", simular=_perfil_simular, ejecutar=_perfil_ejecutar, verificar=_perfil_verificar,
        deshacer=_perfil_deshacer, como_deshacer="vuelve al perfil anterior", plataformas=("linux", "windows")),
    Accion(
        nombre="cerrar_proceso",
        descripcion="Cierra (SIGTERM, nunca a la fuerza) un proceso del usuario, solo si su nombre coincide con `nombre_esperado`. "
                    "Nunca procesos del sistema, de la sesión gráfica, de pc-doctor ni de Claude Code.",
        parametros={"pid": Param("entero", "Número de proceso", minimo=2, maximo=4194304),
                    "nombre_esperado": Param("texto", "Nombre exacto del proceso", patron=r"[A-Za-z0-9._+:@ -]+")},
        riesgo="medio", preaprobable=False, efecto="el proceso ya no existe", simular=_proceso_simular,
        ejecutar=_proceso_ejecutar, verificar=_proceso_verificar, reutilizable=False),
)}


def disponibles() -> dict[str, Accion]:
    """Las acciones del catálogo que existen en esta plataforma."""
    return {n: a for n, a in CATALOGO.items() if plataforma.NOMBRE in a.plataformas}


def catalogo() -> list[dict]:
    """El catálogo como lo ve el modelo: nombre, descripción, parámetros y riesgo (nada de funciones ni rutas). Solo lo de esta plataforma."""
    return [{"nombre": a.nombre, "descripcion": a.descripcion, "parametros": {k: v.describir() for k, v in a.parametros.items()},
             "riesgo": a.riesgo, "reversible": a.reversible, "efecto_esperado": a.efecto} for a in disponibles().values()]


def validar(nombre, parametros) -> tuple[Accion, dict]:
    """Valida el nombre y los parámetros contra el catálogo. Lanza Rechazo; nunca completa ni convierte nada."""
    if not isinstance(nombre, str) or nombre not in CATALOGO:
        raise Rechazo("acción fuera del catálogo")
    accion = CATALOGO[nombre]
    if plataforma.NOMBRE not in accion.plataformas:
        raise Rechazo(f"la acción no está disponible en {plataforma.NOMBRE}")
    if not isinstance(parametros, dict):
        raise Rechazo("los parámetros deben ser un objeto")
    if not all(isinstance(k, str) for k in parametros) or set(parametros) - set(accion.parametros):
        raise Rechazo("parámetros desconocidos")
    faltan = set(accion.parametros) - set(parametros)
    if faltan:
        raise Rechazo(f"faltan parámetros: {', '.join(sorted(faltan))}")
    return accion, {k: p.validar(k, parametros[k]) for k, p in accion.parametros.items()}


# ---------- ejecutor ----------

def aplicar(nombre, parametros=None, *, simular: bool = True, plan_id: int | None = None) -> dict:
    """Simula (por defecto) o ejecuta una acción del catálogo. Todo rechazo y toda ejecución quedan registrados.

    Devuelve {"ok": bool, "resumen": ..., "ejecucion_id": ...} (o "rechazada": True con el motivo en "error").
    """
    parametros = {} if parametros is None else parametros
    con = db.conectar(escribir=True)
    try:
        try:
            accion, p = validar(nombre, parametros)
            if simular:
                return {"ok": True, "simulacion": True, "accion": nombre, **accion.simular(p)}
        except Rechazo as e:
            log.warning("remediación: acción rechazada (%s): %s", str(nombre)[:60], e)
            r = {"ok": False, "rechazada": True, "error": str(e), "resumen": f"rechazada: {e}"}
            r["ejecucion_id"] = _guardar(con, plan_id, nombre, parametros, "rechazada", r, None)
            return r
        try:
            r = accion.ejecutar(p)
        except Rechazo as e:   # lo que recién se ve al ejecutar (por ejemplo, el proceso cambió entre la simulación y ahora)
            r = {"ok": False, "rechazada": True, "error": str(e), "resumen": f"rechazada: {e}"}
            r["ejecucion_id"] = _guardar(con, plan_id, nombre, p, "rechazada", r, None)
            return r
        except Exception as e:   # un error inesperado de una acción no puede tirar al llamador
            log.warning("remediación: falló %s: %s", nombre, e)
            r = {"ok": False, "resumen": f"error inesperado: {type(e).__name__}"}
        deshacer = r.pop("deshacer", None) if accion.reversible else None
        r.pop("deshacer", None)
        r["accion"] = nombre
        r["parametros"] = p
        r["ejecucion_id"] = _guardar(con, plan_id, nombre, p, "aplicada" if r.get("ok") else "fallida", r, deshacer)
        return r
    finally:
        con.close()


def verificar_efecto(ejecucion_id: int) -> dict:
    """¿Se cumplió el efecto esperado de una ejecución? Devuelve {"cumplido": bool, "detalle": texto}."""
    con = db.conectar(escribir=True)
    try:
        e = con.execute("SELECT * FROM ejecuciones WHERE id=?", (ejecucion_id,)).fetchone()
    finally:
        con.close()
    if not e or e["accion"] not in CATALOGO or e["estado"] != "aplicada":
        return {"cumplido": False, "detalle": "no hay una ejecución aplicada con ese id"}
    try:
        ok, detalle = CATALOGO[e["accion"]].verificar(json.loads(e["parametros"]), json.loads(e["resultado"] or "{}"))
    except (ValueError, Rechazo, OSError) as ex:
        return {"cumplido": False, "detalle": f"no se pudo verificar: {ex}"}
    return {"cumplido": bool(ok), "detalle": detalle}


def deshacer(ejecucion_id: int) -> dict:
    """Deshace una ejecución reversible que todavía no se deshizo. Queda registrado."""
    con = db.conectar(escribir=True)
    try:
        e = con.execute("SELECT * FROM ejecuciones WHERE id=?", (ejecucion_id,)).fetchone()
        if not e:
            return {"ok": False, "error": f"No existe la ejecución {ejecucion_id}."}
        if e["estado"] != "aplicada" or e["deshacer"] is None or e["accion"] not in CATALOGO or not CATALOGO[e["accion"]].reversible:
            return {"ok": False, "error": "Esa ejecución no se puede deshacer."}
        if e["deshecha_en"] is not None:
            return {"ok": False, "error": "Esa ejecución ya se deshizo."}
        try:
            info = json.loads(e["deshacer"])
            r = CATALOGO[e["accion"]].deshacer(info if isinstance(info, dict) else {}, con)
        except (ValueError, OSError) as ex:
            r = {"ok": False, "resumen": f"no se pudo deshacer: {ex}"}
        if r.get("ok"):
            if r.get("completo", True):
                con.execute("UPDATE ejecuciones SET deshecha_en=? WHERE id=?", (db.ahora(), ejecucion_id))
                con.commit()
        _registrar_accion(con, f"remediacion:deshacer:{e['accion']}", {"ejecucion": ejecucion_id}, r.get("resumen", ""))
        return r
    finally:
        con.close()

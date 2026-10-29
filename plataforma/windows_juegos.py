"""Juegos en curso en Windows. Igual que en Linux, el cliente del launcher abierto no cuenta: solo cuenta el juego en sí.

Un proceso es un juego si su ejecutable está dentro de la carpeta de instalación de un juego conocido (Steam, Epic, GOG o Xbox);
si no hay ninguno, un proceso que tiene la ventana en primer plano a pantalla completa y usa mucha GPU cuenta como juego genérico.
Todo corre sin permisos especiales y solo mira los procesos del propio usuario.
"""

import json
import logging
import ntpath
import os
import re
import time
from pathlib import Path

import psutil

from . import windows_sensores

log = logging.getLogger("pc-doctor")

# Carpetas de steamapps/common que son herramientas y no juegos (las mismas que en Linux)
HERRAMIENTAS_STEAM = re.compile(r"^(SteamLinuxRuntime|Steam Linux Runtime|Proton|GE-Proton|Steamworks|Steam Controller|SteamVR|Steam\.dll)", re.I)
# Clientes de los launchers y programas de ayuda que viven junto a los juegos o los acompañan: no son el juego
CLIENTES = re.compile(r"(?i)^(steam|steamwebhelper|steamservice|steamerrorreporter\d*|epicgameslauncher|epicwebhelper|eosoverlayrenderer\w*|"
                      r"galaxyclient( helper)?|galaxycommunication|xboxpcapp\w*|gamebar\w*|gamingservices\w*|ubisoftconnect|upc|uplaywebcore|"
                      r"eadesktop|ealauncher|eabackgroundservice|origin|battle\.net|crashhandler\w*|unitycrashhandler\w*|crashreportclient|"
                      r"setup|unins\d*|vc_?redist\S*|dxsetup|installer|launcher)$")
SUBCARPETAS_AUXILIARES = ("\\_commonredist\\", "\\redist\\", "\\directx\\", "\\support\\", "\\__installer\\")
# Programas que pueden estar a pantalla completa con la GPU ocupada sin ser juegos
NO_SON_JUEGOS_PANTALLA_COMPLETA = re.compile(
    r"(?i)^(chrome|msedge|firefox|brave|opera|vlc|mpv|mpc-hc\w*|potplayer\w*|wmplayer|video\.ui|teams|ms-teams|zoom|slack|obs\d*|"
    r"powerpnt|excel|winword|explorer|mstsc|vmware\w*|virtualbox\w*|vboxsvc|blender|davinciresolve|premiere pro|afterfx|code|devenv)$")
GPU_MINIMA_PANTALLA_COMPLETA = 40.0   # % de uso de GPU del proceso para contar como juego genérico
TOLERANCIA_PX = 2


# ---------- catálogo de juegos instalados ----------

def parsear_bibliotecas_steam(texto: str) -> list[str]:
    """Rutas de las bibliotecas de Steam en libraryfolders.vdf (las barras vienen duplicadas: C:\\\\Juegos)."""
    return [m.replace("\\\\", "\\") for m in re.findall(r'"path"\s+"([^"]+)"', texto)]


def parsear_appmanifest(texto: str) -> dict | None:
    """{'appid', 'nombre', 'carpeta'} de un appmanifest de Steam; None si es una herramienta o está incompleto."""
    campo = lambda k: (re.search(rf'"{k}"\s+"([^"]*)"', texto) or [None, None])[1]
    appid, nombre, carpeta = campo("appid"), campo("name"), campo("installdir")
    if not (appid and nombre) or HERRAMIENTAS_STEAM.match(carpeta or nombre):
        return None
    return {"appid": appid, "nombre": nombre, "carpeta": carpeta}


def parsear_epic(texto: str) -> dict | None:
    """{'nombre', 'ruta'} de un manifiesto .item de Epic Games (JSON)."""
    try:
        d = json.loads(texto)
        return {"nombre": d["DisplayName"], "ruta": d["InstallLocation"]} if d.get("InstallLocation") and d.get("DisplayName") else None
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def _norm(ruta: str) -> str:
    return ntpath.normcase(ntpath.normpath(ruta))


def catalogo(appmanifests: dict[str, list[str]], epic: list[str], gog: list[dict], xbox: list[str]) -> list[dict]:
    """Juegos instalados: [{'nombre', 'raiz' (normalizada), 'origen'}].

    `appmanifests` es {carpeta steamapps: [texto de cada appmanifest]}; `epic`, los textos de los .item; `gog`, [{'nombre','ruta'}];
    `xbox`, las carpetas de juego de XboxGames."""
    res = []
    for lib, textos in appmanifests.items():
        conocidas = set()
        for t in textos:
            m = parsear_appmanifest(t)
            if m and m["carpeta"]:
                res.append({"nombre": m["nombre"], "raiz": _norm(ntpath.join(lib, "common", m["carpeta"])), "origen": "steam"})
                conocidas.add(m["carpeta"].lower())
        res.append({"nombre": None, "raiz": _norm(ntpath.join(lib, "common")), "origen": "steam_sin_manifiesto", "conocidas": conocidas})
    for t in epic:
        e = parsear_epic(t)
        if e:
            res.append({"nombre": e["nombre"], "raiz": _norm(e["ruta"]), "origen": "epic"})
    for g in gog:
        res.append({"nombre": g["nombre"], "raiz": _norm(g["ruta"]), "origen": "gog"})
    for carpeta in xbox:
        res.append({"nombre": ntpath.basename(carpeta.rstrip("\\")), "raiz": _norm(carpeta), "origen": "xbox"})
    return res


def juego_de(exe: str, juegos: list[dict]) -> str | None:
    """Nombre del juego al que pertenece un ejecutable, o None si no es de ninguno, es un cliente o es un auxiliar."""
    if not exe:
        return None
    ruta = _norm(exe)
    nombre_exe = ntpath.splitext(ntpath.basename(ruta))[0]
    if CLIENTES.match(nombre_exe) or any(s in ruta for s in SUBCARPETAS_AUXILIARES):
        return None
    for j in juegos:
        if not ruta.startswith(j["raiz"] + "\\"):
            continue
        if j["origen"] == "steam_sin_manifiesto":  # un juego en la biblioteca sin appmanifest: se reconoce por el nombre de su carpeta
            carpeta = ruta[len(j["raiz"]) + 1:].split("\\")[0]
            if carpeta in j["conocidas"] or HERRAMIENTAS_STEAM.match(carpeta):
                continue
            return carpeta
        return j["nombre"]
    return None


# ---------- pantalla completa ----------

def es_pantalla_completa(ventana: dict | None) -> bool:
    """True si la ventana cubre todo el monitor. `ventana` = {'pid', 'rect': (l,t,r,b), 'monitor': (l,t,r,b)}."""
    if not ventana:
        return False
    (l, t, r, b), (ml, mt, mr, mb) = ventana["rect"], ventana["monitor"]
    return l <= ml + TOLERANCIA_PX and t <= mt + TOLERANCIA_PX and r >= mr - TOLERANCIA_PX and b >= mb - TOLERANCIA_PX


def juego_generico(ventana: dict | None, uso_gpu: dict[int, float], procesos: dict[int, dict]) -> dict | None:
    """El proceso de la ventana a pantalla completa, si usa mucha GPU y no es un programa que se sabe que no es un juego."""
    if not es_pantalla_completa(ventana):
        return None
    p = procesos.get(ventana["pid"])
    if not p or uso_gpu.get(ventana["pid"], 0) < GPU_MINIMA_PANTALLA_COMPLETA:
        return None
    nombre = ntpath.splitext(p["nombre"])[0]
    if NO_SON_JUEGOS_PANTALLA_COMPLETA.match(nombre) or CLIENTES.match(nombre):
        return None
    return {"tipo": "juego", "detalle": nombre, "desde": p["desde"], "firma": "pantalla_completa", "pid": p["pid"]}


def identificar(procesos: dict[int, dict], juegos: list[dict]) -> list[dict]:
    """Un juego por nombre, con la hora de inicio del proceso más antiguo. `procesos` = {pid: {'pid','nombre','exe','desde'}}."""
    hallados: dict[str, dict] = {}
    for p in procesos.values():
        nombre = juego_de(p.get("exe"), juegos)
        if nombre:
            d = hallados.setdefault(nombre, {"tipo": "juego", "detalle": nombre, "desde": p["desde"], "firma": "carpeta_de_juego", "pid": p["pid"]})
            d["desde"] = min(d["desde"], p["desde"])
    return list(hallados.values())


# ---------- lecturas del sistema (se reemplazan en las pruebas) ----------

def _registro(raiz: str, ruta: str, nombre: str | None):
    from . import windows
    return windows._registro(raiz, ruta, nombre)


def _leer(ruta: str) -> str:
    try:
        return Path(ruta).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _leer_catalogo() -> list[dict]:
    """Lee Steam (registro y appmanifest), Epic (manifiestos), GOG (registro) y las carpetas XboxGames de cada unidad."""
    steam = _registro("HKCU", r"Software\Valve\Steam", "SteamPath")
    manifiestos: dict[str, list[str]] = {}
    if steam:
        raiz = ntpath.normpath(str(steam))
        libs = [ntpath.join(raiz, "steamapps")] + [ntpath.join(p, "steamapps") for p in
                                                   parsear_bibliotecas_steam(_leer(ntpath.join(raiz, "steamapps", "libraryfolders.vdf")))]
        for lib in dict.fromkeys(_norm(l) for l in libs):
            carpeta = Path(lib)
            if carpeta.is_dir():
                manifiestos[lib] = [_leer(str(f)) for f in carpeta.glob("appmanifest_*.acf")]
    base_epic = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    epic = [_leer(str(f)) for f in base_epic.glob("*.item")] if base_epic.is_dir() else []
    gog = []
    for sub in _registro("HKLM", r"SOFTWARE\WOW6432Node\GOG.com\Games", None) or []:
        clave = rf"SOFTWARE\WOW6432Node\GOG.com\Games\{sub}"
        nombre, ruta = _registro("HKLM", clave, "gameName"), _registro("HKLM", clave, "path")
        if nombre and ruta:
            gog.append({"nombre": nombre, "ruta": ruta})
    xbox = []
    for p in psutil.disk_partitions(all=False):
        base = Path(p.mountpoint) / "XboxGames"
        if base.is_dir():
            xbox += [str(d) for d in base.iterdir() if d.is_dir() and d.name != "GameSave"]
    return catalogo(manifiestos, epic, gog, xbox)


def _procesos() -> dict[int, dict]:
    """Procesos del usuario con su ejecutable (los del sistema no dejan leerlo y se omiten)."""
    res = {}
    for p in psutil.process_iter(["pid", "name", "exe", "create_time"]):
        try:
            if p.info["exe"]:
                res[p.info["pid"]] = {"pid": p.info["pid"], "nombre": p.info["name"] or "", "exe": p.info["exe"],
                                      "desde": int(p.info["create_time"])}
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return res


def _ventana_primer_plano() -> dict | None:
    """Ventana en primer plano y el monitor donde está (user32, sin permisos especiales); None si no se puede leer."""
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32

        class Info(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("monitor", wintypes.RECT), ("trabajo", wintypes.RECT), ("flags", wintypes.DWORD)]
        hwnd = u.GetForegroundWindow()
        if not hwnd:
            return None
        pid, rect, info = wintypes.DWORD(), wintypes.RECT(), Info()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        u.GetWindowRect(hwnd, ctypes.byref(rect))
        info.cbSize = ctypes.sizeof(info)
        u.GetMonitorInfoW(u.MonitorFromWindow(hwnd, 2), ctypes.byref(info))
        m = info.monitor
        return {"pid": pid.value, "rect": (rect.left, rect.top, rect.right, rect.bottom), "monitor": (m.left, m.top, m.right, m.bottom)}
    except (AttributeError, OSError, ImportError):
        return None


def detectar(sensores_crudos: dict) -> list[dict]:
    """Actividad en curso: lista de {tipo, detalle, desde, firma, pid}, uno por juego distinto (igual que en Linux)."""
    procesos = _procesos()
    concretos = identificar(procesos, _leer_catalogo())
    if concretos:
        res = concretos
    else:
        generico = juego_generico(_ventana_primer_plano(), windows_sensores.uso_gpu_por_proceso(
            (sensores_crudos or {}).get("motores_gpu") or []), procesos)
        res = [generico] if generico else []
    ahora = int(time.time())
    for d in res:
        d["desde"] = min(int(d["desde"]), ahora)
    return res

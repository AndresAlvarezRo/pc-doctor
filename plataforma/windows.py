"""Backend de Windows 10/11: lee el equipo con PowerShell/CIM, el registro y LibreHardwareMonitor, sin pedir administrador.

Este archivo hace las lecturas (lo que se reemplaza en las pruebas: `_powershell`, `_registro`, `_particiones`, `_winget`...)
y arma la interfaz de `plataforma`; la interpretación está en `windows_sensores.py`, `windows_sistema.py`, `windows_juegos.py` y
`windows_notificaciones.py`, como funciones puras que se prueban con salidas simuladas. Se puede importar en Linux: nada de lo
específico de Windows (`winreg`, `ctypes.windll`) se toca hasta que se llama a la función que lo usa.
"""

import base64
import json
import logging
import os
import platform
import shutil
import socket
import subprocess
import time
from pathlib import Path

import psutil

from . import (windows_ayudante, windows_juegos, windows_lecturas_seguridad, windows_notificaciones, windows_sensores,
               windows_sistema)
from .comun import lista

log = logging.getLogger("pc-doctor")
NOMBRE = "windows"

TIEMPO_PS_S = 60          # tope de cada llamada a PowerShell
VIDA_SENSORES_S = 30      # los sensores leídos en un paso se reusan en los siguientes de la misma corrida
VIDA_WINGET_S = 6 * 3600  # `winget list` tarda varios segundos: se guarda el resultado

_cache: dict = {}         # por proceso: {"hardware": datos, "sensores": (momento, datos, meta)}


# ---------- lecturas del sistema (lo que las pruebas reemplazan) ----------

def _powershell(script: str, timeout: int = TIEMPO_PS_S) -> str | None:
    """Corre un script en Windows PowerShell (5.1, siempre presente) sin ventana y devuelve su salida, o None si falla.
    El script va codificado (`-EncodedCommand`): no hay que escapar nada y no depende de la política de ejecución."""
    exe = shutil.which("powershell") or shutil.which("powershell.exe")
    if exe is None:
        log.warning("no encuentro powershell")
        return None
    cabecera = "$ProgressPreference='SilentlyContinue';[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
    codificado = base64.b64encode((cabecera + script).encode("utf-16-le")).decode("ascii")
    try:
        r = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", codificado],
                           capture_output=True, timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("falló powershell: %s", e)
        return None
    if r.returncode != 0:
        log.warning("powershell terminó con código %s: %s", r.returncode, r.stderr.decode("utf-8", "replace").strip()[:200])
        return None
    return r.stdout.decode("utf-8", "replace")


def _json_ps(script: str, timeout: int = TIEMPO_PS_S):
    """Salida JSON de un script de PowerShell, o None si falla o no es JSON."""
    salida = _powershell(script, timeout)
    if not salida or not salida.strip():
        return None
    try:
        return json.loads(salida.lstrip("﻿"))
    except ValueError as e:
        log.warning("la salida de powershell no es JSON: %s", e)
        return None


def _registro(raiz: str, ruta: str, nombre: str | None):
    """Valor `nombre` de una clave del registro (raiz 'HKCU' o 'HKLM'), o None. Con nombre=None, los nombres de sus subclaves."""
    try:
        import winreg
        clave = winreg.OpenKey(getattr(winreg, f"HKEY_{'CURRENT_USER' if raiz == 'HKCU' else 'LOCAL_MACHINE'}"), ruta)
        with clave:
            if nombre is not None:
                return winreg.QueryValueEx(clave, nombre)[0]
            return [winreg.EnumKey(clave, i) for i in range(winreg.QueryInfoKey(clave)[0])]
    except (ImportError, OSError):
        return None


def _valores_registro(raiz: str, ruta: str) -> dict:
    """{nombre: valor} de todos los valores de una clave del registro (raiz 'HKCU' o 'HKLM'); vacío si no existe."""
    try:
        import winreg
        clave = winreg.OpenKey(getattr(winreg, f"HKEY_{'CURRENT_USER' if raiz == 'HKCU' else 'LOCAL_MACHINE'}"), ruta)
        with clave:
            return {n: v for n, v, _ in (winreg.EnumValue(clave, i) for i in range(winreg.QueryInfoKey(clave)[1]))}
    except (ImportError, OSError):
        return {}


def _leer_uninstall() -> list[dict]:
    """Entradas de las tres claves `Uninstall` (HKLM, HKLM\\WOW6432Node y HKCU) con los campos que hacen falta."""
    res = []
    for raiz, base in (("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
                       ("HKLM", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
                       ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Uninstall")):
        for sub in _registro(raiz, base, None) or []:
            e = {c: _registro(raiz, f"{base}\\{sub}", c) for c in
                 ("DisplayName", "DisplayVersion", "SystemComponent", "ParentKeyName", "ReleaseType")}
            if e["DisplayName"]:
                res.append(e)
    return res


def _winget() -> str | None:
    """Salida de `winget list` (solo si winget existe); se guarda 6 horas porque tarda varios segundos."""
    if shutil.which("winget") is None:
        return None
    import db  # import tardío: db importa plataforma
    archivo = db.DIR_DATOS / "winget.cache.json"
    try:
        c = json.loads(archivo.read_text(encoding="utf-8"))
        if time.time() - c["ts"] < VIDA_WINGET_S:
            return c["salida"]
    except (OSError, ValueError, KeyError):
        pass
    try:
        r = subprocess.run(["winget", "list", "--accept-source-agreements", "--disable-interactivity"], capture_output=True,
                           timeout=90, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("falló winget: %s", e)
        return None
    if r.returncode != 0:
        log.warning("winget terminó con código %s", r.returncode)
        return None
    salida = r.stdout.decode("utf-8", "replace")
    try:
        archivo.parent.mkdir(parents=True, exist_ok=True)
        archivo.write_text(json.dumps({"ts": time.time(), "salida": salida}), encoding="utf-8")
    except OSError:
        pass
    return salida


def _particiones() -> list[dict]:
    """Particiones con letra de unidad: {punto, fs, opciones, libre_pct}; las que no se pueden medir (BitLocker, sin disco) se omiten."""
    res = []
    for p in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(p.mountpoint)
        except OSError:
            continue
        if u.total:
            res.append({"punto": p.mountpoint, "fs": p.fstype, "opciones": p.opts, "libre_pct": u.free / u.total * 100})
    return res


# ---------- hardware y sistema operativo ----------

def _datos_hardware() -> dict:
    """Una sola llamada a CIM por corrida con todo el hardware y el sistema operativo."""
    if "hardware" not in _cache:
        _cache["hardware"] = _json_ps(windows_sistema.SCRIPT_HARDWARE) or {}
    return _cache["hardware"]


def hardware() -> list[tuple[str, str, str, dict]]:
    import db
    nvidia = None
    if shutil.which("nvidia-smi"):
        nvidia = db.ejecutar(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"])
    return windows_sistema.filas_hardware(_datos_hardware(), psutil.cpu_count(logical=False), psutil.cpu_count(logical=True),
                                          psutil.virtual_memory().total, psutil.swap_memory().total, nvidia)


def distro() -> str:
    return windows_sistema.nombre_so(_datos_hardware(), _registro("HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "DisplayVersion"),
                                     _registro("HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "UBR")) or platform.system()


def kernel() -> str:
    return windows_sistema.version_so(_datos_hardware()) or platform.version()


def escritorio() -> str:
    return "Windows"


def id_maquina() -> str:
    return str(_registro("HKLM", r"SOFTWARE\Microsoft\Cryptography", "MachineGuid") or socket.gethostname())


def paquetes() -> list[tuple[str, str, str]]:
    """Programas de las claves Uninstall (origen 'registro') más los de `winget list` con fuente (origen 'winget')."""
    return windows_sistema.paquetes_registro(_leer_uninstall()) + windows_sistema.paquetes_winget(_winget())


# ---------- rutas ----------

def dir_datos() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "pc-doctor"


def dir_programa() -> Path:
    return Path(__file__).resolve().parent.parent


def carpeta_descargas() -> Path | None:
    """La carpeta Descargas del usuario (puede estar movida de lugar: se pregunta al registro), o ~/Downloads."""
    valor = _registro("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
                      "{374DE290-123F-4565-9164-39C4925E467B}")
    for candidata in (os.path.expandvars(valor) if valor else None, Path.home() / "Downloads"):
        if candidata and Path(candidata).is_dir():
            return Path(candidata)
    return None


def raiz_sistema() -> str:
    return (os.environ.get("SystemDrive") or "C:") + "\\"


def fecha_archivo(st) -> float:
    """En Windows `st_ctime` es la fecha de creación, no la del último cambio: la cuarentena mira solo la de modificación."""
    return st.st_mtime


# ---------- sensores ----------

def _sensores_crudos():
    """(datos, meta) de la lectura de sensores; los pasos de una misma corrida comparten una sola llamada."""
    momento, datos = _cache.get("sensores", (0, None))
    if datos is None or time.monotonic() - momento > VIDA_SENSORES_S:
        datos = _json_ps(windows_sensores.SCRIPT_SENSORES, timeout=90) or {}
        _cache["sensores"] = (time.monotonic(), datos)
        _cache.pop("meta", None)
    return datos


def ayudante() -> dict:
    """Estado que dejó el ayudante con privilegios (instalador/ayudante.ps1), leído una vez por corrida."""
    if "ayudante" not in _cache:
        _cache["ayudante"] = windows_ayudante.leer()
    return _cache["ayudante"]


def _lecturas() -> tuple[list[dict], dict]:
    if "meta" not in _cache:
        lecturas, meta = windows_sensores.construir(_sensores_crudos(), _particiones(), bool(shutil.which("nvidia-smi")))
        _cache["meta"] = (windows_ayudante.mezclar(lecturas, ayudante()), {**meta, "ayudante": ayudante()["estado"]})
    return _cache["meta"]


def leer_sensores() -> list[dict]:
    return _lecturas()[0]


def temperatura_cpu() -> float | None:
    return windows_sensores.temperatura_cpu(_lecturas()[0])


def carga() -> float | None:
    """Windows no tiene carga promedio (ni algo equivalente que se pueda medir sin inventar): no se registra."""
    return None


def nvidia_smi_aplica(lecturas: list[dict]) -> bool:
    return not _cache.get("meta", ([], {}))[1].get("lhm_nvidia")


def no_disponible(lecturas: list[dict]) -> list[str]:
    return windows_sensores.no_disponible(lecturas, _lecturas()[1] if "meta" in _cache else {}) + windows_lecturas_seguridad.avisos_no_disponible() + windows_ayudante.avisos(ayudante())


def limitaciones() -> list[dict]:
    return windows_sistema.LIMITACIONES


def aviso_sin_temperatura() -> str:
    return ("No se pudo leer la temperatura: Windows no la expone sin un programa de sensores. Abrí LibreHardwareMonitor "
            "(lo configura habilitar-sensores.ps1).")


# ---------- eventos ----------

def eventos(desde: int, maximo: int) -> list[tuple[int, str, str, str]]:
    """Errores, críticos y advertencias del log System desde `desde`: (ts, origen, severidad, mensaje), del más viejo al más nuevo."""
    return windows_sistema.interpretar_eventos(_json_ps(windows_sistema.script_eventos(desde, maximo * 4)), maximo)


def patrones_evento(base: list) -> list:
    return windows_sistema.PATRONES_EVENTO


# ---------- actividad ----------

def detectar_juegos() -> list[dict]:
    return windows_juegos.detectar(_sensores_crudos())


# ---------- notificaciones y dashboard ----------

def notificar(titulo: str, mensaje: str, critica: bool = False, seccion: str | None = None, forzar_boton: bool = False) -> bool:
    return windows_notificaciones.notificar(_powershell, titulo, mensaje, critica, seccion, forzar_boton)


def avisar(titulo: str, mensaje: str) -> None:
    windows_notificaciones.notificar(_powershell, titulo, mensaje, False, None, False)


def abrir_url(url: str) -> None:
    windows_notificaciones.abrir_url(url)


def iniciar_dashboard(espera_s: float) -> str:
    return windows_notificaciones.iniciar_dashboard(_powershell, espera_s)


def mensaje_sin_servicio(estado: str) -> str:
    return windows_notificaciones.MENSAJES[estado]


# ---------- seguridad y reputación ----------

def escanear_procesos(con=None) -> tuple[list[dict], dict]:
    return windows_lecturas_seguridad.escanear_procesos(con)


def escanear_extra(con=None) -> list[dict]:
    return windows_lecturas_seguridad.escanear_extra(con)


def describir_procesos(pids) -> dict[int, str]:
    return windows_lecturas_seguridad.describir_procesos(pids)


def consultar_txt(nombre: str) -> tuple[str, list[str]] | None:
    """Registro TXT de un nombre con Resolve-DnsName, sin `dig`: (estado, textos) o None si falló."""
    return windows_lecturas_seguridad.consultar_txt(nombre, _json_ps)

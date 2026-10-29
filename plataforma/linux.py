"""Backend de Linux: adaptador sobre el código que sigue en collector.py, salud.py, db.py, actividad.py, alertas.py y dashboard.py.

No reimplementa nada: cada función llama a la original (los imports van adentro para no crear ciclos y para que las pruebas que
reemplazan esas funciones sigan valiendo). Lo que dice cada función es el contrato que cumple también `windows.py`.
"""

import os
import platform
import re
import subprocess
from pathlib import Path

import psutil

NOMBRE = "linux"


# ---------- rutas ----------

def dir_datos() -> Path:
    """Carpeta de datos (base, configuración, cuarentena, token)."""
    return Path.home() / ".local" / "share" / "pc-doctor"


def dir_programa() -> Path:
    """Carpeta donde está el código."""
    return Path(__file__).resolve().parent.parent


def carpeta_descargas() -> Path | None:
    import db
    return db._carpeta_descargas_linux()


def raiz_sistema() -> str:
    """Punto de montaje del que se mide el espacio libre de las métricas."""
    return "/"


# ---------- identidad del equipo ----------

def id_maquina() -> str:
    import collector
    return collector._id_maquina_linux()


def distro() -> str:
    import collector
    return collector._leer_distro_linux()


def kernel() -> str:
    return platform.release()


def escritorio() -> str:
    return os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION") or ""


def hardware() -> list[tuple[str, str, str, dict]]:
    """Filas (tipo, marca, modelo, detalle) de CPU, GPU, RAM, discos y placa."""
    import collector
    return collector._recolectar_hardware_linux()


def paquetes() -> list[tuple[str, str, str]]:
    """Filas (nombre, versión, origen) del software instalado."""
    import collector
    return collector.paquetes_apt() + collector.paquetes_flatpak() + collector.paquetes_snap()


# ---------- métricas y sensores ----------

def temperatura_cpu() -> float | None:
    import db
    return db._temperatura_cpu_linux()


def carga() -> float | None:
    """Carga promedio del último minuto; None si el sistema no la tiene."""
    return psutil.getloadavg()[0]


def leer_sensores() -> list[dict]:
    """Lecturas (categoria, nombre, valor, unidad, crit) de temperaturas, ventiladores, voltajes, GPU, discos y SMART.
    Cada fuente que falle se omite sin romper el resto."""
    import salud
    res = []
    for nombre, fn in (("hwmon", salud._hwmon), ("gpu_amd", salud._gpu_amd), ("discos", salud._discos), ("smart", salud._smart)):
        try:
            res += fn()
        except Exception:
            salud.log.exception("falló la lectura de %s", nombre)
    return res


def nvidia_smi_aplica(lecturas: list[dict]) -> bool:
    """True si hay que sumar la lectura de nvidia-smi (en Windows, no si LibreHardwareMonitor ya trajo la GPU NVIDIA)."""
    return True


def no_disponible(lecturas: list[dict]) -> list[str]:
    """Qué no se puede medir ahora en este equipo y qué falta para poder hacerlo."""
    import consultas
    return consultas._no_disponible_linux(lecturas)


def limitaciones() -> list[dict]:
    """Limitaciones fijas de este sistema, para la pantalla de limitaciones."""
    import consultas
    return consultas.LIMITACIONES_FIJAS


def aviso_sin_temperatura() -> str:
    return "No se pudo leer la temperatura (¿falta ejecutar sensors-detect?)."


# ---------- eventos ----------

def eventos(desde: int, maximo: int) -> list[tuple[int, str, str, str]]:
    """Errores del sistema desde el epoch `desde`: (ts, origen, severidad, mensaje)."""
    import collector
    return collector._eventos_journal(desde, maximo)


def patrones_evento(base: list) -> list:
    """Patrones que reconocen eventos graves en los mensajes de este sistema (en Linux, los de salud.py)."""
    return base


# ---------- actividad ----------

def detectar_juegos() -> list[dict]:
    import actividad
    return actividad._detectar_linux()


# ---------- notificaciones y dashboard ----------

def notificar(titulo: str, mensaje: str, critica: bool = False, seccion: str | None = None, forzar_boton: bool = False) -> bool:
    import alertas
    return alertas._notificar_linux(titulo, mensaje, critica, seccion, forzar_boton)


def avisar(titulo: str, mensaje: str) -> None:
    """Aviso simple y sin botón (por ejemplo cuando el lanzador no pudo abrir el dashboard)."""
    subprocess.run(["notify-send", "-a", "pc-doctor", "-i", "dialog-warning", titulo, mensaje], capture_output=True, timeout=10)


def abrir_url(url: str) -> None:
    """Abre la URL en el navegador. Levanta OSError si no pudo."""
    subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def iniciar_dashboard(espera_s: float) -> str:
    """Arranca el servicio del dashboard si hace falta: 'activo', 'iniciado', 'no_instalado' o 'no_arranco'."""
    import dashboard
    return dashboard._iniciar_linux(espera_s)


def mensaje_sin_servicio(estado: str) -> str:
    return {
        "no_instalado": "El servicio del dashboard no está instalado (falta pc-doctor-web.service).",
        "no_arranco": "El servicio del dashboard no arrancó. Mirá: journalctl --user -u pc-doctor-web",
    }[estado]


# ---------- archivos ----------

def fecha_archivo(st) -> float:
    """Fecha con la que la cuarentena decide si un archivo es viejo: la mayor entre mtime y ctime, así un archivo recién
    descomprimido o copiado no cuenta como viejo."""
    return max(st.st_mtime, st.st_ctime)


# ---------- seguridad y reputación ----------

def escanear_procesos(con=None) -> tuple[list[dict], dict]:
    """Hallazgos de los procesos y estadísticas {'procesos', 'sin_acceso'}. `con` se usa en Windows (rachas); acá no hace falta."""
    import seguridad
    return seguridad._escanear_procesos_linux()


def escanear_extra(con=None) -> list[dict]:
    """Hallazgos de otras fuentes (arranque y postura en Windows). En Linux no hay."""
    return []


def describir_procesos(pids) -> dict[int, str]:
    """{pid: texto} que se suma al detalle de los puertos en escucha (en Windows, la firma digital del programa)."""
    return {}


def consultar_txt(nombre: str) -> tuple[str, list[str]] | None:
    """Registro TXT de un nombre DNS con `dig`: (estado, textos entre comillas) o None si no se pudo consultar."""
    import reputacion
    salida = reputacion.ejecutar(["dig", "+time=5", "+tries=1", "TXT", nombre], timeout=12)
    if salida is None:
        return None
    estado = re.search(r"status: (\w+)", salida)
    return (estado.group(1) if estado else ""), re.findall(r'"([^"]*)"', salida)

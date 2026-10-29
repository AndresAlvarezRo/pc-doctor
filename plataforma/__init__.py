"""Capa de plataforma: lo que cambia entre Linux y Windows vive acá y el resto del código no sabe en qué sistema corre.

`actual()` devuelve el backend (`plataforma.linux` o `plataforma.windows`). Los dos exponen los mismos nombres (ver INTERFAZ):
una prueba falla si uno de ellos se queda sin alguno. Las reglas:
- Este paquete no importa `db` ni los demás módulos del proyecto al cargarse (lo importan ellos a él); si necesita algo de
  ellos lo hace dentro de la función.
- `linux.py` es un adaptador: llama al código que sigue viviendo en `collector.py`, `salud.py`, `db.py`... Así el comportamiento
  en Linux no cambia y las pruebas existentes (que reemplazan esas funciones) siguen valiendo.
- `windows.py` y los `windows_*.py` leen el sistema con PowerShell/CIM, el registro y LibreHardwareMonitor. Cada parte separa
  lo que lee del sistema (se reemplaza en las pruebas) de lo que interpreta (funciones puras con salidas simuladas).
"""

import importlib
import sys

ES_WINDOWS = sys.platform == "win32"
NOMBRE = "windows" if ES_WINDOWS else "linux"

# Todo lo que un backend tiene que ofrecer (ver el detalle en cada función de plataforma/linux.py)
INTERFAZ = (
    "dir_datos", "dir_programa", "carpeta_descargas", "id_maquina", "distro", "kernel", "escritorio", "raiz_sistema",
    "hardware", "paquetes", "temperatura_cpu", "carga", "leer_sensores", "nvidia_smi_aplica", "no_disponible",
    "limitaciones", "aviso_sin_temperatura", "eventos", "patrones_evento", "detectar_juegos", "notificar", "avisar",
    "abrir_url", "iniciar_dashboard", "mensaje_sin_servicio", "fecha_archivo",
    "escanear_procesos", "escanear_extra", "describir_procesos", "consultar_txt",
)

_cache: dict = {}


def actual():
    """El backend de este sistema (se carga la primera vez que se pide)."""
    if "backend" not in _cache:
        _cache["backend"] = importlib.import_module(f"plataforma.{NOMBRE}")
    return _cache["backend"]


def forzar(nombre: str | None):
    """Solo para pruebas: usa el backend `nombre` ('linux' o 'windows'); con None vuelve al del sistema."""
    if nombre is None:
        _cache.pop("backend", None)
    else:
        _cache["backend"] = importlib.import_module(f"plataforma.{nombre}")

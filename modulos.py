"""Mapa de archivos a módulos del proyecto, para que la bitácora entregue solo lo que toca a la tarea.

Vive en el código y no en la base: cambia junto con el repo y una prueba (`tests/test_bitacora_items.py`) falla si un archivo
versionado de código no cae en ningún módulo. Un archivo puede pertenecer a más de un módulo si coincide con patrones de varios.
"""

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent

# módulo -> patrones de rutas relativas a la raíz del repo (`*` no cruza carpetas, `**` sí). El código y sus pruebas van juntos.
MODULOS: dict[str, list[str]] = {
    "salud": ["salud.py", "linea_base.py", "tests/test_salud.py", "tests/test_smart.py", "tests/test_linea_base.py"],
    "seguridad": ["seguridad.py", "reputacion.py", "tests/test_seguridad.py"],
    "actividad": ["actividad.py", "tests/test_actividad.py"],
    "correlacion": ["correlacion.py", "tests/test_correlacion.py"],
    "reporte": ["reporte.py", "tests/test_reporte.py"],
    "alertas": ["alertas.py", "tests/test_notificaciones.py"],
    "dashboard": ["web/**", "dashboard.py", "tests/test_api.py", "tests/test_api_vs_mcp.py", "tests/test_dashboard.py"],
    "memoria": ["memoria.py", "migrar_memoria.py", "modulos.py", "tests/test_*memoria*.py", "tests/test_hechos_efecto.py",
                "tests/test_bitacora*.py"],
    "datos": ["db.py", "consultas.py", "collector.py", "tests/test_consultas.py", "tests/test_historial.py", "tests/test_local.py"],
    "mcp": ["server.py", "tests/test_cuarentena.py"],
    "plataforma": ["plataforma/__init__.py", "plataforma/comun.py", "plataforma/linux.py", "tests/test_plataforma.py"],
    "windows": ["plataforma/windows*.py", "tests/test_windows_*.py"],
    "instalador": ["instalador/**", "tests/test_instalador.py"],   # habilitar-sensores.ps1 y el ayudante (fase 3); instalar.ps1, empaquetar.py y las plantillas (fases 4 a 6)
    "infra": ["systemd/**", "habilitar-sensores.sh", "pyproject.toml", "uv.lock"],
    "git": ["scripts/**", ".github/**", ".gitignore", "tests/conftest.py", "tests/ayudas.py", "tests/falsos/**", "tests/test_hook.py"],
    "sistema": [],      # lo que está fuera del repo (servicios de otros proyectos, overrides, sudoers, /etc): se resuelve por la ruta
}

# Lo que no cuenta como código a la hora de exigir módulo: la documentación (README, CLAUDE.md y los markdown exportados).
EXENTOS = ("*.md",)


def _regex(patron: str) -> re.Pattern:
    """Traduce un patrón de ruta (`*`, `?`, `**`) a expresión regular."""
    i, out = 0, ""
    while i < len(patron):
        if patron.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif patron.startswith("**", i):
            out, i = out + ".*", i + 2
        elif patron[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif patron[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(patron[i]), i + 1
    return re.compile(out + r"\Z")


_PATRONES = [(modulo, [_regex(p) for p in patrones]) for modulo, patrones in MODULOS.items()]
_EXENTOS = [_regex(p) for p in EXENTOS]


def normalizar(ruta: str, raiz: Path = RAIZ) -> str:
    """Ruta relativa al repo si está dentro de él; si no, la ruta tal cual (absoluta o con `~`)."""
    r = (ruta or "").strip()
    if r.startswith("./"):
        r = r[2:]
    if r.startswith("/"):
        try:
            return Path(r).resolve().relative_to(raiz).as_posix()
        except ValueError:
            return r
    return r


def fuera_del_repo(ruta: str) -> bool:
    return ruta.startswith(("/", "~"))


def modulos_de(ruta: str, raiz: Path = RAIZ) -> list[str]:
    """Módulos a los que pertenece una ruta: lo que está fuera del repo es `sistema`; una ruta del repo sin patrón da lista vacía."""
    r = normalizar(ruta, raiz)
    if not r:
        return []
    if fuera_del_repo(r):
        return ["sistema"]
    return [modulo for modulo, regexes in _PATRONES if any(rx.match(r) for rx in regexes)]


def es_codigo(ruta: str) -> bool:
    return not any(rx.match(Path(ruta).name) for rx in _EXENTOS)


def sin_modulo(archivos: list[str], raiz: Path = RAIZ) -> list[str]:
    """De una lista de archivos versionados, los de código que no caen en ningún módulo."""
    return [a for a in archivos if es_codigo(a) and not modulos_de(a, raiz)]

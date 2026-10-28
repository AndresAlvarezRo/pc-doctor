"""Abrir el dashboard de pc-doctor: arma la URL de una sección, arranca el servicio si hace falta y abre el navegador.

Lo usan el lanzador del menú, los botones de las notificaciones y la tool `abrir_dashboard` del MCP.
Uso: `uv run dashboard.py abrir [seccion]`. Secciones: estado, alertas, linea-de-tiempo, reportes, limitaciones, entorno,
`alerta:N`, `hallazgo:N`, `componente:TIPO` o `componente:TIPO:ID`.
"""

import logging
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

log = logging.getLogger("pc-doctor")

PUERTO = int(os.environ.get("PC_DOCTOR_PUERTO", "8787"))
BASE = f"http://localhost:{PUERTO}"
SERVICIO = "pc-doctor-web.service"
SECCIONES = ("estado", "alertas", "linea-de-tiempo", "reportes", "limitaciones", "entorno")
COMPONENTES = ("cpu", "gpu", "ram", "disco", "ventiladores", "voltajes", "placa")
ESPERA_ARRANQUE_S = 15


def url_de(seccion: str = "") -> str:
    """URL completa de una sección. Solo se aceptan las formas conocidas (nunca una URL arbitraria)."""
    s = (seccion or "").strip().lower().replace("_", "-")
    if s in ("", "inicio", "/"):
        return BASE + "/"
    if s in SECCIONES:
        return f"{BASE}/#{s}"
    if s == "linea de tiempo":
        return f"{BASE}/#linea-de-tiempo"
    m = re.fullmatch(r"(alerta|hallazgo)[:/ ](\d{1,9})", s)
    if m:
        return f"{BASE}/{m[1]}/{m[2]}"
    m = re.fullmatch(r"componente[:/ ](" + "|".join(COMPONENTES) + r")(?:[:/ ]([a-z0-9._-]{1,40}))?", s)
    if m:
        return f"{BASE}/componente/{m[1]}" + (f"?id={m[2]}" if m[2] else "")
    raise ValueError(f"sección desconocida: {seccion!r}. Opciones: {', '.join(SECCIONES)}, alerta:N, hallazgo:N, componente:TIPO[:ID]")


def activo(timeout: float = 1.5) -> bool:
    """True si el dashboard responde en este momento."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PUERTO}/api/config", timeout=timeout) as r:
            return r.status == 200
    except (OSError, urllib.error.URLError):
        return False


def iniciar(espera_s: float = ESPERA_ARRANQUE_S) -> str:
    """Se asegura de que el dashboard esté corriendo. Devuelve 'activo', 'iniciado', 'no_instalado' o 'no_arranco'."""
    if activo():
        return "activo"
    try:
        r = subprocess.run(["systemctl", "--user", "start", SERVICIO], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("no pude iniciar %s: %s", SERVICIO, e)
        return "no_arranco"
    if r.returncode != 0:
        texto = r.stderr.lower()
        return "no_instalado" if ("not found" in texto or "not-found" in texto or "no such file" in texto) else "no_arranco"
    limite = time.time() + espera_s
    while time.time() < limite:
        if activo():
            return "iniciado"
        time.sleep(0.3)
    return "no_arranco"


MENSAJES = {
    "no_instalado": "El servicio del dashboard no está instalado (falta pc-doctor-web.service).",
    "no_arranco": "El servicio del dashboard no arrancó. Mirá: journalctl --user -u pc-doctor-web",
}


def abrir(seccion: str = "") -> dict:
    """Arranca el dashboard si hace falta y abre el navegador en la sección pedida."""
    url = url_de(seccion)
    estado = iniciar()
    res = {"url": url, "servicio": estado, "abierto": False}
    if estado in ("activo", "iniciado"):
        try:
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            res["abierto"] = True
        except OSError as e:
            res["error"] = f"no pude abrir el navegador: {e}"
    else:
        res["error"] = MENSAJES[estado]
    return res


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "abrir":
        try:
            r = abrir(sys.argv[2] if len(sys.argv) > 2 else "")
        except ValueError as e:
            print(e)
            sys.exit(2)
        if not r["abierto"]:
            # lanzado desde el menú no hay terminal: se avisa con una notificación
            subprocess.run(["notify-send", "-a", "pc-doctor", "-i", "dialog-warning", "No se pudo abrir pc-doctor", r.get("error", "")],
                           capture_output=True, timeout=10)
        print(r)
        sys.exit(0 if r["abierto"] else 1)
    print(__doc__)

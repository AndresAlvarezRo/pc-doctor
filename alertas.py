"""Alertas de escritorio de pc-doctor: avisa de hallazgos graves, una sola vez por hallazgo.

Las notificaciones pueden llevar un botón "Ver en el dashboard". Para recibir el clic hace falta un proceso vivo que
escuche, y el recolector termina enseguida (y systemd mata lo que quede en su servicio). Por eso el escucha corre en
una unidad transitoria propia (`systemd-run --user`) con un tope de vida, y se cierra solo. Si el botón no se puede usar
(el escritorio no soporta acciones, no hay systemd, está desactivado en config.json) la notificación sale igual, sin botón.
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import dashboard
import db
import plataforma
from db import log

MAX_LINEAS = 3  # cuántos hallazgos se detallan en una notificación; el resto se resume
TEXTO_BOTON = "Ver en el dashboard"
VIDA_ESCUCHA_S = 6 * 3600  # una notificación sin atender deja de escuchar tras este tiempo (el botón deja de funcionar)
MAX_ESCUCHAS = 10          # tope de escuchas vivos a la vez; pasado esto, las notificaciones salen sin botón


def _entorno() -> dict:
    entorno = dict(os.environ)
    entorno.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{os.getuid()}/bus")
    return entorno


def _comando(titulo: str, mensaje: str, critica: bool, con_boton: bool = False, seccion: str | None = None) -> list[str]:
    cmd = ["notify-send", "-a", "pc-doctor", "-u", "critical" if critica else "normal", "-i", "dialog-warning"]
    if con_boton:
        cmd.append(f"--action=ver={dashboard.texto_boton(seccion)}")  # implica esperar la respuesta; imprime "ver" si se hace clic
    return cmd + [titulo, mensaje]


def _boton_posible(forzar: bool = False) -> bool:
    """True si hay que ofrecer el botón y se puede: opción activa, el escritorio soporta acciones y no hay demasiados escuchas."""
    from reputacion import cargar_config  # import tardío: reputacion no depende de este módulo
    if not forzar and not cargar_config(crear=False).get("boton_dashboard", False):
        return False
    try:
        r = subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.Notifications", "--object-path",
                            "/org/freedesktop/Notifications", "--method", "org.freedesktop.Notifications.GetCapabilities"],
                           capture_output=True, text=True, timeout=5, env=_entorno())
        if r.returncode != 0 or "'actions'" not in r.stdout:
            return False
        activos = subprocess.run(["systemctl", "--user", "list-units", "pc-doctor-notif-*", "--no-legend", "--plain"],
                                 capture_output=True, text=True, timeout=5)
        return len([l for l in activos.stdout.splitlines() if l.strip()]) < MAX_ESCUCHAS
    except (OSError, subprocess.TimeoutExpired):
        return False


def _lanzar_escucha(titulo: str, mensaje: str, critica: bool, seccion: str) -> bool:
    """Muestra la notificación con botón desde una unidad transitoria que sobrevive al recolector. True si se lanzó."""
    cmd = ["systemd-run", "--user", "--quiet", "--collect", f"--unit=pc-doctor-notif-{int(time.time())}-{os.getpid()}",
           "-p", f"RuntimeMaxSec={VIDA_ESCUCHA_S}"]
    for var in ("PC_DOCTOR_DATOS", "PC_DOCTOR_PUERTO"):  # las pruebas usan otra carpeta de datos y otro puerto
        if os.environ.get(var):
            cmd.append(f"--setenv={var}={os.environ[var]}")
    cmd += ["--", sys.executable, str(Path(__file__).resolve()), "--con-boton", f"--titulo={titulo}", f"--mensaje={mensaje}",
            f"--seccion={seccion}"] + (["--critica"] if critica else [])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("no pude lanzar el escucha del botón: %s", e)
        return False
    if r.returncode != 0:
        log.warning("systemd-run falló: %s", r.stderr.strip()[:200])
    return r.returncode == 0


def notificar(titulo: str, mensaje: str, critica: bool = False, seccion: str | None = None, forzar_boton: bool = False) -> bool:
    """Muestra una notificación de escritorio (Linux: `notify-send`; Windows: toast). Devuelve True si se pudo enviar.
    Con `seccion` ofrece el botón "Ver en el dashboard" (ver `_notificar_linux` y plataforma/windows_notificaciones.py)."""
    return plataforma.actual().notificar(titulo, mensaje, critica, seccion, forzar_boton)


def _notificar_linux(titulo: str, mensaje: str, critica: bool = False, seccion: str | None = None, forzar_boton: bool = False) -> bool:
    """Muestra una notificación de escritorio con `notify-send`. Devuelve True si se pudo enviar.

    Con `seccion` (ej. "alerta:4", "hallazgo:7", "reportes") agrega un botón "Ver en el dashboard" que abre esa sección;
    si el botón no se puede ofrecer, la notificación sale igual, sin botón. El botón está apagado por defecto
    (config.json -> "boton_dashboard": true lo activa) hasta que se pruebe en el escritorio real. Funciona también desde un servicio de
    systemd de usuario: si falta la variable del bus de D-Bus, se arma.
    """
    if seccion:
        try:
            dashboard.url_de(seccion)  # solo se ofrece el botón para secciones válidas
            if _boton_posible(forzar_boton) and _lanzar_escucha(titulo, mensaje, critica, seccion):
                return True
        except ValueError:
            log.warning("sección inválida para el botón: %r", seccion)
    try:
        r = subprocess.run(_comando(titulo, mensaje, critica), capture_output=True, text=True, timeout=10, env=_entorno())
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("no pude enviar la notificación: %s", e)
        return False
    if r.returncode != 0:
        log.warning("notify-send falló: %s", r.stderr.strip()[:200])
        return False
    return True


def esperar_accion(titulo: str, mensaje: str, critica: bool, seccion: str) -> int:
    """Corre dentro de la unidad transitoria: muestra la notificación con botón y, si se hace clic, abre el dashboard."""
    try:
        r = subprocess.run(_comando(titulo, mensaje, critica, con_boton=True, seccion=seccion), capture_output=True, text=True,
                           timeout=VIDA_ESCUCHA_S, env=_entorno())
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("escucha de la notificación terminó: %s", e)
        return 1
    if r.returncode != 0:
        # nunca se pierde un aviso: si el escritorio rechazó la versión con botón, sale la simple
        log.warning("notify-send con botón falló (%s): se envía sin botón", r.stderr.strip()[:200])
        try:
            subprocess.run(_comando(titulo, mensaje, critica), capture_output=True, timeout=10, env=_entorno())
        except (OSError, subprocess.TimeoutExpired):
            pass
        return 1
    if r.stdout.strip() == "ver":  # el usuario hizo clic en el botón
        resultado = dashboard.abrir(seccion)
        if not resultado["abierto"]:
            subprocess.run(_comando("No se pudo abrir pc-doctor", resultado.get("error", ""), False), capture_output=True, timeout=10, env=_entorno())
    return 0


def avisar(con, desde: int) -> dict:
    """Notifica (en un único aviso) los hallazgos graves vistos desde `desde` que aún no se hayan avisado.

    Grave = severidad alta y estado 'nuevo' (incluye todo lo que la reputación online marcó como malware).
    Solo se marcan como avisados si la notificación se envió, así que un fallo se reintenta en la próxima corrida.
    """
    from reputacion import cargar_config  # import tardío: reputacion no depende de este módulo
    if not cargar_config().get("notificaciones", True):
        return {"enviadas": 0, "motivo": "desactivadas"}
    filas = con.execute(
        "SELECT h.id, h.huella, h.regla, h.nombre, h.detalle, r.veredicto FROM hallazgos_seguridad h "
        "LEFT JOIN reputacion r ON r.huella = h.huella "
        "WHERE h.severidad='alta' AND h.estado='nuevo' AND h.ultima_vez >= ? "
        "AND h.huella NOT IN (SELECT huella FROM notificaciones) "
        "ORDER BY (r.veredicto IN ('malicioso','sospechoso')) DESC, h.id", (desde,)).fetchall()
    if not filas:
        return {"enviadas": 0}
    malware = any(f["veredicto"] in ("malicioso", "sospechoso") for f in filas)
    titulo = "pc-doctor: posible malware detectado" if malware else f"pc-doctor: {len(filas)} alerta(s) de seguridad"
    lineas = [f"• {f['nombre']}: {f['detalle'][:90]}" + (f" [{f['veredicto']}]" if f["veredicto"] in ("malicioso", "sospechoso") else "")
              for f in filas[:MAX_LINEAS]]
    if len(filas) > MAX_LINEAS:
        lineas.append(f"… y {len(filas) - MAX_LINEAS} más (hallazgos_seguridad)")
    if not notificar(titulo, "\n".join(lineas), critica=malware, seccion=f"hallazgo:{filas[0]['id']}"):
        return {"enviadas": 0, "motivo": "falló el envío, se reintenta"}
    con.executemany("INSERT OR IGNORE INTO notificaciones (huella, ts, titulo) VALUES (?,?,?)",
                    [(f["huella"], db.ahora(), titulo) for f in filas])
    return {"enviadas": 1, "hallazgos": len(filas)}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Alertas de escritorio de pc-doctor")
    p.add_argument("--probar", action="store_true", help="envía una notificación de prueba simple")
    p.add_argument("--probar-boton", action="store_true", help="envía una notificación de prueba con el botón (ES REAL: se ve en pantalla)")
    p.add_argument("--con-boton", action="store_true", help="uso interno: escucha de una notificación con botón")
    p.add_argument("--titulo", default="")
    p.add_argument("--mensaje", default="")
    p.add_argument("--seccion", default="")
    p.add_argument("--critica", action="store_true")
    a = p.parse_args()
    if a.con_boton:
        sys.exit(esperar_accion(a.titulo, a.mensaje, a.critica, a.seccion))
    if a.probar_boton:
        ok = notificar("pc-doctor: prueba del botón", "Tocá «Ver en el dashboard»: debería abrirse el dashboard en las alertas.", seccion="alertas", forzar_boton=True)
        print("lanzada" if ok else "falló (mirá el log)")
        sys.exit(0 if ok else 1)
    if a.probar:
        ok = notificar("pc-doctor: prueba", "Si ves esto, las alertas de escritorio funcionan.")
        print("enviada" if ok else "falló (mirá el log)")
        sys.exit(0 if ok else 1)
    p.print_help()

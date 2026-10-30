"""Notificaciones y apertura del dashboard en Windows.

La notificación es un toast nativo (WinRT desde PowerShell, sin dependencias). El botón "Ver en el dashboard" usa activación por
protocolo: el toast lleva la URL del dashboard y Windows la abre con el navegador predeterminado al hacer clic. No hace falta
ningún proceso que quede escuchando, así que no hay nada equivalente a las unidades transitorias de Linux.
"""

import base64
import json
import logging
import os
import time
from xml.sax.saxutils import escape, quoteattr

log = logging.getLogger("pc-doctor")

TEXTO_BOTON = "Ver en el dashboard"
AUMID = "pc-doctor"   # identidad de la aplicación en las notificaciones (se registra en HKCU, sin administrador)
MENSAJES = {
    "no_instalado": "La tarea programada del dashboard no está instalada (falta pc-doctor-web: corré instalar.ps1).",
    "no_arranco": "La tarea del dashboard no arrancó. Mirá pc-doctor-web en el Programador de tareas.",
}


def xml_toast(titulo: str, mensaje: str, url: str | None, critica: bool = False, texto_boton: str = TEXTO_BOTON) -> str:
    """XML de un toast. Con `url` el toast y su botón abren esa dirección (activación por protocolo)."""
    acciones = ""
    if url:
        acciones = (f'<actions><action content={quoteattr(texto_boton)} arguments={quoteattr(url)} activationType="protocol"/></actions>')
    atributos = ""
    if url:
        atributos += f" launch={quoteattr(url)} activationType=\"protocol\""
    if critica:
        atributos += ' scenario="reminder"' if url else ""  # "reminder" exige un botón; sin él, queda como un toast normal
    return (f"<toast{atributos}><visual><binding template=\"ToastGeneric\"><text>{escape(titulo)}</text>"
            f"<text>{escape(mensaje)}</text></binding></visual>{acciones}</toast>")


def script_toast(xml: str, sin_popup: bool = False) -> str:
    """Script de PowerShell que registra la identidad `pc-doctor` en HKCU (una vez) y muestra el toast.
    Con `sin_popup` el toast no salta en pantalla (SuppressPopup): va directo al Centro de actividades."""
    suprimir = "$t.SuppressPopup=$true\n" if sin_popup else ""
    xml64 = base64.b64encode(xml.encode("utf-8")).decode("ascii")
    return rf"""
$k='HKCU:\Software\Classes\AppUserModelId\{AUMID}'
if(-not (Test-Path $k)){{ New-Item -Path $k -Force | Out-Null; New-ItemProperty -Path $k -Name DisplayName -Value 'pc-doctor' -PropertyType String -Force | Out-Null }}
[void][Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]
[void][Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime]
$x=New-Object Windows.Data.Xml.Dom.XmlDocument
$x.LoadXml([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{xml64}')))
$t=[Windows.UI.Notifications.ToastNotification]::new($x)
{suprimir}[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{AUMID}').Show($t)
"""


def boton_activo() -> bool:
    """El botón está activo salvo que config.json diga explícitamente "boton_dashboard": false. (En Linux es al revés: viene apagado
    hasta probarlo en el escritorio; en Windows no necesita ningún proceso aparte, así que no hay nada que probar antes.)"""
    import reputacion
    try:
        return json.loads(reputacion.RUTA_CONFIG.read_text()).get("boton_dashboard", True) is not False
    except (OSError, ValueError, AttributeError):
        return True


def notificar(powershell, titulo: str, mensaje: str, critica: bool, seccion: str | None, forzar_boton: bool) -> bool:
    """Muestra el toast. `powershell(script)` corre un script y devuelve su salida (None si falló). True si se pudo enviar.

    Con `seccion` ("alerta:4", "hallazgo:7", "reportes"...) ofrece el botón "Ver en el dashboard"; solo se aceptan secciones válidas
    y el botón se puede apagar con "boton_dashboard": false en config.json."""
    url = None
    import dashboard  # import tardío: dashboard importa plataforma
    if seccion:
        try:
            url = dashboard.url_de(seccion)
        except ValueError:
            log.warning("sección inválida para el botón: %r", seccion)
        if url and not forzar_boton and not boton_activo():
            url = None
    import alertas  # import tardío: alertas importa plataforma
    sin_popup = not alertas.banner_deseado()  # mostrar_en_pantalla: nunca / fuera_de_juego / siempre
    xml = xml_toast(titulo, mensaje, url, critica and not sin_popup, dashboard.texto_boton(seccion) if seccion else TEXTO_BOTON)
    if powershell(script_toast(xml, sin_popup), 20) is None:
        log.warning("no pude mostrar la notificación")
        return False
    return True


def abrir_url(url: str) -> None:
    """Abre la URL con el navegador predeterminado. Levanta OSError si no pudo."""
    if hasattr(os, "startfile"):
        os.startfile(url)  # noqa: S606  (solo Windows; la URL ya viene validada por dashboard.url_de)
        return
    import webbrowser
    if not webbrowser.open(url):
        raise OSError("no pude abrir el navegador")


SCRIPT_ARRANCAR = r"""
$t=Get-ScheduledTask -TaskName 'pc-doctor-web' -ErrorAction SilentlyContinue
if(-not $t){ 'no_instalado'; exit 0 }
Start-ScheduledTask -InputObject $t -ErrorAction Stop
'ok'
"""


def iniciar_dashboard(powershell, espera_s: float) -> str:
    """Arranca la tarea programada `pc-doctor-web` si el dashboard no responde: 'activo', 'iniciado', 'no_instalado' o 'no_arranco'."""
    import dashboard
    if dashboard.activo():
        return "activo"
    salida = powershell(SCRIPT_ARRANCAR, 30)
    if salida is None:
        return "no_arranco"
    if salida.strip() == "no_instalado":
        return "no_instalado"
    limite = time.time() + espera_s
    while time.time() < limite:
        if dashboard.activo():
            return "iniciado"
        time.sleep(0.3)
    return "no_arranco"

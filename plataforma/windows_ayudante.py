"""Lado sin privilegios del ayudante de Windows (instalador/ayudante.ps1): lee y valida `estado.json` y lo convierte en lecturas y hallazgos.

El ayudante corre como SYSTEM y escribe en %ProgramData%\\pc-doctor\\ayudante, una carpeta que los usuarios comunes solo pueden leer.
Acá nunca se ejecuta nada que venga de ese archivo: se valida su forma (tamaño, versión, tipos, largos), se descarta lo que no esté en
la lista de campos conocidos y, si es viejo, se avisa en lugar de usarlo.
"""

import json
import os
import re
import time
from pathlib import Path

from .comun import lectura, lista

RUTA_ESTADO = Path(os.environ.get("ProgramData") or r"C:\ProgramData") / "pc-doctor" / "ayudante" / "estado.json"
MAX_BYTES = 1_000_000
VIDA_S = 2 * 3600          # el ayudante corre cada 15 min: sin datos nuevos en 2 horas, algo falló
MAX_TEXTO = 260
NOMBRE_DISCO = re.compile(r"^(disk\d{1,2}|nvme\d{1,2})$")
ARRANQUE_SEGURO = ("activado", "desactivado", "no_soportado")
RIESGO_RUTA = re.compile(r"(?i)^(\*|[a-z]:\\?)$|\\(temp|appdata|downloads|descargas|users\\public|programdata)(\\|$)|\\windows\\temp")


def _texto(v, maximo: int = MAX_TEXTO) -> str:
    return str(v)[:maximo] if isinstance(v, (str, int, float)) and not isinstance(v, bool) else ""


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _lista_textos(v) -> list[str]:
    return [t for t in (_texto(x) for x in lista(v)[:100]) if t]


def validar(d) -> dict | None:
    """Deja solo los campos conocidos y con la forma esperada; None si no es un estado del ayudante (versión 1)."""
    if not isinstance(d, dict) or d.get("version") != 1 or not isinstance(d.get("ts"), int) or isinstance(d.get("ts"), bool):
        return None
    crudo = d.get("smart") if isinstance(d.get("smart"), dict) else {}
    smart = {k: v for k, v in crudo.items() if NOMBRE_DISCO.match(str(k)) and isinstance(v, str) and len(v) <= 200_000}
    fiabilidad = []
    for f in lista(d.get("fiabilidad"))[:64]:
        if isinstance(f, dict) and isinstance(f.get("Id"), int) and 0 <= f["Id"] < 100:
            fiabilidad.append({"Id": f["Id"], **{k: _num(f.get(k)) for k in ("Temperatura", "Desgaste", "Horas", "LecturasNoCorregidas", "EscriturasNoCorregidas")}})
    bitlocker = [{k: _texto(b.get(k), 40) for k in ("Punto", "Estado", "Proteccion", "Bloqueo", "Metodo")} for b in lista(d.get("bitlocker"))[:32] if isinstance(b, dict)]
    defender = d.get("defender") if isinstance(d.get("defender"), dict) else {}
    wmi = d.get("wmi") if isinstance(d.get("wmi"), dict) else {}
    consumidores = [{k: _texto(c.get(k)) for k in ("Name", "CommandLineTemplate", "ExecutablePath", "ScriptFileName") if c.get(k)}
                    for c in lista(wmi.get("consumidores"))[:100] if isinstance(c, dict)]
    consumidores = [c for c in consumidores if c]
    return {"ts": d["ts"], "smart": smart, "fiabilidad": fiabilidad, "bitlocker": bitlocker,
            "arranque_seguro": d.get("arranque_seguro") if d.get("arranque_seguro") in ARRANQUE_SEGURO else "no_soportado",
            "defender": {k: _lista_textos(defender.get(k)) for k in ("rutas", "extensiones", "procesos")},
            "wmi": {"consumidores": consumidores}, "errores": _lista_textos(d.get("errores"))[:20]}


def leer(ruta: Path | None = None, ahora: float | None = None) -> dict:
    """{'estado': 'ausente'|'invalido'|'viejo'|'ok', 'datos': {...} o {}, 'edad_s': int, 'motivo': str}."""
    ruta, ahora = ruta or RUTA_ESTADO, ahora or time.time()
    try:
        if ruta.stat().st_size > MAX_BYTES:
            return {"estado": "invalido", "datos": {}, "edad_s": 0, "motivo": "estado.json es demasiado grande"}
        crudo = json.loads(ruta.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {"estado": "ausente", "datos": {}, "edad_s": 0, "motivo": ""}
    except (OSError, ValueError):
        return {"estado": "invalido", "datos": {}, "edad_s": 0, "motivo": "estado.json no se puede leer o no es JSON"}
    datos = validar(crudo)
    if datos is None:
        return {"estado": "invalido", "datos": {}, "edad_s": 0, "motivo": "estado.json no es de una versión que pc-doctor entienda"}
    edad = int(ahora - datos["ts"])
    return {"estado": "viejo" if edad > VIDA_S else "ok", "datos": datos, "edad_s": edad, "motivo": ""}


def lecturas(datos: dict) -> list[dict]:
    """Lecturas de los discos con los nombres de Linux: el SMART crudo pasa por el mismo parser (`salud.parsear_smart`) y los
    contadores de fiabilidad aportan temperatura y desgaste si el SMART no los trae."""
    import salud  # import tardío: salud importa plataforma
    res = []
    for dev, texto in sorted(datos.get("smart", {}).items()):
        res += salud.parsear_smart(dev, texto)
    for f in datos.get("fiabilidad", []):
        dev, ya = f"disk{f['Id']}", {l["nombre"] for l in res}
        if isinstance(f["Temperatura"], (int, float)) and 0 < f["Temperatura"] < 150:
            res.append(lectura("disco", f"{dev}/temp", f["Temperatura"], "°C"))
        if isinstance(f["Desgaste"], (int, float)) and 0 <= f["Desgaste"] <= 100 and f"{dev}/desgaste_pct" not in ya:
            res.append(lectura("disco", f"{dev}/desgaste_pct", f["Desgaste"], "%"))
        if isinstance(f["Horas"], (int, float)) and f["Horas"] > 0 and f"{dev}/horas_encendido" not in ya:
            res.append(lectura("disco", f"{dev}/horas_encendido", f["Horas"], "h"))
    return res


def mezclar(base: list[dict], estado: dict) -> list[dict]:
    """Suma las lecturas del ayudante a las que ya había. Si el ayudante da una lectura con el mismo nombre, manda el ayudante (mide
    con privilegios). La temperatura de un disco no se repite si LibreHardwareMonitor ya la trajo con otro nombre."""
    if estado.get("estado") != "ok":
        return base
    nuevas = lecturas(estado["datos"])
    nombres = {l["nombre"] for l in nuevas}
    resto = [l for l in base if l["nombre"] not in nombres]
    hay_temp_lhm = any(l["categoria"] == "disco" and l["unidad"] == "°C" and not re.match(r"disk\d+/", l["nombre"]) for l in resto)
    if hay_temp_lhm:
        nuevas = [l for l in nuevas if not (l["unidad"] == "°C" or l["nombre"].endswith("/desgaste_pct"))]
    return resto + nuevas


def consumidores_wmi(estado: dict) -> list[dict]:
    """Suscripciones WMI que ejecutan código, en el formato de `windows_seguridad.items_persistencia`."""
    return estado["datos"]["wmi"]["consumidores"] if estado.get("estado") == "ok" else []


def exclusion_riesgosa(tipo: str, valor: str) -> bool:
    """Una exclusión de Defender es riesgosa si deja sin revisar una carpeta temporal o del usuario, una unidad entera o un tipo de
    archivo ejecutable. Las demás (la carpeta de un juego, de un proyecto) son informativas."""
    if tipo == "extensión":
        return valor.lower().lstrip(".*") in ("exe", "dll", "ps1", "bat", "cmd", "vbs", "js", "scr", "") 
    return bool(RIESGO_RUTA.search(valor))


def hallazgos_postura(estado: dict) -> list[dict]:
    """BitLocker, Secure Boot y exclusiones de Defender, como hallazgos de postura."""
    if estado.get("estado") != "ok":
        return []
    from . import windows_seguridad as ws
    d, res = estado["datos"], []

    def hallazgo(regla, sev, nombre, texto, clave=None):
        res.append(ws._h("postura", regla, sev, nombre, None, "", texto, clave=clave or regla))

    sistema = os.environ.get("SystemDrive", "C:").upper()
    for b in d["bitlocker"]:
        punto = b["Punto"].upper().rstrip("\\")
        if b["Estado"] == "FullyEncrypted" and b["Proteccion"] == "Off":
            hallazgo("bitlocker_suspendido", "media", f"BitLocker {punto}", f"El cifrado de {punto} está suspendido: el volumen está cifrado pero la protección está apagada", clave=punto)
        elif b["Estado"] == "FullyDecrypted":
            hallazgo("bitlocker_sin_cifrar", "baja", f"BitLocker {punto}", f"El volumen {punto}{' (el del sistema)' if punto == sistema else ''} no está cifrado (informativo: es lo habitual en equipos de escritorio)", clave=punto)
    if d["arranque_seguro"] == "desactivado":
        hallazgo("secure_boot_desactivado", "media", "Secure Boot", "Secure Boot está desactivado: el equipo arranca sin verificar la firma del cargador")
    elif d["arranque_seguro"] == "no_soportado":
        hallazgo("secure_boot_no_disponible", "baja", "Secure Boot", "Este equipo arranca en modo heredado (BIOS) o no informa Secure Boot")
    comunes = 0
    for tipo, items in (("ruta", d["defender"]["rutas"]), ("proceso", d["defender"]["procesos"]), ("extensión", d["defender"]["extensiones"])):
        for e in items:
            if exclusion_riesgosa(tipo, e):
                hallazgo("defender_exclusion_riesgosa", "alta", "Defender: exclusión", f"Defender no revisa {tipo}: {e} (carpeta temporal, unidad entera o tipo de archivo ejecutable; "
                         "es lo primero que agrega el malware para esconderse)", clave=f"{tipo}|{e}")
            else:
                comunes += 1
    if comunes:
        hallazgo("defender_exclusiones", "baja", "Defender: exclusiones", f"Defender tiene {comunes} exclusión(es) configuradas por el usuario o por programas (informativo)")
    return res


def avisos(estado: dict) -> list[str]:
    """Lo que falta o falló del ayudante, para `no_disponible`."""
    e = estado.get("estado")
    if e == "ausente":
        return ["Ayudante con privilegios: no está instalado (SMART detallado, BitLocker, Secure Boot, exclusiones de Defender; ver habilitar-sensores.ps1)"]
    if e == "viejo":
        return [f"Ayudante con privilegios: no deja datos desde hace {estado['edad_s'] // 3600} h (¿falló la tarea pc-doctor-ayudante?)"]
    if e == "invalido":
        return [f"Ayudante con privilegios: {estado['motivo']}"]
    return [f"El ayudante no pudo leer: {m}" for m in estado["datos"]["errores"]]

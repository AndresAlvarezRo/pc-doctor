"""Reputación online de ejecutables sospechosos.

Privacidad: los hashes se calculan y guardan en esta PC. Solo se consulta online el HASH (nunca el archivo)
de ejecutables que el escaneo ya marcó como sospechosos; del resto del sistema no sale nada.
Se puede desactivar con "consulta_online": false en ~/.local/share/pc-doctor/config.json.
"""

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import db
import plataforma
from db import ejecutar, log

RUTA_CONFIG = db.DIR_DATOS / "config.json"
CONFIG_BASE = {"consulta_online": True, "malwarebazaar_key": "", "notificaciones": True,
               "salud": True, "umbrales": {}, "boton_dashboard": False, "mostrar_en_pantalla": "nunca"}
VIGENCIA_S = 7 * 86400          # un veredicto se reutiliza una semana antes de volver a consultar
MAX_CONSULTAS_POR_CORRIDA = 3   # acota el tiempo del recolector; el resto queda para la próxima corrida
MAX_BYTES_HASH = 512 * 1024 * 1024
CATEGORIAS_CON_EXE = ("minero", "fantasma", "keylogger", "persistencia")
UA = {"User-Agent": "pc-doctor/0.1"}
FIRMAN = ("malicioso", "sospechoso")


def cargar_config(crear: bool = True) -> dict:
    """Lee la configuración; si no existe la crea con los valores por defecto (salvo con `crear=False`)."""
    cfg = dict(CONFIG_BASE)
    try:
        cfg.update(json.loads(RUTA_CONFIG.read_text()))
    except OSError:
        if not crear:
            return cfg
        try:
            RUTA_CONFIG.parent.mkdir(parents=True, exist_ok=True)
            RUTA_CONFIG.write_text(json.dumps(CONFIG_BASE, indent=2) + "\n")
        except OSError:
            pass
    except ValueError:
        log.warning("config.json inválido, se usan los valores por defecto")
    return cfg


def hashes_de(ruta: str) -> tuple[str, str] | None:
    """Devuelve (sha256, sha1) del archivo, calculados localmente; None si no se puede leer."""
    try:
        if os.path.getsize(ruta) > MAX_BYTES_HASH:
            return None
        s256, s1 = hashlib.sha256(), hashlib.sha1()
        with open(ruta, "rb") as f:
            for bloque in iter(lambda: f.read(1 << 20), b""):
                s256.update(bloque)
                s1.update(bloque)
        return s256.hexdigest(), s1.hexdigest()
    except OSError:
        return None


# ---------- proveedores: devuelven (veredicto, detalle) o None si la consulta falló ----------

def _circl(sha256: str):
    """CIRCL hashlookup: base de archivos conocidos (NSRL, etc.). Solo sirve para descartar; ojo: conocido no implica limpio."""
    req = urllib.request.Request(f"https://hashlookup.circl.lu/lookup/sha256/{sha256}", headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            datos = json.loads(r.read(200_000))
        return "conocido_limpio", f"Archivo conocido en CIRCL ({str(datos.get('FileName', '?'))[:60]})"
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return "sin_registro", None
        log.warning("CIRCL respondió %s", e.code)
    except (urllib.error.URLError, OSError, ValueError) as e:
        log.warning("CIRCL falló: %s", e)
    return None


def _cymru(sha1: str):
    """Team Cymru Malware Hash Registry (DNS, sin clave): porcentaje de antivirus que lo detectan.
    La consulta TXT la hace la plataforma (Linux: `dig`; Windows: Resolve-DnsName)."""
    r = plataforma.actual().consultar_txt(f"{sha1}.hash.cymru.com")
    if r is None:
        return None
    estado, textos = r
    if estado not in ("NOERROR", "NXDOMAIN"):
        log.warning("Cymru devolvió %s", estado or "una respuesta ilegible")
        return None
    m = next(filter(None, (re.fullmatch(r"(\d+)\s+(\d+)", t.strip()) for t in textos)), None)
    if estado == "NXDOMAIN" or not m:
        return "sin_registro", None
    pct = int(m.group(2))
    return ("malicioso" if pct >= 50 else "sospechoso"), f"Detectado por {pct}% de los antivirus"


def _malwarebazaar(sha256: str, clave: str):
    """MalwareBazaar (abuse.ch). Requiere una clave gratuita en config.json; sin ella no se usa."""
    datos = urllib.parse.urlencode({"query": "get_info", "hash": sha256}).encode()
    req = urllib.request.Request("https://mb-api.abuse.ch/api/v1/", data=datos, headers={**UA, "Auth-Key": clave})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            resp = json.loads(r.read(500_000))
    except (urllib.error.URLError, OSError, ValueError) as e:
        log.warning("MalwareBazaar falló: %s", e)
        return None
    if resp.get("query_status") == "ok":
        firma = (resp.get("data") or [{}])[0].get("signature") or "sin firma"
        return "malicioso", f"Conocido en MalwareBazaar: {firma}"
    if resp.get("query_status") == "hash_not_found":
        return "sin_registro", None
    log.warning("MalwareBazaar devolvió %s", resp.get("query_status"))
    return None


def consultar_hash(sha256: str, sha1: str, cfg: dict):
    """Consulta los proveedores en orden. Devuelve (veredicto, fuente, detalle) o None si todos fallaron."""
    consultas = [("CIRCL", lambda: _circl(sha256)), ("Team Cymru", lambda: _cymru(sha1))]
    if cfg.get("malwarebazaar_key"):
        consultas.append(("MalwareBazaar", lambda: _malwarebazaar(sha256, cfg["malwarebazaar_key"])))
    respondieron, conocido, hubo_respuesta = [], None, False
    for nombre, fn in consultas:
        r = fn()
        if r is None:
            continue
        respondieron.append(nombre)
        hubo_respuesta = True
        veredicto, detalle = r
        if veredicto in FIRMAN:  # un veredicto de malware siempre gana, aunque otra base conozca el archivo
            return veredicto, nombre, detalle
        if veredicto == "conocido_limpio":
            conocido = (nombre, detalle)
    if conocido:  # se consultó todo y nadie lo marca como malware
        return "conocido_limpio", conocido[0], conocido[1]
    return ("sin_registro", ", ".join(respondieron), None) if hubo_respuesta else None


# ---------- flujo principal ----------

def consultar_sospechosos(con, hallazgos: list[dict]) -> dict:
    """Para los hallazgos sospechosos con ejecutable: calcula hashes, los guarda y consulta su reputación.

    Devuelve {habilitado, consultados, alertas}. Debe llamarse después de guardar los hallazgos.
    """
    cfg = cargar_config()
    res = {"habilitado": bool(cfg["consulta_online"]), "consultados": 0, "alertas": []}
    vistos = set()
    for h in hallazgos:
        exe = h["exe"]
        if (h["categoria"] not in CATEGORIAS_CON_EXE or h["severidad"] not in ("alta", "media")
                or not exe or exe.endswith(" (deleted)") or h["huella"] in vistos):
            continue
        vistos.add(h["huella"])
        estado = con.execute("SELECT estado FROM hallazgos_seguridad WHERE huella=?", (h["huella"],)).fetchone()
        if estado and estado["estado"] == "falso_positivo":
            continue
        hs = hashes_de(exe)
        if not hs:
            continue
        sha256, sha1 = hs
        previo = con.execute(
            "SELECT veredicto, fuente, detalle FROM reputacion WHERE sha256=? AND consultado_en>=? "
            "AND veredicto IN ('malicioso','sospechoso','sin_registro','conocido_limpio') "
            "ORDER BY consultado_en DESC LIMIT 1", (sha256, db.ahora() - VIGENCIA_S)).fetchone()
        if previo:
            veredicto, fuente, detalle = previo["veredicto"], previo["fuente"], previo["detalle"]
        elif not cfg["consulta_online"]:
            veredicto, fuente, detalle = "sin_consultar", "local", "Consulta online desactivada"
        elif res["consultados"] >= MAX_CONSULTAS_POR_CORRIDA:
            veredicto, fuente, detalle = "sin_consultar", "local", "Pendiente: límite de consultas por corrida"
        else:
            r = consultar_hash(sha256, sha1, cfg)
            res["consultados"] += 1
            veredicto, fuente, detalle = r if r else ("error", None, "Ningún proveedor respondió")
        con.execute(
            "INSERT INTO reputacion (huella, sha256, sha1, ruta_exe, veredicto, fuente, detalle, consultado_en) "
            "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(huella) DO UPDATE SET sha256=excluded.sha256, sha1=excluded.sha1, "
            "ruta_exe=excluded.ruta_exe, veredicto=excluded.veredicto, fuente=excluded.fuente, "
            "detalle=excluded.detalle, consultado_en=excluded.consultado_en",
            (h["huella"], sha256, sha1, exe, veredicto, fuente, detalle, db.ahora()))
        if veredicto in FIRMAN:
            con.execute("UPDATE hallazgos_seguridad SET severidad='alta' WHERE huella=?", (h["huella"],))
            res["alertas"].append({"proceso": h["nombre"], "ruta": exe, "veredicto": veredicto,
                                   "fuente": fuente, "detalle": detalle, "sha256": sha256})
    return res

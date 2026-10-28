"""Escaneo de seguridad local: mineros de criptomonedas, procesos fantasma, posibles keyloggers y red.

Corre como usuario normal (sin root), por lo que solo inspecciona a fondo los procesos propios;
no detecta rootkits ni ve los descriptores de archivo de procesos de otros usuarios.
Es una alerta temprana, no un antivirus: un resultado limpio no garantiza que el equipo esté limpio.
Las listas online solo se DESCARGAN; nunca se envía información de esta máquina a ningún servicio.
"""

import hashlib
import ipaddress
import os
import re
import time
import urllib.request

import psutil

import db
import alertas
import reputacion
from db import log

# ---------- firmas ----------

NOMBRES_MINERO = {
    "xmrig", "xmr-stak", "xmr-stak-cpu", "minerd", "cpuminer", "cpuminer-multi", "cgminer", "bfgminer",
    "ethminer", "nbminer", "t-rex", "phoenixminer", "lolminer", "gminer", "teamredminer", "nanominer",
    "srbminer", "srbminer-multi", "ccminer", "kawpowminer", "minergate", "minergate-cli",
    "kdevtmpfsi", "kinsing",  # malware conocido que instala un minero
}
NOMBRES_KEYLOGGER = {
    "logkeys", "lkl", "pykeylogger", "uberkey", "kidlogger", "xkeylogger", "keylogger", "xspy", "keysniffer",
}
CMDLINE_MINERO = re.compile(
    r"stratum\+(?:tcp|ssl|tls)://|--donate-level|cryptonight|randomx|--algo[= ](?:rx|kawpow|ethash|etchash|cn)",
    re.I,
)
DOMINIOS_POOLS = (
    "nanopool.org", "minexmr.com", "supportxmr.com", "f2pool.com", "2miners.com", "ethermine.org",
    "hashvault.pro", "moneroocean.stream", "c3pool.com", "nicehash.com", "unmineable.com", "herominers.com",
    "miningpoolhub.com", "prohashing.com", "viabtc.com", "antpool.com", "slushpool.com", "poolin.com",
    "kryptex.org", "woolypooly.com", "flexpool.io", "minergate.com", "xmrpool.eu", "dwarfpool.com",
)
PUERTOS_POOL = {3333, 4444, 5555, 7777, 14433, 14444, 45560, 45700}
RUTAS_SOSPECHOSAS = ("/tmp/", "/dev/shm/", "/var/tmp/", "/run/shm/")
EXCEPCIONES_RUTA = ("/tmp/.mount_",)  # AppImage se ejecuta legítimamente desde acá
SHELLS_WEB = {"ttyd", "gotty", "wetty", "shellinabox"}  # exponen una terminal por HTTP
HILOS_KERNEL = re.compile(r"^(kworker|ksoftirqd|kthreadd|migration|rcu_|kswapd|watchdog)")

# Procesos que leen /dev/input legítimamente (se ajusta con la experiencia en esta máquina)
LECTORES_INPUT_OK = {
    "Xorg", "Xwayland", "gnome-shell", "mutter", "kwin_x11", "kwin_wayland", "systemd-logind", "upowerd",
    "ibus-daemon", "ibus-engine-simple", "fcitx5", "libinput",
}

LISTAS = {
    "feodo_ips": "https://feodotracker.abuse.ch/downloads/ipblocklist.txt",
    "nocoin_hosts": "https://raw.githubusercontent.com/hoshsadiq/adblock-nocoin-list/master/hosts.txt",
}
DIR_LISTAS = db.DIR_DATOS / "listas"
REFRESCO_LISTAS_S = 24 * 3600
MAX_BYTES_LISTA = 5_000_000


# ---------- listas online ----------

def actualizar_listas(con) -> dict:
    """Descarga las listas públicas si tienen más de 24 h. Si falla, se conserva la copia anterior."""
    DIR_LISTAS.mkdir(parents=True, exist_ok=True)
    estado = {}
    for nombre, url in LISTAS.items():
        ruta = DIR_LISTAS / f"{nombre}.txt"
        fila = con.execute("SELECT descargada_en FROM listas_seguridad WHERE nombre=?", (nombre,)).fetchone()
        if fila and ruta.exists() and db.ahora() - fila["descargada_en"] < REFRESCO_LISTAS_S:
            estado[nombre] = "vigente"
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "pc-doctor/0.1"})
            with urllib.request.urlopen(req, timeout=10) as r:
                datos = r.read(MAX_BYTES_LISTA + 1)
            if len(datos) > MAX_BYTES_LISTA:
                raise ValueError("lista demasiado grande")
            ruta.write_bytes(datos)
            entradas = len(_leer_lista(nombre))
            con.execute(
                "INSERT INTO listas_seguridad (nombre, url, descargada_en, entradas) VALUES (?,?,?,?) "
                "ON CONFLICT(nombre) DO UPDATE SET descargada_en=excluded.descargada_en, entradas=excluded.entradas",
                (nombre, url, db.ahora(), entradas))
            estado[nombre] = f"descargada ({entradas})"
        except Exception as e:  # red caída, 404, etc.: no debe romper el recolector
            log.warning("no pude actualizar la lista %s: %s", nombre, e)
            estado[nombre] = "falló (se usa copia previa)" if ruta.exists() else "falló (sin copia)"
    return estado


def _leer_lista(nombre: str) -> set[str]:
    """Carga una lista descargada: IPs (feodo) o dominios (nocoin) en minúsculas."""
    ruta = DIR_LISTAS / f"{nombre}.txt"
    try:
        lineas = ruta.read_text(errors="replace").splitlines()
    except OSError:
        return set()
    res = set()
    for l in lineas:
        l = l.strip()
        if not l or l.startswith("#"):
            continue
        partes = l.split()
        res.add((partes[1] if partes[0] in ("0.0.0.0", "127.0.0.1") and len(partes) > 1 else partes[0]).lower())
    return res


def _dominio_en_lista(texto: str, dominios: set[str]) -> str | None:
    """Devuelve el primer dominio de `texto` que esté en la lista (o cuyo dominio padre lo esté)."""
    for host in re.findall(r"[a-z0-9][a-z0-9.-]*\.[a-z]{2,}", texto.lower()):
        partes = host.split(".")
        for i in range(len(partes) - 1):
            if ".".join(partes[i:]) in dominios:
                return host
    return None


# ---------- escaneo ----------

def _h(categoria, regla, severidad, nombre, pid, exe, detalle, clave=None) -> dict:
    huella = hashlib.sha1(f"{categoria}|{regla}|{nombre}|{clave if clave is not None else exe}".encode()).hexdigest()
    return {"huella": huella, "categoria": categoria, "regla": regla, "severidad": severidad,
            "nombre": nombre, "pid": pid, "exe": exe, "detalle": detalle}


def _en_ruta_sospechosa(exe: str) -> bool:
    exe = exe.removesuffix(" (deleted)")
    return (exe.startswith(RUTAS_SOSPECHOSAS) and not exe.startswith(EXCEPCIONES_RUTA)) or exe.startswith("/memfd:")


def escanear_procesos() -> tuple[list[dict], dict]:
    """Revisa procesos: mineros, fantasmas y lectores de /dev/input. Devuelve (hallazgos, estadísticas)."""
    hallazgos, revisados, sin_acceso = [], 0, 0
    nocoin = _leer_lista("nocoin_hosts")
    for p in psutil.process_iter(["pid", "name"]):
        pid, nombre = p.info["pid"], (p.info["name"] or "?")
        revisados += 1
        try:
            exe = os.readlink(f"/proc/{pid}/exe")
        except OSError:
            exe = ""  # hilo del kernel o proceso de otro usuario
        try:
            cmd = " ".join(p.cmdline())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            cmd = ""
        if not exe and cmd:
            sin_acceso += 1
        base = os.path.basename(exe.removesuffix(" (deleted)")).lower() or nombre.lower()

        # -- mineros --
        if base in NOMBRES_MINERO or nombre.lower() in NOMBRES_MINERO:
            hallazgos.append(_h("minero", "nombre_conocido", "alta", nombre, pid, exe, f"Proceso con nombre de minero: {nombre}"))
        elif CMDLINE_MINERO.search(cmd):
            hallazgos.append(_h("minero", "cmdline_minero", "alta", nombre, pid, exe, f"Argumentos típicos de minero: {cmd[:160]}"))
        else:
            pool = next((d for d in DOMINIOS_POOLS if d in cmd.lower()), None)
            if pool:
                hallazgos.append(_h("minero", "pool_en_cmdline", "alta", nombre, pid, exe, f"Menciona el pool {pool}: {cmd[:160]}"))
        if cmd and nocoin:
            host = _dominio_en_lista(cmd, nocoin)
            if host:
                hallazgos.append(_h("lista_online", "nocoin_cmdline", "alta", nombre, pid, exe, f"Dominio {host} está en la lista NoCoin"))

        # -- terminal web expuesta sin autenticación --
        if base in SHELLS_WEB:
            con_auth = re.search(r"(?:^|\s)(?:-c|--credential)(?:\s|=)", cmd)
            solo_local = re.search(r"(?:^|\s)(?:-i|--interface)[ =](?:127\.|lo\b|localhost)", cmd)
            if not con_auth and not solo_local:
                hallazgos.append(_h("red", "shell_web_sin_auth", "alta", nombre, pid, exe,
                                    "Terminal web accesible desde la red y sin credenciales: cualquiera en la LAN obtiene una shell"))

        # -- keyloggers por nombre --
        if base in NOMBRES_KEYLOGGER:
            hallazgos.append(_h("keylogger", "nombre_conocido", "alta", nombre, pid, exe, f"Proceso con nombre de keylogger: {nombre}"))

        # -- fantasmas --
        if exe:
            if _en_ruta_sospechosa(exe):
                hallazgos.append(_h("fantasma", "ejecuta_desde_tmp", "alta", nombre, pid, exe, f"Ejecutable en ruta temporal: {exe}"))
            elif exe.endswith(" (deleted)"):
                hallazgos.append(_h("fantasma", "binario_borrado", "baja", nombre, pid, exe,
                                    "El binario fue borrado y el proceso sigue vivo (suele ser un servicio tras actualizar paquetes; reiniciarlo lo resuelve)"))
            if HILOS_KERNEL.match(nombre):
                hallazgos.append(_h("fantasma", "imita_hilo_kernel", "alta", nombre, pid, exe, f"Se hace pasar por hilo del kernel pero tiene ejecutable: {exe}"))
            if nombre.startswith(".") or os.path.basename(exe).startswith("."):
                hallazgos.append(_h("fantasma", "nombre_oculto", "media", nombre, pid, exe, f"Nombre u ejecutable oculto: {exe}"))
        try:
            pre = open(f"/proc/{pid}/environ", "rb").read().split(b"\0")
            for var in pre:
                if (var.startswith(b"LD_PRELOAD=") and any(r.encode() in var for r in RUTAS_SOSPECHOSAS)
                        and b"gameoverlayrenderer.so" not in var):  # overlay de Steam: legítimo
                    hallazgos.append(_h("fantasma", "ld_preload_tmp", "alta", nombre, pid, exe, f"LD_PRELOAD apunta a ruta temporal: {var.decode(errors='replace')[:120]}"))
        except OSError:
            pass

        # -- lectores de /dev/input (posible keylogger) --
        try:
            for fd in os.listdir(f"/proc/{pid}/fd"):
                try:
                    destino = os.readlink(f"/proc/{pid}/fd/{fd}")
                except OSError:
                    continue
                if destino.startswith("/dev/input/event") and nombre not in LECTORES_INPUT_OK:
                    hallazgos.append(_h("keylogger", "lee_dev_input", "media", nombre, pid, exe,
                                        f"Tiene abierto {destino}; puede ser legítimo (juegos, mandos, remapeo) o un keylogger", clave=exe or nombre))
                    break
        except OSError:
            pass
    return hallazgos, {"procesos": revisados, "sin_acceso": sin_acceso}


def conexiones() -> tuple[list[dict], list[dict]]:
    """Devuelve (escuchas, establecidas) de sockets inet. Sin root, el pid solo se conoce para procesos propios."""
    escuchas, establecidas, nombres = [], [], {}

    def nombre_de(pid):
        if pid is None:
            return "desconocido (otro usuario)"
        if pid not in nombres:
            try:
                nombres[pid] = psutil.Process(pid).name()
            except psutil.Error:
                nombres[pid] = "?"
        return nombres[pid]

    try:
        socks = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, OSError) as e:
        log.warning("no pude listar conexiones: %s", e)
        return [], []
    for c in socks:
        proto = "tcp" if c.type == 1 else "udp"
        if c.laddr and ((proto == "tcp" and c.status == psutil.CONN_LISTEN) or (proto == "udp" and not c.raddr)):
            escuchas.append({"proto": proto + ("6" if c.family == 10 else ""), "direccion": c.laddr.ip,
                             "puerto": c.laddr.port, "pid": c.pid, "proceso": nombre_de(c.pid)})
        elif c.raddr and c.status == psutil.CONN_ESTABLISHED:
            establecidas.append({"remoto": c.raddr.ip, "puerto": c.raddr.port, "pid": c.pid, "proceso": nombre_de(c.pid)})
    return escuchas, establecidas


def _es_loopback(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip.split("%")[0]).is_loopback
    except ValueError:
        return False


def escanear_red() -> tuple[list[dict], list[dict]]:
    """Analiza la red. Devuelve (hallazgos, escuchas)."""
    escuchas, establecidas = conexiones()
    feodo = _leer_lista("feodo_ips")
    hallazgos = []
    for e in escuchas:
        if e["proto"].startswith("tcp") and not _es_loopback(e["direccion"]):
            hallazgos.append(_h("red", "escucha_externa", "baja", e["proceso"], e["pid"], "",
                                f"Escucha en {e['direccion']}:{e['puerto']} (accesible desde la red)", clave=f"{e['proto']}:{e['puerto']}"))
    for c in establecidas:
        try:
            publica = ipaddress.ip_address(c["remoto"]).is_global
        except ValueError:
            continue
        if c["remoto"] in feodo:
            hallazgos.append(_h("lista_online", "ip_botnet_c2", "alta", c["proceso"], c["pid"], "",
                                f"Conexión a {c['remoto']}:{c['puerto']}, IP de C2 en Feodo Tracker", clave=c["remoto"]))
        elif publica and c["puerto"] in PUERTOS_POOL:
            hallazgos.append(_h("minero", "puerto_de_pool", "baja", c["proceso"], c["pid"], "",
                                f"Conexión a {c['remoto']}:{c['puerto']}, puerto típico de pools (suele ser falso positivo)", clave=f"{c['remoto']}:{c['puerto']}"))
    return hallazgos, escuchas


def escanear() -> dict:
    """Escaneo completo en vivo. Devuelve hallazgos, escuchas y estadísticas (no escribe en la base)."""
    h1, stats = escanear_procesos()
    h2, escuchas = escanear_red()
    orden = {"alta": 0, "media": 1, "baja": 2}
    hallazgos = sorted(h1 + h2, key=lambda h: orden[h["severidad"]])
    return {"hallazgos": hallazgos, "escuchas": escuchas, "stats": stats}


# ---------- persistencia ----------

def guardar(con, resultado: dict) -> dict:
    """Guarda hallazgos (con deduplicación por huella) y escuchas. Devuelve {nuevos, total, escuchas_nuevas}."""
    ahora, nuevos = db.ahora(), 0
    for h in resultado["hallazgos"]:
        existe = con.execute("SELECT 1 FROM hallazgos_seguridad WHERE huella=?", (h["huella"],)).fetchone()
        nuevos += 0 if existe else 1
        con.execute(
            "INSERT INTO hallazgos_seguridad (huella, categoria, regla, severidad, nombre, pid, ruta_exe, detalle, "
            "primera_vez, ultima_vez) VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(huella) DO UPDATE SET ultima_vez=excluded.ultima_vez, veces=veces+1, "
            "pid=excluded.pid, detalle=excluded.detalle",
            (h["huella"], h["categoria"], h["regla"], h["severidad"], h["nombre"], h["pid"], h["exe"],
             h["detalle"], ahora, ahora))
    esc_nuevas = 0
    for e in resultado["escuchas"]:
        existe = con.execute("SELECT 1 FROM escuchas WHERE proto=? AND direccion=? AND puerto=? AND proceso=?",
                             (e["proto"], e["direccion"], e["puerto"], e["proceso"])).fetchone()
        esc_nuevas += 0 if existe else 1
        con.execute(
            "INSERT INTO escuchas (proto, direccion, puerto, proceso, pid, primera_vez, ultima_vez) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(proto, direccion, puerto, proceso) DO UPDATE SET ultima_vez=excluded.ultima_vez, pid=excluded.pid",
            (e["proto"], e["direccion"], e["puerto"], e["proceso"], e["pid"], ahora, ahora))
    return {"nuevos": nuevos, "total": len(resultado["hallazgos"]), "escuchas_nuevas": esc_nuevas}


def revisar_y_guardar(con) -> dict:
    """Paso del recolector: actualiza listas (máx. 1 vez al día), escanea y guarda."""
    inicio = db.ahora()
    listas = actualizar_listas(con)
    res = escanear()
    r = guardar(con, res)
    r["listas"] = listas
    r["reputacion"] = reputacion.consultar_sospechosos(con, res["hallazgos"])
    r["notificados"] = alertas.avisar(con, inicio)
    return r

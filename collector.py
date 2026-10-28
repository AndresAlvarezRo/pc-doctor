"""Recolector pasivo de pc-doctor: lo ejecuta el systemd user timer y termina en pocos segundos."""

import hashlib
import json
import logging
import os
import platform
import re
import socket
import sys
from pathlib import Path

import psutil

import actividad
import db
import linea_base
import salud
import seguridad
from db import ejecutar, log

MAX_EVENTOS = 50
RETENCION_DIAS = 30


# ---------- workspace y entorno ----------

def registrar_workspace(con) -> int:
    """Devuelve el id del workspace de esta máquina, creándolo si no existe."""
    try:
        machine_id = Path("/etc/machine-id").read_text().strip()
    except OSError:
        machine_id = socket.gethostname()
    fila = con.execute("SELECT id FROM workspace WHERE machine_id=?", (machine_id,)).fetchone()
    if fila:
        return fila["id"]
    cur = con.execute(
        "INSERT INTO workspace (hostname, machine_id, etiqueta, creado_en) VALUES (?,?,?,?)",
        (socket.gethostname(), machine_id, socket.gethostname(), db.ahora()),
    )
    return cur.lastrowid


def leer_distro() -> str:
    """Nombre bonito de la distro desde /etc/os-release."""
    try:
        for linea in Path("/etc/os-release").read_text().splitlines():
            if linea.startswith("PRETTY_NAME="):
                return linea.split("=", 1)[1].strip('"')
    except OSError:
        pass
    return platform.system()


def paquetes_apt() -> list[tuple[str, str, str]]:
    """Lista (nombre, versión, 'apt') de paquetes instalados con dpkg."""
    salida = ejecutar(["dpkg-query", "-W", "-f=${Package}\t${Version}\t${db:Status-Abbrev}\n"])
    res = []
    for linea in (salida or "").splitlines():
        partes = linea.split("\t")
        if len(partes) == 3 and partes[2].startswith("ii"):
            res.append((partes[0], partes[1], "apt"))
    return res


def paquetes_flatpak() -> list[tuple[str, str, str]]:
    """Lista de aplicaciones y runtimes flatpak."""
    salida = ejecutar(["flatpak", "list", "--columns=application,version"])
    res = []
    for linea in (salida or "").splitlines():
        partes = linea.split("\t")
        if partes and partes[0].strip():
            res.append((partes[0].strip(), partes[1].strip() if len(partes) > 1 else "", "flatpak"))
    return res


def paquetes_snap() -> list[tuple[str, str, str]]:
    """Lista de snaps instalados."""
    salida = ejecutar(["snap", "list"])
    res = []
    for linea in (salida or "").splitlines()[1:]:
        partes = linea.split()
        if len(partes) >= 2:
            res.append((partes[0], partes[1], "snap"))
    return res


# IDs de proveedor PCI conocidos; cualquier otro se informa con su ID crudo.
PROVEEDORES_PCI = {
    "10de": "NVIDIA", "1002": "AMD", "1022": "AMD", "8086": "Intel",
    "1a03": "ASPEED", "15ad": "VMware", "1af4": "Red Hat (virtio)", "1234": "QEMU",
    "5143": "Qualcomm", "13b5": "ARM", "1414": "Microsoft", "80ee": "VirtualBox",
}


def _version_modulo(modulo: str) -> str | None:
    """Versión de un módulo del kernel: /sys/module, /proc (NVIDIA) o `modinfo`; None si es interno al kernel."""
    for ruta in (f"/sys/module/{modulo}/version", "/proc/driver/nvidia/version" if modulo == "nvidia" else ""):
        if ruta:
            try:
                texto = Path(ruta).read_text().strip()
                m = re.search(r"\d+(?:\.\d+)+", texto)
                if m:
                    return m.group(0)
            except OSError:
                pass
    salida = ejecutar(["modinfo", "-F", "version", modulo])
    return salida.strip() or None if salida else None


def _version_mesa() -> str | None:
    """Versión de Mesa (driver de espacio de usuario de AMD/Intel/otros) desde dpkg."""
    salida = ejecutar(["dpkg-query", "-W", "-f=${Version}", "libgl1-mesa-dri"])
    return salida.strip() or None if salida else None


def hardware_gpu() -> list[dict]:
    """Detecta todas las GPU (cualquier fabricante) con `lspci -nnk` y agrega driver y su versión.

    Informa: desc, proveedor, id_pci, driver (módulo del kernel en uso) y version_driver.
    Para NVIDIA la versión viene del módulo propietario; para AMD/Intel, del módulo si la expone
    y, si no, se informa el kernel (driver in-tree) junto con la versión de Mesa.
    """
    res = []
    salida = ejecutar(["lspci", "-nnk"])
    for bloque in re.split(r"\n(?=\S)", salida or ""):
        primera = bloque.splitlines()[0] if bloque else ""
        if not re.search(r"VGA compatible|3D controller|Display controller", primera):
            continue
        desc = re.sub(r"^\S+\s+[^:]+:\s*", "", primera)
        ids = re.findall(r"\[([0-9a-f]{4}):([0-9a-f]{4})\]", primera)
        vendor_id = ids[-1][0] if ids else ""
        m = re.search(r"Kernel driver in use: (\S+)", bloque)
        driver = m.group(1) if m else None
        gpu = {"desc": desc, "proveedor": PROVEEDORES_PCI.get(vendor_id, f"desconocido ({vendor_id})"),
               "id_pci": ":".join(ids[-1]) if ids else None, "driver": driver}
        if driver:
            version = _version_modulo(driver)
            if version:
                gpu["version_driver"] = version
            else:
                gpu["version_driver"] = f"kernel {platform.release()} (in-tree)"
            if driver != "nvidia":
                mesa = _version_mesa()
                if mesa:
                    gpu["mesa"] = mesa
        res.append(gpu)
    # NVIDIA propietario: nvidia-smi es la fuente más exacta de la versión del driver
    ver = ejecutar(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"])
    if ver and ver.strip():
        for g in res:
            if g["proveedor"] == "NVIDIA":
                g["version_driver"] = ver.strip().splitlines()[0]
    return res


def _dmi(nombre: str) -> str:
    try:
        return Path(f"/sys/class/dmi/id/{nombre}").read_text().strip()
    except OSError:
        return ""


def recolectar_hardware() -> list[tuple[str, str, str, dict]]:
    """Devuelve filas (tipo, marca, modelo, detalle) de hardware."""
    filas = []
    # CPU: x86 expone "vendor_id"/"model name"; ARM y otros se resuelven con lscpu
    modelo, vendor = "", ""
    try:
        for l in Path("/proc/cpuinfo").read_text().splitlines():
            if l.startswith("model name") and not modelo:
                modelo = l.split(":", 1)[1].strip()
            elif l.startswith("vendor_id") and not vendor:
                vendor = l.split(":", 1)[1].strip()
    except OSError:
        pass
    if not modelo or not vendor:
        for l in (ejecutar(["lscpu"]) or "").splitlines():
            clave, _, valor = l.partition(":")
            if clave.strip() == "Model name" and not modelo:
                modelo = valor.strip()
            elif clave.strip() == "Vendor ID" and not vendor:
                vendor = valor.strip()
    marcas_cpu = {"GenuineIntel": "Intel", "AuthenticAMD": "AMD", "HygonGenuine": "Hygon", "ARM": "ARM",
                  "Apple": "Apple", "Qualcomm": "Qualcomm"}
    marca = marcas_cpu.get(vendor) or next(
        (m for m in ("Intel", "AMD", "Apple", "Qualcomm") if m.lower() in modelo.lower()), vendor)
    filas.append(("cpu", marca, modelo, {
        "arquitectura": platform.machine(),
        "nucleos_fisicos": psutil.cpu_count(logical=False),
        "hilos": psutil.cpu_count(logical=True),
    }))
    # GPU
    for g in hardware_gpu():
        desc = g["desc"]
        filas.append(("gpu", g["proveedor"], desc, {k: v for k, v in g.items() if k not in ("desc", "proveedor")}))
    # RAM
    vm = psutil.virtual_memory()
    filas.append(("ram", "", "", {"total_gb": round(vm.total / 2**30, 1),
                                  "swap_gb": round(psutil.swap_memory().total / 2**30, 1)}))
    # Discos
    salida = ejecutar(["lsblk", "-d", "-J", "-o", "NAME,MODEL,SIZE,ROTA,TYPE"])
    try:
        for d in json.loads(salida or "{}").get("blockdevices", []):
            if d.get("type") == "disk":
                modelo_d = (d.get("model") or "").strip()
                filas.append(("disco", modelo_d.split(" ")[0] if modelo_d else "", modelo_d,
                              {"dev": d.get("name"), "tamano": d.get("size"),
                               "tipo": "HDD" if d.get("rota") in (True, "1", 1) else "SSD"}))
    except ValueError:
        log.warning("lsblk devolvió JSON inválido")
    # Placa madre
    filas.append(("mother", _dmi("board_vendor"), _dmi("board_name"),
                  {"bios": _dmi("bios_version"), "producto": _dmi("product_name")}))
    return filas


def snapshot_entorno(con, ws: int) -> bool:
    """Guarda un snapshot nuevo solo si cambió el hash de (kernel + driver GPU + paquetes)."""
    kernel = platform.release()
    hw = recolectar_hardware()
    drivers = sorted(
        f"{d.get('driver')}:{d.get('version_driver', '')}"
        for t, _, _, d in hw if t == "gpu"
    )
    paquetes = paquetes_apt() + paquetes_flatpak() + paquetes_snap()
    base = "\n".join([kernel, ",".join(drivers)] + sorted(f"{o}|{n}|{v}" for n, v, o in paquetes))
    h = hashlib.sha256(base.encode()).hexdigest()

    ultimo = con.execute(
        "SELECT hash FROM snapshot_entorno WHERE workspace_id=? ORDER BY tomado_en DESC, id DESC LIMIT 1",
        (ws,),
    ).fetchone()
    if ultimo and ultimo["hash"] == h:
        return False

    escritorio = os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION") or ""
    cur = con.execute(
        "INSERT INTO snapshot_entorno (workspace_id, tomado_en, distro, kernel, escritorio, hash) "
        "VALUES (?,?,?,?,?,?)",
        (ws, db.ahora(), leer_distro(), kernel, escritorio, h),
    )
    sid = cur.lastrowid
    con.executemany(
        "INSERT INTO hardware (snapshot_id, tipo, marca, modelo, detalle) VALUES (?,?,?,?,?)",
        [(sid, t, m, mo, json.dumps(d, ensure_ascii=False)) for t, m, mo, d in hw],
    )
    con.executemany(
        "INSERT INTO software (snapshot_id, nombre, version, origen) VALUES (?,?,?,?)",
        [(sid, n, v, o) for n, v, o in paquetes],
    )
    return True


# ---------- métricas ----------

def guardar_metricas(con, ws: int) -> int:
    """Toma una muestra de métricas y el top 5 de procesos. Devuelve el id de la métrica."""
    cpu = psutil.cpu_percent(interval=1)
    try:
        libre = psutil.disk_usage("/").free / 2**30
    except OSError:
        libre = None
    cur = con.execute(
        "INSERT INTO metricas (workspace_id, ts, cpu_pct, ram_pct, swap_pct, temp_cpu, temp_gpu, "
        "disco_libre_gb, load_1m) VALUES (?,?,?,?,?,?,?,?,?)",
        (ws, db.ahora(), cpu, psutil.virtual_memory().percent, psutil.swap_memory().percent,
         db.temperatura_cpu(), db.temperatura_gpu(),
         round(libre, 2) if libre is not None else None, os.getloadavg()[0]),
    )
    mid = cur.lastrowid
    con.executemany(
        "INSERT INTO top_procesos (metrica_id, nombre, cpu_pct, ram_mb) VALUES (?,?,?,?)",
        [(mid, p["nombre"], p["cpu_pct"], p["ram_mb"]) for p in db.top_procesos(5)],
    )
    return mid


# ---------- eventos del journal ----------

SEVERIDADES = {"0": "emerg", "1": "alert", "2": "crit", "3": "err"}


def guardar_eventos(con) -> int:
    """Guarda hasta MAX_EVENTOS errores de journalctl desde el último ts guardado."""
    fila = con.execute("SELECT MAX(ts) AS m FROM eventos").fetchone()
    desde = (fila["m"] or db.ahora() - 3600) + 1
    salida = ejecutar(["journalctl", "-p", "err", "--since", f"@{desde}", "-o", "json",
                       "-n", str(MAX_EVENTOS), "--no-pager"])
    n = 0
    for linea in (salida or "").splitlines():
        try:
            e = json.loads(linea)
            ts = int(e["__REALTIME_TIMESTAMP"]) // 1_000_000
            msg = e.get("MESSAGE", "")
            if isinstance(msg, list):  # mensaje binario
                msg = bytes(msg).decode("utf-8", "replace")
            con.execute(
                "INSERT INTO eventos (ts, origen, severidad, mensaje) VALUES (?,?,?,?)",
                (ts, e.get("SYSLOG_IDENTIFIER") or e.get("_COMM") or "?",
                 SEVERIDADES.get(str(e.get("PRIORITY")), "err"), str(msg)[:500]),
            )
            n += 1
        except (ValueError, KeyError, TypeError) as ex:
            log.warning("evento del journal ilegible: %s", ex)
    return n


# ---------- retención ----------

def aplicar_retencion(con) -> int:
    """Resume en metricas_diarias las métricas de más de 30 días y luego las borra (también lecturas y alertas viejas)."""
    corte = db.ahora() - RETENCION_DIAS * 86400
    linea_base.mantener(con)  # resumir en lecturas_diarias antes de borrar las lecturas crudas
    con.execute("DELETE FROM lecturas WHERE ts < ?", (corte,))
    con.execute("DELETE FROM alertas_salud WHERE activa=0 AND resuelta_en < ?", (db.ahora() - 90 * 86400,))
    viejas = con.execute("SELECT COUNT(*) AS n FROM metricas WHERE ts < ?", (corte,)).fetchone()["n"]
    if not viejas:
        return 0
    con.execute(
        """
        INSERT OR REPLACE INTO metricas_diarias
        SELECT date(ts,'unixepoch','localtime') AS dia, workspace_id, COUNT(*),
               AVG(cpu_pct), MAX(cpu_pct), AVG(ram_pct), MAX(ram_pct),
               AVG(swap_pct), MAX(swap_pct), AVG(temp_cpu), MAX(temp_cpu),
               AVG(temp_gpu), MAX(temp_gpu), MIN(disco_libre_gb), AVG(load_1m), MAX(load_1m)
        FROM metricas WHERE ts < ? GROUP BY dia, workspace_id
        """,
        (corte,),
    )
    con.execute("DELETE FROM top_procesos WHERE metrica_id IN (SELECT id FROM metricas WHERE ts < ?)", (corte,))
    con.execute("DELETE FROM metricas WHERE ts < ?", (corte,))
    return viejas


# ---------- principal ----------

def paso(nombre: str, fn, *args):
    """Ejecuta un paso del recolector; si falla lo loguea y devuelve None sin interrumpir."""
    try:
        return fn(*args)
    except Exception:
        log.exception("falló el paso %s", nombre)
        return None


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    con = db.conectar()
    ws = registrar_workspace(con)
    con.commit()
    for nombre, fn, args in (
        ("metricas", guardar_metricas, (con, ws)),
        ("eventos", guardar_eventos, (con,)),
        ("actividad", actividad.registrar, (con,)),  # antes de salud: el contexto de las lecturas depende de esto
        ("snapshot", snapshot_entorno, (con, ws)),  # antes de salud: así un aviso de esta corrida puede citar el cambio que acaba de pasar
        ("salud", salud.ciclo, (con,)),
        ("seguridad", seguridad.revisar_y_guardar, (con,)),
        ("retencion", aplicar_retencion, (con,)),
    ):
        r = paso(nombre, fn, *args)
        con.commit()
        log.info("%s: %s", nombre, r)
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Salud del equipo: lee sensores, aplica reglas de "valores normales" y avisa con notificaciones de escritorio.

Los sensores se leen de /sys/class/hwmon, así que sirve para cualquier fabricante (AMD, Intel, NVIDIA vía
nvidia-smi) y sin root. Lo que el kernel no expone (voltajes de placa, SMART de discos SATA) no se inventa:
`estado_salud()` lo informa como no disponible.
"""

import json
import re
import subprocess
import time
from pathlib import Path

import psutil

import actividad
import alertas
import correlacion
import db
import linea_base
from db import ejecutar, log
from reputacion import cargar_config

HWMON = Path("/sys/class/hwmon")
# entradas de temperatura sin sensor real en muchas placas (termistores sin conectar, valores de calibración o del chipset)
TEMP_SIN_SENSOR = re.compile(r"^(AUXTIN\d*|PECI Agent \d+ Calibration|PCH_.*)$")
DRM = Path("/sys/class/drm")
REPETIR_S = {"aviso": 6 * 3600, "critico": 2 * 3600}  # cada cuánto se repite un aviso que persiste
VENTANA_EVENTOS_S = 24 * 3600
MAX_EN_AVISO = 4  # alertas que se detallan en una notificación; el resto se resume
ESPERA_IO_S = 0.5

CHIP_CATEGORIA = {
    "k10temp": "cpu", "coretemp": "cpu", "zenpower": "cpu", "cpu_thermal": "cpu",
    "amdgpu": "gpu", "radeon": "gpu", "nouveau": "gpu", "i915": "gpu", "xe": "gpu",
    "nvme": "disco", "drivetemp": "disco",
}
# Etiquetas de voltaje de la placa que tienen un valor nominal conocido (mV)
RIELES = ((re.compile(r"(^|[^0-9.])12 ?v", re.I), 12000), (re.compile(r"(^|[^0-9.])5 ?v|5vcc", re.I), 5000),
          (re.compile(r"3\.3 ?v|3v3|3vcc|avcc", re.I), 3300))
FS_REALES = {"ext4", "ext3", "btrfs", "xfs", "ntfs", "ntfs3", "fuseblk", "vfat", "exfat", "f2fs"}
DISCO_FISICO = re.compile(r"^(sd[a-z]+|nvme\d+n\d+|vd[a-z]+|mmcblk\d+|hd[a-z]+)$")

# Reglas de "valores normales". `rel` = (aviso, crítico) como distancia bajo el límite crítico que informa el hardware
# (con un valor por defecto si no lo informa). `muestras` = lecturas consecutivas (una cada 15 min) para el aviso;
# el crítico salta con una sola. `margen` evita que la alerta parpadee al volver a la normalidad.
# Cualquier valor se puede cambiar en config.json -> "umbrales": {"temp_cpu": {"aviso": 80, "muestras": 1}}.
REGLAS = [
    dict(id="temp_cpu", cat="cpu", unidad="°C", aviso=85, critico=92, muestras=2, margen=4, texto="Temperatura de CPU"),
    dict(id="temp_gpu", cat="gpu", unidad="°C", rel=(20, 8, 105), muestras=2, margen=4, texto="Temperatura de GPU"),
    dict(id="temp_disco", cat="disco", unidad="°C", rel=(18, 8, 85), muestras=2, margen=3, texto="Temperatura de disco"),
    dict(id="temp_placa", cat="placa", unidad="°C", aviso=80, critico=95, muestras=2, margen=4, texto="Temperatura de la placa"),
    dict(id="gpu_uso", cat="gpu", sufijo="/uso", aviso=95, critico=None, muestras=8, margen=5, texto="Uso de GPU sostenido"),
    dict(id="gpu_vram", cat="gpu", sufijo="/vram_pct", aviso=95, critico=99, muestras=2, margen=3, texto="VRAM de GPU"),
    dict(id="gpu_voltaje", cat="gpu", unidad="mV", aviso=1250, critico=1350, muestras=1, margen=50, texto="Voltaje de GPU"),
    dict(id="cpu_uso", cat="cpu", sufijo="/uso", aviso=95, critico=None, muestras=4, margen=5, texto="Uso de CPU sostenido"),
    dict(id="cpu_carga", cat="cpu", sufijo="/carga_por_hilo", aviso=1.5, critico=3, muestras=3, margen=0.2, texto="Carga del sistema"),
    dict(id="ram", cat="memoria", sufijo="/ram_pct", aviso=90, critico=96, muestras=2, margen=3, texto="Uso de RAM"),
    dict(id="swap", cat="memoria", sufijo="/swap_pct", aviso=50, critico=80, muestras=2, margen=5, texto="Uso de swap"),
    dict(id="disco_libre", cat="disco", sufijo="/libre_pct", dir="min", aviso=15, critico=7, muestras=1, margen=2, texto="Poco espacio libre"),
    dict(id="disco_io", cat="disco", sufijo="/io_util_pct", aviso=95, critico=None, muestras=3, margen=5, texto="Disco saturado"),
    dict(id="disco_ro", cat="disco", sufijo="/solo_lectura", aviso=None, critico=1, muestras=1, margen=0, texto="Partición en solo lectura"),
    dict(id="smart_fallo", cat="disco", sufijo="/smart_ok", dir="min", aviso=None, critico=0, muestras=1, margen=0, texto="SMART reporta fallo"),
    dict(id="smart_pendientes", cat="disco", sufijo="/sectores_pendientes", aviso=1, critico=10, muestras=1, margen=0, texto="Sectores pendientes de realocar"),
    dict(id="smart_incorregibles", cat="disco", sufijo="/sectores_incorregibles", aviso=1, critico=10, muestras=1, margen=0, texto="Sectores incorregibles"),
    dict(id="smart_realocados", cat="disco", sufijo="/sectores_realocados", aviso=5, critico=50, muestras=1, margen=0, texto="Sectores realocados"),
    dict(id="smart_crc", cat="disco", sufijo="/errores_crc", aviso=10, critico=None, muestras=1, margen=0, texto="Errores CRC (posible cable)"),
    dict(id="smart_medio", cat="disco", sufijo="/errores_medio", aviso=1, critico=None, muestras=1, margen=0, texto="Errores de medio NVMe"),
    dict(id="smart_alerta", cat="disco", sufijo="/alerta_critica", aviso=None, critico=1, muestras=1, margen=0, texto="Alerta crítica NVMe"),
    dict(id="smart_desgaste", cat="disco", sufijo="/desgaste_pct", aviso=80, critico=95, muestras=1, margen=2, texto="Desgaste del disco"),
    dict(id="smart_spare", cat="disco", sufijo="/spare_pct", dir="min", aviso=20, critico=10, muestras=1, margen=2, texto="Reserva del disco NVMe"),
    dict(id="riel", cat="placa", sufijo="/desviacion_pct", abs=True, aviso=7, critico=10, muestras=2, margen=1, texto="Voltaje fuera de rango"),
]

# Eventos del journal que indican problemas reales (patrones específicos: los genéricos dan falsos positivos
# con mensajes normales del arranque como "Registered thermal governor" o "EDAC MC: Ver").
PATRONES_EVENTO = [
    ("disco_io", "disco", "critico", "Error de E/S o del sistema de archivos",
     r"I/O error|EXT4-fs error|Buffer I/O error|blk_update_request|critical medium error|"
     r"ata\d+(\.\d+)?: .*(failed command|exception Emask|hard resetting link)|"
     r"nvme\d+.*(I/O \d+ .*timeout|controller is down|resetting controller|I/O Error)|XFS .*(corruption|metadata I/O error)|BTRFS.*(error|corrupt)"),
    ("gpu_fallo", "gpu", "critico", "Fallo de la GPU",
     r"amdgpu.*(ring \S+ timeout|GPU reset|VM fault|\*ERROR\* (?!.*pm))|NVRM: Xid|i915.*GPU HANG|\[drm\] GPU HANG"),
    ("memoria", "memoria", "critico", "Memoria agotada o con errores",
     r"Out of memory|oom-kill|Killed process \d+|mce: .*[Hh]ardware [Ee]rror|Machine check events logged|EDAC .*(CE|UE) "),
    ("termico", "cpu", "aviso", "Limitación térmica",
     r"(thermal|temperature).*(above threshold|throttl)|Package temperature above threshold|thermal.*critical"),
    ("energia", "placa", "aviso", "Problema de energía o PCIe",
     r"PCIe Bus Error: severity=(Uncorrected|Fatal)|AER:.*(Uncorrected|Fatal)|(under|brown)-?volt"),
]
PATRONES_EVENTO = [(i, c, s, t, re.compile(p)) for i, c, s, t, p in PATRONES_EVENTO]


# ---------- lectura de sensores ----------

def _txt(p: Path) -> str | None:
    try:
        return p.read_text().strip()
    except OSError:
        return None


def _num(p: Path) -> float | None:
    t = _txt(p)
    try:
        return float(t) if t is not None else None
    except ValueError:
        return None


def _l(cat: str, nombre: str, valor: float, unidad: str, crit: float | None = None) -> dict:
    return {"categoria": cat, "nombre": nombre, "valor": round(float(valor), 2), "unidad": unidad, "crit": crit}


def _hwmon() -> list[dict]:
    """Temperaturas, ventiladores, voltajes y potencia de todos los chips de /sys/class/hwmon."""
    res = []
    for d in sorted(HWMON.glob("hwmon*")):
        chip = _txt(d / "name") or d.name
        cat = CHIP_CATEGORIA.get(chip, "placa")
        disco = next(iter(sorted((d / "device" / "block").glob("*"))), None)  # ej. drivetemp: un chip por disco
        if disco:
            chip = f"{chip}_{disco.name}"
        for f in sorted(d.glob("temp*_input")):
            i = re.fullmatch(r"temp(\d+)_input", f.name)
            v = _num(f)
            if not i or v is None or not -40 < v / 1000 < 150:
                continue
            idx = i.group(1)
            if TEMP_SIN_SENSOR.match(_txt(d / f"temp{idx}_label") or ""):
                continue
            crit = _num(d / f"temp{idx}_crit")
            crit = crit / 1000 if crit and 30 < crit / 1000 < 150 else None  # descarta límites absurdos (ej. 65261 °C)
            res.append(_l(cat, f"{chip}/{_txt(d / f'temp{idx}_label') or 'temp' + idx}", v / 1000, "°C", crit))
        for f in sorted(d.glob("fan*_input")):
            i = re.fullmatch(r"fan(\d+)_input", f.name)
            v = _num(f)
            if i and v is not None:
                res.append(_l(cat, f"{chip}/{_txt(d / f'fan{i.group(1)}_label') or 'fan' + i.group(1)}", v, "RPM"))
        for f in sorted(d.glob("in*_input")):
            i = re.fullmatch(r"in(\d+)_input", f.name)
            v = _num(f)
            if not i or v is None:
                continue
            etiqueta = _txt(d / f"in{i.group(1)}_label") or f"in{i.group(1)}"
            res.append(_l(cat, f"{chip}/{etiqueta}", v, "mV"))
            if cat == "placa":  # solo los rieles con valor nominal conocido se evalúan por desviación
                nominal = next((n for rx, n in RIELES if rx.search(etiqueta)), None)
                if nominal:
                    res.append(_l(cat, f"{chip}/{etiqueta}/desviacion_pct", (v - nominal) / nominal * 100, "%"))
        for f in sorted(d.glob("power*_average")) + sorted(d.glob("power*_input")):
            i = re.search(r"power(\d+)_", f.name)
            v = _num(f)
            if i and v is not None:
                res.append(_l(cat, f"{chip}/{_txt(d / f'power{i.group(1)}_label') or 'power' + i.group(1)}", v / 1e6, "W"))
                break
    return res


def _gpu_amd() -> list[dict]:
    """Uso y VRAM de GPU AMD desde sysfs (el proveedor 0x1002 identifica a AMD)."""
    res = []
    for d in sorted(DRM.glob("card[0-9]*/device")):
        if _txt(d / "vendor") != "0x1002":
            continue
        uso = _num(d / "gpu_busy_percent")
        usada, total = _num(d / "mem_info_vram_used"), _num(d / "mem_info_vram_total")
        if uso is not None:
            res.append(_l("gpu", "amdgpu/uso", uso, "%"))
        if usada is not None and total:
            res.append(_l("gpu", "amdgpu/vram_pct", usada / total * 100, "%"))
    return res


def parsear_nvidia(salida: str) -> list[dict]:
    """Interpreta la salida CSV de nvidia-smi (temp, uso, VRAM usada/total, potencia, ventilador)."""
    res = []
    for n, linea in enumerate((salida or "").strip().splitlines()):
        campos = [c.strip() for c in linea.split(",")]
        if len(campos) < 6:
            continue

        def f(x):
            try:
                return float(x)
            except ValueError:
                return None  # "[N/A]"
        temp, uso, usada, total, pot, vent = map(f, campos[:6])
        p = f"nvidia{n}"
        if temp is not None:
            res.append(_l("gpu", f"{p}/temp", temp, "°C", 95))
        if uso is not None:
            res.append(_l("gpu", f"{p}/uso", uso, "%"))
        if usada is not None and total:
            res.append(_l("gpu", f"{p}/vram_pct", usada / total * 100, "%"))
        if pot is not None:
            res.append(_l("gpu", f"{p}/potencia", pot, "W"))
        if vent is not None:
            res.append(_l("gpu", f"{p}/ventilador_pct", vent, "%"))
    return res


def _discos() -> list[dict]:
    """E/S de los discos físicos (uso y MB/s en una ventana corta), espacio libre y particiones en solo lectura."""
    res = []
    antes, t0 = psutil.disk_io_counters(perdisk=True), time.monotonic()
    time.sleep(ESPERA_IO_S)
    despues, dt = psutil.disk_io_counters(perdisk=True), time.monotonic() - t0
    for dev, b in despues.items():
        a = antes.get(dev)
        if not a or not DISCO_FISICO.match(dev):
            continue
        busy = getattr(b, "busy_time", None)
        if busy is not None:
            res.append(_l("disco", f"{dev}/io_util_pct", min(100.0, (busy - a.busy_time) / (dt * 1000) * 100), "%"))
        res.append(_l("disco", f"{dev}/lectura_mbs", (b.read_bytes - a.read_bytes) / dt / 1e6, "MB/s"))
        res.append(_l("disco", f"{dev}/escritura_mbs", (b.write_bytes - a.write_bytes) / dt / 1e6, "MB/s"))
    for p in psutil.disk_partitions(all=False):
        if p.fstype not in FS_REALES or p.mountpoint == "/boot/efi" or p.mountpoint.startswith(("/snap", "/var/snap")):
            continue
        try:
            u = psutil.disk_usage(p.mountpoint)
        except OSError:
            continue
        res.append(_l("disco", f"fs:{p.mountpoint}/libre_pct", u.free / u.total * 100, "%"))
        res.append(_l("disco", f"fs:{p.mountpoint}/solo_lectura", 1 if "ro" in p.opts.split(",") else 0, "bool"))
    return res


def parsear_smart(dev: str, texto: str) -> list[dict]:
    """Interpreta la salida JSON de `smartctl -j -H -A` (discos ATA/SATA y NVMe)."""
    try:
        d = json.loads(texto)
    except ValueError:
        return []
    if not isinstance(d, dict):  # JSON válido pero que no es un informe (por ejemplo `null` o una lista)
        return []
    res = []
    ok = (d.get("smart_status") or {}).get("passed")
    if ok is not None:
        res.append(_l("disco", f"{dev}/smart_ok", 1 if ok else 0, "bool"))
    horas = (d.get("power_on_time") or {}).get("hours")
    if horas is not None:
        res.append(_l("disco", f"{dev}/horas_encendido", horas, "h"))
    nv = d.get("nvme_smart_health_information_log") or {}
    for clave, nombre, unidad in (("critical_warning", "alerta_critica", "n"), ("percentage_used", "desgaste_pct", "%"),
                                  ("available_spare", "spare_pct", "%"), ("media_errors", "errores_medio", "n")):
        if clave in nv:
            res.append(_l("disco", f"{dev}/{nombre}", nv[clave], unidad))
    tabla = {a.get("id"): a for a in (d.get("ata_smart_attributes") or {}).get("table") or []}
    for id_, nombre in ((5, "sectores_realocados"), (197, "sectores_pendientes"), (198, "sectores_incorregibles"), (199, "errores_crc")):
        raw = (tabla.get(id_) or {}).get("raw", {}).get("value")
        if raw is not None:
            res.append(_l("disco", f"{dev}/{nombre}", raw, "n"))
    for id_ in (231, 233, 177):  # vida restante normalizada de los SSD SATA (100 = nuevo)
        vida = (tabla.get(id_) or {}).get("value")
        if vida is not None:
            res.append(_l("disco", f"{dev}/desgaste_pct", 100 - vida, "%"))
            break
    return res


def _smart() -> list[dict]:
    """SMART de los discos físicos. Requiere smartmontools y el permiso de habilitar-sensores.sh; si no, se omite."""
    exe = "/usr/sbin/smartctl"
    if not Path(exe).exists():
        return []
    res = []
    for blk in sorted(p.name for p in Path("/sys/block").iterdir() if DISCO_FISICO.match(p.name)):
        dev = "/dev/" + (re.match(r"nvme\d+", blk).group(0) if blk.startswith("nvme") else blk)
        try:
            r = subprocess.run(["sudo", "-n", exe, "-j", "-H", "-A", dev], capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired) as e:
            log.warning("SMART de %s falló: %s", dev, e)
            continue
        if not r.stdout.lstrip().startswith("{"):  # sin permiso (sudo pide contraseña) o sin datos
            log.info("SMART de %s no disponible (¿falta ejecutar habilitar-sensores.sh?)", dev)
            continue
        res += parsear_smart(blk, r.stdout)  # smartctl devuelve códigos distintos de 0 por avisos: no es un error
    return res


def _sistema(fila=None) -> list[dict]:
    """CPU, RAM, swap y carga. Con `fila` (última métrica guardada) no vuelve a medir."""
    if fila is not None:
        cpu, ram, swap, carga = fila["cpu_pct"], fila["ram_pct"], fila["swap_pct"], fila["load_1m"]
    else:
        cpu, ram, swap, carga = (psutil.cpu_percent(interval=0.5), psutil.virtual_memory().percent,
                                 psutil.swap_memory().percent, psutil.getloadavg()[0])
    res = []
    if cpu is not None:
        res.append(_l("cpu", "cpu/uso", cpu, "%"))
    if carga is not None:
        res.append(_l("cpu", "cpu/carga_por_hilo", carga / (psutil.cpu_count() or 1), "carga"))
    if ram is not None:
        res.append(_l("memoria", "memoria/ram_pct", ram, "%"))
    if swap is not None and psutil.swap_memory().total > 0:  # sin swap configurada no hay nada que medir
        res.append(_l("memoria", "memoria/swap_pct", swap, "%"))
    return res


def leer_lecturas(fila=None) -> list[dict]:
    """Todas las lecturas actuales del equipo. Cada fuente que falle se omite sin romper el resto."""
    res = []
    fuentes = [("hwmon", _hwmon), ("gpu_amd", _gpu_amd), ("discos", _discos), ("smart", _smart), ("sistema", lambda: _sistema(fila))]
    for nombre, fn in fuentes:
        try:
            res += fn()
        except Exception:
            log.exception("falló la lectura de %s", nombre)
    nv = ejecutar(["nvidia-smi", "--query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw,fan.speed",
                   "--format=csv,noheader,nounits"])
    return res + (parsear_nvidia(nv) if nv else [])


def guardar_lecturas(con, metrica_id: int, ts: int, lecturas: list[dict], contexto: str | None = None) -> None:
    """Guarda las lecturas asociadas a una métrica, etiquetadas con el contexto (reposo, carga o juego)."""
    con.executemany(
        "INSERT INTO lecturas (metrica_id, ts, categoria, nombre, valor, unidad, limite_crit, contexto) VALUES (?,?,?,?,?,?,?,?)",
        [(metrica_id, ts, l["categoria"], l["nombre"], l["valor"], l["unidad"], l["crit"], contexto) for l in lecturas])


# ---------- evaluación de reglas ----------

def _regla_de(l: dict):
    for r in REGLAS:
        if r["cat"] != l["categoria"]:
            continue
        if "unidad" in r and r["unidad"] != l["unidad"]:
            continue
        if "sufijo" in r and not l["nombre"].endswith(r["sufijo"]):
            continue
        return r
    return None


def _parametros(r: dict, l: dict, cfg: dict) -> dict:
    """Umbrales efectivos de una regla para una lectura, con los cambios de config.json aplicados."""
    p = {"aviso": r.get("aviso"), "critico": r.get("critico"), "muestras": r["muestras"], "margen": r["margen"]}
    if "rel" in r:
        da, dc, por_defecto = r["rel"]
        crit = l.get("crit") or por_defecto
        p["aviso"], p["critico"] = crit - da, crit - dc
    p.update({k: v for k, v in (cfg.get("umbrales") or {}).get(r["id"], {}).items() if k in p})
    return p


def _supera(v: float, umbral, minimo: bool, holgura: float) -> bool:
    if umbral is None:
        return False
    return v <= umbral + holgura if minimo else v >= umbral - holgura


def _serie(con, nombre: str, n: int, actual: float | None) -> list[float]:
    """Últimos `n` valores de un sensor (el más nuevo primero). Con `actual`, ese valor aún no está en la base."""
    filas = con.execute("SELECT valor FROM lecturas WHERE nombre=? ORDER BY ts DESC, metrica_id DESC LIMIT ?",
                        (nombre, n - 1 if actual is not None else n)).fetchall()
    return ([actual] if actual is not None else []) + [f["valor"] for f in filas]


def condiciones(con, lecturas: list[dict], cfg: dict, activas: set[str], en_base: bool) -> dict[str, dict]:
    """Devuelve {clave: condición} con todo lo que hoy está fuera de lo normal."""
    res = {}
    for l in lecturas:
        r = _regla_de(l)
        if not r:
            continue
        clave = f"{r['id']}:{l['nombre']}"
        p, minimo = _parametros(r, l, cfg), r.get("dir") == "min"
        holgura = p["margen"] if clave in activas else 0  # histéresis: una alerta activa se mantiene un poco más
        v = abs(l["valor"]) if r.get("abs") else l["valor"]
        severidad = None
        if _supera(v, p["critico"], minimo, holgura):
            severidad = "critico"
        elif p["aviso"] is not None:
            serie = _serie(con, l["nombre"], p["muestras"], None if en_base else l["valor"])
            serie = [abs(x) for x in serie] if r.get("abs") else serie
            if len(serie) >= p["muestras"] and all(_supera(x, p["aviso"], minimo, holgura) for x in serie):
                severidad = "aviso"
        if severidad:
            lim = p["critico"] if severidad == "critico" else p["aviso"]
            res[clave] = {"clave": clave, "categoria": l["categoria"], "nombre": l["nombre"], "severidad": severidad,
                          "valor": l["valor"], "mensaje": f"{r['texto']}: {l['nombre']} = {l['valor']:g} {l['unidad']} (límite {lim:g})"}
    # ventilador detenido con el chip caliente
    for l in lecturas:
        # un conector sin ventilador marca 0 siempre: solo cuenta si ese ventilador alguna vez giró
        if l["unidad"] == "RPM" and l["valor"] == 0 and (con.execute(
                "SELECT MAX(valor) m FROM lecturas WHERE nombre=?", (l["nombre"],)).fetchone()["m"] or 0) > 0:
            chip = l["nombre"].split("/")[0]
            temp = max((t["valor"] for t in lecturas if t["unidad"] == "°C" and t["nombre"].split("/")[0] == chip), default=None)
            if temp is not None and temp >= 75:
                clave = f"ventilador:{l['nombre']}"
                res[clave] = {"clave": clave, "categoria": l["categoria"], "nombre": l["nombre"],
                              "severidad": "critico" if temp >= 80 else "aviso", "valor": 0,
                              "mensaje": f"Ventilador detenido: {l['nombre']} a 0 RPM con el chip a {temp:g} °C"}
    return res


def condiciones_eventos(con, ahora: int) -> dict[str, dict]:
    """Eventos graves del journal de las últimas 24 h (uno por tipo, con el más reciente)."""
    res = {}
    filas = con.execute("SELECT ts, origen, mensaje FROM eventos WHERE ts >= ? ORDER BY ts DESC",
                        (ahora - VENTANA_EVENTOS_S,)).fetchall()
    for f in filas:
        for tipo, cat, sev, texto, rx in PATRONES_EVENTO:
            clave = f"evento:{tipo}"
            if clave not in res and rx.search(f"{f['origen']}: {f['mensaje']}"):
                res[clave] = {"clave": clave, "categoria": cat, "nombre": tipo, "severidad": sev, "valor": f["ts"],
                              "evento": True, "mensaje": f"{texto}: {f['mensaje'][:110]}"}
    return res


# ---------- estado de las alertas y avisos ----------

def aplicar_condiciones(con, conds: dict[str, dict], vistos: set[str], ahora: int) -> dict:
    """Actualiza `alertas_salud` y decide cuáles avisar: nuevas, que escalan a crítico o que persisten (con repetición)."""
    activas = {f["clave"]: f for f in con.execute("SELECT * FROM alertas_salud WHERE activa=1")}
    a_avisar, resueltas = [], []
    for clave, c in conds.items():
        f = activas.get(clave)
        if f is None:
            con.execute(
                "INSERT INTO alertas_salud (clave, categoria, nombre, severidad, mensaje, valor, desde, ultima_vez) "
                "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(clave) DO UPDATE SET categoria=excluded.categoria, "
                "severidad=excluded.severidad, mensaje=excluded.mensaje, valor=excluded.valor, desde=excluded.desde, "
                "ultima_vez=excluded.ultima_vez, ultima_notif=0, activa=1, resuelta_en=NULL, veces=veces+1",
                (clave, c["categoria"], c["nombre"], c["severidad"], c["mensaje"], c["valor"], ahora, ahora))
            a_avisar.append(c)
            continue
        escala = c["severidad"] == "critico" and f["severidad"] == "aviso"
        if c.get("evento"):
            toca = c["valor"] > f["ultima_notif"]  # hubo un evento nuevo desde el último aviso
        else:
            toca = ahora - f["ultima_notif"] >= c.get("repetir_s", REPETIR_S[c["severidad"]])
        con.execute("UPDATE alertas_salud SET severidad=?, mensaje=?, valor=?, ultima_vez=? WHERE clave=?",
                    (c["severidad"], c["mensaje"], c["valor"], ahora, clave))
        if escala or toca:
            a_avisar.append(c)
    for clave, f in activas.items():
        if clave not in conds and (clave.startswith("evento:") or f["nombre"] in vistos):
            con.execute("UPDATE alertas_salud SET activa=0, resuelta_en=? WHERE clave=?", (ahora, clave))
            resueltas.append(clave)
    return {"a_avisar": a_avisar, "resueltas": resueltas}


def _relacion(con, cond: dict, ahora: int) -> str | None:
    """Cambio de entorno claramente afín justo antes de que empezara la alerta; None si no hay o si falla (nunca bloquea el aviso)."""
    try:
        f = con.execute("SELECT desde FROM alertas_salud WHERE clave=?", (cond["clave"],)).fetchone()
        return correlacion.relacion_fuerte(con, cond.get("categoria"), f["desde"] if f else ahora)
    except Exception as e:  # el aviso es lo importante; la relación es un extra
        db.log.warning("correlación omitida: %s", e)
        return None


def enviar_aviso(con, a_avisar: list[dict], ahora: int, notificar=alertas.notificar) -> bool:
    """Envía un único aviso agrupado. Solo marca como avisadas las alertas si el envío funcionó."""
    if not a_avisar:
        return False
    orden = sorted(a_avisar, key=lambda c: c["severidad"] != "critico")
    critica = orden[0]["severidad"] == "critico"
    titulo = f"pc-doctor: {len(orden)} valor(es) fuera de lo normal"
    lineas = []
    for c in orden[:MAX_EN_AVISO]:
        lineas.append(f"• {'[CRÍTICO] ' if c['severidad'] == 'critico' else ''}{c['mensaje']}")
        relacion = _relacion(con, c, ahora)
        if relacion:
            lineas.append(f"   ↳ posible relación: {relacion}")
    if len(orden) > MAX_EN_AVISO:
        lineas.append(f"… y {len(orden) - MAX_EN_AVISO} más (alertas_salud)")
    # el botón "Ver en el dashboard" abre la alerta más grave del aviso (id de alertas_salud)
    f = con.execute("SELECT rowid FROM alertas_salud WHERE clave=?", (orden[0]["clave"],)).fetchone()
    if not notificar(titulo, "\n".join(lineas), critica=critica, seccion=f"alerta:{f['rowid']}" if f else "alertas"):
        return False
    con.executemany("UPDATE alertas_salud SET ultima_notif=? WHERE clave=?", [(ahora, c["clave"]) for c in orden])
    return True


def ciclo(con, notificar=alertas.notificar) -> dict:
    """Paso del recolector: lee y guarda sensores, evalúa las reglas y avisa de lo que esté fuera de lo normal."""
    cfg = cargar_config()
    ahora = db.ahora()
    fila = con.execute("SELECT id, cpu_pct, ram_pct, swap_pct, load_1m FROM metricas ORDER BY id DESC LIMIT 1").fetchone()
    if not fila:
        return {"error": "todavía no hay métricas"}
    lecturas = leer_lecturas(fila)
    contexto = linea_base.contexto_de(lecturas, actividad.juego_en_curso(con))
    guardar_lecturas(con, fila["id"], ahora, lecturas, contexto)
    aprendizaje = linea_base.mantener(con)
    activas = {f["clave"] for f in con.execute("SELECT clave FROM alertas_salud WHERE activa=1")}
    conds = condiciones(con, lecturas, cfg, activas, en_base=True)
    conds.update(condiciones_eventos(con, ahora))
    conds.update(linea_base.condiciones_anomalias(con, lecturas, contexto))
    conds.update(linea_base.condiciones_deriva(con))
    r = aplicar_condiciones(con, conds, {l["nombre"] for l in lecturas}, ahora)
    enviado = False
    if cfg.get("salud", True) and cfg.get("notificaciones", True):
        enviado = enviar_aviso(con, r["a_avisar"], ahora, notificar)
    return {"lecturas": len(lecturas), "fuera_de_lo_normal": len(conds), "a_avisar": len(r["a_avisar"]),
            "aviso_enviado": enviado, "resueltas": len(r["resueltas"]),
            "contexto": contexto, "aprendizaje": aprendizaje}

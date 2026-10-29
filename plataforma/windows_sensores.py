"""Sensores en Windows: interpreta la salida de CIM/WMI y de LibreHardwareMonitor y la deja con los mismos nombres, categorías y
unidades que las lecturas de Linux (`salud._l`), para que las reglas, la línea base y el dashboard funcionen igual.

Sin administrador, Windows entrega poco: uso de CPU, RAM y discos (psutil), uso de GPU (contadores del motor de GPU), estado
general de los discos y las zonas térmicas ACPI. Temperaturas, ventiladores y voltajes salen de LibreHardwareMonitor si está
abierto (su espacio WMI); si no, no se miden y se informa en `no_disponible()`. Nada se inventa.
"""

import re

from .comun import lectura, lista

# Una sola llamada a CIM con todo lo que se necesita. Se consulta CIM y no `Get-Counter`: los nombres de los contadores se traducen
# al idioma del sistema (en español "GPU Engine" o "PhysicalDisk" no existen), las clases CIM no. Las clases de rendimiento
# calculan tasas entre dos lecturas, por eso se leen una vez para "calentarlas", se espera un segundo y se leen de nuevo.
SCRIPT_SENSORES = r"""
$r=@{}
foreach($ns in 'root/LibreHardwareMonitor','root/OpenHardwareMonitor'){
  try{
    $s=@(Get-CimInstance -Namespace $ns -ClassName Sensor -ErrorAction Stop)
    if($s.Count){
      $r.lhm=@{espacio=$ns
        hardware=@(Get-CimInstance -Namespace $ns -ClassName Hardware -ErrorAction Stop | Select-Object Identifier,HardwareType,Name,Parent)
        sensores=@($s | Select-Object Identifier,Name,SensorType,Value,Parent)}
      break
    }
  }catch{}
}
$null=Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine -ErrorAction SilentlyContinue
$null=Get-CimInstance Win32_PerfFormattedData_PerfDisk_PhysicalDisk -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 1000
try{$r.motores_gpu=@(Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine -ErrorAction Stop | Select-Object Name,UtilizationPercentage)}catch{}
try{$r.disco_perf=@(Get-CimInstance Win32_PerfFormattedData_PerfDisk_PhysicalDisk -ErrorAction Stop | Where-Object Name -ne '_Total' | Select-Object Name,PercentDiskTime,DiskReadBytesPersec,DiskWriteBytesPersec)}catch{}
try{$r.zonas=@(Get-CimInstance Win32_PerfFormattedData_Counters_ThermalZoneInformation -ErrorAction Stop | Select-Object Name,Temperature)}catch{}
try{$r.discos=@(Get-CimInstance -Namespace root/Microsoft/Windows/Storage -ClassName MSFT_PhysicalDisk -ErrorAction Stop | Select-Object DeviceId,FriendlyName,HealthStatus,OperationalStatus)}catch{}
try{$r.fiabilidad=@(Get-PhysicalDisk -ErrorAction Stop | ForEach-Object{$c=$_|Get-StorageReliabilityCounter -ErrorAction Stop;[pscustomobject]@{DeviceId=$_.DeviceId;Temperature=$c.Temperature;Wear=$c.Wear;PowerOnHours=$c.PowerOnHours}})}catch{}
$r|ConvertTo-Json -Depth 5 -Compress
"""

CATEGORIA_DE = {"Cpu": "cpu", "GpuNvidia": "gpu", "GpuAmd": "gpu", "GpuIntel": "gpu", "Storage": "disco", "Memory": "memoria",
                "Motherboard": "placa", "SuperIO": "placa", "EmbeddedController": "placa", "Cooler": "placa", "Psu": "placa"}
CPU_RESUMEN = re.compile(r"package|tctl|tdie|core max|core average|ccd|tccd", re.I)
FS_REALES = {"ntfs", "refs", "fat32", "fat", "exfat"}
UMBRAL_TEMP = (-40, 150)   # fuera de esto la lectura es un sensor roto, no una temperatura
VID = re.compile(r"distance to tjmax", re.I)
GPU_ADAPTADOR = re.compile(r"luid_(0x[0-9a-f]+_0x[0-9a-f]+)", re.I)


def _chip(tipo_hw: str, nombre_hw: str, indices: dict) -> str:
    """Nombre del "chip" de un hardware de LibreHardwareMonitor, estable entre corridas: cpu0, gpu0, o el nombre del dispositivo."""
    if tipo_hw == "Cpu":
        return f"cpu{indices.setdefault(('cpu', nombre_hw), sum(1 for k in indices if k[0] == 'cpu'))}"
    if tipo_hw.startswith("Gpu"):
        return f"gpu{indices.setdefault(('gpu', nombre_hw), sum(1 for k in indices if k[0] == 'gpu'))}"
    return nombre_hw.replace("/", "-").strip() or tipo_hw


def lecturas_lhm(lhm: dict | None) -> tuple[list[dict], dict]:
    """Lecturas de LibreHardwareMonitor mapeadas al formato de Linux. Devuelve (lecturas, {'nvidia': bool, 'gpu_uso': bool, 'disco': bool})."""
    from salud import RIELES, TEMP_SIN_SENSOR  # import tardío: salud importa plataforma
    info = {"nvidia": False, "gpu_uso": False, "disco": False}
    if not lhm:
        return [], info
    hw = {h["Identifier"]: h for h in lista(lhm.get("hardware"))}
    indices: dict = {}
    res, vram = [], {}
    cpu_temps = []
    for s in lista(lhm.get("sensores")):
        h = hw.get(s.get("Parent"))
        valor = s.get("Value")
        if h is None or valor is None or h["HardwareType"] not in CATEGORIA_DE:
            continue
        tipo_hw, cat, tipo, nombre = h["HardwareType"], CATEGORIA_DE[h["HardwareType"]], s["SensorType"], s["Name"]
        chip = _chip(tipo_hw, h["Name"], indices)
        completo = f"{chip}/{nombre}"
        valor = float(valor)
        if tipo_hw == "GpuNvidia":
            info["nvidia"] = True
        if tipo == "Temperature":
            if not UMBRAL_TEMP[0] < valor < UMBRAL_TEMP[1] or VID.search(nombre) or TEMP_SIN_SENSOR.match(nombre):
                continue
            if tipo_hw == "Cpu":
                cpu_temps.append((nombre, lectura(cat, completo, valor, "°C")))
            else:
                res.append(lectura(cat, completo, valor, "°C"))
                info["disco"] |= cat == "disco"
        elif tipo == "Fan":
            res.append(lectura(cat, completo, valor, "RPM"))
        elif tipo == "Voltage" and tipo_hw != "Cpu":  # en la CPU son VID (lo que pide el procesador), no el voltaje real
            mv = valor * 1000
            res.append(lectura(cat, completo, mv, "mV"))
            if cat == "placa":  # solo los rieles con valor nominal conocido se evalúan por desviación
                nominal = next((n for rx, n in RIELES if rx.search(nombre)), None)
                if nominal:
                    res.append(lectura(cat, f"{completo}/desviacion_pct", (mv - nominal) / nominal * 100, "%"))
        elif tipo == "Power" and (tipo_hw.startswith("Gpu") or (tipo_hw == "Cpu" and "package" in nombre.lower())):
            res.append(lectura(cat, completo, valor, "W"))
        elif tipo == "Load" and tipo_hw.startswith("Gpu") and nombre == "GPU Core":
            res.append(lectura(cat, f"{chip}/uso", valor, "%"))
            info["gpu_uso"] = True
        elif tipo == "SmallData" and tipo_hw.startswith("Gpu") and nombre in ("GPU Memory Used", "GPU Memory Total"):
            vram.setdefault(chip, {})[nombre] = valor
        elif tipo == "Level" and tipo_hw == "Storage":
            if nombre == "Remaining Life":
                res.append(lectura(cat, f"{chip}/desgaste_pct", 100 - valor, "%"))
            elif nombre == "Percentage Used":
                res.append(lectura(cat, f"{chip}/desgaste_pct", valor, "%"))
            elif nombre == "Available Spare":
                res.append(lectura(cat, f"{chip}/spare_pct", valor, "%"))
    # CPU: con un resumen (Package, Tctl, núcleo más caliente...) no hace falta cada núcleo
    resumen = [l for n, l in cpu_temps if CPU_RESUMEN.search(n)]
    res += resumen or [l for _, l in cpu_temps]
    for chip, v in vram.items():
        if v.get("GPU Memory Total"):
            res.append(lectura("gpu", f"{chip}/vram_pct", v.get("GPU Memory Used", 0) / v["GPU Memory Total"] * 100, "%"))
    return res, info


def uso_gpu_por_adaptador(motores: list[dict]) -> dict[str, float]:
    """Uso de cada GPU (como lo muestra el Administrador de tareas): por tipo de motor se suman los procesos y se toma el más
    ocupado. {luid del adaptador: %}."""
    por_adaptador: dict[str, dict[str, float]] = {}
    for m in motores:
        a = GPU_ADAPTADOR.search(m.get("Name") or "")
        t = re.search(r"engtype_(\w+)", m.get("Name") or "")
        if a and t:
            d = por_adaptador.setdefault(a.group(1), {})
            d[t.group(1)] = d.get(t.group(1), 0.0) + float(m.get("UtilizationPercentage") or 0)
    return {luid: min(100.0, max(d.values())) for luid, d in por_adaptador.items()}


def uso_gpu_por_proceso(motores: list[dict]) -> dict[int, float]:
    """Uso de GPU de cada proceso: por tipo de motor se suman sus instancias y se toma el más ocupado. {pid: %}."""
    por_pid: dict[int, dict[str, float]] = {}
    for m in motores:
        p = re.search(r"pid_(\d+)_", m.get("Name") or "")
        t = re.search(r"engtype_(\w+)", m.get("Name") or "")
        if p and t:
            d = por_pid.setdefault(int(p.group(1)), {})
            d[t.group(1)] = d.get(t.group(1), 0.0) + float(m.get("UtilizationPercentage") or 0)
    return {pid: min(100.0, max(d.values())) for pid, d in por_pid.items()}


def lecturas_discos(datos: dict, con_lhm_disco: bool) -> list[dict]:
    """E/S, estado general y (si Windows los da sin administrador) temperatura, desgaste y horas de cada disco físico."""
    res = []
    for d in lista(datos.get("disco_perf")):
        dev = "disk" + str(d.get("Name", "")).split(" ")[0]
        res.append(lectura("disco", f"{dev}/io_util_pct", min(100.0, float(d.get("PercentDiskTime") or 0)), "%"))
        res.append(lectura("disco", f"{dev}/lectura_mbs", float(d.get("DiskReadBytesPersec") or 0) / 1e6, "MB/s"))
        res.append(lectura("disco", f"{dev}/escritura_mbs", float(d.get("DiskWriteBytesPersec") or 0) / 1e6, "MB/s"))
    for d in lista(datos.get("discos")):
        salud = {0: 1, "Healthy": 1, 2: 0, "Unhealthy": 0}.get(d.get("HealthStatus"))  # Warning (1) no es ni lo uno ni lo otro: no se inventa
        if salud is not None:
            res.append(lectura("disco", f"disk{d.get('DeviceId')}/smart_ok", salud, "bool"))
    for d in lista(datos.get("fiabilidad")):
        dev = f"disk{d.get('DeviceId')}"
        t = d.get("Temperature")
        if not con_lhm_disco and isinstance(t, (int, float)) and UMBRAL_TEMP[0] < t < UMBRAL_TEMP[1] and t > 0:
            res.append(lectura("disco", f"{dev}/temp", t, "°C"))
        w = d.get("Wear")
        if not con_lhm_disco and isinstance(w, (int, float)) and 0 <= w <= 100:
            res.append(lectura("disco", f"{dev}/desgaste_pct", w, "%"))
        h = d.get("PowerOnHours")
        if isinstance(h, (int, float)) and h > 0:
            res.append(lectura("disco", f"{dev}/horas_encendido", h, "h"))
    return res


def lecturas_particiones(particiones: list[dict]) -> list[dict]:
    """Espacio libre y solo-lectura de cada unidad con letra (los CD/DVD y los discos sin sistema de archivos conocido, no)."""
    res = []
    for p in particiones:
        if p["fs"].lower() not in FS_REALES or "cdrom" in p["opciones"]:
            continue
        punto = p["punto"].rstrip("\\")
        res.append(lectura("disco", f"fs:{punto}/libre_pct", p["libre_pct"], "%"))
        res.append(lectura("disco", f"fs:{punto}/solo_lectura", 1 if "ro" in p["opciones"].split(",") else 0, "bool"))
    return res


def lecturas_zonas(zonas: list[dict]) -> list[dict]:
    """Zonas térmicas ACPI (Kelvin). No son la CPU: son sensores de la placa (a veces fijos); se guardan como placa."""
    res = []
    for z in zonas:
        try:
            c = float(z.get("Temperature")) - 273.15
        except (TypeError, ValueError):
            continue
        if 0 < c < UMBRAL_TEMP[1]:
            res.append(lectura("placa", "acpi/" + str(z.get("Name", "zona")).lstrip("\\").replace("/", "-"), c, "°C"))
    return res


def construir(datos: dict, particiones: list[dict], hay_nvidia_smi: bool) -> tuple[list[dict], dict]:
    """Todas las lecturas de sensores de Windows y un resumen de lo que hubo: {'lhm', 'lhm_nvidia', 'smart', 'gpu_uso'...}."""
    datos = datos or {}
    res, info = lecturas_lhm(datos.get("lhm"))
    tiene_lhm = bool(datos.get("lhm"))
    res += lecturas_discos(datos, info["disco"])
    res += lecturas_particiones(particiones)
    if not tiene_lhm:  # con LibreHardwareMonitor las zonas ACPI son redundantes
        res += lecturas_zonas(lista(datos.get("zonas")))
    # uso de GPU por contadores: solo si nadie más lo trajo (nvidia-smi y LibreHardwareMonitor lo hacen mejor y se duplicaría la alerta)
    if not info["gpu_uso"] and not hay_nvidia_smi:
        for i, (_, uso) in enumerate(sorted(uso_gpu_por_adaptador(lista(datos.get("motores_gpu"))).items())):
            res.append(lectura("gpu", f"gpu{i}/uso", uso, "%"))
    meta = {"lhm": tiene_lhm, "lhm_nvidia": info["nvidia"], "gpu_uso": info["gpu_uso"] or hay_nvidia_smi or bool(datos.get("motores_gpu")),
            "smart": any(l["nombre"].endswith("/smart_ok") for l in res)}
    return res, meta


def temperatura_cpu(lecturas: list[dict]) -> float | None:
    """Temperatura de la CPU a partir de las lecturas (la del paquete/Tctl si hay; si no, la más alta); None si no hay sensor."""
    cpu = [l for l in lecturas if l["categoria"] == "cpu" and l["unidad"] == "°C"]
    if not cpu:
        return None
    preferidas = [l for l in cpu if re.search(r"package|tctl|tdie", l["nombre"], re.I)]
    return float(max(l["valor"] for l in (preferidas or cpu)))


def no_disponible(lecturas: list[dict], meta: dict) -> list[str]:
    """Qué no se puede medir ahora en este equipo y qué falta para poder hacerlo."""
    res = []
    if not meta.get("lhm"):
        res.append("Temperaturas de CPU, GPU, discos y placa, ventiladores y voltajes: Windows no los expone sin un programa de sensores "
                   "(abrí LibreHardwareMonitor; lo configura habilitar-sensores.ps1)")
    if not any(l["categoria"] == "disco" and l["nombre"].endswith("/smart_ok") for l in lecturas):
        res.append("Estado de los discos: Windows no lo entregó (¿falta el módulo Storage de PowerShell?)")
    elif not any(l["nombre"].endswith(("/sectores_realocados", "/errores_crc", "/errores_medio")) for l in lecturas):
        res.append("SMART detallado (sectores realocados, errores CRC): sin administrador solo se lee el estado general del disco "
                   "(habilitar-sensores.ps1 -ConSmartctl agrega los contadores crudos)")
    if not any(l["categoria"] == "gpu" and l["nombre"].endswith("/uso") for l in lecturas):
        res.append("Uso de la GPU: no hay contadores del motor de GPU en este equipo")
    if not any(l["categoria"] == "gpu" and l["nombre"].endswith("/vram_pct") for l in lecturas):
        res.append("VRAM de la GPU: hace falta LibreHardwareMonitor o nvidia-smi (WMI no informa la memoria total real)")
    return res

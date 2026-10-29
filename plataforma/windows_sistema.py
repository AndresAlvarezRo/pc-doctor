"""Hardware, sistema operativo, programas instalados y eventos de Windows: los scripts de PowerShell que los leen y las funciones
puras que interpretan su salida (se prueban en Linux con salidas simuladas)."""

import platform
import re

from .comun import PROVEEDORES_PCI, lista

# Una sola llamada a CIM por corrida. Las fechas se formatean acá para no depender de cómo ConvertTo-Json serializa los DateTime.
SCRIPT_HARDWARE = r"""
$r=@{}
function Q($c,$p,$ns){ try{ if($ns){@(Get-CimInstance -Namespace $ns -ClassName $c -ErrorAction Stop | Select-Object $p)}else{@(Get-CimInstance -ClassName $c -ErrorAction Stop | Select-Object $p)} }catch{@()} }
$r.cpu=Q Win32_Processor Name,Manufacturer,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed
$r.gpu=@(Q Win32_VideoController Name,PNPDeviceID,DriverVersion,AdapterCompatibility,@{n='DriverDate';e={if($_.DriverDate){$_.DriverDate.ToString('yyyy-MM-dd')}}})
$r.ram=Q Win32_PhysicalMemory Manufacturer,Capacity,ConfiguredClockSpeed,Speed
$r.discos=Q Win32_DiskDrive Model,Size,Index,MediaType,InterfaceType
$r.discos_fisicos=Q MSFT_PhysicalDisk DeviceId,MediaType,BusType root/Microsoft/Windows/Storage
$r.placa=Q Win32_BaseBoard Manufacturer,Product
$r.bios=Q Win32_BIOS SMBIOSBIOSVersion
$r.equipo=Q Win32_ComputerSystem Model
$r.so=Q Win32_OperatingSystem Caption,Version,BuildNumber,OSArchitecture
$r|ConvertTo-Json -Depth 4 -Compress
"""

MARCAS_CPU = {"GenuineIntel": "Intel", "AuthenticAMD": "AMD", "HygonGenuine": "Hygon"}
TIPO_MEDIO = {3: "HDD", 4: "SSD", 5: "SSD"}   # MSFT_PhysicalDisk.MediaType: 3 HDD, 4 SSD, 5 SCM
BUS_NVME = 17


def _primero(d: dict, clave: str) -> dict:
    return (lista(d.get(clave)) or [{}])[0] or {}


def nombre_so(d: dict, version_mostrada=None, ubr=None) -> str:
    """Ej.: 'Windows 11 Pro 23H2 (build 22631.4460)'."""
    so = _primero(d, "so")
    caption = re.sub(r"^Microsoft\s+", "", (so.get("Caption") or "").strip())
    if not caption:
        return ""
    build = str(so.get("BuildNumber") or "")
    if build and ubr is not None:
        build = f"{build}.{ubr}"
    return " ".join(p for p in (caption, str(version_mostrada or "")) if p) + (f" (build {build})" if build else "")


def version_so(d: dict) -> str:
    """Versión del núcleo de Windows (ej. '10.0.22631'): lo equivalente al kernel en el snapshot del entorno."""
    return str(_primero(d, "so").get("Version") or "")


def filas_hardware(d: dict, nucleos: int | None, hilos: int | None, ram_total: int, swap_total: int,
                   version_nvidia: str | None = None) -> list[tuple[str, str, str, dict]]:
    """Filas (tipo, marca, modelo, detalle) con el mismo formato que `collector.recolectar_hardware` en Linux."""
    filas = []
    c = _primero(d, "cpu")
    modelo = (c.get("Name") or "").strip()
    marca = MARCAS_CPU.get(c.get("Manufacturer") or "") or next((m for m in ("Intel", "AMD", "Qualcomm") if m.lower() in modelo.lower()),
                                                                (c.get("Manufacturer") or "").strip())
    filas.append(("cpu", marca, modelo, {"arquitectura": platform.machine(), "nucleos_fisicos": nucleos, "hilos": hilos,
                                         "mhz_max": c.get("MaxClockSpeed")}))
    for g in lista(d.get("gpu")):
        pnp = g.get("PNPDeviceID") or ""
        v = re.search(r"VEN_([0-9A-Fa-f]{4})", pnp)
        if not pnp.upper().startswith("PCI\\") or not v:  # adaptadores virtuales (Remote Display, Basic Display...) no son hardware
            continue
        vendor = v.group(1).lower()
        dev = re.search(r"DEV_([0-9A-Fa-f]{4})", pnp)
        proveedor = PROVEEDORES_PCI.get(vendor, f"desconocido ({vendor})")
        detalle = {"id_pci": f"{vendor}:{dev.group(1).lower()}" if dev else None, "driver": proveedor.lower(),
                   "version_driver": g.get("DriverVersion"), "fecha_driver": g.get("DriverDate")}
        if proveedor == "NVIDIA" and version_nvidia and version_nvidia.strip():  # nvidia-smi da la versión que conoce el usuario (ej. 551.23)
            detalle["version_driver"] = version_nvidia.strip().splitlines()[0]
        filas.append(("gpu", proveedor, (g.get("Name") or "").strip(), detalle))
    modulos = [{"fabricante": (m.get("Manufacturer") or "").strip(), "gb": round(int(m.get("Capacity") or 0) / 2**30, 1),
                "mhz": m.get("ConfiguredClockSpeed") or m.get("Speed")} for m in lista(d.get("ram"))]
    filas.append(("ram", "", "", {"total_gb": round(ram_total / 2**30, 1), "swap_gb": round(swap_total / 2**30, 1), "modulos": modulos}))
    fisicos = {str(p.get("DeviceId")): p for p in lista(d.get("discos_fisicos"))}
    for dk in lista(d.get("discos")):
        if "removable" in (dk.get("MediaType") or "").lower():
            continue
        modelo_d = (dk.get("Model") or "").strip()
        p = fisicos.get(str(dk.get("Index")), {})
        tipo = TIPO_MEDIO.get(p.get("MediaType"), "desconocido")
        detalle = {"dev": f"disk{dk.get('Index')}", "tamano": f"{int(dk.get('Size') or 0) / 2**30:.1f}G", "tipo": tipo}
        if p.get("BusType") == BUS_NVME:
            detalle["bus"] = "NVMe"
        filas.append(("disco", modelo_d.split(" ")[0] if modelo_d else "", modelo_d, detalle))
    pl = _primero(d, "placa")
    filas.append(("mother", (pl.get("Manufacturer") or "").strip(), (pl.get("Product") or "").strip(),
                  {"bios": (_primero(d, "bios").get("SMBIOSBIOSVersion") or "").strip(),
                   "producto": (_primero(d, "equipo").get("Model") or "").strip()}))
    return filas


# ---------- programas instalados ----------

ACTUALIZACION = re.compile(r"^(KB\d+|(Update|Security Update|Hotfix|Service Pack) for\b)", re.I)


def paquetes_registro(entradas: list[dict]) -> list[tuple[str, str, str]]:
    """Programas de las claves Uninstall, sin componentes del sistema, parches ni duplicados (el mismo en 32 y 64 bits)."""
    vistos, res = set(), []
    for e in entradas:
        nombre = (e.get("DisplayName") or "").strip()
        if not nombre or e.get("SystemComponent") == 1 or e.get("ParentKeyName") or ACTUALIZACION.match(nombre) \
                or (e.get("ReleaseType") or "") in ("Update", "Hotfix", "Security Update", "Service Pack"):
            continue
        clave = (nombre, str(e.get("DisplayVersion") or ""))
        if clave not in vistos:
            vistos.add(clave)
            res.append((clave[0], clave[1], "registro"))
    return sorted(res)


def tabla_winget(salida: str | None) -> list[dict]:
    """Filas de una tabla de winget como {'Name','Id','Version','Available','Source'} (los títulos en español se traducen). Las columnas se
    ubican por la posición de sus títulos; sin tabla reconocible, vacío."""
    if not salida:
        return []
    lineas = [re.sub(r"[\x08\r]", "", l).rstrip() for l in salida.splitlines()]
    for i, l in enumerate(lineas):
        if re.match(r"^-{5,}\s*$", l) and i > 0:
            cab = lineas[i - 1]
            break
    else:
        return []
    titulos = {"Name": "Name", "Nombre": "Name", "Id": "Id", "Version": "Version", "Versión": "Version", "Available": "Available",
               "Disponible": "Available", "Source": "Source", "Origen": "Source", "Fuente": "Source"}
    cols = sorted({titulos[t]: cab.find(t) for t in titulos if re.search(rf"(?<!\S){t}(?!\S)", cab)}.items(), key=lambda c: c[1])
    if len(cols) < 3 or "Id" not in dict(cols):
        return []
    inicios = [p for _, p in cols] + [None]
    campos = {n: (inicios[k], inicios[k + 1]) for k, (n, _) in enumerate(cols)}
    res = []
    for l in lineas[lineas.index(cab) + 2:]:
        if l.strip():
            res.append({n: l[a:b].strip() for n, (a, b) in campos.items()})
    return [r for r in res if r.get("Id")]


def paquetes_winget(salida: str | None) -> list[tuple[str, str, str]]:
    """Filas de `winget list` que tienen fuente (winget o msstore): complementan al registro con el Id estable y las apps de la Tienda.
    Las que no tienen fuente ya están en el registro."""
    return sorted({(f["Id"], f.get("Version", ""), "winget") for f in tabla_winget(salida) if f.get("Source")})


# ---------- eventos ----------

# Registros muy ruidosos y documentados como inofensivos: no desplazan a los importantes dentro del tope de eventos
RUIDO = {("Microsoft-Windows-DistributedCOM", 10016)}
SEVERIDAD = {1: "crit", 2: "err", 3: "warn"}


def script_eventos(desde: int, maximo: int) -> str:
    """Eventos críticos, de error y de advertencia del log System desde el epoch `desde` (el más nuevo primero, a lo sumo `maximo`)."""
    return rf"""
$ini=[DateTimeOffset]::FromUnixTimeSeconds({int(desde)}).LocalDateTime
try{{
  $e=@(Get-WinEvent -FilterHashtable @{{LogName='System';Level=1,2,3;StartTime=$ini}} -MaxEvents {int(maximo)} -ErrorAction Stop | ForEach-Object{{
    $m=if($_.Message){{($_.Message -split "\r?\n")[0]}}else{{''}}
    [pscustomobject]@{{ts=[DateTimeOffset]::new($_.TimeCreated.ToUniversalTime()).ToUnixTimeSeconds();proveedor=$_.ProviderName;id=$_.Id;nivel=$_.Level;mensaje=$m}}}})
  ConvertTo-Json -InputObject $e -Compress
}}catch{{ if($_.FullyQualifiedErrorId -like 'NoMatchingEventsFound*'){{'[]'}}else{{throw}} }}
"""


def interpretar_eventos(datos, maximo: int) -> list[tuple[int, str, str, str]]:
    """(ts, origen, severidad, mensaje) del más viejo al más nuevo. El mensaje lleva el id del evento, que es lo que identifica
    el problema: '[41 crit] ...'."""
    filas = []
    for e in lista(datos):
        try:
            ts, prov, id_, nivel = int(e["ts"]), str(e.get("proveedor") or "?"), int(e["id"]), int(e["nivel"])
        except (KeyError, TypeError, ValueError):
            continue
        if (prov, id_) in RUIDO:
            continue
        sev = SEVERIDAD.get(nivel, "err")
        filas.append((ts, prov, sev, f"[{id_} {sev}] {(e.get('mensaje') or '').strip()}"[:500]))
    filas.sort(key=lambda f: f[0])
    return filas[-maximo:] if maximo else filas


# Patrones sobre "<proveedor>: [<id> <nivel>] <texto>" con las mismas categorías que los del journal de Linux (salud.PATRONES_EVENTO)
PATRONES_EVENTO = [
    ("disco_io", "disco", "critico", "Error de E/S o del sistema de archivos",
     r"^(?!disk: \[157 )(disk|Ntfs|Microsoft-Windows-Ntfs|ReFS|volmgr|volsnap|stornvme|storahci|partmgr|iaStor\w*|nvme)\b"),
    ("gpu_fallo", "gpu", "critico", "Fallo de la GPU",
     r"^(nvlddmkm|amdkmdag|amdwddmg|atikmdag|igfx\w*|dxgkrnl)\b|^Display: \[4101 "),
    ("memoria", "memoria", "critico", "Memoria agotada",
     r"^(Microsoft-Windows-)?Resource-Exhaustion-Detector\b"),
    ("hardware", "placa", "critico", "Error de hardware (WHEA)",
     r"^(Microsoft-Windows-)?WHEA-Logger\b"),
    ("termico", "cpu", "aviso", "Limitación térmica o de firmware",
     r"^(Microsoft-Windows-)?Kernel-Processor-Power: \[37 "),
    ("apagado_inesperado", "placa", "critico", "Apagado inesperado (energía o cuelgue)",
     r"^(Microsoft-Windows-)?Kernel-Power: \[41 "),
]
PATRONES_EVENTO = [(i, c, s, t, re.compile(p)) for i, c, s, t, p in PATRONES_EVENTO]


# ---------- limitaciones de este sistema ----------

LIMITACIONES = [
    {"tema": "Rootkits y procesos de otros usuarios", "que": "No se detectan",
     "por_que": "El escaneo de seguridad corre sin permisos de administrador. No es un antivirus: un resultado limpio no garantiza un equipo limpio."},
    {"tema": "Keyloggers por ganchos de teclado", "que": "No se pueden detectar",
     "por_que": "Windows no permite listar los ganchos de teclado (SetWindowsHookEx) sin un driver. Solo se detectan por nombre conocido, por estar sin firma "
               "digital en una carpeta del usuario con arranque propio o conexiones salientes, o por conexiones sostenidas sin ventana."},
    {"tema": "Cifrado, Secure Boot y exclusiones de Defender", "que": "No se revisan",
     "por_que": "BitLocker, Secure Boot y las exclusiones de Defender solo se leen como administrador (ayudante opcional). Las suscripciones WMI "
               "de arranque también pueden pedirlo: si no se pueden leer, no se informan."},
    {"tema": "SMBv1 y fin de soporte de Windows", "que": "SMBv1 solo se detecta si está activado de forma explícita; el fin de soporte usa una tabla propia",
     "por_que": "Sin administrador no se puede preguntar por la característica de Windows. La tabla de fechas es de las ediciones Home y Pro y hay que actualizarla a mano."},
    {"tema": "Catálogo KEV de CISA", "que": "Opcional (\"kev\": true en config.json) y solo da coincidencias por nombre",
     "por_que": "No se compara la versión instalada, así que un programa que aparece es algo para revisar y no una prueba de que esté vulnerable."},
    {"tema": "Pools de minería", "que": "Se reconocen por los argumentos del proceso y por puertos y IP conocidas, no por el nombre del servidor",
     "por_que": "Resolver los nombres de las conexiones obligaría a consultar al DNS por cada destino del equipo."},
    {"tema": "Temperaturas, ventiladores y voltajes", "que": "Solo se miden con LibreHardwareMonitor abierto",
     "por_que": "Windows no expone los sensores de la placa, la CPU ni los discos sin un programa con driver propio. Sin él no se inventa ningún valor."},
    {"tema": "SMART de los discos", "que": "Sin administrador solo se lee el estado general (sano o con problemas)",
     "por_que": "Los sectores realocados, pendientes y los errores CRC necesitan smartctl con privilegios (ayudante opcional)."},
    {"tema": "Carga del sistema", "que": "La regla de carga no aplica",
     "por_que": "Windows no tiene carga promedio. No se estima una a partir de otra cosa."},
    {"tema": "Eventos del sistema", "que": "Solo el registro System, de críticos, errores y advertencias",
     "por_que": "Es donde Windows anota los fallos de disco, GPU, memoria y energía. Los registros de aplicaciones no se leen."},
    {"tema": "Uso y memoria de la GPU", "que": "El uso sale de los contadores del motor de GPU; la VRAM total, solo de LibreHardwareMonitor o nvidia-smi",
     "por_que": "WMI informa mal la memoria de las tarjetas de más de 4 GB."},
    {"tema": "Antigüedad de archivos en la cuarentena", "que": "Se mide solo con la fecha de modificación",
     "por_que": "En Windows la fecha de cambio de Linux (ctime) es la de creación: no sirve para saber si un archivo copiado hoy es viejo."},
    {"tema": "Resolución temporal", "que": "Una lectura cada 15 minutos",
     "por_que": "Es la frecuencia del recolector. Un pico o un juego abierto y cerrado entre dos corridas no se ven."},
    {"tema": "Hora del día y estación del año", "que": "La línea base no los distingue",
     "por_que": "El calor del verano puede mover los valores normales. La deriva lenta compara contra un mes y avisa como mucho una vez por semana."},
    {"tema": "Detección de juegos", "que": "Steam, Epic, GOG y Xbox por su carpeta de instalación; el resto, por pantalla completa con GPU alta",
     "por_que": "Un programa a pantalla completa que use mucha GPU y no sea un juego (editor de video) puede contar como juego."},
]

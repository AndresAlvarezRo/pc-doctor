"""Lecturas de seguridad de Windows (procesos, ventanas, firmas digitales, arranque, postura, DNS) y el orden en que se usan.

Las reglas que deciden qué es un hallazgo están en `windows_seguridad.py` (funciones puras). Acá solo se lee el sistema: las pruebas
reemplazan estas funciones. Todo corre sin administrador; lo que lo pide queda registrado como límite en `ayudante_pendiente`.
Privacidad: de esta PC no sale nada. Las firmas se verifican localmente y las listas públicas solo se descargan.
"""

import base64
import json
import logging
import os
import re
import time
import urllib.request
from datetime import date

import psutil

from . import windows_seguridad as ws
from .comun import lista

log = logging.getLogger("pc-doctor")

MAX_FIRMAS_POR_CORRIDA = 60       # cuántos ejecutables nuevos se verifican por corrida (el resto, en la siguiente)
VIDA_FIRMA_S = 30 * 86400
INTERVALO_RACHA_S = 10 * 60       # una corrida suma a una racha solo si pasaron 10 min desde la anterior (una revisión manual no la infla)
INTERVALO_POSTURA_S = 20 * 3600   # la postura se revisa una vez por día
URL_KEV = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
MAX_BYTES_KEV = 20_000_000

_cache: dict = {}   # por proceso: la persistencia se lee una vez por corrida

SCRIPT_PERSISTENCIA = r"""
$r=@{}
try{$r.tareas=@(Get-ScheduledTask -ErrorAction Stop | Where-Object{$_.TaskPath -notlike '\Microsoft\*'} | ForEach-Object{$a=@($_.Actions)[0];[pscustomobject]@{Ruta=$_.TaskPath;Nombre=$_.TaskName;Ejecuta=$a.Execute;Argumentos=$a.Arguments}})}catch{}
try{$r.servicios=@(Get-CimInstance Win32_Service -ErrorAction Stop | Where-Object{$_.StartMode -eq 'Auto'} | Select-Object Name,PathName)}catch{}
try{$sh=New-Object -ComObject WScript.Shell
$r.inicio=@(foreach($d in @([Environment]::GetFolderPath('Startup'),[Environment]::GetFolderPath('CommonStartup'))){if($d -and (Test-Path $d)){Get-ChildItem $d -File -ErrorAction SilentlyContinue | Where-Object{$_.Name -ne 'desktop.ini'} | ForEach-Object{$t=$null;$ar=$null;if($_.Extension -eq '.lnk'){$l=$sh.CreateShortcut($_.FullName);$t=$l.TargetPath;$ar=$l.Arguments};[pscustomobject]@{Nombre=$_.Name;Ruta=$_.FullName;Destino=$t;Argumentos=$ar}}}})}catch{}
try{$c=@(Get-CimInstance -Namespace root/subscription -ClassName CommandLineEventConsumer -ErrorAction Stop | Select-Object Name,CommandLineTemplate,ExecutablePath)
$c+=@(Get-CimInstance -Namespace root/subscription -ClassName ActiveScriptEventConsumer -ErrorAction Stop | Select-Object Name,ScriptFileName)
$r.wmi=@{consumidores=$c}}catch{$r.wmi_sin_acceso=$true}
$r|ConvertTo-Json -Depth 5 -Compress
"""

SCRIPT_POSTURA = r"""
$r=@{}
try{$m=Get-MpComputerStatus -ErrorAction Stop;$r.defender=@{rtp=[bool]$m.RealTimeProtectionEnabled;servicio=[bool]$m.AMServiceEnabled;firmas_dias=$m.AntivirusSignatureAge;rapido_dias=$m.QuickScanAge;modo=[string]$m.AMRunningMode}}catch{}
try{$r.amenazas=@(Get-MpThreatDetection -ErrorAction Stop | Where-Object{$_.InitialDetectionTime -gt (Get-Date).AddDays(-30)} | ForEach-Object{$t=Get-MpThreat -ThreatID $_.ThreatID -ErrorAction SilentlyContinue;[pscustomobject]@{ThreatID=$_.ThreatID;Nombre=$t.ThreatName;Recursos=($_.Resources -join ';');Accion=[bool]$_.ActionSuccess}})}catch{}
try{$r.firewall=@(Get-NetFirewallProfile -ErrorAction Stop | Select-Object Name,@{n='Enabled';e={[string]$_.Enabled}})}catch{}
try{$h=Get-HotFix -ErrorAction Stop | Where-Object{$_.InstalledOn} | Sort-Object InstalledOn -Descending | Select-Object -First 1;if($h){$r.hotfix_dias=[int]((Get-Date)-$h.InstalledOn).TotalDays}}catch{}
$r|ConvertTo-Json -Depth 4 -Compress
"""


def _ps(script: str, timeout: int = 60):
    from . import windows
    return windows._json_ps(script, timeout)


def _registro(raiz, ruta, nombre):
    from . import windows
    return windows._registro(raiz, ruta, nombre)


def _valores_registro(raiz, ruta) -> dict:
    from . import windows
    return windows._valores_registro(raiz, ruta)


# ---------- procesos, ventanas, conexiones ----------

def procesos() -> list[dict]:
    """Procesos en ejecución con su ejecutable (vacío si Windows no deja leerlo: los del sistema), línea de comandos y padre."""
    nombres, res = {}, []
    lista_p = list(psutil.process_iter(["pid", "ppid", "name", "exe", "cmdline"]))
    for p in lista_p:
        nombres[p.info["pid"]] = p.info["name"] or ""
    for p in lista_p:
        i = p.info
        res.append({"pid": i["pid"], "nombre": i["name"] or "?", "exe": i["exe"] or "", "cmd": " ".join(i["cmdline"] or []),
                    "ppid": i["ppid"], "padre": nombres.get(i["ppid"], "")})
    return res


def pids_propios() -> set[int]:
    """Este proceso, sus padres (uv, el programador de tareas) y sus hijos (los PowerShell de pc-doctor): no se revisan."""
    try:
        yo = psutil.Process()
        return {yo.pid} | {p.pid for p in yo.parents()} | {p.pid for p in yo.children(recursive=True)}
    except psutil.Error:
        return {os.getpid()}


def ventanas_visibles() -> set[int]:
    """Pids con una ventana visible y con título (user32, sin permisos especiales). Si no se puede leer, vacío."""
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        pids: set[int] = set()
        enum = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def cb(hwnd, _):
            if u.IsWindowVisible(hwnd) and u.GetWindowTextLengthW(hwnd) > 0:
                pid = wintypes.DWORD()
                u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                pids.add(pid.value)
            return True
        u.EnumWindows(enum(cb), 0)
        return pids
    except (AttributeError, OSError, ImportError):
        return set()


def salientes_por_pid() -> dict[int, int]:
    """Conexiones establecidas hacia IP públicas por proceso."""
    import ipaddress
    import seguridad
    res: dict[int, int] = {}
    for c in seguridad.conexiones()[1]:
        try:
            publica = ipaddress.ip_address(c["remoto"]).is_global
        except ValueError:
            continue
        if publica and c["pid"] is not None:
            res[c["pid"]] = res.get(c["pid"], 0) + 1
    return res


def uso_alto(procs: list[dict]) -> set[str]:
    """Nombres (sin .exe) de procesos con mucha CPU o GPU en este momento."""
    import db
    from . import windows, windows_sensores
    altos = set()
    ncpu = psutil.cpu_count() or 1
    for t in db.top_procesos(10):
        if t["cpu_pct"] / ncpu >= ws.CPU_ALTA_PCT:
            altos.add(ws.stem(t["nombre"]))
    por_pid = {p["pid"]: p for p in procs}
    for pid, pct in windows_sensores.uso_gpu_por_proceso(lista((windows._sensores_crudos() or {}).get("motores_gpu"))).items():
        if pct >= ws.GPU_ALTA_PCT and pid in por_pid:
            altos.add(ws.stem(por_pid[pid]["nombre"]))
    return altos


# ---------- firmas digitales con caché por hash ----------

def _ruta_cache():
    import db
    return db.DIR_DATOS / "firmas.cache.json"


def _leer_cache() -> dict:
    try:
        c = json.loads(_ruta_cache().read_text(encoding="utf-8"))
        return {"hashes": c.get("hashes", {}), "firmas": c.get("firmas", {})}
    except (OSError, ValueError):
        return {"hashes": {}, "firmas": {}}


def _guardar_cache(c: dict) -> None:
    ahora = time.time()
    c["firmas"] = {h: f for h, f in c["firmas"].items() if ahora - f.get("ts", 0) < VIDA_FIRMA_S}
    try:
        _ruta_cache().parent.mkdir(parents=True, exist_ok=True)
        _ruta_cache().write_text(json.dumps(c), encoding="utf-8")
    except OSError:
        pass


def _verificar_firmas(rutas: list[str]) -> dict[str, dict]:
    """{ruta: {estado, firmante}} de Get-AuthenticodeSignature para estos archivos (una sola llamada a PowerShell)."""
    datos = base64.b64encode(json.dumps(rutas).encode("utf-8")).decode("ascii")
    script = (r"$rutas=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + datos + r"'))|ConvertFrom-Json" "\n"
              r"$o=foreach($p in $rutas){try{$s=Get-AuthenticodeSignature -LiteralPath $p -ErrorAction Stop;"
              r"[pscustomobject]@{Ruta=$p;Estado=[string]$s.Status;Firmante=$(if($s.SignerCertificate){$s.SignerCertificate.Subject}else{''})}}"
              r"catch{[pscustomobject]@{Ruta=$p;Estado='Error';Firmante=''}}}" "\n"
              r"ConvertTo-Json -InputObject @($o) -Compress")
    return {ws.norm(f["Ruta"]): {"estado": f["Estado"], "firmante": f["Firmante"]} for f in lista(_ps(script, 120))}


def firmas_de(rutas) -> dict[str, dict]:
    """{ruta normalizada: {estado, firmante}} de los ejecutables dados. Cada archivo se identifica por su hash SHA-256 (calculado acá, solo
    se vuelve a calcular si cambia su tamaño o fecha) y la firma de cada hash se verifica una sola vez por mes."""
    import reputacion
    cache, res, pendientes = _leer_cache(), {}, {}
    unicas = {ws.norm(r): r for r in rutas if r and os.path.isfile(r)}
    for n, r in unicas.items():
        try:
            st = os.stat(r)
        except OSError:
            continue
        ident = f"{n}|{st.st_size}|{int(st.st_mtime)}"
        h = cache["hashes"].get(ident)
        if h is None:
            hs = reputacion.hashes_de(r)
            if not hs:
                continue
            h = cache["hashes"][ident] = hs[0]
        f = cache["firmas"].get(h)
        if f and time.time() - f.get("ts", 0) < VIDA_FIRMA_S:
            res[n] = {"estado": f["estado"], "firmante": f["firmante"]}
        else:
            pendientes[n] = (r, h)
    if pendientes:
        lote = dict(list(pendientes.items())[:MAX_FIRMAS_POR_CORRIDA])
        for n, f in _verificar_firmas([r for r, _ in lote.values()]).items():
            if n in lote and f["estado"] != "Error":
                cache["firmas"][lote[n][1]] = {**f, "ts": time.time()}
                res[n] = f
        _guardar_cache(cache)
    elif cache["hashes"]:
        _guardar_cache(cache)
    return res


def config_minero_junto_a(rutas) -> set[str]:
    """Rutas (normalizadas) de ejecutables con un archivo de configuración de minero en su carpeta."""
    res = set()
    for r in rutas:
        carpeta = os.path.dirname(r)
        for nombre in ws.ARCHIVOS_CONFIG_MINERO:
            try:
                with open(os.path.join(carpeta, nombre), "r", encoding="utf-8", errors="replace") as f:
                    if ws.CONFIG_MINERO.search(f.read(65536)):
                        res.add(ws.norm(r))
                        break
            except OSError:
                continue
    return res


# ---------- estado en la base (se crea solo en Windows) ----------

def asegurar_tablas(con) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS seguridad_estado (clave TEXT PRIMARY KEY, valor INTEGER NOT NULL, actualizado INTEGER NOT NULL)")
    con.execute("CREATE TABLE IF NOT EXISTS persistencia (clave TEXT PRIMARY KEY, tipo TEXT NOT NULL, nombre TEXT, comando TEXT, "
                "ruta_exe TEXT, primera_vez INTEGER NOT NULL, ultima_vez INTEGER NOT NULL)")


def rachas(con) -> dict[str, int]:
    asegurar_tablas(con)
    return {f["clave"][len("racha:"):]: f["valor"] for f in con.execute("SELECT clave, valor FROM seguridad_estado WHERE clave LIKE 'racha:%'")}


def actualizar_rachas(con, activas: set[str], ahora: int) -> None:
    """Suma una corrida a cada racha activa (si pasaron al menos 10 min desde la última suma) y borra las que se cortaron."""
    asegurar_tablas(con)
    previas = {f["clave"]: (f["valor"], f["actualizado"]) for f in con.execute("SELECT clave, valor, actualizado FROM seguridad_estado WHERE clave LIKE 'racha:%'")}
    for k in activas:
        clave = f"racha:{k}"
        valor, cuando = previas.get(clave, (0, 0))
        if ahora - cuando >= INTERVALO_RACHA_S:
            con.execute("INSERT INTO seguridad_estado (clave, valor, actualizado) VALUES (?,?,?) ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor, "
                        "actualizado=excluded.actualizado", (clave, valor + 1, ahora))
    for clave in set(previas) - {f"racha:{k}" for k in activas}:
        con.execute("DELETE FROM seguridad_estado WHERE clave=?", (clave,))


# ---------- escaneo de procesos ----------

def escanear_procesos(con=None) -> tuple[list[dict], dict]:
    """Hallazgos de los procesos (minería, suplantación, espías) y estadísticas, igual que en Linux. Con `con`, también las rachas de uso
    alto y de conexiones salientes (hace falta recordar corridas anteriores)."""
    import actividad
    import seguridad
    from . import windows
    procs = procesos()
    por_pid = {p["pid"]: p for p in procs}
    windir = os.environ.get("SystemRoot") or "C:\\Windows"
    ventanas, salientes, altos = ventanas_visibles(), salientes_por_pid(), uso_alto(procs)
    persistentes = {ws.norm(i["exe"]) for i in persistencia_items() if i["exe"]}
    candidatos = {p["exe"] for p in procs if p["exe"] and not ws.bajo(p["exe"], windir) and (
        ws.en_ruta_de_usuario(p["exe"]) or ws.stem(p["nombre"]) in altos or (p["pid"] in salientes and p["pid"] not in ventanas)
        or ws.norm(p["exe"]) in persistentes)}
    firmas = firmas_de(candidatos)
    sin_firma_ok = {ws.norm(e) for e in candidatos if ws.firma_mala(firmas.get(ws.norm(e))) or ws.en_ruta_de_usuario(e)}
    ctx = {"windir": windir, "pids_propios": pids_propios(), "nocoin": seguridad._leer_lista("nocoin_hosts"), "ventanas": ventanas,
           "firmas": firmas, "salientes": salientes, "persistentes": persistentes, "rachas": {},
           "config_minero": config_minero_junto_a([e for e in candidatos if ws.norm(e) in sin_firma_ok]),
           "juego": bool(con is not None and actividad.juego_en_curso(con))}
    if con is not None:
        ahora = int(time.time())
        activas = {f"uso:{n}" for n in altos if not any(p["pid"] in ventanas for p in procs if ws.stem(p["nombre"]) == n)}
        activas |= {f"con:{ws.norm(p['exe'])}" for p in procs if p["pid"] in salientes and p["pid"] not in ventanas and p["exe"]}
        actualizar_rachas(con, activas, ahora)
        ctx["rachas"] = rachas(con)
    hallazgos = ws.evaluar_procesos(procs, ctx)
    sin_acceso = sum(1 for p in procs if not p["exe"] and p["cmd"])
    return hallazgos, {"procesos": len(procs), "sin_acceso": sin_acceso}


def describir_procesos(pids) -> dict[int, str]:
    """{pid: 'firmado por X' / 'sin firma digital'...} para el detalle de los puertos en escucha."""
    exes = {}
    for pid in {p for p in pids if p}:
        try:
            exe = psutil.Process(pid).exe()
        except psutil.Error:
            continue
        if exe:
            exes[pid] = exe
    firmas = firmas_de(set(exes.values()))
    return {pid: ws.describir_firma(firmas.get(ws.norm(exe))) for pid, exe in exes.items()}


# ---------- arranque (persistencia) ----------

def persistencia_items() -> list[dict]:
    """Todo lo que arranca solo (se lee una vez por corrida)."""
    if "persistencia" in _cache and time.monotonic() - _cache["persistencia"][0] < 60:
        return _cache["persistencia"][1]
    entorno = dict(os.environ)
    run = []
    for raiz, hive in (("HKCU", "HKCU"), ("HKLM", "HKLM")):
        for clave, ruta in (("run", r"Software\Microsoft\Windows\CurrentVersion\Run"), ("runonce", r"Software\Microsoft\Windows\CurrentVersion\RunOnce")):
            for nombre, valor in _valores_registro(raiz, ruta).items():
                run.append({"hive": hive, "clave": clave, "nombre": nombre, "valor": str(valor)})
    for nombre, valor in _valores_registro("HKLM", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run").items():
        run.append({"hive": "HKLM32", "clave": "run", "nombre": nombre, "valor": str(valor)})
    ifeo_base = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options"
    ifeo = {}
    for sub in _registro("HKLM", ifeo_base, None) or []:
        dbg = _registro("HKLM", f"{ifeo_base}\\{sub}", "Debugger")
        if dbg:
            ifeo[sub] = str(dbg)
    appinit = [str(v) for v in (_registro("HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Windows", "AppInit_DLLs"),
                                _registro("HKLM", r"SOFTWARE\WOW6432Node\Microsoft\Windows NT\CurrentVersion\Windows", "AppInit_DLLs")) if v and str(v).strip()]
    base = _ps(SCRIPT_PERSISTENCIA, 90) or {}
    datos = {"run": run, "tareas": lista(base.get("tareas")), "servicios": lista(base.get("servicios")), "inicio": lista(base.get("inicio")),
             "wmi": {"consumidores": lista((base.get("wmi") or {}).get("consumidores"))},
             "winlogon": {"Shell": _registro("HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon", "Shell"),
                          "Userinit": _registro("HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon", "Userinit")},
             "ifeo": ifeo, "appinit": appinit}
    items = ws.items_persistencia(datos, entorno)
    _cache["persistencia"] = (time.monotonic(), items, bool(base.get("wmi_sin_acceso")))
    return items


def avisos_no_disponible() -> list[str]:
    """Lo que el escaneo de seguridad no pudo leer sin administrador en esta corrida (se suma a `no_disponible`)."""
    if "persistencia" in _cache and _cache["persistencia"][2]:
        return ["Suscripciones WMI de arranque (persistencia típica de mineros): Windows pidió administrador para leerlas (lo cubre el ayudante opcional)"]
    return []


def _windir() -> str:
    return os.environ.get("SystemRoot") or "C:\\Windows"


def escanear_extra(con=None) -> list[dict]:
    """Arranque (hallazgo cuando aparece algo nuevo) y, una vez por día, la postura de seguridad. Sin `con` no hay memoria de lo ya visto:
    solo se informa lo sospechoso por su contenido."""
    hallazgos = []
    items = persistencia_items()
    firmas = firmas_de({i["exe"] for i in items if i["exe"] and not ws.bajo(i["exe"], _windir())})
    if con is None:
        return ws.hallazgos_persistencia(items, firmas, set(), True, _windir())[0]
    asegurar_tablas(con)
    ahora = int(time.time())
    conocidos = {f["clave"] for f in con.execute("SELECT clave FROM persistencia")}
    h, nuevos = ws.hallazgos_persistencia(items, firmas, conocidos, not conocidos, _windir())
    hallazgos += h
    for i in nuevos:
        con.execute("INSERT OR IGNORE INTO persistencia (clave, tipo, nombre, comando, ruta_exe, primera_vez, ultima_vez) VALUES (?,?,?,?,?,?,?)",
                    (i["clave"], i["tipo"], i["nombre"], i["comando"], i["exe"], ahora, ahora))
    for i in items:
        con.execute("UPDATE persistencia SET ultima_vez=? WHERE clave=?", (ahora, i["clave"]))
    ultima = con.execute("SELECT valor FROM seguridad_estado WHERE clave='postura_ultima'").fetchone()
    if not ultima or ahora - ultima["valor"] >= INTERVALO_POSTURA_S:
        hallazgos += revisar_postura()
        con.execute("INSERT INTO seguridad_estado (clave, valor, actualizado) VALUES ('postura_ultima',?,?) ON CONFLICT(clave) DO UPDATE SET "
                    "valor=excluded.valor, actualizado=excluded.actualizado", (ahora, ahora))
    return hallazgos


# ---------- postura ----------

def datos_postura() -> dict:
    """Defender, firewall, parches y los ajustes del registro que se leen sin administrador."""
    d = _ps(SCRIPT_POSTURA, 90) or {}
    d["firewall"] = lista(d.get("firewall"))
    d["amenazas"] = lista(d.get("amenazas"))
    d["uac"] = _registro("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System", "EnableLUA")
    d["smb1"] = _registro("HKLM", r"SYSTEM\CurrentControlSet\Services\LanmanServer\Parameters", "SMB1")
    ts = r"SYSTEM\CurrentControlSet\Control\Terminal Server"
    d["rdp"] = {"activo": _registro("HKLM", ts, "fDenyTSConnections") == 0,
                "nla": _registro("HKLM", ts + r"\WinStations\RDP-Tcp", "UserAuthentication")}
    return d


def winget_upgrade() -> list[dict]:
    """Programas con versión nueva según `winget upgrade`. Solo lista: nunca actualiza nada."""
    import shutil
    import subprocess
    from . import windows_sistema
    if shutil.which("winget") is None:
        return []
    try:
        r = subprocess.run(["winget", "upgrade", "--accept-source-agreements", "--disable-interactivity"], capture_output=True, timeout=90,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("falló winget upgrade: %s", e)
        return []
    return [f for f in windows_sistema.tabla_winget(r.stdout.decode("utf-8", "replace")) if f.get("Available")]


def kev() -> dict | None:
    """Catálogo KEV de CISA (descarga pública, 1 vez por día). Solo se descarga: no se envía nada de esta PC."""
    import db
    ruta = db.DIR_DATOS / "listas" / "kev.json"
    try:
        if time.time() - ruta.stat().st_mtime < 86400:
            return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    try:
        with urllib.request.urlopen(urllib.request.Request(URL_KEV, headers={"User-Agent": "pc-doctor/0.1"}), timeout=15) as r:
            datos = r.read(MAX_BYTES_KEV + 1)
        if len(datos) > MAX_BYTES_KEV:
            raise ValueError("catálogo demasiado grande")
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(datos)
        return json.loads(datos)
    except Exception as e:  # red caída, formato nuevo, etc.: no rompe el recolector
        log.warning("no pude descargar el catálogo KEV: %s", e)
        return None


def revisar_postura() -> list[dict]:
    from . import windows
    so = (windows._datos_hardware().get("so") or [{}])
    so = (so[0] if isinstance(so, list) else so) or {}
    try:
        build = int(so.get("BuildNumber") or 0)
    except (TypeError, ValueError):
        build = 0
    hallazgos = ws.evaluar_postura(datos_postura(), date.today(), build or None, so.get("Caption") or "", winget_upgrade())
    from reputacion import cargar_config
    if cargar_config(crear=False).get("kev", False) is True:   # opcional y apagado por defecto
        hallazgos += ws.coincidencias_kev(kev() or {}, windows.paquetes())
    return hallazgos


# ---------- DNS (reputación de hashes sin `dig`) ----------

def consultar_txt(nombre: str, ps=None) -> tuple[str, list[str]] | None:
    """Registro TXT de `nombre` con Resolve-DnsName: (estado, textos) con estado NOERROR o NXDOMAIN; None si falló. Solo acepta el nombre
    de una consulta de hash de Team Cymru (40 hex + .hash.cymru.com)."""
    if not re.fullmatch(r"[0-9a-f]{40}\.hash\.cymru\.com", nombre):
        return None
    script = (f"try{{$r=Resolve-DnsName -Name '{nombre}' -Type TXT -DnsOnly -ErrorAction Stop;"
              "$t=@($r|Where-Object{$_.Type -eq 'TXT'}|ForEach-Object{$_.Strings -join ''});"
              "ConvertTo-Json -InputObject @{estado='NOERROR';txt=$t} -Compress}"
              "catch{if($_.FullyQualifiedErrorId -like '*RCODE_NAME_ERROR*'){'{\"estado\":\"NXDOMAIN\",\"txt\":[]}'}"
              "elseif($_.FullyQualifiedErrorId -like '*NO_RECORDS*'){'{\"estado\":\"NOERROR\",\"txt\":[]}'}"
              "else{'{\"estado\":\"ERROR\",\"txt\":[]}'}}")
    d = (ps or _ps)(script, 20)
    if not isinstance(d, dict) or d.get("estado") not in ("NOERROR", "NXDOMAIN"):
        return None
    return d["estado"], [str(t) for t in lista(d.get("txt"))]

"""Reglas de seguridad de Windows: funciones puras que reciben lo que se leyó del sistema (procesos, firmas, persistencia, postura) y
devuelven hallazgos con el mismo formato y las mismas huellas que `seguridad._h`. Lo que lee el sistema está en
`windows_lecturas_seguridad.py`. Todo corre sin administrador; no es un antivirus.

Las categorías son las de Linux más `persistencia`, `postura` y `vulnerabilidad`. La suplantación de procesos del sistema usa
`fantasma` (lo que en Linux son los procesos que se hacen pasar por otra cosa).
"""

import difflib
import ntpath
import re
from datetime import date

# ---------- firmas de minería ----------

NOMBRES_MINERO_WINDOWS = {"nicehash", "nicehashminer", "excavator", "ewbf", "claymore", "z-enemy", "wildrig", "miniz", "rigel",
                          "bzminer", "xmrig-cuda", "xmrig-notls", "multiminer", "easyminer", "awesomeminer", "gminer", "lolminer",
                          "t-rex", "phoenixminer", "nbminer", "teamredminer", "nanominer", "srbminer", "srbminer-multi", "kawpowminer"}
CMDLINE_MINERO_FUERTE = re.compile(r"stratum\+(?:tcp|ssl|tls)://|--donate-level|cryptonight|randomx|--algo[= ](?:rx|kawpow|ethash|etchash|cn)"
                                   r"|(?:^|\s)-o\s+[\w.-]+\.[a-z]{2,}:\d{3,5}\b", re.I)
CMDLINE_MINERO_DEBIL = re.compile(r"(?:^|\s)--(?:cuda|opencl)\b", re.I)
CONFIG_MINERO = re.compile(r"stratum\+(?:tcp|ssl|tls)://|\"pools?\"\s*:|\"donate-level\"|\"algo\"\s*:\s*\"(?:rx|randomx|kawpow|ethash|cn)", re.I)
ARCHIVOS_CONFIG_MINERO = ("config.json", "config.txt", "pools.txt", "start.bat", "start.cmd", "mine.bat", "run.bat")

# ---------- espías ----------

NOMBRES_KEYLOGGER_WINDOWS = {"ardamax", "refog", "spyrix", "actualspy", "perfectkeylogger", "elitekeylogger", "kidlogger", "revealer",
                             "hawkeye", "agenttesla", "njrat", "darkcomet", "quasar", "quasarrat", "asyncrat", "remcos", "nanocore",
                             "netwire", "warzone", "orcus", "xworm", "limerat", "blackshades", "logkeys", "pykeylogger", "keylogger"}

# ---------- suplantación ----------

# proceso del sistema -> carpetas donde vive de verdad (relativas a la carpeta de Windows) y quién debe ser su padre (None = no se controla)
SISTEMA = {"svchost": ("system32",), "lsass": ("system32",), "csrss": ("system32",), "winlogon": ("system32",), "services": ("system32",),
           "smss": ("system32",), "wininit": ("system32",), "explorer": ("",)}
PADRE_ESPERADO = {"svchost": "services", "lsass": "wininit", "services": "wininit"}
UNICOS = ("lsass", "services", "wininit")        # nunca hay dos
OFFICE = {"winword", "excel", "powerpnt", "outlook", "onenote", "msaccess", "visio", "mspub"}
NAVEGADORES = {"chrome", "msedge", "firefox", "brave", "opera", "iexplore"}
INTERPRETES = {"cmd", "powershell", "pwsh", "wscript", "cscript", "mshta", "bitsadmin", "certutil"}
POWERSHELL_OFUSCADO = re.compile(r"-e(?:nc|ncodedcommand)?\s+[A-Za-z0-9+/=]{20,}|-w(?:indowstyle)?\s+hidden|\bhidden\b.*-nop|-nop.*\bhidden\b", re.I)
POWERSHELL_DESCARGA = re.compile(r"downloadstring|downloadfile|invoke-webrequest|\biwr\b|\biex\b|invoke-expression|net\.webclient|"
                                 r"start-bitstransfer|frombase64string|-bxor", re.I)

RUTAS_USUARIO = ("\\appdata\\", "\\temp\\", "\\downloads\\", "\\descargas\\", "\\programdata\\", "\\users\\public\\", "\\$recycle.bin\\")
RACHA_USO = 4         # corridas seguidas (una cada 15 min) con uso alto y sin ventana
RACHA_SALIDA = 3      # corridas seguidas con conexión saliente sin ventana
CPU_ALTA_PCT = 35.0   # % del total de la CPU
GPU_ALTA_PCT = 60.0   # % de la GPU
PUERTOS_COMUNES = {80, 443, 53, 8080, 8443, 993, 995, 587, 465, 25, 143, 110, 22, 123, 5228, 853}

TRAMOS_SEVERIDAD = ("alta", "media", "baja")


# ---------- utilidades ----------

def stem(nombre: str) -> str:
    """Nombre de un ejecutable en minúsculas y sin .exe: 'XMRig.exe' -> 'xmrig'."""
    n = ntpath.basename((nombre or "").strip().replace("/", "\\")).lower()
    return n[:-4] if n.endswith(".exe") else n


def norm(ruta: str) -> str:
    """Ruta en minúsculas y con barras de Windows, para comparar."""
    return ntpath.normcase(ntpath.normpath(ruta)) if ruta else ""


def en_ruta_de_usuario(exe: str) -> bool:
    return any(r in norm(exe) + "\\" for r in RUTAS_USUARIO)


def bajo(exe: str, carpeta: str) -> bool:
    return bool(exe) and bool(carpeta) and norm(exe).startswith(norm(carpeta).rstrip("\\") + "\\")


def distancia(a: str, b: str) -> int:
    """Distancia de edición (Levenshtein) entre dos cadenas cortas."""
    previa = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        actual = [i]
        for j, cb in enumerate(b, 1):
            actual.append(min(previa[j] + 1, actual[j - 1] + 1, previa[j - 1] + (ca != cb)))
        previa = actual
    return previa[-1]


def firma_mala(firma: dict | None) -> bool:
    """True si se verificó la firma y no es válida (sin firma, alterada o no confiable). Sin dato no es mala: no se inventa."""
    return bool(firma) and firma.get("estado") in ("NotSigned", "HashMismatch", "NotTrusted")


def firma_microsoft(firma: dict | None) -> bool:
    return bool(firma) and firma.get("estado") == "Valid" and "microsoft" in (firma.get("firmante") or "").lower()


def describir_firma(firma: dict | None) -> str:
    if not firma:
        return "firma sin verificar"
    if firma.get("estado") == "Valid":
        m = re.search(r"CN=([^,]+)", firma.get("firmante") or "")
        return f"firmado por {m.group(1).strip(chr(34)) if m else 'un firmante válido'}"
    return {"NotSigned": "sin firma digital", "HashMismatch": "firma alterada", "NotTrusted": "firma no confiable"}.get(firma.get("estado"), "firma sin verificar")


def expandir(texto: str, entorno: dict[str, str]) -> str:
    """Reemplaza %VARIABLE% con el entorno dado (sin distinguir mayúsculas)."""
    claves = {k.lower(): v for k, v in entorno.items()}
    return re.sub(r"%([^%]+)%", lambda m: claves.get(m.group(1).lower(), m.group(0)), texto or "")


def exe_de_comando(comando: str, entorno: dict[str, str] | None = None) -> str:
    """Ruta del ejecutable de una línea de comandos: '"C:\\Archivos\\a.exe" /x' -> 'C:\\Archivos\\a.exe'. Con rundll32 es la DLL.
    Si no se puede saber (comandos de cmd, rutas relativas sin carpeta), devuelve ''."""
    c = expandir((comando or "").strip(), entorno or {})
    if not c:
        return ""
    m = re.match(r'^"([^"]+)"', c) or re.match(r"^((?:[A-Za-z]:|\\\\).*?\.(?:exe|bat|cmd|com|scr|vbs|js|ps1|lnk|dll))(?:\s|$|,)", c, re.I) \
        or re.match(r"^(\S+)", c)
    ruta = m.group(1) if m else ""
    if stem(ruta) == "rundll32":
        d = re.search(r"rundll32(?:\.exe)?\"?\s+\"?([^,\"]+\.dll)", c, re.I)
        ruta = d.group(1) if d else ruta
    return ruta if re.match(r"^(?:[A-Za-z]:|\\\\)", ruta) else ""


def _h(categoria, regla, severidad, nombre, pid, exe, detalle, clave=None) -> dict:
    import seguridad  # import tardío: seguridad importa plataforma
    return seguridad._h(categoria, regla, severidad, nombre, pid, exe, detalle, clave)


# ---------- procesos ----------

def evaluar_procesos(procesos: list[dict], ctx: dict) -> list[dict]:
    """Hallazgos de los procesos en ejecución.

    `procesos`: [{pid, nombre, exe, cmd, ppid, padre}]. `ctx`: windir, pids_propios (este programa y sus hijos, que no se revisan),
    nocoin (dominios), ventanas (pids con ventana visible), firmas ({ruta normalizada: {estado, firmante}}), salientes ({pid: n}
    conexiones salientes a IP pública), persistentes (rutas en el arranque), config_minero (rutas con configuración de minero al
    lado), rachas ({'uso:<nombre>': n, 'con:<ruta>': n}), juego (hay un juego en curso)."""
    from seguridad import _dominio_en_lista
    res = []
    propios, ventanas, firmas = ctx.get("pids_propios", set()), ctx.get("ventanas", set()), ctx.get("firmas", {})
    windir = ctx.get("windir", "C:\\Windows")
    cuenta = {}
    for p in procesos:
        cuenta[stem(p["nombre"])] = cuenta.get(stem(p["nombre"]), 0) + 1
    for p in procesos:
        pid, nombre, exe, cmd = p["pid"], p["nombre"] or "?", p.get("exe") or "", p.get("cmd") or ""
        if pid in propios or pid in (0, 4):
            continue
        s, ex = stem(nombre), norm(exe)
        firma = firmas.get(ex)
        usuario = en_ruta_de_usuario(exe)

        # -- minería --
        if s in NOMBRES_MINERO_WINDOWS or s in _nombres_minero():
            res.append(_h("minero", "nombre_conocido", "alta", nombre, pid, exe, f"Proceso con nombre de minero: {nombre}"))
        elif CMDLINE_MINERO_FUERTE.search(cmd):
            res.append(_h("minero", "cmdline_minero", "alta", nombre, pid, exe, f"Argumentos típicos de minero: {cmd[:160]}"))
        else:
            from seguridad import DOMINIOS_POOLS
            pool = next((d for d in DOMINIOS_POOLS if d in cmd.lower()), None)
            if pool:
                res.append(_h("minero", "pool_en_cmdline", "alta", nombre, pid, exe, f"Menciona el pool {pool}: {cmd[:160]}"))
            elif CMDLINE_MINERO_DEBIL.search(cmd) and not firma_microsoft(firma):
                res.append(_h("minero", "cmdline_gpu_dudoso", "media", nombre, pid, exe,
                              f"Usa --cuda/--opencl (lo hacen los mineros, pero también otros programas de cálculo): {cmd[:140]}"))
        if cmd and ctx.get("nocoin"):
            host = _dominio_en_lista(cmd, ctx["nocoin"])
            if host:
                res.append(_h("lista_online", "nocoin_cmdline", "alta", nombre, pid, exe, f"Dominio {host} está en la lista NoCoin"))
        if ex and ex in ctx.get("config_minero", ()):
            res.append(_h("minero", "config_junto_al_exe", "alta", nombre, pid, exe,
                          f"Hay un archivo de configuración de minero (pools, algoritmo) junto a {exe}"))
        racha = ctx.get("rachas", {}).get(f"uso:{s}", 0)
        if racha >= RACHA_USO and pid not in ventanas and not ctx.get("juego") and ex and not bajo(exe, windir) and not firma_microsoft(firma):
            sev = "alta" if usuario or firma_mala(firma) else "media"
            res.append(_h("minero", "uso_sostenido_sin_ventana", sev, nombre, pid, exe,
                          f"Usa mucha CPU o GPU desde hace unas {racha * 15} min, sin ventana visible ni juego en curso ({describir_firma(firma)})",
                          clave=ex))

        # -- suplantación de procesos del sistema --
        if s in SISTEMA:
            permitidas = [norm(ntpath.join(windir, c)) for c in SISTEMA[s]]
            if ex and ntpath.dirname(ex) not in permitidas:
                res.append(_h("fantasma", "sistema_fuera_de_ruta", "alta", nombre, pid, exe,
                              f"{nombre} solo corre desde {ntpath.join(windir, SISTEMA[s][0])}; este corre desde {exe}"))
            esperado = PADRE_ESPERADO.get(s)
            if esperado and stem(p.get("padre") or "") != esperado:
                res.append(_h("fantasma", "padre_anomalo", "alta", nombre, pid, exe,
                              f"{nombre} debería nacer de {esperado}.exe y nació de {p.get('padre') or 'un proceso que ya no existe'}", clave=f"{s}|{p.get('padre')}"))
            if s in UNICOS and cuenta.get(s, 0) > 1:
                res.append(_h("fantasma", "proceso_duplicado", "alta", nombre, pid, exe, f"Hay {cuenta[s]} procesos {nombre} y solo debería haber uno"))
        elif len(s) >= 4 and ex and not bajo(exe, windir) and not firma_microsoft(firma):
            parecido = next((r for r in SISTEMA if len(r) >= 5 and r != s and (distancia(s, r) <= 1 or (
                len(s) == len(r) and difflib.SequenceMatcher(None, s, r).ratio() >= 0.85))), None)
            if parecido:
                res.append(_h("fantasma", "nombre_parecido", "alta", nombre, pid, exe,
                              f"Se llama casi como {parecido}.exe, un proceso del sistema, pero corre desde {exe}"))

        # -- padres anómalos y PowerShell --
        padre = stem(p.get("padre") or "")
        if s in INTERPRETES and padre in OFFICE:
            res.append(_h("fantasma", "interprete_hijo_de_office", "alta", nombre, pid, exe, f"{nombre} lo lanzó {p['padre']}: típico de macros maliciosas",
                          clave=f"{s}|{padre}"))
        elif s in INTERPRETES and padre in NAVEGADORES:
            res.append(_h("fantasma", "interprete_hijo_de_navegador", "media", nombre, pid, exe, f"{nombre} lo lanzó el navegador {p['padre']}",
                          clave=f"{s}|{padre}"))
        if s in ("powershell", "pwsh") and cmd:
            if POWERSHELL_OFUSCADO.search(cmd) or (POWERSHELL_DESCARGA.search(cmd) and re.search(r"\b(iex|invoke-expression)\b", cmd, re.I)):
                res.append(_h("fantasma", "powershell_sospechoso", "alta", nombre, pid, exe, f"PowerShell oculto, codificado o con descarga: {cmd[:160]}", clave=cmd[:200]))
            elif POWERSHELL_DESCARGA.search(cmd):
                res.append(_h("fantasma", "powershell_descarga", "media", nombre, pid, exe, f"PowerShell que descarga o decodifica: {cmd[:160]}", clave=cmd[:200]))

        # -- espías --
        if s in NOMBRES_KEYLOGGER_WINDOWS or any(k in s for k in ("keylog", "keystroke")):
            res.append(_h("keylogger", "nombre_conocido", "alta", nombre, pid, exe, f"Proceso con nombre de keylogger o acceso remoto malicioso: {nombre}"))
        elif usuario and firma_mala(firma) and not bajo(exe, windir):
            persistente, salidas = ex in ctx.get("persistentes", ()), ctx.get("salientes", {}).get(pid, 0)
            if persistente or salidas:
                motivos = " y ".join(m for m, v in (("está en el arranque", persistente), (f"tiene {salidas} conexión(es) saliente(s)", salidas)) if v)
                res.append(_h("keylogger", "sin_firma_en_ruta_de_usuario", "alta" if persistente and salidas else "media", nombre, pid, exe,
                              f"{describir_firma(firma).capitalize()}, corre desde una carpeta del usuario y {motivos}", clave=ex))
        if ctx.get("rachas", {}).get(f"con:{ex}", 0) >= RACHA_SALIDA and pid not in ventanas and ex and not bajo(exe, windir) \
                and not firma_microsoft(firma) and (usuario or firma_mala(firma)):
            res.append(_h("keylogger", "sin_ventana_con_salida_persistente", "media", nombre, pid, exe,
                          f"Sin ventana y con conexión saliente a IP pública sostenida ({describir_firma(firma)})", clave=ex))
    return res


def _nombres_minero() -> set[str]:
    from seguridad import NOMBRES_MINERO
    return NOMBRES_MINERO


# ---------- persistencia ----------

WINLOGON_NORMAL = {"shell": "explorer.exe", "userinit": "c:\\windows\\system32\\userinit.exe"}
WMI_NORMAL = {"scm event log filter", "scm event log consumer", "bvtfilter", "bvtconsumer"}


def items_persistencia(datos: dict, entorno: dict[str, str]) -> list[dict]:
    """Todo lo que arranca solo, de las distintas fuentes. `datos`: run ({'hive','clave','nombre','valor'}), tareas, servicios, inicio,
    wmi ({'filtros','consumidores'}), winlogon ({'Shell','Userinit'}), ifeo ({exe: debugger}), appinit ([valor]).
    Cada item: {tipo, nombre, comando, exe, sospechoso (motivo o '')}."""
    res = []

    def agregar(tipo, nombre, comando, sospechoso="", exe=None):
        res.append({"tipo": tipo, "nombre": nombre, "comando": (comando or "").strip(),
                    "exe": exe if exe is not None else exe_de_comando(comando, entorno), "sospechoso": sospechoso})

    for r in datos.get("run", []):
        agregar(r["clave"], f"{r['hive']}\\{r['nombre']}", r["valor"])
    for t in datos.get("inicio", []):
        agregar("inicio", t["Nombre"], f"{t.get('Destino') or t['Ruta']} {t.get('Argumentos') or ''}".strip(),
                exe=exe_de_comando(t.get("Destino") or t["Ruta"], entorno))
    for t in datos.get("tareas", []):
        cmd = f"{t.get('Ejecuta') or ''} {t.get('Argumentos') or ''}".strip()
        if cmd:
            agregar("tarea", f"{t.get('Ruta', '')}{t['Nombre']}", cmd)
    for s in datos.get("servicios", []):
        if s.get("PathName"):
            agregar("servicio", s["Name"], s["PathName"])
    w = datos.get("winlogon") or {}
    for clave, normal in WINLOGON_NORMAL.items():
        valor = (w.get(clave.capitalize()) or "").strip()
        if valor and norm(valor.rstrip(",")) != normal and valor.lower().rstrip(",") != normal.rsplit("\\", 1)[-1]:
            agregar("winlogon", clave.capitalize(), valor, f"{clave.capitalize()} de Winlogon distinto del de Windows ({valor})")
    for exe, dbg in (datos.get("ifeo") or {}).items():
        agregar("ifeo", exe, dbg, f"Image File Execution Options redirige {exe} a {dbg}")
    for v in datos.get("appinit") or []:
        agregar("appinit", "AppInit_DLLs", v, "AppInit_DLLs carga una DLL en cada programa con interfaz")
    wmi = datos.get("wmi") or {}
    for c in wmi.get("consumidores", []):
        if (c.get("Name") or "").lower() not in WMI_NORMAL:
            agregar("wmi", c.get("Name") or "?", c.get("CommandLineTemplate") or c.get("ExecutablePath") or c.get("ScriptFileName") or "",
                    "Suscripción WMI que ejecuta código (persistencia típica de mineros y malware sin archivos)")
    return res


def hallazgos_persistencia(items: list[dict], firmas: dict, conocidos: set[str], es_base: bool,
                           windir: str = "C:\\Windows") -> tuple[list[dict], list[dict]]:
    """(hallazgos, items_nuevos). `conocidos` son las huellas de lo ya visto; con `es_base` (primera corrida) se registra todo sin avisar
    de lo nuevo, pero lo sospechoso por su contenido se informa igual. Los servicios y tareas de Microsoft (en la carpeta de Windows o con
    su firma) no se siguen: el arranque que importa es el que no es del sistema."""
    res, nuevos = [], []
    for it in items:
        clave = f"{it['tipo']}|{it['nombre']}|{it['comando']}"
        it["clave"] = clave
        firma = firmas.get(norm(it["exe"]))
        if it["tipo"] in ("servicio", "tarea") and (bajo(it["exe"], windir) or firma_microsoft(firma)):
            continue
        motivo = it["sospechoso"]
        if not motivo and POWERSHELL_OFUSCADO.search(it["comando"]):
            motivo = "El comando de arranque usa PowerShell oculto o codificado"
        elif not motivo and re.search(r"\b(iex|invoke-expression|downloadstring|downloadfile)\b", it["comando"], re.I):
            motivo = "El comando de arranque descarga y ejecuta código"
        if motivo:
            res.append(_h("persistencia", f"{it['tipo']}_sospechoso", "alta", it["nombre"], None, it["exe"], f"{motivo}: {it['comando'][:140]}", clave=clave))
        elif it["exe"] and en_ruta_de_usuario(it["exe"]) and firma_mala(firma):
            res.append(_h("persistencia", f"{it['tipo']}_sin_firma_en_ruta_de_usuario", "media", it["nombre"], None, it["exe"],
                          f"Arranca solo desde una carpeta del usuario y está {describir_firma(firma)}: {it['comando'][:120]}", clave=clave))
        elif clave not in conocidos and not es_base:
            sev = "media" if (en_ruta_de_usuario(it["exe"]) or firma_mala(firma)) else "baja"
            res.append(_h("persistencia", f"{it['tipo']}_nuevo", sev, it["nombre"], None, it["exe"],
                          f"Apareció algo nuevo que arranca solo ({it['tipo']}): {it['comando'][:120]} ({describir_firma(firma)})", clave=clave))
        if clave not in conocidos:
            nuevos.append(it)
    return res, nuevos


# ---------- postura ----------

# Fin de soporte de las ediciones Home/Pro por número de build (Enterprise, Education y ESU tienen más tiempo). Es una tabla propia que hay que
# actualizar a mano cuando Microsoft publica fechas nuevas: un build que no está acá no genera ningún hallazgo.
FIN_SOPORTE_HOME_PRO = {19044: date(2023, 6, 13), 19045: date(2025, 10, 14), 22000: date(2023, 10, 10), 22621: date(2024, 10, 8),
                        22631: date(2025, 11, 11), 26100: date(2026, 10, 13)}


def evaluar_postura(d: dict, hoy: date, build: int | None, edicion: str, upgrades: list[dict] | None) -> list[dict]:
    """Hallazgos de la configuración de seguridad. `d`: defender, amenazas, firewall, hotfix_dias, uac, smb1, rdp ({'activo','nla'})."""
    res = []

    def hallazgo(regla, sev, texto, nombre="Windows"):
        res.append(_h("postura", regla, sev, nombre, None, "", texto, clave=regla))

    df = d.get("defender")
    if df:
        pasivo = str(df.get("modo") or "").lower() in ("passive mode", "edr block mode", "sxs passive mode")
        if df.get("rtp") is False and not pasivo:
            hallazgo("defender_sin_proteccion", "alta", "La protección en tiempo real de Microsoft Defender está desactivada", "Microsoft Defender")
        elif df.get("rtp") is False:
            hallazgo("defender_pasivo", "baja", "Defender está en modo pasivo: hay otro antivirus a cargo (pc-doctor no lo ve)", "Microsoft Defender")
        edad = df.get("firmas_dias")
        if isinstance(edad, (int, float)) and edad >= 7 and not pasivo:
            hallazgo("defender_firmas_viejas", "media" if edad < 30 else "alta", f"Las definiciones de Defender tienen {int(edad)} días", "Microsoft Defender")
        v = df.get("rapido_dias")
        if isinstance(v, (int, float)) and 30 <= v < 36500 and not pasivo:   # 36500+ es "nunca" en Windows
            hallazgo("defender_sin_escaneo", "baja", f"Hace {int(v)} días que Defender no hace un escaneo rápido", "Microsoft Defender")
    for a in d.get("amenazas") or []:
        res.append(_h("postura", "defender_amenaza", "alta", a.get("Nombre") or f"Amenaza {a.get('ThreatID')}", None, "",
                      f"Defender detectó {a.get('Nombre') or 'una amenaza'} en {str(a.get('Recursos') or '')[:100]}"
                      f"{' (acción exitosa)' if a.get('Accion') else ' (sin acción exitosa)'}", clave=f"amenaza|{a.get('ThreatID')}|{a.get('Recursos')}"))
    for f in d.get("firewall") or []:
        activo = {True: True, 1: True, "True": True, False: False, 0: False, "False": False}.get(f.get("Enabled"))
        if activo is False:
            nombre = str(f.get("Name") or "?")
            hallazgo(f"firewall_{nombre.lower()}", "alta" if nombre.lower() == "public" else "media",
                     f"El firewall de Windows está desactivado en el perfil {nombre}", "Firewall")
    if d.get("uac") == 0:
        hallazgo("uac_desactivado", "alta", "El control de cuentas de usuario (UAC) está desactivado", "UAC")
    if d.get("smb1") == 1:
        hallazgo("smb1_activo", "alta", "SMBv1 está habilitado en el servidor (protocolo obsoleto, usado por WannaCry)", "SMBv1")
    rdp = d.get("rdp") or {}
    if rdp.get("activo") and rdp.get("nla") == 0:
        hallazgo("rdp_sin_nla", "alta", "El Escritorio remoto está habilitado sin autenticación a nivel de red (NLA)", "Escritorio remoto")
    dias = d.get("hotfix_dias")
    if isinstance(dias, (int, float)) and dias >= 60:
        hallazgo("sin_parches_recientes", "media" if dias < 120 else "alta", f"El último parche de Windows instalado es de hace {int(dias)} días", "Windows Update")
    fin = FIN_SOPORTE_HOME_PRO.get(build or 0)
    if fin and fin < hoy and not re.search(r"enterprise|education|iot|server", edicion or "", re.I):
        hallazgo("windows_sin_soporte", "alta", f"Esta versión de Windows (build {build}) terminó su soporte el {fin.isoformat()} "
                 "(fecha de Home/Pro: Enterprise, Education o ESU pueden tener más)", "Windows")
    if upgrades:
        nombres = ", ".join(u.get("Name") or u.get("Id", "?") for u in upgrades[:5])
        hallazgo("programas_desactualizados", "media" if len(upgrades) > 20 else "baja",
                 f"{len(upgrades)} programa(s) con versión nueva disponible en winget (no se actualiza nada solo): {nombres}{'...' if len(upgrades) > 5 else ''}",
                 "Programas")
    return res


# ---------- catálogo KEV de CISA (opcional) ----------

GENERICOS_KEV = {"windows", "office", "microsoft", "adobe", "google", "apple", "oracle", "linux", "android", "ios", "browser", "server", "client"}


def coincidencias_kev(kev: dict, programas: list[tuple[str, str, str]], maximo: int = 10) -> list[dict]:
    """Programas instalados cuyo nombre coincide con un producto del catálogo KEV (vulnerabilidades explotadas). Coincidir por nombre da
    falsos positivos: no se compara la versión, así que se informa como "revisar" y nunca como "vulnerable"."""
    por_programa: dict[str, list[str]] = {}
    for v in (kev or {}).get("vulnerabilities", []):
        producto, proveedor = (v.get("product") or "").lower().strip(), (v.get("vendorProject") or "").lower().strip()
        if len(producto) < 4 or producto in GENERICOS_KEV or not proveedor:
            continue
        for nombre, _, _ in programas:
            n = nombre.lower()
            if re.search(rf"(?<![a-z0-9]){re.escape(producto)}(?![a-z0-9])", n) and proveedor.split()[0] in n:
                por_programa.setdefault(nombre, []).append(v.get("cveID") or "?")
    res = []
    for nombre, cves in sorted(por_programa.items(), key=lambda kv: -len(kv[1]))[:maximo]:
        res.append(_h("vulnerabilidad", "posible_kev", "baja", nombre, None, "",
                      f"REVISAR (no significa que esté vulnerable): el nombre coincide con productos del catálogo KEV de CISA "
                      f"({len(cves)} CVE, ej. {', '.join(sorted(set(cves))[:3])}). No se comparó la versión.", clave=nombre))
    return res

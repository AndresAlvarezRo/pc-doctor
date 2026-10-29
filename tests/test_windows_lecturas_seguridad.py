"""Lecturas de seguridad de Windows con el sistema simulado: caché de firmas por hash, rachas, instantánea del arranque, postura diaria,
DNS sin `dig`. Ningún comando, registro ni red reales; corre en Linux."""

import json
import time
from types import SimpleNamespace

import pytest

import db
import plataforma
import reputacion
import seguridad
from plataforma import windows, windows_lecturas_seguridad as wl, windows_seguridad as ws, windows_sistema as wsi

MALA = {"estado": "NotSigned", "firmante": ""}
VALIDA = {"estado": "Valid", "firmante": "CN=Acme"}


@pytest.fixture
def datos(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DIR_DATOS", tmp_path)
    wl._cache.clear()
    return tmp_path


def archivo(carpeta, nombre, contenido=b"x"):
    p = carpeta / nombre
    p.write_bytes(contenido)
    return str(p)


class Verificador:
    """Reemplazo de _verificar_firmas: anota qué rutas se pidieron."""
    def __init__(self, estado="NotSigned"):
        self.estado, self.llamadas = estado, []

    def __call__(self, rutas):
        self.llamadas.append(list(rutas))
        return {ws.norm(r): {"estado": self.estado, "firmante": "CN=Acme" if self.estado == "Valid" else ""} for r in rutas}


# ---------- firmas ----------

def test_cada_ejecutable_se_verifica_una_sola_vez_por_hash(datos, monkeypatch):
    v = Verificador()
    monkeypatch.setattr(wl, "_verificar_firmas", v)
    a, b = archivo(datos, "a.exe", b"programa uno"), archivo(datos, "b.exe", b"programa dos")
    r = wl.firmas_de([a, b, str(datos / "no_existe.exe"), ""])
    assert set(r) == {ws.norm(a), ws.norm(b)} and r[ws.norm(a)]["estado"] == "NotSigned" and len(v.llamadas) == 1 and len(v.llamadas[0]) == 2
    wl.firmas_de([a, b])
    assert len(v.llamadas) == 1                                       # todo salió de la caché
    copia = archivo(datos, "copia.exe", b"programa uno")             # mismo contenido en otra ruta: mismo hash
    assert wl.firmas_de([copia])[ws.norm(copia)]["estado"] == "NotSigned" and len(v.llamadas) == 1
    archivo(datos, "a.exe", b"programa uno MODIFICADO")             # cambió el archivo: se vuelve a verificar
    wl.firmas_de([a])
    assert len(v.llamadas) == 2 and v.llamadas[1] == [a]


def test_la_cache_vive_en_un_archivo_y_las_firmas_vencidas_se_repiten(datos, monkeypatch):
    v = Verificador("Valid")
    monkeypatch.setattr(wl, "_verificar_firmas", v)
    a = archivo(datos, "a.exe")
    wl.firmas_de([a])
    c = json.loads((datos / "firmas.cache.json").read_text())
    assert list(c["firmas"].values())[0]["estado"] == "Valid" and len(c["hashes"]) == 1
    for f in c["firmas"].values():
        f["ts"] = time.time() - 40 * 86400
    (datos / "firmas.cache.json").write_text(json.dumps(c))
    wl.firmas_de([a])
    assert len(v.llamadas) == 2


def test_un_error_de_verificacion_no_se_guarda_ni_inventa_una_firma(datos, monkeypatch):
    v = Verificador("Error")
    monkeypatch.setattr(wl, "_verificar_firmas", v)
    a = archivo(datos, "a.exe")
    assert wl.firmas_de([a]) == {}
    wl.firmas_de([a])
    assert len(v.llamadas) == 2


def test_se_verifican_como_mucho_60_archivos_nuevos_por_corrida(datos, monkeypatch):
    v = Verificador()
    monkeypatch.setattr(wl, "_verificar_firmas", v)
    rutas = [archivo(datos, f"p{i}.exe", f"contenido {i}".encode()) for i in range(70)]
    assert len(wl.firmas_de(rutas)) == 60 and len(wl.firmas_de(rutas)) == 70      # el resto, en la corrida siguiente


def test_la_verificacion_va_en_una_sola_llamada_y_con_las_rutas_codificadas(monkeypatch):
    llamadas = []
    monkeypatch.setattr(wl, "_ps", lambda script, timeout=60: llamadas.append(script) or [{"Ruta": "C:\\A B\\x.exe", "Estado": "Valid", "Firmante": "CN=Acme"}])
    r = wl._verificar_firmas(["C:\\A B\\x.exe", "C:\\o'malley\\y.exe"])
    assert len(llamadas) == 1 and "o'malley" not in llamadas[0] and "Get-AuthenticodeSignature -LiteralPath" in llamadas[0]
    assert r == {ws.norm("C:\\A B\\x.exe"): {"estado": "Valid", "firmante": "CN=Acme"}}


def test_describir_procesos_da_la_firma_de_quien_escucha(datos, monkeypatch):
    a = archivo(datos, "srv.exe")
    monkeypatch.setattr(wl, "_verificar_firmas", Verificador("Valid"))
    monkeypatch.setattr(wl, "psutil", SimpleNamespace(Process=lambda pid: SimpleNamespace(exe=lambda: a if pid == 10 else ""), Error=Exception))
    assert wl.describir_procesos([10, 11, None, 0]) == {10: "firmado por Acme"}


# ---------- rachas ----------

def test_una_racha_suma_una_corrida_cada_10_minutos_y_se_corta_si_deja_de_pasar(con):
    wl.actualizar_rachas(con, {"uso:a", "con:b"}, 1000)
    assert wl.rachas(con) == {"uso:a": 1, "con:b": 1}
    wl.actualizar_rachas(con, {"uso:a"}, 1100)            # una revisión manual a los 100 s no cuenta como otra corrida
    assert wl.rachas(con) == {"uso:a": 1}                  # con:b se cortó
    wl.actualizar_rachas(con, {"uso:a"}, 1700)
    assert wl.rachas(con) == {"uso:a": 2}
    wl.actualizar_rachas(con, set(), 2400)
    assert wl.rachas(con) == {}


# ---------- procesos ----------

def P(pid, nombre, exe, cmd="", padre=""):
    return {"pid": pid, "nombre": nombre, "exe": exe, "cmd": cmd or exe, "ppid": 1, "padre": padre}


@pytest.fixture
def sistema(monkeypatch, con):
    """Un equipo de Windows simulado: un suplantador, un proceso que lleva casi una hora al máximo y uno normal."""
    imp = "C:\\Users\\v\\AppData\\Local\\Temp\\svchost.exe"
    pesado = "C:\\Users\\v\\AppData\\Roaming\\m\\render2.exe"
    procs = [P(100, "svchost.exe", imp, padre="services.exe"), P(101, "render2.exe", pesado), P(102, "notepad.exe", "C:\\Windows\\notepad.exe"),
             P(103, "python.exe", "C:\\py\\python.exe")]
    monkeypatch.setattr(wl, "procesos", lambda: procs)
    monkeypatch.setattr(wl, "ventanas_visibles", lambda: {102})
    monkeypatch.setattr(wl, "salientes_por_pid", lambda: {101: 2})
    monkeypatch.setattr(wl, "uso_alto", lambda p: {"render2"})
    monkeypatch.setattr(wl, "persistencia_items", lambda: [])
    monkeypatch.setattr(wl, "pids_propios", lambda: {103})
    monkeypatch.setattr(wl, "config_minero_junto_a", lambda rutas: set())
    monkeypatch.setattr(wl, "firmas_de", lambda rutas: {ws.norm(r): MALA for r in rutas})
    return SimpleNamespace(imp=imp, pesado=pesado)


def test_el_escaneo_de_procesos_une_las_lecturas_las_rachas_y_las_reglas(sistema, con):
    wl.asegurar_tablas(con)
    con.execute("INSERT INTO seguridad_estado (clave, valor, actualizado) VALUES ('racha:uso:render2', 3, 0)")
    hallazgos, stats = wl.escanear_procesos(con)
    reglas = {(h["pid"], h["regla"]) for h in hallazgos}
    assert (100, "sistema_fuera_de_ruta") in reglas and (101, "uso_sostenido_sin_ventana") in reglas      # la racha llegó a 4
    assert not any(h["pid"] in (102, 103) for h in hallazgos)
    assert stats == {"procesos": 4, "sin_acceso": 0}
    assert wl.rachas(con)["uso:render2"] == 4 and wl.rachas(con)[f"con:{ws.norm(sistema.pesado)}"] == 1


def test_sin_base_no_hay_rachas_pero_lo_demas_si(sistema):
    reglas = {h["regla"] for h in wl.escanear_procesos(None)[0]}
    assert "sistema_fuera_de_ruta" in reglas and "uso_sostenido_sin_ventana" not in reglas       # lo que depende de la memoria de corridas anteriores no aparece


def test_seguridad_escanear_en_windows_junta_procesos_red_y_extras(sistema, con, monkeypatch):
    plataforma.forzar("windows")
    try:
        monkeypatch.setattr(wl, "escanear_extra", lambda con=None: [ws._h("postura", "uac_desactivado", "alta", "UAC", None, "", "UAC apagado", clave="uac")])
        monkeypatch.setattr(seguridad, "conexiones", lambda: ([], []))
        r = seguridad.escanear(con)
    finally:
        plataforma.forzar(None)
    assert [h["severidad"] for h in r["hallazgos"]] == sorted((h["severidad"] for h in r["hallazgos"]), key=["alta", "media", "baja"].index)
    assert {"sistema_fuera_de_ruta", "uac_desactivado"} <= {h["regla"] for h in r["hallazgos"]} and r["stats"]["procesos"] == 4


def test_los_hallazgos_de_windows_se_guardan_con_las_categorias_nuevas(con):
    h = [ws._h(c, "r", "media", "n", None, "", "d", clave=c) for c in ("persistencia", "postura", "vulnerabilidad", "fantasma")]
    assert seguridad.guardar(con, {"hallazgos": h, "escuchas": []})["nuevos"] == 4
    assert con.execute("SELECT COUNT(*) c FROM hallazgos_seguridad").fetchone()["c"] == 4


# ---------- arranque y postura ----------

@pytest.fixture
def arranque(monkeypatch):
    items = ws.items_persistencia({"run": [{"hive": "HKCU", "clave": "run", "nombre": "Steam", "valor": '"C:\\Program Files\\Steam\\steam.exe" -silent'}],
                                   "appinit": ["C:\\evil.dll"]}, {})
    estado = {"items": items, "postura": 0}
    monkeypatch.setattr(wl, "persistencia_items", lambda: estado["items"])
    monkeypatch.setattr(wl, "firmas_de", lambda rutas: {})
    monkeypatch.setattr(wl, "revisar_postura", lambda: estado.__setitem__("postura", estado["postura"] + 1) or [])
    return estado


def test_la_primera_corrida_es_la_base_y_despues_solo_se_avisa_de_lo_que_aparece(con, arranque):
    h = wl.escanear_extra(con)
    assert [x["regla"] for x in h] == ["appinit_sospechoso"]                       # lo sospechoso por su contenido, aunque sea la base
    assert con.execute("SELECT COUNT(*) c FROM persistencia").fetchone()["c"] == 2
    assert [x["regla"] for x in wl.escanear_extra(con)] == ["appinit_sospechoso"]   # nada nuevo
    arranque["items"] = arranque["items"] + ws.items_persistencia({"run": [{"hive": "HKCU", "clave": "run", "nombre": "Nuevo", "valor": "C:\\Programas\\n.exe"}]}, {})
    assert sorted(x["regla"] for x in wl.escanear_extra(con)) == ["appinit_sospechoso", "run_nuevo"]
    assert sorted(x["regla"] for x in wl.escanear_extra(con)) == ["appinit_sospechoso"]   # lo nuevo ya es parte de la base: se avisa una sola vez
    assert con.execute("SELECT COUNT(*) c FROM persistencia").fetchone()["c"] == 3


def test_la_postura_se_revisa_una_vez_por_dia(con, arranque):
    wl.escanear_extra(con)
    wl.escanear_extra(con)
    assert arranque["postura"] == 1
    con.execute("UPDATE seguridad_estado SET valor = valor - ? WHERE clave='postura_ultima'", (21 * 3600,))
    wl.escanear_extra(con)
    assert arranque["postura"] == 2


def test_sin_base_solo_se_informa_lo_sospechoso_y_no_se_revisa_la_postura(arranque):
    assert [x["regla"] for x in wl.escanear_extra(None)] == ["appinit_sospechoso"] and arranque["postura"] == 0


def test_los_datos_de_postura_salen_de_powershell_y_del_registro(monkeypatch):
    reg = {"EnableLUA": 0, "SMB1": 1, "fDenyTSConnections": 0, "UserAuthentication": 0}
    monkeypatch.setattr(wl, "_ps", lambda *a, **k: {"defender": {"rtp": False}, "firewall": {"Name": "Public", "Enabled": "False"}, "hotfix_dias": 90})
    monkeypatch.setattr(wl, "_registro", lambda raiz, ruta, nombre: reg.get(nombre))
    d = wl.datos_postura()
    assert d["firewall"] == [{"Name": "Public", "Enabled": "False"}] and d["amenazas"] == []      # un solo objeto se vuelve lista
    assert (d["uac"], d["smb1"], d["rdp"]) == (0, 1, {"activo": True, "nla": 0})


def test_revisar_postura_arma_los_hallazgos_y_el_kev_es_opcional(monkeypatch):
    monkeypatch.setattr(windows, "_datos_hardware", lambda: {"so": [{"BuildNumber": "19045", "Caption": "Microsoft Windows 10 Pro"}]})
    monkeypatch.setattr(wl, "datos_postura", lambda: {"uac": 0})
    monkeypatch.setattr(wl, "winget_upgrade", lambda: [{"Name": "Firefox", "Id": "Mozilla.Firefox", "Available": "127"}])
    monkeypatch.setattr(windows, "paquetes", lambda: [("Mozilla Firefox", "126", "registro")])
    descargas = []
    monkeypatch.setattr(wl, "kev", lambda: descargas.append(1) or {"vulnerabilidades": []})
    monkeypatch.setattr(reputacion, "cargar_config", lambda crear=True: {"kev": False})
    reglas = {h["regla"] for h in wl.revisar_postura()}
    assert {"uac_desactivado", "windows_sin_soporte", "programas_desactualizados"} <= reglas and descargas == []     # sin kev: no se descarga nada
    monkeypatch.setattr(reputacion, "cargar_config", lambda crear=True: {"kev": True})
    wl.revisar_postura()
    assert descargas == [1]


def test_winget_upgrade_solo_lista_y_lee_los_titulos_en_espanol(monkeypatch):
    salida = ("Nombre              Id                Versión  Disponible  Origen\n"
              "-----------------------------------------------------------------\n"
              "Mozilla Firefox     Mozilla.Firefox   126.0    127.0       winget\n"
              "Steam               Valve.Steam       2.10     2.10        winget\n"
              "3 actualizaciones disponibles.\n")
    comandos = []
    monkeypatch.setattr("shutil.which", lambda n: "winget")
    monkeypatch.setattr("subprocess.run", lambda cmd, **k: comandos.append(cmd) or SimpleNamespace(stdout=salida.encode()))
    r = wl.winget_upgrade()
    assert [f["Id"] for f in r] == ["Mozilla.Firefox", "Valve.Steam"] and comandos[0][:2] == ["winget", "upgrade"]
    assert "--all" not in comandos[0] and "install" not in comandos[0]                  # nunca actualiza


def test_el_catalogo_kev_se_descarga_una_vez_por_dia_y_si_falla_no_rompe(datos, monkeypatch):
    llamadas = []

    def falla(*a, **k):
        llamadas.append(1)
        raise OSError("sin red")
    monkeypatch.setattr(wl.urllib.request, "urlopen", falla)
    assert wl.kev() is None and llamadas == [1]
    (datos / "listas").mkdir()
    (datos / "listas" / "kev.json").write_text('{"vulnerabilities": []}')
    assert wl.kev() == {"vulnerabilities": []} and llamadas == [1]                       # vigente: no vuelve a la red


def test_la_persistencia_se_lee_del_registro_y_de_powershell(monkeypatch):
    claves = {("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Run"): {"Steam": '"C:\\S\\steam.exe" -silent'}}
    monkeypatch.setattr(wl, "_valores_registro", lambda raiz, ruta: claves.get((raiz, ruta), {}))
    monkeypatch.setattr(wl, "_registro", lambda raiz, ruta, nombre: {("HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon", "Shell"): "explorer.exe",
                        ("HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Windows", "AppInit_DLLs"): "  "}.get((raiz, ruta, nombre)))
    monkeypatch.setattr(wl, "_ps", lambda *a, **k: {"tareas": {"Ruta": "\\", "Nombre": "T", "Ejecuta": "C:\\t\\t.exe", "Argumentos": ""}, "servicios": [], "wmi": {}})
    items = wl.persistencia_items()
    assert sorted((i["tipo"], i["nombre"]) for i in items) == [("run", "HKCU\\Steam"), ("tarea", "\\T")]


# ---------- DNS sin dig ----------

def stub(respuesta):
    pedidos = []
    return pedidos, lambda script, timeout=20: pedidos.append(script) or respuesta


HASH = "a" * 40


def test_consultar_txt_en_windows_entiende_las_tres_respuestas():
    for respuesta, esperado in (({"estado": "NOERROR", "txt": ["1700000000 45"]}, ("NOERROR", ["1700000000 45"])), ({"estado": "NXDOMAIN", "txt": []}, ("NXDOMAIN", [])),
                                ({"estado": "ERROR", "txt": []}, None), (None, None)):
        _, ps = stub(respuesta)
        assert wl.consultar_txt(f"{HASH}.hash.cymru.com", ps) == esperado


def test_consultar_txt_rechaza_cualquier_nombre_que_no_sea_una_consulta_de_hash():
    pedidos, ps = stub({"estado": "NOERROR", "txt": []})
    for malo in ("x.hash.cymru.com", f"{HASH}.evil.com", f"{HASH}.hash.cymru.com'; calc;'", "'; Remove-Item *; '", f"{HASH.upper()}.hash.cymru.com"):
        assert wl.consultar_txt(malo, ps) is None
    assert pedidos == []


class DNS:
    def __init__(self, respuesta):
        self.respuesta = respuesta


@pytest.mark.parametrize("plataforma_activa", ["linux", "windows"])
def test_team_cymru_da_el_mismo_veredicto_con_dig_y_con_resolve_dnsname(plataforma_activa, monkeypatch):
    dig = lambda estado, txt: (f";; ->>HEADER<<- opcode: QUERY, status: {estado}, id: 1\n" + (f'{HASH}.hash.cymru.com. 60 IN TXT "{txt}"\n' if txt else ""))
    casos = [("NOERROR", "1700000000 75", ("malicioso", "Detectado por 75% de los antivirus")), ("NOERROR", "1700000000 20", ("sospechoso", "Detectado por 20% de los antivirus")),
             ("NXDOMAIN", None, ("sin_registro", None))]
    for estado, txt, esperado in casos:
        plataforma.forzar(plataforma_activa)
        try:
            if plataforma_activa == "linux":
                monkeypatch.setattr(reputacion, "ejecutar", lambda cmd, timeout=20, e=estado, t=txt: dig(e, t) if cmd[0] == "dig" and cmd[-1] == f"{HASH}.hash.cymru.com" else None)
            else:
                monkeypatch.setattr(windows, "_json_ps", lambda script, timeout=60, e=estado, t=txt: {"estado": e, "txt": [t] if t else []})
            assert reputacion._cymru(HASH) == esperado
        finally:
            plataforma.forzar(None)


def test_team_cymru_sin_dig_o_con_error_devuelve_none(monkeypatch):
    monkeypatch.setattr(reputacion, "ejecutar", lambda *a, **k: None)
    assert reputacion._cymru(HASH) is None
    monkeypatch.setattr(reputacion, "ejecutar", lambda *a, **k: ";; ->>HEADER<<- status: SERVFAIL\n")
    assert reputacion._cymru(HASH) is None


def test_en_windows_solo_se_consultan_hashes_de_sospechosos_y_las_persistencias_con_ejecutable_tambien(con, tmp_path, monkeypatch):
    exe = tmp_path / "evil.exe"
    exe.write_bytes(b"MZ prueba")
    consultados = []
    monkeypatch.setattr(reputacion, "consultar_hash", lambda s256, s1, cfg: consultados.append(s256) or ("sin_registro", "CIRCL", None))
    sospechoso = ws._h("persistencia", "run_sospechoso", "alta", "Run", None, str(exe), "x", clave="k")
    comun = ws._h("persistencia", "run_nuevo", "baja", "Run2", None, str(exe), "x", clave="k2")      # baja: nunca se consulta
    postura = ws._h("postura", "uac_desactivado", "alta", "UAC", None, "", "x", clave="uac")          # sin ejecutable
    seguridad.guardar(con, {"hallazgos": [sospechoso, comun, postura], "escuchas": []})
    r = reputacion.consultar_sospechosos(con, [sospechoso, comun, postura])
    assert len(consultados) == 1 and r["consultados"] == 1


def test_la_suscripcion_wmi_que_pide_administrador_se_informa_como_no_disponible(monkeypatch):
    wl._cache.clear()
    assert wl.avisos_no_disponible() == []
    monkeypatch.setattr(wl, "_registro", lambda *a: None)
    monkeypatch.setattr(wl, "_valores_registro", lambda *a: {})
    monkeypatch.setattr(wl, "_ps", lambda *a, **k: {"wmi_sin_acceso": True})
    wl.persistencia_items()
    assert "WMI" in wl.avisos_no_disponible()[0] and "administrador" in wl.avisos_no_disponible()[0]
    wl._cache.clear()

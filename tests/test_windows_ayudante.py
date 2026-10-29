"""Lado sin privilegios del ayudante de Windows: validación de estado.json (que lo escribe SYSTEM), lecturas con los nombres de Linux,
hallazgos de postura y avisos. Corre en Linux con archivos simulados."""

import json
import time

import pytest

import plataforma
import salud
from plataforma import windows, windows_ayudante as wa, windows_lecturas_seguridad as wl, windows_seguridad as ws

AHORA = 1_800_000_000
# Lo que dio smartctl en el SSD con problemas de la PC de desarrollo: 1 sector realocado, 1 pendiente, 2 incorregibles, 10 errores CRC
SMARTCTL = json.dumps({"smart_status": {"passed": True}, "power_on_time": {"hours": 21125},
                       "ata_smart_attributes": {"table": [{"id": 5, "raw": {"value": 1}}, {"id": 197, "raw": {"value": 1}},
                                                          {"id": 198, "raw": {"value": 2}}, {"id": 199, "raw": {"value": 10}}]}})


def estado(**cambios):
    base = {"version": 1, "ts": AHORA - 60, "smart": {"disk1": SMARTCTL},
            "fiabilidad": [{"Id": 0, "Temperatura": 38, "Desgaste": 4, "Horas": 1200, "LecturasNoCorregidas": 0, "EscriturasNoCorregidas": 0}],
            "bitlocker": [{"Punto": "C:", "Estado": "FullyEncrypted", "Proteccion": "On", "Bloqueo": "Unlocked", "Metodo": "XtsAes128"}],
            "arranque_seguro": "activado", "defender": {"rutas": [], "extensiones": [], "procesos": []},
            "wmi": {"consumidores": []}, "errores": []}
    return {**base, **cambios}


def ok(**cambios):
    return {"estado": "ok", "datos": wa.validar(estado(**cambios)), "edad_s": 60, "motivo": ""}


# ---------- validación ----------

def archivo(tmp_path, contenido, nombre="estado.json"):
    p = tmp_path / nombre
    p.write_text(contenido if isinstance(contenido, str) else json.dumps(contenido), encoding="utf-8-sig")
    return p


def test_un_estado_reciente_y_bien_formado_se_lee(tmp_path):
    r = wa.leer(archivo(tmp_path, estado()), ahora=AHORA)
    assert r["estado"] == "ok" and r["edad_s"] == 60 and r["datos"]["smart"] == {"disk1": SMARTCTL}


def test_sin_archivo_es_ausente_y_sin_datos_recientes_es_viejo(tmp_path):
    assert wa.leer(tmp_path / "no_esta.json", ahora=AHORA) == {"estado": "ausente", "datos": {}, "edad_s": 0, "motivo": ""}
    r = wa.leer(archivo(tmp_path, estado(ts=AHORA - 3 * 3600)), ahora=AHORA)
    assert r["estado"] == "viejo" and r["edad_s"] == 3 * 3600 and r["datos"]["smart"]


@pytest.mark.parametrize("contenido", ["no es json", "[]", "null", '{"version": 2, "ts": 1}', '{"version": 1}', '{"version": 1, "ts": "ayer"}',
                                       '{"version": 1, "ts": true}'])
def test_lo_que_no_es_un_estado_del_ayudante_es_invalido(tmp_path, contenido):
    r = wa.leer(archivo(tmp_path, contenido), ahora=AHORA)
    assert r["estado"] == "invalido" and r["datos"] == {} and r["motivo"]


def test_un_archivo_demasiado_grande_no_se_lee(tmp_path):
    p = archivo(tmp_path, json.dumps(estado(errores=["x" * 100] * 20)) + " " * (wa.MAX_BYTES + 1))
    assert wa.leer(p, ahora=AHORA)["estado"] == "invalido"


def test_solo_pasan_los_campos_conocidos_con_la_forma_esperada():
    sucio = estado(smart={"disk0": SMARTCTL, "../../etc/passwd": "x", "disk1": 5, "disk2": "x" * 200_001, "nvme0": "{}"},
                   fiabilidad=[{"Id": 0, "Temperatura": "caliente", "Desgaste": 4}, {"Id": "x"}, {"Id": 500}, "raro", {"Id": 1, "Horas": True}],
                   bitlocker=[{"Punto": "C:" * 50, "Estado": "X", "Comando": "calc.exe"}, "no"],
                   arranque_seguro="quien sabe", defender={"rutas": ["C:\\a", 5, None, "R" * 400], "extra": ["x"]},
                   wmi={"consumidores": [{"Name": "n", "Peligroso": "x"}, {}, 3]}, errores=["e"] * 30, extra="no")
    d = wa.validar(sucio)
    assert set(d["smart"]) == {"disk0", "nvme0"} and [f["Id"] for f in d["fiabilidad"]] == [0, 1]
    assert d["fiabilidad"][0]["Temperatura"] is None and d["fiabilidad"][1]["Horas"] is None          # un texto o un booleano no es un número
    assert len(d["bitlocker"]) == 1 and "Comando" not in d["bitlocker"][0] and len(d["bitlocker"][0]["Punto"]) == 40
    assert d["arranque_seguro"] == "no_soportado" and d["defender"]["rutas"] == ["C:\\a", "5", "R" * 260] and set(d["defender"]) == {"rutas", "extensiones", "procesos"}
    assert d["wmi"]["consumidores"] == [{"Name": "n"}] and len(d["errores"]) == 20 and "extra" not in d


def test_el_json_de_un_solo_elemento_que_serializa_powershell_tambien_se_entiende():
    # ConvertTo-Json de PowerShell 5.1 a veces convierte una lista de un elemento en un objeto suelto
    d = wa.validar(estado(fiabilidad={"Id": 0, "Temperatura": 30}, bitlocker={"Punto": "C:", "Estado": "FullyDecrypted", "Proteccion": "Off"}))
    assert len(d["fiabilidad"]) == 1 and len(d["bitlocker"]) == 1


# ---------- lecturas ----------

def por_nombre(ls):
    return {l["nombre"]: l for l in ls}


def test_el_smart_crudo_da_los_mismos_nombres_y_valores_que_en_linux_y_activa_las_mismas_reglas():
    r = por_nombre(wa.lecturas(wa.validar(estado())))
    assert r["disk1/smart_ok"]["valor"] == 1 and r["disk1/horas_encendido"]["valor"] == 21125
    assert (r["disk1/sectores_realocados"]["valor"], r["disk1/sectores_pendientes"]["valor"],
            r["disk1/sectores_incorregibles"]["valor"], r["disk1/errores_crc"]["valor"]) == (1, 1, 2, 10)
    reglas = {n: salud._regla_de(l)["id"] for n, l in r.items() if salud._regla_de(l)}
    assert reglas["disk1/sectores_pendientes"] == "smart_pendientes" and reglas["disk1/errores_crc"] == "smart_crc"


def test_los_contadores_de_fiabilidad_aportan_lo_que_el_smart_no_trae():
    r = por_nombre(wa.lecturas(wa.validar(estado())))
    assert r["disk0/temp"]["valor"] == 38 and r["disk0/desgaste_pct"]["valor"] == 4 and r["disk0/horas_encendido"]["valor"] == 1200
    d = estado(smart={"disk0": json.dumps({"power_on_time": {"hours": 999}, "nvme_smart_health_information_log": {"percentage_used": 7}})})
    r = por_nombre(wa.lecturas(wa.validar(d)))
    assert r["disk0/horas_encendido"]["valor"] == 999 and r["disk0/desgaste_pct"]["valor"] == 7       # manda el SMART
    d = estado(fiabilidad=[{"Id": 3, "Temperatura": 0, "Desgaste": 400, "Horas": 0}])
    assert not [l for l in wa.lecturas(wa.validar(d)) if l["nombre"].startswith("disk3/")]            # 0 °C o desgaste imposible: Windows no lo informa


def test_mezclar_el_ayudante_manda_sobre_lo_que_ya_habia():
    base = [{"categoria": "disco", "nombre": "disk1/smart_ok", "valor": 0, "unidad": "bool", "crit": None},
            {"categoria": "cpu", "nombre": "cpu0/Package", "valor": 50, "unidad": "°C", "crit": None}]
    r = por_nombre(wa.mezclar(base, ok()))
    assert r["disk1/smart_ok"]["valor"] == 1 and "cpu0/Package" in r and "disk1/errores_crc" in r


def test_si_lhm_ya_trae_la_temperatura_de_los_discos_no_se_duplica():
    lhm = [{"categoria": "disco", "nombre": "Samsung SSD 980/Temperature", "valor": 40, "unidad": "°C", "crit": None}]
    r = por_nombre(wa.mezclar(lhm, ok()))
    assert "disk0/temp" not in r and "disk0/desgaste_pct" not in r and "disk1/errores_crc" in r


def test_un_ayudante_viejo_o_ausente_no_agrega_nada():
    base = [{"categoria": "disco", "nombre": "x", "valor": 1, "unidad": "n", "crit": None}]
    for e in ({"estado": "viejo", "datos": wa.validar(estado()), "edad_s": 99999, "motivo": ""}, {"estado": "ausente", "datos": {}, "edad_s": 0, "motivo": ""}):
        assert wa.mezclar(base, e) == base and wa.hallazgos_postura(e) == [] and wa.consumidores_wmi(e) == []


# ---------- hallazgos ----------

def reglas(estado_):
    return {h["regla"]: h["severidad"] for h in wa.hallazgos_postura(estado_)}


def test_un_equipo_normal_no_tiene_hallazgos():
    assert reglas(ok()) == {}


def test_bitlocker_secure_boot():
    r = reglas(ok(bitlocker=[{"Punto": "C:", "Estado": "FullyEncrypted", "Proteccion": "Off"}, {"Punto": "D:", "Estado": "FullyDecrypted", "Proteccion": "Off"}],
                  arranque_seguro="desactivado"))
    assert r == {"bitlocker_suspendido": "media", "bitlocker_sin_cifrar": "baja", "secure_boot_desactivado": "media"}
    assert reglas(ok(arranque_seguro="no_soportado")) == {"secure_boot_no_disponible": "baja"}


@pytest.mark.parametrize("tipo,valor,riesgosa", [
    ("ruta", "C:\\Users\\v\\AppData\\Local\\Temp", True), ("ruta", "C:\\Users\\v\\Downloads\\x", True), ("ruta", "C:\\", True), ("ruta", "*", True),
    ("ruta", "C:\\Windows\\Temp", True), ("ruta", "D:\\Juegos\\Steam", False), ("ruta", "C:\\proyectos\\app", False),
    ("proceso", "C:\\Users\\v\\AppData\\Roaming\\x.exe", True), ("proceso", "steam.exe", False),
    ("extensión", ".exe", True), ("extensión", "ps1", True), ("extensión", "*", True), ("extensión", ".log", False)])
def test_que_exclusiones_de_defender_son_riesgosas(tipo, valor, riesgosa):
    assert wa.exclusion_riesgosa(tipo, valor) is riesgosa


def test_las_exclusiones_riesgosas_son_altas_y_las_comunes_una_sola_nota_informativa():
    d = {"rutas": ["C:\\Users\\v\\AppData\\Local\\Temp", "D:\\Juegos", "E:\\datos"], "extensiones": [".exe", ".log"], "procesos": []}
    h = wa.hallazgos_postura(ok(defender=d))
    assert sorted((x["regla"], x["severidad"]) for x in h) == [("defender_exclusion_riesgosa", "alta")] * 2 + [("defender_exclusiones", "baja")]
    assert "3 exclusión" in [x["detalle"] for x in h if x["regla"] == "defender_exclusiones"][0]
    assert all(x["categoria"] == "postura" for x in h)


def test_las_suscripciones_wmi_del_ayudante_tienen_el_formato_de_la_persistencia():
    cons = [{"Name": "evil", "CommandLineTemplate": "powershell -enc AAAA"}, {"Name": "SCM Event Log Consumer"}]
    items = ws.items_persistencia({"wmi": {"consumidores": wa.consumidores_wmi(ok(wmi={"consumidores": cons}))}}, {})
    assert [i["nombre"] for i in items] == ["evil"]               # el de fábrica de Windows se descarta como en la fase 2


def test_los_avisos_dicen_que_falta():
    assert "no está instalado" in wa.avisos({"estado": "ausente"})[0]
    assert "3 h" in wa.avisos({"estado": "viejo", "edad_s": 3 * 3600 + 5})[0]
    assert wa.avisos({"estado": "invalido", "motivo": "estado.json no es JSON"}) == ["Ayudante con privilegios: estado.json no es JSON"]
    assert wa.avisos(ok(errores=["bitlocker: acceso denegado"])) == ["El ayudante no pudo leer: bitlocker: acceso denegado"] and wa.avisos(ok()) == []


# ---------- integración con la plataforma ----------

@pytest.fixture
def en_windows(monkeypatch):
    plataforma.forzar("windows")
    windows._cache.clear()
    wl._cache.clear()
    monkeypatch.setattr(windows, "_json_ps", lambda *a, **k: None)
    monkeypatch.setattr(windows, "_powershell", lambda *a, **k: None)
    monkeypatch.setattr(windows, "_registro", lambda *a, **k: None)
    monkeypatch.setattr(windows, "_particiones", lambda: [])
    yield monkeypatch
    plataforma.forzar(None)
    windows._cache.clear()
    wl._cache.clear()


def test_las_lecturas_de_windows_incluyen_las_del_ayudante_y_el_aviso_desaparece(en_windows):
    en_windows.setattr(wa, "RUTA_ESTADO", None)
    en_windows.setattr(wa, "leer", lambda *a, **k: ok(ts=int(time.time())))
    nombres = {l["nombre"] for l in windows.leer_sensores()}
    assert {"disk1/sectores_realocados", "disk1/errores_crc", "disk0/temp"} <= nombres
    avisos = " | ".join(windows.no_disponible(windows.leer_sensores()))
    assert "SMART detallado" not in avisos and "no está instalado" not in avisos


def test_sin_ayudante_el_aviso_dice_como_instalarlo(en_windows, tmp_path):
    en_windows.setattr(wa, "RUTA_ESTADO", tmp_path / "no_esta.json")
    windows.leer_sensores()
    assert any("habilitar-sensores.ps1" in a for a in windows.no_disponible([]))


def test_la_persistencia_usa_las_suscripciones_wmi_del_ayudante_cuando_las_propias_piden_administrador(en_windows):
    en_windows.setattr(wl, "_ps", lambda *a, **k: {"wmi_sin_acceso": True})
    en_windows.setattr(wl, "_registro", lambda *a: None)
    en_windows.setattr(wl, "_valores_registro", lambda *a: {})
    en_windows.setattr(wa, "leer", lambda *a, **k: ok(wmi={"consumidores": [{"Name": "evil", "CommandLineTemplate": "powershell -w hidden"}]}))
    items = wl.persistencia_items()
    assert [i["nombre"] for i in items if i["tipo"] == "wmi"] == ["evil"] and wl.avisos_no_disponible() == []     # ya no está "sin acceso"
    wl._cache.clear()
    en_windows.setattr(wa, "leer", lambda *a, **k: {"estado": "ausente", "datos": {}, "edad_s": 0, "motivo": ""})
    windows._cache.clear()
    wl.persistencia_items()
    assert "WMI" in wl.avisos_no_disponible()[0]


def test_la_postura_diaria_suma_los_hallazgos_del_ayudante(en_windows):
    en_windows.setattr(windows, "_datos_hardware", lambda: {"so": [{"BuildNumber": "26200", "Caption": "Windows 11 Pro"}]})
    en_windows.setattr(wl, "datos_postura", lambda: {})
    en_windows.setattr(wl, "winget_upgrade", lambda: [])
    en_windows.setattr(wa, "leer", lambda *a, **k: ok(arranque_seguro="desactivado"))
    assert "secure_boot_desactivado" in {h["regla"] for h in wl.revisar_postura()}

"""Hardware, sistema operativo, programas y eventos de Windows con salidas simuladas de CIM, del registro y de winget."""

import pytest

import salud
from plataforma import windows_sistema as wsi

HW = {
    "cpu": {"Name": "AMD Ryzen 7 5800X 8-Core Processor      ", "Manufacturer": "AuthenticAMD", "NumberOfCores": 8, "NumberOfLogicalProcessors": 16, "MaxClockSpeed": 3801},
    "gpu": [{"Name": "NVIDIA GeForce RTX 3070", "PNPDeviceID": r"PCI\VEN_10DE&DEV_2484&SUBSYS_1", "DriverVersion": "31.0.15.5123", "DriverDate": "2024-05-01"},
            {"Name": "Microsoft Remote Display Adapter", "PNPDeviceID": r"ROOT\BASICDISPLAY\0000", "DriverVersion": "10.0.1"},
            {"Name": "AMD Radeon(TM) Graphics", "PNPDeviceID": r"PCI\VEN_1002&DEV_1638&SUBSYS_2", "DriverVersion": "31.0.21001.1", "DriverDate": "2024-03-02"}],
    "ram": [{"Manufacturer": "Corsair ", "Capacity": 17179869184, "ConfiguredClockSpeed": 3200, "Speed": 3200}, {"Manufacturer": "Corsair", "Capacity": 17179869184, "Speed": 3600}],
    "discos": [{"Model": "Samsung SSD 980 PRO 1TB", "Size": 1000204886016, "Index": 0, "MediaType": "Fixed hard disk media"},
               {"Model": "WDC WD20EZRZ", "Size": 2000398934016, "Index": 1, "MediaType": "Fixed hard disk media"},
               {"Model": "Kingston DataTraveler", "Size": 32000000000, "Index": 2, "MediaType": "Removable Media"}],
    "discos_fisicos": [{"DeviceId": "0", "MediaType": 4, "BusType": 17}, {"DeviceId": "1", "MediaType": 3, "BusType": 11}],
    "placa": {"Manufacturer": "ASUSTeK COMPUTER INC.", "Product": "ROG STRIX B550-F GAMING"},
    "bios": {"SMBIOSBIOSVersion": "3607"}, "equipo": {"Model": "System Product Name"},
    "so": {"Caption": "Microsoft Windows 11 Pro", "Version": "10.0.22631", "BuildNumber": "22631", "OSArchitecture": "64-bit"},
}


def filas(d=HW, nvidia=None):
    return wsi.filas_hardware(d, 8, 16, 32 * 2**30, 4 * 2**30, nvidia)


def test_el_hardware_tiene_las_mismas_filas_que_en_linux():
    f = filas()
    assert [x[0] for x in f] == ["cpu", "gpu", "gpu", "ram", "disco", "disco", "mother"]   # el adaptador virtual y el pendrive no cuentan
    cpu = f[0]
    assert cpu[1] == "AMD" and cpu[2] == "AMD Ryzen 7 5800X 8-Core Processor" and cpu[3]["nucleos_fisicos"] == 8 and cpu[3]["hilos"] == 16


def test_la_gpu_se_identifica_por_el_id_pci_como_en_linux():
    nvidia, amd = filas()[1], filas()[2]
    assert nvidia[1] == "NVIDIA" and nvidia[3]["id_pci"] == "10de:2484" and nvidia[3]["version_driver"] == "31.0.15.5123"
    assert amd[1] == "AMD" and amd[3]["id_pci"] == "1002:1638"
    assert filas(nvidia="551.23\n")[1][3]["version_driver"] == "551.23" and filas(nvidia="551.23")[2][3]["version_driver"] == "31.0.21001.1"


def test_ram_discos_y_placa():
    f = filas()
    ram = f[3][3]
    assert ram["total_gb"] == 32.0 and ram["swap_gb"] == 4.0 and [m["gb"] for m in ram["modulos"]] == [16.0, 16.0]
    assert f[4][2] == "Samsung SSD 980 PRO 1TB" and f[4][3]["tipo"] == "SSD" and f[4][3]["bus"] == "NVMe" and f[4][3]["dev"] == "disk0"
    assert f[5][3]["tipo"] == "HDD" and f[5][3]["tamano"] == "1863.0G"
    assert f[6][1:3] == ("ASUSTeK COMPUTER INC.", "ROG STRIX B550-F GAMING") and f[6][3] == {"bios": "3607", "producto": "System Product Name"}


def test_el_hardware_funciona_aunque_cim_no_devuelva_nada():
    f = wsi.filas_hardware({}, None, None, 2**30, 0)
    assert [x[0] for x in f] == ["cpu", "ram", "mother"]


def test_una_lista_de_un_solo_elemento_se_trata_como_lista():
    # PowerShell serializa @(x) con un solo elemento como objeto suelto
    d = {**HW, "gpu": HW["gpu"][0], "discos": HW["discos"][0], "ram": HW["ram"][0]}
    assert [x[0] for x in filas(d)] == ["cpu", "gpu", "ram", "disco", "mother"]


def test_nombre_y_version_del_sistema():
    assert wsi.nombre_so(HW, "23H2", 4460) == "Windows 11 Pro 23H2 (build 22631.4460)"
    assert wsi.nombre_so(HW) == "Windows 11 Pro (build 22631)" and wsi.nombre_so({}) == ""
    assert wsi.version_so(HW) == "10.0.22631"


# ---------- programas ----------

def test_los_programas_del_registro_sin_parches_ni_componentes_ni_duplicados():
    e = [{"DisplayName": "Mozilla Firefox", "DisplayVersion": "126.0"}, {"DisplayName": "Mozilla Firefox", "DisplayVersion": "126.0"},
         {"DisplayName": "Microsoft Visual C++ 2015-2022 Redistributable (x64)", "DisplayVersion": "14.38"},
         {"DisplayName": "Driver interno", "SystemComponent": 1}, {"DisplayName": "Hotfix X", "ParentKeyName": "OperatingSystem"},
         {"DisplayName": "Update for Windows (KB5034)", "DisplayVersion": "1"}, {"DisplayName": "KB5034441"},
         {"DisplayName": "Parche", "ReleaseType": "Security Update"}, {"DisplayName": ""}, {"DisplayVersion": "1"}]
    assert wsi.paquetes_registro(e) == [("Microsoft Visual C++ 2015-2022 Redistributable (x64)", "14.38", "registro"), ("Mozilla Firefox", "126.0", "registro")]


WINGET = """\
   -
Name                          Id                           Version      Available    Source
------------------------------------------------------------------------------------------
Mozilla Firefox (x64 es-AR)   Mozilla.Firefox              126.0        127.0        winget
Microsoft Teams               MSTeams_8wekyb3d8bbwe        24004.1307                msstore
Programa viejo                                             1.0
Steam                         Valve.Steam                  2.10.91.91                winget
"""


def test_winget_aporta_solo_lo_que_tiene_fuente_y_con_su_id():
    assert wsi.paquetes_winget(WINGET) == [("MSTeams_8wekyb3d8bbwe", "24004.1307", "winget"),
                                           ("Mozilla.Firefox", "126.0", "winget"), ("Valve.Steam", "2.10.91.91", "winget")]


def test_winget_con_salida_vacia_o_irreconocible_no_rompe():
    assert wsi.paquetes_winget(None) == [] and wsi.paquetes_winget("") == [] and wsi.paquetes_winget("sin tabla\nni columnas") == []


# ---------- eventos ----------

E = [{"ts": 300, "proveedor": "Microsoft-Windows-Kernel-Power", "id": 41, "nivel": 1, "mensaje": "El sistema se reinició sin antes apagarse correctamente."},
     {"ts": 100, "proveedor": "disk", "id": 51, "nivel": 2, "mensaje": r"Se detectó un error durante una operación de paginación en \Device\Harddisk0\DR0."},
     {"ts": 200, "proveedor": "Microsoft-Windows-DistributedCOM", "id": 10016, "nivel": 2, "mensaje": "ruido conocido"},
     {"ts": 250, "proveedor": "nvlddmkm", "id": 14, "nivel": 3, "mensaje": "driver"},
     {"ts": 260, "proveedor": "algo", "id": "x", "nivel": 2}]


def test_los_eventos_quedan_ordenados_con_su_id_y_sin_el_ruido_conocido():
    r = wsi.interpretar_eventos(E, 50)
    assert [x[:3] for x in r] == [(100, "disk", "err"), (250, "nvlddmkm", "warn"), (300, "Microsoft-Windows-Kernel-Power", "crit")]
    assert r[0][3].startswith("[51 err] Se detectó un error")
    assert wsi.interpretar_eventos(E, 2)[0][0] == 250 and wsi.interpretar_eventos(None, 5) == []   # con tope se quedan los más nuevos


def coincide(origen, mensaje):
    t = f"{origen}: {mensaje}"
    return {tipo for tipo, *_, rx in wsi.PATRONES_EVENTO if rx.search(t)}


@pytest.mark.parametrize("origen,mensaje,esperado", [
    ("disk", "[7 err] bloque defectuoso", {"disco_io"}), ("Ntfs", "[55 err] estructura dañada", {"disco_io"}),
    ("stornvme", "[129 warn] reinicio del dispositivo", {"disco_io"}), ("volmgr", "[46 err] x", {"disco_io"}),
    ("disk", "[157 warn] El disco se quitó inesperadamente", set()),                 # un pendrive sacado no es un fallo
    ("nvlddmkm", "[13 err] Graphics SM Warp Exception", {"gpu_fallo"}), ("Display", "[4101 warn] El controlador dejó de responder", {"gpu_fallo"}),
    ("amdkmdag", "[0 err] x", {"gpu_fallo"}), ("Display", "[4102 warn] otro", set()),
    ("Microsoft-Windows-Resource-Exhaustion-Detector", "[2004 warn] poca memoria virtual", {"memoria"}),
    ("Microsoft-Windows-WHEA-Logger", "[18 crit] Error de hardware fatal", {"hardware"}),
    ("Microsoft-Windows-Kernel-Processor-Power", "[37 warn] velocidad limitada por el firmware", {"termico"}),
    ("Microsoft-Windows-Kernel-Processor-Power", "[26 warn] otro", set()),
    ("Microsoft-Windows-Kernel-Power", "[41 crit] reinicio sin apagado", {"apagado_inesperado"}),
    ("Microsoft-Windows-Kernel-Power", "[109 warn] otro", set()),
    ("Service Control Manager", "[7000 err] un servicio no inició", set()), ("Schannel", "[36874 err] TLS", set()),
])
def test_los_patrones_de_windows_reconocen_lo_grave_y_no_lo_normal(origen, mensaje, esperado):
    assert coincide(origen, mensaje) == esperado


def test_los_patrones_de_windows_usan_las_categorias_que_entienden_las_alertas():
    for tipo, cat, sev, texto, _ in wsi.PATRONES_EVENTO:
        assert cat in {"cpu", "gpu", "disco", "memoria", "placa"} and sev in ("aviso", "critico") and texto
    assert {t for t, *_ in wsi.PATRONES_EVENTO} >= {t for t, *_ in salud.PATRONES_EVENTO if t in ("disco_io", "gpu_fallo", "memoria", "termico")}


def test_el_script_de_eventos_lleva_el_tramo_y_el_tope_como_numeros():
    s = wsi.script_eventos(1700000000, 200)
    assert "FromUnixTimeSeconds(1700000000)" in s and "-MaxEvents 200" in s and "LogName='System'" in s and "Level=1,2,3" in s


def test_las_limitaciones_de_windows_dicen_lo_que_no_se_mide():
    temas = {l["tema"] for l in wsi.LIMITACIONES}
    assert {"Temperaturas, ventiladores y voltajes", "SMART de los discos", "Carga del sistema", "Antigüedad de archivos en la cuarentena"} <= temas
    assert all({"tema", "que", "por_que"} <= set(l) for l in wsi.LIMITACIONES)

"""Sensores de Windows con salidas simuladas de LibreHardwareMonitor y CIM: mismos nombres, categorías y unidades que en Linux."""

import pytest

import salud
from plataforma import windows_sensores as ws


def hw(ident, tipo, nombre):
    return {"Identifier": ident, "HardwareType": tipo, "Name": nombre, "Parent": None}


def s(parent, nombre, tipo, valor):
    return {"Identifier": f"{parent}/{tipo.lower()}/{nombre}", "Name": nombre, "SensorType": tipo, "Value": valor, "Parent": parent}


LHM = {"espacio": "root/LibreHardwareMonitor",
       "hardware": [hw("/amdcpu/0", "Cpu", "AMD Ryzen 7 5800X"), hw("/gpu-nvidia/0", "GpuNvidia", "NVIDIA GeForce RTX 3070"),
                    hw("/nvme/0", "Storage", "Samsung SSD 980 PRO 1TB"), hw("/lpc/nct6798d", "SuperIO", "Nuvoton NCT6798D"),
                    hw("/ram", "Memory", "Total Memory")],
       "sensores": [
           s("/amdcpu/0", "Core (Tctl/Tdie)", "Temperature", 71.5), s("/amdcpu/0", "CCD1 (Tdie)", "Temperature", 66.0),
           s("/amdcpu/0", "Core #1", "Temperature", 60.0), s("/amdcpu/0", "Core #1 Distance to TjMax", "Temperature", 29.0),
           s("/amdcpu/0", "Core #1 VID", "Voltage", 1.2), s("/amdcpu/0", "Package", "Power", 88.0), s("/amdcpu/0", "Core #1", "Power", 5.0),
           s("/gpu-nvidia/0", "GPU Core", "Temperature", 64.0), s("/gpu-nvidia/0", "GPU Hot Spot", "Temperature", 78.0),
           s("/gpu-nvidia/0", "GPU Core", "Load", 97.0), s("/gpu-nvidia/0", "GPU Memory", "Load", 40.0),
           s("/gpu-nvidia/0", "GPU Memory Used", "SmallData", 4096.0), s("/gpu-nvidia/0", "GPU Memory Total", "SmallData", 8192.0),
           s("/gpu-nvidia/0", "GPU Package", "Power", 210.0), s("/gpu-nvidia/0", "GPU Fan", "Fan", 1450.0),
           s("/gpu-nvidia/0", "GPU Core", "Voltage", 0.95),
           s("/nvme/0", "Temperature", "Temperature", 47.0), s("/nvme/0", "Remaining Life", "Level", 97.0),
           s("/nvme/0", "Available Spare", "Level", 100.0), s("/nvme/0", "Used Space", "Load", 33.0),
           s("/lpc/nct6798d", "CPU Fan", "Fan", 0.0), s("/lpc/nct6798d", "System Fan #2", "Fan", 1210.0),
           s("/lpc/nct6798d", "+12V", "Voltage", 12.096), s("/lpc/nct6798d", "Vcore", "Voltage", 1.1),
           s("/lpc/nct6798d", "CPUTIN", "Temperature", 45.0), s("/lpc/nct6798d", "AUXTIN0", "Temperature", 84.0),
           s("/lpc/nct6798d", "Temperature #3", "Temperature", -128.0), s("/lpc/nct6798d", "Temperature #4", "Temperature", None),
           s("/ram", "Memory", "Load", 38.0)]}


def por_nombre(lecturas):
    return {l["nombre"]: l for l in lecturas}


def test_lhm_usa_los_mismos_nombres_y_categorias_que_linux():
    res, info = ws.lecturas_lhm(LHM)
    r = por_nombre(res)
    assert r["cpu0/Core (Tctl/Tdie)"] | {"valor": 71.5} == r["cpu0/Core (Tctl/Tdie)"] and r["cpu0/Core (Tctl/Tdie)"]["categoria"] == "cpu"
    assert r["gpu0/GPU Hot Spot"]["categoria"] == "gpu" and r["gpu0/uso"]["valor"] == 97.0 and r["gpu0/vram_pct"]["valor"] == 50.0
    assert r["Samsung SSD 980 PRO 1TB/Temperature"]["categoria"] == "disco" and r["Samsung SSD 980 PRO 1TB/desgaste_pct"]["valor"] == 3.0
    assert r["Samsung SSD 980 PRO 1TB/spare_pct"]["valor"] == 100.0
    assert r["Nuvoton NCT6798D/System Fan #2"] | {"unidad": "RPM"} == r["Nuvoton NCT6798D/System Fan #2"]
    assert r["Nuvoton NCT6798D/+12V"]["valor"] == pytest.approx(12096.0) and r["Nuvoton NCT6798D/+12V"]["unidad"] == "mV"
    assert r["Nuvoton NCT6798D/+12V/desviacion_pct"]["valor"] == pytest.approx(0.8, abs=0.01)
    assert info == {"nvidia": True, "gpu_uso": True, "disco": True}


def test_lhm_descarta_lo_que_no_es_una_lectura_real():
    nombres = set(por_nombre(ws.lecturas_lhm(LHM)[0]))
    assert "cpu0/Core #1 Distance to TjMax" not in nombres and "cpu0/Core #1 VID" not in nombres   # distancia y VID no son temperatura ni voltaje
    assert "cpu0/Core #1" not in nombres and "cpu0/Core #1/..." not in nombres    # con un resumen (Tctl, CCD) no hace falta cada núcleo
    assert "Nuvoton NCT6798D/AUXTIN0" not in nombres                               # termistor sin conectar (84 °C falsos)
    assert "Nuvoton NCT6798D/Temperature #3" not in nombres and "Nuvoton NCT6798D/Temperature #4" not in nombres   # -128 °C y sin valor
    assert "gpu0/GPU Memory" not in nombres and "Total Memory/Memory" not in nombres
    assert "cpu0/Vcore" not in nombres and not any("Voltage" in n for n in nombres)


def test_lhm_sin_resumen_de_cpu_se_quedan_todos_los_nucleos():
    lhm = {"hardware": [hw("/cpu", "Cpu", "Intel")], "sensores": [s("/cpu", "Core #1", "Temperature", 50.0), s("/cpu", "Core #2", "Temperature", 52.0)]}
    assert set(por_nombre(ws.lecturas_lhm(lhm)[0])) == {"cpu0/Core #1", "cpu0/Core #2"}


def test_los_nombres_de_lhm_activan_las_mismas_reglas_de_salud():
    res, _ = ws.lecturas_lhm(LHM)
    reglas = {l["nombre"]: (salud._regla_de(l) or {}).get("id") for l in res}
    assert reglas["cpu0/Core (Tctl/Tdie)"] == "temp_cpu" and reglas["gpu0/GPU Hot Spot"] == "temp_gpu" and reglas["gpu0/uso"] == "gpu_uso"
    assert reglas["gpu0/vram_pct"] == "gpu_vram" and reglas["Samsung SSD 980 PRO 1TB/Temperature"] == "temp_disco"
    assert reglas["Samsung SSD 980 PRO 1TB/desgaste_pct"] == "smart_desgaste" and reglas["Nuvoton NCT6798D/CPUTIN"] == "temp_placa"
    assert reglas["Nuvoton NCT6798D/+12V/desviacion_pct"] == "riel" and reglas["gpu0/GPU Core"] == "gpu_voltaje"


def test_sin_lhm_no_hay_lecturas_de_lhm():
    assert ws.lecturas_lhm(None) == ([], {"nvidia": False, "gpu_uso": False, "disco": False})


# ---------- GPU por contadores ----------

MOTORES = [{"Name": "pid_100_luid_0x00000000_0x0000AAAA_phys_0_eng_0_engtype_3D", "UtilizationPercentage": 30},
           {"Name": "pid_200_luid_0x00000000_0x0000AAAA_phys_0_eng_0_engtype_3D", "UtilizationPercentage": 25},
           {"Name": "pid_200_luid_0x00000000_0x0000AAAA_phys_0_eng_1_engtype_Copy", "UtilizationPercentage": 5},
           {"Name": "pid_200_luid_0x00000000_0x0000BBBB_phys_0_eng_0_engtype_VideoDecode", "UtilizationPercentage": 12},
           {"Name": "algo raro", "UtilizationPercentage": 99}]


def test_el_uso_de_la_gpu_se_calcula_como_el_administrador_de_tareas():
    assert ws.uso_gpu_por_adaptador(MOTORES) == {"0x00000000_0x0000AAAA": 55.0, "0x00000000_0x0000BBBB": 12.0}
    assert ws.uso_gpu_por_proceso(MOTORES) == {100: 30.0, 200: 25.0}   # por proceso: el motor más ocupado de ese proceso


def test_los_motores_de_gpu_se_usan_solo_si_nadie_mas_trae_el_uso():
    datos = {"motores_gpu": MOTORES}
    assert por_nombre(ws.construir(datos, [], hay_nvidia_smi=False)[0])["gpu0/uso"]["valor"] == 55.0
    assert "gpu0/uso" not in por_nombre(ws.construir(datos, [], hay_nvidia_smi=True)[0])      # nvidia-smi ya lo trae: no se duplica la alerta
    con_lhm = {"motores_gpu": MOTORES, "lhm": LHM}
    assert "gpu1/uso" not in por_nombre(ws.construir(con_lhm, [], hay_nvidia_smi=False)[0])


# ---------- discos, particiones y zonas térmicas ----------

DISCOS = {"disco_perf": [{"Name": "0 C:", "PercentDiskTime": 140, "DiskReadBytesPersec": 5_000_000, "DiskWriteBytesPersec": 1_000_000}],
          "discos": [{"DeviceId": "0", "HealthStatus": 0}, {"DeviceId": "1", "HealthStatus": 2}, {"DeviceId": "2", "HealthStatus": 1}],
          "fiabilidad": [{"DeviceId": "0", "Temperature": 38, "Wear": 4, "PowerOnHours": 1200}, {"DeviceId": "1", "Temperature": 0, "Wear": None, "PowerOnHours": 0}]}


def test_discos_sin_administrador_estado_io_y_lo_que_windows_entregue():
    r = por_nombre(ws.lecturas_discos(DISCOS, con_lhm_disco=False))
    assert r["disk0/io_util_pct"]["valor"] == 100.0 and r["disk0/lectura_mbs"]["valor"] == 5.0 and r["disk0/escritura_mbs"]["valor"] == 1.0
    assert r["disk0/smart_ok"]["valor"] == 1 and r["disk1/smart_ok"]["valor"] == 0
    assert "disk2/smart_ok" not in r                                   # "con advertencia" no es ni sano ni roto: no se inventa
    assert r["disk0/temp"]["valor"] == 38 and r["disk0/desgaste_pct"]["valor"] == 4 and r["disk0/horas_encendido"]["valor"] == 1200
    assert "disk1/temp" not in r and "disk1/desgaste_pct" not in r and "disk1/horas_encendido" not in r   # 0 °C = el disco no lo informa


def test_si_lhm_ya_trae_temperatura_y_desgaste_no_se_duplican():
    r = por_nombre(ws.lecturas_discos(DISCOS, con_lhm_disco=True))
    assert "disk0/temp" not in r and "disk0/desgaste_pct" not in r and "disk0/horas_encendido" in r


def test_particiones_solo_las_reales_con_los_nombres_que_usan_las_reglas():
    parts = [{"punto": "C:\\", "fs": "NTFS", "opciones": "rw,fixed", "libre_pct": 42.0},
             {"punto": "D:\\", "fs": "exFAT", "opciones": "ro,removable", "libre_pct": 90.0},
             {"punto": "E:\\", "fs": "CDFS", "opciones": "ro,cdrom", "libre_pct": 0.0}]
    r = por_nombre(ws.lecturas_particiones(parts))
    assert set(r) == {"fs:C:/libre_pct", "fs:C:/solo_lectura", "fs:D:/libre_pct", "fs:D:/solo_lectura"}
    assert r["fs:C:/solo_lectura"]["valor"] == 0 and r["fs:D:/solo_lectura"]["valor"] == 1
    assert salud._regla_de(r["fs:C:/libre_pct"])["id"] == "disco_libre"


def test_zonas_termicas_acpi_en_kelvin_y_solo_las_plausibles():
    r = ws.lecturas_zonas([{"Name": r"\_TZ.TZ00", "Temperature": 318.15}, {"Name": "cero", "Temperature": 0}, {"Name": "x", "Temperature": None}])
    assert [(l["nombre"], l["categoria"], l["valor"]) for l in r] == [("acpi/_TZ.TZ00", "placa", 45.0)]


# ---------- todo junto ----------

def test_construir_sin_nada_no_inventa_ni_rompe():
    assert ws.construir({}, [], False)[0] == [] and ws.construir(None, [], False)[1]["lhm"] is False


def test_las_zonas_acpi_solo_van_sin_lhm():
    zonas = {"zonas": [{"Name": "TZ", "Temperature": 320.0}]}
    assert "acpi/TZ" in por_nombre(ws.construir(zonas, [], False)[0])
    assert "acpi/TZ" not in por_nombre(ws.construir({**zonas, "lhm": LHM}, [], False)[0])


def test_la_temperatura_de_la_cpu_prefiere_el_paquete_y_sin_sensor_es_none():
    lecturas, _ = ws.lecturas_lhm(LHM)
    assert ws.temperatura_cpu(lecturas) == 71.5 and ws.temperatura_cpu([]) is None
    assert ws.temperatura_cpu(ws.construir({"zonas": [{"Name": "TZ", "Temperature": 330.0}]}, [], False)[0]) is None  # la ACPI no es la CPU


def test_no_disponible_dice_que_falta_en_vez_de_inventar():
    sin, meta_sin = ws.construir({}, [], False)
    textos = " | ".join(ws.no_disponible(sin, meta_sin))
    assert "LibreHardwareMonitor" in textos and "Estado de los discos" in textos and "Uso de la GPU" in textos and "VRAM" in textos
    con, meta_con = ws.construir({"lhm": LHM, **DISCOS}, [], False)
    textos = " | ".join(ws.no_disponible(con, meta_con))
    assert "Temperaturas" not in textos and "VRAM" not in textos and "SMART detallado" in textos

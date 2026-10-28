"""Ayudas compartidas por las pruebas (se importan con `import ayudas`)."""

import json
import os
import time
from pathlib import Path

FALSOS = Path(__file__).resolve().parent / "falsos"


def L(nombre, valor, cat="cpu", unidad="°C", crit=None):
    """Una lectura de sensor con la forma que produce salud.leer_lecturas()."""
    return {"categoria": cat, "nombre": nombre, "valor": valor, "unidad": unidad, "crit": crit}


def lecturas_vivas(**cambios) -> list[dict]:
    """Lecturas sintéticas con los nombres de sensores reales de la PC de desarrollo, para no depender del hardware."""
    base = {
        "cpu/uso": L("cpu/uso", 4.0, "cpu", "%"), "k10temp/Tctl": L("k10temp/Tctl", 50.0), "k10temp/Tccd1": L("k10temp/Tccd1", 46.0),
        "amdgpu/uso": L("amdgpu/uso", 3.0, "gpu", "%"), "amdgpu/junction": L("amdgpu/junction", 46.0, "gpu", crit=110.0),
        "amdgpu/edge": L("amdgpu/edge", 42.0, "gpu", crit=100.0), "amdgpu/fan1": L("amdgpu/fan1", 0.0, "gpu", "RPM"),
        "memoria/ram_pct": L("memoria/ram_pct", 31.0, "memoria", "%"), "fs:/home/libre_pct": L("fs:/home/libre_pct", 65.0, "disco", "%"),
        "nvme/Composite": L("nvme/Composite", 41.0, "disco", crit=87.8), "sda/smart_ok": L("sda/smart_ok", 1.0, "disco", "bool"),
        "nct6798/fan2": L("nct6798/fan2", 1500.0, "placa", "RPM"), "nct6798/in0": L("nct6798/in0", 576.0, "placa", "mV"),
        "nct6798/TSI0_TEMP": L("nct6798/TSI0_TEMP", 55.0, "placa"), "drivetemp_sda/temp1": L("drivetemp_sda/temp1", 29.0, "disco"),
        "drivetemp_sdb/temp1": L("drivetemp_sdb/temp1", 33.0, "disco"), "sdb/smart_ok": L("sdb/smart_ok", 1.0, "disco", "bool"),
    }
    for k, v in cambios.items():
        base[k.replace("__", "/")] = {**base.get(k.replace("__", "/"), L(k, 0)), "valor": v}
    return list(base.values())


def leer_registro(ruta: str | Path | None = None) -> list[dict]:
    """Lo que pidieron los comandos falsos (notify-send, xdg-open, systemd-run...), en orden."""
    ruta = Path(ruta or os.environ["FAKE_LOG"])
    return [json.loads(l) for l in ruta.read_text().splitlines()] if ruta.exists() else []


def comandos(nombre: str) -> list[dict]:
    return [x for x in leer_registro() if x["cmd"] == nombre]


def esperar(condicion, segundos: float = 6.0) -> bool:
    """Espera a que algo ocurra en otro proceso (los comandos falsos corren en segundo plano)."""
    fin = time.time() + segundos
    while time.time() < fin:
        if condicion():
            return True
        time.sleep(0.05)
    return False


def matar_servidores_falsos():
    """Cierra los servidores falsos y espera a que el puerto quede libre (si no, el siguiente arranque choca con el que se está muriendo)."""
    import psutil
    import dashboard
    for p in psutil.process_iter(["cmdline"]):
        if any("servidor_falso.py" in (x or "") for x in (p.info["cmdline"] or [])):
            p.kill()
            try:
                p.wait(3)
            except psutil.Error:
                pass
    esperar(lambda: not dashboard.activo(), 3)

"""Capa de plataforma: los dos backends ofrecen lo mismo, Linux delega en el código de siempre y Windows se conecta con el resto
del programa (eventos, rutas, cuarentena) usando salidas simuladas de PowerShell. Corre en Linux."""

import json
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

import collector
import db
import plataforma
import salud
from plataforma import linux, windows


@pytest.fixture
def en_windows(monkeypatch):
    """Usa el backend de Windows con PowerShell, registro y particiones falsos (nada toca el sistema)."""
    plataforma.forzar("windows")
    windows._cache.clear()
    monkeypatch.setattr(windows, "_powershell", lambda *a, **k: None)
    monkeypatch.setattr(windows, "_registro", lambda *a, **k: None)
    monkeypatch.setattr(windows, "_particiones", lambda: [])
    yield windows
    plataforma.forzar(None)
    windows._cache.clear()


def test_los_dos_backends_ofrecen_toda_la_interfaz():
    assert [n for n in plataforma.INTERFAZ if not hasattr(linux, n)] == []
    assert [n for n in plataforma.INTERFAZ if not hasattr(windows, n)] == []


def test_windows_se_puede_importar_en_linux_sin_tocar_winreg_ni_windll():
    import importlib
    importlib.reload(windows)  # no levanta ImportError ni AttributeError al cargarse
    assert windows.NOMBRE == "windows"


def test_en_este_sistema_el_backend_es_el_de_su_plataforma():
    assert plataforma.actual().NOMBRE == plataforma.NOMBRE == ("windows" if plataforma.ES_WINDOWS else "linux")


# ---------- Linux: nada cambia ----------

def test_linux_deja_las_rutas_y_la_antiguedad_de_siempre():
    assert linux.dir_datos() == Path.home() / ".local" / "share" / "pc-doctor"
    assert linux.fecha_archivo(SimpleNamespace(st_mtime=10.0, st_ctime=30.0)) == 30.0   # la mayor entre mtime y ctime
    assert linux.raiz_sistema() == "/" and linux.patrones_evento(["x"]) == ["x"] and linux.nvidia_smi_aplica([])


def test_linux_delega_en_las_funciones_de_los_modulos(monkeypatch):
    monkeypatch.setattr(db, "_temperatura_cpu_linux", lambda: 61.5)
    monkeypatch.setattr(collector, "_leer_distro_linux", lambda: "Zorin de prueba")
    assert db.temperatura_cpu() == 61.5 and collector.leer_distro() == "Zorin de prueba"


def test_linux_lee_los_eventos_con_la_misma_forma(monkeypatch):
    linea = json.dumps({"__REALTIME_TIMESTAMP": "1700000000000000", "SYSLOG_IDENTIFIER": "kernel", "PRIORITY": "3", "MESSAGE": "I/O error"})
    monkeypatch.setattr(collector, "ejecutar", lambda *a, **k: linea + "\nno es json\n")
    assert linux.eventos(1, 50) == [(1700000000, "kernel", "err", "I/O error")]


# ---------- Windows ----------

def test_windows_usa_localappdata_y_solo_la_fecha_de_modificacion(en_windows, monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert windows.dir_datos() == tmp_path / "pc-doctor"
    assert windows.fecha_archivo(SimpleNamespace(st_mtime=10.0, st_ctime=30.0)) == 10.0
    assert windows.carga() is None and windows.escritorio() == "Windows"


def test_windows_la_carpeta_de_descargas_sale_del_registro_y_si_no_de_downloads(en_windows, monkeypatch, tmp_path):
    movida = tmp_path / "MisDescargas"
    movida.mkdir()
    monkeypatch.setattr(windows, "_registro", lambda raiz, ruta, nombre: str(movida))
    assert db.carpeta_descargas() == movida
    monkeypatch.setattr(windows, "_registro", lambda *a: None)
    (Path.home() / "Downloads").mkdir(exist_ok=True)
    assert db.carpeta_descargas() == Path.home() / "Downloads"


def test_windows_los_eventos_llegan_a_la_tabla_y_disparan_las_alertas_de_windows(en_windows, monkeypatch, con):
    ahora = db.ahora()
    datos = [{"ts": ahora - 60, "proveedor": "Microsoft-Windows-Kernel-Power", "id": 41, "nivel": 1, "mensaje": "El sistema se reinició sin apagarse"},
             {"ts": ahora - 30, "proveedor": "disk", "id": 7, "nivel": 2, "mensaje": r"El dispositivo \Device\Harddisk1\DR1 tiene un bloque defectuoso"},
             {"ts": ahora - 20, "proveedor": "Microsoft-Windows-DistributedCOM", "id": 10016, "nivel": 2, "mensaje": "ruido"}]
    monkeypatch.setattr(windows, "_json_ps", lambda *a, **k: datos)
    assert collector.guardar_eventos(con) == 2   # el ruido conocido no entra
    conds = salud.condiciones_eventos(con, ahora)
    assert {"evento:disco_io", "evento:apagado_inesperado"} <= set(conds) and "evento:termico" not in conds


def test_windows_una_corrida_sin_powershell_no_rompe_nada(en_windows, con):
    assert windows.leer_sensores() == [] and windows.hardware()[0][0] == "cpu" and windows.paquetes() == []
    assert windows.eventos(0, 50) == [] and db.temperatura_cpu() is None


def test_el_esquema_acepta_los_origenes_de_windows(con):
    con.execute("INSERT INTO workspace (hostname, machine_id, creado_en) VALUES ('h','m',1)")
    con.execute("INSERT INTO snapshot_entorno (workspace_id, tomado_en, hash) VALUES (1,1,'x')")
    for origen in ("apt", "flatpak", "snap", "registro", "winget"):
        con.execute("INSERT INTO software (snapshot_id, nombre, version, origen) VALUES (1,'a','1',?)", (origen,))
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO software (snapshot_id, nombre, version, origen) VALUES (1,'a','1','otro')")

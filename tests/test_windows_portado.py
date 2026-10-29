"""Lo que cambia en Windows en reporte.py, collector.py y verificar.py (en Linux no cambia nada)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

import collector
import db
import memoria
import plataforma
import reporte

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "instalador"))
import verificar  # noqa: E402


@pytest.fixture
def en_windows():
    plataforma.forzar("windows")
    yield
    plataforma.forzar(None)


def test_en_linux_claude_sigue_en_su_propio_grupo_de_sesion():
    assert reporte._grupo_de_procesos() == {"start_new_session": True}


def test_en_windows_claude_corre_sin_ventana_y_en_su_grupo(en_windows):
    flags = reporte._grupo_de_procesos()["creationflags"]
    assert flags & 0x200 and flags & 0x08000000        # CREATE_NEW_PROCESS_GROUP y CREATE_NO_WINDOW


def test_en_windows_se_mata_el_arbol_completo_con_taskkill(en_windows, monkeypatch):
    llamadas = []
    monkeypatch.setattr(reporte.subprocess, "run", lambda cmd, **k: llamadas.append(cmd))
    reporte._matar_arbol(type("P", (), {"pid": 4321})())
    assert llamadas == [["taskkill", "/PID", "4321", "/T", "/F"]]


def test_el_mcp_del_reporte_encuentra_el_uv_que_instala_el_instalador(tmp_path, monkeypatch):
    monkeypatch.setattr(reporte.shutil, "which", lambda n: None)
    assert reporte.ruta_uv().endswith(os.path.join(".local", "bin", "uv"))
    propio = Path(reporte.__file__).resolve().parent / "herramientas" / "uv.exe"
    monkeypatch.setattr(Path, "is_file", lambda self: self == propio)
    assert reporte.ruta_uv() == str(propio)


def test_el_exportador_de_windows_deja_el_changelog_en_la_carpeta_de_datos(tmp_path, monkeypatch):
    destino = tmp_path / "datos"
    monkeypatch.setattr(db, "DIR_DATOS", destino)
    con = db.conectar()
    memoria.asegurar(con)
    memoria.registrar_changelog(con, "cambio", "prueba", "Se probó la exportación en Windows")
    res = collector.exportar_memoria(con)
    assert res.get("CHANGELOG.md", 0) >= 1
    assert "exportación en Windows" in (destino / "CHANGELOG.md").read_text(encoding="utf-8")
    assert not (destino / "BITACORA.md").exists()      # la bitácora es del desarrollo: no viaja ni se exporta en Windows


def test_el_paso_exportar_solo_existe_en_windows(monkeypatch, en_windows):
    pasos = []
    monkeypatch.setattr(collector, "paso", lambda nombre, fn, *a: pasos.append(nombre))
    monkeypatch.setattr(db, "conectar", lambda: type("C", (), {"commit": lambda s: None, "close": lambda s: None})())
    monkeypatch.setattr(collector, "registrar_workspace", lambda con: 1)
    collector.main()
    assert "exportar" in pasos


def test_en_linux_el_recolector_no_exporta(monkeypatch):
    pasos = []
    monkeypatch.setattr(collector, "paso", lambda nombre, fn, *a: pasos.append(nombre))
    monkeypatch.setattr(db, "conectar", lambda: type("C", (), {"commit": lambda s: None, "close": lambda s: None})())
    monkeypatch.setattr(collector, "registrar_workspace", lambda con: 1)
    collector.main()
    assert "exportar" not in pasos


def test_verificar_resume_los_sensores_sin_inventar():
    assert "ninguna lectura" in verificar.resumen_sensores([])[0]
    assert verificar.resumen_sensores([{"categoria": "cpu"}, {"categoria": "cpu"}, {"categoria": "gpu"}]) == ["Sensores: cpu 2, gpu 1"]


def test_verificar_informa_lo_que_no_se_puede_medir_en_windows(en_windows, monkeypatch):
    from plataforma import windows
    monkeypatch.setattr(windows, "leer_sensores", lambda: [])
    monkeypatch.setattr(windows, "distro", lambda: "Windows 11 de prueba")
    monkeypatch.setattr(windows, "no_disponible", lambda l: ["Temperaturas: falta el ayudante"])
    monkeypatch.setattr(windows, "ayudante", lambda: {"estado": "ausente", "edad_s": 0})
    texto = "\n".join(verificar.lineas())
    assert "Windows 11 de prueba" in texto and "no instalado (opcional)" in texto and "Temperaturas: falta el ayudante" in texto
    assert "Limitaciones fijas:" in texto

"""Remediación en Windows (simulada en Linux): solo las acciones con implementación allá, planes de energía con powercfg falso,
temporales del usuario y cachés de uv/pip. Nada toca el sistema real."""

import importlib
import json
import os
import time
from pathlib import Path

import pytest

import db
import remediacion
from remediacion import aplicar

EQ, AHORRO, ALTO = "381b4222-f694-41f0-9685-ff5bb260df2e", "a1841308-3541-4fab-bc81-f71556f20b4a", "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"


def fakes(nombre):
    return [json.loads(l) for l in Path(os.environ["FAKE_LOG"]).read_text().splitlines() if json.loads(l).get("cmd") == nombre]


def seteos():
    return [f["argv"] for f in fakes("powercfg") if f["argv"][:1] == ["/setactive"]]


@pytest.fixture(autouse=True)
def en_windows(monkeypatch):
    monkeypatch.setattr(remediacion.plataforma, "NOMBRE", "windows")
    monkeypatch.setitem(remediacion.plataforma._cache, "backend", importlib.import_module("plataforma.windows"))   # y que no quede cacheado después
    monkeypatch.setattr(remediacion, "_en_uso", lambda nombres: None)
    local = Path.home() / "AppData" / "Local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("TEMP", str(local / "Temp"))
    (local / "Temp").mkdir(parents=True)


def archivo(ruta: Path, dias=0, contenido=b"x" * 2048) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(contenido)
    if dias:
        t = time.time() - dias * 86400
        os.utime(ruta, (t, t))
    return ruta


# ---------- el catálogo de Windows ----------

def test_el_modelo_solo_ve_las_acciones_de_windows():
    nombres = {a["nombre"] for a in remediacion.catalogo()}
    assert nombres == {"limpiar_descargas_viejas", "cambiar_perfil_energia", "limpiar_temporales_usuario", "limpiar_cache_uv", "limpiar_cache_pip"}
    assert "limpiar_cache_miniaturas" not in nombres and "cerrar_proceso" not in nombres and "reiniciar_servicio_usuario" not in nombres


def test_en_linux_no_aparece_la_de_temporales_de_windows(monkeypatch):
    monkeypatch.setattr(remediacion.plataforma, "NOMBRE", "linux")
    nombres = {a["nombre"] for a in remediacion.catalogo()}
    assert "limpiar_temporales_usuario" not in nombres and "cerrar_proceso" in nombres and "limpiar_cache_miniaturas" in nombres
    assert aplicar("limpiar_temporales_usuario", {"dias": 5})["rechazada"]


@pytest.mark.parametrize("accion,params", [("limpiar_cache_miniaturas", {}), ("cerrar_proceso", {"pid": 4242, "nombre_esperado": "x"}),
                                            ("reiniciar_servicio_usuario", {"nombre": "x"})])
def test_las_acciones_de_linux_se_rechazan_en_windows(accion, params):
    assert aplicar(accion, params, simular=False)["rechazada"]


# ---------- planes de energía ----------

def test_cambia_el_plan_con_powercfg_y_se_verifica_y_se_deshace():
    r = aplicar("cambiar_perfil_energia", {"perfil": "performance"}, simular=False)
    assert r["ok"] and seteos() == [["/setactive", ALTO]]
    assert r["resumen"] == "perfil de energía: balanced → performance"
    assert remediacion.verificar_efecto(r["ejecucion_id"])["cumplido"]
    d = remediacion.deshacer(r["ejecucion_id"])
    assert d["ok"] and seteos()[-1] == ["/setactive", EQ]


def test_simular_no_cambia_el_plan():
    r = aplicar("cambiar_perfil_energia", {"perfil": "power-saver"})
    assert "balanced a power-saver" in r["resumen"] and seteos() == []


def test_si_el_plan_no_existe_en_esta_pc_no_cambia_nada(monkeypatch):
    monkeypatch.setenv("FAKE_PLANES", "solo-equilibrado")
    r = aplicar("cambiar_perfil_energia", {"perfil": "performance"}, simular=False)
    assert r["ok"] is False and "no existe en esta PC" in r["resumen"] and seteos() == []


def test_un_plan_del_fabricante_no_se_toca(monkeypatch):
    monkeypatch.setenv("FAKE_PLAN", "12345678-1234-1234-1234-123456789abc")
    r = aplicar("cambiar_perfil_energia", {"perfil": "balanced"}, simular=False)
    assert r["ok"] is False and seteos() == []


def test_si_powercfg_falla_se_informa(monkeypatch):
    monkeypatch.setenv("FAKE_POWERCFG_FALLA", "1")
    assert aplicar("cambiar_perfil_energia", {"perfil": "power-saver"}, simular=False)["ok"] is False


def test_el_mismo_plan_no_hace_nada():
    r = aplicar("cambiar_perfil_energia", {"perfil": "balanced"}, simular=False)
    assert r["ok"] and seteos() == []


# ---------- temporales del usuario ----------

def test_los_temporales_viejos_van_a_cuarentena_y_los_nuevos_no():
    temp = Path(os.environ["TEMP"])
    viejo = archivo(temp / "sub" / "viejo.tmp", dias=40)
    nuevo = archivo(temp / "nuevo.tmp")
    s = aplicar("limpiar_temporales_usuario", {"dias": 10})
    assert s["modo"] == "simulación" and s["archivos"] == 1 and viejo.exists()
    r = aplicar("limpiar_temporales_usuario", {"dias": 10}, simular=False)
    assert r["ok"] and not viejo.exists() and nuevo.exists()
    assert list((db.DIR_CUARENTENA).rglob("viejo.tmp"))                           # en cuarentena, no borrado
    assert remediacion.verificar_efecto(r["ejecucion_id"])["cumplido"]
    d = remediacion.deshacer(r["ejecucion_id"])
    assert d["ok"] and viejo.exists()


def test_un_archivo_en_uso_se_saltea_y_la_verificacion_lo_tiene_en_cuenta(monkeypatch):
    temp = Path(os.environ["TEMP"])
    bloqueado, libre = archivo(temp / "bloqueado.tmp", dias=40), archivo(temp / "libre.tmp", dias=40)
    original = remediacion.mover_a_cuarentena

    def mover(con, origen, destino_base, rel):
        if origen.name == "bloqueado.tmp":
            raise PermissionError("en uso por otro proceso")
        return original(con, origen, destino_base, rel)
    monkeypatch.setattr(remediacion, "mover_a_cuarentena", mover)
    r = aplicar("limpiar_temporales_usuario", {"dias": 10}, simular=False)
    assert r["ok"] and bloqueado.exists() and not libre.exists() and "1 en uso" in r["resumen"]
    assert remediacion.verificar_efecto(r["ejecucion_id"])["cumplido"]


@pytest.mark.parametrize("temp", ["", "relativa/ruta", "/tmp", "C:\\Windows\\Temp"])
def test_solo_se_limpia_una_carpeta_temporal_dentro_del_perfil(monkeypatch, temp):
    monkeypatch.setenv("TEMP", temp)
    monkeypatch.delenv("TMP", raising=False)
    r = aplicar("limpiar_temporales_usuario", {"dias": 10}, simular=False)
    assert r["ok"] is False and "no está dentro de tu perfil" in r["resumen"]


def test_temp_igual_al_perfil_no_se_limpia(monkeypatch):
    monkeypatch.setenv("TEMP", str(Path.home()))
    assert aplicar("limpiar_temporales_usuario", {"dias": 10}, simular=False)["ok"] is False


# ---------- cachés de uv y pip ----------

def test_las_caches_de_windows_estan_en_localappdata():
    local = Path(os.environ["LOCALAPPDATA"])
    a, b = archivo(local / "uv" / "cache" / "paquete.bin"), archivo(local / "pip" / "Cache" / "http" / "x")
    assert remediacion._carpetas_cache("uv") == [local / "uv" / "cache"] and remediacion._carpetas_cache("pip") == [local / "pip" / "Cache"]
    r = aplicar("limpiar_cache_uv", {}, simular=False)
    assert r["ok"] and not a.exists() and b.exists()
    assert remediacion.CATALOGO["limpiar_cache_uv"].preaprobable and remediacion.CATALOGO["limpiar_cache_pip"].preaprobable

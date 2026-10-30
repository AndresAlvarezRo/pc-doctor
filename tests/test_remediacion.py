"""Remediación (fase 1): el catálogo cerrado, la validación con entradas maliciosas, la simulación, la ejecución real en un HOME
temporal y el deshacer. Ningún proceso ni servicio real: `systemctl` y `powerprofilesctl` son los de tests/falsos/."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

import db
import remediacion
from remediacion import Rechazo, aplicar, validar

EN_USO_REAL = remediacion._en_uso
ACCIONES = {"limpiar_cache_miniaturas", "limpiar_cache_uv", "limpiar_cache_pip", "limpiar_descargas_viejas",
            "reiniciar_servicio_usuario", "cambiar_perfil_energia", "cerrar_proceso", "limpiar_temporales_usuario"}


def fakes(nombre):
    return [json.loads(l) for l in Path(os.environ["FAKE_LOG"]).read_text().splitlines() if json.loads(l).get("cmd") == nombre]


def filas(tabla):
    con = db.conectar()
    try:
        return [dict(r) for r in con.execute(f"SELECT * FROM {tabla} ORDER BY id")]
    finally:
        con.close()


def archivo(ruta: Path, contenido=b"x" * 2048) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(contenido)
    return ruta


@pytest.fixture
def cache(monkeypatch):
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    return Path.home() / ".cache"


@pytest.fixture(autouse=True)
def sin_programas_en_marcha(monkeypatch):
    """En la PC de desarrollo puede haber un `uv` real corriendo (esta misma prueba, sin ir más lejos)."""
    monkeypatch.setattr(remediacion, "_en_uso", lambda nombres: None)


@pytest.fixture
def config(tmp_path):
    def poner(**remediacion_cfg):
        (db.DIR_DATOS / "config.json").write_text(json.dumps({"remediacion": remediacion_cfg}))
    import reputacion
    reputacion.RUTA_CONFIG = db.DIR_DATOS / "config.json"
    return poner


@pytest.fixture
def proceso():
    """Un proceso hijo inofensivo del mismo usuario (nombre: el del intérprete)."""
    p = subprocess.Popen([shutil.which("sleep"), "60"])   # no el intérprete: su ruta está dentro de la carpeta del proyecto
    time.sleep(0.3)
    yield p
    if p.poll() is None:
        p.kill()
    p.wait()


# ---------- el catálogo ----------

def test_el_catalogo_tiene_exactamente_las_acciones_previstas_y_sus_reglas():
    assert set(remediacion.CATALOGO) == ACCIONES
    c = remediacion.CATALOGO
    assert {n for n, a in c.items() if a.preaprobable} == {"limpiar_cache_miniaturas", "limpiar_cache_uv", "limpiar_cache_pip"}
    assert c["cerrar_proceso"].riesgo == "medio" and not c["cerrar_proceso"].preaprobable and not c["cerrar_proceso"].reversible
    assert c["reiniciar_servicio_usuario"].riesgo == "medio" and all(a.riesgo in ("bajo", "medio") for a in c.values())
    assert c["cambiar_perfil_energia"].reversible and c["limpiar_descargas_viejas"].reversible
    assert all(a.descripcion and a.efecto and callable(a.simular) and callable(a.verificar) for a in c.values())


def test_el_catalogo_para_el_modelo_no_expone_funciones_ni_rutas():
    texto = json.dumps(remediacion.catalogo())
    assert "cerrar_proceso" in texto and "function" not in texto and str(Path.home()) not in texto


# ---------- validación con entradas maliciosas ----------

@pytest.mark.parametrize("nombre,params", [
    ("rm_rf", {}), ("", {}), (None, {}), (["limpiar_cache_uv"], {}), ("limpiar_cache_uv; rm -rf ~", {}), ("LIMPIAR_CACHE_UV", {}),
    ("limpiar_cache_uv", {"ruta": "/etc"}),                       # parámetro que no existe
    ("limpiar_cache_uv", "ruta"), ("limpiar_cache_uv", [1]),
    ("limpiar_descargas_viejas", {}),                              # falta `dias`
    ("limpiar_descargas_viejas", {"dias": 0}), ("limpiar_descargas_viejas", {"dias": -5}), ("limpiar_descargas_viejas", {"dias": 99999}),
    ("limpiar_descargas_viejas", {"dias": "30"}), ("limpiar_descargas_viejas", {"dias": 30.0}), ("limpiar_descargas_viejas", {"dias": True}),
    ("limpiar_descargas_viejas", {"dias": 30, "carpeta": "../../"}),
    ("cambiar_perfil_energia", {"perfil": "turbo"}), ("cambiar_perfil_energia", {"perfil": "balanced; reboot"}), ("cambiar_perfil_energia", {"perfil": 1}),
    ("reiniciar_servicio_usuario", {"nombre": "../../etc/passwd"}), ("reiniciar_servicio_usuario", {"nombre": "--now x"}),
    ("reiniciar_servicio_usuario", {"nombre": "a b"}), ("reiniciar_servicio_usuario", {"nombre": "x;reboot"}),
    ("reiniciar_servicio_usuario", {"nombre": "$(id)"}), ("reiniciar_servicio_usuario", {"nombre": "-h"}),
    ("reiniciar_servicio_usuario", {"nombre": "a" * 200}), ("reiniciar_servicio_usuario", {"nombre": "x\n"}),
    ("cerrar_proceso", {"pid": 1, "nombre_esperado": "systemd"}), ("cerrar_proceso", {"pid": 0, "nombre_esperado": "x"}),
    ("cerrar_proceso", {"pid": -1, "nombre_esperado": "x"}), ("cerrar_proceso", {"pid": "123", "nombre_esperado": "x"}),
    ("cerrar_proceso", {"pid": 123, "nombre_esperado": "x/../y"}), ("cerrar_proceso", {"pid": 123, "nombre_esperado": "x;y"}),
    ("cerrar_proceso", {"pid": 123, "nombre_esperado": "x\x00y"}), ("cerrar_proceso", {"pid": 123, "nombre_esperado": ""}),
    ("cerrar_proceso", {"pid": 123, "nombre_esperado": "ñandú"}), ("cerrar_proceso", {"pid": 123}),
])
def test_entradas_maliciosas_se_rechazan_y_quedan_registradas(nombre, params):
    with pytest.raises(Rechazo):
        validar(nombre, params)
    for simular in (True, False):
        r = aplicar(nombre, params, simular=simular)
        assert r["ok"] is False and r["rechazada"] is True and r["ejecucion_id"]
    rechazos = filas("ejecuciones")
    assert len(rechazos) == 2 and all(f["estado"] == "rechazada" for f in rechazos)
    assert all(a["tool"].startswith("remediacion:") for a in filas("acciones"))
    assert fakes("systemctl") == [] and fakes("powerprofilesctl") == []     # no se llegó a tocar nada


def test_el_rechazo_registra_basura_sin_romperse():
    r = aplicar("x", {"a": object(), "b": float("nan")}, simular=False)
    assert r["rechazada"] and len(filas("ejecuciones")) == 1


# ---------- cachés ----------

@pytest.mark.parametrize("accion,carpeta", [("limpiar_cache_miniaturas", "thumbnails"), ("limpiar_cache_uv", "uv"), ("limpiar_cache_pip", "pip")])
def test_cache_simulacion_real_y_deshacer(cache, accion, carpeta):
    archivo(cache / carpeta / "grande" / "a.bin"); archivo(cache / carpeta / "b.bin"); archivo(cache / carpeta / ".lock")
    sim = aplicar(accion, {})
    assert sim["ok"] and sim["simulacion"] and sim["elementos"] == 2 and "cuarentena" in sim["resumen"]
    assert (cache / carpeta / "b.bin").exists() and filas("ejecuciones") == []      # simular no toca ni registra ejecuciones

    r = aplicar(accion, {}, simular=False)
    assert r["ok"] and r["bytes_antes"] == 4096 and r["ejecucion_id"]
    assert not (cache / carpeta / "b.bin").exists() and not (cache / carpeta / "grande").exists()
    assert (cache / carpeta / ".lock").exists()                                      # los candados no se mueven
    moved = list((db.DIR_CUARENTENA).rglob("*.bin"))
    assert len(moved) == 2, "nada se borra: está todo en cuarentena"
    ej, = filas("ejecuciones")
    assert ej["estado"] == "aplicada" and ej["deshecha_en"] is None and len(json.loads(ej["deshacer"])["cuarentena_ids"]) == 2
    assert len(filas("cuarentena")) == 2 and any(a["tool"] == f"remediacion:{accion}" for a in filas("acciones"))
    assert remediacion.verificar_efecto(ej["id"])["cumplido"]

    d = remediacion.deshacer(ej["id"])
    assert d["ok"] and (cache / carpeta / "b.bin").read_bytes() == b"x" * 2048 and (cache / carpeta / "grande" / "a.bin").exists()
    assert filas("ejecuciones")[0]["deshecha_en"] and all(c["restaurado"] for c in filas("cuarentena"))
    assert remediacion.deshacer(ej["id"])["ok"] is False                             # no se deshace dos veces


def test_cache_inexistente_no_hace_nada(cache):
    r = aplicar("limpiar_cache_uv", {}, simular=False)
    assert r["ok"] and filas("cuarentena") == []


def test_en_uso_ignora_a_los_ancestros_pero_ve_a_los_demas():
    class Falso:
        def __init__(self, pid): self.pid, self.info = pid, {"name": "uv"}
    with pytest.MonkeyPatch.context() as m:   # acotado: el cierre de conftest también recorre los procesos
        m.setattr(psutil, "process_iter", lambda attrs=None: [Falso(os.getppid())])
        assert EN_USO_REAL({"uv"}) is None                         # el `uv run` que nos lanzó no cuenta
        m.setattr(psutil, "process_iter", lambda attrs=None: [Falso(os.getppid()), Falso(4194000)])
        assert EN_USO_REAL({"uv"}) == "uv"                         # otro uv sí


def test_cache_con_el_programa_en_marcha_no_se_toca(cache, monkeypatch):
    archivo(cache / "uv" / "a.bin")
    monkeypatch.setattr(remediacion, "_en_uso", lambda nombres: "uv")
    r = aplicar("limpiar_cache_uv", {}, simular=False)
    assert r["ok"] is False and (cache / "uv" / "a.bin").exists() and "en marcha" in r["resumen"]
    assert filas("ejecuciones")[0]["estado"] == "fallida"


def test_cache_no_sigue_enlaces_simbolicos(cache, tmp_path):
    afuera = tmp_path / "afuera"; archivo(afuera / "secreto.txt")
    archivo(cache / "pip" / "ok.bin")
    (cache / "pip" / "enlace").symlink_to(afuera)
    aplicar("limpiar_cache_pip", {}, simular=False)
    assert (afuera / "secreto.txt").exists() and (cache / "pip" / "enlace").is_symlink()
    # y una caché que es un enlace a otra parte no se toca
    (cache / "uv").symlink_to(afuera)
    assert aplicar("limpiar_cache_uv", {}, simular=False)["ok"] and (afuera / "secreto.txt").exists()


def test_xdg_cache_home_fuera_del_home_se_ignora(cache, monkeypatch, tmp_path):
    ajena = tmp_path / "ajena"; archivo(ajena / "uv" / "a.bin")
    monkeypatch.setenv("XDG_CACHE_HOME", str(ajena))
    aplicar("limpiar_cache_uv", {}, simular=False)
    assert (ajena / "uv" / "a.bin").exists()


def test_deshacer_no_pisa_lo_regenerado(cache):
    archivo(cache / "thumbnails" / "a.png")
    ej = aplicar("limpiar_cache_miniaturas", {}, simular=False)["ejecucion_id"]
    archivo(cache / "thumbnails" / "a.png", b"nuevo")
    d = remediacion.deshacer(ej)
    assert d["ok"] is False and (cache / "thumbnails" / "a.png").read_bytes() == b"nuevo"
    assert filas("ejecuciones")[0]["deshecha_en"] is None


# ---------- limpiar_descargas_viejas ----------

def test_descargas_simulacion_real_y_deshacer(monkeypatch):
    d = Path.home() / "Descargas"
    viejo = archivo(d / "viejo.iso"); archivo(d / "nuevo.txt")
    monkeypatch.setattr(remediacion, "time", type("T", (), {"time": staticmethod(lambda: time.time() + 100 * 86400), "sleep": time.sleep}))
    sim = aplicar("limpiar_descargas_viejas", {"dias": 90})
    assert sim["ok"] and sim["archivos"] == 2 and viejo.exists()
    r = aplicar("limpiar_descargas_viejas", {"dias": 90}, simular=False)
    assert r["ok"] and r["movidos"] == 2 and not viejo.exists()
    ej = filas("ejecuciones")[0]
    assert remediacion.verificar_efecto(ej["id"])["cumplido"]
    assert remediacion.deshacer(ej["id"])["ok"] and viejo.exists()


def test_descargas_sin_carpeta():
    r = aplicar("limpiar_descargas_viejas", {"dias": 30}, simular=False)
    assert r["ok"] is False and "Descargas" in r["resumen"]


# ---------- reiniciar_servicio_usuario ----------

def test_servicio_fuera_de_la_lista_se_rechaza_aunque_sea_valido(config):
    assert aplicar("reiniciar_servicio_usuario", {"nombre": "mi-servicio"}, simular=False)["rechazada"]   # lista vacía por defecto
    config(servicios_permitidos=["otro"])
    assert aplicar("reiniciar_servicio_usuario", {"nombre": "mi-servicio"}, simular=False)["rechazada"]
    assert fakes("systemctl") == []


def test_servicio_permitido_simula_reinicia_y_verifica(config):
    config(servicios_permitidos=["mi-servicio", "../malo", 5, "x y"])
    assert remediacion._servicios_permitidos() == {"mi-servicio.service"}           # lo inválido de la lista se ignora
    sim = aplicar("reiniciar_servicio_usuario", {"nombre": "mi-servicio"})
    assert sim["ok"] and "reiniciaría" in sim["resumen"] and not any("restart" in f["argv"] for f in fakes("systemctl"))
    r = aplicar("reiniciar_servicio_usuario", {"nombre": "mi-servicio.service"}, simular=False)
    assert r["ok"] and ["--user", "restart", "mi-servicio.service"] in [f["argv"] for f in fakes("systemctl")]
    ej, = filas("ejecuciones")
    assert ej["deshacer"] is None and remediacion.verificar_efecto(ej["id"])["cumplido"]
    assert remediacion.deshacer(ej["id"])["ok"] is False                             # no es reversible


def test_servicio_que_no_vuelve_falla_la_verificacion(config, monkeypatch):
    config(servicios_permitidos=["mi-servicio"])
    ej = aplicar("reiniciar_servicio_usuario", {"nombre": "mi-servicio"}, simular=False)["ejecucion_id"]
    monkeypatch.setenv("FAKE_ACTIVO", "failed")
    monkeypatch.setattr(time, "sleep", lambda s: None)
    assert remediacion.verificar_efecto(ej)["cumplido"] is False


# ---------- cambiar_perfil_energia ----------

def test_perfil_cambia_verifica_y_se_deshace(monkeypatch):
    monkeypatch.setenv("FAKE_PERFIL", "power-saver")
    assert "de power-saver a performance" in aplicar("cambiar_perfil_energia", {"perfil": "performance"})["resumen"]
    assert fakes("powerprofilesctl")[-1]["argv"] == ["get"]                          # simular solo lee
    r = aplicar("cambiar_perfil_energia", {"perfil": "performance"}, simular=False)
    assert r["ok"] and r["anterior"] == "power-saver"
    ej, = filas("ejecuciones")
    assert json.loads(ej["deshacer"]) == {"perfil": "power-saver"} and remediacion.verificar_efecto(ej["id"])["cumplido"]
    assert remediacion.deshacer(ej["id"])["ok"] and fakes("powerprofilesctl")[-1]["argv"] == ["set", "power-saver"]
    assert filas("ejecuciones")[0]["deshecha_en"]


def test_perfil_igual_no_cambia_nada_y_no_deja_con_que_deshacer():
    r = aplicar("cambiar_perfil_energia", {"perfil": "balanced"}, simular=False)
    assert r["ok"] and not any(f["argv"][:1] == ["set"] for f in fakes("powerprofilesctl")) and filas("ejecuciones")[0]["deshacer"] is None


def test_perfil_que_el_sistema_no_acepta_queda_fallido(monkeypatch):
    monkeypatch.setenv("FAKE_PERFIL_FALLA", "1")
    r = aplicar("cambiar_perfil_energia", {"perfil": "performance"}, simular=False)
    assert r["ok"] is False and filas("ejecuciones")[0]["estado"] == "fallida"


def test_un_deshacer_manipulado_en_la_base_no_ejecuta_nada_raro():
    ej = aplicar("cambiar_perfil_energia", {"perfil": "performance"}, simular=False)["ejecucion_id"]
    con = db.conectar(); con.execute("UPDATE ejecuciones SET deshacer=?", (json.dumps({"perfil": "x; reboot"}),)); con.commit(); con.close()
    assert remediacion.deshacer(ej)["ok"] is False and not any("reboot" in " ".join(f["argv"]) for f in fakes("powerprofilesctl"))


# ---------- cerrar_proceso ----------

def test_cerrar_proceso_simula_cierra_y_verifica(proceso):
    nombre = psutil.Process(proceso.pid).name()
    sim = aplicar("cerrar_proceso", {"pid": proceso.pid, "nombre_esperado": nombre})
    assert sim["ok"] and "cerraría" in sim["resumen"] and proceso.poll() is None
    r = aplicar("cerrar_proceso", {"pid": proceso.pid, "nombre_esperado": nombre}, simular=False)
    assert r["ok"] and proceso.wait(5) is not None
    ej, = filas("ejecuciones")
    assert ej["deshacer"] is None and remediacion.verificar_efecto(ej["id"])["cumplido"]


def test_cerrar_proceso_con_nombre_distinto_no_lo_toca(proceso):
    r = aplicar("cerrar_proceso", {"pid": proceso.pid, "nombre_esperado": "firefox"}, simular=False)
    assert r["rechazada"] and "firefox" in r["error"] and proceso.poll() is None


@pytest.mark.parametrize("quien", ["init", "propio", "padre", "inexistente"])
def test_cerrar_proceso_nunca_toca_sistema_ni_pc_doctor(quien):
    pid, nombre = {"init": (1, "systemd"), "propio": (os.getpid(), psutil.Process().name()),
                   "padre": (os.getppid(), psutil.Process(os.getppid()).name()), "inexistente": (4194000, "nada")}[quien]
    r = aplicar("cerrar_proceso", {"pid": pid, "nombre_esperado": nombre[:60]}, simular=False)
    assert r["rechazada"] is True
    assert psutil.pid_exists(os.getpid()) and (quien != "padre" or psutil.pid_exists(os.getppid()))


def test_cerrar_proceso_de_otro_usuario_se_rechaza(monkeypatch, proceso):
    nombre = psutil.Process(proceso.pid).name()
    monkeypatch.setattr(os, "getuid", lambda: 0 if os.geteuid() else 1)
    assert aplicar("cerrar_proceso", {"pid": proceso.pid, "nombre_esperado": nombre}, simular=False)["rechazada"]
    assert proceso.poll() is None


@pytest.mark.parametrize("nombre", ["gnome-shell", "Xorg", "Xwayland", "systemd", "claude", "pipewire", "pc-doctor-web", "dbus-daemon", "tmux"])
def test_cerrar_proceso_protegidos_por_nombre(monkeypatch, proceso, nombre):
    original = psutil.Process.name
    monkeypatch.setattr(psutil.Process, "name", lambda self: nombre if self.pid == proceso.pid else original(self))
    r = aplicar("cerrar_proceso", {"pid": proceso.pid, "nombre_esperado": nombre}, simular=False)
    assert r["rechazada"] and "protegido" in r["error"] and proceso.poll() is None


def test_cerrar_proceso_cuya_linea_de_comandos_es_claude_o_pc_doctor(proceso):
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "pc-doctor"])
    try:
        time.sleep(0.3)
        nombre = psutil.Process(p.pid).name()
        assert aplicar("cerrar_proceso", {"pid": p.pid, "nombre_esperado": nombre}, simular=False)["rechazada"] and p.poll() is None
    finally:
        p.kill(); p.wait()


# ---------- el ejecutor ----------

def test_error_inesperado_en_una_accion_queda_fallido_sin_tirar_al_llamador(monkeypatch):
    def rota(p): raise RuntimeError("boom")
    monkeypatch.setitem(remediacion.CATALOGO, "limpiar_cache_uv", remediacion.CATALOGO["limpiar_cache_uv"].__class__(
        **{**remediacion.CATALOGO["limpiar_cache_uv"].__dict__, "ejecutar": rota}))
    r = aplicar("limpiar_cache_uv", {}, simular=False)
    assert r["ok"] is False and "RuntimeError" in r["resumen"] and filas("ejecuciones")[0]["estado"] == "fallida"


def test_el_plan_queda_anotado_en_la_ejecucion():
    aplicar("cambiar_perfil_energia", {"perfil": "balanced"}, simular=False, plan_id=7)
    assert filas("ejecuciones")[0]["plan_id"] == 7


def test_la_accion_de_otra_plataforma_se_rechaza(monkeypatch):
    monkeypatch.setattr(remediacion.plataforma, "NOMBRE", "windows")
    assert aplicar("limpiar_cache_miniaturas", {})["rechazada"]            # en Windows no hay caché de miniaturas, ni procesos, ni servicios de systemd
    assert aplicar("cerrar_proceso", {"pid": 99999, "nombre_esperado": "x"})["rechazada"]
    assert aplicar("reiniciar_servicio_usuario", {"nombre": "x"})["rechazada"]


def test_ninguna_accion_usa_shell_ni_sudo():
    fuente = Path(remediacion.__file__).read_text()
    assert "shell=True" not in fuente and "os.system" not in fuente and "sudo" not in fuente.lower().replace("sin root", "")
    assert "os.remove" not in fuente and "unlink" not in fuente and "rmtree" not in fuente and "SIGKILL" not in fuente and ".kill(" not in fuente

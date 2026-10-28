"""Configuración común de las pruebas de pc-doctor.

Reglas de oro (las pruebas también corren en GitHub Actions, donde no existe esta PC):
- Todo el proyecto se importa con una carpeta de datos y un HOME **temporales**: ninguna prueba toca la base real, la
  configuración, ~/.steam ni ~/.local/bin/claude.
- `notify-send`, `systemd-run`, `systemctl`, `gdbus`, `xdg-open` y `claude` son reemplazos (tests/falsos/), puestos al
  principio del PATH, que solo registran qué se les pidió.
- Los sensores y los procesos reales están bloqueados: `salud.leer_lecturas` y `actividad.detectar` devuelven datos sintéticos
  salvo en las pruebas marcadas `@pytest.mark.local`, que solo tienen sentido en la PC de desarrollo.
"""

import atexit
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
FALSOS = Path(__file__).resolve().parent / "falsos"

# Esto va ANTES de importar cualquier módulo del proyecto: db.py lee estas variables al importarse.
TEMP = Path(tempfile.mkdtemp(prefix="pc-doctor-pruebas-"))
DATOS = TEMP / "datos"
HOME = TEMP / "home"
DATOS.mkdir()
HOME.mkdir()
PUERTO_PRUEBAS = "8795"  # nunca el 8787: así ninguna prueba toca el dashboard real si está corriendo
os.environ.update({"PC_DOCTOR_DATOS": str(DATOS), "HOME": str(HOME), "PC_DOCTOR_PUERTO": PUERTO_PRUEBAS,
                   "FAKE_LOG": str(TEMP / "registro.jsonl"), "PATH": f"{FALSOS}:{os.environ['PATH']}"})
atexit.register(shutil.rmtree, TEMP, ignore_errors=True)

sys.path.insert(0, str(Path(__file__).resolve().parent))  # para `import ayudas`
sys.path.insert(0, str(RAIZ))

import ayudas  # noqa: E402
import actividad  # noqa: E402
import db  # noqa: E402
import reputacion  # noqa: E402
import salud  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line("markers", "local: solo tiene sentido en la PC de desarrollo (lee sensores o procesos reales); se saltea en CI")
    config.addinivalue_line("markers", "lento: tarda más de ~1 s (datos sintéticos grandes, procesos); el hook pre-commit las saltea")


def pytest_sessionstart(session):
    # Última barrera: si algo apuntara a la carpeta de datos real, se aborta todo antes de correr una sola prueba.
    real = Path("/home/v/.local/share/pc-doctor")
    assert db.DIR_DATOS == DATOS and db.DIR_DATOS != real and TEMP in db.DIR_DATOS.parents, f"las pruebas apuntan a {db.DIR_DATOS}"
    assert Path.home() == HOME


@pytest.fixture(autouse=True)
def entorno_aislado(monkeypatch, request):
    """Carpeta de datos vacía, comandos falsos limpios y sensores/procesos reales bloqueados en cada prueba."""
    for carpeta in (DATOS, HOME):  # cada prueba empieza con datos y HOME vacíos
        for p in carpeta.iterdir():
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() and not p.is_symlink() else p.unlink()
    for k in [k for k in os.environ if k.startswith("FAKE_") and k != "FAKE_LOG"]:
        monkeypatch.delenv(k)
    Path(os.environ["FAKE_LOG"]).write_text("")
    monkeypatch.setattr(db, "SOLO_LECTURA", False)
    monkeypatch.setattr(db, "DIR_DATOS", DATOS)
    monkeypatch.setattr(db, "RUTA_DB", DATOS / "doctor.db")
    monkeypatch.setattr(reputacion, "RUTA_CONFIG", DATOS / "config.json")
    if request.node.get_closest_marker("local") is None:
        monkeypatch.setattr(salud, "leer_lecturas", lambda fila=None: ayudas.lecturas_vivas())
        monkeypatch.setattr(actividad, "detectar", lambda: [])
        monkeypatch.setattr(actividad, "juegos_steam", lambda: {
            "646570": {"nombre": "Slay the Spire", "carpeta": "SlayTheSpire"},
            "3321460": {"nombre": "Crimson Desert Enhanced", "carpeta": "Crimson Desert"},
            "1245620": {"nombre": "ELDEN RING NIGHTREIGN", "carpeta": "ELDEN RING NIGHTREIGN"}})
        monkeypatch.setattr(actividad, "_bibliotecas_steam", lambda: [])


@pytest.fixture
def con():
    """Conexión a la base temporal vacía (con el esquema aplicado)."""
    c = db.conectar()
    yield c
    c.close()


@pytest.fixture(scope="session")
def datos_ricos(tmp_path_factory):
    """Carpeta con datos sintéticos de 45 días (lecturas, sesiones, alertas, reportes...), generada una vez por sesión."""
    destino = tmp_path_factory.mktemp("datos_ricos") / "datos"
    r = subprocess.run([sys.executable, str(RAIZ / "web" / "datos_de_prueba.py"), str(destino), "45"],
                       capture_output=True, text=True, env={**os.environ, "PC_DOCTOR_DATOS": str(destino)}, timeout=180)
    assert r.returncode == 0, r.stderr[-800:]
    return destino


@pytest.fixture
def con_datos_ricos(datos_ricos, tmp_path, monkeypatch):
    """Copia de los datos sintéticos como carpeta de datos activa (se puede escribir sin afectar a otras pruebas)."""
    copia = tmp_path / "datos"
    shutil.copytree(datos_ricos, copia)
    monkeypatch.setattr(db, "DIR_DATOS", copia)
    monkeypatch.setattr(db, "RUTA_DB", copia / "doctor.db")
    monkeypatch.setattr(reputacion, "RUTA_CONFIG", copia / "config.json")
    return copia


@pytest.fixture
def cliente_api(con_datos_ricos, monkeypatch):
    """Cliente HTTP en proceso del dashboard, en modo de solo lectura y con los sensores en vivo sintéticos."""
    from fastapi.testclient import TestClient
    import consultas
    import web.api as api  # al importarse activa db.SOLO_LECTURA: acá se maneja a mano para no contaminar otras pruebas
    monkeypatch.setattr(db, "SOLO_LECTURA", True)
    monkeypatch.setattr(consultas, "no_disponible", lambda lecturas: [])  # depende de /sys/block: no es de esta prueba
    api._vivo.update({"t": 0.0, "v": None})
    with TestClient(api.app, base_url=f"http://127.0.0.1:{PUERTO_PRUEBAS}") as c:
        c.api = api
        yield c

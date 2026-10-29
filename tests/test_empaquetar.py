"""empaquetar.py: lo que entra al zip de Windows y lo que lo hace fallar."""

import hashlib
import json
import os
import shutil
import time
import zipfile
from pathlib import Path

import pytest

import empaquetar
import reputacion

RAIZ = Path(__file__).resolve().parent.parent
BOM = b"\xef\xbb\xbf"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """Copia del repo sin lo pesado, con un frontend compilado de mentira y un ícono de mentira (no hace falta Pillow)."""
    destino = tmp_path / "repo"
    ignorar = shutil.ignore_patterns("venv", ".venv", ".git", "node_modules", "paquetes", "dist", "__pycache__", "capturas", "datos", ".pytest_cache")
    shutil.copytree(RAIZ, destino, ignore=ignorar)
    dist = destino / "web" / "frontend" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html></html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    futuro = time.time() + 60
    os.utime(dist / "index.html", (futuro, futuro))
    monkeypatch.setattr(empaquetar, "icono_ico", lambda raiz=None: b"\x00\x00\x01\x00")
    return destino


def limpio() -> dict[str, bytes]:
    base = {n: b"x" for n in ("instalar.ps1", "habilitar-sensores.ps1", "ayudante.ps1", "versiones.toml", "lanzador.pyw", "INSTALAR-WINDOWS.md",
                              "PROMPT-VERIFICACION.md", "config.ejemplo.json", "plantillas/CLAUDE.usuario.md", "icono.ico", "uv.lock", "pyproject.toml",
                              "web/frontend/dist/index.html", "collector.py", "server.py", "web/api.py")}
    for n in ("instalar.ps1", "habilitar-sensores.ps1", "ayudante.ps1"):
        base[n] = BOM + b"Write-Host 1"
    return base


def test_un_paquete_limpio_pasa():
    empaquetar.verificar(limpio())


@pytest.mark.parametrize("cambio, texto", [
    ({"collector.py": b"x = '" + empaquetar.EICAR + b"'"}, "EICAR"),
    ({"extra.dat": b"MZ\x90\x00"}, "ejecutable de Windows"),
    ({"ayudante.ps1": b"Write-Host 1"}, "BOM"),
    ({"db.py": b"R = '/home/alguien/proyecto'"}, "ruta de esta PC"),
    ({"db.py": b"R = 'C:\\Users\\Alguien\\x'"}, "ruta de esta PC"),
    ({"doctor.db": b"SQLite"}, "no debe ir"),
    ({"config.json": b"{}"}, "no debe ir"),
    ({"web_token": b"abc"}, "no debe ir"),
    ({"tests/test_x.py": b"x"}, "no debe ir"),
    ({"BITACORA.md": b"x"}, "no debe ir"),
])
def test_verificar_rechaza(cambio, texto):
    c = {**limpio(), **cambio}
    with pytest.raises(empaquetar.ErrorDePaquete, match=texto):
        empaquetar.verificar(c)


def test_verificar_informa_todos_los_problemas_juntos():
    c = {**limpio(), "ayudante.ps1": b"x", "collector.py": empaquetar.EICAR}
    with pytest.raises(empaquetar.ErrorDePaquete) as e:
        empaquetar.verificar(c)
    assert "BOM" in str(e.value) and "EICAR" in str(e.value)


def test_falla_si_falta_algo_obligatorio():
    c = limpio()
    del c["instalar.ps1"]
    with pytest.raises(empaquetar.ErrorDePaquete, match="instalar.ps1: falta"):
        empaquetar.verificar(c)


def test_este_archivo_no_contiene_la_cadena_eicar_entera():
    assert empaquetar.EICAR.decode() not in (RAIZ / "empaquetar.py").read_text()
    assert empaquetar.EICAR.decode() not in Path(__file__).read_text()


def test_el_zip_lleva_el_codigo_y_los_scripts_en_la_raiz_y_nada_de_desarrollo(repo):
    zip_, suma = empaquetar.construir(repo, repo / "salida")
    nombres = set(zipfile.ZipFile(zip_).namelist())
    for esperado in ("instalar.ps1", "habilitar-sensores.ps1", "ayudante.ps1", "versiones.toml", "lanzador.pyw", "verificar.py", "icono.ico",
                     "config.ejemplo.json", "plantillas/CLAUDE.usuario.md", "INSTALAR-WINDOWS.md", "pyproject.toml", "uv.lock",
                     "collector.py", "server.py", "reporte.py", "plataforma/windows.py", "web/api.py", "web/frontend/dist/index.html"):
        assert esperado in nombres, esperado
    for n in nombres:
        partes = Path(n).parts
        assert partes[0] not in ("tests", "scripts", "systemd", "instalador", ".github", "node_modules", "paquetes"), n
        assert n not in ("empaquetar.py", "BITACORA.md", "CHANGELOG.md", "CLAUDE.md", "habilitar-sensores.sh", "web/pc-doctor.desktop"), n
        assert "capturas" not in partes and "datos" not in partes
    assert hashlib.sha256(zip_.read_bytes()).hexdigest() == suma
    assert zip_.with_name(zip_.name + ".sha256").read_text() == f"{suma}  {zip_.name}\n"


def test_el_mismo_contenido_da_el_mismo_zip(repo):
    a = empaquetar.construir(repo, repo / "a")[1]
    b = empaquetar.construir(repo, repo / "b")[1]
    assert a == b


def test_ningun_archivo_del_zip_nombra_una_ruta_de_esta_pc(repo):
    zip_, _ = empaquetar.construir(repo, repo / "salida")
    z = zipfile.ZipFile(zip_)
    for n in z.namelist():
        if not n.endswith((".ico", ".png")):
            assert b"/home/" not in z.read(n) and b"Practicas-IA" not in z.read(n), n


def test_no_se_genera_el_zip_si_un_script_perdio_el_bom(repo):
    ruta = repo / "instalador" / "instalar.ps1"
    ruta.write_bytes(ruta.read_bytes().removeprefix(BOM))
    with pytest.raises(empaquetar.ErrorDePaquete, match="BOM"):
        empaquetar.construir(repo, repo / "salida")
    assert not (repo / "salida").exists() or not list((repo / "salida").glob("*.zip"))


def test_sin_frontend_compilado_no_se_genera(repo):
    shutil.rmtree(repo / "web" / "frontend" / "dist")
    with pytest.raises(empaquetar.ErrorDePaquete, match="construir.sh"):
        empaquetar.construir(repo, repo / "salida")


def test_frontend_mas_viejo_que_su_codigo_no_se_empaqueta(repo):
    (repo / "web" / "frontend" / "src").mkdir(parents=True, exist_ok=True)
    nuevo = repo / "web" / "frontend" / "src" / "App.tsx"
    nuevo.write_text("x")
    pasado = time.time() - 3600
    os.utime(repo / "web" / "frontend" / "dist" / "index.html", (pasado, pasado))
    with pytest.raises(empaquetar.ErrorDePaquete, match="más viejo"):
        empaquetar.construir(repo, repo / "salida")


def test_el_icono_real_trae_todas_las_resoluciones():
    pytest.importorskip("PIL")
    from PIL import IcoImagePlugin
    import io
    ico = IcoImagePlugin.IcoFile(io.BytesIO(empaquetar.icono_ico(RAIZ)))
    assert {s[0] for s in ico.sizes()} >= {16, 32, 48, 256}


# ---------- lo que no viaja y lo que sí ----------

def test_config_ejemplo_tiene_las_mismas_claves_que_la_base_y_ningun_secreto():
    ejemplo = json.loads((RAIZ / "config.ejemplo.json").read_text())
    assert set(ejemplo) == set(reputacion.CONFIG_BASE)
    assert ejemplo["malwarebazaar_key"] == "" and ejemplo["boton_dashboard"] is True


def test_la_plantilla_de_claude_md_solo_tiene_reglas_de_usuario():
    t = (RAIZ / "plantillas" / "CLAUDE.usuario.md").read_text()
    for pedido in ("buscar_memoria", "hechos_conocidos", "changelog_abierto", "registrar_changelog", "resolver_changelog", "explícita"):
        assert pedido in t
    for ajeno in ("git", "pytest", "bitácora", "registrar_bitacora", "commit", "sudo"):
        assert ajeno not in t.lower()
    assert "## Memoria de la PC (pc-doctor)" in t        # instalar.ps1 usa este encabezado para no agregarla dos veces
    assert "## Memoria de la PC (pc-doctor)" in (RAIZ / "instalador" / "instalar.ps1").read_text(encoding="utf-8-sig")

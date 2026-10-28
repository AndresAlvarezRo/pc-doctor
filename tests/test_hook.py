"""Hook pre-commit (scripts/pre-commit) e instalador (scripts/instalar-hooks.sh), probados con repositorios git temporales.

Los secretos falsos se arman en tiempo de ejecución: ningún archivo del repositorio contiene uno completo."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import RAIZ

pytestmark = pytest.mark.lento   # crean repositorios git temporales: corren en la suite completa y en CI, no en cada commit

HOOK = RAIZ / "scripts" / "pre-commit"
INSTALADOR = RAIZ / "scripts" / "instalar-hooks.sh"

# secretos falsos con la forma real, armados por partes
GITHUB = "gh" + "p_" + "A1b2C3d4E5" * 3 + "F6g7H8"
GITHUB_PAT = "github" + "_pat_" + "11ABCDEFG0" + "x" * 22
ANTHROPIC = "sk-" + "ant-api03-" + "Zz9" * 12
AWS = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
CLAVE_PRIVADA = "-----" + "BEGIN RSA PRIVATE" + " KEY-----"
CLAVE_LARGA = "a1B2c3D4" * 6


@pytest.fixture
def repo(tmp_path):
    """Un repositorio git vacío, con el hook copiado y las pruebas rápidas desactivadas (se prueban aparte)."""
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    for k, v in (("user.name", "Prueba"), ("user.email", "prueba@example.com"), ("commit.gpgsign", "false")):
        subprocess.run(["git", "config", k, v], cwd=r, check=True)
    (r / "scripts").mkdir()
    shutil.copy(HOOK, r / "scripts" / "pre-commit")
    (r / "scripts" / "pre-commit").chmod(0o755)
    shutil.copy(INSTALADOR, r / "scripts" / "instalar-hooks.sh")
    return r


def agregar(repo, ruta, contenido="x\n", binario=False):
    p = repo / ruta
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(contenido if binario else contenido.encode())
    subprocess.run(["git", "add", "-f", ruta], cwd=repo, check=True)
    return p


def hook(repo, **env):
    e = {**os.environ, "PC_DOCTOR_HOOK_SIN_PRUEBAS": "1", **env}
    return subprocess.run([sys.executable, "scripts/pre-commit"], cwd=repo, capture_output=True, text=True, env=e)


# ---------- por nombre ----------

@pytest.mark.parametrize("ruta", ["doctor.db", "datos/doctor.db", "x/y/respaldo.db", "doctor.db-wal", "doctor.db-shm",
                                  "doctor.db.antes-de-juego-1793", "config.json", "datos/config.json", "web_token", "datos/cualquier_cosa.txt",
                                  "datos/reportes/2026-10-28.md", "base.sqlite", "base.sqlite3"])
def test_bloquea_datos_y_secretos_por_su_nombre(repo, ruta):
    agregar(repo, ruta)
    r = hook(repo)
    assert r.returncode == 1 and "BLOQUEADO" in r.stderr and ruta in r.stderr


def test_bloquea_el_enlace_simbolico_datos(repo):
    (repo / "datos").symlink_to("/tmp")
    subprocess.run(["git", "add", "-f", "datos"], cwd=repo, check=True)
    r = hook(repo)
    assert r.returncode == 1 and "datos/" in r.stderr


@pytest.mark.parametrize("ruta", ["main.py", "datos_de_prueba.py", "web/datos_de_prueba.py", "web/frontend/package.json", "tsconfig.json",
                                  "docs/config.json.md", "mi_database.txt", "notas_db.md", "scripts/web_tokens.md".replace("web_tokens", "web-token")])
def test_no_bloquea_nombres_parecidos_pero_inofensivos(repo, ruta):
    agregar(repo, ruta)
    assert hook(repo).returncode == 0


# ---------- secretos en el contenido ----------

@pytest.mark.parametrize("contenido,tipo", [
    (f"TOKEN = '{GITHUB}'\n", "token de GitHub"), (f"x = '{GITHUB_PAT}'\n", "token de GitHub (granular)"),
    (f"k = '{ANTHROPIC}'\n", "Anthropic"), (f"clave = {AWS}\n", "AWS"),
    (f"{CLAVE_PRIVADA}\nMIIE...\n", "clave privada"),
    ("password=hunter2xyz\n", "contraseña"), ('{"password": "S3cretaLarga"}\n', "contraseña"), ("PASSWORD = 'abcd1234'\n", "contraseña"),  # permitir-secreto: son ejemplos falsos a propósito
    (f"api_key = '{CLAVE_LARGA}'\n", "clave de API"), (f'"token": "{CLAVE_LARGA}"\n', "clave de API"),
])
def test_bloquea_algo_con_forma_de_secreto(repo, contenido, tipo):
    agregar(repo, "config_de_ejemplo.py", contenido)
    r = hook(repo)
    assert r.returncode == 1 and tipo.lower() in r.stderr.lower() and "config_de_ejemplo.py:1" in r.stderr


def test_el_mensaje_enmascara_el_secreto(repo):
    agregar(repo, "a.py", f"TOKEN = '{GITHUB}'\n")
    r = hook(repo)
    assert GITHUB not in r.stderr and GITHUB[:4] in r.stderr and "caracteres" in r.stderr


@pytest.mark.parametrize("contenido", [
    "password = input('Contraseña: ')\n", "password: str\n", "def f(password: str, token: int): pass\n", "password = None\n",
    "password=\n", "pwd = 'abc'\n", "x = 'ghp_corto'\n", "token = 'abc'\n", 'texto = "la clave está en el gestor de contraseñas"\n',
    "CLAVES_SECRETAS = re.compile(r'key|token|secret|clave|password')\n", "api_key = os.environ['API_KEY']\n",
    f"password = 'ejemplo-falso'  # {'permitir' + '-secreto'}\n", "# -----BEGIN ... PRIVATE KEY----- (solo texto de ayuda)\n",  # permitir-secreto: ejemplo falso a propósito
])
def test_no_bloquea_codigo_normal_ni_falsos_positivos(repo, contenido):
    agregar(repo, "codigo.py", contenido)
    assert hook(repo).returncode == 0, hook(repo).stderr


def test_solo_se_revisan_las_lineas_agregadas_no_lo_que_ya_estaba(repo):
    agregar(repo, "ejemplo.py", f"VIEJO = '{GITHUB}'  # permitir-secreto\n")
    subprocess.run(["git", "commit", "-q", "--no-verify", "-m", "base"], cwd=repo, check=True)
    # se quita la marca de la línea vieja SIN tocar el secreto: esa línea es "modificada", así que sí se revisa
    agregar(repo, "ejemplo.py", f"VIEJO = '{GITHUB}'  # permitir-secreto\nNUEVA = 1\n")
    assert hook(repo).returncode == 0                                   # solo se agregó una línea inocente
    agregar(repo, "ejemplo.py", f"VIEJO = '{GITHUB}'  # permitir-secreto\nNUEVA = '{GITHUB_PAT}'\n")
    assert hook(repo).returncode == 1                                   # la línea agregada con un secreto bloquea


def test_el_numero_de_linea_es_el_de_la_linea_agregada(repo):
    agregar(repo, "a.py", "uno\ndos\ntres\n")
    subprocess.run(["git", "commit", "-q", "--no-verify", "-m", "base"], cwd=repo, check=True)
    agregar(repo, "a.py", f"uno\ndos\ntres\ncuatro\nTOKEN = '{GITHUB}'\n")
    assert "a.py:5" in hook(repo).stderr


def test_la_marca_permitir_secreto_se_respeta_solo_en_esa_linea(repo):
    agregar(repo, "a.py", f"A = '{GITHUB}'  # permitir-secreto\nB = '{GITHUB}'\n")
    r = hook(repo)
    assert r.returncode == 1 and "a.py:2" in r.stderr and "a.py:1" not in r.stderr


def test_se_revisa_lo_indexado_no_el_archivo_de_trabajo(repo):
    agregar(repo, "a.py", "limpio = 1\n")                                # lo que va al commit es inocente
    (repo / "a.py").write_text(f"T = '{GITHUB}'\n")                       # pero el archivo de trabajo cambió después
    assert hook(repo).returncode == 0


def test_los_archivos_binarios_no_se_escanean_pero_si_se_pesan(repo):
    agregar(repo, "icono.png", b"\x89PNG\0\0" + GITHUB.encode(), binario=True)
    assert hook(repo).returncode == 0


# ---------- tamaño ----------

def test_bloquea_archivos_de_mas_de_1_mib_y_acepta_uno_justo(repo):
    agregar(repo, "justo.bin", b"\0" * (1024 * 1024), binario=True)
    assert hook(repo).returncode == 0
    agregar(repo, "grande.bin", b"\0" * (1024 * 1024 + 1), binario=True)
    r = hook(repo)
    assert r.returncode == 1 and "grande.bin" in r.stderr and "1 MiB" in r.stderr


def test_un_archivo_de_texto_grande_tambien_se_bloquea_por_tamano(repo):
    agregar(repo, "log.txt", "linea de texto normal\n" * 60000)
    r = hook(repo)
    assert r.returncode == 1 and "log.txt" in r.stderr and "MiB" in r.stderr


# ---------- altas, bajas y varios problemas ----------

def test_dar_de_baja_un_archivo_prohibido_esta_permitido(repo):
    agregar(repo, "doctor.db")
    subprocess.run(["git", "commit", "-q", "--no-verify", "-m", "se coló por error"], cwd=repo, check=True)
    subprocess.run(["git", "rm", "-q", "--cached", "doctor.db"], cwd=repo, check=True)
    assert hook(repo).returncode == 0                                    # sacarlo del repositorio es justo lo que hay que poder hacer


def test_informa_todos_los_problemas_juntos(repo):
    agregar(repo, "doctor.db")
    agregar(repo, "a.py", f"X = '{GITHUB}'\n")
    agregar(repo, "b.bin", b"\0" * (1024 * 1024 + 5), binario=True)
    r = hook(repo)
    assert "3 problema(s)" in r.stderr and "doctor.db" in r.stderr and "a.py:1" in r.stderr and "b.bin" in r.stderr


def test_un_commit_limpio_pasa_y_lo_dice(repo):
    agregar(repo, "bien.py", "print('hola')\n")
    r = hook(repo)
    assert r.returncode == 0 and "pre-commit: OK" in r.stdout


def test_el_propio_hook_y_los_archivos_de_pruebas_pasan_su_propia_revision(repo):
    for ruta in ("scripts/pre-commit", "scripts/instalar-hooks.sh", "tests/test_hook.py"):
        agregar(repo, ruta, (RAIZ / ruta).read_text())
    r = hook(repo)
    assert r.returncode == 0, r.stderr


# ---------- pruebas rápidas ----------

def uv_falso(tmp_path, codigo, salida=""):
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    u = d / "uv"
    u.write_text(f"#!/bin/sh\necho '{salida}'\necho \"$@\" > '{tmp_path}/uv_llamado.txt'\nexit {codigo}\n")
    u.chmod(0o755)
    return d


def hook_con_pruebas(repo, ruta_path):
    env = {k: v for k, v in os.environ.items() if k != "PC_DOCTOR_HOOK_SIN_PRUEBAS"}
    env["PATH"] = f"{ruta_path}:/usr/bin:/bin"
    return subprocess.run([sys.executable, "scripts/pre-commit"], cwd=repo, capture_output=True, text=True, env=env)


def test_si_fallan_las_pruebas_rapidas_bloquea_y_muestra_el_final(repo, tmp_path):
    agregar(repo, "bien.py", "x = 1\n")
    r = hook_con_pruebas(repo, uv_falso(tmp_path, 1, "FAILED tests/test_x.py::test_roto - assert 1 == 2"))
    assert r.returncode == 1 and "pruebas rápidas" in r.stderr and "test_roto" in r.stderr
    assert "run pytest -m not lento" in (tmp_path / "uv_llamado.txt").read_text()   # llama exactamente al subconjunto rápido


def test_si_pasan_las_pruebas_rapidas_el_commit_sigue(repo, tmp_path):
    agregar(repo, "bien.py", "x = 1\n")
    r = hook_con_pruebas(repo, uv_falso(tmp_path, 0))
    assert r.returncode == 0 and "pruebas rápidas OK" in r.stdout


def test_sin_uv_bloquea_con_un_mensaje_claro(repo, tmp_path):
    agregar(repo, "bien.py", "x = 1\n")
    r = hook_con_pruebas(repo, tmp_path / "vacio")
    assert r.returncode == 1 and "uv" in r.stderr


def test_los_problemas_de_archivos_se_informan_sin_correr_las_pruebas(repo, tmp_path):
    agregar(repo, "doctor.db")
    r = hook_con_pruebas(repo, uv_falso(tmp_path, 0))
    assert r.returncode == 1 and not (tmp_path / "uv_llamado.txt").exists()


# ---------- integración con git y el instalador ----------

def test_el_instalador_enlaza_el_hook_y_se_puede_repetir(repo):
    r1 = subprocess.run(["bash", "scripts/instalar-hooks.sh"], cwd=repo, capture_output=True, text=True)
    enlace = repo / ".git" / "hooks" / "pre-commit"
    assert r1.returncode == 0 and enlace.is_symlink() and enlace.resolve() == (repo / "scripts" / "pre-commit").resolve()
    assert os.readlink(enlace) == "../../scripts/pre-commit"           # enlace relativo
    r2 = subprocess.run(["bash", "scripts/instalar-hooks.sh"], cwd=repo, capture_output=True, text=True)
    assert r2.returncode == 0 and "ya estaba instalado" in r2.stdout


def test_el_instalador_guarda_un_hook_anterior(repo):
    previo = repo / ".git" / "hooks" / "pre-commit"
    previo.write_text("#!/bin/sh\necho viejo\n")
    subprocess.run(["bash", "scripts/instalar-hooks.sh"], cwd=repo, check=True, capture_output=True)
    assert (repo / ".git" / "hooks" / "pre-commit.antes").read_text() == "#!/bin/sh\necho viejo\n"
    assert (repo / ".git" / "hooks" / "pre-commit").is_symlink()


def test_git_commit_con_el_hook_instalado_bloquea_lo_malo_y_deja_pasar_lo_bueno(repo):
    subprocess.run(["bash", "scripts/instalar-hooks.sh"], cwd=repo, check=True, capture_output=True)
    env = {**os.environ, "PC_DOCTOR_HOOK_SIN_PRUEBAS": "1"}
    agregar(repo, "doctor.db")
    r = subprocess.run(["git", "commit", "-q", "-m", "malo"], cwd=repo, capture_output=True, text=True, env=env)
    assert r.returncode != 0 and "BLOQUEADO" in r.stderr
    assert subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True).returncode != 0      # no se creó ningún commit
    subprocess.run(["git", "rm", "-q", "-f", "--cached", "doctor.db"], cwd=repo, check=True)
    agregar(repo, "bien.py", "x = 1\n")
    r = subprocess.run(["git", "commit", "-q", "-m", "bueno"], cwd=repo, capture_output=True, text=True, env=env)
    assert r.returncode == 0 and subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True).returncode == 0
    agregar(repo, "otro.db")
    r = subprocess.run(["git", "commit", "-q", "--no-verify", "-m", "saltado a propósito"], cwd=repo, capture_output=True, text=True, env=env)
    assert r.returncode == 0                                              # --no-verify sigue siendo la salida de emergencia

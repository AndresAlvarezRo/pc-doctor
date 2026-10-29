"""instalador/lanzador.pyw: lanza un programa sin consola y deja su salida en un log que se rota."""

import importlib.machinery
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

RUTA = Path(__file__).resolve().parent.parent / "instalador" / "lanzador.pyw"


@pytest.fixture
def lanzador(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("lanzador_prueba", RUTA, loader=importlib.machinery.SourceFileLoader("lanzador_prueba", str(RUTA)))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    programa = tmp_path / "programa"
    programa.mkdir()
    monkeypatch.setattr(m, "PROGRAMA", programa)
    monkeypatch.setenv("PC_DOCTOR_DATOS", str(tmp_path / "datos"))
    return m


def correr(lanzador, argv, monkeypatch):
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(sys, "argv", sys.argv)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.chdir(Path.cwd())
    return lanzador.main(argv)


def test_la_salida_del_programa_va_al_log(lanzador, monkeypatch, tmp_path):
    (lanzador.PROGRAMA / "hola.py").write_text("import sys\nprint('salida', sys.argv[1:])\nprint('error', file=sys.stderr)\n")
    assert correr(lanzador, ["hola.py", "uno"], monkeypatch) == 0
    sys.stdout.flush()
    log = (tmp_path / "datos" / "logs" / "hola.log").read_text()
    assert "salida ['uno']" in log and "error" in log


def test_lanza_un_modulo_con_menos_m(lanzador, monkeypatch, tmp_path):
    (lanzador.PROGRAMA / "modulo_de_prueba.py").write_text("print('corrió', __name__)\n")
    assert correr(lanzador, ["-m", "modulo_de_prueba"], monkeypatch) == 0
    assert "corrió __main__" in (tmp_path / "datos" / "logs" / "modulo_de_prueba.log").read_text()


def test_rota_el_log_cuando_pasa_de_un_mega(lanzador, tmp_path):
    carpeta = tmp_path / "datos" / "logs"
    carpeta.mkdir(parents=True)
    (carpeta / "x.log").write_text("a" * (lanzador.MAX_LOG + 1))
    f = lanzador.abrir_log("x")
    f.close()
    assert (carpeta / "x.log.1").stat().st_size > lanzador.MAX_LOG and (carpeta / "x.log").stat().st_size == 0


def test_sin_argumentos_no_hace_nada(lanzador, capsys):
    assert lanzador.main([]) == 2


def test_un_error_del_programa_queda_en_el_log_y_sale_con_codigo_distinto_de_cero(tmp_path):
    (tmp_path / "rota.py").write_text("raise RuntimeError('se rompió')\n")
    # proceso aparte: el lanzador cambia la salida estándar del proceso, y acá no conviene hacerlo en el de pytest
    copia = tmp_path / "lanzador.pyw"
    copia.write_text(RUTA.read_text())
    r = subprocess.run([sys.executable, "-I", str(copia), "rota.py"], capture_output=True, text=True, env={"PC_DOCTOR_DATOS": str(tmp_path / "datos")})
    assert r.returncode == 1
    assert "se rompió" in (tmp_path / "datos" / "logs" / "rota.log").read_text()

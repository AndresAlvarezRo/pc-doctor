"""Lanza un programa de pc-doctor sin ventana (lo usan las tareas programadas de Windows con pythonw.exe).

pythonw no tiene consola: lo que el programa escriba por stdout/stderr (el log del recolector, los avisos de uvicorn) se perdería.
Acá se redirige a %LOCALAPPDATA%\\pc-doctor\\logs\\<nombre>.log, que se rota al pasar de 1 MB.
Uso: lanzador.pyw collector.py [argumentos]   |   lanzador.pyw -m uvicorn web.api:app [argumentos]
"""

import os
import runpy
import sys
from pathlib import Path

PROGRAMA = Path(__file__).resolve().parent
MAX_LOG = 1024 * 1024


def carpeta_logs() -> Path:
    base = os.environ.get("PC_DOCTOR_DATOS") or os.path.join(os.environ.get("LOCALAPPDATA") or str(Path.home()), "pc-doctor")
    return Path(base) / "logs"


def abrir_log(nombre: str):
    """Abre el log en modo agregar, rotándolo a `.1` si pasó de MAX_LOG. Devuelve None si no se puede escribir."""
    try:
        carpeta = carpeta_logs()
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta = carpeta / f"{nombre}.log"
        if ruta.exists() and ruta.stat().st_size > MAX_LOG:
            os.replace(ruta, ruta.with_suffix(".log.1"))
        return open(ruta, "a", encoding="utf-8", errors="replace", buffering=1)
    except OSError:
        return None


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    modulo = argv[0] == "-m"
    if modulo and len(argv) < 2:
        return 2
    destino = argv[1] if modulo else argv[0]
    log = abrir_log(Path(destino).stem if not modulo else destino.split(".")[0].split(":")[0])
    if log is not None:
        sys.stdout = sys.stderr = log
    os.chdir(PROGRAMA)
    sys.path.insert(0, str(PROGRAMA))
    if modulo:
        sys.argv = [destino, *argv[2:]]
        runpy.run_module(destino, run_name="__main__", alter_sys=True)
    else:
        sys.argv = [str(PROGRAMA / destino), *argv[1:]]
        runpy.run_path(str(PROGRAMA / destino), run_name="__main__")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except BaseException:
        import traceback
        traceback.print_exc()
        sys.exit(1)

"""Arma el paquete de instalación para Windows: pc-doctor-Win-v<VERSION_PAQUETE>.zip y su .sha256, en la carpeta `paquetes/`.

Uso: `uv run --with pillow empaquetar.py` (Pillow solo hace falta para generar icono.ico). Antes hay que compilar el frontend
(`bash web/construir.sh`): el paquete lleva `web/frontend/dist/` ya compilado porque la PC de destino no tiene Node.

Qué lleva: el código que corre en producción, pyproject.toml y uv.lock, los scripts de instalar/ (en la raíz del zip), la plantilla
de config, la plantilla de CLAUDE.md y el ícono. Qué NO lleva nunca: pruebas, git, scripts de desarrollo, capturas, node_modules,
ni nada de esta PC (base de datos, config.json, web_token, hechos conocidos, bitácora, memoria). Y falla, sin generar el zip, si:
  - algún archivo contiene la cadena de prueba EICAR o es un ejecutable de Windows (Defender pondría el zip entero en cuarentena),
  - algún .ps1 perdió la marca de orden de bytes UTF-8 (Windows PowerShell 5.1 lo leería como ANSI y rompería los acentos),
  - algún archivo de texto nombra una ruta absoluta de esta PC,
  - el frontend compilado no existe o es más viejo que su código.
"""

import hashlib
import io
import re
import sys
import tomllib
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
SALIDA = RAIZ / "paquetes"
VERSION_PAQUETE = "1.0"                 # versión del paquete de Windows (aparte de la de pyproject.toml)
FECHA_ZIP = (2026, 1, 1, 0, 0, 0)       # fija: el mismo contenido da siempre el mismo zip (y el mismo SHA-256)

# El código que corre en producción (en la raíz del zip, con la misma estructura que el repo).
EXCLUIR_RAIZ = {"empaquetar.py"}
CARPETAS_CODIGO = ("plataforma",)
SUELTOS = ("pyproject.toml", "uv.lock", "config.ejemplo.json", "web/api.py")
EXTENSIONES_FRONTEND = {".ts", ".tsx", ".css", ".html", ".json", ".svg", ".png"}
DE_INSTALADOR_A_RAIZ = "instalador"      # todo lo de instalador/ va en la raíz del zip
NOMBRES_PROHIBIDOS = {"doctor.db", "config.json", "web_token", "datos", "BITACORA.md", "CHANGELOG.md"}

# Se arma por partes para que este archivo no se confunda con una muestra (y para que ningún antivirus lo marque).
EICAR = ("X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + "EICAR-STANDARD-ANTIVIRUS-TEST-FILE" + "!$H+H*").encode()
RUTAS_DE_ESTA_PC = re.compile(rb"/home/[A-Za-z0-9_.-]+/|Practicas-IA|C:\\Users\\[A-Za-z0-9_. -]+\\")


class ErrorDePaquete(Exception):
    """Algo hace inseguro o inútil el paquete: no se genera."""


def version(raiz: Path = RAIZ) -> str:
    return tomllib.loads((raiz / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def _archivos(carpeta: Path, patron: str = "*"):
    return sorted(p for p in carpeta.rglob(patron) if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")


def icono_ico(raiz: Path = RAIZ) -> bytes:
    """icono.ico con 16, 24, 32, 48, 64, 128 y 256 px, dibujado con el mismo código que los PNG del dashboard."""
    try:
        sys.path.insert(0, str(raiz))
        from web.generar_iconos import dibujar
    except ImportError as e:
        raise ErrorDePaquete(f"Falta Pillow para generar icono.ico ({e}). Corré: uv run --with pillow empaquetar.py") from e
    finally:
        sys.path.remove(str(raiz))
    sal = io.BytesIO()
    dibujar(256).save(sal, format="ICO", sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
    return sal.getvalue()


def revisar_frontend(raiz: Path = RAIZ) -> None:
    dist = raiz / "web" / "frontend" / "dist"
    if not (dist / "index.html").is_file():
        raise ErrorDePaquete("No está el frontend compilado (web/frontend/dist). Corré: bash web/construir.sh")
    fuentes = [p for p in (raiz / "web" / "frontend" / "src").rglob("*") if p.is_file()] + [raiz / "web" / "frontend" / "package.json"]
    reciente = max(p.stat().st_mtime for p in fuentes if p.exists())
    if (dist / "index.html").stat().st_mtime < reciente:
        raise ErrorDePaquete("El frontend compilado es más viejo que su código fuente. Corré: bash web/construir.sh")


def reunir(raiz: Path = RAIZ) -> dict[str, bytes]:
    """{ruta dentro del zip: contenido}. Solo lo de la lista blanca."""
    res: dict[str, bytes] = {}

    def sumar(arcname: str, ruta: Path):
        res[arcname] = ruta.read_bytes()

    for p in sorted(raiz.glob("*.py")):
        if p.name not in EXCLUIR_RAIZ:
            sumar(p.name, p)
    for carpeta in CARPETAS_CODIGO:
        for p in _archivos(raiz / carpeta, "*.py"):
            sumar(p.relative_to(raiz).as_posix(), p)
    for s in SUELTOS:
        sumar(s, raiz / s)
    for p in _archivos(raiz / "web" / "frontend" / "dist"):
        sumar(p.relative_to(raiz).as_posix(), p)
    for p in _archivos(raiz / "plantillas"):
        sumar(p.relative_to(raiz).as_posix(), p)
    for p in _archivos(raiz / DE_INSTALADOR_A_RAIZ):
        sumar(p.relative_to(raiz / DE_INSTALADOR_A_RAIZ).as_posix(), p)
    res["icono.ico"] = icono_ico(raiz)
    return res


def verificar(contenido: dict[str, bytes]) -> None:
    """Levanta ErrorDePaquete con todo lo que está mal, no solo con el primer problema."""
    problemas = []
    for nombre, datos in sorted(contenido.items()):
        partes = set(Path(nombre).parts)
        if partes & NOMBRES_PROHIBIDOS or partes & {"tests", ".git", ".github", "scripts", "node_modules", "capturas", "venv", ".venv"}:
            problemas.append(f"{nombre}: no debe ir en el paquete")
        if EICAR in datos:
            problemas.append(f"{nombre}: contiene la cadena de prueba EICAR (Defender pondría el zip en cuarentena)")
        if datos[:2] == b"MZ":
            problemas.append(f"{nombre}: es un ejecutable de Windows (el paquete no lleva binarios; se descargan verificados)")
        if nombre.endswith(".ps1") and not datos.startswith(b"\xef\xbb\xbf"):
            problemas.append(f"{nombre}: perdió la marca de orden de bytes UTF-8 (BOM); PowerShell 5.1 rompería los acentos")
        if not nombre.endswith((".ico", ".png")) and (m := RUTAS_DE_ESTA_PC.search(datos)):
            problemas.append(f"{nombre}: nombra una ruta de esta PC ({m.group().decode(errors='replace')})")
    for obligatorio in ("instalar.ps1", "habilitar-sensores.ps1", "ayudante.ps1", "versiones.toml", "lanzador.pyw", "INSTALAR-WINDOWS.md", "PROMPT-VERIFICACION.md",
                        "config.ejemplo.json", "plantillas/CLAUDE.usuario.md", "icono.ico", "uv.lock", "pyproject.toml",
                        "web/frontend/dist/index.html", "collector.py", "server.py", "web/api.py"):
        if obligatorio not in contenido:
            problemas.append(f"{obligatorio}: falta")
    if problemas:
        raise ErrorDePaquete("No se generó el paquete:\n  - " + "\n  - ".join(problemas))


def construir(raiz: Path = RAIZ, salida: Path | None = None) -> tuple[Path, str]:
    """Genera el zip y su .sha256. Devuelve (ruta del zip, sha256)."""
    revisar_frontend(raiz)
    contenido = reunir(raiz)
    verificar(contenido)
    salida = salida or SALIDA
    salida.mkdir(parents=True, exist_ok=True)
    destino = salida / f"pc-doctor-Win-v{VERSION_PAQUETE}.zip"
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for nombre in sorted(contenido):
            info = zipfile.ZipInfo(nombre, FECHA_ZIP)
            info.compress_type, info.external_attr = zipfile.ZIP_DEFLATED, 0o644 << 16
            z.writestr(info, contenido[nombre])
    suma = hashlib.sha256(destino.read_bytes()).hexdigest()
    destino.with_name(destino.name + ".sha256").write_text(f"{suma}  {destino.name}\n", encoding="utf-8")
    return destino, suma


def main() -> int:
    try:
        zip_, suma = construir()
    except ErrorDePaquete as e:
        print(e, file=sys.stderr)
        return 1
    with zipfile.ZipFile(zip_) as z:
        n = len(z.namelist())
    print(f"{zip_}\n  {n} archivos, {zip_.stat().st_size / 1e6:.1f} MB\n  SHA-256: {suma}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

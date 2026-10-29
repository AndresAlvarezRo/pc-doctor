"""Invocación aislada de `claude -p`, compartida por el reporte semanal y el diagnóstico de alertas.

Todo lo que decide qué puede hacer el modelo vive acá, en un solo lugar (ver la bitácora, invariante del `claude -p`):
- `--tools ""`: sin herramientas integradas (Bash, Write, Edit, web).
- `--strict-mcp-config` con un `--mcp-config` que carga SOLO el MCP de pc-doctor (los demás MCP de la cuenta no se cargan).
- `--allowedTools` con las tools de lectura que pasa quien llama, una por una; `--permission-mode dontAsk` niega todo lo demás.
- `--disallowedTools` con las prohibidas por nombre (prohibir pesa más que permitir).
- Sin `CLAUDE.md` ni memoria, sin ajustes ni hooks del usuario, sin guardar la sesión, en una carpeta de trabajo neutra.
- El prompt va por stdin: las opciones `--allowedTools`, `--tools` y `--mcp-config` aceptan varios valores y lo habrían absorbido.
Quien llama valida la respuesta: lo que dice el modelo es texto no confiable.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

import db
import plataforma

PREFIJO_MCP = "mcp__pc-doctor__"
INTEGRADAS_PROHIBIDAS = ["Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch", "Task", "Agent"]


def ruta_claude(cfg: dict) -> str | None:
    """Ruta absoluta de claude (systemd no hereda el PATH del usuario); None si no existe."""
    for c in (cfg.get("claude"), str(Path.home() / ".local" / "bin" / "claude"), str(Path.home() / ".local" / "bin" / "claude.exe"), shutil.which("claude")):
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return c
    return None


def ruta_uv() -> str:
    """uv del PATH; si no, el de ~/.local/bin; en Windows, también el que deja instalar.ps1 junto al programa."""
    propio = Path(__file__).resolve().parent / "herramientas" / "uv.exe"
    return shutil.which("uv") or (str(propio) if propio.is_file() else str(Path.home() / ".local" / "bin" / "uv"))


def config_mcp() -> str:
    """JSON con SOLO el servidor de pc-doctor (el resto de los MCP de la cuenta, como web o Drive, no se cargan)."""
    uv = ruta_uv()
    srv = {"command": uv, "args": ["run", "--directory", str(Path(__file__).resolve().parent), "server.py"]}
    if os.environ.get("PC_DOCTOR_DATOS"):
        srv["env"] = {"PC_DOCTOR_DATOS": os.environ["PC_DOCTOR_DATOS"]}
    return json.dumps({"mcpServers": {"pc-doctor": srv}})


def construir_comando(claude: str, cfg: dict, permitidas: list[str], prohibidas: list[str]) -> list[str]:
    """El prompt NO va en los argumentos: se pasa por stdin."""
    cmd = [claude, "-p", "--output-format", "text", "--max-turns", str(cfg["max_turns"]),
           "--permission-mode", "dontAsk",          # lo que no esté pre-aprobado se deniega, no se pregunta
           "--tools", "",                           # sin herramientas integradas (Bash, Write, Edit, web...)
           "--strict-mcp-config", "--mcp-config", config_mcp(),
           "--allowedTools", ",".join(PREFIJO_MCP + h for h in permitidas),
           "--disallowedTools", ",".join([PREFIJO_MCP + h for h in prohibidas] + INTEGRADAS_PROHIBIDAS),
           "--no-session-persistence", "--setting-sources", "project"]  # no carga ajustes ni hooks del usuario
    if cfg.get("modelo"):
        cmd += ["--model", cfg["modelo"]]
    return cmd


def clasificar_error(codigo: int, texto: str) -> str:
    t = texto.lower()
    if re.search(r"not logged in|please run /login|invalid api key|authentication|unauthorized|\b401\b|oauth", t):
        return "claude no tiene sesión iniciada (ejecutá `claude` y hacé /login)"
    if re.search(r"usage limit|rate limit|limit reached|quota|credit balance|\b429\b|overloaded|too many requests", t):
        return "límite de uso de Claude alcanzado"
    if re.search(r"enotfound|econnrefused|econnreset|network|fetch failed|unable to connect|getaddrinfo|connection error", t):
        return "sin conexión a internet"
    return f"error de claude (código {codigo}): {' '.join(texto.split())[:150]}"


def _grupo_de_procesos() -> dict:
    """Argumentos de Popen para que claude y el servidor MCP que lanza formen un grupo que se pueda matar junto."""
    if plataforma.actual().NOMBRE == "windows":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200) | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {"start_new_session": True}


def _matar_arbol(p: subprocess.Popen) -> None:
    if plataforma.actual().NOMBRE == "windows":
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True, timeout=30)
    else:
        os.killpg(p.pid, signal.SIGKILL)


def pedir(prompt: str, cfg: dict, permitidas: list[str], prohibidas: list[str], carpeta: str) -> tuple[str | None, str | None, float]:
    """(salida, motivo_del_fallo, segundos). Con salida None, `motivo` explica por qué hay que usar el plan B.

    `carpeta` es el nombre de una subcarpeta neutra de la carpeta de datos (sin CLAUDE.md del proyecto)."""
    claude = ruta_claude(cfg)
    if not claude:
        return None, "no encontré el ejecutable de claude", 0.0
    entorno = dict(os.environ)
    entorno.update({"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"})  # sin CLAUDE.md ni memoria
    base = "" if plataforma.actual().NOMBRE == "windows" else "/usr/bin:/bin"
    entorno["PATH"] = f"{Path.home() / '.local' / 'bin'}{os.pathsep}{entorno.get('PATH', base)}"
    cwd = db.DIR_DATOS / carpeta
    cwd.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    try:
        p = subprocess.Popen(construir_comando(claude, cfg, permitidas, prohibidas), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, cwd=cwd, env=entorno, **_grupo_de_procesos())
    except OSError as e:
        return None, f"no pude ejecutar claude: {e}", 0.0
    try:
        salida, err = p.communicate(prompt, timeout=cfg["timeout_s"])
    except subprocess.TimeoutExpired:
        _matar_arbol(p)  # mata también al servidor MCP que lanzó claude
        p.communicate()
        return None, f"tiempo agotado ({cfg['timeout_s']} s)", time.time() - t0
    seg = time.time() - t0
    if p.returncode != 0:
        return None, clasificar_error(p.returncode, f"{err}\n{salida}"), seg
    return salida.strip(), None, seg

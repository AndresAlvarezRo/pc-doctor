"""Reporte semanal con Claude: seguridad de la invocación de `claude -p`, plan B sin modelo y guardado.

`claude` es un reemplazo (tests/falsos/claude) que registra cómo lo llamaron. Rescatadas de las pruebas de la Fase 3 (BITACORA.md)."""

import inspect
import json
import os
import time

import pytest
from ayudas import FALSOS

import alertas
import db
import reporte
import server

pytestmark = pytest.mark.lento


@pytest.fixture
def config(monkeypatch):
    def poner(**extra):
        (db.DIR_DATOS / "config.json").write_text(json.dumps({"notificaciones": True, "reporte": {"claude": str(FALSOS / "claude"), **extra}}))
    poner()
    return poner


@pytest.fixture
def aviso(monkeypatch):
    enviadas = []
    monkeypatch.setattr(alertas, "notificar", lambda t, m, critica=False, seccion=None, **k: enviadas.append((t, m, seccion)) or True)
    return enviadas


def correr(con, argv=()):
    assert reporte.main(list(argv)) == 0
    fila = con.execute("SELECT * FROM reportes ORDER BY id DESC LIMIT 1").fetchone()
    return dict(fila), open(fila["ruta"]).read()


def test_exito_guarda_el_reporte_y_avisa(con, config, aviso, monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_CLAUDE_REGISTRO", str(tmp_path / "recibido.json"))
    fila, texto = correr(con)
    assert fila["modo"] == "claude" and fila["motivo"] is None and "## 8. Recomendaciones" in texto and texto.count("RESUMEN:") == 0
    assert fila["resumen"].startswith("Semana tranquila") and aviso and aviso[-1][2] == "reportes"   # el botón abre la sección de reportes
    assert "Redactado por Claude" in texto


def test_la_invocacion_de_claude_es_de_solo_lectura(con, config, aviso, monkeypatch, tmp_path):
    reg = tmp_path / "recibido.json"
    monkeypatch.setenv("FAKE_CLAUDE_REGISTRO", str(reg))
    correr(con)
    rec = json.loads(reg.read_text())
    a = rec["argv"]
    valor = lambda flag: a[a.index(flag) + 1]
    permitidas = valor("--allowedTools").split(",")
    prohibidas = valor("--disallowedTools").split(",")
    assert a[0] == "-p" and rec["stdin"].startswith("Generá el reporte"), "el prompt va por stdin (las opciones variádicas lo absorberían)"
    assert valor("--tools") == "" and valor("--permission-mode") == "dontAsk" and "--strict-mcp-config" in a and "--no-session-persistence" in a
    assert all(p.startswith("mcp__pc-doctor__") for p in permitidas)
    escriben = {"limpiar_descargas_viejas", "restaurar_cuarentena", "marcar_hallazgo", "revision_seguridad"}
    assert not any(p.split("__")[-1] in escriben for p in permitidas)
    assert escriben <= {p.split("__")[-1] for p in prohibidas if p.startswith("mcp__")}
    assert {"Bash", "Write", "Edit", "WebFetch", "WebSearch"} <= set(prohibidas) and not {"Bash", "Write", "Edit"} & set(permitidas)
    assert list(json.loads(valor("--mcp-config"))["mcpServers"]) == ["pc-doctor"], "solo se carga el MCP de pc-doctor"
    texto = rec["stdin"].lower()
    assert "datos no confiables" in texto and "no intentes modificar nada" in texto   # el prompt declara los datos como no confiables
    assert rec["env"]["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1" and rec["cwd"].endswith("/reportes")


def test_toda_tool_permitida_existe_en_el_servidor_y_no_escribe():
    """Si alguien agrega un efecto a una tool 'de lectura', o renombra una, esto falla."""
    reales = {t.name for t in server.mcp._tool_manager.list_tools()}
    assert set(reporte.HERRAMIENTAS_LECTURA) <= reales
    assert set(reporte.HERRAMIENTAS_PROHIBIDAS) & set(reporte.HERRAMIENTAS_LECTURA) == set()
    for nombre in reporte.HERRAMIENTAS_LECTURA:
        fuente = inspect.getsource(getattr(server, nombre))
        for efecto in ("_registrar_accion", "shutil.move", "INSERT", "UPDATE ", "DELETE", ".commit()", "revisar_y_guardar", "consultar_sospechosos"):
            assert efecto not in fuente, f"{nombre} tiene un efecto ({efecto}) y está permitida para el modelo"


@pytest.mark.parametrize("modo,esperado", [("login", "sesión"), ("limite", "límite"), ("red", "conexión"),
                                           ("otro", "error de claude (código 2)"), ("corta", "incompleta")])
def test_plan_b_cuando_claude_falla(con, config, aviso, monkeypatch, modo, esperado):
    monkeypatch.setenv("FAKE_CLAUDE_MODO", modo)
    fila, texto = correr(con)
    assert fila["modo"] == "determinista" and esperado in fila["motivo"] and "determinístico" in texto and "## 6. SMART" in texto
    assert "Sin redactar" in aviso[-1][1]


def test_plan_b_si_claude_se_cuelga_y_no_queda_el_proceso(con, config, aviso, monkeypatch, tmp_path):
    config(timeout_s=2)
    pidfile = tmp_path / "pid"
    monkeypatch.setenv("FAKE_CLAUDE_MODO", "cuelga")
    monkeypatch.setenv("FAKE_CLAUDE_PID", str(pidfile))
    t0 = time.time()
    fila, _ = correr(con)
    assert fila["modo"] == "determinista" and "tiempo agotado" in fila["motivo"] and time.time() - t0 < 12
    pid = int(pidfile.read_text())
    time.sleep(0.3)
    estado = open(f"/proc/{pid}/stat").read().split()[2] if os.path.exists(f"/proc/{pid}") else "Z"
    assert estado == "Z"  # muerto (o zombi pendiente de recoger)


def test_el_resumen_malicioso_se_limpia_en_el_archivo_y_en_la_notificacion(con, config, aviso, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODO", "malicioso")
    fila, _ = correr(con)
    assert not any(c in fila["resumen"] for c in "<>\x1b\n")
    assert not any(c in aviso[-1][1].split("\n")[1] for c in "<>\x1b")


def test_plan_b_si_no_hay_claude(con, config, aviso, monkeypatch):
    config(claude="/no/existe/claude")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")       # sin los reemplazos: no hay ningún `claude`
    fila, _ = correr(con)
    assert fila["modo"] == "determinista" and "no encontré" in fila["motivo"]


def test_opciones_sin_claude_sin_notificar_y_desactivado(con, config, aviso):
    fila, _ = correr(con, ["--sin-claude", "--sin-notificar"])
    assert fila["modo"] == "determinista" and not aviso
    (db.DIR_DATOS / "config.json").write_text(json.dumps({"reporte": False}))
    antes = len(list((db.DIR_DATOS / "reportes").glob("*.md")))
    reporte.main([])
    assert len(list((db.DIR_DATOS / "reportes").glob("*.md"))) == antes      # reporte desactivado: no genera nada


def test_las_tools_de_lectura_de_reportes(con, config, aviso):
    correr(con)
    assert server.ultimo_reporte()["modo"] == "claude" and "contenido" in server.ultimo_reporte()
    assert len(server.reportes(3)["reportes"]) == 1


@pytest.mark.parametrize("fecha", ["../../etc/passwd", "2026-99-99", "doctor", "2026-10-28/../x", ""])
def test_leer_un_reporte_no_sale_de_la_carpeta_de_reportes(con, config, aviso, fecha):
    correr(con)
    assert reporte.leer(con, fecha) is None


def test_limpiar_resumen_acota_el_largo():
    assert len(reporte.limpiar_resumen("a" * 1000)) == reporte.RESUMEN_MAX

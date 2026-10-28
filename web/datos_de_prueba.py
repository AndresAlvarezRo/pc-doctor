"""Genera una carpeta de datos SINTÉTICA para probar la API y el dashboard sin tocar la base real.

Uso: `uv run python web/datos_de_prueba.py /ruta/carpeta` y después, con esa carpeta:
`PC_DOCTOR_DATOS=/ruta/carpeta uv run uvicorn web.api:app --host 127.0.0.1 --port 8787` (desde la carpeta del proyecto).

Crea 120 días de lecturas cada 15 minutos (los últimos 30 crudos y el resto como registro diario, igual que la
retención real), sesiones de juego, una línea base madura, alertas, hallazgos, eventos, reportes, acciones y cambios de
entorno. Los nombres de sensores son los reales de este equipo; los valores son inventados. No usar los datos como diagnóstico.
"""

import json
import os
import random
import sys
import time
from pathlib import Path

if len(sys.argv) < 2:
    sys.exit("Uso: web/datos_de_prueba.py CARPETA_DESTINO")
DESTINO = Path(sys.argv[1]).resolve()
if (DESTINO / "doctor.db").exists():
    sys.exit(f"{DESTINO}/doctor.db ya existe: no se pisa. Usá una carpeta nueva.")
if DESTINO == (Path.home() / ".local" / "share" / "pc-doctor"):
    sys.exit("Esa es la carpeta de datos real: este script solo escribe en carpetas de prueba.")
DESTINO.mkdir(parents=True, exist_ok=True)
os.environ["PC_DOCTOR_DATOS"] = str(DESTINO)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db  # noqa: E402
import linea_base  # noqa: E402

DIAS, DIAS_CRUDOS, PASO = 120, 30, 900
H, D = 3600, 86400
# nombre, categoría, unidad, (reposo, carga, juego) valores centrales, ruido, deriva por día
SENSORES = [
    ("cpu/uso", "cpu", "%", (3, 45, 30), 2.5, 0), ("k10temp/Tctl", "cpu", "°C", (48, 65, 72), 1.8, 0.03),
    ("k10temp/Tccd1", "cpu", "°C", (45, 62, 68), 1.8, 0.02),
    ("amdgpu/uso", "gpu", "%", (3, 30, 85), 3, 0), ("amdgpu/junction", "gpu", "°C", (45, 60, 74), 1.2, 0),
    ("amdgpu/edge", "gpu", "°C", (42, 55, 66), 1.2, 0), ("amdgpu/mem", "gpu", "°C", (60, 65, 70), 1, 0),
    ("amdgpu/PPT", "gpu", "W", (12, 60, 130), 4, 0), ("amdgpu/fan1", "gpu", "RPM", (0, 900, 1400), 40, 0),
    ("amdgpu/vddgfx", "gpu", "mV", (712, 850, 1050), 15, 0), ("memoria/ram_pct", "memoria", "%", (30, 40, 55), 1.5, 0),
    ("nvme/Composite", "disco", "°C", (40, 45, 50), 1.5, 0), ("drivetemp_sda/temp1", "disco", "°C", (28, 29, 30), 0.6, 0),
    ("drivetemp_sdb/temp1", "disco", "°C", (33, 34, 35), 0.6, 0), ("nvme0n1/escritura_mbs", "disco", "MB/s", (1, 40, 15), 2, 0),
    ("sda/escritura_mbs", "disco", "MB/s", (0.2, 3, 1), 0.3, 0),
    ("nct6798/fan2", "placa", "RPM", (1500, 1700, 1900), 60, 0), ("nct6798/in0", "placa", "mV", (576, 900, 1000), 20, 0),
    ("nct6798/in3", "placa", "mV", (3328, 3328, 3328), 8, 0), ("nct6798/SYSTIN", "placa", "°C", (33, 34, 35), 0.8, 0),
    ("nct6798/TSI0_TEMP", "placa", "°C", (50, 66, 74), 2, 0.02),
]
JUEGOS = ["Slay the Spire", "ELDEN RING NIGHTREIGN", "Project Zomboid"]


def main() -> None:
    random.seed(11)
    con = db.conectar()
    T = db.ahora()
    ws = con.execute("INSERT INTO workspace (hostname, machine_id, creado_en) VALUES ('equipo-de-prueba','prueba',?)", (T - DIAS * D,)).lastrowid

    # ---- sesiones de juego: tarde-noche de días alternados, y una en curso
    ses = []
    for d in range(1, DIAS):
        if d % 2 == 0:
            ini = T - d * D - (T % D) + 22 * H  # aprox. 19-20 h local: lo exacto no importa en datos de prueba
            ses.append((JUEGOS[(d // 2) % 3], ini, ini + random.randint(2, 4) * H))
    for nombre, ini, fin in ses:
        con.execute("INSERT INTO sesiones_actividad (tipo, detalle, inicio, fin, ultima_vez, origen) VALUES ('juego',?,?,?,?,'detectada')",
                    (nombre, ini, fin, fin))
    con.execute("INSERT INTO sesiones_actividad (tipo, detalle, inicio, fin, ultima_vez, origen) VALUES ('juego','Slay the Spire',?,NULL,?,'detectada')",
                (T - 90 * 60, T - 60))
    ses.append(("Slay the Spire", T - 90 * 60, T + 10 * D))

    def contexto(ts):
        if any(a <= ts <= b for _, a, b in ses):
            return "juego"
        return "carga" if random.random() < 0.08 else "reposo"

    # ---- lecturas cada 15 minutos
    filas, metricas = [], []
    inicio = T - DIAS * D
    for ts in range(inicio - inicio % PASO, T, PASO):
        ctx = contexto(ts)
        ci = ("reposo", "carga", "juego").index(ctx)
        dias_desde_inicio = (ts - inicio) / D
        reciente = T - ts < 6 * PASO  # las últimas lecturas: una GPU anómala para ver los puntos fuera de la banda
        for nombre, cat, unidad, centros, ruido, deriva in SENSORES:
            v = centros[ci] + random.gauss(0, ruido) + deriva * dias_desde_inicio
            if nombre == "amdgpu/junction" and reciente:
                v += 28
            filas.append((0, ts, cat, nombre, round(max(v, 0), 2), unidad, None, ctx))
        filas.append((0, ts, "disco", "sdb/errores_crc", 10.0, "n", None, ctx))
        filas.append((0, ts, "disco", "sdb/sectores_pendientes", 1.0 if ts > T - 10 * D else 0.0, "n", None, ctx))
        filas.append((0, ts, "disco", "sda/smart_ok", 1.0, "bool", None, ctx))
        filas.append((0, ts, "disco", "fs:/home/libre_pct", round(70 - 5 * dias_desde_inicio / DIAS + random.gauss(0, 0.05), 2), "%", None, ctx))
        filas.append((0, ts, "placa", "nct6798/fan1", 0.0, "RPM", None, ctx))
        filas.append((0, ts, "placa", "nct6798/fan7", float(random.choice([0, 0, 375, 631, 1100, 1250, 1762])), "RPM", None, ctx))
        if T - ts < 2 * D:
            metricas.append((ws, ts, 5.0, 31.0, 0.0, 60.0, 50.0, 145.0, 0.4))
    con.executemany("INSERT INTO lecturas (metrica_id, ts, categoria, nombre, valor, unidad, limite_crit, contexto) VALUES (?,?,?,?,?,?,?,?)", filas)
    con.executemany("INSERT INTO metricas (workspace_id, ts, cpu_pct, ram_pct, swap_pct, temp_cpu, temp_gpu, disco_libre_gb, load_1m) VALUES (?,?,?,?,?,?,?,?,?)", metricas)
    con.commit()
    linea_base.rollup_diario(con)                                                    # registro diario permanente
    con.execute("DELETE FROM lecturas WHERE ts < ?", (T - DIAS_CRUDOS * D,))         # retención de 30 días, como la real
    linea_base.recalcular_base(con, forzar=True)

    # ---- entorno: kernel y driver cambian hace 5 h; mesa cambió hace 30 h
    def snap(horas, kernel, mesa, extra):
        sid = con.execute("INSERT INTO snapshot_entorno (workspace_id, tomado_en, distro, kernel, escritorio, hash) VALUES (?,?,?,?,?,?)",
                          (ws, T - horas * H, "Zorin OS 18.1", kernel, "zorin:GNOME", f"h{horas}")).lastrowid
        hw = [("cpu", "AMD", "AMD Ryzen 5 5600X 6-Core Processor", {"arquitectura": "x86_64", "nucleos_fisicos": 6, "hilos": 12}),
              ("gpu", "AMD", "Advanced Micro Devices, Inc. [AMD/ATI] Navi 33 [Radeon RX 7600] (rev c0)",
               {"id_pci": "1002:7480", "driver": "amdgpu", "version_driver": f"kernel {kernel} (in-tree)", "mesa": mesa}),
              ("ram", "", "", {"total_gb": 31.2, "swap_gb": 0.0}),
              ("disco", "KINGSTON", "KINGSTON SA400S37480G", {"dev": "sda", "tamano": "447,1G"}),
              ("disco", "Patriot", "Patriot Burst Elite 240GB", {"dev": "sdb", "tamano": "223,6G"}),
              ("disco", "CT1000P310SSD8", "CT1000P310SSD8", {"dev": "nvme0n1", "tamano": "931,5G"}),
              ("mother", "ASUSTeK COMPUTER INC.", "PRIME B550-PLUS", {"bios": "3404"})]
        con.executemany("INSERT INTO hardware (snapshot_id, tipo, marca, modelo, detalle) VALUES (?,?,?,?,?)",
                        [(sid, t, m, mo, json.dumps(d)) for t, m, mo, d in hw])
        con.executemany("INSERT INTO software (snapshot_id, nombre, version, origen) VALUES (?,?,?,?)",
                        [(sid, f"paquete{i}", "1.0", "apt") for i in range(40)] + [(sid, n, v, "apt") for n, v in extra.items()])
    snap(DIAS * 24, "7.0.0-30-generic", "25.0", {"mesa-vulkan-drivers": "25.0"})
    snap(30, "7.0.0-30-generic", "25.1", {"mesa-vulkan-drivers": "25.1", "fonts-nuevas": "1"})
    snap(5, "7.0.0-38-generic", "25.1", {"mesa-vulkan-drivers": "25.1", "fonts-nuevas": "1", "linux-image-7.0.0-38-generic": "7.0.0-38"})

    # ---- alertas, hallazgos, eventos, acciones
    def alerta(clave, cat, nombre, sev, msg, valor, horas, activa=1, resuelta_h=None, veces=1):
        con.execute("INSERT INTO alertas_salud (clave, categoria, nombre, severidad, mensaje, valor, desde, ultima_vez, ultima_notif, activa, resuelta_en, veces) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (clave, cat, nombre, sev, msg, valor, T - horas * H, T - 60 if activa else T - (resuelta_h or 0) * H,
                                                          T - horas * H, activa, T - resuelta_h * H if resuelta_h else None, veces))
    alerta("smart_pendientes:sdb/sectores_pendientes", "disco", "sdb/sectores_pendientes", "aviso", "Sectores pendientes de realocar: sdb/sectores_pendientes = 1 n (límite 1)", 1, 240, veces=40)
    alerta("smart_crc:sdb/errores_crc", "disco", "sdb/errores_crc", "aviso", "Errores CRC (posible cable): sdb/errores_crc = 10 n (límite 10)", 10, 240, veces=40)
    alerta("ventilador:nct6798/fan7", "placa", "nct6798/fan7", "critico", "Ventilador detenido: nct6798/fan7 a 0 RPM con el chip a 84 °C", 0, 3)
    alerta("temp_gpu:amdgpu/junction", "gpu", "amdgpu/junction", "aviso", "Temperatura de la GPU alta: amdgpu/junction = 102.3 °C (límite 100)", 102.3, 2)
    alerta("anomalia:k10temp/Tctl:reposo", "cpu", "k10temp/Tctl", "aviso", "Fuera de lo habitual: k10temp/Tctl = 71.2 °C en reposo (lo normal es 49.1)", 71.2, 50, 0, 49)
    hallazgos = [("h1", "red", "shell_web_sin_auth", "alta", "ttyd", "Terminal web accesible desde la red y sin credenciales", 400, "revisado"),
                 ("h2", "red", "escucha_externa", "baja", "steam", "Escucha en 0.0.0.0:27036 (accesible desde la red)", 400, "nuevo"),
                 ("h3", "minero", "nombre_minero", "media", "xmrig", "Proceso con nombre de minero de criptomonedas", 90, "falso_positivo")]
    for hu, cat, regla, sev, nom, det, h, est in hallazgos:
        con.execute("INSERT INTO hallazgos_seguridad (huella, categoria, regla, severidad, nombre, pid, detalle, primera_vez, ultima_vez, veces, estado) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (hu, cat, regla, sev, nom, 1234, det, T - h * H, T - 3 * H, 12, est))
    con.execute("INSERT INTO reputacion (huella, sha256, sha1, ruta_exe, veredicto, fuente, detalle, consultado_en) VALUES ('h3','aa','bb','/tmp/xmrig','sin_registro','Team Cymru','sin coincidencias',?)", (T - 80 * H,))
    for ts, o, sv, m in [(T - 3 * H, "kernel", "err", "amdgpu: ring gfx_0.0.0 timeout"), (T - 3 * H + 30, "kernel", "err", "amdgpu: ring gfx_0.0.0 timeout"),
                         (T - 2 * H, "smartd", "crit", "Device: /dev/sdb [SAT], 1 Currently unreadable (pending) sectors")]:
        con.execute("INSERT INTO eventos (ts, origen, severidad, mensaje) VALUES (?,?,?,?)", (ts, o, sv, m))
    for ts, tool, par, res in [(T - 5 * D, "limpiar_descargas_viejas", '{"dias": 90, "simular": false}', "12 elementos movidos a cuarentena"),
                               (T - 4 * D, "marcar_hallazgo", '{"id": 3, "estado": "falso_positivo"}', "ok")]:
        con.execute("INSERT INTO acciones (ts, tool, parametros, resultado) VALUES (?,?,?,?)", (ts, tool, par, res))

    # ---- reportes
    (DESTINO / "reportes").mkdir(exist_ok=True)
    for i, (modo, motivo) in enumerate([("claude", None), ("claude", None), ("determinista", "límite de uso de Claude alcanzado")]):
        fecha = time.strftime("%Y-%m-%d", time.localtime(T - (14 - 7 * i) * D))
        ruta = DESTINO / "reportes" / f"{fecha}.md"
        ruta.write_text(f"# Reporte semanal de pc-doctor, {fecha}\n\n> **Resumen:** Semana de prueba {i + 1}.\n\n## 1. Estado general\n- Todo dentro de lo normal salvo `sdb`.\n\n"
                        f"## 6. SMART y discos\n| Contador | Valor |\n|---|---|\n| errores_crc | 10 |\n\n**Atención:** texto de prueba con `código` y [un enlace](https://ejemplo.com).\n")
        con.execute("INSERT INTO reportes (ts, ruta, modo, motivo, duracion_s, resumen) VALUES (?,?,?,?,?,?)",
                    (T - (14 - 7 * i) * D, str(ruta), modo, motivo, 27.0 if modo == "claude" else 3.0, f"Semana de prueba {i + 1}."))
    (DESTINO / "config.json").write_text(json.dumps({
        "consulta_online": True, "malwarebazaar_key": "esto-es-un-secreto-de-prueba", "notificaciones": True, "salud": True,
        "umbrales": {"temp_cpu": {"aviso": 80, "muestras": 1}}, "reporte": {"habilitado": True, "modelo": "sonnet", "max_turns": 30}}, indent=2))
    con.commit()
    n = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("lecturas", "lecturas_diarias", "linea_base", "sesiones_actividad", "alertas_salud")}
    print(f"datos de prueba en {DESTINO}: {n}")


main()

"""Detección de juegos por procesos, sesiones de actividad y migración del historial al contexto 'juego'.

Los procesos son sintéticos (incluidas las líneas de comandos reales de Crimson Desert bajo Proton) y los juegos de Steam
salen de un diccionario fijo de conftest.py: no se lee ningún proceso real ni ~/.steam."""

import pytest
from ayudas import L

import actividad
import db
import linea_base
import salud

DETECTAR = actividad.detectar  # la función real: conftest.py la reemplaza por una vacía en cada prueba
S = "/home/v/.steam/debian-installation/steamapps/common"
REAPER = ["/home/v/.steam/debian-installation/ubuntu12_32/reaper", "SteamLaunch", "AppId=646570", "--", "x"]
SH_ENVOLTORIO = ["/bin/sh", "-c", "/home/v/.steam/debian-installation/ubuntu12_32/steam-launch-wrapper -- /home/v/.steam/debian-installation/ubuntu12_32/reaper "
                 f"SteamLaunch AppId=3321460 -- {S}/SteamLinuxRuntime_4/_v2-entry-point --verb=waitforexitandrun -- {S}/Proton - Experimental/proton "
                 f"waitforexitandrun {S}/Crimson Desert/bin64/CrimsonDesert.exe"]
VACIOS = [""] * 30  # Wine rellena la línea de comandos con argumentos vacíos

# (nombre del proceso, argumentos, juego esperado o None)
CASOS = [
    # el cliente de Steam siempre está abierto: no es un juego
    ("steam", ["/home/v/.steam/debian-installation/ubuntu12_32/steam"], None),
    ("steamwebhelper", ["/home/v/.steam/debian-installation/ubuntu12_64/steamwebhelper", "-lang=es"], None),
    ("srt-bwrap", ["/home/v/.steam/debian-installation/steamrt64/pv-runtime/srt-bwrap", "--args", "26"], None),
    # juegos de Steam
    ("reaper", REAPER, "Slay the Spire"),
    ("SlayTheSpire", [f"{S}/SlayTheSpire/jre/bin/java", "-jar", "desktop-1.0.jar"], "Slay the Spire"),
    ("java", ["java", "-jar", f"{S}/SlayTheSpire/desktop-1.0.jar"], "Slay the Spire"),              # intérprete: se mira lo que ejecuta
    ("bash", ["bash", f"{S}/SlayTheSpire/SlayTheSpireTroubleshoot.sh"], "Slay the Spire"),
    ("Game.exe", ["Z:\\home\\v\\.steam\\debian-installation\\steamapps\\common\\ELDEN RING NIGHTREIGN\\Game\\nightreign.exe"], "ELDEN RING NIGHTREIGN"),
    # herramientas y programas que solo mencionan la ruta de un juego
    ("proton", [f"{S}/Proton - Experimental/proton", "waitforexitandrun", "x.exe"], None),
    ("srt", [f"{S}/SteamLinuxRuntime_sniper/_v2-entry-point", "--verb=run"], None),
    ("code", ["code", f"{S}/SlayTheSpire/README.md"], None),
    ("nautilus", ["/usr/bin/nautilus", f"{S}/SlayTheSpire"], None),
    # programas de Windows bajo wine
    ("MiJuego.exe", ["C:\\Games\\MiJuego\\MiJuego.exe"], "MiJuego"),
    ("services.exe", ["C:\\windows\\system32\\services.exe"], None),
    ("explorer.exe", ["C:\\windows\\system32\\explorer.exe", "/desktop"], None),
    ("steam.exe", ["C:\\Program Files (x86)\\Steam\\steam.exe"], None),
    ("wine64", ["/usr/bin/wine64", "juego2.exe"], "juego2"),
    ("wine", ["/usr/bin/wine", "winecfg"], None),
    ("wineserver", ["/usr/bin/wineserver", "-p"], None),                                          # solo wineserver no cuenta
    ("gamescope", ["gamescope", "-W", "1920", "--", "foo"], "gamescope"),
    # casos reales de un juego de Steam bajo Proton (visto con Crimson Desert)
    ("sh", SH_ENVOLTORIO, None),                                                                  # `sh -c "<línea entera>"` es un envoltorio
    ("CrimsonDesert.e", ["S:\\steamapps\\common\\Crimson Desert\\bin64\\CrimsonDesert.exe", "PlatformServiceType=Steam"] + VACIOS, "Crimson Desert Enhanced"),
    ("steam.exe", ["c:\\windows\\system32\\steam.exe", f"{S}/Crimson Desert/bin64/CrimsonDesert.exe", "PlatformServiceType=Steam"] + VACIOS, None),
    ("xalia.exe", ["\\\\?\\S:\\steamapps\\common\\Proton - Experimental\\files\\share\\wine/../xalia/xalia.exe"] + VACIOS, None),
    ("wineserver", [f"{S}/Proton", "-", "Experimental/files/lib/wine/../../bin/wineserver"], None),
]


def evaluar(nombre, args):
    for f in actividad.FIRMAS:
        r = actividad._evaluar(f, nombre, args, actividad.juegos_steam)
        if r:
            return r
    return None


@pytest.mark.parametrize("nombre,args,esperado", CASOS, ids=[f"{n}:{(e or 'nada')}" for n, _, e in CASOS])
def test_firmas(nombre, args, esperado):
    assert evaluar(nombre, args) == esperado


@pytest.mark.parametrize("seccion", ["http://evil.com", "alerta:abc"])
def test_el_nombre_de_un_juego_nunca_sale_de_texto_arbitrario(seccion):
    assert evaluar("firefox", ["firefox", seccion]) is None


# ---------- detectar() con procesos sintéticos ----------

class Proceso:
    def __init__(self, pid, nombre, args, ct, ancestros=()):
        self.info = dict(pid=pid, name=nombre, cmdline=args, create_time=ct)
        self._ancestros = [type("A", (), {"name": lambda s, n=n: n})() for n in ancestros]

    def parents(self):
        return self._ancestros


@pytest.fixture
def procesos(monkeypatch):
    def poner(lista):
        monkeypatch.setattr(actividad.psutil, "process_iter", lambda attrs=None: iter(lista))
    return poner


def test_varios_procesos_de_un_mismo_juego_son_uno_y_con_el_inicio_mas_antiguo(procesos):
    procesos([Proceso(1, "reaper", REAPER, 1000), Proceso(2, "SlayTheSpire", CASOS[4][1], 1010), Proceso(3, "gamescope", ["gamescope", "--", "x"], 990)])
    d = DETECTAR()
    assert [x["detalle"] for x in d] == ["Slay the Spire"] and d[0]["desde"] == 1000   # el genérico (gamescope) se descarta si hay uno concreto


def test_gamescope_solo_cuenta_si_no_hay_un_juego_concreto(procesos):
    procesos([Proceso(1, "gamescope", ["gamescope", "--", "x"], 990), Proceso(2, "steam", CASOS[0][1], 1)])
    assert [x["detalle"] for x in DETECTAR()] == ["gamescope"]


def test_el_cliente_de_steam_abierto_no_es_un_juego(procesos):
    procesos([Proceso(1, "steam", CASOS[0][1], 1), Proceso(2, "steamwebhelper", CASOS[1][1], 1)])
    assert DETECTAR() == []


def test_wine_bajo_un_lanzador_de_steam_no_suma_otro_juego_pero_wine_suelto_si(procesos):
    procesos([Proceso(10, "reaper", REAPER, 1000),
              Proceso(11, "juego.exe", ["C:\\Games\\Otro\\Otro.exe"], 1010, ancestros=("pv-adverb", "reaper", "sh")),
              Proceso(12, "xalia.exe", ["\\\\?\\S:\\x\\xalia.exe"], 1010, ancestros=("reaper",))])
    assert [x["detalle"] for x in DETECTAR()] == ["Slay the Spire"]
    procesos([Proceso(20, "juego.exe", ["C:\\Games\\Otro\\Otro.exe"], 1010, ancestros=("bash",))])
    assert [x["detalle"] for x in DETECTAR()] == ["Otro"]


def test_crimson_desert_bajo_proton_se_detecta_como_un_solo_juego(procesos):
    """El caso real que antes daba tres juegos: el envoltorio sh -c, xalia y el juego."""
    anc = ("pv-adverb", "srt-bwrap", "reaper", "sh", "steam")
    procesos([Proceso(1, "sh", SH_ENVOLTORIO, 900, ancestros=("steam",)),
              Proceso(2, "reaper", ["/home/v/.steam/debian-installation/ubuntu12_32/reaper", "SteamLaunch", "AppId=3321460", "--", "x"], 901),
              Proceso(3, "CrimsonDesert.e", CASOS[21][1], 910, ancestros=anc),
              Proceso(4, "xalia.exe", CASOS[23][1], 912, ancestros=anc),
              Proceso(5, "steam.exe", CASOS[22][1], 905, ancestros=anc),
              Proceso(6, "wineserver", CASOS[24][1], 905, ancestros=anc)])
    d = DETECTAR()
    assert [x["detalle"] for x in d] == ["Crimson Desert Enhanced"]


# ---------- sesiones ----------

T = 1_800_000_000
DET = [{"tipo": "juego", "detalle": "X", "desde": T - 300, "firma": "t", "pid": 1}]


def test_ciclo_de_vida_de_una_sesion(con):
    actividad.registrar(con, DET, T)
    actividad.registrar(con, DET, T + 900)
    actividad.registrar(con, [], T + 1800)
    filas = con.execute("SELECT * FROM sesiones_actividad").fetchall()
    assert len(filas) == 1 and filas[0]["inicio"] == T - 300 and filas[0]["fin"] == T + 900   # inicio real; fin = última vez que se la vio


def test_una_sesion_vencida_se_cierra_y_la_siguiente_es_otra(con):
    actividad.registrar(con, DET, T)
    actividad.registrar(con, DET, T + 7200)          # pasaron 2 h sin verla (PC apagada)
    assert con.execute("SELECT COUNT(*) FROM sesiones_actividad").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM sesiones_actividad WHERE fin IS NULL").fetchone()[0] == 1


def test_juego_en_curso_solo_si_se_lo_vio_hace_poco(con):
    actividad.registrar(con, DET, db.ahora())
    assert actividad.juego_en_curso(con)
    con.execute("UPDATE sesiones_actividad SET ultima_vez = ?", (db.ahora() - 3600,))
    assert not actividad.juego_en_curso(con)


def test_el_contexto_de_las_lecturas_es_juego_mientras_hay_un_juego(con):
    con.execute("INSERT INTO metricas (workspace_id, ts, cpu_pct) VALUES (1, ?, 5)", (db.ahora(),))
    actividad.registrar(con, [{**DET[0], "desde": db.ahora() - 600}])
    r = salud.ciclo(con, lambda *a, **k: True)
    assert r["contexto"] == "juego"
    actividad.registrar(con, [])
    assert salud.ciclo(con, lambda *a, **k: True)["contexto"] == "reposo"


# ---------- migración del historial al contexto 'juego' ----------

@pytest.fixture
def historial_con_un_juego(con):
    """6 corridas: en las 4 primeras había un juego entre los procesos más activos (con contexto reposo o carga)."""
    for i in range(1, 7):
        ts = 1_000_000 + i * 900
        con.execute("INSERT INTO metricas (id, workspace_id, ts, cpu_pct) VALUES (?,1,?,5)", (i, ts))
        if i <= 4:
            con.execute("INSERT INTO top_procesos (metrica_id, nombre, cpu_pct, ram_mb) VALUES (?,?,?,?)", (i, "SlayTheSpire", 30.0, 900.0))
        ctx = "carga" if i % 2 else "reposo"
        con.executemany("INSERT INTO lecturas (metrica_id, ts, categoria, nombre, valor, unidad, contexto) VALUES (?,?,?,?,?,?,?)",
                        [(i, ts, "cpu", f"s{k}", 50.0 + k, "°C", ctx) for k in range(25)])
    con.commit()
    return {"slaythespire": "Slay the Spire"}


def contextos(con):
    return dict(con.execute("SELECT contexto, COUNT(*) FROM lecturas GROUP BY contexto").fetchall())


def test_la_migracion_simula_sin_tocar_nada(con, historial_con_un_juego):
    antes = contextos(con)
    r = actividad.reclasificar_historial(con, simular=True, nombres=historial_con_un_juego)
    assert r["corridas_con_juego"] == 4 and r["aplicado"] is False and r["juegos"] == ["Slay the Spire"]
    assert contextos(con) == antes and not list(db.DIR_DATOS.glob("doctor.db.antes-de-juego-*"))


def test_la_migracion_reclasifica_hace_copia_reconstruye_sesiones_y_es_idempotente(con, historial_con_un_juego):
    r = actividad.reclasificar_historial(con, simular=False, nombres=historial_con_un_juego)
    con.commit()
    assert r["aplicado"] and contextos(con) == {"juego": 100, "carga": 25, "reposo": 25}   # 4 corridas × 25 lecturas pasan a juego
    assert len(list(db.DIR_DATOS.glob("doctor.db.antes-de-juego-*"))) == 1                  # copia de seguridad
    ses = con.execute("SELECT detalle, origen FROM sesiones_actividad").fetchall()
    assert [(s["detalle"], s["origen"]) for s in ses] == [("Slay the Spire", "reconstruida")]
    assert con.execute("SELECT tool FROM acciones").fetchone()["tool"] == "reclasificar_historial"
    # idempotente: si no hay nada que cambiar, no toca ni copia nada
    r2 = actividad.reclasificar_historial(con, simular=False, nombres=historial_con_un_juego)
    assert contextos(con) == {"juego": 100, "carga": 25, "reposo": 25}
    assert "copia_de_seguridad" not in r2 and len(list(db.DIR_DATOS.glob("doctor.db.antes-de-juego-*"))) == 1


def test_la_migracion_no_toca_lecturas_sin_contexto(con, historial_con_un_juego):
    con.execute("UPDATE lecturas SET contexto = NULL WHERE metrica_id = 1")
    con.commit()
    actividad.reclasificar_historial(con, simular=False, nombres=historial_con_un_juego)
    assert contextos(con).get(None) == 25  # las anteriores a la columna `contexto` quedan como estaban


# ---------- local: lectura real de procesos ----------

@pytest.mark.local
def test_detectar_con_procesos_reales_no_falla():
    assert isinstance(DETECTAR(), list)

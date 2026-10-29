"""Detección de actividad (hoy: juego) por procesos y registro de sesiones.

Un juego cuenta solo cuando se ejecuta el juego en sí: el cliente de Steam (siempre abierto) no cuenta.
Todas las firmas están en FIRMAS, más abajo, para poder extenderlas en un solo lugar.
Corre sin permisos especiales: solo lee la línea de comandos de los procesos propios.

Uso manual: `uv run actividad.py` muestra la actividad detectada ahora;
`uv run actividad.py --reclasificar [--aplicar]` migra el historial al contexto 'juego' (ver reclasificar_historial).
"""

import re
import sys
from pathlib import Path

import psutil

import db
import plataforma
from db import log

# ---------- firmas (único lugar que hay que tocar para reconocer más juegos) ----------

# Carpetas de steamapps/common que son herramientas y no juegos
HERRAMIENTAS_STEAM = re.compile(r"^(SteamLinuxRuntime|Steam Linux Runtime|Proton|GE-Proton|Steamworks|Steam Controller|Steam\.dll)", re.I)
# Programas que pueden mencionar la ruta de un juego sin ser el juego (editores, copias, el propio Steam, etc.)
NO_SON_JUEGOS = r"^(code|codium|nautilus|gedit|vim|nvim|nano|less|cat|grep|rg|ls|du|find|tail|head|rsync|cp|mv|tar|xdg-open|ps|top|htop|steam|steamwebhelper|claude|node)$"
# Ejecutables de Windows que son del sistema, de Steam o de ayuda, no el juego
EXE_AUXILIARES = (r"(?i)^(services|winedevice|plugplay|svchost|rpcss|explorer|conhost|wineboot|winemenubuilder|start|cmd|rundll32|"
                  r"tabtip|iexplore|steam|gameoverlayui|crashhandler\w*|unitycrashhandler\w*|crashreportclient|"
                  r"eosoverlayrenderer\w*|steamwebhelper|setup|unins\d*|vc_?redist\S*|dxsetup|xalia)$")

# Cada firma: id, tipo, filtros sobre el nombre del proceso ("proceso") o sus primeros argumentos ("cmdline", con
# las barras de Windows normalizadas a "/"), "excluir" (sobre el nombre), "detalle" (grupo `juego` o texto fijo) y
# "generico": las firmas genéricas (gamescope, gamemode) se descartan si ya se identificó un juego concreto.
FIRMAS = [
    {"id": "steam_lanzador", "tipo": "juego", "proceso": r"^reaper$", "cmdline": r"SteamLaunch\s+AppId=(?P<appid>\d+)"},
    {"id": "steam_ruta", "tipo": "juego", "cmdline": r"steamapps/common/(?P<dir>[^/]+)/", "excluir": NO_SON_JUEGOS,
     "solo_argv0": True},  # Proton, runtimes y juegos nativos de Steam
    {"id": "windows_exe", "tipo": "juego", "cmdline": r"(?P<exe>[^/ ]+)\.exe\b", "excluir": NO_SON_JUEGOS,
     "solo_argv0": True, "excluir_detalle": EXE_AUXILIARES},  # el proceso de wine/Proton renombrado al .exe
    {"id": "wine_con_exe", "tipo": "juego", "proceso": r"^wine(64)?(-preloader)?$", "cmdline": r"(?P<exe>[^/ ]+)\.exe\b",
     "excluir_detalle": EXE_AUXILIARES},  # `wine juego.exe`; wineserver solo no cuenta
    {"id": "gamescope", "tipo": "juego", "proceso": r"^gamescope(-wl)?$", "generico": True, "texto": "gamescope"},
]
# gamemoded es un servicio que siempre puede estar vivo: cuenta solo si tiene clientes (gamemodelist)
GAMEMODE = {"proceso": "gamemoded", "listar": ["/usr/games/gamemodelist"]}  # ruta completa: /usr/games no suele estar en el PATH de systemd

MAX_ARGS = 3          # cuántos argumentos de la línea de comandos se miran
SESION_VENCIDA_S = 45 * 60   # una sesión no vista en este tiempo se cierra y la siguiente es otra (ej. PC apagada)
HUECO_RECONSTRUIDA_S = 40 * 60  # al reconstruir el historial, corridas separadas por más que esto son sesiones distintas
FRESCA_S = 5 * 60     # "juego en curso" = una sesión vista hace menos que esto


# ---------- datos de Steam ----------

def _bibliotecas_steam() -> list[Path]:
    """Carpetas steamapps de todas las bibliotecas de Steam que existan ahora (las de discos desmontados se omiten)."""
    raiz = Path.home() / ".steam" / "debian-installation" / "steamapps"
    rutas = [raiz]
    try:
        rutas += [Path(m) / "steamapps" for m in re.findall(r'"path"\s+"([^"]+)"', (raiz / "libraryfolders.vdf").read_text())]
    except OSError:
        pass
    vistas, res = set(), []
    for r in rutas:
        if r not in vistas and r.is_dir():
            vistas.add(r)
            res.append(r)
    return res


def juegos_steam() -> dict:
    """{'appid': {'nombre', 'carpeta'}} leído de los appmanifest de cada biblioteca."""
    res = {}
    for lib in _bibliotecas_steam():
        for f in lib.glob("appmanifest_*.acf"):
            try:
                t = f.read_text(errors="replace")
            except OSError:
                continue
            campo = lambda k: (re.search(rf'"{k}"\s+"([^"]*)"', t) or [None, None])[1]
            appid, nombre, carpeta = campo("appid"), campo("name"), campo("installdir")
            if appid and nombre and not HERRAMIENTAS_STEAM.match(carpeta or nombre):
                res[appid] = {"nombre": nombre, "carpeta": carpeta}
    return res


def nombres_de_proceso_de_juegos() -> dict[str, str]:
    """{nombre de proceso (minúsculas, 15 letras como `comm`): nombre del juego} de lo instalado en Steam.

    Se usa solo para reclasificar el historial, donde `top_procesos` guarda únicamente el nombre del proceso.
    Incluye la carpeta de instalación y los ejecutables sin extensión de su primer nivel.
    """
    res, juegos = {}, juegos_steam().values()
    for lib in _bibliotecas_steam():
        for j in juegos:
            base = lib / "common" / (j["carpeta"] or "")
            if not j["carpeta"] or not base.is_dir():
                continue
            nombres = {j["carpeta"]}
            try:
                for f in base.iterdir():
                    if f.is_file() and "." not in f.name and f.stat().st_mode & 0o100:
                        nombres.add(f.name)
            except OSError:
                pass
            for n in nombres:
                res[n[:15].lower()] = j["nombre"]
    for lib in _bibliotecas_steam():  # juegos sin appmanifest: se reconocen por el nombre de su carpeta
        for d in (lib / "common").glob("*"):
            if d.is_dir() and not HERRAMIENTAS_STEAM.match(d.name):
                res.setdefault(d.name[:15].lower(), d.name)
    return res


# ---------- detección ----------

def _normalizar(args: list[str]) -> list[str]:
    return [a.replace("\\", "/") for a in args]


def _nombre_steam(m: re.Match, juegos) -> str | None:
    """Nombre del juego según el AppId o la carpeta; `juegos` es una función que lee los appmanifest (solo si hace falta)."""
    if m.groupdict().get("appid"):
        j = juegos().get(m["appid"])
        return j["nombre"] if j else f"Steam AppId {m['appid']}"
    d = m.groupdict().get("dir")
    if d:
        if HERRAMIENTAS_STEAM.match(d):
            return None
        return next((j["nombre"] for j in juegos().values() if j["carpeta"] == d), d)
    return None


def _evaluar(firma: dict, nombre: str, args: list[str], juegos) -> str | None:
    """Devuelve el detalle (nombre del juego) si el proceso coincide con la firma; si no, None."""
    if firma.get("proceso") and not re.search(firma["proceso"], nombre):
        return None
    if firma.get("excluir") and re.search(firma["excluir"], nombre):
        return None
    if firma.get("texto") and "cmdline" not in firma:
        return firma["texto"]
    args = _normalizar(args)
    zona = args[:1] if firma.get("solo_argv0") else args[:MAX_ARGS]
    # un intérprete (bash, java, python) recibe el programa en los argumentos siguientes
    if firma.get("solo_argv0") and args and re.search(r"/(bash|sh|java|python[\d.]*|env)$|^(bash|sh|java|python[\d.]*|env)$", args[0]):
        if args[1:2] == ["-c"]:  # `sh -c "<línea entera>"` es un envoltorio (ej. el de Steam), no el programa: ya lo cubre el lanzador
            return None
        zona = args[:MAX_ARGS]
    m = re.search(firma["cmdline"], " ".join(zona))
    if not m:
        return None
    if firma["id"].startswith("steam"):
        return _nombre_steam(m, juegos)
    exe = m.groupdict().get("exe")
    if exe:
        if re.search(firma.get("excluir_detalle", "$^"), exe):
            return None
        return exe
    return None


def _clientes_gamemode() -> list[str]:
    """Programas registrados en gamemode ahora; vacío si no hay o no está instalado."""
    salida = db.ejecutar(GAMEMODE["listar"], timeout=3)
    if not salida:
        return []
    return [Path(m[0]).name for m in re.findall(r"(/\S+)", salida) if not m.startswith("/proc")]


def detectar() -> list[dict]:
    """Actividad en curso: lista de {tipo, detalle, desde, firma, pid}, uno por juego distinto (cada sistema tiene su detector)."""
    return plataforma.actual().detectar_juegos()


def _detectar_linux() -> list[dict]:
    """Actividad en curso en Linux (Steam, Proton, Wine, gamescope, gamemode), por la línea de comandos de los procesos.

    `desde` es la hora real de inicio del proceso (la más antigua entre los que forman ese juego).
    """
    cache = []

    def juegos():
        if not cache:
            cache.append(juegos_steam())
        return cache[0]

    hallados: dict[tuple, dict] = {}
    gamemode_vivo = False
    for p in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
        try:
            nombre, args = p.info["name"] or "", p.info["cmdline"] or []
            if nombre == GAMEMODE["proceso"]:
                gamemode_vivo = True
            for f in FIRMAS:
                detalle = _evaluar(f, nombre, args, juegos)
                # un proceso de Wine que cuelga de `reaper` es parte de un juego de Steam, que ya identifican el lanzador y la ruta
                if detalle and f["id"] in ("windows_exe", "wine_con_exe") and any(a.name() == "reaper" for a in p.parents()):
                    break
                if detalle:
                    k = (f["tipo"], detalle, bool(f.get("generico")))
                    d = hallados.setdefault(k, {"tipo": f["tipo"], "detalle": detalle, "desde": p.info["create_time"],
                                                 "firma": f["id"], "pid": p.info["pid"], "generico": bool(f.get("generico"))})
                    d["desde"] = min(d["desde"], p.info["create_time"])
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    if gamemode_vivo:
        for c in _clientes_gamemode():
            hallados.setdefault(("juego", c, True), {"tipo": "juego", "detalle": c, "desde": db.ahora(),
                                                      "firma": "gamemode", "pid": 0, "generico": True})
    concretos = [d for d in hallados.values() if not d["generico"]]
    res = concretos or list(hallados.values())  # los genéricos solo valen si no hay un juego concreto
    for d in res:
        d.pop("generico", None)
        d["desde"] = min(int(d["desde"]), db.ahora())
    return res


# ---------- sesiones ----------

def registrar(con, detectados: list[dict] | None = None, ahora: int | None = None) -> dict:
    """Paso del recolector: abre, extiende y cierra las sesiones según lo que hay ahora."""
    ahora = ahora or db.ahora()
    detectados = detectar() if detectados is None else detectados
    abiertas = {(f["tipo"], f["detalle"]): f for f in con.execute(
        "SELECT id, tipo, detalle, ultima_vez FROM sesiones_actividad WHERE fin IS NULL")}
    vistos, nuevas = set(), 0
    for d in detectados:
        k = (d["tipo"], d["detalle"])
        vistos.add(k)
        previa = abiertas.get(k)
        if previa and ahora - previa["ultima_vez"] <= SESION_VENCIDA_S:
            con.execute("UPDATE sesiones_actividad SET ultima_vez=? WHERE id=?", (ahora, previa["id"]))
            continue
        if previa:  # la anterior quedó vencida (equipo apagado): se cierra y esta es otra sesión
            con.execute("UPDATE sesiones_actividad SET fin=ultima_vez WHERE id=?", (previa["id"],))
        con.execute("INSERT INTO sesiones_actividad (tipo, detalle, inicio, ultima_vez) VALUES (?,?,?,?)",
                    (d["tipo"], d["detalle"], min(d["desde"], ahora), ahora))
        nuevas += 1
    cerradas = 0
    for k, f in abiertas.items():
        if k not in vistos:
            con.execute("UPDATE sesiones_actividad SET fin=ultima_vez WHERE id=?", (f["id"],))
            cerradas += 1
    return {"detectados": [d["detalle"] for d in detectados], "nuevas": nuevas, "cerradas": cerradas}


def juego_en_curso(con) -> bool:
    """True si el recolector vio un juego en esta corrida (sesión abierta y vista hace pocos minutos)."""
    return con.execute("SELECT 1 FROM sesiones_actividad WHERE tipo='juego' AND fin IS NULL AND ultima_vez >= ?",
                       (db.ahora() - FRESCA_S,)).fetchone() is not None


# ---------- migración del historial ----------

def reclasificar_historial(con, simular: bool = True, nombres: dict[str, str] | None = None) -> dict:
    """Pasa a 'juego' las lecturas viejas (reposo o carga) de corridas donde había un juego en `top_procesos`.

    Une por `metrica_id`, sin ventanas de tiempo. Solo ve los 5 procesos que más CPU usaban: los juegos que
    no estaban entre ellos siguen como estaban. También reconstruye las sesiones (origen 'reconstruida'),
    rehace los resúmenes diarios de los días afectados y recalcula la línea base. Es idempotente.
    Con simular=True solo cuenta. Al aplicar, guarda antes una copia de la base junto a ella.
    """
    import linea_base
    nombres = nombres_de_proceso_de_juegos() if nombres is None else nombres
    if not nombres:
        return {"error": "no encontré juegos de Steam instalados para reconocer en el historial"}
    marcas = ",".join("?" for _ in nombres)
    runs = con.execute(
        f"SELECT t.metrica_id, m.ts, lower(substr(t.nombre,1,15)) p FROM top_procesos t JOIN metricas m ON m.id=t.metrica_id "
        f"WHERE lower(substr(t.nombre,1,15)) IN ({marcas}) ORDER BY m.ts", list(nombres)).fetchall()
    ids = sorted({r["metrica_id"] for r in runs})
    por_ctx = {}
    for i in range(0, len(ids), 500):
        trozo = ids[i:i + 500]
        for f in con.execute(f"SELECT contexto, COUNT(*) c FROM lecturas WHERE metrica_id IN ({','.join('?' * len(trozo))}) "
                             f"AND contexto IN ('reposo','carga') GROUP BY contexto", trozo):
            por_ctx[f["contexto"]] = por_ctx.get(f["contexto"], 0) + f["c"]
    sesiones = _sesiones_de(runs, nombres)
    res = {"corridas_con_juego": len(ids), "lecturas_a_cambiar": por_ctx, "sesiones_a_reconstruir": len(sesiones),
           "juegos": sorted({s[0] for s in sesiones}), "aplicado": False}
    if simular or not por_ctx:  # sin nada que cambiar (por ejemplo, ya migrado) no se toca ni se copia nada
        return res
    copia = db.DIR_DATOS / f"doctor.db.antes-de-juego-{db.ahora()}"
    con.execute("VACUUM INTO ?", (str(copia),))
    res["copia_de_seguridad"] = str(copia)
    dias = set()
    for i in range(0, len(ids), 500):
        trozo = ids[i:i + 500]
        q = ",".join("?" * len(trozo))
        dias |= {f[0] for f in con.execute(
            f"SELECT DISTINCT date(ts,'unixepoch','localtime') FROM lecturas WHERE metrica_id IN ({q}) AND contexto IN ('reposo','carga')", trozo)}
        con.execute(f"UPDATE lecturas SET contexto='juego' WHERE metrica_id IN ({q}) AND contexto IN ('reposo','carga')", trozo)
    for d in dias:  # los días ya resumidos se rehacen con el contexto nuevo (el rollup los vuelve a completar)
        con.execute("DELETE FROM lecturas_diarias WHERE dia=?", (d,))
    con.execute("DELETE FROM sesiones_actividad WHERE origen='reconstruida'")
    con.executemany("INSERT INTO sesiones_actividad (tipo, detalle, inicio, fin, ultima_vez, origen) VALUES ('juego',?,?,?,?,'reconstruida')",
                    [(n, a, b, b) for n, a, b in sesiones])
    res["resumenes_rehechos"] = linea_base.rollup_diario(con)
    res["base_recalculada"] = linea_base.recalcular_base(con, forzar=True)
    con.execute("INSERT INTO acciones (ts, tool, parametros, resultado) VALUES (?,?,?,?)",
                (db.ahora(), "reclasificar_historial", None, f"{len(ids)} corridas pasadas a 'juego'"))
    res["aplicado"] = True
    return res


def _sesiones_de(runs, nombres: dict[str, str]) -> list[tuple[str, int, int]]:
    """Agrupa corridas consecutivas con el mismo juego en sesiones (nombre, inicio, fin)."""
    por_juego: dict[str, list[int]] = {}
    for r in runs:
        por_juego.setdefault(nombres[r["p"]], []).append(r["ts"])
    res = []
    for juego, tss in por_juego.items():
        tss = sorted(set(tss))
        ini = prev = tss[0]
        for t in tss[1:]:
            if t - prev > HUECO_RECONSTRUIDA_S:
                res.append((juego, ini, prev))
                ini = t
            prev = t
        res.append((juego, ini, prev))
    return sorted(res, key=lambda s: s[1])


if __name__ == "__main__":
    if "--reclasificar" in sys.argv:
        c = db.conectar()
        print(reclasificar_historial(c, simular="--aplicar" not in sys.argv))
        c.commit()
    else:
        print(detectar() or "sin juego en curso")

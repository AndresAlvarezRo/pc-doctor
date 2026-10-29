"""Consultas compartidas entre el servidor MCP (server.py) y el dashboard (web/api.py).

Lo que muestran las tools y el dashboard sale de estas funciones, así que nunca divergen. No escriben en la base y
no dependen de FastMCP ni de FastAPI. Las tools de server.py las envuelven y recortan el resultado para el chat.
"""

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import psutil

import actividad
import db
import linea_base
import memoria
import reputacion
import salud

ORDEN_SEVERIDAD_HALLAZGO = "CASE h.severidad WHEN 'alta' THEN 0 WHEN 'media' THEN 1 ELSE 2 END"
RANGO_DIARIO_DIAS = 30      # sobre este rango, la serie usa el registro diario en vez de las lecturas crudas
MAX_PUNTOS_SERIE = 800      # sobre esta cantidad de puntos crudos, la serie se agrupa en intervalos
ANCHO_BANDA_TIPICA = 2.0    # la zona "típica" del gráfico es la mediana ± 2 desvíos robustos


# ---------- alertas, hallazgos y sesiones ----------

def alertas(con, solo_activas: bool = True, dias: int = 7, limite: int = 200) -> list[dict]:
    """Alertas de salud de los últimos `dias`. `id` es el rowid, el que acepta correlacionar()."""
    t = db.ahora() - max(1, dias) * 86400
    filas = con.execute(
        f"SELECT rowid AS id, * FROM alertas_salud WHERE ultima_vez >= ? {'AND activa=1' if solo_activas else ''} "
        "ORDER BY activa DESC, severidad DESC, ultima_vez DESC LIMIT ?", (t, limite)).fetchall()
    hechos = memoria.hechos_activos(con)    # vacío si el usuario no declaró ninguno (o si las tablas no existen)
    res = []
    for f in filas:
        d = dict(f)
        d["hecho_conocido"] = memoria.compacto(memoria.hecho_de(hechos, {"clave": d["clave"], "nombre": d["nombre"]}))
        res.append(d)
    return res


def hallazgos(con, estado: str = "nuevo", dias: int = 30, limite: int = 200) -> tuple[int, list[dict]]:
    """(total, filas) de hallazgos de seguridad por severidad, con el veredicto de reputación si lo hay."""
    t = db.ahora() - max(1, dias) * 86400
    filtro, args = ("", (t,)) if estado == "todos" else ("AND h.estado=?", (t, estado))
    filas = con.execute(
        "SELECT h.*, r.veredicto, r.fuente, r.detalle AS rep_detalle FROM hallazgos_seguridad h "
        f"LEFT JOIN reputacion r ON r.huella = h.huella WHERE h.ultima_vez >= ? {filtro} "
        f"ORDER BY {ORDEN_SEVERIDAD_HALLAZGO}, h.ultima_vez DESC LIMIT ?", (*args, limite)).fetchall()
    total = con.execute(f"SELECT COUNT(*) n FROM hallazgos_seguridad h WHERE h.ultima_vez >= ? {filtro}", args).fetchone()["n"]
    return total, [dict(f) for f in filas]


def sesiones(con, tipo: str = "", dias: int = 30, limite: int = 60) -> tuple[list[dict], dict]:
    """(sesiones, resumen por juego). Cada sesión trae la temperatura máxima de CPU y GPU medida durante ella."""
    desde = db.ahora() - max(1, dias) * 86400
    args, filtro = [desde], ""
    if tipo:
        filtro, args = " AND tipo=?", [desde, tipo]
    filas = con.execute("SELECT * FROM sesiones_actividad WHERE COALESCE(fin, ultima_vez) >= ?" + filtro +
                        " ORDER BY inicio DESC LIMIT ?", (*args, limite)).fetchall()
    res, resumen = [], {}
    for f in filas:
        fin = f["fin"] or f["ultima_vez"]
        t = {c: con.execute("SELECT MAX(valor) m FROM lecturas WHERE categoria=? AND unidad='°C' AND ts BETWEEN ? AND ?",
                            (c, f["inicio"], fin)).fetchone()["m"] for c in ("cpu", "gpu")}
        res.append({"id": f["id"], "tipo": f["tipo"], "detalle": f["detalle"], "inicio": f["inicio"], "fin": fin,
                    "duracion_min": round((fin - f["inicio"]) / 60), "en_curso": f["fin"] is None, "origen": f["origen"],
                    "cpu_max_c": t["cpu"], "gpu_max_c": t["gpu"]})
        r = resumen.setdefault(f["detalle"], {"sesiones": 0, "minutos": 0, "cpu_max_c": None, "gpu_max_c": None})
        r["sesiones"] += 1
        r["minutos"] += round((fin - f["inicio"]) / 60)
        for c in ("cpu", "gpu"):
            if t[c] is not None:
                r[f"{c}_max_c"] = max(r[f"{c}_max_c"] or 0, t[c])
    return res, resumen


# ---------- estado en vivo ----------

def no_disponible(lecturas: list[dict]) -> list[str]:
    """Qué no se puede medir ahora en este equipo y qué falta para poder hacerlo."""
    res = []
    if not any(l["categoria"] == "placa" and l["unidad"] == "mV" for l in lecturas):
        res.append("Voltajes de la placa: el kernel no expone un sensor compatible")
    # drivetemp crea un chip por disco, llamado drivetemp_<disco> (ej. drivetemp_sda)
    sin_temp = sorted(p.name for p in Path("/sys/block").glob("sd*")
                      if not any(l["nombre"].startswith(f"drivetemp_{p.name}/") for l in lecturas))
    if sin_temp:
        res.append(f"Temperatura de discos SATA ({', '.join(sin_temp)}): falta el módulo drivetemp (ejecutar habilitar-sensores.sh)")
    if not any(l["nombre"].endswith("/smart_ok") for l in lecturas):
        res.append("SMART de los discos: falta smartmontools y el permiso (ejecutar habilitar-sensores.sh)")
    return res


def estado_en_vivo(con, cfg: dict | None = None) -> dict:
    """Lee ahora los sensores y los evalúa: lecturas, condiciones fuera de lo normal, contexto y juego en curso."""
    cfg = reputacion.cargar_config() if cfg is None else cfg
    lecturas = salud.leer_lecturas()
    activas = {f["clave"] for f in con.execute("SELECT clave FROM alertas_salud WHERE activa=1")}
    juego = actividad.detectar()
    contexto = linea_base.contexto_de(lecturas, bool(juego))
    conds = salud.condiciones(con, lecturas, cfg, activas, en_base=False)
    conds.update(salud.condiciones_eventos(con, db.ahora()))
    conds.update(linea_base.condiciones_anomalias(con, lecturas, contexto, en_base=False))
    return {"lecturas": lecturas, "conds": conds, "contexto": contexto, "juego": juego, "no_disponible": no_disponible(lecturas)}


# ---------- líneas base y bandas ----------

def _banda_de(b, pf: dict) -> dict:
    """Banda de una fila de linea_base: zona típica (mediana ± 2 desvíos) y límites de anomalía."""
    escala = linea_base.escala_robusta(b, pf)
    bajo, alto = linea_base.limites(b, pf)
    return {"contexto": b["contexto"], "n": b["n"], "madura": b["n"] >= linea_base.MIN_MUESTRAS,
            "mediana": b["p50"], "escala": escala, "p95": b["p95"], "p99": b["p99"],
            "tipica": [b["p50"] - ANCHO_BANDA_TIPICA * escala, b["p50"] + ANCHO_BANDA_TIPICA * escala],
            "limite": [bajo, alto]}


def bandas(con, nombre: str, unidad: str | None, contextos: tuple = ("reposo", "carga", "juego")) -> dict:
    """{contexto: banda} de un sensor. Vacío si ese sensor no se aprende (por ejemplo, los booleanos)."""
    pf = linea_base.perfil(nombre, unidad or "")
    if not pf:
        return {}
    filas = con.execute("SELECT * FROM linea_base WHERE nombre=?", (nombre,)).fetchall()
    return {f["contexto"]: _banda_de(f, pf) for f in filas if f["contexto"] in contextos}


# ---------- componentes ----------

ETIQUETAS = {
    "Tctl": "Temperatura del procesador (Tctl)", "Tccd1": "Temperatura del chiplet 1 (Tccd1)", "Tccd2": "Temperatura del chiplet 2 (Tccd2)",
    "uso": "Uso", "carga_por_hilo": "Carga por hilo", "edge": "Temperatura del borde", "junction": "Temperatura de unión (junction)",
    "mem": "Temperatura de la memoria", "PPT": "Potencia", "vddgfx": "Voltaje del núcleo", "vram_pct": "VRAM usada",
    "ram_pct": "RAM usada", "swap_pct": "Swap usada", "libre_pct": "Espacio libre", "solo_lectura": "Solo lectura",
    "desgaste_pct": "Desgaste", "io_util_pct": "Utilización de E/S", "spare_pct": "Reserva disponible",
    "escritura_mbs": "Escritura", "lectura_mbs": "Lectura", "smart_ok": "Estado SMART", "horas_encendido": "Horas encendido",
    "alerta_critica": "Alerta crítica de SMART", "errores_medio": "Errores de medio", "errores_crc": "Errores CRC",
    "sectores_incorregibles": "Sectores incorregibles", "sectores_pendientes": "Sectores pendientes",
    "sectores_realocados": "Sectores realocados", "temp1": "Temperatura", "Composite": "Temperatura (compuesta)",
    "Sensor 1": "Temperatura (sensor 1)", "CPUTIN": "Temperatura del zócalo (CPUTIN)", "SYSTIN": "Temperatura del sistema (SYSTIN)",
    "TSI0_TEMP": "Temperatura TSI0",
}
ESTADO_ORDEN = {"normal": 0, "aviso": 1, "critico": 2}
TIPOS_COMPONENTE = ("cpu", "gpu", "ram", "disco", "ventiladores", "voltajes", "placa")
TITULOS = {"cpu": "Procesador", "gpu": "Placa de video", "ram": "Memoria RAM", "disco": "Discos", "ventiladores": "Ventiladores",
           "voltajes": "Voltajes", "placa": "Placa madre"}


def etiqueta(nombre: str) -> str:
    """Nombre legible de un sensor (el nombre técnico queda en `nombre`)."""
    sufijo = nombre.rsplit("/", 1)[-1]
    if sufijo in ETIQUETAS:
        return ETIQUETAS[sufijo]
    if sufijo.startswith("fan") and sufijo[3:].isdigit():
        return f"Ventilador {sufijo[3:]}"
    if sufijo.startswith("in") and sufijo[2:].isdigit():
        return f"Entrada de voltaje {sufijo[2:]}"
    return sufijo.replace("_", " ").capitalize()


def _clasificar(l: dict, nvme: str | None) -> tuple[str, str]:
    """(tipo de componente, id del componente) de una lectura."""
    n, cat, u = l["nombre"], l["categoria"], l["unidad"]
    chip = n.rsplit("/", 1)[0] if n.startswith("fs:") else n.split("/")[0]
    if u == "RPM":
        return "ventiladores", chip
    if cat == "placa":
        return ("voltajes" if u == "mV" else "placa"), chip
    if cat == "cpu":
        return "cpu", "cpu"
    if cat == "gpu":
        return "gpu", "gpu"
    if cat == "memoria":
        return "ram", "ram"
    if cat == "disco":
        if n.startswith("fs:"):
            return "disco", "particiones"
        if chip.startswith("drivetemp_"):
            return "disco", chip[len("drivetemp_"):]
        return "disco", (nvme if chip == "nvme" and nvme else chip)
    return "placa", chip


def _modelos_hardware(con) -> dict:
    """{'cpu': [modelo], 'gpu': [modelo], 'disco': {dispositivo: 'modelo · tamaño'}} del último snapshot."""
    s = con.execute("SELECT id FROM snapshot_entorno ORDER BY tomado_en DESC, id DESC LIMIT 1").fetchone()
    res = {"cpu": [], "gpu": [], "disco": {}}
    if not s:
        return res
    for h in con.execute("SELECT tipo, modelo, detalle FROM hardware WHERE snapshot_id=?", (s["id"],)):
        if h["tipo"] == "disco":
            try:
                d = json.loads(h["detalle"] or "{}")
            except ValueError:
                d = {}
            if d.get("dev"):
                res["disco"][d["dev"]] = f"{h['modelo']} · {d.get('tamano', '')}".strip(" ·")
        elif h["tipo"] in res:
            res[h["tipo"]].append(h["modelo"] or "")
    return res


def nombre_gpu(modelo: str) -> str:
    """Nombre comercial de la GPU a partir de la descripción de lspci, para cualquier fabricante.

    Toma el último grupo entre corchetes que no sea el id PCI (ej. "...Navi 33 [Radeon RX 7600] [1002:7480]" -> Radeon RX 7600).
    """
    grupos = [g for g in re.findall(r"\[([^\]]+)\]", modelo or "") if not re.fullmatch(r"[0-9a-fA-F]{4}:[0-9a-fA-F]{4}", g)]
    return (grupos[-1] if grupos else re.sub(r"\s*\(rev [0-9a-f]+\)", "", modelo or "").strip())[:60] or "Placa de video"


def _titulo(tipo: str, ident: str, hw: dict) -> str:
    if tipo == "cpu" and hw["cpu"]:
        return hw["cpu"][0] or "Procesador"
    if tipo == "gpu" and hw["gpu"]:
        return nombre_gpu(hw["gpu"][0])
    if tipo == "ram":
        return f"Memoria RAM ({psutil.virtual_memory().total / 2 ** 30:.1f} GB)"
    if tipo == "disco" and ident == "particiones":
        return "Particiones"
    if tipo == "disco":
        return f"{ident} · {hw['disco'][ident]}" if ident in hw["disco"] else ident
    if tipo in ("ventiladores", "voltajes", "placa"):
        return f"{TITULOS[tipo]} ({ident})"  # hay un grupo por chip (ej. nct6798 de la placa y amdgpu de la GPU)
    return TITULOS.get(tipo, ident)


def _sensor(l: dict, conds_por_sensor: dict, base: dict, contexto: str | None, giro_previo: set) -> dict:
    """Un sensor con su estado, la referencia aprendida de ese contexto y si está dentro de la banda."""
    nombre, valor, unidad = l["nombre"], l["valor"], l["unidad"]
    cond = conds_por_sensor.get(nombre)
    s = {"nombre": nombre, "etiqueta": etiqueta(nombre), "valor": valor, "unidad": unidad,
         "estado": cond["severidad"] if cond else "normal", "mensaje": cond["mensaje"] if cond else None,
         "referencia": "ninguna", "dentro_de_banda": None, "banda": None}
    pf = linea_base.perfil(nombre, unidad or "")
    if pf:
        b = base.get((nombre, contexto))
        if b is None:
            s["referencia"] = "aprendiendo"
        else:
            banda = _banda_de(b, pf)
            s["banda"], s["referencia"] = banda, "aprendida" if banda["madura"] else "aprendiendo"
            if banda["madura"]:
                bajo, alto = banda["limite"]
                s["dentro_de_banda"] = not ((alto is not None and valor >= alto) or (bajo is not None and valor <= bajo))
    elif unidad != "bool":
        s["referencia"] = "fija"
    if unidad == "RPM":
        # parado: hay registro de que giró y ahora no; vacío: marca 0 y nunca se lo vio girar (conector sin ventilador, o sin historia)
        s["giro"] = "gira" if valor > 0 else "parado" if nombre in giro_previo else "vacio"
        s["conector_vacio"] = s["giro"] == "vacio"
    return s


def _principal(tipo: str, ident: str, sensores: list[dict]) -> dict | None:
    """El sensor que representa al componente en su tarjeta."""
    def elegir(*finales, unidad=None):
        for f in finales:
            for s in sensores:
                if s["nombre"].endswith(f):
                    return s
        return next((s for s in sensores if unidad and s["unidad"] == unidad), None)
    if tipo == "cpu":
        s = elegir("/Tctl", unidad="°C")
    elif tipo == "gpu":
        s = elegir("/junction", "/edge", unidad="°C")
    elif tipo == "ram":
        s = elegir("/ram_pct")
    elif tipo == "disco" and ident == "particiones":
        s = min((x for x in sensores if x["nombre"].endswith("/libre_pct")), key=lambda x: x["valor"], default=None)
    elif tipo == "disco":
        s = elegir("/temp1", "/Composite", unidad="°C") or elegir("/smart_ok")
    elif tipo == "ventiladores":
        s = max((x for x in sensores), key=lambda x: x["valor"], default=None)
    else:
        s = max((x for x in sensores if x["unidad"] == "°C"), key=lambda x: x["valor"], default=sensores[0] if sensores else None)
    return {k: s[k] for k in ("nombre", "etiqueta", "valor", "unidad", "dentro_de_banda", "referencia")} if s else None


def componentes(con, estado: dict) -> dict[str, list[dict]]:
    """Agrupa las lecturas en componentes (cpu, gpu, ram, un disco por entrada, ventiladores, voltajes, placa)."""
    lecturas, contexto = estado["lecturas"], estado["contexto"]
    conds_por_sensor = {}
    for c in estado["conds"].values():  # si hay varias condiciones para un sensor, queda la más grave
        n = c.get("nombre")
        if n and ESTADO_ORDEN[c["severidad"]] >= ESTADO_ORDEN[conds_por_sensor.get(n, {"severidad": "normal"})["severidad"]]:
            conds_por_sensor[n] = c
    base = {(b["nombre"], b["contexto"]): b for b in con.execute("SELECT * FROM linea_base")}
    giro_previo = {r["nombre"] for r in con.execute("SELECT nombre FROM lecturas WHERE unidad='RPM' GROUP BY nombre HAVING MAX(valor) > 0")}
    nvme = next((l["nombre"].split("/")[0] for l in lecturas if l["nombre"].startswith("nvme") and l["nombre"][4:5].isdigit()), None)
    hw = _modelos_hardware(con)
    grupos: dict[tuple, list] = defaultdict(list)
    for l in lecturas:
        grupos[_clasificar(l, nvme)].append(_sensor(l, conds_por_sensor, base, contexto, giro_previo))
    res: dict[str, list] = {t: [] for t in TIPOS_COMPONENTE}
    for (tipo, ident), sensores in sorted(grupos.items()):
        peor = max((s["estado"] for s in sensores), key=ESTADO_ORDEN.get)
        titulo = _titulo(tipo, ident, hw)
        res.setdefault(tipo, []).append({
            "tipo": tipo, "id": ident, "titulo": titulo, "estado": peor, "principal": _principal(tipo, ident, sensores),
            "aprendiendo": any(s["referencia"] == "aprendiendo" for s in sensores), "sensores": sensores})
    return res


# ---------- series ----------

def serie(con, sensor: str, t0: int, t1: int, contexto: str = "", max_puntos: int = MAX_PUNTOS_SERIE,
          diario: bool | None = None) -> dict:
    """Puntos de un sensor para graficar, con las bandas de la línea base y la actividad de cada momento.

    Hasta 30 días usa las lecturas crudas (agrupadas si son demasiadas). Sobre ese rango usa el registro diario y las
    lecturas crudas solo de hoy; los días anteriores a las lecturas crudas disponibles salen siempre del registro diario.
    `diario=False` fuerza usar las crudas en todo el rango (lo usa historial() del MCP); `True` fuerza el registro diario.
    """
    filtro, fargs = (" AND contexto=?", [contexto]) if contexto else ("", [])
    diario = (t1 - t0) > RANGO_DIARIO_DIAS * 86400 if diario is None else diario
    inicio_crudas = max(t0, db.dia_a_epoch(db.inicio_dia_local(db.ahora()))) if diario else t0
    crudas = con.execute(f"SELECT ts, valor, unidad, contexto FROM lecturas WHERE nombre=? AND ts BETWEEN ? AND ?{filtro} ORDER BY ts",
                         [sensor, inicio_crudas, t1] + fargs).fetchall()
    primer_dia = db.inicio_dia_local(crudas[0]["ts"]) if crudas else "9999-12-31"
    diarias = con.execute(
        f"SELECT dia, SUM(n * media) / SUM(n) v, MIN(minimo) mn, MAX(maximo) mx, MAX(unidad) unidad, "
        f"CASE WHEN COUNT(DISTINCT contexto) = 1 THEN MAX(contexto) END ctx FROM lecturas_diarias "
        f"WHERE nombre=? AND dia >= ? AND dia <= ? AND dia < ?{filtro} GROUP BY dia ORDER BY dia",
        [sensor, db.inicio_dia_local(t0), db.inicio_dia_local(t1), primer_dia] + fargs).fetchall()
    unidad = crudas[0]["unidad"] if crudas else (diarias[0]["unidad"] if diarias else None)
    bs = bandas(con, sensor, unidad, (contexto,) if contexto else ("reposo", "carga", "juego"))
    ses = [(s["inicio"], s["fin"] or s["ultima_vez"], s["detalle"]) for s in con.execute(
        "SELECT inicio, fin, ultima_vez, detalle FROM sesiones_actividad WHERE inicio <= ? AND COALESCE(fin, ultima_vez) >= ?", (t1, t0))] \
        if _existe(con, "sesiones_actividad") else []

    def actividad_en(ts):
        return next((d for a, b, d in ses if a <= ts <= b), None)

    def fuera(v, ctx):
        b = bs.get(ctx)
        if not b or not b["madura"]:
            return False
        bajo, alto = b["limite"]
        return (alto is not None and v >= alto) or (bajo is not None and v <= bajo)

    puntos = [{"t": db.dia_a_epoch(d["dia"]), "v": d["v"], "min": d["mn"], "max": d["mx"], "c": d["ctx"], "a": None, "f": False}
              for d in diarias]
    crudos = [{"t": r["ts"], "v": r["valor"], "c": r["contexto"], "a": actividad_en(r["ts"]), "f": fuera(r["valor"], r["contexto"])}
              for r in crudas]
    resolucion = "diaria + cruda" if diarias and crudos else "diaria" if diarias else "cruda"
    if len(crudos) > max_puntos:
        paso = math.ceil((crudos[-1]["t"] - crudos[0]["t"] + 1) / max_puntos)
        cubos: dict[int, list] = defaultdict(list)
        for p in crudos:
            cubos[(p["t"] - crudos[0]["t"]) // paso].append(p)
        crudos = [{"t": round(sum(p["t"] for p in g) / len(g)), "v": sum(p["v"] for p in g) / len(g),
                   "min": min(p["v"] for p in g), "max": max(p["v"] for p in g),
                   "c": Counter(p["c"] for p in g).most_common(1)[0][0], "a": next((p["a"] for p in g if p["a"]), None),
                   "f": any(p["f"] for p in g)} for _, g in sorted(cubos.items())]
        resolucion += f" agrupada cada {max(1, round(paso / 60))} min"
    puntos += crudos
    return {"sensor": sensor, "etiqueta": etiqueta(sensor), "unidad": unidad, "desde": t0, "hasta": t1,
            "contexto": contexto or None, "resolucion": resolucion, "puntos": puntos, "bandas": bs, "n_diarios": len(diarias)}


def _existe(con, tabla: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tabla,)).fetchone() is not None


def tabla_existe(con, tabla: str) -> bool:
    return _existe(con, tabla)


# ---------- aprendizaje y limitaciones ----------

LIMITACIONES_FIJAS = [
    {"tema": "Rootkits y procesos de otros usuarios", "que": "No se detectan",
     "por_que": "El escaneo de seguridad corre sin permisos de administrador. No es un antivirus: un resultado limpio no garantiza un equipo limpio."},
    {"tema": "Voltajes de la placa", "que": "Se registran y se aprenden, pero no tienen un valor nominal de referencia",
     "por_que": "El kernel entrega las entradas sin el nombre del riel (in0 a in14) y el mapeo depende de cada placa. No se inventó ninguno."},
    {"tema": "Temperaturas sin sensor real", "que": "Se ignoran las entradas AUXTIN, PECI Agent y PCH",
     "por_que": "Son conectores de termistor sin conectar o valores del chipset que dan lecturas falsas (por ejemplo 84 y -61 °C)."},
    {"tema": "Ventiladores en 0 RPM", "que": "Solo se vigilan los que alguna vez giraron",
     "por_que": "Un conector sin ventilador marca 0 RPM siempre. Un ventilador que giraba y se frena sí genera una alerta."},
    {"tema": "Resolución temporal", "que": "Una lectura cada 15 minutos",
     "por_que": "Es la frecuencia del recolector. Un pico o un juego abierto y cerrado entre dos corridas no se ven."},
    {"tema": "Hora del día y estación del año", "que": "La línea base no los distingue",
     "por_que": "El calor del verano puede mover los valores normales. La deriva lenta compara contra un mes y avisa como mucho una vez por semana."},
    {"tema": "Swap", "que": "La regla de swap no aplica",
     "por_que": "El equipo no tiene swap configurada: si la RAM se agota, el kernel mata procesos directamente."},
    {"tema": "GPU NVIDIA", "que": "El lector de nvidia-smi no se probó con hardware real",
     "por_que": "Este equipo tiene una GPU AMD; el lector se probó solo con datos sintéticos."},
    {"tema": "Detección de juegos", "que": "Se basa en la línea de comandos de los procesos",
     "por_que": "Un programa de Windows bajo wine que no sea un juego puede contar como juego."},
]


def aprendizaje(con) -> dict:
    """Qué sensores ya tienen línea base madura y cuánto falta a los demás, por contexto."""
    desde = db.ahora() - linea_base.VENTANA_DIAS * 86400
    filas = con.execute(
        "SELECT nombre, contexto, MAX(unidad) unidad, COUNT(*) n, MIN(ts) primero, MAX(ts) ultimo FROM lecturas "
        "WHERE contexto IS NOT NULL AND ts >= ? GROUP BY nombre, contexto", (desde,)).fetchall()
    sensores, por_contexto = [], defaultdict(lambda: {"sensores": 0, "maduros": 0})
    for f in filas:
        if not linea_base.perfil(f["nombre"], f["unidad"] or ""):
            continue
        falta = max(0, linea_base.MIN_MUESTRAS - f["n"])
        dias = max(1.0, (f["ultimo"] - f["primero"]) / 86400)
        ritmo = f["n"] / dias
        por_contexto[f["contexto"]]["sensores"] += 1
        por_contexto[f["contexto"]]["maduros"] += not falta
        sensores.append({"sensor": f["nombre"], "contexto": f["contexto"], "muestras": f["n"], "minimo": linea_base.MIN_MUESTRAS,
                         "falta": falta, "madura": not falta, "ritmo_por_dia": round(ritmo, 1),
                         # en carga y juego depende de cuánto se use el equipo: no se estima
                         "dias_estimados": round(falta / ritmo, 1) if falta and ritmo > 0 and f["contexto"] == "reposo" else None,
                         "depende_del_uso": f["contexto"] != "reposo"})
    return {"resumen": linea_base.resumen(con), "por_contexto": dict(por_contexto),
            "sensores": sorted(sensores, key=lambda s: (s["madura"], s["falta"], s["sensor"]))}

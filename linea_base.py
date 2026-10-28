"""Aprendizaje de valores normales: registro diario, línea base por componente y detección de anomalías y deriva.

Cada lectura se etiqueta con un contexto (reposo, carga o juego) para comparar manzanas con manzanas: una GPU a 70 °C
jugando es normal, a 70 °C en reposo no. La línea base usa mediana y desvío robusto (MAD), que resisten datos atípicos.
Las alertas aprendidas son siempre de tipo "aviso"; los críticos siguen siendo límites absolutos del hardware.
"""

import statistics
from collections import defaultdict

import db
from db import log

VENTANA_DIAS = 30            # ventana de la línea base (coincide con la retención de lecturas crudas)
MIN_MUESTRAS = 200           # muestras mínimas por sensor y contexto para considerar madura la base (~2 días)
RECALCULAR_CADA_S = 6 * 3600
Z_ANOMALIA = 4.0             # desvíos robustos respecto de la mediana
UMBRAL_CPU_REPOSO = 25       # % de CPU bajo el cual se considera reposo
UMBRAL_GPU_REPOSO = 20       # % de GPU bajo el cual se considera reposo
REPETIR_DERIVA_S = 7 * 86400  # la deriva es lenta: se avisa como mucho una vez por semana


def contexto_de(lecturas: list[dict], juego: bool = False) -> str | None:
    """'juego' si hay un juego en ejecución; si no, 'reposo' o 'carga' según el uso de CPU y GPU. None sin dato de CPU."""
    cpu = next((l["valor"] for l in lecturas if l["nombre"] == "cpu/uso"), None)
    if cpu is None:
        return None
    if juego:
        return "juego"
    gpu = max((l["valor"] for l in lecturas if l["categoria"] == "gpu" and l["nombre"].endswith("/uso")), default=0)
    return "reposo" if cpu < UMBRAL_CPU_REPOSO and gpu < UMBRAL_GPU_REPOSO else "carga"


def perfil(nombre: str, unidad: str) -> dict | None:
    """Cómo se aprende cada tipo de sensor: lados vigilados, piso del desvío y cambio mínimo que importa."""
    if unidad == "°C":
        return {"lados": "alto", "piso": 2.0, "delta": lambda p50: 8.0}
    if unidad == "RPM":
        return {"lados": "ambos", "piso": 50.0, "delta": lambda p50: max(200.0, 0.3 * p50)}
    if unidad == "W":
        return {"lados": "alto", "piso": 2.0, "delta": lambda p50: max(20.0, 0.5 * p50)}
    if unidad == "mV":
        return {"lados": "ambos", "piso": 15.0, "delta": lambda p50: 100.0}
    if nombre.endswith("/ram_pct"):
        return {"lados": "alto", "piso": 2.0, "delta": lambda p50: 15.0}
    if nombre.endswith("/libre_pct"):
        return {"lados": "bajo", "piso": 0.5, "delta": lambda p50: 5.0}
    return None


# ---------- registro diario y línea base ----------

def rollup_diario(con) -> int:
    """Resume en `lecturas_diarias` los días completos que aún no están resumidos. Devuelve cuántas filas agregó."""
    dias = [r[0] for r in con.execute(
        "SELECT DISTINCT date(ts,'unixepoch','localtime') d FROM lecturas WHERE contexto IS NOT NULL "
        "AND d < date('now','localtime') AND d NOT IN (SELECT DISTINCT dia FROM lecturas_diarias)")]
    n = 0
    for d in dias:
        cur = con.execute(
            "INSERT OR REPLACE INTO lecturas_diarias (dia, nombre, contexto, categoria, unidad, n, media, minimo, maximo) "
            "SELECT ?, nombre, contexto, MAX(categoria), MAX(unidad), COUNT(*), AVG(valor), MIN(valor), MAX(valor) "
            "FROM lecturas WHERE contexto IS NOT NULL AND date(ts,'unixepoch','localtime') = ? GROUP BY nombre, contexto",
            (d, d))
        n += cur.rowcount
    return n


def _percentil(ordenados: list[float], p: float) -> float:
    return ordenados[min(len(ordenados) - 1, int(p * len(ordenados)))]


def estadisticas(valores: list[float]) -> dict:
    """Media, desviación, extremos, mediana, MAD y percentiles de una lista de valores."""
    v = sorted(valores)
    p50 = statistics.median(v)
    return {"n": len(v), "media": statistics.fmean(v), "desviacion": statistics.pstdev(v) if len(v) > 1 else 0.0,
            "minimo": v[0], "maximo": v[-1], "p50": p50, "mad": statistics.median(abs(x - p50) for x in v),
            "p95": _percentil(v, 0.95), "p99": _percentil(v, 0.99)}


def recalcular_base(con, forzar: bool = False) -> int:
    """Recalcula la línea base (últimos 30 días) por sensor y contexto, como mucho cada 6 h. Devuelve cuántas filas."""
    ultima = con.execute("SELECT MAX(actualizada_en) m FROM linea_base").fetchone()["m"]
    if not forzar and ultima and db.ahora() - ultima < RECALCULAR_CADA_S:
        return 0
    desde = db.ahora() - VENTANA_DIAS * 86400
    grupos = defaultdict(list)
    meta = {}
    for r in con.execute("SELECT nombre, contexto, categoria, unidad, valor, ts FROM lecturas WHERE contexto IS NOT NULL AND ts >= ?",
                         (desde,)):
        k = (r["nombre"], r["contexto"])
        grupos[k].append((r["ts"], r["valor"]))
        meta[k] = (r["categoria"], r["unidad"])
    ahora = db.ahora()
    con.execute("DELETE FROM linea_base")
    guardadas = 0
    for (nombre, ctx), pares in grupos.items():
        if len(pares) < 20:  # muy poco para mostrar algo útil
            continue
        guardadas += 1
        e = estadisticas([v for _, v in pares])
        con.execute(
            "INSERT INTO linea_base (nombre, contexto, categoria, unidad, n, media, desviacion, minimo, maximo, p50, mad, "
            "p95, p99, desde, hasta, actualizada_en) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (nombre, ctx, *meta[(nombre, ctx)], e["n"], e["media"], e["desviacion"], e["minimo"], e["maximo"], e["p50"],
             e["mad"], e["p95"], e["p99"], min(t for t, _ in pares), max(t for t, _ in pares), ahora))
    return guardadas


def mantener(con) -> dict:
    """Mantenimiento del aprendizaje en cada corrida: registro diario y línea base."""
    return {"dias_resumidos": rollup_diario(con), "base_recalculada": recalcular_base(con)}


# ---------- detección ----------

def escala_robusta(b, pf: dict) -> float:
    """Desvío robusto de la línea base (MAD escalado), con un piso para sensores muy estables."""
    return max(1.4826 * b["mad"], pf["piso"])


def limites(b, pf: dict) -> tuple[float | None, float | None]:
    """(bajo, alto): fuera de estos límites un valor es anómalo. None en el lado que ese sensor no vigila.

    Es lo que usa la detección de anomalías y lo que dibuja el dashboard, para que nunca diverjan.
    """
    margen = max(Z_ANOMALIA * escala_robusta(b, pf), pf["delta"](b["p50"]))
    bajo = b["p50"] - margen if pf["lados"] in ("bajo", "ambos") else None
    alto = b["p50"] + margen if pf["lados"] in ("alto", "ambos") else None
    return bajo, alto


def _anomalo(v: float, b, pf: dict) -> bool:
    bajo, alto = limites(b, pf)
    return (alto is not None and v >= alto) or (bajo is not None and v <= bajo)


def condiciones_anomalias(con, lecturas: list[dict], contexto: str | None, en_base: bool = True) -> dict[str, dict]:
    """Valores muy distintos de lo habitual de ese sensor en ese contexto, dos lecturas seguidas (evita falsos picos)."""
    res = {}
    if not contexto:
        return res
    for l in lecturas:
        pf = perfil(l["nombre"], l["unidad"])
        if not pf:
            continue
        b = con.execute("SELECT * FROM linea_base WHERE nombre=? AND contexto=?", (l["nombre"], contexto)).fetchone()
        if not b or b["n"] < MIN_MUESTRAS or not _anomalo(l["valor"], b, pf):
            continue
        # con la lectura ya guardada, la anterior del mismo contexto es la segunda fila; en vivo, la primera
        previas = con.execute("SELECT valor FROM lecturas WHERE nombre=? AND contexto=? ORDER BY ts DESC, metrica_id DESC LIMIT 2",
                              (l["nombre"], contexto)).fetchall()
        i = 1 if en_base else 0
        if len(previas) <= i or not _anomalo(previas[i]["valor"], b, pf):
            continue
        clave = f"anomalia:{l['nombre']}:{contexto}"
        res[clave] = {"clave": clave, "categoria": l["categoria"], "nombre": l["nombre"], "severidad": "aviso",
                      "valor": l["valor"],
                      "mensaje": f"Fuera de lo habitual: {l['nombre']} = {l['valor']:.1f} {l['unidad']} en {contexto} "
                                 f"(lo normal es {b['p50']:.1f}, 99 % de las veces menos de {b['p99']:.1f})"}
    return res


def condiciones_deriva(con) -> dict[str, dict]:
    """Cambios lentos en reposo: compara los últimos 7 días con los 37 anteriores (de 8 a 45 días atrás).

    Temperatura +6 °C, ventilador +30 % o espacio libre -8 puntos. Necesita al menos 3 semanas de datos
    (7 días recientes + 14 de referencia), para no confundir una variación normal con un desgaste.
    """
    filas = con.execute(
        "SELECT nombre, categoria, unidad, n, media, "
        "CAST(julianday(date('now','localtime')) - julianday(dia) AS INTEGER) AS edad "
        "FROM lecturas_diarias WHERE contexto='reposo' AND dia < date('now','localtime') "
        "AND dia >= date('now','localtime','-45 day')").fetchall()
    por = defaultdict(lambda: {"rec": [], "ref": []})
    for f in filas:
        if f["unidad"] == "°C" or f["unidad"] == "RPM" or f["nombre"].endswith("/libre_pct"):
            por[(f["nombre"], f["categoria"], f["unidad"])]["rec" if f["edad"] <= 7 else "ref"].append((f["n"], f["media"]))
    res = {}
    for (nombre, cat, unidad), g in por.items():
        if len(g["rec"]) < 3 or len(g["ref"]) < 14 or sum(n for n, _ in g["rec"]) < 100 or sum(n for n, _ in g["ref"]) < 600:
            continue
        rec = sum(n * m for n, m in g["rec"]) / sum(n for n, _ in g["rec"])
        ref = sum(n * m for n, m in g["ref"]) / sum(n for n, _ in g["ref"])
        d = rec - ref
        if unidad == "°C" and d >= 6:
            msg = f"{nombre} en reposo subió {d:.1f} °C ({ref:.1f} -> {rec:.1f}): revisar polvo, flujo de aire o pasta térmica"
        elif unidad == "RPM" and ref > 0 and d / ref >= 0.30:
            msg = f"{nombre} gira {d / ref * 100:.0f} % más rápido en reposo ({ref:.0f} -> {rec:.0f} RPM): posible polvo o calor"
        elif nombre.endswith("/libre_pct") and d <= -8:
            msg = f"{nombre} perdió {-d:.1f} puntos de espacio libre en un mes ({ref:.1f} % -> {rec:.1f} %)"
        else:
            continue
        clave = f"deriva:{nombre}"
        res[clave] = {"clave": clave, "categoria": cat, "nombre": nombre, "severidad": "aviso", "valor": rec,
                      "mensaje": f"Deriva: {msg}", "repetir_s": REPETIR_DERIVA_S}
    return res


def resumen(con) -> dict:
    """Estado del aprendizaje: cuántos sensores tienen base madura y cuántas muestras faltan."""
    filas = con.execute("SELECT n FROM linea_base").fetchall()
    maduros = sum(1 for f in filas if f["n"] >= MIN_MUESTRAS)
    dias = con.execute("SELECT COUNT(DISTINCT dia) c FROM lecturas_diarias").fetchone()["c"]
    return {"sensores_con_base": len(filas), "maduros": maduros, "minimo_muestras": MIN_MUESTRAS, "dias_registrados": dias,
            "estado": "aprendiendo (sin avisos aprendidos todavía)" if not maduros else "activo"}

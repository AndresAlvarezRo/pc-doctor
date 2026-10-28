"""Correlación de eventos y línea de tiempo: qué pasó cerca de una alerta.

Junta en una sola lista lo que registra pc-doctor (cambios de entorno, eventos del sistema, alertas, hallazgos de
seguridad, sesiones de actividad y acciones) y lo ordena por cercanía en el tiempo y afinidad con la alerta.
El resultado son **coincidencias en el tiempo** ("posibles causas"): nunca se afirma que algo fue la causa.

Las listas de afinidad están todas al principio, para ajustarlas en un solo lugar.
"""

import json
import re
import sqlite3

import db
import reputacion

# ---------- ajustes ----------
HORAS_ANTES = 48            # ventana por defecto antes del momento (config.json -> "correlacion": {"horas_antes": N})
HORAS_DESPUES = 2           # y después
MITAD_VIDA_ANTES_H = 12     # cada 12 h de distancia, el peso de lo ocurrido antes se reduce a la mitad
MITAD_VIDA_DESPUES_H = 1    # lo ocurrido después se descuenta más rápido: no puede ser causa
FUERTE_ULTIMAS_H = 24       # para la notificación: solo cambios de entorno de las últimas 24 h
AFINIDAD_FUERTE = 0.8       # afinidad mínima para llamar "fuerte" a un candidato en la notificación
MAX_CANDIDATOS = 8          # candidatos que devuelve correlacionar()
MAX_POR_TIPO = 3            # como mucho 3 candidatos del mismo tipo, para que un solo origen ruidoso no tape al resto
MAX_LINEA = 80              # filas máximas de la línea de tiempo
MAX_PAQUETES_RELEVANTES = 10

CATEGORIAS_HARDWARE = {"cpu", "gpu", "disco", "memoria", "placa"}

# Paquetes por categoría de hardware con la que pueden estar relacionados: (categoría, regex del nombre, afinidad 0 a 1)
AFINIDAD_PAQUETES = [
    ("gpu", re.compile(r"^(mesa|libdrm|libgl|libegl|libvulkan|vulkan|xserver-xorg|xorg|nvidia|amdgpu|rocm|libva|vdpau|libglx)"), 0.9),
    ("gpu", re.compile(r"^linux-firmware"), 0.8),
    ("cpu", re.compile(r"^(intel-microcode|amd64-microcode|cpufrequtils|thermald|tlp|power-profiles|linux-(image|modules|headers))"), 0.85),
    ("disco", re.compile(r"^(udisks|e2fsprogs|lvm2|mdadm|nvme-cli|xfsprogs|btrfs|fstrim)"), 0.85),
    ("memoria", re.compile(r"^(earlyoom|zram|systemd-oomd)"), 0.8),
    ("placa", re.compile(r"^(fancontrol|fwupd|bios)"), 0.8),
]
# Herramientas de monitoreo: instalarlas suele destapar un problema que ya existía, no causarlo
OBSERVADORES = [
    ("disco", re.compile(r"^(smartmontools|gsmartcontrol|nvme-cli)$")),
    ("placa", re.compile(r"^(lm-sensors|fancontrol|psensor)$")),
    ("gpu", re.compile(r"^(radeontop|nvtop|corectrl|lact)$")),
]
# Categoría probable de un evento del sistema según su origen y mensaje
CATEGORIA_EVENTO = [
    ("gpu", re.compile(r"amdgpu|\bdrm\b|\bgpu\b|nvidia|nouveau|i915|\bxe\b", re.I)),
    ("disco", re.compile(r"nvme|\bata\d|smartd|\bsd[a-z]\b|ext4|btrfs|i/o error|blk_update", re.I)),
    ("memoria", re.compile(r"out of memory|\boom\b|\bedac\b", re.I)),
    ("cpu", re.compile(r"thermal|\bmce\b|machine check|cpufreq|k10temp|throttl", re.I)),
]
# Afinidad base por tipo de elemento (se combina con la categoría de la alerta). El kernel queda bajo el umbral de
# "fuerte" a propósito: solo lo supera cuando trae el driver de la GPU (ver cambios_de_entorno)

BASE = {"driver_gpu": 1.0, "kernel": 0.7, "evento": 0.6, "alerta": 0.6, "hallazgo": 0.7, "sesion": 0.7, "accion": 0.3,
        "paquete_otros": 0.1}


def _config() -> tuple[int, int]:
    c = reputacion.cargar_config().get("correlacion") or {}
    try:
        return int(c.get("horas_antes", HORAS_ANTES)), int(c.get("horas_despues", HORAS_DESPUES))
    except (TypeError, ValueError):
        return HORAS_ANTES, HORAS_DESPUES


def _item(ts: int, tipo: str, titulo: str, cats: set | None, base: float, **extra) -> dict:
    return {"ts": ts, "tipo": tipo, "titulo": titulo, "cats": cats, "base": base, "observador": False, **extra}


# ---------- recolección de elementos ----------

def _paquetes(con, sid: int) -> dict:
    return {(r["origen"], r["nombre"]): r["version"]
            for r in con.execute("SELECT origen, nombre, version FROM software WHERE snapshot_id=?", (sid,))}


def _gpu(con, sid: int) -> dict:
    r = con.execute("SELECT detalle FROM hardware WHERE snapshot_id=? AND tipo='gpu' LIMIT 1", (sid,)).fetchone()
    try:
        return json.loads(r["detalle"]) if r and r["detalle"] else {}
    except ValueError:
        return {}


def _clasificar_paquete(nombre: str):
    """(categoría, afinidad, observador) del paquete, o None si no tiene relación aparente con el hardware."""
    for cat, rx in OBSERVADORES:
        if rx.search(nombre):
            return cat, 0.25, True
    for cat, rx, af in AFINIDAD_PAQUETES:
        if rx.search(nombre):
            return cat, af, False
    return None


def cambios_de_entorno(con, t0: int, t1: int) -> list[dict]:
    """Diferencias entre snapshots consecutivos cuyo momento cae en [t0, t1]: kernel, driver de GPU y paquetes.

    El snapshot se guarda la primera corrida en que cambió algo, así que la hora tiene precisión de ~15 min.
    """
    snaps = con.execute("SELECT * FROM snapshot_entorno ORDER BY tomado_en, id").fetchall()
    items = []
    for i in range(1, len(snaps)):
        previo, nuevo = snaps[i - 1], snaps[i]
        if not t0 <= nuevo["tomado_en"] <= t1:
            continue
        ts = nuevo["tomado_en"]
        ga, gb = _gpu(con, previo["id"]), _gpu(con, nuevo["id"])
        claves = [k for k in ("driver", "version_driver", "mesa") if ga.get(k) != gb.get(k)]
        difs = [f"{k}: {ga.get(k)} -> {gb.get(k)}" for k in claves]
        kernel_cambio = previo["kernel"] != nuevo["kernel"]
        # con un driver dentro del kernel (in-tree), el "cambio de driver" es el del kernel: se muestra un solo elemento
        en_kernel = kernel_cambio and claves == ["version_driver"]
        if kernel_cambio:
            it = _item(ts, "kernel", f"kernel {previo['kernel']} -> {nuevo['kernel']}"
                       + (" (incluye el driver de GPU, que viene con el kernel)" if en_kernel else ""), CATEGORIAS_HARDWARE, BASE["kernel"])
            if en_kernel:
                it["afin"] = {"gpu": BASE["driver_gpu"]}
            items.append(it)
        if difs and not en_kernel:
            items.append(_item(ts, "driver_gpu", "driver de GPU: " + "; ".join(difs), {"gpu"}, BASE["driver_gpu"]))
        a, b = _paquetes(con, previo["id"]), _paquetes(con, nuevo["id"])
        cambios = ([("instalado", n, b[(o, n)]) for (o, n) in b.keys() - a.keys()] +
                   [("quitado", n, a[(o, n)]) for (o, n) in a.keys() - b.keys()] +
                   [("actualizado", n, f"{a[(o, n)]} -> {b[(o, n)]}") for (o, n) in a.keys() & b.keys() if a[(o, n)] != b[(o, n)]])
        otros, relevantes = [], []
        for accion, nombre, version in cambios:
            c = _clasificar_paquete(nombre)
            (relevantes if c else otros).append((accion, nombre, version, c))
        for accion, nombre, version, (cat, af, obs) in relevantes[:MAX_PAQUETES_RELEVANTES]:
            it = _item(ts, "paquete", f"paquete {accion}: {nombre} {version}", {cat}, af)
            if obs:
                it["observador"] = True
                it["titulo"] += " (herramienta de monitoreo: puede haber destapado el problema, no causarlo)"
            items.append(it)
        resto = len(relevantes) - MAX_PAQUETES_RELEVANTES
        if resto > 0 or otros:
            ejemplos = ", ".join(n for _, n, _, _ in otros[:3])
            n_otros = len(otros) + max(resto, 0)
            items.append(_item(ts, "paquete_otros", f"{n_otros} {'paquete más' if n_otros == 1 else 'paquetes más'} sin relación aparente con el hardware"
                               + (f" (ej.: {ejemplos})" if ejemplos else ""), None, BASE["paquete_otros"]))
    return items


def _categoria_evento(origen: str, mensaje: str) -> set | None:
    texto = f"{origen} {mensaje}"
    for cat, rx in CATEGORIA_EVENTO:
        if rx.search(texto):
            return {cat}
    return None


def _eventos(con, t0: int, t1: int, momento: int | None) -> list[dict]:
    """Eventos del sistema agrupados por mensaje repetido (se conserva la aparición más cercana al momento)."""
    grupos = {}
    for r in con.execute("SELECT ts, origen, severidad, mensaje FROM eventos WHERE ts BETWEEN ? AND ? ORDER BY ts", (t0, t1)):
        k = (r["origen"], (r["mensaje"] or "")[:80])
        g = grupos.setdefault(k, {"n": 0, "ts": r["ts"], "r": r})
        g["n"] += 1
        if momento is not None and abs(r["ts"] - momento) < abs(g["ts"] - momento):
            g["ts"], g["r"] = r["ts"], r
    res = []
    for (origen, _), g in grupos.items():
        r = g["r"]
        veces = f" (x{g['n']})" if g["n"] > 1 else ""
        res.append(_item(g["ts"], "evento", f"{r['severidad']} {origen}: {(r['mensaje'] or '')[:110]}{veces}",
                         _categoria_evento(origen or "", r["mensaje"] or ""), BASE["evento"]))
    return res


def _alertas(con, t0: int, t1: int, excluir: str | None) -> list[dict]:
    res = []
    for r in con.execute("SELECT rowid AS id, * FROM alertas_salud WHERE desde BETWEEN ? AND ?", (t0, t1)):
        if r["clave"] == excluir:
            continue
        fin = f", resuelta {db.iso(r['resuelta_en'])[-5:]}" if r["resuelta_en"] else ", sigue activa" if r["activa"] else ""
        res.append(_item(r["desde"], "alerta", f"alerta {r['severidad']} de {r['categoria']}: {(r['mensaje'] or '')[:100]}{fin}",
                         {r["categoria"]} if r["categoria"] else None, BASE["alerta"], ref=f"alerta:{r['id']}"))
    return res


def _hallazgos(con, t0: int, t1: int, excluir_id: int | None) -> list[dict]:
    res = []
    for r in con.execute("SELECT * FROM hallazgos_seguridad WHERE primera_vez BETWEEN ? AND ?", (t0, t1)):
        if r["id"] == excluir_id:
            continue
        cats = {"cpu", "gpu"} if r["categoria"] == "minero" else {"seguridad", "red"}
        res.append(_item(r["primera_vez"], "hallazgo", f"seguridad ({r['severidad']}, {r['categoria']}): {r['nombre']} - {(r['detalle'] or '')[:80]}",
                         cats, BASE["hallazgo"], ref=f"hallazgo:{r['id']}"))
    return res


def _sesiones(con, t0: int, t1: int) -> list[dict]:
    res = []
    for r in con.execute("SELECT * FROM sesiones_actividad WHERE inicio <= ? AND COALESCE(fin, ultima_vez) >= ?", (t1, t0)):
        fin = r["fin"] or r["ultima_vez"]
        res.append(_item(r["inicio"], "sesion", f"{r['tipo']}: {r['detalle']} ({round((fin - r['inicio']) / 60)} min"
                         f"{', en curso' if r['fin'] is None else ''})", {"cpu", "gpu", "placa", "memoria"}, BASE["sesion"], ts_fin=fin,
                         ref=f"sesion:{r['id']}"))
    return res


def _acciones(con, t0: int, t1: int) -> list[dict]:
    res = []
    for r in con.execute("SELECT ts, tool, resultado FROM acciones WHERE ts BETWEEN ? AND ?", (t0, t1)):
        cats = {"disco"} if r["tool"] in ("limpiar_descargas_viejas", "restaurar_cuarentena") else None
        res.append(_item(r["ts"], "accion", f"acción de pc-doctor: {r['tool']} - {(r['resultado'] or '')[:80]}",
                         cats, 0.5 if cats else BASE["accion"]))
    return res


def elementos(con, t0: int, t1: int, momento: int | None = None, excluir_alerta: str | None = None,
              excluir_hallazgo: int | None = None) -> list[dict]:
    """Todo lo registrado entre t0 y t1, sin ordenar ni puntuar."""
    res = []
    for fuente, args in ((cambios_de_entorno, (t0, t1)), (_eventos, (t0, t1, momento)), (_alertas, (t0, t1, excluir_alerta)),
                         (_hallazgos, (t0, t1, excluir_hallazgo)), (_sesiones, (t0, t1)), (_acciones, (t0, t1))):
        try:
            res += fuente(con, *args)
        except sqlite3.OperationalError as e:  # base de una versión anterior: falta la tabla de esa fuente, las demás siguen
            if "no such table" not in str(e):
                raise
    return res


# ---------- puntuación ----------

def afinidad(it: dict, categoria: str | None) -> float:
    """Qué tan relacionado está el elemento con la categoría de la alerta (0 a 1)."""
    if categoria in it.get("afin", {}):  # afinidad propia de esa categoría (ej. kernel que trae el driver de GPU)
        return it["afin"][categoria]
    if it["cats"] is None:
        return it["base"] * 0.6
    return it["base"] if categoria in it["cats"] else it["base"] * 0.25


def cercania(it: dict, momento: int) -> float:
    """1 si ocurrió en el momento; baja a la mitad cada 12 h antes (cada 1 h si fue después y ya no puede ser causa)."""
    ini, fin = it["ts"], it.get("ts_fin", it["ts"])
    if ini <= momento <= fin:
        return 1.0
    if fin < momento:
        return 0.5 ** ((momento - fin) / 3600 / MITAD_VIDA_ANTES_H)
    return 0.5 * 0.5 ** ((ini - momento) / 3600 / MITAD_VIDA_DESPUES_H)


def etiqueta(puntaje: float) -> str:
    return "alta" if puntaje >= 0.5 else "media" if puntaje >= 0.2 else "baja"


def _hace(ts: int, momento: int) -> str:
    d = ts - momento
    h = abs(d) / 3600
    texto = f"{round(abs(d) / 60)} min" if h < 1 else f"{h:.1f} h"
    return f"{texto} {'antes' if d <= 0 else 'después'}"


def posibles_causas(con, momento: int, categoria: str | None, antes_h: int | None = None, despues_h: int | None = None,
                    excluir_alerta: str | None = None, excluir_hallazgo: int | None = None) -> list[dict]:
    """Candidatos ordenados de mayor a menor (afinidad por cercanía). No prueban causalidad."""
    cfg_a, cfg_d = _config()
    t0 = momento - (antes_h if antes_h is not None else cfg_a) * 3600
    t1 = momento + (despues_h if despues_h is not None else cfg_d) * 3600
    res = []
    for it in elementos(con, t0, t1, momento, excluir_alerta, excluir_hallazgo):
        p = afinidad(it, categoria) * cercania(it, momento)
        if p >= 0.03:
            res.append({"puntaje": round(p, 3), "relevancia": etiqueta(p), "cuando": _hace(it["ts"], momento),
                        "tipo": it["tipo"], "que": it["titulo"]})
    res.sort(key=lambda r: r["puntaje"], reverse=True)
    vistos, variados, resto = {}, [], []
    for r in res:
        vistos[r["tipo"]] = vistos.get(r["tipo"], 0) + 1
        (variados if vistos[r["tipo"]] <= MAX_POR_TIPO else resto).append(r)
    return variados + resto  # los repetidos de un mismo tipo quedan al final, solo contados


def relacion_fuerte(con, categoria: str | None, momento: int) -> str | None:
    """Texto breve para la notificación si hay un cambio de entorno claramente afín en las últimas 24 h; si no, None.

    Solo cuentan cambios de driver, kernel o paquetes de la misma categoría. Eventos, alertas y sesiones de juego
    no se citan: darían ruido en el aviso. Las herramientas de monitoreo tampoco (destapan, no causan).
    """
    if not categoria:
        return None
    mejor = None
    for it in cambios_de_entorno(con, momento - FUERTE_ULTIMAS_H * 3600, momento):
        if it["tipo"] not in ("driver_gpu", "kernel", "paquete") or it["observador"] or afinidad(it, categoria) < AFINIDAD_FUERTE:
            continue
        p = afinidad(it, categoria) * cercania(it, momento)
        if mejor is None or p > mejor[0]:
            mejor = (p, it)
    return f"{mejor[1]['titulo']} (hace {_hace(mejor[1]['ts'], momento).split(' antes')[0]})" if mejor else None


# ---------- línea de tiempo ----------

def linea_de_tiempo(con, t0: int, t1: int, tipos: set | None = None, limite: int = MAX_LINEA, estructurado: bool = False) -> dict:
    """Todo lo registrado en el rango, en orden cronológico y compacto. `tipos` filtra por tipo de elemento."""
    items = sorted((i for i in elementos(con, t0, t1) if not tipos or i["tipo"] in tipos),
                   key=lambda i: (i["ts"], i["tipo"], i["titulo"]))  # desempate: orden estable
    filas = [[db.iso(i["ts"]), i["tipo"], i["titulo"]] for i in items]
    res = {"desde": db.iso(t0), "hasta": db.iso(t1), "total": len(filas), "cronologia": filas[:limite]}
    if len(filas) > limite:
        res["nota"] = f"Se muestran las primeras {limite} de {len(filas)}: acotá el rango para ver el resto."
    if estructurado:
        res["items"] = [{"ts": i["ts"], "fin": i.get("ts_fin"), "tipo": i["tipo"], "titulo": i["titulo"], "ref": i.get("ref")}
                        for i in items[:limite]]
    return res

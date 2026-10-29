"""Recetas: lo que ya funcionó (o falló) contra una misma alerta, guardado solo como datos estructurados.

Una receta es una firma de alerta (regla + componente, sin valores concretos) más una lista ordenada de acciones del catálogo con
sus parámetros. Se crea o se refuerza ÚNICAMENTE cuando un plan termina `verificado` (la alerta se resolvió y se cumplió el efecto
de cada acción); un plan `fallido` le baja la confianza a la receta que coincide. Nunca se guarda texto del modelo (ni hipótesis,
ni «porque»): la próxima vez que aparezca la misma firma, el diagnóstico recibe estas recetas como datos con su tasa de éxito, y
cualquier acción que proponga a partir de ellas vuelve a pasar por el catálogo, la validación y la aprobación.
"""

import hashlib
import json

import db
import remediacion
from db import log

MADURA_DESDE = 2    # éxitos mínimos para que una receta se considere madura (la usa el nivel 2 de la fase 5)
MAX_PARA_PROMPT = 3


def _canonica(acciones: list[dict]) -> list[dict]:
    return [{"accion": a["accion"], "parametros": dict(sorted(a["parametros"].items()))} for a in acciones]


def _clave(acciones: list[dict]) -> str:
    return hashlib.sha256(json.dumps(_canonica(acciones), sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def _acciones_validas(acciones) -> list[dict] | None:
    """Las acciones de un plan, solo con nombre y parámetros ya validados (nada de `porque` ni `simulacion`).

    None si hay alguna que no se puede reutilizar (por ejemplo un pid) o que ya no valida."""
    if not isinstance(acciones, list) or not acciones:
        return None
    res = []
    for a in acciones:
        try:
            accion, params = remediacion.validar(a.get("accion"), a.get("parametros"))
        except (remediacion.Rechazo, AttributeError):
            return None
        if not accion.reutilizable:
            return None
        res.append({"accion": accion.nombre, "parametros": params})
    return res


def _forma(f) -> dict:
    n = f["funciono"] + f["fallo"]
    return {"id": f["id"], "firma": f["firma"], "acciones": json.loads(f["acciones"]), "aplicada": f["aplicada"], "funciono": f["funciono"],
            "fallo": f["fallo"], "tasa_exito": round(f["funciono"] / n, 2) if n else None, "ultima_vez": db.iso(f["ultima_vez"]),
            "madura": f["funciono"] >= MADURA_DESDE and f["funciono"] > f["fallo"]}


def registrar_resultado(con, plan_id: int, funciono: bool) -> dict | None:
    """Refuerza (o crea, solo si funcionó) la receta de un plan terminado. Devuelve la receta o None si no corresponde."""
    f = con.execute("SELECT p.acciones, d.firma FROM planes p JOIN diagnosticos d ON d.id=p.diagnostico_id WHERE p.id=?", (plan_id,)).fetchone()
    if f is None or not f["firma"]:
        return None
    try:
        acciones = _acciones_validas(json.loads(f["acciones"]))
    except ValueError:
        acciones = None
    if acciones is None:
        return None
    clave, ahora = _clave(acciones), db.ahora()
    r = con.execute("SELECT id FROM recetas WHERE firma=? AND clave=?", (f["firma"], clave)).fetchone()
    if r is None:
        if not funciono:
            return None     # un fallo no crea recetas: solo le baja la confianza a una que ya existe
        cur = con.execute("INSERT INTO recetas (firma, clave, acciones, aplicada, funciono, fallo, primera_vez, ultima_vez) VALUES (?,?,?,?,?,?,?,?)",
                          (f["firma"], clave, json.dumps(_canonica(acciones), ensure_ascii=False), 1, 1, 0, ahora, ahora))
        rid = cur.lastrowid
    else:
        rid = r["id"]
        con.execute(f"UPDATE recetas SET aplicada=aplicada+1, {'funciono=funciono+1' if funciono else 'fallo=fallo+1'}, ultima_vez=? WHERE id=?", (ahora, rid))
    con.commit()
    log.info("receta #%s %s (%s)", rid, "reforzada" if funciono else "debilitada", f["firma"])
    return _forma(con.execute("SELECT * FROM recetas WHERE id=?", (rid,)).fetchone())


def lista(con, firma: str | None = None, n: int = 50) -> list[dict]:
    filas = con.execute("SELECT * FROM recetas WHERE (:f IS NULL OR firma=:f) ORDER BY ultima_vez DESC LIMIT :n", {"f": firma, "n": n}).fetchall()
    return [_forma(f) for f in filas]


def para_prompt(con, firma: str) -> list[dict]:
    """Recetas de esta firma como datos para el modelo: acciones, parámetros y tasa de éxito. Nada de texto libre.

    Se revalidan contra el catálogo de hoy; las que ya no valen se omiten."""
    res = []
    for r in sorted(lista(con, firma), key=lambda r: (r["tasa_exito"] or 0, r["funciono"]), reverse=True):
        acciones = _acciones_validas(r["acciones"])
        if acciones is not None:
            res.append({"acciones": acciones, "veces_aplicada": r["aplicada"], "veces_funciono": r["funciono"], "veces_fallo": r["fallo"],
                        "tasa_exito": r["tasa_exito"]})
    return res[:MAX_PARA_PROMPT]


def es_madura(con, firma: str, acciones: list[dict], minimo: int = MADURA_DESDE) -> bool:
    """¿Estas acciones exactas tienen una receta con al menos `minimo` éxitos y más éxitos que fallos para esta firma?"""
    validas = _acciones_validas(acciones)
    if validas is None:
        return False
    f = con.execute("SELECT funciono, fallo FROM recetas WHERE firma=? AND clave=?", (firma, _clave(validas))).fetchone()
    return f is not None and f["funciono"] >= minimo and f["funciono"] > f["fallo"]

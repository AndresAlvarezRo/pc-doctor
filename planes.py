"""Planes de remediación: aprobar, rechazar, aplicar, deshacer y verificar. Es lo único que ejecuta lo que propone un diagnóstico.

Quién puede llamar a estas funciones (y solo ellos): los endpoints POST del dashboard (con token, Origin y Host) y las tools
`aprobar_plan` / `rechazar_plan` del MCP, que Claude Code usa únicamente cuando el usuario lo pide en la conversación. Nunca el
`claude -p` del diagnóstico ni el del reporte (están prohibidas por nombre en agente/reporte).

Aprobar un plan = aplicarlo: cada acción se vuelve a validar y a simular antes de correr (`remediacion.aplicar`), porque entre la
propuesta y la aprobación el equipo pudo cambiar. Después, el recolector verifica en las próximas corridas si la alerta se
resolvió y si se cumplió el efecto esperado de cada acción. El texto de los planes lo escribió un modelo y es no confiable: acá
solo se muestra, nunca se interpreta.
"""

import json

import alertas
import db
import diagnostico
import memoria
import recetas
import remediacion
from db import log

CORTE_DIAS = 7       # cuánto dura un corte por bucle antes de que esa firma pueda volver a aplicarse sola
VENTANA_INTENTOS_S = 86400
ESTADOS = ("propuesto", "aprobado", "rechazado", "aplicado", "verificado", "fallido", "escalado")
MAX_RESUMEN = 110


def _js(x) -> str:
    return json.dumps(x, ensure_ascii=False)


def _cargar(texto, vacio):
    try:
        return json.loads(texto) if texto else vacio
    except ValueError:
        return vacio


def _fila(con, plan_id):
    return con.execute("SELECT p.*, d.ref, d.firma, d.componente, d.disparador, d.alerta_clave, d.alerta_id, d.modo, d.hipotesis, d.evidencia, "
                       "d.confianza, d.sospechoso, d.motivo, d.estado AS estado_diagnostico, d.changelog_id, d.duracion_s, d.ts AS ts_diagnostico "
                       "FROM planes p JOIN diagnosticos d ON d.id = p.diagnostico_id WHERE p.id=?", (plan_id,)).fetchone()


def _forma(f, completo: bool) -> dict:
    """El plan como lo ven el dashboard y las tools. Con `completo=False` va sin el texto libre del modelo."""
    acciones = _cargar(f["acciones"], [])
    base = {"id": f["id"], "diagnostico_id": f["diagnostico_id"], "ts": f["ts_diagnostico"], "estado": f["estado"], "firma": f["firma"],
            "componente": f["componente"], "disparador": f["disparador"], "modo": f["modo"], "confianza": f["confianza"],
            "acciones": [a["accion"] for a in acciones] if not completo else acciones, "pasos_manuales_n": len(_cargar(f["pasos_manuales"], [])),
            "resultado": f["resultado"], "corridas": f["corridas"], "aprobado_en": f["aprobado_en"], "aplicado_en": f["aplicado_en"],
            "verificado_en": f["verificado_en"], "escalado_en": f["escalado_en"], "alerta_id": f["alerta_id"], "redactado": bool(f["redactado"])}
    if completo:
        base.update(hipotesis=f["hipotesis"], evidencia=_cargar(f["evidencia"], []), sospechoso=_cargar(f["sospechoso"], []),
                    pasos_manuales=_cargar(f["pasos_manuales"], []), como_verificar=f["verificar"], descartes=_cargar(f["descartes"], []),
                    motivo=f["motivo"], estado_diagnostico=f["estado_diagnostico"], duracion_s=f["duracion_s"], origen=f["origen"],
                    ejecuciones=_ejecuciones(f))
    return base


def _ejecuciones(f) -> list[dict]:
    ids = [i for i in _cargar(f["ejecuciones"], []) if type(i) is int]
    if not ids:
        return []
    con = db.conectar()
    try:
        filas = con.execute(f"SELECT id, accion, parametros, estado, resultado, deshacer IS NOT NULL AS reversible, deshecha_en FROM ejecuciones "
                            f"WHERE id IN ({','.join('?' * len(ids))}) ORDER BY id", ids).fetchall()
    finally:
        con.close()
    return [{"id": r["id"], "accion": r["accion"], "parametros": _cargar(r["parametros"], {}), "estado": r["estado"],
             "resumen": (_cargar(r["resultado"], {}) or {}).get("resumen"), "reversible": bool(r["reversible"]), "deshecha_en": r["deshecha_en"]} for r in filas]


def lista(con, estado: str = "", dias: int = 30, n: int = 50) -> list[dict]:
    """Planes recientes, del más nuevo al más viejo, sin el texto libre del modelo."""
    if estado and estado not in ESTADOS:
        raise ValueError(f"estado debe ser uno de: {', '.join(ESTADOS)}")
    filtro, args = ("AND p.estado=?", (estado,)) if estado else ("", ())
    filas = con.execute("SELECT p.id FROM planes p JOIN diagnosticos d ON d.id=p.diagnostico_id WHERE d.ts >= ? " + filtro + " ORDER BY p.id DESC LIMIT ?",
                        (db.ahora() - max(1, dias) * 86400, *args, n)).fetchall()
    return [_forma(_fila(con, r["id"]), False) for r in filas]


def detalle(con, plan_id: int) -> dict | None:
    f = _fila(con, plan_id)
    return _forma(f, True) if f else None


# ---------- aprobar, rechazar, deshacer ----------

def _transicion(con, plan_id: int, de: str, a: str, origen: str, extra: str = "") -> bool:
    """Cambia el estado solo si sigue siendo `de` (dos clics o dos llamadas a la vez no aplican dos veces)."""
    cur = con.execute(f"UPDATE planes SET estado=?, origen=?{extra} WHERE id=? AND estado=?", (a, origen, plan_id, de))
    con.commit()
    return cur.rowcount == 1


def aprobar(plan_id: int, origen: str) -> dict:
    """Aprueba y aplica un plan `propuesto`. Se detiene en la primera acción que falla (el plan queda `fallido` y se escala)."""
    con = db.conectar(escribir=True)
    try:
        f = _fila(con, plan_id)
        if f is None:
            return {"ok": False, "error": f"No existe el plan {plan_id}."}
        if f["estado"] != "propuesto":
            return {"ok": False, "error": f"El plan está «{f['estado']}»: solo se aprueba uno «propuesto»."}
        if diagnostico.configuracion()["nivel"] == 0:
            return {"ok": False, "error": "El nivel de autonomía es 0 (solo diagnóstico): no se aplica nada. Se cambia en config.json (remediacion.nivel)."}
        acciones = _cargar(f["acciones"], [])
        if not acciones:
            return {"ok": False, "error": "El plan no tiene acciones para aplicar (es solo diagnóstico). Los pasos manuales los hacés vos."}
        if not _transicion(con, plan_id, "propuesto", "aprobado", origen, ", aprobado_en=%d" % db.ahora()):
            return {"ok": False, "error": "El plan ya no está «propuesto»."}
        ids, hechas, ok = [], [], True
        for a in acciones:
            r = remediacion.aplicar(a.get("accion"), a.get("parametros"), simular=False, plan_id=plan_id)
            ids.append(r.get("ejecucion_id"))
            hechas.append({"accion": a.get("accion"), "ok": bool(r.get("ok")), "resumen": r.get("resumen")})
            if not r.get("ok"):
                ok = False
                break
        resultado = "aplicado; se verifica en las próximas corridas" if ok else f"falló al aplicar «{hechas[-1]['accion']}»: {hechas[-1]['resumen']}"
        con.execute("UPDATE planes SET estado=?, aplicado_en=?, ejecuciones=?, resultado=?, corridas=0 WHERE id=?",
                    ("aplicado" if ok else "fallido", db.ahora(), _js([i for i in ids if i]), resultado, plan_id))
        con.commit()
        if not ok:
            _escalar(con, plan_id)
        return {"ok": ok, "plan": plan_id, "estado": "aplicado" if ok else "fallido", "acciones": hechas, "resultado": resultado}
    finally:
        con.close()


def rechazar(plan_id: int, origen: str) -> dict:
    con = db.conectar(escribir=True)
    try:
        f = _fila(con, plan_id)
        if f is None:
            return {"ok": False, "error": f"No existe el plan {plan_id}."}
        if not _transicion(con, plan_id, "propuesto", "rechazado", origen, ", resultado='rechazado por el usuario'"):
            return {"ok": False, "error": f"El plan está «{f['estado']}»: solo se rechaza uno «propuesto»."}
        return {"ok": True, "plan": plan_id, "estado": "rechazado"}
    finally:
        con.close()


def deshacer(plan_id: int, origen: str) -> dict:
    """Deshace lo aplicado, en orden inverso. Lo irreversible (reiniciar un servicio, cerrar un proceso) no se toca y se informa."""
    con = db.conectar(escribir=True)
    try:
        f = _fila(con, plan_id)
        if f is None:
            return {"ok": False, "error": f"No existe el plan {plan_id}."}
        if f["estado"] not in ("aplicado", "verificado", "fallido", "escalado"):
            return {"ok": False, "error": f"El plan está «{f['estado']}»: no hay nada aplicado para deshacer."}
        ids = [i for i in _cargar(f["ejecuciones"], []) if type(i) is int]
        hechos, pendientes = [], []
        for i in reversed(ids):
            e = con.execute("SELECT accion, deshacer, deshecha_en, estado FROM ejecuciones WHERE id=?", (i,)).fetchone()
            if not e or e["estado"] != "aplicada" or e["deshecha_en"] is not None:
                continue
            if e["deshacer"] is None:
                pendientes.append(f"«{e['accion']}» no se puede deshacer")
                continue
            r = remediacion.deshacer(i)
            (hechos if r.get("ok") else pendientes).append(f"«{e['accion']}»: {r.get('resumen') or r.get('error')}")
        completo = all("no se puede deshacer" in p for p in pendientes)   # lo irreversible no impide dar el plan por deshecho
        if completo:
            con.execute("UPDATE planes SET estado='rechazado', origen=?, resultado=? WHERE id=?", (origen, "deshecho por el usuario", plan_id))
            con.commit()
        return {"ok": completo, "plan": plan_id, "deshecho": hechos, "pendiente": pendientes,
                "estado": "rechazado" if completo else f["estado"]}
    finally:
        con.close()


# ---------- verificación ----------

def _alerta_resuelta(con, f) -> bool:
    if f["ref"].startswith("hallazgo:"):
        h = con.execute("SELECT ultima_vez FROM hallazgos_seguridad WHERE huella=?", (f["ref"].split(":", 1)[1],)).fetchone()
        return h is None or h["ultima_vez"] <= f["aplicado_en"]       # no se lo volvió a ver después de aplicar
    a = con.execute("SELECT activa, resuelta_en FROM alertas_salud WHERE clave=?", (f["alerta_clave"],)).fetchone()
    return a is None or (a["activa"] == 0 and (a["resuelta_en"] or 0) >= f["aplicado_en"])


def verificar_pendientes(con) -> dict:
    """Paso del recolector: para cada plan `aplicado`, ¿se resolvió la alerta y se cumplió el efecto de cada acción?

    `verificado` si ambas cosas; `fallido` (y se escala) si pasaron `verificar_corridas` corridas sin lograrlo."""
    maximo = diagnostico.configuracion()["verificar_corridas"]
    res = {"verificados": [], "fallidos": [], "esperando": [], "cortados": []}
    for p in con.execute("SELECT id FROM planes WHERE estado='aplicado'").fetchall():
        con.execute("UPDATE planes SET corridas = corridas + 1 WHERE id=?", (p["id"],))
        con.commit()
        f = _fila(con, p["id"])
        nueva = _alerta_nueva_tras(con, f)
        if nueva:
            _cortar(con, p["id"], f"tras aplicar el plan apareció la alerta nueva `{diagnostico.limpiar(nueva, 80)}`")
            res["cortados"].append(p["id"])
            continue
        efectos = [remediacion.verificar_efecto(i) for i in _cargar(f["ejecuciones"], []) if type(i) is int]
        cumplidos = all(e["cumplido"] for e in efectos)
        resuelta = _alerta_resuelta(con, f)
        if resuelta and cumplidos:
            texto = "la alerta se resolvió y se cumplió el efecto esperado de cada acción"
            con.execute("UPDATE planes SET estado='verificado', verificado_en=?, resultado=? WHERE id=?", (db.ahora(), texto, p["id"]))
            con.commit()
            _cerrar_changelog(con, f, texto)
            _receta(con, p["id"], True)
            res["verificados"].append(p["id"])
        elif f["corridas"] >= maximo:
            motivo = ("la alerta sigue activa" if not resuelta else "") + ("; " if not resuelta and not cumplidos else "") + \
                     ("no se cumplió el efecto: " + "; ".join(e["detalle"] for e in efectos if not e["cumplido"]) if not cumplidos else "")
            texto = f"no funcionó tras {f['corridas']} corrida(s): {motivo}"
            con.execute("UPDATE planes SET estado='fallido', resultado=? WHERE id=?", (texto[:400], p["id"]))
            con.commit()
            _escalar(con, p["id"])
            _receta(con, p["id"], False)
            res["fallidos"].append(p["id"])
        else:
            res["esperando"].append(p["id"])
    return res


def _alerta_nueva_tras(con, f) -> str | None:
    """Clave de una alerta de otra cosa que empezó después de aplicar el plan. Es una coincidencia en el tiempo, no una prueba:
    por eso lo único que dispara es cortar lo automático y avisar, nunca una acción."""
    r = con.execute("SELECT clave FROM alertas_salud WHERE activa=1 AND desde>=? AND clave<>COALESCE(?, '') ORDER BY desde LIMIT 1",
                    (f["aplicado_en"], f["alerta_clave"])).fetchone()
    return r["clave"] if r else None


def corte_vigente(con, firma: str) -> dict | None:
    r = con.execute("SELECT * FROM cortes_auto WHERE firma=? AND ts>?", (firma, db.ahora() - CORTE_DIAS * 86400)).fetchone()
    return dict(r) if r else None


def _cortar(con, plan_id: int, motivo: str) -> None:
    """Bucle: una acción aplicada trajo otra alerta. Se corta todo lo automático de esa firma, el plan queda `escalado` y se avisa."""
    f = _fila(con, plan_id)
    con.execute("INSERT INTO cortes_auto (firma, ts, plan_id, motivo) VALUES (?,?,?,?) ON CONFLICT(firma) DO UPDATE SET ts=excluded.ts, "
                "plan_id=excluded.plan_id, motivo=excluded.motivo", (f["firma"], db.ahora(), plan_id, motivo))
    con.execute("UPDATE planes SET estado='escalado', resultado=? WHERE id=?", (f"posible bucle: {motivo}; se cortó lo automático para esta alerta", plan_id))
    con.commit()
    _escalar(con, plan_id)
    _receta(con, plan_id, False)


def autoaplicar(con, plan_id: int) -> dict:
    """Nivel 2: aplica sola la acción preaprobada de una receta madura. Devuelve {"aplicado": bool, "motivo": ...}.

    Condiciones (todas): nivel 2; todas las acciones están en `preaprobadas` (que solo edita el usuario) y son preaprobables en el
    catálogo; la receta exacta tiene ≥2 éxitos; sin corte por bucle; menos de `max_intentos_por_firma` aplicados en 24 h y al menos
    `espera_entre_intentos_min` desde el último. Si algo falla, el plan sigue `propuesto` para aprobación manual."""
    cfg = diagnostico.configuracion()
    f = _fila(con, plan_id)
    acciones = _cargar(f["acciones"], []) if f else []
    no = lambda m: {"aplicado": False, "motivo": m}
    if cfg["nivel"] != 2:
        return no("el nivel de autonomía no es 2")
    if f["estado"] != "propuesto" or not acciones:
        return no("el plan no está propuesto o no tiene acciones")
    for a in acciones:
        c = remediacion.CATALOGO.get(a.get("accion"))
        if c is None or not c.preaprobable or a["accion"] not in cfg["preaprobadas"]:
            return no(f"«{diagnostico.limpiar(a.get('accion'), 40)}» no está preaprobada")
    if not recetas.es_madura(con, f["firma"], acciones):
        return no("no hay una receta madura (2 éxitos o más) con estas acciones para esta alerta")
    if corte_vigente(con, f["firma"]):
        return no("hay un corte por bucle vigente para esta alerta")
    previos = con.execute("SELECT aplicado_en FROM planes p JOIN diagnosticos d ON d.id=p.diagnostico_id WHERE d.firma=? AND p.aplicado_en>? "
                          "ORDER BY p.aplicado_en DESC", (f["firma"], db.ahora() - VENTANA_INTENTOS_S)).fetchall()
    if len(previos) >= cfg["max_intentos_por_firma"]:
        return no(f"ya hubo {len(previos)} intento(s) en 24 h para esta alerta (máximo {cfg['max_intentos_por_firma']})")
    if previos and db.ahora() - previos[0]["aplicado_en"] < cfg["espera_entre_intentos_min"] * 60:
        return no(f"hay que esperar {cfg['espera_entre_intentos_min']} min entre intentos")
    r = aprobar(plan_id, "automatico")
    if not r["ok"] and r.get("estado") is None:
        return no(r.get("error", "no se pudo aprobar"))
    _avisar_automatico(con, plan_id, r)
    return {"aplicado": r["ok"], "motivo": r.get("resultado", ""), "resultado": r}


def _avisar_automatico(con, plan_id: int, r: dict) -> None:
    f = _fila(con, plan_id)
    try:
        if f and _notificaciones_activas():
            hechas = "; ".join(f"{a['accion']}: {'ok' if a['ok'] else 'falló'}" for a in r.get("acciones", []))
            alertas.notificar("pc-doctor: apliqué un plan solo" if r["ok"] else "pc-doctor: un plan automático falló",
                              f"Alerta: {diagnostico.limpiar(f['firma'], 80)}\n{hechas}\nSe verifica en las próximas corridas. Podés deshacerlo desde el plan.",
                              critica=not r["ok"], seccion=f"plan:{plan_id}")
    except Exception as e:
        log.warning("no pude avisar del plan automático: %s", e)


def _receta(con, plan_id: int, funciono: bool) -> None:
    try:
        recetas.registrar_resultado(con, plan_id, funciono)
    except Exception as e:   # aprender es un extra: no puede tirar la verificación
        log.warning("no pude actualizar la receta del plan #%s: %s", plan_id, e)


def _cerrar_changelog(con, f, texto: str) -> None:
    if f["changelog_id"]:
        try:
            memoria.resolver_changelog(con, f["changelog_id"], f"Plan #{f['id']} verificado: {texto}.")
        except Exception as e:   # el changelog no puede tirar la verificación
            log.warning("no pude cerrar la entrada del changelog: %s", e)


def _intentos(f) -> list[str]:
    """Lo que se intentó, con parámetros ya validados (nunca texto libre del modelo)."""
    res = []
    for e in _ejecuciones(f):
        params = ", ".join(f"{k}={v}" for k, v in (e["parametros"] or {}).items())
        res.append(f"{e['accion']}({params}): {'ok' if e['estado'] == 'aplicada' else e['estado']}" + (" [deshecha]" if e["deshecha_en"] else ""))
    return res


def _escalar(con, plan_id: int) -> None:
    """Avisa con todo lo intentado y deja una entrada abierta en el changelog. Solo una vez por plan."""
    f = _fila(con, plan_id)
    if f is None or f["escalado_en"]:
        return
    intentos = _intentos(f)
    try:
        memoria.registrar_changelog(
            con, "error", (f["componente"] or "pc")[:80],
            f"El plan #{plan_id} (diagnóstico #{f['diagnostico_id']}, alerta `{diagnostico.limpiar(f['firma'], 80)}`) no resolvió el problema. "
            f"Se intentó: {'; '.join(intentos) or 'nada'}. Resultado: {diagnostico.limpiar(f['resultado'], 300)}. Pide revisión manual.",
            "abierto", f"Plan #{plan_id} no resolvió la alerta")
    except Exception as e:
        log.warning("no pude registrar el escalado en el changelog: %s", e)
    try:
        if _notificaciones_activas():
            alertas.notificar(f"pc-doctor: el plan #{plan_id} no resolvió la alerta",
                              f"Se intentó: {'; '.join(intentos) or 'nada'}\nResultado: {diagnostico.limpiar(f['resultado'], MAX_RESUMEN)}",
                              critica=True, seccion=f"plan:{plan_id}")
    except Exception as e:
        log.warning("no pude enviar el aviso de escalado: %s", e)
    con.execute("UPDATE planes SET escalado_en=? WHERE id=?", (db.ahora(), plan_id))
    con.commit()


def _notificaciones_activas() -> bool:
    import reputacion
    return bool(reputacion.cargar_config(crear=False).get("notificaciones", True))


def avisar_plan(con, plan_id: int) -> bool:
    """Aviso de escritorio cuando hay un plan propuesto: la alerta (dato de este código), la hipótesis resumida y el botón «Ver el plan».
    No hay botón de aplicar: aprobar exige ver el plan completo en el dashboard."""
    f = _fila(con, plan_id)
    if f is None or not _notificaciones_activas():
        return False
    n = len(_cargar(f["acciones"], []))
    lineas = [f"Alerta: {diagnostico.limpiar(f['firma'], 80)}"]
    if f["modo"] == "modelo":
        lineas.append(f"Hipótesis (sin verificar): {diagnostico.limpiar(f['hipotesis'], MAX_RESUMEN)}")
    else:
        lineas.append("Plan sin redactar (sin modelo): solo la correlación")
    lineas.append(f"{n} acción(es) propuesta(s). Nada se aplica sin tu aprobación.")
    return alertas.notificar("pc-doctor: hay un plan para revisar", "\n".join(lineas), critica=False, seccion=f"plan:{plan_id}")

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
import remediacion
from db import log

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
    res = {"verificados": [], "fallidos": [], "esperando": []}
    for p in con.execute("SELECT id FROM planes WHERE estado='aplicado'").fetchall():
        con.execute("UPDATE planes SET corridas = corridas + 1 WHERE id=?", (p["id"],))
        con.commit()
        f = _fila(con, p["id"])
        efectos = [remediacion.verificar_efecto(i) for i in _cargar(f["ejecuciones"], []) if type(i) is int]
        cumplidos = all(e["cumplido"] for e in efectos)
        resuelta = _alerta_resuelta(con, f)
        if resuelta and cumplidos:
            texto = "la alerta se resolvió y se cumplió el efecto esperado de cada acción"
            con.execute("UPDATE planes SET estado='verificado', verificado_en=?, resultado=? WHERE id=?", (db.ahora(), texto, p["id"]))
            con.commit()
            _cerrar_changelog(con, f, texto)
            res["verificados"].append(p["id"])
        elif f["corridas"] >= maximo:
            motivo = ("la alerta sigue activa" if not resuelta else "") + ("; " if not resuelta and not cumplidos else "") + \
                     ("no se cumplió el efecto: " + "; ".join(e["detalle"] for e in efectos if not e["cumplido"]) if not cumplidos else "")
            texto = f"no funcionó tras {f['corridas']} corrida(s): {motivo}"
            con.execute("UPDATE planes SET estado='fallido', resultado=? WHERE id=?", (texto[:400], p["id"]))
            con.commit()
            _escalar(con, p["id"])
            res["fallidos"].append(p["id"])
        else:
            res["esperando"].append(p["id"])
    return res


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

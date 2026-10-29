"""Memoria de pc-doctor en tablas de doctor.db, consultable por el MCP.

Cuatro tablas:
- `memoria`: lo que el agente aprende en las sesiones (hechos, decisiones, preferencias, observaciones), con búsqueda de texto completo (FTS5).
- `hechos_conocidos`: lo que el USUARIO declara como sabido, para que el sistema no lo trate como novedad. Solo se escriben con su intervención.
- `bitacora`: las decisiones, errores, pruebas y limitaciones del proyecto.
- `changelog`: la historia de la PC (errores, soluciones, cambios y observaciones).

El esquema es aparte del de `db.ESQUEMA` a propósito: `db.conectar()` aplica `db.ESQUEMA` en cada corrida del recolector, y estas tablas
solo deben crearse cuando alguien ESCRIBE (las tools de escritura y la migración). Las lecturas nunca crean nada: si las tablas no
existen, devuelven vacío. Las funciones reciben la conexión y no la cierran.
"""

import json
import re
import sqlite3
from datetime import date

import db

TIPOS_MEMORIA = ("hecho", "decision", "preferencia", "observacion")
ORIGENES = ("agente", "usuario")
TIPOS_BITACORA = ("decision", "error", "prueba", "limitacion", "nota")
TIPOS_CHANGELOG = ("error", "solucion", "cambio", "observacion")
ESTADOS_CHANGELOG = ("abierto", "resuelto")

MAX_TEMA, MAX_TEXTO = 80, 4000
MAX_SECCION, MAX_TITULO, MAX_CONTENIDO = 200, 200, 60000
MAX_COMPONENTE, MAX_DETALLE = 80, 12000
MAX_APLICA_A = 200
RESUMEN = 280          # largo de los textos en las listas compactas
MAX_RESULTADOS = 20
MAX_PALABRAS = 8       # palabras de una búsqueda que se usan

ESQUEMA = """
CREATE TABLE IF NOT EXISTS memoria (
    id INTEGER PRIMARY KEY,
    creado INTEGER NOT NULL,        -- epoch UTC
    actualizado INTEGER NOT NULL,
    tema TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('hecho','decision','preferencia','observacion')),
    texto TEXT NOT NULL,
    origen TEXT NOT NULL CHECK (origen IN ('agente','usuario')),
    activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0,1))
);
CREATE INDEX IF NOT EXISTS idx_memoria_activo ON memoria(activo, actualizado);
CREATE VIRTUAL TABLE IF NOT EXISTS memoria_fts USING fts5(
    tema, texto, content='memoria', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS memoria_ai AFTER INSERT ON memoria BEGIN
    INSERT INTO memoria_fts(rowid, tema, texto) VALUES (new.id, new.tema, new.texto);
END;
CREATE TRIGGER IF NOT EXISTS memoria_ad AFTER DELETE ON memoria BEGIN
    INSERT INTO memoria_fts(memoria_fts, rowid, tema, texto) VALUES ('delete', old.id, old.tema, old.texto);
END;
CREATE TRIGGER IF NOT EXISTS memoria_au AFTER UPDATE ON memoria BEGIN
    INSERT INTO memoria_fts(memoria_fts, rowid, tema, texto) VALUES ('delete', old.id, old.tema, old.texto);
    INSERT INTO memoria_fts(rowid, tema, texto) VALUES (new.id, new.tema, new.texto);
END;

CREATE TABLE IF NOT EXISTS hechos_conocidos (
    id INTEGER PRIMARY KEY,
    creado INTEGER NOT NULL,
    texto TEXT NOT NULL,
    aplica_a TEXT,                  -- sensor, huella de alerta o hallazgo, disco o proceso (opcional)
    vence TEXT,                     -- AAAA-MM-DD: fecha de revisión (opcional)
    activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0,1))
);
CREATE INDEX IF NOT EXISTS idx_hechos_activo ON hechos_conocidos(activo, aplica_a);
CREATE TABLE IF NOT EXISTS hechos_referencia (
    hecho_id INTEGER NOT NULL,      -- con qué estado quedó silenciada una alerta: si empeora, vuelve a avisar
    clave TEXT NOT NULL,
    severidad TEXT NOT NULL,
    valor REAL,
    desde INTEGER NOT NULL,
    PRIMARY KEY (hecho_id, clave)
);

CREATE TABLE IF NOT EXISTS bitacora (
    id INTEGER PRIMARY KEY,
    fecha TEXT NOT NULL,            -- AAAA-MM-DD
    seccion TEXT NOT NULL,          -- por ejemplo "Nivel nuevo 2: correlación"
    tipo TEXT NOT NULL CHECK (tipo IN ('decision','error','prueba','limitacion','nota')),
    titulo TEXT NOT NULL,
    contenido TEXT NOT NULL         -- markdown
);
CREATE INDEX IF NOT EXISTS idx_bitacora_fecha ON bitacora(fecha, id);
CREATE VIRTUAL TABLE IF NOT EXISTS bitacora_fts USING fts5(
    seccion, titulo, contenido, content='bitacora', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS bitacora_ai AFTER INSERT ON bitacora BEGIN
    INSERT INTO bitacora_fts(rowid, seccion, titulo, contenido) VALUES (new.id, new.seccion, new.titulo, new.contenido);
END;
CREATE TRIGGER IF NOT EXISTS bitacora_ad AFTER DELETE ON bitacora BEGIN
    INSERT INTO bitacora_fts(bitacora_fts, rowid, seccion, titulo, contenido) VALUES ('delete', old.id, old.seccion, old.titulo, old.contenido);
END;
CREATE TRIGGER IF NOT EXISTS bitacora_au AFTER UPDATE ON bitacora BEGIN
    INSERT INTO bitacora_fts(bitacora_fts, rowid, seccion, titulo, contenido) VALUES ('delete', old.id, old.seccion, old.titulo, old.contenido);
    INSERT INTO bitacora_fts(rowid, seccion, titulo, contenido) VALUES (new.id, new.seccion, new.titulo, new.contenido);
END;

CREATE TABLE IF NOT EXISTS changelog (
    id INTEGER PRIMARY KEY,
    fecha TEXT NOT NULL,            -- AAAA-MM-DD
    tipo TEXT NOT NULL CHECK (tipo IN ('error','solucion','cambio','observacion')),
    componente TEXT NOT NULL,       -- cpu, gpu, disco sdb, ventilador fan7, kernel...
    titulo TEXT,                    -- opcional: el título corto que tenían las entradas del archivo
    detalle TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'abierto' CHECK (estado IN ('abierto','resuelto')),
    resuelto_en TEXT                -- AAAA-MM-DD
);
CREATE INDEX IF NOT EXISTS idx_changelog_estado ON changelog(estado, fecha);
"""


# ---------- base ----------

def asegurar(con) -> None:
    """Crea las tablas de memoria si no existen. Solo lo llaman las operaciones de escritura y la migración."""
    con.executescript(ESQUEMA)


def existe(con, tabla: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE name=? AND type IN ('table','view')", (tabla,)).fetchone() is not None


def hoy() -> str:
    return date.today().isoformat()


def _texto(valor, campo: str, maximo: int, obligatorio: bool = True) -> str:
    v = (valor or "").strip() if isinstance(valor, str) or valor is None else str(valor).strip()
    if obligatorio and not v:
        raise ValueError(f"`{campo}` no puede estar vacío.")
    if len(v) > maximo:
        raise ValueError(f"`{campo}` es demasiado largo ({len(v)} caracteres; el máximo es {maximo}).")
    return v


def _opcion(valor: str, opciones: tuple, campo: str) -> str:
    v = (valor or "").strip().lower()
    if v not in opciones:
        raise ValueError(f"`{campo}` debe ser uno de: {', '.join(opciones)}.")
    return v


def _fecha(valor: str, campo: str) -> str:
    v = (valor or "").strip()
    try:
        return date.fromisoformat(v).isoformat()
    except ValueError:
        raise ValueError(f"`{campo}` debe tener el formato AAAA-MM-DD.") from None


def corto(texto: str | None, largo: int = RESUMEN) -> str:
    t = " ".join((texto or "").split())
    return t if len(t) <= largo else t[: largo - 1] + "…"


def _auditar(con, tool: str, parametros: dict, resultado: str) -> None:
    """Deja constancia en `acciones` de quién cambió qué (los hechos conocidos silencian alertas, así que se registran)."""
    con.execute("INSERT INTO acciones (ts, tool, parametros, resultado) VALUES (?,?,?,?)",
                (db.ahora(), tool, json.dumps(parametros, ensure_ascii=False), resultado[:500]))


# ---------- búsqueda de texto completo ----------

def consulta_fts(texto: str, modo: str = "y") -> str | None:
    """Arma una consulta FTS5 segura a partir de texto libre: solo palabras, cada una como prefijo.

    Se ignora la sintaxis de FTS5 que escriba el usuario (comillas, AND, NEAR, *, -), que daría errores o resultados raros.
    `modo` "y" exige todas las palabras; "o" alcanza con alguna.
    """
    palabras = [p for p in re.findall(r"\w+", (texto or "").lower()) if len(p) >= 2 or p.isdigit()][:MAX_PALABRAS]
    if not palabras:
        return None
    return (" OR " if modo == "o" else " ").join(f'"{p}"*' for p in palabras)


def _buscar(con, tabla: str, fts: str, columnas: str, pesos: str, filtro: str, consulta: str, n: int) -> list:
    """Busca primero con todas las palabras y, si no hay nada, con cualquiera de ellas. Ordena por relevancia (bm25)."""
    for modo in ("y", "o"):
        q = consulta_fts(consulta, modo)
        if q is None:
            return []
        filas = con.execute(
            f"SELECT {columnas} FROM {tabla} t JOIN {fts} ON {fts}.rowid = t.id WHERE {fts} MATCH ? {filtro} "
            f"ORDER BY bm25({fts}, {pesos}) LIMIT ?", (q, n)).fetchall()
        if filas:
            return filas
    return []


# ---------- memoria ----------

def _fila_memoria(f) -> dict:
    return {"id": f["id"], "tema": f["tema"], "tipo": f["tipo"], "origen": f["origen"], "texto": corto(f["texto"]),
            "actualizado": db.iso(f["actualizado"])}


def recordar(con, tema: str, texto: str, tipo: str = "hecho", origen: str = "agente") -> dict:
    tema, texto = _texto(tema, "tema", MAX_TEMA), _texto(texto, "texto", MAX_TEXTO)
    tipo, origen = _opcion(tipo, TIPOS_MEMORIA, "tipo"), _opcion(origen, ORIGENES, "origen")
    asegurar(con)
    igual = con.execute("SELECT id FROM memoria WHERE activo=1 AND lower(tema)=lower(?) AND texto=?", (tema, texto)).fetchone()
    if igual:
        return {"id": igual["id"], "mensaje": "Ya estaba guardado (no se duplicó)."}
    ahora = db.ahora()
    cur = con.execute("INSERT INTO memoria (creado, actualizado, tema, tipo, texto, origen) VALUES (?,?,?,?,?,?)", (ahora, ahora, tema, tipo, texto, origen))
    con.commit()
    return {"id": cur.lastrowid, "mensaje": "Guardado."}


def buscar_memoria(con, consulta: str, n: int = 5) -> dict:
    n = max(1, min(int(n), MAX_RESULTADOS))
    if not existe(con, "memoria"):
        return {"total": 0, "resultados": [], "nota": "La memoria todavía no tiene datos."}
    if consulta_fts(consulta) is None:
        return {"error": "Escribí al menos una palabra para buscar."}
    filas = _buscar(con, "memoria", "memoria_fts", "t.*", "5.0, 1.0", "AND t.activo = 1", consulta, n)
    return {"total": len(filas), "resultados": [_fila_memoria(f) for f in filas]}


def olvidar(con, ident: int) -> dict:
    if not existe(con, "memoria"):
        return {"error": f"No existe el recuerdo {ident}."}
    f = con.execute("SELECT activo FROM memoria WHERE id=?", (ident,)).fetchone()
    if not f:
        return {"error": f"No existe el recuerdo {ident}."}
    if not f["activo"]:
        return {"mensaje": "Ya estaba olvidado."}
    con.execute("UPDATE memoria SET activo=0, actualizado=? WHERE id=?", (db.ahora(), ident))
    con.commit()
    return {"mensaje": "Olvidado (queda guardado como inactivo; no se borra)."}


def memoria_reciente(con, n: int = 10) -> dict:
    n = max(1, min(int(n), MAX_RESULTADOS))
    if not existe(con, "memoria"):
        return {"total": 0, "resultados": [], "nota": "La memoria todavía no tiene datos."}
    filas = con.execute("SELECT * FROM memoria WHERE activo=1 ORDER BY actualizado DESC, id DESC LIMIT ?", (n,)).fetchall()
    return {"total": len(filas), "resultados": [_fila_memoria(f) for f in filas]}


# ---------- hechos conocidos ----------

def aplica(aplica_a: str | None, referencia: str) -> bool:
    """¿Un hecho con `aplica_a` se refiere a `referencia`? Igual, o sus segmentos aparecen seguidos dentro de la referencia.

    Los segmentos se separan por ':' y '/'. Ejemplos: el hecho 'sdb' aplica a 'smart_pendientes:sdb/sectores_pendientes' y a
    'sdb/errores_crc'; el hecho 'sdb/errores_crc' aplica a 'smart_crc:sdb/errores_crc' pero no a 'sdb/sectores_pendientes'.
    """
    if not aplica_a or not referencia:
        return False
    a, r = aplica_a.strip().lower(), referencia.strip().lower()
    if a == r:
        return True
    sa, sr = [s for s in re.split(r"[:/]", a) if s], [s for s in re.split(r"[:/]", r) if s]
    return bool(sa) and any(sr[i:i + len(sa)] == sa for i in range(len(sr) - len(sa) + 1))


def _fila_hecho(f) -> dict:
    return {"id": f["id"], "texto": corto(f["texto"], 400), "aplica_a": f["aplica_a"], "vence": f["vence"], "creado": db.iso(f["creado"])[:10]}


def hechos_activos(con) -> list:
    """Hechos activos y vigentes (los vencidos no cuentan: dejan de silenciar). Lo usan las alertas y el reporte."""
    if not existe(con, "hechos_conocidos"):
        return []
    return con.execute("SELECT * FROM hechos_conocidos WHERE activo=1 AND (vence IS NULL OR vence >= ?) ORDER BY id", (hoy(),)).fetchall()


def hechos_para_revisar(con) -> list:
    """Hechos activos cuya fecha de revisión ya pasó."""
    if not existe(con, "hechos_conocidos"):
        return []
    return con.execute("SELECT * FROM hechos_conocidos WHERE activo=1 AND vence IS NOT NULL AND vence < ? ORDER BY vence, id", (hoy(),)).fetchall()


def hechos_conocidos(con, aplica_a: str | None = None) -> dict:
    activos, revisar = hechos_activos(con), hechos_para_revisar(con)
    if aplica_a:
        activos = [h for h in activos if aplica(h["aplica_a"], aplica_a)]
        revisar = [h for h in revisar if aplica(h["aplica_a"], aplica_a)]
    res = {"activos": [_fila_hecho(h) for h in activos], "para_revisar": [_fila_hecho(h) for h in revisar]}
    if not existe(con, "hechos_conocidos"):
        res["nota"] = "Todavía no hay hechos conocidos declarados."
    return res


def agregar_hecho_conocido(con, texto: str, aplica_a: str = "", vence: str = "") -> dict:
    texto = _texto(texto, "texto", MAX_TEXTO)
    aplica_a = _texto(aplica_a, "aplica_a", MAX_APLICA_A, obligatorio=False) or None
    vence = _fecha(vence, "vence") if (vence or "").strip() else None
    if vence and vence < hoy():
        raise ValueError("`vence` no puede ser una fecha pasada.")
    asegurar(con)
    cur = con.execute("INSERT INTO hechos_conocidos (creado, texto, aplica_a, vence) VALUES (?,?,?,?)", (db.ahora(), texto, aplica_a, vence))
    _auditar(con, "agregar_hecho_conocido", {"id": cur.lastrowid, "aplica_a": aplica_a, "vence": vence, "texto": texto[:200]}, "agregado")
    con.commit()
    return {"id": cur.lastrowid, "mensaje": "Hecho conocido agregado."}


def retirar_hecho_conocido(con, ident: int) -> dict:
    if not existe(con, "hechos_conocidos"):
        return {"error": f"No existe el hecho conocido {ident}."}
    f = con.execute("SELECT activo FROM hechos_conocidos WHERE id=?", (ident,)).fetchone()
    if not f:
        return {"error": f"No existe el hecho conocido {ident}."}
    if not f["activo"]:
        return {"mensaje": "Ya estaba retirado."}
    con.execute("UPDATE hechos_conocidos SET activo=0 WHERE id=?", (ident,))
    _auditar(con, "retirar_hecho_conocido", {"id": ident}, "retirado")
    con.commit()
    return {"mensaje": "Hecho conocido retirado (queda guardado como inactivo; no se borra)."}


# ---------- efecto de los hechos conocidos en las alertas ----------

RANGO_SEVERIDAD = {"aviso": 1, "critico": 2}
TOLERANCIA_REL = 0.05   # cuánto puede moverse un valor (de una alerta que no es de contadores) sin contar como empeoramiento


def hecho_de(hechos: list, cond: dict):
    """El primer hecho vigente cuyo `aplica_a` se refiere a la clave o al nombre del sensor de la alerta; None si ninguno."""
    for h in hechos:
        if aplica(h["aplica_a"], cond["clave"]) or aplica(h["aplica_a"], cond.get("nombre") or ""):
            return h
    return None


def empeoro(cond: dict, ref) -> bool:
    """¿La alerta está peor que cuando quedó silenciada? Sube la severidad o el valor se aleja de lo normal.

    Los contadores de SMART (`smart_*`) cuentan cualquier aumento (un sector defectuoso más ya es una novedad); el resto, un
    cambio de más del 5 %. Los eventos del journal solo empeoran si escala la severidad. `dir` "min" = peor cuanto más bajo.
    """
    if RANGO_SEVERIDAD.get(cond["severidad"], 0) > RANGO_SEVERIDAD.get(ref["severidad"], 0):
        return True
    if cond.get("evento") or ref["valor"] is None or cond.get("valor") is None:
        return False
    delta = (ref["valor"] - cond["valor"]) if cond.get("dir") == "min" else (cond["valor"] - ref["valor"])
    tolerancia = 0 if cond["clave"].startswith("smart_") else TOLERANCIA_REL * abs(ref["valor"])
    return delta > tolerancia


def filtrar_avisos(con, a_avisar: list[dict], conds: dict[str, dict], ahora: int) -> list[dict]:
    """Aplica los hechos conocidos a los avisos. Lo cubierto por un hecho y sin cambios se silencia (aunque tocara avisar o
    recordar); lo que empeoró desde que se silenció se avisa, aclarando que había un hecho conocido; lo no cubierto sigue igual.

    Se mira TODA condición vigente (`conds`) y no solo las que tocaba avisar: un empeoramiento puede ocurrir en medio de la
    ventana de repetición. Sin hechos activos (o sin las tablas) devuelve la lista tal cual y no toca la base."""
    hechos = hechos_activos(con)
    if not hechos:
        return a_avisar
    asegurar(con)       # solo hay hechos si alguien los declaró: la tabla de referencias se crea ahora si faltaba
    res = [c for c in a_avisar if hecho_de(hechos, c) is None]
    for c in conds.values():
        h = hecho_de(hechos, c)
        if h is None:
            continue
        ref = con.execute("SELECT * FROM hechos_referencia WHERE hecho_id=? AND clave=?", (h["id"], c["clave"])).fetchone()
        if ref is not None and not empeoro(c, ref):
            continue                                    # conocido y sin cambios: se silencia
        if ref is not None:                             # empeoró: se avisa, diciendo que había un hecho conocido
            antes = ref["severidad"] if c.get("evento") or ref["valor"] is None else f"{ref['valor']:g}"   # en un evento el valor es su hora
            res.append({**c, "mensaje": f"{c['mensaje']} [hecho conocido #{h['id']}: empeoró (antes {antes})]", "hecho_id": h["id"]})
        # primera vez bajo el hecho (se silencia) o empeoramiento (se avisa): en ambos casos se anota el estado de referencia
        con.execute("INSERT OR REPLACE INTO hechos_referencia (hecho_id, clave, severidad, valor, desde) VALUES (?,?,?,?,?)",
                    (h["id"], c["clave"], c["severidad"], c.get("valor"), ahora))
    return res


def olvidar_referencias(con, claves: list[str]) -> None:
    """Cuando una alerta se resuelve, la próxima vez que aparezca cuenta como primera vez bajo el hecho."""
    if claves and existe(con, "hechos_referencia"):
        con.executemany("DELETE FROM hechos_referencia WHERE clave=?", [(k,) for k in claves])


def empeorada(con, alerta: dict) -> bool:
    """Una alerta que tiene hecho conocido: ¿está peor que cuando se silenció? Sin referencia anotada, no (todavía no se silenció)."""
    h = alerta.get("hecho_conocido")
    if not h or not existe(con, "hechos_referencia"):
        return False
    ref = con.execute("SELECT * FROM hechos_referencia WHERE hecho_id=? AND clave=?", (h["id"], alerta["clave"])).fetchone()
    return ref is not None and empeoro({**alerta, "evento": alerta["clave"].startswith("evento:")}, ref)


def compacto(h) -> dict | None:
    """El hecho conocido en forma breve, para mostrarlo junto a una alerta."""
    return None if h is None else {"id": h["id"], "texto": corto(h["texto"], 300), "aplica_a": h["aplica_a"], "vence": h["vence"]}


# ---------- bitácora ----------

def registrar_bitacora(con, seccion: str, tipo: str, titulo: str, contenido: str, fecha: str = "") -> dict:
    seccion, titulo = _texto(seccion, "seccion", MAX_SECCION), _texto(titulo, "titulo", MAX_TITULO)
    contenido = _texto(contenido, "contenido", MAX_CONTENIDO)
    tipo = _opcion(tipo, TIPOS_BITACORA, "tipo")
    fecha = _fecha(fecha, "fecha") if (fecha or "").strip() else hoy()
    asegurar(con)
    cur = con.execute("INSERT INTO bitacora (fecha, seccion, tipo, titulo, contenido) VALUES (?,?,?,?,?)", (fecha, seccion, tipo, titulo, contenido))
    con.commit()
    return {"id": cur.lastrowid, "mensaje": "Registrado en la bitácora."}


def buscar_bitacora(con, consulta: str, n: int = 5, completo: bool = False) -> dict:
    n = max(1, min(int(n), MAX_RESULTADOS))
    if not existe(con, "bitacora"):
        return {"total": 0, "resultados": [], "nota": "La bitácora todavía no tiene entradas en la base."}
    if consulta_fts(consulta) is None:
        return {"error": "Escribí al menos una palabra para buscar."}
    filas = _buscar(con, "bitacora", "bitacora_fts", "t.*", "3.0, 5.0, 1.0", "", consulta, n)
    return {"total": len(filas), "resultados": [
        {"id": f["id"], "fecha": f["fecha"], "seccion": f["seccion"], "tipo": f["tipo"], "titulo": f["titulo"],
         "contenido": f["contenido"] if completo else corto(f["contenido"], 400)} for f in filas]}


# ---------- changelog ----------

def _fila_changelog(f) -> dict:
    return {"id": f["id"], "fecha": f["fecha"], "tipo": f["tipo"], "componente": f["componente"], "titulo": f["titulo"],
            "detalle": corto(f["detalle"], 400), "estado": f["estado"], "resuelto_en": f["resuelto_en"]}


def registrar_changelog(con, tipo: str, componente: str, detalle: str, estado: str = "abierto", titulo: str = "", fecha: str = "") -> dict:
    tipo, estado = _opcion(tipo, TIPOS_CHANGELOG, "tipo"), _opcion(estado, ESTADOS_CHANGELOG, "estado")
    componente = _texto(componente, "componente", MAX_COMPONENTE)
    detalle = _texto(detalle, "detalle", MAX_DETALLE)
    titulo = _texto(titulo, "titulo", MAX_TITULO, obligatorio=False) or None
    fecha = _fecha(fecha, "fecha") if (fecha or "").strip() else hoy()
    asegurar(con)
    cur = con.execute("INSERT INTO changelog (fecha, tipo, componente, titulo, detalle, estado, resuelto_en) VALUES (?,?,?,?,?,?,?)",
                      (fecha, tipo, componente, titulo, detalle, estado, fecha if estado == "resuelto" else None))
    con.commit()
    return {"id": cur.lastrowid, "mensaje": "Registrado en el changelog."}


def resolver_changelog(con, ident: int, detalle: str = "") -> dict:
    if not existe(con, "changelog"):
        return {"error": f"No existe la entrada {ident} del changelog."}
    f = con.execute("SELECT * FROM changelog WHERE id=?", (ident,)).fetchone()
    if not f:
        return {"error": f"No existe la entrada {ident} del changelog."}
    if f["estado"] == "resuelto":
        return {"error": f"La entrada {ident} ya estaba resuelta el {f['resuelto_en']}."}
    extra = _texto(detalle, "detalle", MAX_DETALLE, obligatorio=False)
    nuevo = f["detalle"] + (f"\n\n**Resuelto el {hoy()}:** {extra}" if extra else "")
    if len(nuevo) > MAX_DETALLE * 2:
        raise ValueError("Con ese detalle la entrada quedaría demasiado larga.")
    con.execute("UPDATE changelog SET estado='resuelto', resuelto_en=?, detalle=? WHERE id=?", (hoy(), nuevo, ident))
    con.commit()
    return {"mensaje": f"Entrada {ident} resuelta."}


def changelog_abierto(con, n: int = 30) -> dict:
    n = max(1, min(int(n), 50))
    if not existe(con, "changelog"):
        return {"total": 0, "abiertos": [], "nota": "El changelog todavía no tiene entradas en la base."}
    total = con.execute("SELECT COUNT(*) FROM changelog WHERE estado='abierto'").fetchone()[0]
    filas = con.execute("SELECT * FROM changelog WHERE estado='abierto' ORDER BY fecha DESC, id DESC LIMIT ?", (n,)).fetchall()
    return {"total": total, "abiertos": [_fila_changelog(f) for f in filas]}

"""Memoria de pc-doctor en tablas de doctor.db, consultable por el MCP.

Estas tablas:
- `memoria`: lo que el agente aprende en las sesiones (hechos, decisiones, preferencias, observaciones), con búsqueda de texto completo (FTS5).
- `hechos_conocidos`: lo que el USUARIO declara como sabido, para que el sistema no lo trate como novedad. Solo se escriben con su intervención.
- `bitacora`: las decisiones, errores, pruebas y limitaciones del proyecto, agrupadas por sección; su contenido son los ítems de `bitacora_items`
  (tipo, vigencia, módulos, archivos y un resumen de una línea), que es lo que se busca y se entrega por tarea (ver `modulos.py`).
- `changelog`: la historia de la PC (errores, soluciones, cambios y observaciones).

El esquema es aparte del de `db.ESQUEMA` a propósito: `db.conectar()` aplica `db.ESQUEMA` en cada corrida del recolector, y estas tablas
solo deben crearse cuando alguien ESCRIBE (las tools de escritura y la migración). Las lecturas nunca crean nada: si las tablas no
existen, devuelven vacío. Las funciones reciben la conexión y no la cierran.
"""

import json
import re
import socket
import sqlite3
import sys
from datetime import date
from pathlib import Path

import db
import modulos as mapa      # el parámetro `modulos` de las funciones taparía al módulo

TIPOS_MEMORIA = ("hecho", "decision", "preferencia", "observacion")
ORIGENES = ("agente", "usuario")
TIPOS_BITACORA = ("decision", "error", "prueba", "limitacion", "nota")      # los de la entrada (agrupación)
TIPOS_ITEM = ("invariante", "decision", "error", "limitacion", "prueba", "pendiente", "nota")
ORDEN_TIPOS = ("invariante", "pendiente", "limitacion", "decision", "error", "prueba", "nota")     # qué se muestra primero en `contexto`
VIGENCIAS = ("vigente", "superada", "historica")
TIPO_DE_ENTRADA = {"invariante": "decision", "pendiente": "nota"}           # los tipos de ítem que la entrada no tiene
TIPOS_CHANGELOG = ("error", "solucion", "cambio", "observacion")
ESTADOS_CHANGELOG = ("abierto", "resuelto")

MAX_TEMA, MAX_TEXTO = 80, 4000
MAX_SECCION, MAX_TITULO, MAX_CONTENIDO = 200, 200, 60000
MAX_RESUMEN, MAX_PRUEBA, MAX_MOTIVO, MAX_ARCHIVO = 120, 200, 300, 300
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

CREATE TABLE IF NOT EXISTS identidad_manual (
    campo TEXT PRIMARY KEY,         -- Energía, Red expuesta, Sensores extra, Node.js...: identidad de la PC que no se puede recalcular
    valor TEXT NOT NULL,            -- se exporta a "Identidad actual" del CHANGELOG.md (no es un dato personal)
    actualizado INTEGER NOT NULL
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

-- Ítems atómicos de la bitácora: `bitacora` queda como agrupación (sección y título) y cada ítem es un bullet de primer nivel
-- con sus subbullets, o un párrafo. Sobre los ítems se busca y se arma el contexto de cada tarea.
CREATE TABLE IF NOT EXISTS bitacora_items (
    id INTEGER PRIMARY KEY,
    entrada_id INTEGER NOT NULL REFERENCES bitacora(id),
    orden INTEGER NOT NULL,         -- posición dentro de la entrada: es el orden en que se exporta
    fecha TEXT NOT NULL,            -- AAAA-MM-DD
    tipo TEXT NOT NULL CHECK (tipo IN ('invariante','decision','error','limitacion','prueba','pendiente','nota')),
    vigencia TEXT NOT NULL DEFAULT 'vigente' CHECK (vigencia IN ('vigente','superada','historica')),
    reemplazada_por INTEGER REFERENCES bitacora_items(id) CHECK (reemplazada_por IS NULL OR reemplazada_por <> id),
    motivo TEXT,
    resumen TEXT NOT NULL,          -- una línea, hasta 120 caracteres
    contenido TEXT NOT NULL,        -- el texto original, tal cual (markdown)
    prueba TEXT                     -- nombre del test que protege el ítem (sobre todo en las invariantes)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bitacora_items_orden ON bitacora_items(entrada_id, orden);
CREATE INDEX IF NOT EXISTS idx_bitacora_items_tipo ON bitacora_items(vigencia, tipo, fecha);
CREATE TABLE IF NOT EXISTS bitacora_item_modulo (
    item_id INTEGER NOT NULL REFERENCES bitacora_items(id),
    modulo TEXT NOT NULL,
    PRIMARY KEY (item_id, modulo)
);
CREATE INDEX IF NOT EXISTS idx_bitacora_item_modulo ON bitacora_item_modulo(modulo, item_id);
CREATE TABLE IF NOT EXISTS bitacora_item_archivo (
    item_id INTEGER NOT NULL REFERENCES bitacora_items(id),
    ruta TEXT NOT NULL,
    PRIMARY KEY (item_id, ruta)
);
CREATE INDEX IF NOT EXISTS idx_bitacora_item_archivo ON bitacora_item_archivo(ruta);
CREATE VIRTUAL TABLE IF NOT EXISTS bitacora_items_fts USING fts5(
    resumen, contenido, content='bitacora_items', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS bitacora_items_ai AFTER INSERT ON bitacora_items BEGIN
    INSERT INTO bitacora_items_fts(rowid, resumen, contenido) VALUES (new.id, new.resumen, new.contenido);
END;
CREATE TRIGGER IF NOT EXISTS bitacora_items_ad AFTER DELETE ON bitacora_items BEGIN
    INSERT INTO bitacora_items_fts(bitacora_items_fts, rowid, resumen, contenido) VALUES ('delete', old.id, old.resumen, old.contenido);
END;
CREATE TRIGGER IF NOT EXISTS bitacora_items_au AFTER UPDATE ON bitacora_items BEGIN
    INSERT INTO bitacora_items_fts(bitacora_items_fts, rowid, resumen, contenido) VALUES ('delete', old.id, old.resumen, old.contenido);
    INSERT INTO bitacora_items_fts(rowid, resumen, contenido) VALUES (new.id, new.resumen, new.contenido);
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


# ---------- identidad declarada a mano ----------

MAX_CAMPO_IDENTIDAD, MAX_VALOR_IDENTIDAD = 60, 1500
CAMPOS_CALCULADOS = {"hostname", "so", "kernel", "cpu", "gpu", "ram", "discos", "placa madre", "paquetes", "snapshot"}


def registrar_identidad(con, campo: str, valor: str) -> dict:
    """Crea o actualiza una fila de "Identidad actual" que no se puede calcular (energía, red expuesta, sensores extra, Node.js...)."""
    campo, valor = _texto(campo, "campo", MAX_CAMPO_IDENTIDAD), _texto(valor, "valor", MAX_VALOR_IDENTIDAD)
    if campo.lower().strip("_ ") in CAMPOS_CALCULADOS:
        raise ValueError(f"`{campo}` se calcula solo desde el snapshot de entorno; no se declara a mano.")
    asegurar(con)
    antes = con.execute("SELECT 1 FROM identidad_manual WHERE lower(campo)=lower(?)", (campo,)).fetchone()
    if antes:
        con.execute("DELETE FROM identidad_manual WHERE lower(campo)=lower(?)", (campo,))
    con.execute("INSERT INTO identidad_manual (campo, valor, actualizado) VALUES (?,?,?)", (campo, valor, db.ahora()))
    con.commit()
    return {"mensaje": f"Identidad actualizada: {campo}." if antes else f"Identidad agregada: {campo}."}


def identidad_declarada(con) -> list:
    """Filas declaradas a mano, en el orden en que se agregaron (vacío si la tabla no existe)."""
    if not existe(con, "identidad_manual"):
        return []
    return con.execute("SELECT * FROM identidad_manual ORDER BY rowid").fetchall()


# ---------- bitácora ----------
# `bitacora` agrupa (sección y título); lo que se busca, se filtra y se entrega al agente son los ítems de `bitacora_items`.

MAX_CONTEXTO = 50


def _lista(valor, campo: str, maximo: int) -> list[str]:
    """Lista de textos desde una lista o desde un texto separado por comas o saltos de línea; sin vacíos ni repetidos."""
    partes = re.split(r"[,\n]", valor) if isinstance(valor, str) else [str(p) for p in (valor or [])]
    out: list[str] = []
    for p in (x.strip() for x in partes):
        if len(p) > maximo:
            raise ValueError(f"En `{campo}`, un valor es demasiado largo ({len(p)} caracteres; el máximo es {maximo}).")
        if p and p not in out:
            out.append(p)
    return out


def _modulo(valor: str) -> str:
    v = (valor or "").strip().lower()
    if v not in mapa.MODULOS:
        raise ValueError(f"Módulo desconocido: `{valor}`. Los válidos son: {', '.join(mapa.MODULOS)}.")
    return v


def _sin_encabezados(contenido: str) -> str:
    """Un ítem es una viñeta o un párrafo: un encabezado suelto (`## x`) partiría la bitácora exportada al volver a importarla."""
    en_codigo = False
    for linea in contenido.split("\n"):
        if linea.lstrip().startswith("```"):
            en_codigo = not en_codigo
        elif not en_codigo and RX_ENCABEZADO_MD.match(linea):
            raise ValueError("`contenido` no puede tener encabezados (líneas que empiezan con #): es una viñeta o un párrafo.")
        elif not en_codigo and RX_COMENTARIO.match(linea):
            raise ValueError("`contenido` no puede tener líneas que parezcan un comentario de metadatos (<!-- item {...} -->).")
    return contenido


def _resumen(valor: str) -> str:
    v = _texto(valor, "resumen", MAX_RESUMEN)
    if "\n" in v:
        raise ValueError("`resumen` es una sola línea.")
    return v


def crear_item(con, entrada_id: int, fecha: str, tipo: str, resumen: str, contenido: str, modulos: list[str], archivos=(),
               prueba: str = "", vigencia: str = "vigente", orden: int | None = None) -> int:
    """Inserta un ítem (con sus módulos y archivos) al final de la entrada. No valida ni confirma: eso lo hace quien llama."""
    if orden is None:
        orden = con.execute("SELECT COALESCE(MAX(orden), 0) + 1 FROM bitacora_items WHERE entrada_id=?", (entrada_id,)).fetchone()[0]
    cur = con.execute("INSERT INTO bitacora_items (entrada_id, orden, fecha, tipo, vigencia, resumen, contenido, prueba) VALUES (?,?,?,?,?,?,?,?)",
                      (entrada_id, orden, fecha, tipo, vigencia, resumen, contenido, prueba or None))
    con.executemany("INSERT INTO bitacora_item_modulo (item_id, modulo) VALUES (?,?)", [(cur.lastrowid, m) for m in modulos])
    con.executemany("INSERT INTO bitacora_item_archivo (item_id, ruta) VALUES (?,?)", [(cur.lastrowid, a) for a in archivos])
    return cur.lastrowid


def registrar_bitacora(con, seccion: str, tipo: str, titulo: str, resumen: str, modulos, contenido: str, fecha: str = "",
                       archivos=None, prueba: str = "") -> dict:
    """Crea un ítem de la bitácora (y la entrada `seccion` / `titulo` si todavía no existe). Devuelve el id del ÍTEM."""
    seccion, titulo = _texto(seccion, "seccion", MAX_SECCION), _texto(titulo, "titulo", MAX_TITULO)
    tipo, resumen = _opcion(tipo, TIPOS_ITEM, "tipo"), _resumen(resumen)
    contenido = _sin_encabezados(_texto(contenido, "contenido", MAX_CONTENIDO))
    lista_modulos = [_modulo(m) for m in _lista(modulos, "modulos", 40)]
    if not lista_modulos:
        raise ValueError(f"`modulos` no puede estar vacío. Los válidos son: {', '.join(mapa.MODULOS)}.")
    lista_archivos = [mapa.normalizar(a) for a in _lista(archivos, "archivos", MAX_ARCHIVO)]
    prueba = _texto(prueba, "prueba", MAX_PRUEBA, obligatorio=False)
    fecha = _fecha(fecha, "fecha") if (fecha or "").strip() else hoy()
    asegurar(con)
    entrada = con.execute("SELECT id, contenido FROM bitacora WHERE seccion=? AND titulo=? ORDER BY id DESC LIMIT 1", (seccion, titulo)).fetchone()
    if entrada is None:
        entrada_id = con.execute("INSERT INTO bitacora (fecha, seccion, tipo, titulo, contenido) VALUES (?,?,?,?,'')",
                                 (fecha, seccion, TIPO_DE_ENTRADA.get(tipo, tipo), titulo)).lastrowid
    else:
        entrada_id = entrada["id"]
        if entrada["contenido"] and not con.execute("SELECT 1 FROM bitacora_items WHERE entrada_id=?", (entrada_id,)).fetchone():
            raise ValueError("Esa entrada todavía tiene su texto sin dividir en ítems: agregarle uno ahora lo sacaría del archivo exportado. "
                             "Usá otro título o migrala primero.")
    item = crear_item(con, entrada_id, fecha, tipo, resumen, contenido, lista_modulos, lista_archivos, prueba)
    con.commit()
    return {"id": item, "entrada": entrada_id, "mensaje": "Registrado en la bitácora."}


def _modulos_de_items(con, ids: list[int]) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {i: [] for i in ids}
    for i in range(0, len(ids), 500):
        lote = ids[i:i + 500]
        for f in con.execute(f"SELECT item_id, modulo FROM bitacora_item_modulo WHERE item_id IN ({','.join('?' * len(lote))}) ORDER BY modulo", lote):
            out[f["item_id"]].append(f["modulo"])
    return out


def _item_compacto(f, mods: dict[int, list[str]]) -> dict:
    d = {"id": f["id"], "tipo": f["tipo"], "modulos": mods.get(f["id"], []), "resumen": f["resumen"]}
    if f["vigencia"] != "vigente":
        d["vigencia"] = f["vigencia"]
    if f["reemplazada_por"]:
        d["reemplazada_por"] = f["reemplazada_por"]
    return d


def _hay_items(con) -> bool:
    return existe(con, "bitacora_items") and con.execute("SELECT 1 FROM bitacora_items LIMIT 1").fetchone() is not None


def buscar_bitacora(con, consulta: str, n: int = 5) -> dict:
    """Busca sobre los ítems (resumen y contenido) y devuelve resúmenes, no bloques; el contenido está en `detalle_bitacora`.
    Mientras la base no tenga ítems, cae a la búsqueda por sección de antes."""
    n = max(1, min(int(n), MAX_RESULTADOS))
    if not existe(con, "bitacora"):
        return {"total": 0, "resultados": [], "nota": "La bitácora todavía no tiene entradas en la base."}
    if consulta_fts(consulta) is None:
        return {"error": "Escribí al menos una palabra para buscar."}
    if not _hay_items(con):
        filas = _buscar(con, "bitacora", "bitacora_fts", "t.*", "3.0, 5.0, 1.0", "", consulta, n)
        return {"total": len(filas), "nota": "Sin ítems todavía: resultados por sección.", "resultados": [
            {"id": f["id"], "fecha": f["fecha"], "seccion": f["seccion"], "tipo": f["tipo"], "titulo": f["titulo"],
             "contenido": corto(f["contenido"], 400)} for f in filas]}
    filas = _buscar(con, "bitacora_items", "bitacora_items_fts", "t.*", "5.0, 1.0", "", consulta, n)
    mods = _modulos_de_items(con, [f["id"] for f in filas])
    return {"total": len(filas), "resultados": [_item_compacto(f, mods) for f in filas]}


def contexto(con, archivo: str | None = None, modulo: str | None = None, tipo: str | None = None,
             incluir_superadas: bool = False, n: int = 12) -> dict:
    """Resúmenes de la bitácora para una tarea. `archivo` se resuelve a su módulo con el mapa (y suma los ítems que lo nombran);
    sin `archivo` ni `modulo` son todos. Orden: invariantes, pendientes, limitaciones, decisiones, errores, pruebas, notas. Las
    invariantes vigentes se incluyen siempre, aunque se pase de `n`."""
    n = max(1, min(int(n), MAX_CONTEXTO))
    tipo = _opcion(tipo, TIPOS_ITEM, "tipo") if (tipo or "").strip() else None
    de_modulos = [_modulo(modulo)] if (modulo or "").strip() else []
    ruta = mapa.normalizar(archivo) if (archivo or "").strip() else None
    if ruta:
        encontrados = mapa.modulos_de(ruta)
        if not encontrados and not de_modulos:
            raise ValueError(f"`{ruta}` no está en ningún módulo del mapa: pasá `modulo`.")
        de_modulos += [m for m in encontrados if m not in de_modulos]
    if not _hay_items(con):
        return {"total": 0, "items": [], "nota": "La bitácora todavía no tiene ítems en la base."}
    donde, par = [], []
    if de_modulos or ruta:
        partes = []
        if de_modulos:
            partes.append(f"i.id IN (SELECT item_id FROM bitacora_item_modulo WHERE modulo IN ({','.join('?' * len(de_modulos))}))")
            par += de_modulos
        if ruta:
            partes.append("i.id IN (SELECT item_id FROM bitacora_item_archivo WHERE ruta = ?)")
            par.append(ruta)
        donde.append("(" + " OR ".join(partes) + ")")
    if tipo:
        donde.append("i.tipo = ?")
        par.append(tipo)
    if not incluir_superadas:
        donde.append("i.vigencia = 'vigente'")
    orden = "CASE i.tipo " + " ".join(f"WHEN '{t}' THEN {k}" for k, t in enumerate(ORDEN_TIPOS)) + " END"
    filas = con.execute(f"SELECT i.* FROM bitacora_items i {'WHERE ' + ' AND '.join(donde) if donde else ''} "
                        f"ORDER BY (i.vigencia <> 'vigente'), {orden}, i.fecha DESC, i.id DESC", par).fetchall()
    fijas = [f for f in filas if f["tipo"] == "invariante" and f["vigencia"] == "vigente"] if tipo in (None, "invariante") else []
    ids_fijas = {f["id"] for f in fijas}
    resto = [f for f in filas if f["id"] not in ids_fijas]
    cupo = len(resto) if tipo == "invariante" else max(0, n - len(fijas))
    elegidas = fijas + resto[:cupo]
    mods = _modulos_de_items(con, [f["id"] for f in elegidas])
    out = {"total": len(filas), "items": [_item_compacto(f, mods) for f in elegidas]}
    if ruta:
        out["modulos"] = de_modulos
    if len(elegidas) < len(filas):
        out["omitidos"] = len(filas) - len(elegidas)
    return out


def _item(con, ident) -> sqlite3.Row:
    f = con.execute("SELECT i.*, b.seccion, b.titulo AS entrada FROM bitacora_items i JOIN bitacora b ON b.id = i.entrada_id WHERE i.id=?",
                    (int(ident),)).fetchone() if existe(con, "bitacora_items") else None
    if f is None:
        raise ValueError(f"No existe el ítem #{ident} en la bitácora.")
    return f


def detalle_bitacora(con, ident: int) -> dict:
    f = _item(con, ident)
    out = {"id": f["id"], "seccion": f["seccion"], "entrada": f["entrada"], "fecha": f["fecha"], "tipo": f["tipo"], "vigencia": f["vigencia"],
           "modulos": _modulos_de_items(con, [f["id"]])[f["id"]],
           "archivos": [a["ruta"] for a in con.execute("SELECT ruta FROM bitacora_item_archivo WHERE item_id=? ORDER BY ruta", (f["id"],))],
           "resumen": f["resumen"], "contenido": f["contenido"]}
    if f["prueba"]:
        out["prueba"] = f["prueba"]
    if f["reemplazada_por"]:
        r = con.execute("SELECT id, resumen FROM bitacora_items WHERE id=?", (f["reemplazada_por"],)).fetchone()
        out["reemplazada_por"] = {"id": r["id"], "resumen": r["resumen"]} if r else {"id": f["reemplazada_por"]}
        out["motivo"] = f["motivo"]
    anteriores = [r["id"] for r in con.execute("SELECT id FROM bitacora_items WHERE reemplazada_por=? ORDER BY id", (f["id"],))]
    if anteriores:
        out["reemplaza"] = anteriores
    return out


def pendientes(con, modulo: str | None = None) -> dict:
    """Los ítems `pendiente` vigentes, del más nuevo al más viejo; con `modulo`, solo los de ese módulo."""
    de_modulo = _modulo(modulo) if (modulo or "").strip() else None
    if not _hay_items(con):
        return {"total": 0, "pendientes": [], "nota": "La bitácora todavía no tiene ítems en la base."}
    filtro = "AND i.id IN (SELECT item_id FROM bitacora_item_modulo WHERE modulo = ?)" if de_modulo else ""
    filas = con.execute(f"SELECT i.* FROM bitacora_items i WHERE i.tipo='pendiente' AND i.vigencia='vigente' {filtro} "
                        "ORDER BY i.fecha DESC, i.id DESC", (de_modulo,) if de_modulo else ()).fetchall()
    mods = _modulos_de_items(con, [f["id"] for f in filas[:MAX_CONTEXTO]])
    out = {"total": len(filas), "pendientes": [{**_item_compacto(f, mods), "fecha": f["fecha"]} for f in filas[:MAX_CONTEXTO]]}
    if len(filas) > MAX_CONTEXTO:
        out["omitidos"] = len(filas) - MAX_CONTEXTO
    return out


def marcar_superada(con, ident: int, reemplazada_por: int, motivo: str) -> dict:
    """Marca un ítem como superado por otro ítem vigente. No borra nada: el ítem queda como historia, con su reemplazo y el motivo."""
    motivo = _texto(motivo, "motivo", MAX_MOTIVO)
    viejo, nuevo = _item(con, ident), _item(con, reemplazada_por)
    if viejo["id"] == nuevo["id"]:
        raise ValueError("Un ítem no puede reemplazarse a sí mismo.")
    if viejo["vigencia"] == "superada":
        raise ValueError(f"El ítem #{viejo['id']} ya está superado por #{viejo['reemplazada_por']}.")
    if nuevo["vigencia"] != "vigente":
        raise ValueError(f"El ítem #{nuevo['id']} no está vigente: indicá el que realmente reemplaza.")
    con.execute("UPDATE bitacora_items SET vigencia='superada', reemplazada_por=?, motivo=? WHERE id=?", (nuevo["id"], motivo, viejo["id"]))
    _auditar(con, "marcar_superada", {"id": viejo["id"], "reemplazada_por": nuevo["id"], "motivo": motivo}, f"#{viejo['id']} superado por #{nuevo['id']}")
    con.commit()
    return {"id": viejo["id"], "mensaje": f"El ítem #{viejo['id']} quedó superado por #{nuevo['id']}."}


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


# ---------- exportación a markdown (BITACORA.md y CHANGELOG.md) ----------
# Solo se exportan la bitácora y el changelog. `memoria` y `hechos_conocidos` son datos personales: no salen de la base ni van a git.

RAIZ = Path(__file__).resolve().parent
AVISO_GENERADO = ("> Archivo **generado** desde la tabla `{tabla}` de `doctor.db` con `uv run memoria.py --exportar` (el hook pre-commit lo "
                  "regenera). **No se edita a mano**: los cambios se hacen con `{tool}` y se vuelve a exportar.")
INTRO_BITACORA = "Registro cronológico de las decisiones del proyecto. Cada entrada indica su fecha y su tipo."
INTRO_CHANGELOG = ("Historial de diagnósticos, errores, soluciones y cambios del equipo, de la entrada más nueva a la más vieja. "
                   "La identidad del equipo se calcula al exportar, desde el último snapshot de entorno.")
SECCION_INTRO = "Introducción"
TIPO_CHANGELOG_TEXTO = {"error": "error", "solucion": "solución", "cambio": "cambio", "observacion": "observación"}


RX_VINETA = re.compile(r"^(?:[-*+] |\d+[.)] )")


def es_continuacion(texto: str) -> bool:
    """Si un ítem se pega a lo anterior sin línea en blanco (una viñeta), en vez de empezar un párrafo."""
    return bool(RX_VINETA.match(texto)) or texto.startswith((" ", "\t"))


def marcas_de_item(f) -> list[str]:
    """Líneas que se agregan al ítem exportado: si es una invariante (con el test que la protege) y si está superada. Nunca tocan el texto."""
    marcas = []
    if f["tipo"] == "invariante":
        marcas.append(f"**(invariante · prueba: {' '.join(f['prueba'].split())})**" if f["prueba"] else "**(invariante)**")
    if f["vigencia"] == "superada" and f["reemplazada_por"]:
        marcas.append(f"(superada por #{f['reemplazada_por']}: {' '.join((f['motivo'] or '').split())})")
    return marcas


def _cuerpo_de(con, entrada, items: list, modulos_de: dict, archivos_de: dict) -> str:
    """El texto de una entrada: sus ítems en orden o, si no tiene ítems, su `contenido`. Cada ítem lleva antes su comentario de metadatos
    (sangrado dentro de la viñeta anterior, para que la lista siga siendo una sola). Cada viñeta va pegada a la anterior y un párrafo,
    separado por una línea en blanco. Las marcas van en líneas aparte, después del ítem y sangradas si el ítem es una viñeta."""
    if not items:
        return entrada["contenido"]
    cuerpo = ""
    for k, it in enumerate(items):
        pegado = es_continuacion(it["contenido"])
        sangria = "  " if pegado else ""
        bloque = "\n".join([(sangria if k else "") + comentario("item", _meta_item(it, modulos_de, archivos_de)), it["contenido"]]
                           + [sangria + m for m in marcas_de_item(it)])
        cuerpo += (("\n" if pegado else "\n\n") if k else "") + bloque
    return cuerpo


def exportar_bitacora(con) -> str:
    """Markdown de la bitácora: una sección `##` por `seccion` (o `##` + `###` si trae ` / `) y un encabezado por entrada, con su fecha y tipo."""
    con_items = existe(con, "bitacora_items")
    items_de: dict[int, list] = {}
    modulos_de: dict[int, list] = {}
    archivos_de: dict[int, list] = {}
    if con_items:
        for it in con.execute("SELECT * FROM bitacora_items ORDER BY entrada_id, orden"):
            items_de.setdefault(it["entrada_id"], []).append(it)
        for f in con.execute("SELECT item_id, modulo FROM bitacora_item_modulo ORDER BY modulo"):
            modulos_de.setdefault(f["item_id"], []).append(f["modulo"])
        for f in con.execute("SELECT item_id, ruta FROM bitacora_item_archivo ORDER BY ruta"):
            archivos_de.setdefault(f["item_id"], []).append(f["ruta"])
    out = ["# Bitácora de pc-doctor", "", AVISO_GENERADO.format(tabla="bitacora", tool="registrar_bitacora"), "", INTRO_BITACORA]
    anterior: list[str] = []
    for f in con.execute("SELECT * FROM bitacora ORDER BY id"):
        ruta = f["seccion"].split(" / ")
        for i, parte in enumerate(ruta):
            if anterior[:i + 1] != ruta[:i + 1]:
                out += ["", f"{'#' * (i + 2)} {parte}"]
        anterior = ruta
        meta = comentario("entrada", {"id": f["id"], "seccion": f["seccion"], "titulo": f["titulo"], "fecha": f["fecha"], "tipo": f["tipo"]})
        cuerpo = _cuerpo_de(con, f, items_de.get(f["id"], []), modulos_de, archivos_de)
        if f["titulo"] == SECCION_INTRO:          # el texto que va antes de los subtítulos de la sección, sin encabezado propio
            out += ["", meta, "", cuerpo]
            continue
        out += ["", f"{'#' * (len(ruta) + 2)} {f['titulo']}", f"_{f['fecha']} · {f['tipo']}_", meta, "", cuerpo]
    return "\n".join(out) + "\n"


def _disco(h, d) -> str:
    modelo = (h["modelo"] or h["marca"] or "disco").strip()
    return f"{modelo} {d.get('tamano', '')} ({d.get('dev', '?')})".replace("  ", " ")


def identidad(con) -> list[tuple[str, str]]:
    """(campo, valor) de la identidad del equipo, calculada desde el último snapshot de entorno y su hardware. [] si no hay snapshot."""
    s = con.execute("SELECT * FROM snapshot_entorno ORDER BY tomado_en DESC, id DESC LIMIT 1").fetchone()
    if not s:
        return []
    hw = [(h, json.loads(h["detalle"] or "{}")) for h in con.execute("SELECT * FROM hardware WHERE snapshot_id=?", (s["id"],))]
    por_tipo = lambda t: [(h, d) for h, d in hw if h["tipo"] == t]
    filas = [("Hostname", socket.gethostname()), ("SO", f"{s['distro']}, escritorio {s['escritorio']}"), ("Kernel", s["kernel"])]
    for h, d in por_tipo("cpu")[:1]:
        modelo = re.sub(r"\s+\d+-Core Processor$", "", h["modelo"])
        filas.append(("CPU", f"{modelo} ({d.get('nucleos_fisicos', '?')} núcleos, {d.get('hilos', '?')} hilos, {d.get('arquitectura', '?')})"))
    for h, d in por_tipo("gpu")[:1]:
        modelo = re.sub(r"\s*\(rev [0-9a-f]+\)", "", re.sub(r"^Advanced Micro Devices, Inc\. \[AMD/ATI\] ", "", h["modelo"]))
        extra = ", ".join(x for x in (f"driver `{d['driver']}`" if d.get("driver") else "", f"Mesa {d['mesa'].split('~')[0]}" if d.get("mesa") else "") if x)
        filas.append(("GPU", f"{modelo}{', ' + extra if extra else ''}"))
    for h, d in por_tipo("ram")[:1]:
        filas.append(("RAM", f"{str(d.get('total_gb', '?')).replace('.', ',')} GB ({'sin swap' if not d.get('swap_gb') else 'swap ' + str(d['swap_gb']) + ' GB'})"))
    discos = [_disco(h, d) for h, d in hw if h["tipo"] == "disco" or d.get("dev")]
    if discos:
        filas.append(("Discos", "; ".join(discos)))
    for h, d in por_tipo("mother")[:1]:
        filas.append(("Placa madre", f"{h['marca']} {h['modelo']}".strip() + (f", BIOS {d['bios']}" if d.get("bios") else "")))
    cuentas = con.execute("SELECT origen, COUNT(*) n FROM software WHERE snapshot_id=? GROUP BY origen ORDER BY origen", (s["id"],)).fetchall()
    if cuentas:
        filas.append(("Paquetes", f"{sum(c['n'] for c in cuentas)} (" + ", ".join(f"{c['origen']} {c['n']}" for c in cuentas) + ")"))
    filas.append(("_Snapshot_", db.iso(s["tomado_en"])))
    return filas


def exportar_changelog(con) -> str:
    out = ["# Changelog de la PC", "", AVISO_GENERADO.format(tabla="changelog", tool="registrar_changelog` y `resolver_changelog"), "", INTRO_CHANGELOG, "",
           "## Identidad actual", ""]
    calculadas, manuales = identidad(con), identidad_declarada(con)
    filas = calculadas + [(f["campo"], f["valor"]) for f in manuales]
    if filas:
        out += ["| Campo | Valor |", "|---|---|"] + [f"| {c} | {v.replace('|', '/').replace(chr(10), ' ')} |" for c, v in filas]
    if not calculadas:
        out += ["", "_Todavía no hay un snapshot de entorno._"]
    if manuales:
        ultima = max(f["actualizado"] for f in manuales)
        out += ["", f"_{', '.join(f['campo'] for f in manuales)}: declarados a mano (`registrar_identidad`), no calculados; "
                    f"última actualización: {db.iso(ultima)[:10]}._"]
        out += [comentario("identidad_manual", {"campo": f["campo"], "valor": f["valor"], "actualizado": f["actualizado"]}) for f in manuales]
    out += ["", "## Entradas"]
    for f in con.execute("SELECT * FROM changelog ORDER BY id DESC"):
        titulo = f["titulo"] or corto(f["detalle"].split("\n")[0], 90)
        estado = "resuelto" + (f" ({f['resuelto_en']})" if f["resuelto_en"] else "") if f["estado"] == "resuelto" else "abierto"
        meta = {"id": f["id"], "fecha": f["fecha"], "tipo": f["tipo"], "componente": f["componente"], "titulo": f["titulo"], "estado": f["estado"],
                "resuelto_en": f["resuelto_en"]}
        out += ["", f"### {f['fecha']} — {titulo}", comentario("changelog", meta), f"- **Tipo:** {TIPO_CHANGELOG_TEXTO[f['tipo']]}", f"- **Componente:** {f['componente']}",
                f"- **Detalle:** {f['detalle']}", f"- **Estado:** {estado}"]
    return "\n".join(out) + "\n"


def exportar(con, destino: Path = RAIZ, archivos: tuple[str, ...] | None = None) -> dict:
    """Escribe BITACORA.md y CHANGELOG.md en `destino` (o solo los de `archivos`). No escribe lo que no tiene tabla todavía; devuelve
    cuántas entradas exportó."""
    res = {}
    for tabla, archivo, funcion in (("bitacora", "BITACORA.md", exportar_bitacora), ("changelog", "CHANGELOG.md", exportar_changelog)):
        if not existe(con, tabla) or (archivos is not None and archivo not in archivos):
            continue
        texto = funcion(con)
        destino.mkdir(parents=True, exist_ok=True)
        if not (destino / archivo).exists() or (destino / archivo).read_text(encoding="utf-8") != texto:   # no toca el archivo si no cambió
            (destino / archivo).write_text(texto, encoding="utf-8")
        res[archivo] = con.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
    return res


# ---------- el markdown como respaldo completo (metadatos en comentarios HTML e importación) ----------
# Cada entrada, cada ítem, cada entrada del changelog y cada fila de identidad manual llevan un comentario HTML de una línea con sus
# metadatos en JSON: GitHub no lo muestra, pero queda en el archivo, y `--importar` reconstruye las tablas leyendo solo esos comentarios y el
# texto que cuelga de ellos. Lo que se ve (encabezados, fecha, tipo, marcas, tabla de identidad) es para leer; al importar no cuenta.

RX_COMENTARIO = re.compile(r"^\s*<!-- (entrada|item|changelog|identidad_manual) (\{.*\}) -->\s*$")
RX_ENCABEZADO_MD = re.compile(r"^#{2,6} ")
_ESCAPES_JSON = (("--", "\\u002d\\u002d"), ("<", "\\u003c"), (">", "\\u003e"), (" ", "\\u2028"), (" ", "\\u2029"), ("\x85", "\\u0085"))
TABLAS_BITACORA = ("bitacora_item_modulo", "bitacora_item_archivo", "bitacora_items", "bitacora")     # en orden de borrado
TABLAS_CHANGELOG = ("changelog", "identidad_manual")


def comentario(clave: str, datos: dict) -> str:
    """Comentario HTML de una línea con `datos` en JSON. Se escapa lo que podría cerrarlo (`--`, `<`, `>`) o partir la línea."""
    texto = json.dumps(datos, ensure_ascii=False, separators=(",", ":"))
    for crudo, escapado in _ESCAPES_JSON:
        texto = texto.replace(crudo, escapado)
    return f"<!-- {clave} {texto} -->"


def unir_items(textos: list[str]) -> str:
    """Pega los ítems de una entrada: cada viñeta va pegada a la anterior y un párrafo, separado por una línea en blanco."""
    cuerpo = textos[0]
    for t in textos[1:]:
        cuerpo += ("\n" if es_continuacion(t) else "\n\n") + t
    return cuerpo


def _meta_item(it, modulos_de: dict, archivos_de: dict) -> dict:
    meta = {"id": it["id"], "tipo": it["tipo"], "vigencia": it["vigencia"], "fecha": it["fecha"], "resumen": it["resumen"],
            "modulos": modulos_de.get(it["id"], [])}
    if archivos_de.get(it["id"]):
        meta["archivos"] = archivos_de[it["id"]]
    for campo in ("prueba", "reemplazada_por", "motivo"):
        if it[campo]:
            meta[campo] = it[campo]
    return meta


def _leer_comentario(linea: str):
    m = RX_COMENTARIO.match(linea)
    if not m:
        return None
    try:
        return m.group(1), json.loads(m.group(2))
    except json.JSONDecodeError as e:
        raise ValueError(f"Un comentario de metadatos no es JSON válido ({e}): {linea.strip()[:120]}") from None


def _recortar(lineas: list[str]) -> list[str]:
    ini, fin = 0, len(lineas)
    while ini < fin and not lineas[ini].strip():
        ini += 1
    while fin > ini and not lineas[fin - 1].strip():
        fin -= 1
    return lineas[ini:fin]


def leer_bitacora(texto: str) -> list[dict]:
    """Entradas (con sus ítems) de un BITACORA.md exportado. Lee solo los comentarios de metadatos y el texto que sigue a cada uno; un
    bloque termina en el comentario siguiente o en un encabezado (fuera de los bloques de código)."""
    entradas: list[dict] = []
    bloque, en_codigo = None, False       # bloque = (clave, meta, líneas)

    def cerrar():
        nonlocal bloque
        if bloque is None:
            return
        clave, meta, lineas = bloque
        bloque = None
        lineas = _recortar(lineas)
        if clave == "entrada":
            meta["items"], meta["lineas"] = [], lineas
            entradas.append(meta)
            return
        for marca in reversed(marcas_de_item({"tipo": meta["tipo"], "prueba": meta.get("prueba"), "vigencia": meta["vigencia"],
                                              "reemplazada_por": meta.get("reemplazada_por"), "motivo": meta.get("motivo")})):
            if not lineas or lineas[-1].strip() != marca:
                raise ValueError(f"Al ítem #{meta['id']} le falta la marca `{marca}` que dicen sus metadatos.")
            lineas = _recortar(lineas[:-1])
        if not lineas:
            raise ValueError(f"El ítem #{meta['id']} no tiene texto.")
        meta["contenido"] = "\n".join(lineas)
        entradas[-1]["items"].append(meta)

    for linea in texto.split("\n"):
        if bloque is not None and linea.lstrip().startswith("```"):
            en_codigo = not en_codigo
        if not en_codigo:
            leido = _leer_comentario(linea)
            if leido and leido[0] in ("entrada", "item"):
                cerrar()
                if leido[0] == "item" and not entradas:
                    raise ValueError(f"El ítem #{leido[1].get('id')} aparece antes de cualquier entrada.")
                bloque = (leido[0], leido[1], [])
                continue
            if RX_ENCABEZADO_MD.match(linea):
                cerrar()
                continue
        if bloque is not None:
            bloque[2].append(linea)
    cerrar()
    for e in entradas:
        if e["items"]:
            if e["lineas"]:
                raise ValueError(f"La entrada #{e['id']} tiene texto fuera de sus ítems.")
            e["contenido"] = unir_items([i["contenido"] for i in e["items"]])
        else:
            e["contenido"] = "\n".join(e["lineas"])
    return entradas


def leer_changelog(texto: str) -> tuple[list[dict], list[dict]]:
    """(entradas del changelog, filas de identidad manual) de un CHANGELOG.md exportado. La identidad calculada no se importa."""
    lineas = texto.split("\n")
    marcas = [(i, *c) for i, l in enumerate(lineas) if (c := _leer_comentario(l))]
    identidad_m = [meta for _, clave, meta in marcas if clave == "identidad_manual"]
    cl = [(i, meta) for i, clave, meta in marcas if clave == "changelog"]
    entradas = []
    for k, (i, meta) in enumerate(cl):
        fin = cl[k + 1][0] - 1 if k + 1 < len(cl) else len(lineas)          # la línea anterior al siguiente comentario es su encabezado
        bloque = _recortar(lineas[i + 1:fin])
        if "detalle" not in meta:
            ini = next((j for j, l in enumerate(bloque) if l.startswith("- **Detalle:** ")), None)
            fin_d = max((j for j, l in enumerate(bloque) if l.startswith("- **Estado:** ")), default=None)
            if ini is None or fin_d is None or fin_d < ini:
                raise ValueError(f"La entrada #{meta.get('id')} del changelog no tiene Detalle y Estado.")
            meta["detalle"] = "\n".join([bloque[ini][len("- **Detalle:** "):]] + bloque[ini + 1:fin_d])
        entradas.append(meta)
    return entradas, identidad_m


def importar(con, bitacora_md: str | None = None, changelog_md: str | None = None, reemplazar: bool = False) -> dict:
    """Reconstruye `bitacora`, `bitacora_items` (con módulos y archivos), `changelog` e `identidad_manual` desde los markdown exportados,
    con los mismos ids. Se niega si esas tablas ya tienen datos, salvo `reemplazar=True` (que las vacía; quien llama hace la copia previa).
    Todo en una sola transacción: si algo falla, no queda nada a medias."""
    entradas = leer_bitacora(bitacora_md) if bitacora_md is not None else None
    cl, ident = leer_changelog(changelog_md) if changelog_md is not None else (None, None)
    if entradas is not None and not entradas:
        raise ValueError("BITACORA.md no tiene metadatos (<!-- entrada ... -->): es de antes de la Fase 5. Usá el tag `pre-migracion-memoria` o regeneralo.")
    if cl is not None and not cl and not ident:
        raise ValueError("CHANGELOG.md no tiene metadatos (<!-- changelog ... -->): es de antes de la Fase 5.")
    if entradas is None and cl is None:
        raise ValueError("No hay nada que importar.")
    asegurar(con)
    tablas = (TABLAS_BITACORA if entradas is not None else ()) + (TABLAS_CHANGELOG if cl is not None else ())
    con_datos = [t for t in tablas if con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]]
    if con_datos and not reemplazar:
        raise RuntimeError(f"Las tablas {', '.join(con_datos)} ya tienen datos: la importación no pisa nada sin `--reemplazar`.")
    res = {}
    try:
        con.execute("BEGIN")
        for t in tablas:
            con.execute(f"DELETE FROM {t}")
        if entradas is not None:
            n_items = 0
            for e in entradas:
                con.execute("INSERT INTO bitacora (id, fecha, seccion, tipo, titulo, contenido) VALUES (?,?,?,?,?,?)",
                            (e["id"], e["fecha"], e["seccion"], e["tipo"], e["titulo"], e["contenido"]))
                for orden, it in enumerate(e["items"], 1):
                    con.execute("INSERT INTO bitacora_items (id, entrada_id, orden, fecha, tipo, vigencia, reemplazada_por, motivo, resumen, contenido, prueba) "
                                "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (it["id"], e["id"], orden, it["fecha"], it["tipo"], it["vigencia"], it.get("reemplazada_por"),
                                                                     it.get("motivo"), it["resumen"], it["contenido"], it.get("prueba")))
                    con.executemany("INSERT INTO bitacora_item_modulo (item_id, modulo) VALUES (?,?)", [(it["id"], m) for m in it.get("modulos", [])])
                    con.executemany("INSERT INTO bitacora_item_archivo (item_id, ruta) VALUES (?,?)", [(it["id"], a) for a in it.get("archivos", [])])
                    n_items += 1
            res.update(bitacora=len(entradas), items=n_items)
        if cl is not None:
            for e in sorted(cl, key=lambda x: x["id"]):
                con.execute("INSERT INTO changelog (id, fecha, tipo, componente, titulo, detalle, estado, resuelto_en) VALUES (?,?,?,?,?,?,?,?)",
                            (e["id"], e["fecha"], e["tipo"], e["componente"], e.get("titulo"), e["detalle"], e["estado"], e.get("resuelto_en")))
            for f in ident:
                con.execute("INSERT INTO identidad_manual (campo, valor, actualizado) VALUES (?,?,?)", (f["campo"], f["valor"], f["actualizado"]))
            res.update(changelog=len(cl), identidad=len(ident))
        _auditar(con, "importar_memoria", {"reemplazar": reemplazar}, str(res))
        con.commit()
    except BaseException:
        con.rollback()
        raise
    return res


def _carpeta(argv: list[str], opcion: str) -> Path | None:
    """Carpeta que sigue a `opcion` (--destino, --origen), o la raíz del proyecto si no se pasó."""
    if opcion not in argv:
        return RAIZ
    i = argv.index(opcion)
    if i + 1 >= len(argv):
        print(f"{opcion} necesita una carpeta.", file=sys.stderr)
        return None
    return Path(argv[i + 1]).expanduser().resolve()


def main_importar(argv: list[str]) -> int:
    origen = _carpeta(argv, "--origen")
    if origen is None:
        return 2
    leidos = {a: (origen / a).read_text(encoding="utf-8") for a in ("BITACORA.md", "CHANGELOG.md") if (origen / a).exists()}
    if not leidos:
        print(f"No hay BITACORA.md ni CHANGELOG.md en {origen}.", file=sys.stderr)
        return 1
    reemplazar = "--reemplazar" in argv
    con = db.conectar()
    try:
        if reemplazar and db.RUTA_DB.exists():
            copia = db.RUTA_DB.with_name(f"{db.RUTA_DB.name}.antes-de-importar-{db.ahora()}")
            con.execute(f"VACUUM INTO '{str(copia).replace(chr(39), chr(39) * 2)}'")
            print("Copia previa:", copia)
        res = importar(con, leidos.get("BITACORA.md"), leidos.get("CHANGELOG.md"), reemplazar)
    except (RuntimeError, ValueError) as e:
        print(e, file=sys.stderr)
        return 1
    finally:
        con.close()
    print("Importado desde", origen, "->", res)
    return 0


def main(argv: list[str]) -> int:
    if "--importar" in argv:
        return main_importar(argv)
    if "--exportar" not in argv:
        print("Uso: uv run memoria.py --exportar [--destino CARPETA]   (regenera BITACORA.md y CHANGELOG.md desde la base)\n"
              "     uv run memoria.py --importar [--origen CARPETA] [--reemplazar]   (reconstruye las tablas desde los markdown; "
              "--reemplazar vacía las que tengan datos, después de hacer una copia de la base)", file=sys.stderr)
        return 2
    destino = _carpeta(argv, "--destino")
    if destino is None:
        return 2
    if not db.RUTA_DB.exists():
        print("No hay base de datos: no hay nada que exportar.")
        return 0
    con = sqlite3.connect(f"file:{db.RUTA_DB}?mode=ro", uri=True, timeout=10)    # solo lectura: exportar nunca cambia la base
    con.row_factory = sqlite3.Row
    try:
        res = exportar(con, destino)
    finally:
        con.close()
    print("Exportado en", destino, "->", ", ".join(f"{a} ({n} entradas)" for a, n in res.items()) or "nada (las tablas no existen todavía)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""Migra la memoria que estaba en archivos (BITACORA.md, CHANGELOG.md y hechos sueltos) a las tablas de doctor.db.

    uv run migrar_memoria.py              simula: muestra qué se migraría y no escribe nada
    uv run migrar_memoria.py --ejecutar   escribe en la base
    uv run migrar_memoria.py --items PROPUESTA.json [--ejecutar]
                                          divide las entradas de la bitácora ya migradas en ítems (tipo, módulos, vigencia, resumen...)
                                          según una propuesta revisada; exige la copia `doctor.db.antes-de-items-*`

Reglas: no borra ni modifica ningún markdown; se niega a escribir si no hay una copia previa de la base
(`doctor.db.antes-de-memoria-*`) o si las tablas ya tienen datos; escribe todo en una sola transacción y deja constancia en `acciones`.
"""

import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import db
import memoria
import modulos as mapa_modulos

RAIZ = Path(__file__).resolve().parent
FECHA_INICIAL = "2026-10-28"                       # el único día con fecha en los archivos: todo el proyecto es de ese día
SECCION_INICIAL = "Construcción inicial"
RX_ENCABEZADO = re.compile(r"^(#{1,4}) (.+?)\s*$")
RX_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------- bitácora ----------

def tipo_de_bitacora(titulo: str) -> str:
    """Tipo de la entrada según el título de su sección (Decisiones, Errores, Pruebas, Limitaciones...); el resto es una nota."""
    t = titulo.lower().strip()
    if t.startswith("decision"):
        return "decision"
    if t.startswith(("errores", "problemas")):
        return "error"
    if t.startswith(("prueba", "verificaci")):
        return "prueba"
    if t.startswith("limitaci"):
        return "limitacion"
    return "nota"


def _arbol(texto: str) -> tuple[list[str], list[dict]]:
    """(líneas antes del primer `##`, nodos de nivel 2). Cada nodo: titulo, cuerpo (líneas) y hijos. No toma como encabezado
    lo que está dentro de un bloque de código."""
    previo, raiz, pila, en_codigo = [], [], [], False
    for linea in texto.splitlines():
        if linea.lstrip().startswith("```"):
            en_codigo = not en_codigo
        m = None if en_codigo else RX_ENCABEZADO.match(linea)
        if m and len(m.group(1)) >= 2:
            nivel = len(m.group(1))
            nodo = {"nivel": nivel, "titulo": m.group(2), "cuerpo": [], "hijos": []}
            while pila and pila[-1]["nivel"] >= nivel:
                pila.pop()
            (pila[-1]["hijos"] if pila else raiz).append(nodo)
            pila.append(nodo)
        elif m:                                     # el `#` del título del documento
            previo.append(linea)
        elif pila:
            pila[-1]["cuerpo"].append(linea)
        else:
            previo.append(linea)
    return previo, raiz


def _contenido(lineas: list[str]) -> str:
    return "\n".join(lineas).strip("\n").strip()


def parsear_bitacora(texto: str) -> tuple[str, list[dict]]:
    """(preámbulo, entradas). Una entrada por cada sección hoja del documento, con `seccion` = `##` (o `## / ###` cuando hay `####`),
    `titulo` = el encabezado más profundo y `contenido` = su texto tal cual. Un texto que está antes de los subtítulos se guarda como
    entrada "Introducción". Las fechas: el bloque `## AAAA-MM-DD` se llama "Construcción inicial (fecha)"; el resto hereda la última."""
    previo, nodos = _arbol(texto)
    entradas, fecha = [], FECHA_INICIAL

    def agregar(seccion, titulo, cuerpo, tipo=None):
        contenido = _contenido(cuerpo)
        if contenido:
            entradas.append({"fecha": fecha, "seccion": seccion, "tipo": tipo or tipo_de_bitacora(titulo), "titulo": titulo, "contenido": contenido})

    for n2 in nodos:
        if RX_FECHA.match(n2["titulo"]):
            fecha, seccion = n2["titulo"], f"{SECCION_INICIAL} ({n2['titulo']})"
        else:
            seccion = n2["titulo"]
        agregar(seccion, "Introducción", n2["cuerpo"], "nota")
        for n3 in n2["hijos"]:
            if not n3["hijos"]:
                agregar(seccion, n3["titulo"], n3["cuerpo"])
                continue
            sub = f"{seccion} / {n3['titulo']}"
            agregar(sub, "Introducción", n3["cuerpo"], "nota")
            for n4 in n3["hijos"]:
                agregar(sub, n4["titulo"], n4["cuerpo"])
    return _contenido(previo), entradas


def dividir_en_items(contenido: str) -> list[str]:
    """Parte el contenido de una entrada en ítems: una viñeta de primer nivel con sus subviñetas, o un párrafo. El texto de cada ítem
    queda tal cual (los bloques de código no se parten); las líneas en blanco entre ítems se descartan, el exportador las vuelve a poner."""
    items, actual, en_codigo = [], [], False

    def cerrar():
        nonlocal actual
        if actual:
            items.append("\n".join(actual))
        actual = []

    for linea in contenido.split("\n"):
        if linea.lstrip().startswith("```"):
            en_codigo = not en_codigo
            actual.append(linea)
        elif en_codigo:
            actual.append(linea)
        elif not linea.strip():
            cerrar()
        elif linea.startswith((" ", "\t")):
            actual.append(linea)
        elif memoria.RX_VINETA.match(linea):
            cerrar()
            actual = [linea]
        elif actual and not memoria.RX_VINETA.match(actual[0]):       # sigue el mismo párrafo
            actual.append(linea)
        else:
            cerrar()
            actual = [linea]
    cerrar()
    return items


# ---------- changelog ----------

COMPONENTES = [   # (fragmento del título en minúsculas, componente); la primera coincidencia gana
    ("suite de pruebas", "pc-doctor (pruebas)"), ("node.js", "node"), ("dashboard", "dashboard"), ("procesador y gpu", "cpu y gpu"),
    ("detección de juegos", "actividad"), ("distingue cuando", "actividad"), ("fan7", "ventilador fan7"),
    ("reporte semanal", "reporte"), ("smartd", "disco (smartd)"), ("smart de `sdb`", "disco sdb"), ("sensores habilitados", "sensores"),
    ("aprendizaje", "línea base"), ("alertas de salud", "alertas"), ("xmrig", "seguridad"), ("ttyd", "red"), ("terminal web", "red"),
    ("mineros", "seguridad"), ("perfil de energía", "cpu (energía)"), ("temperatura de cpu", "cpu"), ("instalación de pc-doctor", "pc-doctor"),
]
TIPOS = {"solución": "solucion", "solucion": "solucion", "cambio": "cambio", "observación": "observacion", "observacion": "observacion", "error": "error"}
RX_ENTRADA = re.compile(r"^### (\d{4}-\d{2}-\d{2}) — (.+?)\s*$")
RX_CAMPO = re.compile(r"^- \*\*(.+?):\*\*\s?(.*)$")


def componente_de(titulo: str) -> str:
    t = titulo.lower()
    return next((c for frag, c in COMPONENTES if frag in t), "general")


def parsear_changelog(texto: str) -> list[dict]:
    """Entradas de la sección "Entradas" de CHANGELOG.md, de la más nueva a la más vieja (como están en el archivo).

    `tipo` y `estado` se normalizan a los valores de la tabla (lo que sigue entre paréntesis, o las notas del estado, no se pierden:
    pasan al detalle). Todo lo demás de la entrada (Detalle, Hipótesis, Para confirmar...) se conserva tal cual en `detalle`."""
    resto = texto.split("\n## Entradas", 1)
    entradas, actual = [], None
    for linea in (resto[1] if len(resto) > 1 else "").splitlines():
        m = RX_ENTRADA.match(linea)
        if m:
            actual = {"fecha": m.group(1), "titulo": m.group(2), "lineas": []}
            entradas.append(actual)
        elif actual is not None:
            actual["lineas"].append(linea)
    return [_entrada_changelog(e) for e in entradas]


def _entrada_changelog(e: dict) -> dict:
    tipo_crudo, estado_crudo, partes = "", "", []
    for linea in "\n".join(e["lineas"]).strip().split("\n"):
        m = RX_CAMPO.match(linea)
        if m and m.group(1) == "Tipo":
            tipo_crudo = m.group(2).strip()
        elif m and m.group(1) == "Estado":
            estado_crudo = m.group(2).strip()
        elif m and m.group(1) == "Detalle" and not partes:
            partes.append(m.group(2))
        else:
            partes.append(linea)
    base = re.split(r"[\s(.]", tipo_crudo, maxsplit=1)[0].lower()
    tipo = TIPOS.get(base, "error")
    palabra = re.split(r"[\s(.:]", estado_crudo, maxsplit=1)[0].lower()
    estado = "resuelto" if palabra == "resuelto" else "abierto"       # "en curso" y "abierto (vigilando)" siguen abiertos
    notas = []
    if tipo_crudo.lower() != tipo and tipo_crudo.lower() not in TIPOS:
        notas.append(f"- **Tipo original:** {tipo_crudo}")
    if estado_crudo and estado_crudo.lower() != estado:
        notas.append(f"- **Estado original:** {estado_crudo}")
    detalle = "\n".join(partes).strip("\n").strip()
    if notas:
        detalle += "\n" + "\n".join(notas)
    return {"fecha": e["fecha"], "tipo": tipo, "componente": componente_de(e["titulo"]), "titulo": e["titulo"], "detalle": detalle,
            "estado": estado, "resuelto_en": e["fecha"] if estado == "resuelto" else None}


# ---------- hechos de la PC que vivían en los archivos ----------

def hechos_de_identidad(texto: str) -> list[dict]:
    """Filas de "Identidad actual" que NO se pueden volver a calcular con el snapshot de entorno (energía, red, sensores extra, Node.js):
    pasan a `identidad_manual`, que SÍ se exporta (es identidad de la PC, no un dato personal). Las demás (SO, kernel, CPU, GPU, RAM,
    discos, placa, paquetes) se generan al exportar desde el snapshot."""
    fecha = (re.search(r"_Última actualización: (\d{4}-\d{2}-\d{2})_", texto) or [None, FECHA_INICIAL])[1]
    res = []
    for campo in ("Energía", "Red expuesta", "Sensores extra", "Node.js"):
        m = re.search(rf"^\| {re.escape(campo)} \| (.+?) \|\s*$", texto, re.M)
        if m:
            res.append({"campo": campo, "valor": m.group(1), "fecha": fecha})
    return res


HECHOS_DE_CLAUDE_MD = [   # hechos del equipo y del proyecto que estaban dentro de las reglas de CLAUDE.md
    {"tema": "pc-doctor: ubicación de los datos", "tipo": "hecho",
     "texto": "La base está en ~/.local/share/pc-doctor/doctor.db (fuera del repositorio). En la carpeta del proyecto, `datos` es un enlace "
              "simbólico visible hacia esa carpeta y `venv` hacia `.venv`."},
    {"tema": "pc-doctor: privacidad", "tipo": "decision",
     "texto": "Los datos se guardan solo en la PC. Online solo se consulta el hash de ejecutables ya marcados como sospechosos; nunca se suben "
              "archivos ni se consultan procesos no sospechosos."},
]


# ---------- migración ----------

def copias_previas() -> list[Path]:
    return sorted(db.DIR_DATOS.glob("doctor.db.antes-de-memoria-*"))


def reunir(raiz: Path = RAIZ) -> dict:
    bit = (raiz / "BITACORA.md").read_text(encoding="utf-8")
    cl = (raiz / "CHANGELOG.md").read_text(encoding="utf-8")
    preambulo, bitacora = parsear_bitacora(bit)
    return {"preambulo": preambulo, "bitacora": bitacora, "changelog": parsear_changelog(cl),
            "identidad": hechos_de_identidad(cl), "memoria": HECHOS_DE_CLAUDE_MD}


def migrar(con, datos: dict) -> dict:
    """Escribe todo en una sola transacción. Se niega si alguna tabla ya tiene datos (no se puede repetir por accidente)."""
    memoria.asegurar(con)
    for tabla in ("memoria", "bitacora", "changelog"):
        if con.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]:
            raise RuntimeError(f"La tabla {tabla} ya tiene datos: la migración no se repite.")
    ahora = db.ahora()
    try:
        con.execute("BEGIN")
        # en orden inverso: las entradas del archivo van de la más nueva a la más vieja y los ids deben crecer con el tiempo
        for e in reversed(datos["changelog"]):
            con.execute("INSERT INTO changelog (fecha, tipo, componente, titulo, detalle, estado, resuelto_en) VALUES (?,?,?,?,?,?,?)",
                        (e["fecha"], e["tipo"], e["componente"], e["titulo"], e["detalle"], e["estado"], e["resuelto_en"]))
        for e in datos["bitacora"]:
            con.execute("INSERT INTO bitacora (fecha, seccion, tipo, titulo, contenido) VALUES (?,?,?,?,?)",
                        (e["fecha"], e["seccion"], e["tipo"], e["titulo"], e["contenido"]))
        for e in datos.get("identidad", []):
            con.execute("INSERT INTO identidad_manual (campo, valor, actualizado) VALUES (?,?,?)",
                        (e["campo"], e["valor"], int(datetime.fromisoformat(e["fecha"]).timestamp())))
        for e in datos["memoria"]:
            con.execute("INSERT INTO memoria (creado, actualizado, tema, tipo, texto, origen) VALUES (?,?,?,?,?,'agente')",
                        (ahora, ahora, e["tema"], e["tipo"], e["texto"]))
        con.execute("INSERT INTO acciones (ts, tool, parametros, resultado) VALUES (?,?,?,?)",
                    (ahora, "migrar_memoria", "{}", f"bitacora={len(datos['bitacora'])} changelog={len(datos['changelog'])} memoria={len(datos['memoria'])} identidad={len(datos.get('identidad', []))}"))
        con.commit()
    except BaseException:
        con.rollback()
        raise
    return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("bitacora", "changelog", "memoria")}


# ---------- bitácora en ítems ----------

def copias_previas_items() -> list[Path]:
    return sorted(db.DIR_DATOS.glob("doctor.db.antes-de-items-*"))


unir_items = memoria.unir_items       # lo contrario de dividir_en_items; el exportador usa el mismo


def validar_items(con, propuesta: list[dict]) -> list[str]:
    """Problemas que impedirían migrar (lista vacía si está todo bien). No escribe. Exige que los ítems de cada entrada, unidos, den
    exactamente su texto actual: así no se pierde ni se reordena nada; y que el `n` de cada ítem sea su futuro id."""
    if not memoria.existe(con, "bitacora"):
        return ["La base no tiene la tabla bitacora."]
    problemas, vistos = [], {}
    if [d["n"] for d in propuesta] != list(range(1, len(propuesta) + 1)):
        problemas.append("Los `n` de la propuesta deben ser 1, 2, 3... sin saltos: son los ids de los ítems.")
    entradas = {f["id"]: f["contenido"] for f in con.execute("SELECT id, contenido FROM bitacora")}
    por_entrada: dict[int, list[str]] = {}
    for d in propuesta:
        if d["entrada"] not in entradas:
            problemas.append(f"#{d['n']}: la entrada {d['entrada']} no existe.")
        elif not d.get("nuevo"):
            por_entrada.setdefault(d["entrada"], []).append(d["texto"])
        vistos[d["n"]] = d
    for eid, contenido in entradas.items():
        textos = por_entrada.get(eid)
        if not textos:
            problemas.append(f"La entrada {eid} no tiene ítems en la propuesta.")
        elif unir_items(textos) != contenido:
            problemas.append(f"La entrada {eid}: sus ítems, unidos, no dan su texto actual.")
    for d in propuesta:
        n = d["n"]
        if d["tipo"] not in memoria.TIPOS_ITEM or d["vigencia"] not in memoria.VIGENCIAS:
            problemas.append(f"#{n}: tipo o vigencia inválidos.")
        if not d["modulos"] or any(m not in mapa_modulos.MODULOS for m in d["modulos"]):
            problemas.append(f"#{n}: módulos inválidos {d['modulos']}.")
        if not d["resumen"].strip() or len(d["resumen"]) > memoria.MAX_RESUMEN or "\n" in d["resumen"]:
            problemas.append(f"#{n}: el resumen debe ser una línea de hasta {memoria.MAX_RESUMEN} caracteres.")
        if (d["vigencia"] == "superada") != bool(d.get("reemplazada_por")):
            problemas.append(f"#{n}: superada y reemplazo van juntos.")
        if d.get("reemplazada_por"):
            r = vistos.get(d["reemplazada_por"])
            if r is None or r["vigencia"] != "vigente" or r["n"] == n:
                problemas.append(f"#{n}: lo reemplaza #{d['reemplazada_por']}, que no existe o no está vigente.")
            if not (d.get("motivo") or "").strip():
                problemas.append(f"#{n}: falta el motivo.")
    return problemas


def migrar_items(con, propuesta: list[dict]) -> dict:
    """Escribe los ítems en una sola transacción (las tablas se crean antes). Se niega si hay problemas o si ya hay ítems."""
    memoria.asegurar(con)
    problemas = validar_items(con, propuesta)
    if problemas:
        raise ValueError("La propuesta no es válida:\n- " + "\n- ".join(problemas[:20]))
    if con.execute("SELECT COUNT(*) FROM bitacora_items").fetchone()[0]:
        raise RuntimeError("La tabla bitacora_items ya tiene datos: la migración no se repite.")
    try:
        con.execute("BEGIN")
        orden: dict[int, int] = {}
        for d in propuesta:
            orden[d["entrada"]] = orden.get(d["entrada"], 0) + 1
            nuevo = memoria.crear_item(con, d["entrada"], d["fecha"], d["tipo"], d["resumen"].strip(), d["texto"], d["modulos"], d["archivos"],
                                       d.get("prueba") or "", d["vigencia"] if d["vigencia"] != "superada" else "vigente", orden[d["entrada"]])
            if nuevo != d["n"]:
                raise RuntimeError(f"El ítem #{d['n']} quedó con el id {nuevo}: la base no estaba vacía.")
        for d in propuesta:
            if d["vigencia"] == "superada":
                con.execute("UPDATE bitacora_items SET vigencia='superada', reemplazada_por=?, motivo=? WHERE id=?", (d["reemplazada_por"], d["motivo"].strip(), d["n"]))
        res = {"items": len(propuesta), "nuevos": sum(bool(d.get("nuevo")) for d in propuesta), "superadas": sum(d["vigencia"] == "superada" for d in propuesta),
               "historicas": sum(d["vigencia"] == "historica" for d in propuesta), "invariantes": sum(d["tipo"] == "invariante" for d in propuesta),
               "pendientes": sum(d["tipo"] == "pendiente" for d in propuesta)}
        con.execute("INSERT INTO acciones (ts, tool, parametros, resultado) VALUES (?,?,?,?)", (db.ahora(), "migrar_memoria", '{"items": true}', str(res)))
        con.commit()
    except BaseException:
        con.rollback()
        raise
    return res


def main_items(argv: list[str]) -> int:
    i = argv.index("--items")
    if i + 1 >= len(argv):
        print("--items necesita el archivo de la propuesta (JSON).", file=sys.stderr)
        return 2
    propuesta = json.loads(Path(argv[i + 1]).expanduser().read_text(encoding="utf-8"))
    if "--ejecutar" not in argv:      # simulación: solo lectura, no crea tablas
        if not db.RUTA_DB.exists():
            print("No hay base de datos.", file=sys.stderr)
            return 1
        con = sqlite3.connect(f"file:{db.RUTA_DB}?mode=ro", uri=True, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            problemas = validar_items(con, propuesta)
        finally:
            con.close()
        print(f"Se migrarían {len(propuesta)} ítems." + (f" Problemas ({len(problemas)}):\n- " + "\n- ".join(problemas[:20]) if problemas else " La propuesta es válida."))
        print("Simulación: no se escribió nada. Con --ejecutar se escribe en la base.")
        return 1 if problemas else 0
    if not copias_previas_items():
        print("No encuentro una copia previa (doctor.db.antes-de-items-*). Hacela con VACUUM INTO antes de migrar.", file=sys.stderr)
        return 1
    con = db.conectar()
    try:
        print("Escrito:", migrar_items(con, propuesta))
    except (RuntimeError, ValueError) as e:
        print(e, file=sys.stderr)
        return 1
    finally:
        con.close()
    return 0


def main(argv: list[str]) -> int:
    if "--items" in argv:
        return main_items(argv)
    datos = reunir()
    print(f"Se migrarían: {len(datos['bitacora'])} entradas de bitácora, {len(datos['changelog'])} del changelog "
          f"({sum(e['estado'] == 'abierto' for e in datos['changelog'])} abiertas), {len(datos['memoria'])} recuerdos y {len(datos['identidad'])} filas de identidad.")
    if "--ejecutar" not in argv:
        print("Simulación: no se escribió nada. Con --ejecutar se escribe en la base.")
        return 0
    if not copias_previas():
        print("No encuentro una copia previa (doctor.db.antes-de-memoria-*). Hacela con VACUUM INTO antes de migrar.", file=sys.stderr)
        return 1
    con = db.conectar()
    try:
        print("Escrito:", migrar(con, datos))
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 1
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

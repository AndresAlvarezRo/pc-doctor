"""Migración de BITACORA.md, CHANGELOG.md y hechos sueltos a las tablas de memoria (migrar_memoria.py).

Con textos sintéticos y en la base temporal: la base real solo se toca al correr la migración de verdad, con copia previa."""

import re
import sqlite3

import pytest

import db
import memoria
import migrar_memoria as mm

BITACORA = """# Bitácora de pc-doctor

Texto del preámbulo.

## 2026-10-28

### Estructura y datos
- Un punto con `código`.

### Servidor MCP
Texto suelto.

## Nivel nuevo 1: línea base
Introducción del nivel.

### Decisiones
- Decisión A.

### Errores encontrados y corregidos
- Error B.

```
### esto no es un encabezado
```

## Nivel nuevo 2: dashboard

### Fase 1
#### Decisiones
- Decisión C.

#### Pruebas (base temporal)
- Prueba D.

### Fase 2
Texto propio de la fase.
#### Limitaciones
- Limitación E.
"""

CHANGELOG = """# Changelog de la PC

## Identidad actual
_Última actualización: 2026-10-27_

| Campo | Valor |
|---|---|
| SO | Zorin OS |
| Energía | Perfil `balanced` |
| Red expuesta | Solo Steam |
| Sensores extra | `smartmontools` |
| Node.js | 24.22.2 |

## Entradas

### 2026-10-28 — SMART de `sdb`: nuevo error
- **Tipo:** error (hardware, a confirmar)
- **Detalle:** primera línea
  con continuación.
- **Hipótesis (sin confirmar):** algo.
- **Estado:** abierto (vigilando)

### 2026-10-27 — Se cambió el perfil de energía
- **Tipo:** solución
- **Detalle:** listo.
- **Estado:** resuelto. El usuario lo probó.

### 2026-10-26 — Algo en curso
- **Tipo:** cambio
- **Detalle:** x
- **Estado:** en curso (aprendiendo)
"""


def test_tipo_de_bitacora_segun_el_titulo():
    for titulo, tipo in [("Decisiones", "decision"), ("Errores encontrados y corregidos", "error"), ("Problemas de las pruebas mismas", "error"),
                         ("Pruebas (base temporal)", "prueba"), ("Verificación (Paso 8)", "prueba"), ("Limitaciones", "limitacion"),
                         ("Qué quedó", "nota"), ("Ajuste a algo", "nota")]:
        assert mm.tipo_de_bitacora(titulo) == tipo


def test_la_bitacora_se_parte_por_encabezado_y_conserva_el_texto():
    pre, es = mm.parsear_bitacora(BITACORA)
    assert pre.endswith("Texto del preámbulo.")
    resumen = [(e["seccion"], e["tipo"], e["titulo"]) for e in es]
    assert resumen == [
        ("Construcción inicial (2026-10-28)", "nota", "Estructura y datos"),
        ("Construcción inicial (2026-10-28)", "nota", "Servidor MCP"),
        ("Nivel nuevo 1: línea base", "nota", "Introducción"),
        ("Nivel nuevo 1: línea base", "decision", "Decisiones"),
        ("Nivel nuevo 1: línea base", "error", "Errores encontrados y corregidos"),
        ("Nivel nuevo 2: dashboard / Fase 1", "decision", "Decisiones"),
        ("Nivel nuevo 2: dashboard / Fase 1", "prueba", "Pruebas (base temporal)"),
        ("Nivel nuevo 2: dashboard / Fase 2", "nota", "Introducción"),
        ("Nivel nuevo 2: dashboard / Fase 2", "limitacion", "Limitaciones"),
    ]
    assert all(e["fecha"] == "2026-10-28" for e in es)
    assert "### esto no es un encabezado" in es[4]["contenido"]                  # dentro de un bloque de código
    assert es[0]["contenido"] == "- Un punto con `código`."


def test_la_bitacora_no_pierde_ni_reordena_ninguna_linea():
    pre, es = mm.parsear_bitacora(BITACORA)
    esperadas = [l for l in BITACORA.splitlines() if l.strip() and not re.match(r"^#{1,4} ", l) or l.startswith("### esto")]
    obtenidas = [l for l in pre.splitlines() if l.strip() and not l.startswith("# ")] + [l for e in es for l in e["contenido"].splitlines() if l.strip()]
    assert obtenidas == esperadas


def test_las_fechas_de_un_bloque_con_fecha_se_heredan_hasta_el_siguiente():
    _, es = mm.parsear_bitacora("# B\n\n## 2026-01-02\n### A\nx\n\n## 2026-03-04\n### B\ny\n\n## Nivel\n### C\nz\n")
    assert [(e["fecha"], e["titulo"]) for e in es] == [("2026-01-02", "A"), ("2026-03-04", "B"), ("2026-03-04", "C")]


def test_el_changelog_se_normaliza_sin_perder_notas():
    es = mm.parsear_changelog(CHANGELOG)
    assert [e["fecha"] for e in es] == ["2026-10-28", "2026-10-27", "2026-10-26"]
    a, b, c = es
    assert (a["tipo"], a["estado"], a["resuelto_en"], a["componente"]) == ("error", "abierto", None, "disco sdb")
    assert "primera línea\n  con continuación." in a["detalle"] and "**Hipótesis (sin confirmar):** algo." in a["detalle"]
    assert "**Tipo original:** error (hardware, a confirmar)" in a["detalle"] and "**Estado original:** abierto (vigilando)" in a["detalle"]
    assert (b["tipo"], b["estado"], b["resuelto_en"], b["componente"]) == ("solucion", "resuelto", "2026-10-27", "cpu (energía)")
    assert "**Estado original:** resuelto. El usuario lo probó." in b["detalle"]
    assert (c["tipo"], c["estado"]) == ("cambio", "abierto") and "en curso (aprendiendo)" in c["detalle"]       # "en curso" sigue abierto


def test_de_la_identidad_solo_pasan_los_datos_que_no_se_pueden_recalcular():
    hs = mm.hechos_de_identidad(CHANGELOG)
    assert [h["tema"] for h in hs] == ["identidad: energía", "identidad: red expuesta", "identidad: sensores extra", "identidad: node.js"]
    assert "(según el changelog al 2026-10-27)" in hs[0]["texto"] and all("SO" not in h["tema"] for h in hs)


def datos():
    pre, bit = mm.parsear_bitacora(BITACORA)
    return {"preambulo": pre, "bitacora": bit, "changelog": mm.parsear_changelog(CHANGELOG), "memoria": mm.hechos_de_identidad(CHANGELOG) + mm.HECHOS_DE_CLAUDE_MD}


def test_migrar_escribe_todo_y_deja_los_ids_en_orden_cronologico(con):
    r = mm.migrar(con, datos())
    assert r == {"bitacora": 9, "changelog": 3, "memoria": 6}
    assert [f["fecha"] for f in con.execute("SELECT fecha FROM changelog ORDER BY id")] == ["2026-10-26", "2026-10-27", "2026-10-28"]   # el archivo va al revés
    assert [f["titulo"] for f in con.execute("SELECT titulo FROM bitacora ORDER BY id LIMIT 2")] == ["Estructura y datos", "Servidor MCP"]
    assert con.execute("SELECT COUNT(*) FROM acciones WHERE tool='migrar_memoria'").fetchone()[0] == 1
    assert memoria.buscar_bitacora(con, "Texto propio de la fase")["total"] == 1 and memoria.buscar_memoria(con, "energia")["total"] == 1   # y se puede buscar
    assert memoria.changelog_abierto(con)["total"] == 2 and memoria.hechos_conocidos(con)["activos"] == []     # ningún hecho conocido se carga solo


def test_la_migracion_no_se_repite(con):
    mm.migrar(con, datos())
    with pytest.raises(RuntimeError, match="ya tiene datos"):
        mm.migrar(con, datos())
    assert con.execute("SELECT COUNT(*) FROM bitacora").fetchone()[0] == 9


def test_si_algo_falla_a_mitad_no_queda_nada_a_medias(con):
    malo = datos()
    malo["memoria"] = [{"tema": "x", "tipo": "inventado", "texto": "y"}]                  # viola el CHECK de la tabla
    with pytest.raises(sqlite3.IntegrityError):
        mm.migrar(con, malo)
    assert all(con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0 for t in ("bitacora", "changelog", "memoria"))


def test_sin_copia_previa_no_escribe(monkeypatch, capsys):
    monkeypatch.setattr(mm, "reunir", datos)
    assert mm.main(["--ejecutar"]) == 1 and "copia previa" in capsys.readouterr().err
    c = db.conectar()
    assert not memoria.existe(c, "bitacora")
    c.close()


def test_la_simulacion_no_escribe_nada(monkeypatch, capsys):
    monkeypatch.setattr(mm, "reunir", datos)
    assert mm.main([]) == 0 and "Simulación" in capsys.readouterr().out
    c = db.conectar()
    assert not memoria.existe(c, "bitacora")
    c.close()


def test_con_copia_previa_escribe(monkeypatch, capsys):
    monkeypatch.setattr(mm, "reunir", datos)
    (db.DIR_DATOS / "doctor.db.antes-de-memoria-1").write_text("")
    assert mm.main(["--ejecutar"]) == 0 and "'bitacora': 9" in capsys.readouterr().out
    assert mm.main(["--ejecutar"]) == 1                                                   # la segunda vez se niega

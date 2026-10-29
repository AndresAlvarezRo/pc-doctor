"""limpiar_descargas_viejas y restaurar_cuarentena: son las únicas tools que MUEVEN archivos del usuario, así que se prueban a fondo.

Todo ocurre en un HOME temporal (conftest.py): ~/Descargas es una carpeta de la prueba y nada toca archivos reales.

La edad de un archivo es el máximo entre mtime y ctime, y el ctime no se puede falsear (es el momento del último cambio de
metadatos). Por eso, para volver "viejos" a archivos recién creados se adelanta el reloj que usa solo remediacion.py."""

import hashlib
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import db
import remediacion
import server

HASTA_AHORA = time.time


@pytest.fixture
def descargas():
    d = Path.home() / "Descargas"
    d.mkdir()
    return d


@pytest.fixture
def adelantar_reloj(monkeypatch):
    """Hace que `limpiar_descargas_viejas` (que vive en remediacion.py) crea que pasaron `dias` días (el resto del programa conserva el reloj real)."""
    def poner(dias):
        monkeypatch.setattr(remediacion, "time", SimpleNamespace(time=lambda: HASTA_AHORA() + dias * 86400))
    return poner


def archivo(ruta: Path, contenido: bytes = b"contenido") -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(contenido)
    return ruta


def huella(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def todos(raiz: Path) -> set[str]:
    return {str(p.relative_to(raiz)) for p in raiz.rglob("*") if p.is_file() or p.is_symlink()}


# ---------- límites y entradas inválidas ----------

def test_dias_menores_que_1_dan_error(descargas):
    assert "error" in server.limpiar_descargas_viejas(0, simular=False)


def test_sin_carpeta_de_descargas_da_error():
    assert "No existe" in server.limpiar_descargas_viejas(90)["error"]


def test_prefiere_descargas_sobre_downloads(descargas):
    (Path.home() / "Downloads").mkdir()
    assert db.carpeta_descargas() == descargas
    descargas.rmdir()
    assert db.carpeta_descargas() == Path.home() / "Downloads"


# ---------- qué cuenta como viejo ----------

def test_un_archivo_recien_copiado_no_cuenta_como_viejo_aunque_su_mtime_sea_de_hace_un_ano(descargas):
    a = archivo(descargas / "copiado.zip")
    hace_un_ano = time.time() - 365 * 86400
    os.utime(a, (hace_un_ano, hace_un_ano))           # mtime viejo, pero el ctime es de ahora (acaba de crearse)
    r = server.limpiar_descargas_viejas(90, simular=False)
    assert r["movidos"] == 0 and a.exists()


def test_los_archivos_viejos_se_listan_agrupados_por_elemento_de_primer_nivel(descargas, adelantar_reloj):
    archivo(descargas / "suelto.iso", b"x" * 3_000_000)
    archivo(descargas / "proyecto" / "a.txt", b"x" * 1_000_000)
    archivo(descargas / "proyecto" / "sub" / "b.txt", b"x" * 1_000_000)
    adelantar_reloj(100)
    r = server.limpiar_descargas_viejas(90)
    assert r["modo"] == "simulación" and r["archivos"] == 3 and r["elementos"] == 2
    por = {e["elemento"]: e for e in r["por_elemento"]}
    assert por["proyecto"]["archivos"] == 2 and por["suelto.iso"]["archivos"] == 1
    assert [e["elemento"] for e in r["por_elemento"]] == ["suelto.iso", "proyecto"]   # de mayor a menor tamaño
    assert r["total_mb"] == pytest.approx(4.8, abs=0.1)


def test_la_simulacion_no_mueve_nada_y_es_lo_predeterminado(descargas, adelantar_reloj):
    a = archivo(descargas / "viejo.bin")
    adelantar_reloj(100)
    r = server.limpiar_descargas_viejas()          # sin argumentos: simulación
    assert r["modo"] == "simulación" and a.exists() and not db.DIR_CUARENTENA.exists()
    assert "No se movió nada" in r["nota"]


def test_el_resumen_se_acota_a_20_elementos(descargas, adelantar_reloj):
    for i in range(25):
        archivo(descargas / f"carpeta{i:02d}" / "f.txt")
    adelantar_reloj(100)
    r = server.limpiar_descargas_viejas(90)
    assert r["elementos"] == 25 and len(r["por_elemento"]) == 20


# ---------- ejecución: mueve, nunca borra ----------

def test_ejecutar_mueve_a_cuarentena_conserva_el_contenido_y_registra(descargas, adelantar_reloj, con):
    a = archivo(descargas / "carpeta" / "documento.pdf", b"contenido importante")
    original = huella(a)
    adelantar_reloj(100)
    r = server.limpiar_descargas_viejas(90, simular=False)
    assert r["modo"] == "ejecución" and r["movidos"] == 1 and r["errores"] == []
    assert not a.exists()                                                    # salió de Descargas
    fila = con.execute("SELECT * FROM cuarentena").fetchone()
    nueva = Path(fila["ruta_nueva"])
    assert nueva.is_file() and huella(nueva) == original                      # nunca se borra: el contenido está intacto
    assert db.DIR_CUARENTENA in nueva.parents and nueva.name == "documento.pdf"
    assert fila["ruta_original"] == str(a.resolve()) and fila["restaurado"] == 0 and fila["tamano_bytes"] == len(b"contenido importante")
    accion = con.execute("SELECT * FROM acciones WHERE tool='limpiar_descargas_viejas'").fetchone()
    assert accion is not None and "movido a" in accion["resultado"]


def test_ejecutar_nunca_borra_ningun_archivo(descargas, adelantar_reloj):
    for i in range(5):
        archivo(descargas / f"d{i}" / f"f{i}.txt", f"datos {i}".encode())
    antes = sum(len(c.read_bytes()) for c in descargas.rglob("*.txt"))
    adelantar_reloj(100)
    server.limpiar_descargas_viejas(90, simular=False)
    en_cuarentena = list(db.DIR_CUARENTENA.rglob("*.txt"))
    assert len(en_cuarentena) == 5 and sum(len(c.read_bytes()) for c in en_cuarentena) == antes


def test_dos_corridas_el_mismo_dia_no_se_pisan(descargas, adelantar_reloj, con):
    adelantar_reloj(100)
    archivo(descargas / "a.txt", b"primero")
    server.limpiar_descargas_viejas(90, simular=False)
    archivo(descargas / "a.txt", b"segundo")                                   # otro archivo con el mismo nombre
    server.limpiar_descargas_viejas(90, simular=False)
    nuevas = sorted(Path(f["ruta_nueva"]) for f in con.execute("SELECT ruta_nueva FROM cuarentena"))
    assert len(nuevas) == 2 and {p.read_bytes() for p in nuevas} == {b"primero", b"segundo"}
    assert {p.name for p in nuevas} == {"a.txt", "a.1.txt"}


# ---------- solo opera dentro de Descargas ----------

def test_nunca_toca_archivos_fuera_de_descargas(descargas, adelantar_reloj):
    fuera = archivo(Path.home() / "Documentos" / "importante.txt", b"no tocar")
    contiguo = archivo(Path.home() / "Descargas2" / "x.txt", b"no tocar tampoco")   # carpeta de nombre parecido
    archivo(descargas / "viejo.txt")
    adelantar_reloj(100)
    server.limpiar_descargas_viejas(90, simular=False)
    assert fuera.read_bytes() == b"no tocar" and contiguo.read_bytes() == b"no tocar tampoco"


def test_los_enlaces_simbolicos_no_se_siguen_ni_se_mueven(descargas, adelantar_reloj):
    afuera = archivo(Path.home() / "secreto.txt", b"fuera de Descargas")
    carpeta_afuera = Path.home() / "otra"
    archivo(carpeta_afuera / "dentro.txt", b"dentro de la carpeta externa")
    enlace_archivo = descargas / "enlace.txt"
    enlace_archivo.symlink_to(afuera)
    enlace_carpeta = descargas / "enlace_carpeta"
    enlace_carpeta.symlink_to(carpeta_afuera)
    adelantar_reloj(100)
    r = server.limpiar_descargas_viejas(90, simular=False)
    assert r["movidos"] == 0
    assert afuera.read_bytes() == b"fuera de Descargas" and (carpeta_afuera / "dentro.txt").exists()
    assert enlace_archivo.is_symlink() and enlace_carpeta.is_symlink()       # los enlaces quedan donde estaban


def test_un_enlace_que_apunta_adentro_tampoco_se_mueve(descargas, adelantar_reloj):
    real = archivo(descargas / "real.txt")
    (descargas / "atajo.txt").symlink_to(real)
    adelantar_reloj(100)
    r = server.limpiar_descargas_viejas(90, simular=False)
    assert r["movidos"] == 1 and (descargas / "atajo.txt").is_symlink() and not real.exists()


# ---------- restaurar ----------

@pytest.fixture
def en_cuarentena(descargas, adelantar_reloj, con):
    """Un archivo ya movido a cuarentena; devuelve (id del registro, ruta original, contenido)."""
    a = archivo(descargas / "docs" / "carta.txt", b"hola mundo")
    adelantar_reloj(100)
    server.limpiar_descargas_viejas(90, simular=False)
    return con.execute("SELECT id FROM cuarentena").fetchone()["id"], a.resolve(), b"hola mundo"


def test_restaurar_devuelve_el_archivo_identico_a_su_lugar(en_cuarentena, con):
    ident, original, contenido = en_cuarentena
    assert not original.exists()
    r = server.restaurar_cuarentena(ident)
    assert r == {"restaurado": str(original)} and original.read_bytes() == contenido
    assert con.execute("SELECT restaurado FROM cuarentena WHERE id=?", (ident,)).fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM acciones WHERE tool='restaurar_cuarentena'").fetchone()[0] == 1
    assert not list(db.DIR_CUARENTENA.rglob("carta.txt"))                    # ya no queda en cuarentena


def test_restaurar_dos_veces_da_error_y_no_duplica(en_cuarentena):
    ident, original, _ = en_cuarentena
    server.restaurar_cuarentena(ident)
    assert "ya fue restaurado" in server.restaurar_cuarentena(ident)["error"]


def test_restaurar_no_pisa_un_archivo_que_ya_existe(en_cuarentena, con):
    ident, original, contenido = en_cuarentena
    archivo(original, b"otro archivo mas nuevo")
    r = server.restaurar_cuarentena(ident)
    assert "no lo piso" in r["error"]
    assert original.read_bytes() == b"otro archivo mas nuevo"                  # el existente quedó intacto
    assert Path(con.execute("SELECT ruta_nueva FROM cuarentena").fetchone()[0]).read_bytes() == contenido   # y la copia sigue en cuarentena


def test_restaurar_recrea_la_carpeta_original_si_ya_no_existe(en_cuarentena, descargas):
    ident, original, contenido = en_cuarentena
    original.parent.rmdir()
    assert not original.parent.exists()
    server.restaurar_cuarentena(ident)
    assert original.read_bytes() == contenido


@pytest.mark.parametrize("ident", [0, 999, -1])
def test_restaurar_un_id_inexistente_da_error(con, ident):
    assert "No existe" in server.restaurar_cuarentena(ident)["error"]


def test_restaurar_si_el_archivo_de_cuarentena_ya_no_esta(en_cuarentena, con):
    ident, _, _ = en_cuarentena
    Path(con.execute("SELECT ruta_nueva FROM cuarentena").fetchone()[0]).unlink()
    assert "no existe" in server.restaurar_cuarentena(ident)["error"]


def test_el_ciclo_completo_deja_todo_como_estaba(descargas, adelantar_reloj, con):
    archivo(descargas / "a.txt", b"uno")
    archivo(descargas / "d" / "b.txt", b"dos")
    antes = {p: huella(descargas / p) for p in todos(descargas)}
    adelantar_reloj(100)
    server.limpiar_descargas_viejas(90, simular=False)
    assert todos(descargas) == set()                                          # Descargas quedó vacía de archivos
    for fila in con.execute("SELECT id FROM cuarentena").fetchall():
        assert "restaurado" in server.restaurar_cuarentena(fila["id"])
    assert {p: huella(descargas / p) for p in todos(descargas)} == antes

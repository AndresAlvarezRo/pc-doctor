"""Resumen de lo que pc-doctor puede medir en esta PC, para `instalar.ps1 -Verificar`.

Solo lee: lecturas de sensores, lo que no se puede medir, estado del ayudante con privilegios y limitaciones fijas. No inventa nada: si un
valor no se puede medir, lo dice.
"""

import sys
from collections import Counter

import consultas
import db
import plataforma


def resumen_sensores(lecturas: list[dict]) -> list[str]:
    cuenta = Counter(l["categoria"] for l in lecturas)
    if not lecturas:
        return ["Sensores: ninguna lectura (ver 'No se puede medir' más abajo)."]
    return ["Sensores: " + ", ".join(f"{c} {n}" for c, n in sorted(cuenta.items()))]


def lineas() -> list[str]:
    p = plataforma.actual()
    res = [f"Sistema: {p.distro()} ({p.NOMBRE}), datos en {db.DIR_DATOS}"]
    lecturas = p.leer_sensores()
    res += resumen_sensores(lecturas)
    if p.NOMBRE == "windows":
        from plataforma import windows
        e = windows.ayudante()
        res.append("Ayudante con privilegios: " + {"ok": f"activo (último dato hace {e['edad_s'] // 60} min)", "ausente": "no instalado (opcional)",
                                                    "viejo": "sin datos recientes", "invalido": "archivo inválido"}.get(e["estado"], e["estado"]))
    faltan = p.no_disponible(lecturas)
    res.append("No se puede medir:" + ("" if faltan else " nada"))
    res += [f"  - {t}" for t in faltan]
    res.append("Limitaciones fijas:")
    res += [f"  - {l['tema']}: {l['que']}" for l in consultas.limitaciones_fijas()]
    return res


if __name__ == "__main__":
    print("\n".join(lineas()))
    sys.exit(0)

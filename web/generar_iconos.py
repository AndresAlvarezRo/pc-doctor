"""Genera los íconos de pc-doctor (SVG y PNG) en web/frontend/public/.

Es un cuadrado azul con esquinas redondeadas y un pulso (línea de latidos) blanco. Se corre una sola vez, o al cambiar el diseño:
    python3 web/generar_iconos.py        (necesita Pillow: paquete python3-pil)
El mismo SVG se copia a ~/.local/share/icons/hicolor/scalable/apps/pc-doctor.svg para el lanzador del menú.
"""

from pathlib import Path

from PIL import Image, ImageDraw

DESTINO = Path(__file__).resolve().parent / "frontend" / "public"
AZUL, BLANCO = (11, 92, 199), (255, 255, 255)
# el pulso, en un lienzo de 512 x 512
PULSO = [(64, 272), (172, 272), (212, 160), (288, 384), (336, 272), (448, 272)]
GROSOR, RADIO = 30, 112

SVG = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" role="img" aria-label="pc-doctor">
  <rect width="512" height="512" rx="{RADIO}" fill="rgb{AZUL}"/>
  <path d="M{PULSO[0][0]} {PULSO[0][1]}h{PULSO[1][0] - PULSO[0][0]}l{PULSO[2][0] - PULSO[1][0]} {PULSO[2][1] - PULSO[1][1]}l{PULSO[3][0] - PULSO[2][0]} {PULSO[3][1] - PULSO[2][1]}l{PULSO[4][0] - PULSO[3][0]} {PULSO[4][1] - PULSO[3][1]}h{PULSO[5][0] - PULSO[4][0]}" fill="none" stroke="#fff" stroke-width="{GROSOR}" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""


def dibujar(tam: int, enmascarable: bool = False) -> Image.Image:
    """PNG de `tam` píxeles. Enmascarable: fondo a sangre y pulso más chico, para que el sistema pueda recortarlo."""
    k = 4  # se dibuja al cuádruple y se reduce, para bordes suaves
    lienzo = tam * k
    img = Image.new("RGBA", (lienzo, lienzo), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if enmascarable:
        d.rectangle([0, 0, lienzo, lienzo], fill=AZUL)
        escala, desvio = 0.7, 0.15 * lienzo
    else:
        d.rounded_rectangle([0, 0, lienzo - 1, lienzo - 1], radius=RADIO / 512 * lienzo, fill=AZUL)
        escala, desvio = 1.0, 0.0
    f = lienzo / 512 * escala
    puntos = [(x * f + desvio, y * f + desvio) for x, y in PULSO]
    ancho = GROSOR * f
    d.line(puntos, fill=BLANCO, width=round(ancho), joint="curve")
    for x, y in (puntos[0], puntos[-1]):  # puntas redondeadas
        d.ellipse([x - ancho / 2, y - ancho / 2, x + ancho / 2, y + ancho / 2], fill=BLANCO)
    return img.resize((tam, tam), Image.LANCZOS)


if __name__ == "__main__":
    DESTINO.mkdir(parents=True, exist_ok=True)
    (DESTINO / "icono.svg").write_text(SVG)
    for nombre, tam, mask in (("icono-192.png", 192, False), ("icono-512.png", 512, False), ("icono-180.png", 180, False),
                              ("icono-maskable-512.png", 512, True)):
        dibujar(tam, mask).save(DESTINO / nombre, optimize=True)
        print("creado", DESTINO / nombre)
    print("creado", DESTINO / "icono.svg")

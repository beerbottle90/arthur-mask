"""ArthurLegal armasını Arthur Mask'a üretir: arayuz/logo.png (1024 px) ve arayuz/logo.svg.

Arma AL Masası'nınkiyle birebir aynıdır: geometri ve renkler arthurlegal-app4all `ortak/tasarim/arma.svg`'den
(lacivert squircle #183064 → #071230, altın A #FFE48A → #F7BE2D). Windows .ico ve macOS .icns derleme sırasında
logo.png'den üretilir (derle.py, derle_macos.py), yani kurulum simgeleri de bu armadır.

    python paketleme/logo_uret.py
"""

import re
from pathlib import Path

from PIL import Image, ImageDraw

KOK = Path(__file__).resolve().parent.parent
ARAYUZ = KOK / "arthur_mask" / "arayuz"

ZEMIN = ("#183064", "#071230")
ALTIN = ("#FFE48A", "#F7BE2D")
SQUIRCLE = (
    "M100.00 50.00L99.90 69.75L99.61 76.01L99.13 80.49L98.44 84.05L97.55 87.01L96.44 89.52L95.11 91.68L93.53 93.53"
    "L91.68 95.11L89.52 96.44L87.01 97.55L84.05 98.44L80.49 99.13L76.01 99.61L69.75 99.90L50.00 100.00L30.25 99.90"
    "L23.99 99.61L19.51 99.13L15.95 98.44L12.99 97.55L10.48 96.44L8.32 95.11L6.47 93.53L4.89 91.68L3.56 89.52"
    "L2.45 87.01L1.56 84.05L0.87 80.49L0.39 76.01L0.10 69.75L0.00 50.00L0.10 30.25L0.39 23.99L0.87 19.51L1.56 15.95"
    "L2.45 12.99L3.56 10.48L4.89 8.32L6.47 6.47L8.32 4.89L10.48 3.56L12.99 2.45L15.95 1.56L19.51 0.87L23.99 0.39"
    "L30.25 0.10L50.00 0.00L69.75 0.10L76.01 0.39L80.49 0.87L84.05 1.56L87.01 2.45L89.52 3.56L91.68 4.89L93.53 6.47"
    "L95.11 8.32L96.44 10.48L97.55 12.99L98.44 15.95L99.13 19.51L99.61 23.99L99.90 30.25Z"
)
HARF_A = ("M43.75 23.50L56.25 23.50L35.00 77.50L22.50 77.50Z"
          "M43.75 23.50L56.25 23.50L77.50 77.50L65.00 77.50Z"
          "M30.50 57.50L69.50 57.50L69.50 66.75L30.50 66.75Z")


def _cokgenler(yol: str):
    return [[(float(x), float(y)) for x, y in re.findall(r"([\d.]+) ([\d.]+)", parca)]
            for parca in yol.split("M")[1:]]


def _renk(h: str):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def _dikey_gecis(boyut: int, ust: str, alt: str, bas: float, son: float) -> Image.Image:
    """SVG linearGradient (x1=0 y1=bas x2=0 y2=son, nesnenin kutusuna göre) karşılığı; kutu = tuval."""
    a, b = _renk(ust), _renk(alt)
    sutun = Image.new("RGB", (1, boyut))
    for y in range(boyut):
        t = min(max((y / (boyut - 1) - bas) / (son - bas), 0.0), 1.0)
        sutun.putpixel((0, y), tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3)))
    return sutun.resize((boyut, boyut))


def ciz(boyut: int = 1024, ornek: int = 4) -> Image.Image:
    buyuk = boyut * ornek
    k = buyuk / 100

    maske = Image.new("L", (buyuk, buyuk), 0)
    ImageDraw.Draw(maske).polygon([(x * k, y * k) for x, y in _cokgenler(SQUIRCLE)[0]], fill=255)
    tuval = Image.new("RGBA", (buyuk, buyuk), (0, 0, 0, 0))
    tuval.paste(_dikey_gecis(buyuk, *ZEMIN, 0.0, 1.0), (0, 0), maske)

    # A'nın geçişi kendi kutusuna göredir (y 23.5–77.5): y1=0.2, y2=0.8.
    harf = _cokgenler(HARF_A)
    ust, alt = min(y for c in harf for _, y in c), max(y for c in harf for _, y in c)
    a_maske = Image.new("L", (buyuk, buyuk), 0)
    ciz_a = ImageDraw.Draw(a_maske)
    for c in harf:
        ciz_a.polygon([(x * k, y * k) for x, y in c], fill=255)
    gecis = Image.new("RGB", (buyuk, buyuk))
    kutu = _dikey_gecis(round((alt - ust) * k), *ALTIN, 0.2, 0.8)
    gecis.paste(kutu.resize((buyuk, kutu.height)), (0, round(ust * k)))
    tuval.paste(gecis, (0, 0), a_maske)
    return tuval.resize((boyut, boyut), Image.LANCZOS)


def svg() -> str:
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><defs>'
            f'<linearGradient id="z" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{ZEMIN[0]}"/>'
            f'<stop offset="1" stop-color="{ZEMIN[1]}"/></linearGradient>'
            f'<linearGradient id="a" x1="0" y1="0.2" x2="0" y2="0.8"><stop offset="0" stop-color="{ALTIN[0]}"/>'
            f'<stop offset="1" stop-color="{ALTIN[1]}"/></linearGradient></defs>'
            f'<path fill="url(#z)" d="{SQUIRCLE}"/><path fill="url(#a)" d="{HARF_A}"/></svg>\n')


if __name__ == "__main__":
    ciz().save(ARAYUZ / "logo.png", optimize=True)
    (ARAYUZ / "logo.svg").write_text(svg(), encoding="utf-8")
    print("logo.png ve logo.svg yazıldı:", ARAYUZ)

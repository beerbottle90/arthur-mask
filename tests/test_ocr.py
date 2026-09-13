"""Taranmış belge: yerel OCR, metin maskeleme ve görüntüye kalıcı etiket basma."""

from pathlib import Path

import pytest

rapidocr = pytest.importorskip("rapidocr")
pytest.importorskip("pypdfium2")

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from arthur_mask import belgeler  # noqa: E402
from arthur_mask.kasa import Kasa  # noqa: E402
from arthur_mask.servis import maskele_belge  # noqa: E402

SATIRLAR = [
    "DAVACI : Şebnem KURT (T.C. Kimlik No: 12345678950)",
    "Adres : Barbaros Mah. Lale Sk. No:14 D:3 Ataşehir/İSTANBUL",
    "SELLER: Harrow & Vale Holdings Limited, Passport No: U12345678",
]


def _tarama(yol, bicim):
    yollar = ("C:/Windows/Fonts/times.ttf", "/System/Library/Fonts/Supplemental/Times New Roman.ttf")
    font = ImageFont.truetype(next((y for y in yollar if Path(y).exists()), yollar[0]), 34)
    img = Image.new("RGB", (1654, 700), "white")
    ciz = ImageDraw.Draw(img)
    for i, satir in enumerate(SATIRLAR):
        ciz.text((120, 120 + 90 * i), satir, fill=(20, 20, 20), font=font)
    img.save(yol, bicim, **({"quality": 80} if bicim == "JPEG" else {"resolution": 200}))


@pytest.mark.parametrize("uzanti, bicim", [(".jpg", "JPEG"), (".pdf", "PDF")])
def test_taranmis_belge_maskelenir_ve_goruntuye_basilir(tmp_path, motor, uzanti, bicim):
    kaynak = tmp_path / f"tarama{uzanti}"
    _tarama(kaynak, bicim)
    belge = belgeler.ac(kaynak)
    assert belge.ocr and belge.cikti_uzantisi == ".pdf"
    sonuc = maskele_belge(belge, motor, Kasa())
    for deger in ("Şebnem", "12345678950", "Barbaros", "Harrow", "U12345678"):
        assert deger not in sonuc.maskeli_metin, (deger, sonuc.maskeli_metin)

    hedef = tmp_path / "maskeli.pdf"
    belge.yaz(sonuc.degisiklikler, hedef)
    # Maskeli PDF yalnız görüntüdür: metin katmanı yoktur ve yeniden OCR'da gerçek değer çıkmaz.
    from pypdf import PdfReader
    assert not (PdfReader(str(hedef)).pages[0].extract_text() or "").strip()
    yeniden = belgeler.ac(hedef)
    for deger in ("12345678950", "U12345678", "Barbaros"):
        assert deger not in yeniden.metin, (deger, yeniden.metin)

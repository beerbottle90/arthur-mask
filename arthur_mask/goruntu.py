"""Metin katmanı olmayan taranmış PDF'ler ve belge fotoğrafları: yerel OCR + görüntüde maskeleme.

Akış:
1. Sayfa görüntüsü: PDF → pypdfium2 (Apache/BSD) ile 200 DPI; JPEG/PNG/TIFF → Pillow.
2. OCR: RapidOCR PP-OCRv6 çok dilli (Apache-2.0, ONNX; Türkçe ve İngilizce Latin harfleri).
   Satır kutuları ve sözcük kutuları alınır; metin satır sırasıyla birleştirilir.
3. Metin mevcut motorla maskelenir; etiketli metin Claude'a gider.
4. Maskeli görüntü: kişisel veri sözcüklerinin kutuları piksellere kalıcı olarak basılır
   (üst üste bindirme değil), yeni görüntü üstverisiz (EXIF/GPS/XMP yok) PNG olarak yazılır.

Sınırlar: el yazısı, imza, mühür, fotoğraf ve karekod OCR ile okunmaz; bu yüzden OCR ile
okunan her belge istisna sayılır ve avukat incelemesi zorunludur.
"""

import io
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

gunluk = logging.getLogger("arthur_mask.goruntu")

GORUNTU_UZANTILARI = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp")
PDF_DPI = 200
KUTU_PAYI = 3
ETIKET_ZEMIN = (244, 239, 227)
ETIKET_CERCEVE = (15, 26, 43)


class OcrHatasi(Exception):
    pass


def ocr_kullanilabilir_mi() -> bool:
    try:
        import pypdfium2  # noqa: F401
        from rapidocr import RapidOCR  # noqa: F401
    except ImportError:
        return False
    return True


@dataclass
class Sozcuk:
    metin: str
    kutu: Tuple[int, int, int, int]  # x0, y0, x1, y1
    bas: int = 0  # sayfa metnindeki karakter ofseti
    son: int = 0
    satir: int = 0  # OCR satır sırası
    satir_kutusu: Tuple[int, int, int, int] = (0, 0, 0, 0)


@dataclass
class Sayfa:
    goruntu: "object"  # PIL.Image
    sozcukler: List[Sozcuk] = field(default_factory=list)
    metin: str = ""
    guven: float = 0.0


def sayfa_goruntuleri(yol: Path) -> List["object"]:
    from PIL import Image, ImageOps

    uzanti = yol.suffix.lower()
    if uzanti == ".pdf":
        import pypdfium2 as pdfium

        belge = pdfium.PdfDocument(str(yol))
        try:
            return [belge[i].render(scale=PDF_DPI / 72).to_pil().convert("RGB") for i in range(len(belge))]
        finally:
            belge.close()
    goruntu = Image.open(yol)
    sayfalar = []
    for i in range(getattr(goruntu, "n_frames", 1)):
        goruntu.seek(i)
        sayfalar.append(ImageOps.exif_transpose(goruntu.copy()).convert("RGB"))
    return sayfalar


class OcrMotoru:
    def __init__(self, model_boyu: str = "small"):
        from rapidocr import EngineType, ModelType, OCRVersion, RapidOCR

        boy = {"tiny": ModelType.TINY, "small": ModelType.SMALL, "medium": ModelType.MEDIUM}[model_boyu]
        # PP-OCRv6 tek çok dilli modeldir (multi_PP-OCRv6_*); dil parametresi yok sayılır.
        self._ocr = RapidOCR(params={
            "Global.log_level": "error",
            "Global.return_word_box": True,
            "Det.engine_type": EngineType.ONNXRUNTIME, "Det.model_type": boy, "Det.ocr_version": OCRVersion.PPOCRV6,
            "Rec.engine_type": EngineType.ONNXRUNTIME, "Rec.model_type": boy, "Rec.ocr_version": OCRVersion.PPOCRV6,
        })

    def oku(self, goruntu) -> Sayfa:
        import numpy as np

        sonuc = self._ocr(np.asarray(goruntu))
        if sonuc is None or sonuc.boxes is None or not len(sonuc.boxes):
            return Sayfa(goruntu)
        satirlar = []
        kelime_sonuclari = getattr(sonuc, "word_results", None) or [None] * len(sonuc.boxes)
        for kutu, metin, skor, kelimeler in zip(sonuc.boxes, sonuc.txts, sonuc.scores, kelime_sonuclari):
            xs, ys = [p[0] for p in kutu], [p[1] for p in kutu]
            satirlar.append((min(ys), min(xs), (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))), metin, skor, kelimeler))
        # Üstten alta, aynı satırda soldan sağa (satır yüksekliğinin yarısı tolerans).
        satirlar.sort(key=lambda s: (round(s[0] / max(8, (s[2][3] - s[2][1]) * 0.6)), s[1]))

        sayfa = Sayfa(goruntu, guven=float(sum(s[4] for s in satirlar) / len(satirlar)))
        parcalar, imlec = [], 0
        for sira, (_, _, satir_kutusu, metin, _, kelimeler) in enumerate(satirlar):
            for sozcuk in _sozcuklere_bol(metin, satir_kutusu, kelimeler):
                bas = metin.find(sozcuk.metin, max(0, sozcuk.bas))
                bas = bas if bas >= 0 else sozcuk.bas
                sozcuk.bas, sozcuk.son = imlec + bas, imlec + bas + len(sozcuk.metin)
                sozcuk.satir, sozcuk.satir_kutusu = sira, satir_kutusu
                sayfa.sozcukler.append(sozcuk)
            parcalar.append(metin)
            imlec += len(metin) + 1
        sayfa.metin = "\n".join(parcalar)
        return sayfa


def _sozcuklere_bol(metin: str, satir_kutusu, kelimeler) -> List[Sozcuk]:
    """OCR sözcük kutuları varsa onları, yoksa karakter genişliği oranıyla yaklaşık kutuları kullanır."""
    sozcukler: List[Sozcuk] = []
    if kelimeler:
        imlec = 0
        for oge in kelimeler:
            kelime, _, kutu = oge[0], oge[1], oge[2]
            xs, ys = [p[0] for p in kutu], [p[1] for p in kutu]
            bas = metin.find(kelime, imlec)
            if bas < 0:
                bas = imlec
            sozcukler.append(Sozcuk(kelime, (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))), bas, bas + len(kelime)))
            imlec = bas + len(kelime)
        if sozcukler:
            return sozcukler
    x0, y0, x1, y1 = satir_kutusu
    genislik = (x1 - x0) / max(1, len(metin))
    import re

    for m in re.finditer(r"\S+", metin):
        sozcukler.append(Sozcuk(m.group(), (int(x0 + m.start() * genislik), y0, int(x0 + m.end() * genislik), y1), m.start(), m.end()))
    return sozcukler


def maskeli_goruntu(sayfa: Sayfa, degisiklikler: Sequence[Tuple[int, int, str]], sayfa_basi: int = 0):
    """Değişiklik aralıklarına denk gelen sözcükleri piksellere kalıcı olarak basar.

    Aynı OCR satırındaki sözcükler tek kutuda birleşir. OCR sözcük kutuları dar ve taramada
    kaymalı olabildiği için kutu, satır yüksekliğiyle orantılı payla genişletilir ve dikeyde
    satır kutusunun tamamını kaplar (harf kenarı sızmasın). Etiket kutuya sığacak biçimde
    küçültülür ve kutu içine kırpılarak basılır.
    """
    from PIL import Image, ImageDraw

    temiz = Image.new("RGB", sayfa.goruntu.size)
    temiz.paste(sayfa.goruntu)  # üstveri taşımayan yeni görüntü
    ciz = ImageDraw.Draw(temiz)
    genislik, yukseklik = temiz.size
    for bas, son, etiket in degisiklikler:
        bas, son = bas - sayfa_basi, son - sayfa_basi
        satirlar = {}
        for s in sayfa.sozcukler:
            if s.bas < son and bas < s.son:
                satirlar.setdefault(s.satir, []).append(s)
        for sira, (satir_no, sozcukler) in enumerate(sorted(satirlar.items())):
            x0 = min(s.kutu[0] for s in sozcukler)
            x1 = max(s.kutu[2] for s in sozcukler)
            sy0, sy1 = sozcukler[0].satir_kutusu[1], sozcukler[0].satir_kutusu[3]
            y0 = min([sy0] + [s.kutu[1] for s in sozcukler])
            y1 = max([sy1] + [s.kutu[3] for s in sozcukler])
            h = max(8, y1 - y0)
            pay_x, pay_y = max(6, int(h * 0.35)), max(3, int(h * 0.15))
            kutu = (max(0, x0 - pay_x), max(0, y0 - pay_y), min(genislik, x1 + pay_x), min(yukseklik, y1 + pay_y))
            ciz.rectangle(kutu, fill=ETIKET_ZEMIN, outline=ETIKET_CERCEVE, width=2)
            if sira == 0:
                _etiket_bas(temiz, kutu, etiket)
    return temiz


def _etiket_bas(goruntu, kutu, etiket: str) -> None:
    from PIL import Image, ImageDraw, ImageFont

    x0, y0, x1, y1 = kutu
    en, boy = max(1, x1 - x0 - 6), max(1, y1 - y0 - 4)
    boyut = max(8, int(boy * 0.8))
    while True:
        try:
            yazi = ImageFont.truetype("consola.ttf", boyut)
        except OSError:
            yazi = ImageFont.load_default()
            break
        if yazi.getlength(etiket) <= en or boyut <= 9:
            break
        boyut -= 1
    parca = Image.new("RGB", (en, boy), ETIKET_ZEMIN)
    ImageDraw.Draw(parca).text((0, max(0, (boy - boyut) // 2 - 1)), etiket, fill=ETIKET_CERCEVE, font=yazi)
    goruntu.paste(parca, (x0 + 3, y0 + 2))  # kutu içine kırpılmış etiket


def goruntuleri_pdf_yap(goruntuler: Sequence["object"], hedef: Path) -> None:
    """Yalnız görüntüden oluşan, metin katmanı ve üstverisi olmayan PDF."""
    if not goruntuler:
        raise OcrHatasi("Yazılacak sayfa yok.")
    tampon = io.BytesIO()
    ilk, *kalan = goruntuler
    ilk.save(tampon, format="PDF", save_all=True, append_images=list(kalan), resolution=PDF_DPI)
    hedef.write_bytes(tampon.getvalue())


SAYFA_AYRACI = "\n\f\n"
DUSUK_GUVEN = 0.80
_ocr_motoru: Optional[OcrMotoru] = None


def ocr_motoru() -> OcrMotoru:
    global _ocr_motoru
    if _ocr_motoru is None:
        _ocr_motoru = OcrMotoru("small")
    return _ocr_motoru


def ocr_belgesi(yol: Path):
    """(metin, yazıcı, uyarılar): sayfaları OCR ile okur; yazıcı maskeli, görüntü tabanlı PDF üretir."""
    if not ocr_kullanilabilir_mi():
        raise OcrHatasi(
            f"{yol.name} metin katmanı içermiyor ve yerel OCR kurulu değil "
            '(pip install "arthur-mask[ocr]").'
        )
    goruntuler = sayfa_goruntuleri(yol)
    if not goruntuler:
        raise OcrHatasi(f"{yol.name} içinde sayfa bulunamadı.")
    motor = ocr_motoru()
    sayfalar = [motor.oku(g) for g in goruntuler]
    baslar, imlec = [], 0
    for sayfa in sayfalar:
        baslar.append(imlec)
        imlec += len(sayfa.metin) + len(SAYFA_AYRACI)
    metin = SAYFA_AYRACI.join(s.metin for s in sayfalar)
    if not metin.strip(" \n\f"):
        raise OcrHatasi(f"{yol.name} içinde okunabilir metin bulunamadı (boş, el yazısı ya da çok düşük çözünürlük).")

    ortalama = sum(s.guven for s in sayfalar if s.metin) / max(1, sum(1 for s in sayfalar if s.metin))
    uyarilar = [
        f"Belge yerel OCR ile okundu ({len(sayfalar)} sayfa, ortalama güven %{ortalama * 100:.0f}). "
        "El yazısı, imza, mühür, fotoğraf ve karekod okunmaz ve MASKELENMEZ: maskeli kopyayı açıp kontrol edin.",
    ]
    zayif = [str(i + 1) for i, s in enumerate(sayfalar) if not s.metin or s.guven < DUSUK_GUVEN]
    if zayif:
        uyarilar.append(f"Okuma güveni düşük ya da metinsiz sayfalar: {', '.join(zayif)}.")

    def yazici(degisiklikler, hedef: Path) -> None:
        maskeli = []
        for sayfa, bas in zip(sayfalar, baslar):
            son = bas + len(sayfa.metin)
            ilgili = [d for d in degisiklikler if d[0] < son and bas < d[1]]
            maskeli.append(maskeli_goruntu(sayfa, ilgili, sayfa_basi=bas))
        goruntuleri_pdf_yap(maskeli, hedef)

    return metin, yazici, uyarilar

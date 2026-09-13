"""PDF metin katmanını okuma.

Yapay zekâya giden şey metindir; bu nedenle PDF'in metin katmanı çıkarılır,
maskelenir ve metin / DOCX / UDF olarak yazılır. Maskeli çıktı PDF değildir:
sayfa düzenini koruyan görsel karartma (redaction) ayrı bir iştir ve
alttaki metni gerçekten silmeyen araçlar sızıntıya yol açar.

Taranmış (görüntü) PDF'lerde metin katmanı yoktur. Sessizce boş çıktı üretmek
yerine hata verilir: OCR (ör. Tesseract `tur`) ile metin katmanı oluşturulmalıdır.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from pypdf import PdfReader
from pypdf.errors import PdfReadError

SAYFA_AYRACI = "\n\f\n"
MIN_KARAKTER_SAYFA_BASI = 25


class PdfHatasi(Exception):
    pass


@dataclass
class PdfBelge:
    metin: str
    sayfa_sayisi: int
    uyarilar: List[str] = field(default_factory=list)


def oku(yol: Path) -> PdfBelge:
    try:
        okuyucu = PdfReader(str(yol))
    except PdfReadError as hata:
        raise PdfHatasi(f"{yol} okunamadı: {hata}") from hata
    if okuyucu.is_encrypted:
        raise PdfHatasi(f"{yol} parolalı; önce parolasını kaldırın.")

    sayfalar = [(sayfa.extract_text() or "").replace("\r\n", "\n") for sayfa in okuyucu.pages]
    bos = [i + 1 for i, s in enumerate(sayfalar) if len(s.strip()) < MIN_KARAKTER_SAYFA_BASI]
    if len(bos) == len(sayfalar):
        raise PdfHatasi(
            f"{yol} metin katmanı içermiyor (taranmış belge). OCR ile metin katmanı oluşturmadan maskelenemez."
        )
    uyarilar = ["Maskeli çıktı PDF değil, metindir; özgün PDF'in kendisi gönderilmez."]
    if bos:
        uyarilar.append(
            f"Metni olmayan sayfalar: {', '.join(map(str, bos))}. Taranmış sayfa olabilir; bu sayfalardaki veri MASKELENMEDİ."
        )
    return PdfBelge(SAYFA_AYRACI.join(sayfalar), len(sayfalar), uyarilar)

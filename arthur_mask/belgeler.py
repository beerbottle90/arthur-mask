"""Biçimden bağımsız belge arayüzü: .udf, .docx, .pdf, .txt, .md ve taranmış görüntüler (OCR)."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from . import docx, goruntu, pdf, udf
from .maskeleyici import Degisiklik, degisiklikleri_uygula

DESTEKLENEN = (".udf", ".docx", ".pdf", ".txt", ".md") + goruntu.GORUNTU_UZANTILARI


class BelgeHatasi(Exception):
    pass


@dataclass
class Belge:
    yol: Path
    metin: str
    uyarilar: List[str] = field(default_factory=list)
    # Biçimi koruyarak yazan işlev; yoksa (PDF) çıktı düz metindir.
    _yazici: Optional[Callable[[Sequence[Degisiklik], Path], None]] = None
    # OCR ile okunan belge: maskeli çıktı görüntü tabanlı PDF'tir ve inceleme zorunludur.
    ocr: bool = False

    @property
    def cikti_uzantisi(self) -> str:
        if self.ocr:
            return ".pdf"
        return self.yol.suffix.lower() if self._yazici else ".txt"

    def yaz(self, degisiklikler: Sequence[Degisiklik], hedef: Path) -> None:
        if self._yazici:
            self._yazici(degisiklikler, hedef)
        else:
            hedef.write_text(degisiklikleri_uygula(self.metin, degisiklikler), encoding="utf-8")


def ac(yol: Path) -> Belge:
    yol = Path(yol)
    uzanti = yol.suffix.lower()
    try:
        if uzanti == ".udf":
            b = udf.oku(yol)
            return Belge(yol, b.metin, [], lambda d, h: udf.maskelenmis_yaz(b, d, h))
        if uzanti == ".docx":
            b = docx.oku(yol)
            return Belge(yol, b.metin, b.uyarilar, lambda d, h: docx.maskelenmis_yaz(b, d, h))
        if uzanti == ".pdf":
            try:
                b = pdf.oku(yol)
            except pdf.PdfHatasi as hata:
                if "OCR" not in str(hata):
                    raise
                return _ocr_ile_ac(yol)
            if b.bos_sayfalar and goruntu.ocr_kullanilabilir_mi():
                return _ocr_ile_ac(yol)  # karışık PDF: taranmış sayfalar da okunsun
            return Belge(yol, b.metin, b.uyarilar, None)
        if uzanti in goruntu.GORUNTU_UZANTILARI:
            return _ocr_ile_ac(yol)
        if uzanti in (".txt", ".md"):
            metin = yol.read_text(encoding="utf-8")
            return Belge(yol, metin, [], lambda d, h: h.write_text(degisiklikleri_uygula(metin, d), encoding="utf-8"))
    except (udf.UdfHatasi, docx.DocxHatasi, pdf.PdfHatasi, goruntu.OcrHatasi) as hata:
        raise BelgeHatasi(str(hata)) from hata
    if uzanti == ".doc":
        raise BelgeHatasi("Word 97-2003 (.doc) desteklenmez; belgeyi .docx olarak kaydedin.")
    raise BelgeHatasi(f"Desteklenmeyen biçim: {uzanti} (desteklenen: {', '.join(DESTEKLENEN)})")


def _ocr_ile_ac(yol: Path) -> Belge:
    metin, yazici, uyarilar = goruntu.ocr_belgesi(yol)
    return Belge(yol, metin, uyarilar, yazici, ocr=True)


def markdown_sadelestir(metin: str) -> str:
    """UYAP editörü tablo ve biçim işaretlerini desteklemediği için Markdown sade metne iner."""
    import re

    satirlar = []
    for satir in metin.split("\n"):
        if re.match(r"^\|?\s*:?-{3,}", satir.strip()):
            continue
        if satir.lstrip().startswith("|"):
            hucreler = [h.strip() for h in satir.strip().strip("|").split("|")]
            satir = "    ".join(h.replace("<br>", " ") for h in hucreler)
        satir = re.sub(r"^#{1,6}\s+", "", satir)
        satir = re.sub(r"^\s*[-*]\s+", "• ", satir)
        satirlar.append(satir.replace("**", ""))
    return "\n".join(satirlar)


def metinden_yaz(metin: str, hedef: Path) -> None:
    """Metni hedef uzantıya göre UDF, DOCX veya metin olarak yazar (DOCX'te Markdown yapısı korunur)."""
    uzanti = hedef.suffix.lower()
    if uzanti == ".udf":
        udf.metinden_udf(markdown_sadelestir(metin), hedef)
    elif uzanti == ".docx":
        docx.metinden_docx(metin, hedef)
    else:
        hedef.write_text(metin, encoding="utf-8")

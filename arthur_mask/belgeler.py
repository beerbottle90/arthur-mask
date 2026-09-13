"""Biçimden bağımsız belge arayüzü: .udf, .docx, .pdf, .txt, .md"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from . import docx, pdf, udf
from .maskeleyici import Degisiklik, degisiklikleri_uygula

DESTEKLENEN = (".udf", ".docx", ".pdf", ".txt", ".md")


class BelgeHatasi(Exception):
    pass


@dataclass
class Belge:
    yol: Path
    metin: str
    uyarilar: List[str] = field(default_factory=list)
    # Biçimi koruyarak yazan işlev; yoksa (PDF) çıktı düz metindir.
    _yazici: Optional[Callable[[Sequence[Degisiklik], Path], None]] = None

    @property
    def cikti_uzantisi(self) -> str:
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
            b = pdf.oku(yol)
            return Belge(yol, b.metin, b.uyarilar, None)
        if uzanti in (".txt", ".md"):
            metin = yol.read_text(encoding="utf-8")
            return Belge(yol, metin, [], lambda d, h: h.write_text(degisiklikleri_uygula(metin, d), encoding="utf-8"))
    except (udf.UdfHatasi, docx.DocxHatasi, pdf.PdfHatasi) as hata:
        raise BelgeHatasi(str(hata)) from hata
    if uzanti == ".doc":
        raise BelgeHatasi("Word 97-2003 (.doc) desteklenmez; belgeyi .docx olarak kaydedin.")
    raise BelgeHatasi(f"Desteklenmeyen biçim: {uzanti} (desteklenen: {', '.join(DESTEKLENEN)})")


def metinden_yaz(metin: str, hedef: Path) -> None:
    """Düz metni hedef uzantıya göre UDF, DOCX veya metin olarak yazar."""
    uzanti = hedef.suffix.lower()
    if uzanti == ".udf":
        udf.metinden_udf(metin, hedef)
    elif uzanti == ".docx":
        docx.metinden_docx(metin, hedef)
    else:
        hedef.write_text(metin, encoding="utf-8")

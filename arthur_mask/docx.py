"""Word (.docx) okuma ve biçimi koruyarak maskeleme.

Word metni paragraf içinde birden çok `<w:t>` düğümüne (run) bölünür; yazım
denetimi veya biçim değişikliği bir adı iki düğüme ayırabilir. Bu modül bütün
metin parçalarını tek bir analiz metninde birleştirir, değişiklikleri düğümlere
geri dağıtır ve XML'in geri kalanına dokunmaz (ElementTree ile yeniden
serileştirme Word'ün ad alanı önekleri nedeniyle dosyayı bozabilir).

Taranan parçalar: gövde, üst/alt bilgi, dipnot/son not, yorumlar; izlenen
değişikliklerdeki silinmiş metin (`w:delText`) de maskelenir. Üstveri
(yazar, son değiştiren, şirket) temizlenir; e-posta köprüleri maskelenir.
"""

import html
import re
import zipfile
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from .maskeleyici import Degisiklik

_PARCA = re.compile(r"^word/(document|header\d*|footer\d*|footnotes|endnotes|comments)\.xml$")
_BELIRTEC = re.compile(
    r"(?P<pkapa></w:p>)"
    r"|(?P<metin><w:(?:t|delText)\b[^>]*>)(?P<icerik>[^<]*)</w:(?:t|delText)>"
    r"|(?P<sekme><w:tab/>|<w:ptab\b[^>]*/>)"
    r"|(?P<satir><w:br\b[^>]*/>|<w:cr/>)"
)
_CORE_TEMIZLE = re.compile(r"(<(dc:creator|cp:lastModifiedBy|cp:keywords|dc:description|dc:subject|dc:title)(?:\s[^>]*)?>)[^<]*(</\2>)")
_APP_TEMIZLE = re.compile(r"(<(Company|Manager)>)[^<]*(</\2>)")
_MAILTO = re.compile(r'(Target=")mailto:[^"]*(")')
XML_GECERSIZ = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


class DocxHatasi(Exception):
    pass


@dataclass
class _Dugum:
    parca: str
    xml_bas: int
    xml_son: int
    metin_bas: int
    metin: str

    @property
    def metin_son(self) -> int:
        return self.metin_bas + len(self.metin)


@dataclass
class DocxBelge:
    girdiler: List[Tuple[zipfile.ZipInfo, bytes]]
    parcalar: Dict[str, str]
    dugumler: List[_Dugum]
    metin: str
    uyarilar: List[str] = field(default_factory=list)


def oku(yol: Path) -> DocxBelge:
    try:
        with zipfile.ZipFile(yol) as zf:
            girdiler = [(bilgi, zf.read(bilgi)) for bilgi in zf.infolist()]
    except zipfile.BadZipFile as hata:
        raise DocxHatasi(f"{yol} geçerli bir .docx değil (Word 97-2003 .doc ise .docx olarak kaydedin).") from hata

    adlar = [b.filename for b, _ in girdiler]
    if "word/document.xml" not in adlar:
        raise DocxHatasi(f"{yol} içinde word/document.xml yok.")
    sirali = sorted((a for a in adlar if _PARCA.match(a)), key=lambda a: (a != "word/document.xml", a))
    icerik = dict((b.filename, v) for b, v in girdiler)

    parcalar, dugumler, metin_parcalari, imlec = {}, [], [], 0
    for ad in sirali:
        xml = icerik[ad].decode("utf-8")
        parcalar[ad] = xml
        for m in _BELIRTEC.finditer(xml):
            if m.group("metin"):
                duz = html.unescape(m.group("icerik"))
                dugumler.append(_Dugum(ad, m.start("icerik"), m.end("icerik"), imlec, duz))
                metin_parcalari.append(duz)
                imlec += len(duz)
            else:
                ayrac = "\t" if m.group("sekme") else "\n"
                metin_parcalari.append(ayrac)
                imlec += 1
        metin_parcalari.append("\n")
        imlec += 1

    uyarilar = []
    govde = parcalar["word/document.xml"]
    if "<w:del " in govde or "<w:ins " in govde:
        uyarilar.append("Belgede izlenen değişiklikler var; silinmiş metin de maskelendi, yine de göndermeden önce değişiklikleri kabul edin.")
    if "word/comments.xml" in parcalar:
        uyarilar.append("Belgede yorumlar var; yorum metni maskelendi, gerekmiyorsa yorumları silin.")
    if any(a.startswith("word/media/") for a in adlar):
        uyarilar.append("Belgede görsel var (imza, kimlik fotokopisi vb.); görseller MASKELENMEZ.")
    if any(a.startswith("word/embeddings/") for a in adlar):
        uyarilar.append("Belgede gömülü nesne var; gömülü dosyalar MASKELENMEZ.")
    return DocxBelge(girdiler, parcalar, dugumler, "".join(metin_parcalari), uyarilar)


def _dugum_metinleri(belge: DocxBelge, degisiklikler: Sequence[Degisiklik]) -> List[str]:
    yeni = [d.metin for d in belge.dugumler]
    baslar = [d.metin_bas for d in belge.dugumler]
    # Sondan başa: önceki değişikliklerin düğüm içi konumları bozulmasın.
    for bas, son, deger in sorted(degisiklikler, reverse=True):
        i = max(bisect_right(baslar, bas) - 1, 0)
        ilgili = []
        while i < len(belge.dugumler) and belge.dugumler[i].metin_bas < son:
            if belge.dugumler[i].metin_son > bas:
                ilgili.append(i)
            i += 1
        if not ilgili:
            continue
        for sira, j in enumerate(ilgili):
            d = belge.dugumler[j]
            yerel_bas = max(bas - d.metin_bas, 0)
            yerel_son = min(son - d.metin_bas, len(d.metin))
            ek = deger if sira == 0 else ""
            yeni[j] = yeni[j][:yerel_bas] + ek + yeni[j][yerel_son:]
    return yeni


def _xml_space_ekle(xml: str, metin_bas: int) -> str:
    """Değişen metin boşlukla başlıyor/bitiyorsa `xml:space="preserve"` gerekir."""
    etiket_bas = xml.rfind("<w:", 0, metin_bas)
    etiket = xml[etiket_bas:metin_bas]
    if "xml:space" in etiket:
        return xml
    return xml[:metin_bas - 1] + ' xml:space="preserve"' + xml[metin_bas - 1:]


def maskelenmis_yaz(belge: DocxBelge, degisiklikler: Sequence[Degisiklik], hedef: Path, ustveri_temizle: bool = True) -> None:
    yeni_metinler = _dugum_metinleri(belge, degisiklikler)
    parcalar = dict(belge.parcalar)
    for j in range(len(belge.dugumler) - 1, -1, -1):
        d = belge.dugumler[j]
        if yeni_metinler[j] == d.metin:
            continue
        xml = parcalar[d.parca]
        kacisli = html.escape(XML_GECERSIZ.sub("", yeni_metinler[j]), quote=False)
        xml = xml[:d.xml_bas] + kacisli + xml[d.xml_son:]
        if kacisli != kacisli.strip():
            xml = _xml_space_ekle(xml, d.xml_bas)
        parcalar[d.parca] = xml

    gecici = Path(str(hedef) + ".tmp")
    with zipfile.ZipFile(gecici, "w", zipfile.ZIP_DEFLATED) as zf:
        for bilgi, veri in belge.girdiler:
            ad = bilgi.filename
            if ad in parcalar:
                veri = parcalar[ad].encode("utf-8")
            elif ustveri_temizle and ad == "docProps/core.xml":
                veri = _CORE_TEMIZLE.sub(r"\1\3", veri.decode("utf-8")).encode("utf-8")
            elif ustveri_temizle and ad == "docProps/app.xml":
                veri = _APP_TEMIZLE.sub(r"\1\3", veri.decode("utf-8")).encode("utf-8")
            elif ustveri_temizle and ad.endswith(".rels"):
                veri = _MAILTO.sub(r"\1mailto:maskeli@example.invalid\2", veri.decode("utf-8")).encode("utf-8")
            zf.writestr(bilgi, veri)
    gecici.replace(hedef)


_ICERIK_TURLERI = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>"""
_ILISKILER = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>"""


_YAZI = '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman"/>'
_TABLO_AYRAC = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def _runlar(metin: str, boyut: int = 24, kalin: bool = False) -> str:
    """Satır içi **kalın** işaretini Word run'larına çevirir."""
    metin = XML_GECERSIZ.sub("", metin)
    runlar = []
    for i, parca in enumerate(re.split(r"\*\*(.+?)\*\*", metin)):
        if not parca:
            continue
        rpr = f"<w:rPr>{_YAZI}{'<w:b/>' if kalin or i % 2 else ''}<w:sz w:val=\"{boyut}\"/></w:rPr>"
        runlar.append(f'<w:r>{rpr}<w:t xml:space="preserve">{html.escape(parca, quote=False)}</w:t></w:r>')
    return "".join(runlar)


def _paragraf(metin: str, boyut: int = 24, kalin: bool = False, girinti: int = 0) -> str:
    ppr = f'<w:pPr><w:ind w:left="{girinti}" w:hanging="{min(girinti, 283)}"/></w:pPr>' if girinti else ""
    return f"<w:p>{ppr}{_runlar(metin, boyut, kalin)}</w:p>"


def _tablo(satirlar) -> str:
    sutun = max(len(s) for s in satirlar)
    genislik = int(9638 / sutun)  # A4 metin alanı (twip)
    kenar = "".join(f'<w:{k} w:val="single" w:sz="4" w:space="0" w:color="999999"/>'
                    for k in ("top", "left", "bottom", "right", "insideH", "insideV"))
    xml = [f'<w:tbl><w:tblPr><w:tblW w:w="5000" w:type="pct"/><w:tblBorders>{kenar}</w:tblBorders>'
           '<w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid>'
           + f'<w:gridCol w:w="{genislik}"/>' * sutun + "</w:tblGrid>"]
    for no, satir in enumerate(satirlar):
        xml.append("<w:tr>")
        for hucre in satir + [""] * (sutun - len(satir)):
            paragraflar = "".join(_paragraf(p.strip(), 22, kalin=False)
                                  for p in re.split(r"<br\s*/?>", hucre)) or "<w:p/>"
            xml.append(f'<w:tc><w:tcPr><w:tcW w:w="{genislik}" w:type="dxa"/></w:tcPr>{paragraflar}</w:tc>')
        xml.append("</w:tr>")
    xml.append("</w:tbl><w:p/>")
    return "".join(xml)


def _tablo_satiri(satir: str):
    icerik = satir.strip()
    if icerik.startswith("|"):
        icerik = icerik[1:]
    if icerik.endswith("|") and not icerik.endswith("\|"):
        icerik = icerik[:-1]
    return [h.replace("\|", "|").strip() for h in re.split(r"(?<!\)\|", icerik)]


def metinden_docx(metin: str, hedef: Path) -> None:
    """Metinden .docx üretir. Markdown yapısı Word yapısına çevrilir:
    tablolar (| a | b |) gerçek tablo, # başlıklar, - / 1. listeler, **kalın**, \f sayfa sonu.
    Markdown olmayan satırlar olduğu gibi (baştaki boşluklar korunarak) paragraf olur.
    """
    satirlar = metin.replace("\r\n", "\n").split("\n")
    govde_parcalari, i = [], 0
    while i < len(satirlar):
        satir = satirlar[i]
        if satir == "\f":
            govde_parcalari.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
            i += 1
            continue
        # Tablo: ardışık | satırları; ikinci satır ayraçsa başlık satırı kabul edilir.
        if satir.lstrip().startswith("|") and i + 1 < len(satirlar) and (
            _TABLO_AYRAC.match(satirlar[i + 1]) or satirlar[i + 1].lstrip().startswith("|")
        ):
            tablo = []
            while i < len(satirlar) and satirlar[i].lstrip().startswith("|"):
                if not _TABLO_AYRAC.match(satirlar[i]):
                    tablo.append(_tablo_satiri(satirlar[i]))
                i += 1
            if tablo:
                govde_parcalari.append(_tablo(tablo))
            continue
        baslik = re.match(r"^(#{1,6})\s+(.*)$", satir)
        liste = re.match(r"^\s*[-*•]\s+(.*)$", satir)
        if baslik:
            duzey = len(baslik.group(1))
            govde_parcalari.append(_paragraf(baslik.group(2), boyut=max(24, 34 - 3 * duzey), kalin=True))
        elif liste:
            govde_parcalari.append(_paragraf("• " + liste.group(1), girinti=567))
        else:
            govde_parcalari.append(_paragraf(satir) if satir else "<w:p/>")
        i += 1
    govde = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
        + "".join(govde_parcalari)
        + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" '
        'w:header="709" w:footer="709" w:gutter="0"/></w:sectPr></w:body></w:document>'
    )
    with zipfile.ZipFile(hedef, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _ICERIK_TURLERI)
        zf.writestr("_rels/.rels", _ILISKILER)
        zf.writestr("word/document.xml", govde)

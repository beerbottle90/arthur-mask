"""Word (.docx) okuma ve biçimi koruyarak maskeleme.

Word metni paragraf içinde birden çok `<w:t>` düğümüne (run) bölünür; yazım
denetimi veya biçim değişikliği bir adı iki düğüme ayırabilir. Bu modül bütün
metin parçalarını tek bir analiz metninde birleştirir, değişiklikleri düğümlere
geri dağıtır ve XML'in geri kalanına dokunmaz (ElementTree ile yeniden
serileştirme Word'ün ad alanı önekleri nedeniyle dosyayı bozabilir).

Taranan parçalar: gövde, üst/alt bilgi, dipnot/son not, yorumlar; izlenen
değişikliklerdeki silinmiş metin (`w:delText`) de maskelenir.

Maskeli kopyada üstveri de temizlenir: belge özellikleri (yazar, son değiştiren, şirket, başlık,
özel özellikler), yorum ve izli değişiklik yazarları ("Yazar 1", "Yazar 2"), kişi listesi
(`people.xml`), belge değişkenleri, görsellerin alternatif metni, küçük resim ve dış bağlantılar
(yerel yol, şablon, e-posta). Gövdede maskelenen gerçek değerler gövde dışında geçtiği yerlerde de
(alan kodu, içerik denetimine bağlı veri, grafik, yapı taşı) etiketine çevrilir.
"""

import html
import re
import xml.etree.ElementTree as ET
import zipfile
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Sequence, Tuple
from urllib.parse import unquote

from .cikis import CikisDenetimi, normallestir
from .kasa import Kasa
from .maskeleyici import Degisiklik
from .sinirlar import arsiv_oku

_PARCA = re.compile(r"^word/(document|header\d*|footer\d*|footnotes|endnotes|comments)\.xml$")
_BELIRTEC = re.compile(
    r"(?P<pkapa></w:p>)"
    r"|(?P<metin><w:(?:t|delText)\b[^>]*>)(?P<icerik>[^<]*)</w:(?:t|delText)>"
    r"|(?P<sekme><w:tab/>|<w:ptab\b[^>]*/>)"
    r"|(?P<satir><w:br\b[^>]*/>|<w:cr/>)"
)
_CORE_TEMIZLE = re.compile(r"(<(dc:creator|cp:lastModifiedBy|cp:keywords|dc:description|dc:subject|dc:title|"
                           r"cp:category|cp:contentStatus|dc:identifier)(?:\s[^>]*)?>)[^<]*(</\2>)")
_APP_TEMIZLE = re.compile(r"(<(Company|Manager|HyperlinkBase|Template)>)[^<]*(</\2>)")
_APP_BASLIKLAR = re.compile(r"<TitlesOfParts>.*?</TitlesOfParts>", re.S)
_VT_METIN = re.compile(r"(<vt:lpw?str>)[^<]*(</vt:lpw?str>)")
_OZEL_OZELLIK = re.compile(r"<(?:\w+:)?property\b.*?</(?:\w+:)?property>", re.S)
_BELGE_DEGISKENLERI = re.compile(r"<w:docVars\b(?:[^>]*/>|.*?</w:docVars>)", re.S)
_YAZAR = re.compile(r'(\s(?:w|w15):author=")([^"]*)(")')
_BAS_HARFLER = re.compile(r'(\sw:initials=")[^"]*(")')
_KISI_KIMLIGI = re.compile(r'(\sw15:(?:userId|providerId)=")[^"]*(")')
_ALT_METNI_OLAN = re.compile(r"<(?:\w+:)?(?:docPr|cNvPr|shape|imagedata)\b[^>]*>")
_ALT_METIN = re.compile(r'(\s(?:descr|title|alt|o:title)=")[^"]*(")')
_ALAN_KODU = re.compile(r"(<w:instrText\b[^>]*>)([^<]*)(</w:instrText>)")
_OZNITELIK_METNI = re.compile(r'(\s(?:w:instr|w:tooltip)=")([^"]*)(")')
_METIN_DUGUMU = re.compile(r">([^<]+)<")
_ILISKI = re.compile(r"<Relationship\b[^>]*>")
_HEDEF = re.compile(r'(\sTarget=")([^"]*)(")')
_KUCUK_RESIM = re.compile(r"^docProps/thumbnail\.\w+$")
XML_GECERSIZ = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _xml_metni(xml: str) -> str:
    """Bir parçanın metni, Claude görünümünü üreten ayrıştırıcının (ElementTree) gördüğü gibi."""
    kok = ET.fromstring(xml.encode("utf-8"))
    return "".join(d.text or "" for d in kok.iter() if d.tag in (_W + "t", _W + "delText"))


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
            girdiler = arsiv_oku(zf, yol.name, DocxHatasi)
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
        # Maskeleme bu düz kalıpla okur, Claude'a giden görünüm ElementTree ile. Word dışı bir programın yazdığı
        # dosyada (başka ad alanı öneki, CDATA, varlık tanımı) ikisi farklı metin görür ve kalıbın görmediği metin
        # maskesiz gider. Bu yüzden ikisi aynı metni vermiyorsa belge işlenmez.
        try:
            ayni = _xml_metni(xml).replace("\r", "") == "".join(d.metin for d in dugumler if d.parca == ad).replace("\r", "")
        except ET.ParseError:
            ayni = False
        if not ayni:
            raise DocxHatasi(f"{yol.name} içindeki {ad} alışılmadık biçimde yazılmış (Word dışı bir program üretmiş "
                             "olabilir); güvenle maskelenemiyor. Belgeyi Word'de açıp .docx olarak yeniden kaydedin.")

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


class _Ustveri:
    """Maskeli kopyanın gövde dışı temizliği. `degisiklikler`deki gerçek değer → etiket eşlemesi, gövde dışında
    kalan metne de uygulanır."""

    def __init__(self, belge: DocxBelge, degisiklikler: Sequence[Degisiklik]):
        ciftler: Dict[str, str] = {}
        for bas, son, etiket in degisiklikler:
            deger = belge.metin[bas:son]
            if deger.strip() and deger != etiket:
                ciftler.setdefault(deger, etiket)
        self._denetim = CikisDenetimi(Kasa(), ek_degerler=list(ciftler.items())) if ciftler else None
        sikisik = (re.sub(r"[^0-9a-z]", "", normallestir(d)[0]) for d in ciftler)
        self._url_parcalari = [s for s in sikisik if len(s) >= 5]
        self.yazarlar: Dict[str, str] = {}

    def ort(self, metin: str) -> str:
        return self._denetim.temizle(metin)[0] if self._denetim and metin.strip() else metin

    def _xml_ort(self, ham: str, tirnak: bool) -> str:
        duz = html.unescape(ham)
        yeni = self.ort(duz)
        return ham if yeni == duz else html.escape(yeni, quote=tirnak)

    def _yazar(self, m: re.Match) -> str:
        if not m.group(2):
            return m.group(0)
        takma = self.yazarlar.setdefault(m.group(2), f"Yazar {len(self.yazarlar) + 1}")
        return m.group(1) + takma + m.group(3)

    def kisiler(self, xml: str) -> str:
        """Yazarlar takma adla, baş harfler ve hesap kimlikleri boş; görsellerin alt metni silinir."""
        xml = _YAZAR.sub(self._yazar, xml)
        xml = _BAS_HARFLER.sub(r"\1\2", xml)
        xml = _KISI_KIMLIGI.sub(r"\1\2", xml)
        return _ALT_METNI_OLAN.sub(lambda m: _ALT_METIN.sub(r"\1\2", m.group(0)), xml)

    def govde(self, xml: str) -> str:
        """Gövde parçası (metni zaten maskeli): alan kodları ve ipuçları da etiketlenir."""
        xml = _ALAN_KODU.sub(lambda m: m.group(1) + self._xml_ort(m.group(2), False) + m.group(3), xml)
        xml = _OZNITELIK_METNI.sub(lambda m: m.group(1) + self._xml_ort(m.group(2), True) + m.group(3), xml)
        return self.kisiler(xml)

    def _url_maskeli(self, url: str) -> bool:
        sikisik = re.sub(r"[^0-9a-z]", "", normallestir(unquote(url))[0])
        return any(p in sikisik for p in self._url_parcalari)

    def _iliski(self, m: re.Match) -> str:
        etiket = m.group(0)
        if "/metadata/thumbnail" in etiket:
            return ""  # küçük resim kopyaya alınmaz
        hedef = _HEDEF.search(etiket)
        if not hedef:
            return etiket
        url = html.unescape(hedef.group(2))
        if url.lower().startswith("mailto:"):
            yeni = "mailto:maskeli@example.invalid"
        elif 'TargetMode="External"' not in etiket:
            return etiket
        elif re.match(r"https?://", url, re.I):
            # Web bağlantısı içerik olabilir (mevzuat, karar); yalnız maskelenen bir değeri taşıyorsa değişir.
            if not self._url_maskeli(url):
                return etiket
            yeni = "https://maskeli.invalid/"
        else:
            yeni = "maskeli.invalid"  # yerel yol, ağ paylaşımı, şablon: kullanıcı ve klasör adı taşır
        return etiket[:hedef.start(2)] + html.escape(yeni) + etiket[hedef.end(2):]

    def parca(self, ad: str, veri: bytes) -> bytes:
        if not (ad.endswith(".xml") or ad.endswith(".rels")) or ad == "[Content_Types].xml":
            return veri
        try:
            xml = veri.decode("utf-8")
        except UnicodeDecodeError:
            return veri
        if ad == "docProps/core.xml":
            xml = _CORE_TEMIZLE.sub(r"\1\3", xml)
        elif ad == "docProps/app.xml":
            xml = _APP_TEMIZLE.sub(r"\1\3", xml)
            xml = _APP_BASLIKLAR.sub(lambda m: _VT_METIN.sub(r"\1\2", m.group(0)), xml)
        elif ad == "docProps/custom.xml":
            xml = _OZEL_OZELLIK.sub("", xml)
        elif ad.endswith(".rels"):
            xml = _ILISKI.sub(self._iliski, xml)
        else:
            if ad == "word/settings.xml":
                xml = _BELGE_DEGISKENLERI.sub("", xml)
            # Grafik, SmartArt, içerik denetimi verisi (customXml), yapı taşları: metin düğümleri etiketlenir.
            xml = _METIN_DUGUMU.sub(lambda m: ">" + self._xml_ort(m.group(1), False) + "<", xml)
            xml = self.kisiler(xml)
        return xml.encode("utf-8")


def maskelenmis_yaz(belge: DocxBelge, degisiklikler: Sequence[Degisiklik], hedef: Path, ustveri_temizle: bool = True) -> None:
    ustveri = _Ustveri(belge, degisiklikler) if ustveri_temizle else None
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
            if ustveri and _KUCUK_RESIM.match(ad):
                continue  # ilk sayfanın görüntüsü: gerçek adlar piksel olarak durur
            if ad in parcalar:
                veri = (ustveri.govde(parcalar[ad]) if ustveri else parcalar[ad]).encode("utf-8")
            elif ustveri:
                veri = ustveri.parca(ad, veri)
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
    if icerik.endswith("|") and not icerik.endswith("\\|"):
        icerik = icerik[:-1]
    # Kaçışlı dikey çizgi ("\|") hücre ayıracı değildir.
    return [h.replace("\\|", "|").strip() for h in re.split(r"(?<!\\)\|", icerik)]


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

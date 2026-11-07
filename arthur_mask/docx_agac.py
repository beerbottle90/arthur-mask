"""Word gövdesinin konum korumalı ağacı: bloklar, paragraflar, run'lar ve otomatik numaralandırma.

ElementTree ile yeniden yazmak Word'ün ad alanı öneklerini bozabildiği için (bkz. docx.py) bu modül
`word/document.xml`'i yalnız okur ve her öğenin metindeki başlangıç/bitiş konumunu tutar. Değişiklik
gerekiyorsa (sürüm karşılaştırması) bu konumlara göre metin olarak yapılır; XML'in geri kalanına dokunulmaz.

Paragraf metni "kabul edilmiş" görünümdür: izli silinen metin (`w:del`) alınmaz, izli eklenen alınır.
Metin kutuları (paragraf içindeki çizimlerin kendi paragrafları) paragrafın metnine girmez.
"""

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

_ETIKET = re.compile(
    r"<!--.*?-->|<\?.*?\?>|<!\[CDATA\[.*?\]\]>|<!DOCTYPE[^>]*>"
    r"|<(/?)([^\s/>!?]+)((?:[^>\"']|\"[^\"]*\"|'[^']*')*?)(/?)>",
    re.S,
)
# Run'ları taşıyan, paragraf içi sarmalayıcılar (köprü, içerik denetimi, alan, izli ekleme).
_SARMALAYICI = {"w:hyperlink", "w:smartTag", "w:sdt", "w:sdtContent", "w:fldSimple", "w:customXml",
                "w:ins", "w:moveTo", "w:dir", "w:bdo"}
_BLOK_SARMALAYICI = {"w:sdt", "w:sdtContent", "w:customXml"}


class AgacHatasi(Exception):
    pass


@dataclass(eq=False)
class Oge:
    ad: str
    bas: int
    ic_bas: int
    ic_son: int = -1
    son: int = -1
    ust: Optional["Oge"] = None
    cocuklar: List["Oge"] = field(default_factory=list)

    def cocuk(self, ad: str) -> Optional["Oge"]:
        return next((c for c in self.cocuklar if c.ad == ad), None)

    def torunlar(self, ad: str) -> Iterator["Oge"]:
        for c in self.cocuklar:
            if c.ad == ad:
                yield c
            yield from c.torunlar(ad)

    @property
    def bos(self) -> bool:
        return self.ic_bas == self.son


def agac(xml: str) -> Oge:
    """Konum korumalı ağaç. Kapanmayan ya da yanlış kapanan öğede hoşgörülüdür."""
    kok = Oge("#kok", 0, 0, len(xml), len(xml))
    yigin = [kok]
    for m in _ETIKET.finditer(xml):
        ad = m.group(2)
        if ad is None:
            continue  # yorum, işlem talimatı, CDATA
        if m.group(1):
            if not any(o.ad == ad for o in yigin[1:]):
                continue
            while len(yigin) > 1:
                o = yigin.pop()
                o.ic_son, o.son = m.start(), m.end()
                if o.ad == ad:
                    break
            continue
        oge = Oge(ad, m.start(), m.end(), ust=yigin[-1])
        yigin[-1].cocuklar.append(oge)
        if m.group(4):
            oge.ic_son = oge.son = m.end()
        else:
            yigin.append(oge)
    for o in yigin[1:]:
        o.ic_son = o.son = len(xml)
    return kok


def oznitelik(xml: str, oge: Optional[Oge], ad: str) -> Optional[str]:
    if oge is None:
        return None
    m = re.search(r"\s" + re.escape(ad) + r"\s*=\s*(\"([^\"]*)\"|'([^']*)')", xml[oge.bas:oge.ic_bas])
    if not m:
        return None
    return html.unescape(m.group(2) if m.group(2) is not None else m.group(3))


def icerik(oge: Oge, ad: str) -> Iterator[Oge]:
    """`ad` adlı çocuklar; içerik denetimi (w:sdt) ve customXml sarmalayıcılarının içine de girer."""
    for c in oge.cocuklar:
        if c.ad == ad:
            yield c
        elif c.ad in _BLOK_SARMALAYICI:
            yield from icerik(c, ad)


def bloklar(kap: Oge) -> Iterator[Oge]:
    """Gövde ya da hücredeki paragraf ve tablolar, belge sırasıyla."""
    for c in kap.cocuklar:
        if c.ad in ("w:p", "w:tbl"):
            yield c
        elif c.ad in _BLOK_SARMALAYICI:
            yield from bloklar(c)


def satirlar(tablo: Oge) -> List[Oge]:
    return list(icerik(tablo, "w:tr"))


def hucreler(satir: Oge) -> List[Oge]:
    return list(icerik(satir, "w:tc"))


# -- run ve paragraf modeli ---------------------------------------------------------------------
@dataclass
class Parca:
    """Run içeriğinin bir öğesi: metin (w:t) ya da atom (sekme, satır sonu, alan, çizim, dipnot imi...)."""
    metin_mi: bool
    metin: str
    oge: Oge


@dataclass
class Run:
    oge: Oge
    rpr: str
    parcalar: List[Parca]
    bas: int = 0
    son: int = 0


@dataclass
class Paragraf:
    oge: Oge
    runlar: List[Run]
    metin: str
    sira: int = 0                       # belgedeki paragraf sırası (0'dan)
    tablo: Optional[Tuple[int, int, int]] = None  # (tablo no, satır, sütun), 1'den; iç içe tabloda dıştaki
    numara: Optional[str] = None        # Word'ün otomatik numarası ("7.3.", "(b)"); metinde yazmaz
    baslik: bool = False


def _run_ogeleri(oge: Oge) -> Iterator[Oge]:
    for c in oge.cocuklar:
        if c.ad == "w:r":
            yield c
        elif c.ad in _SARMALAYICI:
            yield from _run_ogeleri(c)


def run_oku(xml: str, r: Oge) -> Run:
    rpr, parcalar = "", []
    for c in r.cocuklar:
        if c.ad == "w:rPr":
            rpr = xml[c.bas:c.son]
        elif c.ad == "w:t":
            parcalar.append(Parca(True, html.unescape(xml[c.ic_bas:c.ic_son]) if not c.bos else "", c))
        elif c.ad in ("w:tab", "w:ptab"):
            parcalar.append(Parca(False, "\t", c))
        elif c.ad in ("w:br", "w:cr"):
            parcalar.append(Parca(False, "\n", c))
        elif c.ad == "w:delText":
            continue
        else:
            parcalar.append(Parca(False, "", c))
    return Run(r, rpr, parcalar)


def paragraf_oku(xml: str, p: Oge) -> Paragraf:
    runlar, imlec = [], 0
    for r in _run_ogeleri(p):
        run = run_oku(xml, r)
        run.bas = imlec
        imlec += sum(len(x.metin) for x in run.parcalar)
        run.son = imlec
        runlar.append(run)
    return Paragraf(p, runlar, "".join(x.metin for run in runlar for x in run.parcalar))


# -- otomatik numaralandırma ---------------------------------------------------------------------
_ROMEN = [(1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"), (50, "l"), (40, "xl"),
          (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]


def _romen(n: int) -> str:
    cikti = ""
    for deger, harf in _ROMEN:
        while n >= deger:
            cikti += harf
            n -= deger
    return cikti or "0"


def _harf(n: int) -> str:
    if n <= 0:
        return "0"
    return chr(ord("a") + (n - 1) % 26) * ((n - 1) // 26 + 1)


def sayi_bicimle(n: int, bicim: str) -> str:
    if bicim in ("lowerLetter",):
        return _harf(n)
    if bicim == "upperLetter":
        return _harf(n).upper()
    if bicim == "lowerRoman":
        return _romen(n)
    if bicim == "upperRoman":
        return _romen(n).upper()
    if bicim == "decimalZero":
        return f"{n:02d}"
    return str(n)


@dataclass
class _Duzey:
    baslangic: int = 1
    bicim: str = "decimal"
    metin: str = ""
    yasal: bool = False


class Numaralandirma:
    """Word otomatik numaralandırmasının sadeleştirilmiş hesabı (numbering.xml + styles.xml).

    Sayaçlar soyut liste (abstractNum) başına tutulur; bir düzey artınca alt düzeyler baştan başlar.
    `startOverride` taşıyan liste örneği ilk kullanıldığında sayaçlar o değerden başlar. Madde işaretleri
    (bullet) numara sayılmaz.
    """

    def __init__(self, numbering_xml: Optional[bytes], styles_xml: Optional[bytes]):
        self.soyutlar: Dict[str, Dict[int, _Duzey]] = {}
        self.ornekler: Dict[str, Tuple[str, Dict[int, int]]] = {}
        self.stil_numara: Dict[str, Tuple[Optional[str], Optional[int]]] = {}
        self.stil_ust: Dict[str, str] = {}
        self.stil_adlari: Dict[str, str] = {}
        self._baglanti: Dict[str, str] = {}
        self._sayac: Dict[str, Dict[int, int]] = {}
        self._baslayan: set = set()
        if styles_xml:
            self._stiller(styles_xml)
        if numbering_xml:
            self._numaralar(numbering_xml)

    @staticmethod
    def _deger(oge, ad: str) -> Optional[str]:
        alt = oge.find(W_NS + ad) if oge is not None else None
        return alt.get(W_NS + "val") if alt is not None else None

    def _stiller(self, veri: bytes) -> None:
        try:
            kok = ET.fromstring(veri)
        except ET.ParseError:
            return
        for stil in kok.iter(W_NS + "style"):
            kimlik = stil.get(W_NS + "styleId")
            if not kimlik:
                continue
            ad = stil.find(W_NS + "name")
            self.stil_adlari[kimlik] = (ad.get(W_NS + "val") if ad is not None else "") or kimlik
            ust = self._deger(stil, "basedOn")
            if ust:
                self.stil_ust[kimlik] = ust
            numpr = stil.find(f"{W_NS}pPr/{W_NS}numPr")
            if numpr is not None:
                ilvl = self._deger(numpr, "ilvl")
                self.stil_numara[kimlik] = (self._deger(numpr, "numId"), int(ilvl) if ilvl and ilvl.isdigit() else None)

    def _numaralar(self, veri: bytes) -> None:
        try:
            kok = ET.fromstring(veri)
        except ET.ParseError:
            return
        for soyut in kok.iter(W_NS + "abstractNum"):
            kimlik = soyut.get(W_NS + "abstractNumId")
            duzeyler = {}
            for lvl in soyut.findall(W_NS + "lvl"):
                ilvl = int(lvl.get(W_NS + "ilvl") or 0)
                bas = self._deger(lvl, "start")
                duzeyler[ilvl] = _Duzey(
                    int(bas) if bas and bas.lstrip("-").isdigit() else 1,
                    self._deger(lvl, "numFmt") or "decimal",
                    self._deger(lvl, "lvlText") or "",
                    lvl.find(W_NS + "isLgl") is not None,
                )
            self.soyutlar[kimlik] = duzeyler
            stil_baglantisi = self._deger(soyut, "numStyleLink")
            if stil_baglantisi:
                self._baglanti[kimlik] = stil_baglantisi
        for num in kok.iter(W_NS + "num"):
            kimlik = num.get(W_NS + "numId")
            ustunlukler = {}
            for ov in num.findall(W_NS + "lvlOverride"):
                bas = self._deger(ov, "startOverride")
                if bas and bas.isdigit():
                    ustunlukler[int(ov.get(W_NS + "ilvl") or 0)] = int(bas)
            self.ornekler[kimlik] = (self._deger(num, "abstractNumId") or "", ustunlukler)

    def _soyut(self, num_id: str) -> Optional[str]:
        ornek = self.ornekler.get(num_id)
        if not ornek:
            return None
        soyut = ornek[0]
        # Stile bağlı liste: soyut liste kendi düzeylerini değil, bir stilin numarasını kullanır.
        if soyut in self._baglanti:
            stil_num = self.stil_numara.get(self._baglanti[soyut], (None, None))[0]
            if stil_num and stil_num in self.ornekler and stil_num != num_id:
                return self.ornekler[stil_num][0]
        return soyut

    def stil_zinciri(self, stil: Optional[str]) -> Iterator[str]:
        gorulen = set()
        while stil and stil not in gorulen:
            gorulen.add(stil)
            yield stil
            stil = self.stil_ust.get(stil)

    def paragraf_numarasi(self, xml: str, p: Oge) -> Optional[str]:
        """Paragrafın numarası; belge sırasıyla çağrılmalı (sayaçları ilerletir)."""
        ppr = p.cocuk("w:pPr")
        stil = oznitelik(xml, ppr.cocuk("w:pStyle"), "w:val") if ppr is not None and ppr.cocuk("w:pStyle") else None
        num_id, ilvl = None, None
        numpr = ppr.cocuk("w:numPr") if ppr is not None else None
        if numpr is not None:
            num_id = oznitelik(xml, numpr.cocuk("w:numId"), "w:val")
            deger = oznitelik(xml, numpr.cocuk("w:ilvl"), "w:val")
            ilvl = int(deger) if deger and deger.isdigit() else None
        for s in self.stil_zinciri(stil):
            if num_id is not None and ilvl is not None:
                break
            s_num, s_ilvl = self.stil_numara.get(s, (None, None))
            num_id = num_id if num_id is not None else s_num
            ilvl = ilvl if ilvl is not None else s_ilvl
        if not num_id or num_id == "0":
            return None
        soyut = self._soyut(num_id)
        if soyut is None or soyut not in self.soyutlar:
            return None
        duzeyler = self.soyutlar[soyut]
        ilvl = min(max(ilvl or 0, 0), 8)
        duzey = duzeyler.get(ilvl, _Duzey())
        sayac = self._sayac.setdefault(soyut, {})
        if num_id not in self._baslayan:
            self._baslayan.add(num_id)
            for d, bas in self.ornekler[num_id][1].items():
                sayac[d] = bas - 1
                for alt in [k for k in sayac if k > d]:
                    del sayac[alt]
        sayac[ilvl] = sayac[ilvl] + 1 if ilvl in sayac else duzey.baslangic
        for alt in [k for k in sayac if k > ilvl]:
            del sayac[alt]
        if duzey.bicim in ("bullet", "none"):
            return None

        def yer(m):
            d = int(m.group(1)) - 1
            dz = duzeyler.get(d, _Duzey())
            n = sayac.get(d, dz.baslangic)
            return sayi_bicimle(n, "decimal" if duzey.yasal else dz.bicim)

        etiket = re.sub(r"%([1-9])", yer, duzey.metin).strip()
        return etiket or None


# -- belge ---------------------------------------------------------------------------------------
class WordBelgesi:
    """Bir .docx'in gövdesi: paragraflar (tablo hücreleri dahil), tablolar ve numaralar.

    `donustur` verilirse paragraf metinleri ona göre dönüştürülür (yalnız karşılaştırma özetinde kullanılır;
    o zaman run konumları dönüştürülmüş metne karşılık gelmez ve belge yazmak için kullanılamaz).
    """

    def __init__(self, girdiler: Dict[str, bytes], donustur=None):
        if "word/document.xml" not in girdiler:
            raise AgacHatasi("Belgede word/document.xml yok.")
        self.girdiler = girdiler
        self.xml = girdiler["word/document.xml"].decode("utf-8")
        self.kok = agac(self.xml)
        belge = next((c for c in self.kok.cocuklar if c.ad == "w:document"), None)
        self.govde = belge.cocuk("w:body") if belge is not None else None
        if self.govde is None:
            raise AgacHatasi("Belgede gövde (w:body) bulunamadı.")
        self.numara = Numaralandirma(girdiler.get("word/numbering.xml"), girdiler.get("word/styles.xml"))
        self.stiller = set(self.numara.stil_adlari)
        self._donustur = donustur
        self._paragraflar: Dict[int, Paragraf] = {}
        self.sirali: List[Paragraf] = []
        self.tablo_sirasi: Dict[int, int] = {}
        self._gez(self.govde, None)

    def _baslik_mi(self, p: Oge) -> bool:
        ppr = p.cocuk("w:pPr")
        stil = oznitelik(self.xml, ppr.cocuk("w:pStyle"), "w:val") if ppr is not None and ppr.cocuk("w:pStyle") else None
        for s in self.numara.stil_zinciri(stil):
            ad = (self.numara.stil_adlari.get(s, s) or "").lower()
            if re.search(r"heading|başlık|baslik|title", ad):
                return True
        return False

    def _gez(self, kap: Oge, tablo_yeri: Optional[Tuple[int, int, int]]) -> None:
        for blok in bloklar(kap):
            if blok.ad == "w:p":
                p = paragraf_oku(self.xml, blok)
                if self._donustur is not None:
                    p.metin = self._donustur(p.metin)
                p.sira = len(self.sirali)
                p.tablo = tablo_yeri
                p.numara = self.numara.paragraf_numarasi(self.xml, blok)
                p.baslik = self._baslik_mi(blok)
                self._paragraflar[id(blok)] = p
                self.sirali.append(p)
            else:
                if tablo_yeri is None:
                    no = len(self.tablo_sirasi) + 1
                    self.tablo_sirasi[id(blok)] = no
                for s_no, satir in enumerate(satirlar(blok), start=1):
                    for h_no, hucre in enumerate(hucreler(satir), start=1):
                        yer = tablo_yeri or (self.tablo_sirasi[id(blok)], s_no, h_no)
                        self._gez(hucre, yer)

    def paragraf(self, p: Oge) -> Paragraf:
        return self._paragraflar[id(p)]

    def blok_metni(self, oge: Oge) -> str:
        if oge.ad == "w:p":
            return self.paragraf(oge).metin
        return "\n".join(self.paragraf(p).metin for p in oge.torunlar("w:p") if id(p) in self._paragraflar)

    def hucre_metni(self, hucre: Oge) -> str:
        return "\n".join(self.blok_metni(b) for b in bloklar(hucre))

    def izli_degisiklik_var(self) -> bool:
        return bool(re.search(r"<w:(?:ins|del|moveFrom|moveTo)\b", self.xml))

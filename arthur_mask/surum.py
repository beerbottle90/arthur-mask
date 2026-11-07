"""İki sürümün karşılaştırması: avukatın özgün .docx'i ile karşı tarafın "temiz" gönderdiği yeni sürüm.

- `izli_karsilastirma`: yeni sürümün kendisi üzerine, özgünden farkları Word izli değişikliği (w:ins / w:del) olarak
  yazar. Word'de "Tümünü kabul et" yeni sürümü, "Tümünü reddet" özgün metni verir. Gerçek metinle çalışır; çıktı
  avukatın bilgisayarında kalır.
- `degisiklik_ozeti`: aynı hizalamayla "ne değişti" listesi. Maskeli kopyalar üzerinde çalıştırılır; Claude'a yalnız
  bu özet gider.

Hizalama üç düzeydedir: gövde blokları (paragraf/tablo), tablo satırları ve hücre içi bloklar. Bloklar difflib ile
eşlenir; değişen paragrafta fark sözcük düzeyinde hesaplanır. Yeni sürümün biçimi (stil, numara, tablo düzeni)
olduğu gibi kalır; silinen metin özgündeki biçimiyle silinmiş olarak geri konur. Yalnız gövde karşılaştırılır.
"""

import html
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .docx_agac import AgacHatasi, Oge, Paragraf, WordBelgesi, bloklar, hucreler, oznitelik, satirlar
from .sinirlar import arsiv_oku

YAZAR = "Yeni sürüm"
# Maske etiketi ve ayraçlı sayı/tarih tek parça sayılır: "{{KİŞİ-01}}" ya da "1.250.000,00" değişince fark bütün
# olarak görünsün (etiketin içinden bölünmüş bir fark Claude'u yanıltır).
_SOZCUK = re.compile(r"\{\{[^{}\s]{1,40}\}\}|\d+(?:[.,/]\d+)*|\w+|\s+|[^\w\s]", re.U)
_KELIME = re.compile(r"\w+", re.U)
_AZAMI_ESLEME = 40_000


class SurumHatasi(Exception):
    pass


def girdiler(veri: bytes, ad: str = "belge") -> List[Tuple[zipfile.ZipInfo, bytes]]:
    try:
        with zipfile.ZipFile(io.BytesIO(veri)) as zf:
            return arsiv_oku(zf, ad, SurumHatasi)
    except zipfile.BadZipFile as hata:
        raise SurumHatasi(f"{ad} geçerli bir Word (.docx) dosyası değil.") from hata


def word_belgesi(veri_ya_da_girdiler, ad: str = "belge", donustur=None) -> WordBelgesi:
    liste = girdiler(veri_ya_da_girdiler, ad) if isinstance(veri_ya_da_girdiler, bytes) else veri_ya_da_girdiler
    try:
        return WordBelgesi({b.filename: v for b, v in liste}, donustur=donustur)
    except (AgacHatasi, UnicodeDecodeError) as hata:
        raise SurumHatasi(f"{ad} okunamadı: {hata}") from hata


# -- sözcük düzeyinde fark --------------------------------------------------------------------------
def kelime_farki(a: str, b: str) -> List[Tuple[str, int, int, int, int]]:
    """Karakter aralıklı işlemler: (tür, a_bas, a_son, b_bas, b_son); tür equal/insert/delete/replace.
    Değişiklikler arasında yalnız boşluk kalıyorsa iki değişiklik birleştirilir ("eski sözcük" → "yeni ifade")."""
    ta = [(m.group(), m.start(), m.end()) for m in _SOZCUK.finditer(a)]
    tb = [(m.group(), m.start(), m.end()) for m in _SOZCUK.finditer(b)]
    sm = SequenceMatcher(lambda t: t.isspace(), [t[0] for t in ta], [t[0] for t in tb], autojunk=False)

    def aralik(liste, i1, i2, uzunluk):
        if i1 == i2:
            konum = liste[i1][1] if i1 < len(liste) else uzunluk
            return konum, konum
        return liste[i1][1], liste[i2 - 1][2]

    islemler = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        a1, a2 = aralik(ta, i1, i2, len(a))
        b1, b2 = aralik(tb, j1, j2, len(b))
        islemler.append([tag, a1, a2, b1, b2])
    # Yalnız boşluk olan eşit parça iki değişikliğin arasındaysa değişikliğe katılır.
    for k in range(1, len(islemler) - 1):
        if islemler[k][0] == "equal" and not b[islemler[k][3]:islemler[k][4]].strip() \
                and islemler[k - 1][0] != "equal" and islemler[k + 1][0] != "equal":
            islemler[k][0] = "replace"
    birlesik: List[list] = []
    for op in islemler:
        if birlesik and op[0] != "equal" and birlesik[-1][0] != "equal":
            birlesik[-1][2], birlesik[-1][4] = op[2], op[4]
        else:
            birlesik.append(list(op))
    sonuc = []
    for tag, a1, a2, b1, b2 in birlesik:
        if tag != "equal":
            tag = "insert" if a1 == a2 else "delete" if b1 == b2 else "replace"
        sonuc.append((tag, a1, a2, b1, b2))
    return sonuc


def _benzerlik(a: str, b: str) -> float:
    """Sözcük torbası Dice benzerliği: "Süre 12 aydır." ile "Süre 24 aydır ve kendiliğinden uzar." aynı paragrafın
    iki sürümü sayılsın (0,55), bambaşka iki paragraf sayılmasın."""
    ka, kb = Counter(_KELIME.findall(a.lower())), Counter(_KELIME.findall(b.lower()))
    toplam = sum(ka.values()) + sum(kb.values())
    if not toplam:
        return 1.0 if not a.strip() and not b.strip() else 0.0
    return 2 * sum((ka & kb).values()) / toplam


def _esle(A: Sequence, B: Sequence, benzerlik: Callable, esik: float) -> List[Tuple[str, object, object]]:
    """Sırayı koruyan en iyi eşleme: [("eslesti", a, b) | ("silindi", a, None) | ("eklendi", None, b)]."""
    n, m = len(A), len(B)
    if not n or not m:
        return [("silindi", a, None) for a in A] + [("eklendi", None, b) for b in B]
    if n * m > _AZAMI_ESLEME:
        adimlar, i, j = [], 0, 0
        while i < n and j < m:
            if benzerlik(A[i], B[j]) >= esik:
                adimlar.append(("eslesti", A[i], B[j]))
                i, j = i + 1, j + 1
            else:
                adimlar += [("silindi", A[i], None), ("eklendi", None, B[j])]
                i, j = i + 1, j + 1
        return adimlar + [("silindi", a, None) for a in A[i:]] + [("eklendi", None, b) for b in B[j:]]
    S = [[benzerlik(a, b) for b in B] for a in A]
    T = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            en_iyi = max(T[i + 1][j], T[i][j + 1])
            if S[i][j] >= esik:
                en_iyi = max(en_iyi, T[i + 1][j + 1] + S[i][j])
            T[i][j] = en_iyi
    adimlar, i, j = [], 0, 0
    while i < n and j < m:
        if S[i][j] >= esik and T[i][j] == T[i + 1][j + 1] + S[i][j]:
            adimlar.append(("eslesti", A[i], B[j]))
            i, j = i + 1, j + 1
        elif T[i][j] == T[i + 1][j]:
            adimlar.append(("silindi", A[i], None))
            i += 1
        else:
            adimlar.append(("eklendi", None, B[j]))
            j += 1
    return adimlar + [("silindi", a, None) for a in A[i:]] + [("eklendi", None, b) for b in B[j:]]


# -- hizalama -------------------------------------------------------------------------------------------
class _Hizalayici:
    """Eski ve yeni belgeyi gezer; farkları alıcıya bildirir (izli değişiklik yazıcısı ya da özetleyici)."""

    def __init__(self, eski: WordBelgesi, yeni: WordBelgesi, alici):
        self.e, self.y, self.alici = eski, yeni, alici

    def govde(self) -> None:
        self.bloklar(list(bloklar(self.e.govde)), list(bloklar(self.y.govde)))

    @staticmethod
    def _anahtar(belge: WordBelgesi, oge: Oge) -> str:
        return ("P|" if oge.ad == "w:p" else "T|") + " ".join(belge.blok_metni(oge).split())

    def _blok_benzerligi(self, a: Oge, b: Oge) -> float:
        if a.ad != b.ad:
            return 0.0
        oran = _benzerlik(self.e.blok_metni(a), self.y.blok_metni(b))
        return oran if a.ad == "w:p" else max(oran, 0.5)  # aynı yerdeki iki tablo çoğu kez aynı tablodur

    def _satir_metni(self, belge: WordBelgesi, satir: Oge) -> str:
        return " | ".join(" ".join(belge.hucre_metni(h).split()) for h in hucreler(satir))

    @staticmethod
    def _yay(adimlar, silindi, eslesti, eklendi) -> None:
        son_b = None
        for k, (tur, a, b) in enumerate(adimlar):
            if tur == "silindi":
                if son_b is not None:
                    capa = son_b.son
                else:
                    sonraki = next((x[2] for x in adimlar[k:] if x[2] is not None), None)
                    capa = sonraki.bas if sonraki is not None else None
                silindi(a, capa)
                continue
            son_b = b
            if tur == "eslesti":
                eslesti(a, b)
            elif tur == "eklendi":
                eklendi(b)

    def bloklar(self, A: List[Oge], B: List[Oge]) -> None:
        ka = [self._anahtar(self.e, a) for a in A]
        kb = [self._anahtar(self.y, b) for b in B]
        adimlar = []
        for tag, i1, i2, j1, j2 in SequenceMatcher(None, ka, kb, autojunk=False).get_opcodes():
            if tag == "equal":
                adimlar += [("ayni", A[i1 + k], B[j1 + k]) for k in range(i2 - i1)]
            else:
                adimlar += _esle(A[i1:i2], B[j1:j2], self._blok_benzerligi, 0.5)
        self._yay(adimlar, self.alici.blok_silindi, self._blok_eslesti, self.alici.blok_eklendi)

    def _blok_eslesti(self, a: Oge, b: Oge) -> None:
        if a.ad == "w:p":
            pa, pb = self.e.paragraf(a), self.y.paragraf(b)
            if pa.metin != pb.metin:
                self.alici.paragraf_degisti(a, b, kelime_farki(pa.metin, pb.metin))
        else:
            self._tablo(a, b)

    def _tablo(self, ta: Oge, tb: Oge) -> None:
        RA, RB = satirlar(ta), satirlar(tb)
        ka = [self._satir_metni(self.e, r) for r in RA]
        kb = [self._satir_metni(self.y, r) for r in RB]
        adimlar = []
        for tag, i1, i2, j1, j2 in SequenceMatcher(None, ka, kb, autojunk=False).get_opcodes():
            if tag == "equal":
                adimlar += [("ayni", RA[i1 + k], RB[j1 + k]) for k in range(i2 - i1)]
            else:
                ea, eb = {id(r): ka[i1 + k] for k, r in enumerate(RA[i1:i2])}, {id(r): kb[j1 + k] for k, r in enumerate(RB[j1:j2])}
                adimlar += _esle(RA[i1:i2], RB[j1:j2], lambda x, y: _benzerlik(ea[id(x)], eb[id(y)]), 0.45)
        self._yay(adimlar, self.alici.satir_silindi, self._satir, self.alici.satir_eklendi)

    def _satir(self, ra: Oge, rb: Oge) -> None:
        CA, CB = hucreler(ra), hucreler(rb)
        for ca, cb in zip(CA, CB):
            self.bloklar(list(bloklar(ca)), list(bloklar(cb)))
        for cb in CB[len(CA):]:
            for blok in bloklar(cb):
                self.alici.blok_eklendi(blok)
        if len(CA) > len(CB) and CB:
            son = list(bloklar(CB[-1]))
            capa = son[-1].son if son else None
            for ca in CA[len(CB):]:
                for blok in bloklar(ca):
                    self.alici.blok_silindi(blok, capa)


# -- izli değişiklik yazıcısı ------------------------------------------------------------------------
def _kacis(metin: str) -> str:
    return html.escape(re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", metin), quote=False)


class _Yazici:
    def __init__(self, eski: WordBelgesi, yeni: WordBelgesi, yazar: str):
        self.e, self.y = eski, yeni
        self.yazar = html.escape(yazar)
        self.tarih = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        kimlikler = [int(x) for x in re.findall(r'\sw:id="(\d{1,9})"', yeni.xml)]
        self._kimlik = max(kimlikler, default=0) + 100
        self.duzenlemeler: List[Tuple[int, int, str, int]] = []
        self.sayim: Counter = Counter()

    # -- yardımcılar
    def _iz(self) -> str:
        self._kimlik += 1
        return f'w:id="{self._kimlik}" w:author="{self.yazar}" w:date="{self.tarih}"'

    def _ekle(self, bas: int, son: int, metin: str) -> None:
        self.duzenlemeler.append((bas, son, metin, len(self.duzenlemeler)))

    def _stil_gecerli(self, xml: str, oge: Oge) -> bool:
        return oznitelik(xml, oge, "w:val") in self.y.stiller

    def _alt_xml(self, oge: Optional[Oge], haric: set) -> str:
        """Eski belgedeki bir özellik öğesinin çocukları (yeni belgede olmayan stil başvuruları ve izler hariç)."""
        if oge is None:
            return ""
        xml = self.e.xml
        parcalar = []
        for c in oge.cocuklar:
            if c.ad in haric:
                continue
            if c.ad in ("w:pStyle", "w:rStyle", "w:tblStyle") and not self._stil_gecerli(xml, c):
                continue
            parcalar.append(xml[c.bas:c.son])
        return "".join(parcalar)

    def _rpr_temizle(self, rpr: str) -> str:
        if not rpr:
            return ""
        rpr = re.sub(r"<w:rPrChange\b.*?</w:rPrChange>|<w:rPrChange\b[^>]*/>", "", rpr, flags=re.S)

        def stil(m):
            return m.group(0) if m.group(1) in self.y.stiller else ""

        return re.sub(r'<w:rStyle\s+w:val="([^"]*)"\s*/>', stil, rpr)

    def _isaret(self, p: Oge, tur: str) -> None:
        """Paragraf imini izli eklenmiş/silinmiş olarak işaretler (pPr/rPr içinde w:ins / w:del)."""
        xml = self.y.xml
        isaret = f"<w:{tur} {self._iz()}/>"
        ppr = p.cocuk("w:pPr")
        if p.bos:
            etiket = xml[p.bas:p.son]
            self._ekle(p.bas, p.son, etiket[:-2].rstrip() + f"><w:pPr><w:rPr>{isaret}</w:rPr></w:pPr></w:p>")
        elif ppr is None:
            self._ekle(p.ic_bas, p.ic_bas, f"<w:pPr><w:rPr>{isaret}</w:rPr></w:pPr>")
        elif ppr.bos:
            self._ekle(ppr.bas, ppr.son, f"<w:pPr><w:rPr>{isaret}</w:rPr></w:pPr>")
        else:
            rpr = ppr.cocuk("w:rPr")
            if rpr is None:
                sonra = next((c for c in ppr.cocuklar if c.ad in ("w:sectPr", "w:pPrChange")), None)
                konum = sonra.bas if sonra is not None else ppr.ic_son
                self._ekle(konum, konum, f"<w:rPr>{isaret}</w:rPr>")
            elif rpr.bos:
                self._ekle(rpr.bas, rpr.son, f"<w:rPr>{isaret}</w:rPr>")
            else:
                self._ekle(rpr.ic_bas, rpr.ic_bas, isaret)

    def _silinen_runlar(self, pa: Paragraf, a1: int, a2: int) -> str:
        runlar = []
        for run in pa.runlar:
            if run.son <= a1 or run.bas >= a2:
                continue
            icerik, konum = [], run.bas
            for parca in run.parcalar:
                uzunluk = len(parca.metin)
                s, e = max(a1, konum), min(a2, konum + uzunluk)
                if s < e:
                    if parca.metin_mi:
                        icerik.append(f'<w:delText xml:space="preserve">{_kacis(parca.metin[s - konum:e - konum])}</w:delText>')
                    elif parca.metin == "\t":
                        icerik.append("<w:tab/>")
                    else:
                        icerik.append("<w:br/>")
                konum += uzunluk
            if icerik:
                runlar.append(f"<w:r>{self._rpr_temizle(run.rpr)}{''.join(icerik)}</w:r>")
        return f"<w:del {self._iz()}>{''.join(runlar)}</w:del>" if runlar else ""

    def _run_yaz(self, run, eklenen: List[Tuple[int, int]], silinen: List[Tuple[int, str]]) -> str:
        xml = self.y.xml
        bas_etiketi = xml[run.oge.bas:run.oge.ic_bas]
        sinirlar = sorted({x for s, e in eklenen for x in (s, e)} | {k for k, _ in silinen})
        bekleyen = sorted(silinen, key=lambda x: x[0])
        gruplar: List[list] = []

        def koy(durum: str, icerik: str) -> None:
            if gruplar and gruplar[-1][0] == durum and durum != "silinen":
                gruplar[-1][1].append(icerik)
            else:
                gruplar.append([durum, [icerik]])

        def silinenleri_koy(konum: int) -> None:
            while bekleyen and bekleyen[0][0] <= konum:
                koy("silinen", bekleyen.pop(0)[1])

        def durum(konum: int) -> str:
            return "eklenen" if any(s <= konum < e for s, e in eklenen) else "kalan"

        konum = run.bas
        for parca in run.parcalar:
            if parca.metin_mi:
                i = 0
                while i < len(parca.metin):
                    p = konum + i
                    silinenleri_koy(p)
                    sonraki = next((x for x in sinirlar if x > p), konum + len(parca.metin))
                    j = min(sonraki - konum, len(parca.metin))
                    koy(durum(p), f'<w:t xml:space="preserve">{_kacis(parca.metin[i:j])}</w:t>')
                    i = j
                konum += len(parca.metin)
            elif parca.metin:
                silinenleri_koy(konum)
                koy(durum(konum), xml[parca.oge.bas:parca.oge.son])
                konum += 1
            else:
                koy(durum(konum) if konum < run.son else "kalan", xml[parca.oge.bas:parca.oge.son])
        silinenleri_koy(10**12)
        cikti = []
        for d, icerik in gruplar:
            if d == "silinen":
                cikti.append(icerik[0])
            elif d == "kalan":
                cikti.append(f"{bas_etiketi}{run.rpr}{''.join(icerik)}</w:r>")
            else:
                cikti.append(f"<w:ins {self._iz()}>{bas_etiketi}{run.rpr}{''.join(icerik)}</w:r></w:ins>")
        return "".join(cikti)

    # -- alıcı arayüzü
    def paragraf_degisti(self, a: Oge, b: Oge, islemler) -> None:
        pa, pb = self.e.paragraf(a), self.y.paragraf(b)
        silinenler, eklenenler = [], []
        for tag, a1, a2, b1, b2 in islemler:
            if tag == "equal":
                continue
            if a2 > a1:
                parca = self._silinen_runlar(pa, a1, a2)
                if parca:
                    silinenler.append((b1, parca))
            if b2 > b1:
                eklenenler.append((b1, b2))
        self.sayim["degisen"] += 1
        metinli = [r for r in pb.runlar if r.son > r.bas]
        atamalar: Dict[int, list] = {}
        sahipsiz = []
        for konum, parca in silinenler:
            ev = next((r for r in metinli if r.bas <= konum < r.son), None)
            if ev is None and metinli:
                ev = metinli[-1]
            if ev is None:
                sahipsiz.append(parca)
            else:
                atamalar.setdefault(id(ev), []).append((konum, parca))
        for run in metinli:
            dels = atamalar.get(id(run), [])
            ek = [(s, e) for s, e in eklenenler if s < run.son and run.bas < e]
            if dels or ek:
                self._ekle(run.oge.bas, run.oge.son, self._run_yaz(run, ek, dels))
        if sahipsiz:
            if b.bos:
                etiket = self.y.xml[b.bas:b.son]
                self._ekle(b.bas, b.son, etiket[:-2].rstrip() + ">" + "".join(sahipsiz) + "</w:p>")
            else:
                self._ekle(b.ic_son, b.ic_son, "".join(sahipsiz))

    def _paragraf_eklendi(self, b: Oge) -> None:
        pb = self.y.paragraf(b)
        for run in pb.runlar:
            self._ekle(run.oge.bas, run.oge.son, f"<w:ins {self._iz()}>{self.y.xml[run.oge.bas:run.oge.son]}</w:ins>")
        self._isaret(b, "ins")

    def blok_eklendi(self, b: Oge) -> None:
        if b.ad == "w:p":
            if self.y.paragraf(b).metin.strip():  # boş paragraf işaretlenir ama sayılmaz (özetle aynı sayım)
                self.sayim["eklenen"] += 1
            self._paragraf_eklendi(b)
        else:
            self.sayim["tablo_eklenen"] += 1
            for satir in satirlar(b):
                self._satir_eklendi(satir)

    def _satir_eklendi(self, rb: Oge) -> None:
        trpr = rb.cocuk("w:trPr")
        isaret = f"<w:ins {self._iz()}/>"
        if trpr is None:
            onceki = rb.cocuk("w:tblPrEx")
            konum = onceki.son if onceki is not None else rb.ic_bas
            self._ekle(konum, konum, f"<w:trPr>{isaret}</w:trPr>")
        elif trpr.bos:
            self._ekle(trpr.bas, trpr.son, f"<w:trPr>{isaret}</w:trPr>")
        else:
            degisim = trpr.cocuk("w:trPrChange")
            konum = degisim.bas if degisim is not None else trpr.ic_son
            self._ekle(konum, konum, isaret)
        for hucre in hucreler(rb):
            for blok in bloklar(hucre):
                if blok.ad == "w:p":
                    self._paragraf_eklendi(blok)
                else:
                    for satir in satirlar(blok):
                        self._satir_eklendi(satir)

    def satir_eklendi(self, rb: Oge) -> None:
        self.sayim["satir_eklenen"] += 1
        self._satir_eklendi(rb)

    def _bos_silinen_paragraf(self) -> str:
        return f"<w:p><w:pPr><w:rPr><w:del {self._iz()}/></w:rPr></w:pPr></w:p>"

    def _silinen_paragraf(self, a: Oge) -> str:
        pa = self.e.paragraf(a)
        ppr = a.cocuk("w:pPr")
        haric = {"w:rPr", "w:sectPr", "w:pPrChange"}
        # Otomatik numara yeni belgede de tanımlıysa korunur (silinen madde numarasıyla görünür, reddedilince
        # numarasına döner); tanımlı değilse başka bir listeye bağlanmasın diye düşer.
        numpr = ppr.cocuk("w:numPr") if ppr is not None else None
        if numpr is not None and oznitelik(self.e.xml, numpr.cocuk("w:numId"), "w:val") not in self.y.numara.ornekler:
            haric.add("w:numPr")
        ic = self._alt_xml(ppr, haric)
        govde = self._silinen_runlar(pa, 0, len(pa.metin))
        return f"<w:p><w:pPr>{ic}<w:rPr><w:del {self._iz()}/></w:rPr></w:pPr>{govde}</w:p>"

    def _silinen_satir(self, r: Oge) -> str:
        ic = self._alt_xml(r.cocuk("w:trPr"), {"w:ins", "w:del", "w:trPrChange"})
        hucre_xml = []
        for hucre in hucreler(r):
            tcpr = hucre.cocuk("w:tcPr")
            tc_ic = (f"<w:tcPr>{self._alt_xml(tcpr, {'w:tcPrChange', 'w:cellIns', 'w:cellDel', 'w:cellMerge'})}</w:tcPr>"
                     if tcpr is not None else "")
            icerik = "".join(self._silinen_paragraf(b) if b.ad == "w:p" else self._silinen_tablo(b) for b in bloklar(hucre))
            hucre_xml.append(f"<w:tc>{tc_ic}{icerik or self._bos_silinen_paragraf()}</w:tc>")
        return f"<w:tr><w:trPr>{ic}<w:del {self._iz()}/></w:trPr>{''.join(hucre_xml)}</w:tr>"

    def _silinen_tablo(self, t: Oge) -> str:
        tblpr = t.cocuk("w:tblPr")
        ozellik = f"<w:tblPr>{self._alt_xml(tblpr, {'w:tblPrChange'})}</w:tblPr>"
        izgara = t.cocuk("w:tblGrid")
        izgara_xml = (f"<w:tblGrid>{self._alt_xml(izgara, {'w:tblGridChange'})}</w:tblGrid>"
                      if izgara is not None else "<w:tblGrid/>")
        satir_xml = "".join(self._silinen_satir(r) for r in satirlar(t))
        # Hücre ve gövde paragrafla bitmeli: tablonun ardına silinmiş boş bir paragraf konur.
        return f"<w:tbl>{ozellik}{izgara_xml}{satir_xml}</w:tbl>{self._bos_silinen_paragraf()}"

    def blok_silindi(self, a: Oge, capa: Optional[int]) -> None:
        if a.ad != "w:p" or self.e.paragraf(a).metin.strip():
            self.sayim["silinen" if a.ad == "w:p" else "tablo_silinen"] += 1
        if capa is not None:
            self._ekle(capa, capa, self._silinen_paragraf(a) if a.ad == "w:p" else self._silinen_tablo(a))

    def satir_silindi(self, ra: Oge, capa: Optional[int]) -> None:
        self.sayim["satir_silinen"] += 1
        if capa is not None:
            self._ekle(capa, capa, self._silinen_satir(ra))


def _uygula(xml: str, duzenlemeler) -> str:
    cikti, imlec = [], 0
    for bas, son, metin, _ in sorted(duzenlemeler, key=lambda d: (d[0], d[1], d[3])):
        if bas < imlec:
            raise SurumHatasi("Karşılaştırma düzenlemeleri çakıştı; bu belge çifti izli değişikliğe çevrilemedi.")
        cikti.append(xml[imlec:bas])
        cikti.append(metin)
        imlec = max(imlec, son)
    cikti.append(xml[imlec:])
    return "".join(cikti)


_DIGER_PARCALAR = re.compile(r"^word/(header\d*|footer\d*|footnotes|endnotes)\.xml$")


def _parca_metni(veri: bytes) -> str:
    return "".join(html.unescape(t) for t in re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>", veri.decode("utf-8", "replace")))


def izli_karsilastirma(eski_veri: bytes, yeni_veri: bytes, yazar: str = YAZAR) -> Tuple[bytes, Dict[str, int], List[str]]:
    """(izli .docx baytları, sayım, uyarılar)."""
    eski_girdiler, yeni_girdiler = girdiler(eski_veri, "Özgün sürüm"), girdiler(yeni_veri, "Yeni sürüm")
    eski, yeni = word_belgesi(eski_girdiler, "Özgün sürüm"), word_belgesi(yeni_girdiler, "Yeni sürüm")
    if yeni.izli_degisiklik_var():
        raise SurumHatasi("Yeni sürümde kabul edilmemiş izli değişiklikler var. Karşı tarafın değişikliklerini Word'de "
                          "'Tümünü kabul et' ile kabul edip kaydedin (ya da temiz sürüm isteyin) ve yeniden deneyin.")
    uyarilar = []
    if eski.izli_degisiklik_var():
        uyarilar.append("Özgün sürümde kabul edilmemiş izli değişiklikler vardı; karşılaştırmada kabul edilmiş sayıldı.")
    yazici = _Yazici(eski, yeni, yazar)
    _Hizalayici(eski, yeni, yazici).govde()
    yeni_xml = _uygula(yeni.xml, yazici.duzenlemeler)
    try:
        ET.fromstring(yeni_xml.encode("utf-8"))
    except ET.ParseError as hata:
        raise SurumHatasi("İzli değişiklikli belge üretilemedi (Word yapısı beklenmedik).") from hata

    eski_parcalar = {b.filename: v for b, v in eski_girdiler}
    farkli = []
    for bilgi, veri in yeni_girdiler:
        if _DIGER_PARCALAR.match(bilgi.filename) and _parca_metni(veri) != _parca_metni(eski_parcalar.get(bilgi.filename, b"")):
            farkli.append(bilgi.filename)
    if any(_DIGER_PARCALAR.match(ad) and ad not in {b.filename for b, _ in yeni_girdiler} for ad in eski_parcalar):
        farkli.append("silinen parça")
    if farkli:
        uyarilar.append("Üst/alt bilgi ya da dipnotlarda da fark var; bunlar izli değişikliğe işlenmedi, ayrıca kontrol edin.")
    if any(a.startswith("word/media/") for a in eski_parcalar) or any(b.filename.startswith("word/media/") for b, _ in yeni_girdiler):
        uyarilar.append("Belgede görsel var; görsel değişiklikleri karşılaştırılmaz.")

    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as zf:
        for bilgi, veri in yeni_girdiler:
            zf.writestr(bilgi, yeni_xml.encode("utf-8") if bilgi.filename == "word/document.xml" else veri)
    return tampon.getvalue(), dict(yazici.sayim), uyarilar


# -- değişiklik özeti --------------------------------------------------------------------------------
_KISA = 90


def _isaretle(a: str, b: str, islemler) -> str:
    """'Süre [-30-]{+60+} gündür.' biçiminde; uzun eşit parçalar kısaltılır."""
    parcalar = []
    for k, (tag, a1, a2, b1, b2) in enumerate(islemler):
        if tag == "equal":
            esit = b[b1:b2]
            ilk, son = k == 0, k == len(islemler) - 1
            if ilk and len(esit) > _KISA:
                esit = "…" + esit[-_KISA:]
            elif son and len(esit) > _KISA:
                esit = esit[:_KISA] + "…"
            elif not ilk and not son and len(esit) > 2 * _KISA + 10:
                esit = esit[:_KISA] + " … " + esit[-_KISA:]
            parcalar.append(esit)
            continue
        if a2 > a1:
            parcalar.append(f"[-{a[a1:a2]}-]")
        if b2 > b1:
            parcalar.append(f"{{+{b[b1:b2]}+}}")
    return "".join(parcalar)


def _kisalt(metin: str, sinir: int = 1500) -> str:
    metin = metin.strip()
    return metin if len(metin) <= sinir else metin[:sinir] + " …"


class _Ozetleyici:
    def __init__(self, eski: WordBelgesi, yeni: WordBelgesi):
        from .tutarlilik import MaddeYapisi, MetinParagrafi, iki_dilli_tablolar

        self.e, self.y = eski, yeni
        self.ogeler: List[Dict] = []
        self.sayim: Counter = Counter()
        self._yer = {}
        for belge in (eski, yeni):
            paragraflar = [MetinParagrafi(p.metin, (), p.tablo, p.numara, p.baslik) for p in belge.sirali]
            self._yer[id(belge)] = (MaddeYapisi(paragraflar), iki_dilli_tablolar(paragraflar))

    def _konum(self, belge: WordBelgesi, p: Optional[Paragraf], satir_duzeyi: bool = False) -> str:
        if p is None:
            return ""
        yapi, diller = self._yer[id(belge)]
        parcalar = []
        if yapi.yer[p.sira]:
            parcalar.append(f"Madde {yapi.yer[p.sira]}")
        if p.tablo:
            tablo, satir, sutun = p.tablo
            if satir_duzeyi:
                parcalar.append(f"Tablo {tablo}, satır {satir}")
            else:
                dil = diller.get(tablo)
                ek = f" ({dil[0 if sutun == 1 else 1].upper()})" if dil and sutun in (1, 2) else ""
                parcalar.append(f"Tablo {tablo}, satır {satir}, sütun {sutun}{ek}")
        elif not parcalar:
            parcalar.append(f"paragraf {p.sira + 1}")
        return " · ".join(parcalar)

    def _ilk_paragraf(self, belge: WordBelgesi, oge: Oge) -> Optional[Paragraf]:
        if oge.ad == "w:p":
            return belge.paragraf(oge)
        return next((belge.paragraf(p) for p in oge.torunlar("w:p") if id(p) in belge._paragraflar), None)

    _SAYIM = {"değişti": "degisen", "eklendi": "eklenen", "silindi": "silinen", "satır eklendi": "satir_eklenen",
              "satır silindi": "satir_silinen", "tablo eklendi": "tablo_eklenen", "tablo silindi": "tablo_silinen"}

    def _ekle(self, tur: str, yer: str, **alanlar) -> None:
        self.sayim[self._SAYIM[tur]] += 1  # izli değişiklik yazıcısıyla aynı anahtarlar
        self.ogeler.append({"no": len(self.ogeler) + 1, "tur": tur, "yer": yer, **alanlar})

    def _tablo_metni(self, belge: WordBelgesi, tablo: Oge) -> str:
        return "\n".join(" | ".join(" ".join(belge.hucre_metni(h).split()) for h in hucreler(s)) for s in satirlar(tablo))

    def paragraf_degisti(self, a: Oge, b: Oge, islemler) -> None:
        pa, pb = self.e.paragraf(a), self.y.paragraf(b)
        self._ekle("değişti", self._konum(self.y, pb), fark=_isaretle(pa.metin, pb.metin, islemler))

    def blok_eklendi(self, b: Oge) -> None:
        if b.ad == "w:p":
            p = self.y.paragraf(b)
            if p.metin.strip():
                self._ekle("eklendi", self._konum(self.y, p), metin=_kisalt(p.metin))
        else:
            self._ekle("tablo eklendi", self._konum(self.y, self._ilk_paragraf(self.y, b), True),
                       metin=_kisalt(self._tablo_metni(self.y, b), 3000))

    def blok_silindi(self, a: Oge, capa) -> None:
        if a.ad == "w:p":
            p = self.e.paragraf(a)
            if p.metin.strip():
                self._ekle("silindi", self._konum(self.e, p) + " (özgünde)", metin=_kisalt(p.metin))
        else:
            self._ekle("tablo silindi", self._konum(self.e, self._ilk_paragraf(self.e, a), True) + " (özgünde)",
                       metin=_kisalt(self._tablo_metni(self.e, a), 3000))

    def _satir_metni(self, belge: WordBelgesi, satir: Oge) -> str:
        return " | ".join(" ".join(belge.hucre_metni(h).split()) for h in hucreler(satir))

    def satir_eklendi(self, rb: Oge) -> None:
        metin = self._satir_metni(self.y, rb)
        if metin.replace("|", "").strip():
            self._ekle("satır eklendi", self._konum(self.y, self._ilk_paragraf(self.y, rb), True), metin=_kisalt(metin))

    def satir_silindi(self, ra: Oge, capa) -> None:
        metin = self._satir_metni(self.e, ra)
        if metin.replace("|", "").strip():
            self._ekle("satır silindi", self._konum(self.e, self._ilk_paragraf(self.e, ra), True) + " (özgünde)",
                       metin=_kisalt(metin))


def degisiklik_ozeti(eski_girdiler, yeni_girdiler, donustur: Optional[Callable[[str], str]] = None) -> Dict:
    """Maskeli kopyalardan "ne değişti" listesi. `donustur` her paragraf metnine uygulanır (çıkış kapısının
    normalleştirmesi: iki sürümde farklı biçimde kalmış aynı değer sahte bir fark üretmesin)."""
    eski = word_belgesi(eski_girdiler, "Özgün sürüm", donustur=donustur)
    yeni = word_belgesi(yeni_girdiler, "Yeni sürüm", donustur=donustur)
    ozetleyici = _Ozetleyici(eski, yeni)
    _Hizalayici(eski, yeni, ozetleyici).govde()
    return {"degisiklikler": ozetleyici.ogeler, "sayim": dict(ozetleyici.sayim)}

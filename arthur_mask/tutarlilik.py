"""Sözleşmenin iç tutarlılık denetimi: kurallarla, yerelde, dış veri olmadan.

Bulduğu dört şey:
- tanımlanıp kullanılmayan ve tanımlanmadan (büyük harfle, terim gibi) kullanılan terimler,
- belgede bulunmayan maddeye, alt maddeye, fıkraya ya da bende iç atıf ("m. 7.3", "Madde 12(b)", "Article 5.2"),
- taraf unvanı tutarsızlığı (aynı şirket farklı şirket türüyle, çok benzer ama farklı yazım, aynı rolün iki ayrı
  tarafa bağlanması),
- çift dilli (iki sütunlu tablo) belgelerde aynı satırın iki sütunu arasında madde numarası, atıf, tutar, oran,
  tarih ve sayı farkı.

Denetim gerçek metinde yapılır ve her bulgunun kanıtı bir paragraf aralığıdır. Rapor iki kez yazılır (`rapor_yaz`):
avukatın ekranı için gerçek metinle, Claude için aynı aralıkların maskeli karşılığıyla. Maskeli karşılık, belgenin
maskelenmesinde kullanılan değişikliklerden konumla üretilir; Claude'un belge metninde gördüğünden fazlası gitmez.
"""

import re
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .turkce import ascii_kucuk


@dataclass
class MetinParagrafi:
    metin: str
    konumlar: Sequence[int]  # her karakterin maskelenen düz metindeki yeri; -1: eşlenmeyen (sekme, satır sonu)
    tablo: Optional[Tuple[int, int, int]] = None
    numara: Optional[str] = None
    baslik: bool = False


@dataclass(frozen=True)
class Kanit:
    paragraf: int
    bas: int
    son: int


@dataclass
class TutarlilikBulgusu:
    kural: str
    onem: str
    sablon: str  # "{0} tanımlanmış ama…": {i} yerine i. kanıtın metni (gerçek ya da maskeli) gelir
    kanitlar: List[Kanit]


KURAL_ADLARI = {
    "terim_kullanilmiyor": "Tanımlanıp kullanılmayan terim",
    "terim_tanimsiz": "Tanımlanmadan kullanılan terim (olası)",
    "atif_madde_yok": "Var olmayan maddeye atıf",
    "atif_alt_yok": "Var olmayan alt maddeye, fıkraya ya da bende atıf",
    "taraf_turu": "Taraf unvanında şirket türü farkı",
    "taraf_yazim": "Taraf unvanında yazım farkı",
    "taraf_rol": "Aynı taraf rolü iki ayrı unvana bağlı",
    "iki_dil_madde": "Sütunlar arası madde numarası farkı",
    "iki_dil_atif": "Sütunlar arası atıf farkı",
    "iki_dil_tutar": "Sütunlar arası tutar farkı",
    "iki_dil_oran": "Sütunlar arası oran farkı",
    "iki_dil_tarih": "Sütunlar arası tarih farkı",
    "iki_dil_sayi": "Sütunlar arası sayı farkı",
}
_ONEM_SIRASI = {"yüksek": 0, "orta": 1, "düşük": 2}
_AZAMI_TANIMSIZ = 12


# -- yardımcılar ---------------------------------------------------------------------------------------
def katla(metin: str) -> str:
    """Uzunluk koruyan Türkçe/aksan duyarsız küçük harf (konumlar özgün metne eşlenir)."""
    katli = ascii_kucuk(metin)
    if len(katli) == len(metin):
        return katli
    return "".join(ascii_kucuk(h)[:1] or h for h in metin)


def _bosluk(metin: str) -> str:
    return " ".join(metin.split())


_DIL_SOZCUKLERI = {
    "tr": {"ve", "ile", "icin", "olarak", "isbu", "veya", "olan", "her", "tarafindan", "gore", "ise", "gibi",
           "kadar", "sozlesme", "sozlesmenin", "taraflar", "taraf", "edilir", "olup", "olacaktir", "halinde",
           "hukumleri", "eder", "ettigi", "yukumludur", "degildir", "uygun", "suresi"},
    "en": {"the", "and", "of", "to", "in", "shall", "by", "for", "or", "with", "this", "be", "any", "such",
           "agreement", "party", "parties", "is", "are", "which", "under", "hereof", "on", "that", "as", "from"},
}


def dil_tahmini(metin: str) -> str:
    """'tr', 'en', 'az' ya da '' (emin değil). Azerbaycan Türkçesinde 'ə' harfi belirleyicidir."""
    sozcukler = re.findall(r"[^\W\d_]+", katla(metin))
    if len(sozcukler) < 3:
        return ""
    if metin.count("ə") + metin.count("Ə") >= max(2, len(sozcukler) // 40):
        return "az"
    skor = {d: sum(1 for s in sozcukler if s in kume) / len(sozcukler) for d, kume in _DIL_SOZCUKLERI.items()}
    sirali = sorted(skor.items(), key=lambda x: -x[1])
    if sirali[0][1] >= 0.04 and sirali[0][1] >= 1.5 * sirali[1][1]:
        return sirali[0][0]
    return ""


def _sozcuk_sinirli(metin: str, bas: int, son: int) -> Tuple[int, int]:
    while bas > 0 and not metin[bas - 1].isspace():
        bas -= 1
    while son < len(metin) and not metin[son].isspace():
        son += 1
    return bas, son


# -- madde yapısı ve iç atıflar --------------------------------------------------------------------
_NUM = r"\d{1,3}(?:\.\d{1,3})*"
_MADDE_BASI = re.compile(
    r"^\s*(?:MADDE|Madde|MADDƏ|Maddə|ARTICLE|Article|SECTION|Section|CLAUSE|Clause|BÖLÜM|Bölüm|Md\.|MD\.)\s*"
    rf"({_NUM})(?![\d])"
)
_NUMARA_BASI = re.compile(r"^\s*(\d{1,3}(?:\.\d{1,3})+)\.?(?=\s|$|[)\-–—:])|^\s*(\d{1,3})\s*(\.|\)|[-–—])(?=\s|$)")
_FIKRA_BASI = re.compile(r"^\s*\((\d{1,2})\)(?=\s|$)")
_BENT_BASI = re.compile(r"^\s*\(?([a-zçğıöşü]|[ivx]{1,5})\)(?=\s|$)", re.I)

_ONEK = (
    r"(?:[Mm]adde(?:ler)?|MADDE(?:LER)?|[Mm]addə|MADDƏ"
    r"|[Mm][Dd]\.|[Mm]\.|[Aa]rticles?|ARTICLES?|[Aa]rt\.|[Ss]ections?|SECTIONS?|[Ss]ec\.|[Cc]lauses?|CLAUSES?|[Cc]l\."
    r"|[Ss]ub-?[Cc]lauses?|[Pp]aragraphs?|[Pp]ara\.|§§?)"
)
_BENT = r"(?:\s?\(\s?(?:[a-zA-ZçğıöşüÇĞİÖŞÜ]{1,2}|[ivxIVX]{1,5}|\d{1,2})\s?\))*"
_ATIF_ONEKLI = re.compile(rf"(?<![\w.]){_ONEK}\s*({_NUM})(?!\d)(?!\.\d)\.?({_BENT})(?:\s?/\s?(\d{{1,2}}))?")
_SIRA_EKI = r"(?:['’]?\s*(?:inci|ıncı|uncu|üncü|nci|ncı|ncu|ncü|ci|cı|cu|cü)\s+)?"
_ATIF_SONEKLI = re.compile(
    rf"(?<![\w.])({_NUM})(?!\d)\.?\s*{_SIRA_EKI}"
    r"(?:madde|MADDE)(?:si|sinin|sine|sinde|sini|nin|ye|de|deki|den|ler|leri|lerinde|lerine)?(?![\wçğıöşü])"
    rf"(?:\s*\(?(\d{{1,2}})\)?\s*\.?\s*{_SIRA_EKI}(?:numaralı\s+)?fıkra\w*)?"
    r"(?:\s*\(?([a-zçğıöşü])\)?\s*bend\w*)?"
)
_DEVAM = re.compile(
    rf"\s*(?:,|ve|veya|ile|and|or|ila|to|through|-|–)\s*({_NUM})(?!\d)\.?({_BENT})"
    r"(?!\s*(?:gün|ay\b|yıl|hafta|saat|iş\s+gün|days?|months?|years?|weeks?|hours?|%|TL|USD|EUR))"
)
_KANUN_IZI = re.compile(
    r"(?:Kanun|KANUN|kanun|Yönetmeli|YÖNETMELİ|yönetmeli|Tebliğ|TEBLİĞ|tebliğ|Tüzü|Kararname|Anayasa|ANAYASA|sayılı"
    r"|\bTBK|\bTTK|\bTMK|\bHMK|\bİİK|\bIIK|\bCMK|\bTCK|\bKVKK|\bİYUK|\bIYUK|\bMÖHUK|\bHUMK|\bBK|\bAİHS|\bAIHS|\bVUK"
    r"|Convention|Directive|Regulation|\bAct|\bLaw|\bCode|GDPR|Treaty|Statute|\bRules|Məcəllə|Qanun|qanun)"
    r"[^\s]{0,8}\s*$"
)
_IC_IZ = re.compile(r"(?:işbu|İşbu|ISBU|İŞBU|Sözleşme|SÖZLEŞME|sözleşme|this|This|hereof|herein|Agreement|yukarıda|aşağıda)")


@dataclass
class Atif:
    paragraf: int
    bas: int
    son: int
    yol: str                 # "7.3"
    bentler: Tuple[str, ...]  # ("b",)
    fikra: Optional[str] = None


def _bent_listesi(metin: str) -> Tuple[str, ...]:
    return tuple(katla(x) for x in re.findall(r"\(\s?([^()\s]{1,5})\s?\)", metin or ""))


def _baslik_devami(kalan: str) -> bool:
    """Madde numarasından sonra gelen metin bir başlık mı ("– GİZLİLİK", ": Süre", "Taraflar…") yoksa numarayla
    başlayan bir cümle mi ("Madde 5'te", "Madde 2.2(c) uyarınca", "7.3 maddesine göre")?"""
    kalan = kalan.lstrip()
    return not kalan or not (kalan[0].islower() or kalan[0] in "'’(")


def etiket_coz(etiket: str) -> Optional[Tuple[str, str]]:
    """Paragraf başı etiketi: ('madde', '7'), ('yol', '7.3'), ('fikra', '2'), ('bent', 'b'), ('sira', '3') ya da None."""
    if not etiket:
        return None
    etiket = etiket + " "
    m = _MADDE_BASI.match(etiket)
    if m:
        if not _baslik_devami(etiket[m.end():]):
            return None
        return ("yol", m.group(1)) if "." in m.group(1) else ("madde", m.group(1))
    m = _NUMARA_BASI.match(etiket)
    if m:
        if m.group(3) == ")":
            return "sira", m.group(2)  # "1) yazılı bildirimle": sıralı bent küçük harfle de başlar
        if not _baslik_devami(etiket[m.end():]):
            return None
        return ("yol", m.group(1)) if m.group(1) else ("madde", m.group(2))
    m = _FIKRA_BASI.match(etiket)
    if m:
        return "fikra", m.group(1)
    m = _BENT_BASI.match(etiket)
    if m:
        return "bent", katla(m.group(1))
    return None


class MaddeYapisi:
    """Belgedeki madde, alt madde, fıkra ve bentlerin kümesi ve her paragrafın konum etiketi ("7.3(b)")."""

    def __init__(self, paragraflar: Sequence[MetinParagrafi]):
        self.maddeler: set = set()
        self.yollar: set = set()
        self.bentler: set = set()
        self.fikralar: set = set()
        self.yer: List[str] = []
        etiketler = [etiket_coz(p.numara or "") or etiket_coz(p.metin) for p in paragraflar]

        def anahtar_sozcuklu_mu(p, etiket) -> bool:
            return bool(etiket) and bool(_MADDE_BASI.match(p.numara or "") or _MADDE_BASI.match(p.metin))

        # "MADDE 7" biçimi kullanılan belgede çıplak "1." numaraları maddenin içindeki sıralı fıkralardır.
        anahtar_sozcuklu = sum(1 for p, e in zip(paragraflar, etiketler) if anahtar_sozcuklu_mu(p, e)) >= 2
        # Durum (geçerli madde, alt madde, bent, fıkra sayısı) gövde ve her tablo sütunu için ayrı tutulur: çift dilli
        # tabloda sol sütun "MADDE 6", sağ sütun "ARTICLE 6" diye ilerler; biri ötekinin yerini bozmasın.
        durumlar: Dict[object, Tuple] = {}
        madde, yol, bent, fikra_sayisi = None, None, None, 0
        anahtar = None
        for p, etiket in zip(paragraflar, etiketler):
            yeni_anahtar = (p.tablo[0], p.tablo[2]) if p.tablo else "govde"
            if yeni_anahtar != anahtar:
                if anahtar is not None:
                    durumlar[anahtar] = (madde, yol, bent, fikra_sayisi)
                madde, yol, bent, fikra_sayisi = durumlar.get(yeni_anahtar) or durumlar.get("govde") or (None, None, None, 0)
                anahtar = yeni_anahtar
            tur, deger = etiket if etiket else (None, None)
            if tur == "madde" and anahtar_sozcuklu and not anahtar_sozcuklu_mu(p, etiket):
                tur = "sira"
            if tur == "madde":
                madde, yol, bent = deger, deger, None
                self.maddeler.add(deger)
                self.yollar.add(deger)
                kalan = len(p.metin.split())
                fikra_sayisi = 1 if kalan > 8 else 0
                if fikra_sayisi:
                    self.fikralar.add(f"{madde}/1")
            elif tur == "yol":
                parcalar = deger.split(".")
                madde, yol, bent = parcalar[0], deger, None
                self.maddeler.add(madde)
                for i in range(1, len(parcalar) + 1):
                    self.yollar.add(".".join(parcalar[:i]))
                self.fikralar.add(f"{madde}/{parcalar[1]}")
            elif tur in ("fikra", "sira") and madde:
                self.fikralar.add(f"{madde}/{deger}")
                self.bentler.add(f"{yol}({deger})")
                if tur == "sira":
                    self.yollar.add(f"{madde}.{deger}")
            elif tur == "bent" and madde:
                bent = deger
                self.bentler.add(f"{yol}({deger})")
                self.bentler.add(f"{madde}({deger})")
            elif madde and p.metin.strip() and not p.baslik:
                fikra_sayisi += 1
                self.fikralar.add(f"{madde}/{fikra_sayisi}")
            if not madde:
                self.yer.append("")
            else:
                self.yer.append(yol + (f"({bent})" if bent and tur == "bent" else ""))

    def var_mi(self, atif: Atif) -> Optional[str]:
        """Atıf yerindeyse None; değilse bulgu kuralı."""
        madde = atif.yol.split(".")[0]
        if madde not in self.maddeler:
            return "atif_madde_yok"
        if atif.yol not in self.yollar:
            return "atif_alt_yok"
        for b in atif.bentler:
            if f"{atif.yol}({b})" not in self.bentler and f"{madde}({b})" not in self.bentler:
                return "atif_alt_yok"
        if atif.fikra and f"{madde}/{atif.fikra}" not in self.fikralar and f"{atif.yol}.{atif.fikra}" not in self.yollar:
            return "atif_alt_yok"
        return None


def _dis_atif_mi(metin: str, bas: int, son: int) -> bool:
    once = metin[max(0, bas - 40):bas]
    if _KANUN_IZI.search(once):
        return True
    sonra = metin[son:son + 60]
    m = re.match(r"\s*(?:\([^)]{0,12}\)\s*)?(?:of|under)\s+(?:the\s+)?([A-Z][\w-]*)", sonra)
    if m and m.group(1).lower() not in {"agreement", "contract", "deed", "annex", "schedule", "appendix", "exhibit"}:
        return True
    return False


def atiflar(paragraflar: Sequence[MetinParagrafi]) -> List[Atif]:
    sonuc = []
    for i, p in enumerate(paragraflar):
        metin = p.metin
        if not re.search(r"\d", metin):
            continue
        ilk = len(metin) - len(metin.lstrip())
        baslikli = etiket_coz(p.metin) is not None and etiket_coz(p.metin)[0] in ("madde", "yol")
        alinan: List[Tuple[int, int]] = []
        bulunan = []
        for m in _ATIF_ONEKLI.finditer(metin):
            bulunan.append((m.start(), m.end(), m.group(1), _bent_listesi(m.group(2)), m.group(3)))
        for m in _ATIF_SONEKLI.finditer(metin):
            bulunan.append((m.start(), m.end(), m.group(1), (katla(m.group(3)),) if m.group(3) else (), m.group(2)))
        # Çakışan adaylardan önce başlayan (eşitse uzun olan) kalır: "2. maddenin 9. fıkrası" tek atıftır.
        for bas, son, yol, bentler, fikra in sorted(bulunan, key=lambda x: (x[0], -x[1])):
            if any(a < son and bas < b for a, b in alinan):
                continue
            if bas == ilk and baslikli:
                alinan.append((bas, son))
                continue  # paragrafın kendi başlığı ("MADDE 7 –")
            dis = _dis_atif_mi(metin, bas, son)
            arada = metin[max(0, bas - 40):bas]
            if dis and _IC_IZ.search(arada[-25:]) and not _KANUN_IZI.search(metin[max(0, bas - 12):bas]):
                dis = False
            alinan.append((bas, son))
            if not dis:
                sonuc.append(Atif(i, bas, son, yol.rstrip("."), bentler, fikra))
            imlec = son
            while True:
                d = _DEVAM.match(metin, imlec)
                # "… 2. fıkrası ile 2. maddenin 9. fıkrası": devam sayısı kendi başına bir atıfın başıysa devam değildir.
                if not d or any(a < d.end() and d.start(1) < b and a != bas for a, b, *_ in bulunan):
                    break
                alinan.append((d.start(1), d.end()))
                if not dis:
                    sonuc.append(Atif(i, d.start(1), d.end(), d.group(1).rstrip("."), _bent_listesi(d.group(2))))
                imlec = d.end()
    return sonuc


# -- tanımlı terimler ----------------------------------------------------------------------------------
_TIRNAK_AC, _TIRNAK_KAPA = "\"“„«", "\"”»“"
_TIRNAKLI = re.compile(r"[\"“„«]\s*([A-ZÇĞİÖŞÜƏ0-9][^\"“”„«»\n]{0,58}?)\s*[\"”»“]")
_PARANTEZ = re.compile(r"\(([^()\n]{0,300})\)")
_TANIM_BASI = re.compile(
    r"^\s*(?:[(\[]?[\w.]{1,8}[)\].]?\s+)?[\"“„«]\s*([A-ZÇĞİÖŞÜƏ0-9][^\"“”„«»\n]{0,58}?)\s*[\"”»“]\s*"
    r"(?=$|[:：,\-–—(]|means\b|shall\s+mean|has\s+the\s+meaning|includes\b|ifadesi|terimi|deyimi|kavramı|sözcüğü"
    r"|anlamına|ifade\s+eder|deməkdir|dedikdə)",
    re.I,
)


@dataclass
class Tanim:
    terim: str
    anahtar: str
    kanit: Kanit
    rol_icin: Optional[int] = None  # parantez tanımında açılış parantezinin konumu (taraf rolü eşlemesi)


def tanimlar(paragraflar: Sequence[MetinParagrafi]) -> List[Tanim]:
    sonuc, gorulen = [], set()
    for i, p in enumerate(paragraflar):
        metin = p.metin
        if not any(t in metin for t in _TIRNAK_AC):
            continue
        adaylar = []
        m = _TANIM_BASI.match(metin)
        if m:
            adaylar.append((m.start(1), m.end(1), None))
        for par in _PARANTEZ.finditer(metin):
            ic = par.group(1)
            if re.search(r"\bbkz\b|\bsee\b|başlıklı|titled", ic, re.I):
                continue
            # Toplu tanım ("birlikte 'Taraflar'") tek bir tarafa bağlanmaz.
            toplu = re.search(r"birlikte|ayrı\s+ayrı|together|collectively|each|her\s+biri|birgə|ayrı-ayrılıqda", ic, re.I)
            for t in _TIRNAKLI.finditer(ic):
                adaylar.append((par.start(1) + t.start(1), par.start(1) + t.end(1), None if toplu else par.start()))
        for bas, son, parantez in adaylar:
            terim = metin[bas:son].strip()
            if not terim or len(terim.split()) > 6 or terim.endswith((".", ",")):
                continue
            anahtar = _bosluk(katla(terim))
            if (i, bas) in gorulen or len(anahtar) < 2:
                continue
            gorulen.add((i, bas))
            sonuc.append(Tanim(terim, anahtar, Kanit(i, bas, son), parantez))
    return sonuc


def _terim_deseni(anahtar: str) -> re.Pattern:
    govde = r"\s+".join(re.escape(s) for s in anahtar.split())
    return re.compile(rf"(?<![a-z0-9]){govde}(?![0-9])")


def _kullanimlar(tanim: Tanim, paragraflar, katlilar, tanim_araliklari) -> List[Kanit]:
    desen = _terim_deseni(tanim.anahtar)
    sonuc = []
    tum_buyuk = tanim.terim.isupper()
    for i, katli in enumerate(katlilar):
        if tanim.anahtar.split()[0] not in katli:
            continue
        metin = paragraflar[i].metin
        for m in desen.finditer(katli):
            if any(a <= m.start() < b for a, b in tanim_araliklari.get(i, ())):
                continue
            ilk = metin[m.start()]
            if not (ilk.isupper() or ilk.isdigit()):
                continue
            # Terimin ardından büyük harfle devam eden sözcük: "Bilgi" ≠ "BilgiSistemi"
            if m.end() < len(metin) and metin[m.end()].isupper() and not tum_buyuk:
                continue
            sonuc.append(Kanit(i, m.start(), m.end()))
    return sonuc


_DURAK = {
    "madde", "maddesi", "article", "section", "clause", "ek", "ekler", "annex", "schedule", "exhibit", "appendix",
    "sayin", "turkiye", "cumhuriyeti", "turk", "istanbul", "ankara", "izmir", "baku", "azerbaycan", "azerbaijan",
    "london", "england", "wales", "ingiltere", "isvicre", "switzerland", "cenevre", "geneva", "new", "york",
    "ocak", "subat", "mart", "nisan", "mayis", "haziran", "temmuz", "agustos", "eylul", "ekim", "kasim", "aralik",
    "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
    "december", "pazartesi", "sali", "carsamba", "persembe", "cuma", "cumartesi", "pazar", "monday", "tuesday",
    "wednesday", "thursday", "friday", "saturday", "sunday", "mr", "mrs", "ms", "dr", "av", "prof", "bay", "bayan",
    "hanim", "bey", "tl", "usd", "eur", "kdv", "vat", "icc", "uncitral", "lcia", "istac", "the", "in", "this",
    "yanvar", "fevral", "aprel", "iyun", "iyul", "avqust", "sentyabr", "oktyabr", "noyabr", "dekabr", "isbu",
}
_KURUM_SONU = (
    "kanun", "yonetmeli", "teblig", "tuzu", "kararname", "anayasa", "mahkeme", "daire", "kurum", "kurul", "bakanlig",
    "baskanlig", "mudurlug", "oda", "borsa", "banka", "universite", "noter", "belediye", "valilig", "law", "act",
    "code", "regulation", "directive", "convention", "court", "tribunal", "ministry", "authority", "commission",
    "chamber", "bank", "rules", "treaty", "arbitration", "tahkim", "merkez", "center", "centre", "icra", "registry",
    "sicil", "office", "agency", "council", "institute", "enstitu", "vakf", "dernek", "sendika", "holding",
)
_BAGLAC = {"of", "and", "for", "the", "ve", "ile"}
_SOZCUK = re.compile(r"[^\W\d_][\w\-]*(?:['’][\w]+)?")


def _cumle_basi_mi(metin: str, bas: int) -> bool:
    once = metin[:bas].rstrip().rstrip("\"“„«([").rstrip()
    if not once:
        return True
    if once[-1] in ".!?:;•–—-*":
        return True
    return bool(re.fullmatch(r"\s*(?:\(?[\w.]{1,6}[).]|[-•*–])\s*", metin[:bas]))


def _tanimsiz_terimler(paragraflar, tanimlar_, varlik_araliklari) -> List[Tuple[List[Kanit], str]]:
    tanim_sozcukleri = [t.anahtar.split() for t in tanimlar_]

    def tanimli(sozcukler: List[str]) -> bool:
        for t in tanim_sozcukleri:
            if t[:len(sozcukler)] == sozcukler or sozcukler[:len(t)] == t:
                return True
            if len(t) == len(sozcukler) and t[:-1] == sozcukler[:-1] and sozcukler[-1].startswith(t[-1]) \
                    and len(sozcukler[-1]) - len(t[-1]) <= 6:
                return True
            if len(sozcukler) < len(t) and t[-len(sozcukler):] == sozcukler:
                return True
        return False

    adaylar: Dict[str, List[Kanit]] = defaultdict(list)
    gorunum: Dict[str, str] = {}
    for i, p in enumerate(paragraflar):
        metin = p.metin
        sozcukler_ = metin.split()
        if p.baslik or (len(sozcukler_) <= 8 and (metin.isupper() or all(s[:1].isupper() for s in sozcukler_ if s[:1].isalpha()))):
            continue
        dizi: List[Tuple[int, int, str]] = []

        def bitir():
            while dizi and katla(dizi[-1][2]) in _BAGLAC:
                dizi.pop()
            if dizi:
                sozler = [katla(s) for _, _, s in dizi]
                bas, son = dizi[0][0], dizi[-1][1]
                if (not any(s in _DURAK for s in (sozler[0], sozler[-1]))
                        and not sozler[-1].startswith(_KURUM_SONU)
                        and not any(a < son and bas < b for a, b in varlik_araliklari.get(i, ()))
                        and not tanimli(sozler)
                        and all(len(s) > 1 and not any(h.isdigit() for h in s) for s in sozler)):
                    anahtar = " ".join(sozler)
                    adaylar[anahtar].append(Kanit(i, bas, son))
                    gorunum.setdefault(anahtar, " ".join(s for _, _, s in dizi))
            dizi.clear()

        for m in _SOZCUK.finditer(metin):
            ham = re.split(r"['’]", m.group())[0].rstrip(".-")
            son = m.start() + len(ham)
            if not ham:
                bitir()
                continue
            buyuk = ham[0].isupper() and not ham.isupper()
            ara = metin[dizi[-1][1]:m.start()] if dizi else ""
            if dizi and (ara.strip() or "\n" in ara):
                bitir()
            if buyuk:
                if not dizi and _cumle_basi_mi(metin, m.start()):
                    continue
                dizi.append((m.start(), son, ham))
            elif dizi and katla(ham) in _BAGLAC:
                dizi.append((m.start(), son, ham))
            else:
                bitir()
            if son != m.end():
                bitir()  # ek almış sözcük ("Satıcı'nın") diziyi bitirir
        bitir()

    sonuc = []
    for anahtar, kanitlar in adaylar.items():
        sozcuk_sayisi = len(anahtar.split())
        if (sozcuk_sayisi == 1 and len(kanitlar) >= 3) or (sozcuk_sayisi > 1 and len(kanitlar) >= 2):
            sonuc.append((kanitlar, anahtar))
    sonuc.sort(key=lambda x: -len(x[0]))
    return sonuc


# -- taraflar ----------------------------------------------------------------------------------------
_TUR_EKI = [
    (r"a\.?\s?s\.?|anonim\s+sirketi?", "AŞ"),
    (r"ltd\.?\s*sti\.?|limited\s+sirketi?|sti\.?", "LTD ŞTİ"),
    (r"kollektif\s+sirketi?|koll\.?\s*sti\.?", "KOLL ŞTİ"),
    (r"komandit\s+sirketi?|kom\.?\s*sti\.?", "KOM ŞTİ"),
    (r"kooperatifi?", "KOOPERATİF"),
    (r"l\.?l\.?c\.?|limited\s+liability\s+company", "LLC"),
    (r"inc\.?|incorporated", "INC"),
    (r"corp\.?|corporation", "CORP"),
    (r"plc\.?|public\s+limited\s+company", "PLC"),
    (r"ltd\.?|limited", "LTD"),
    (r"gmbh", "GMBH"),
    (r"ag", "AG"),
    (r"s\.?a\.?|s\.?p\.?a\.?", "SA"),
    (r"b\.?v\.?", "BV"),
    (r"n\.?v\.?", "NV"),
    (r"mmc|məhdud\s+məsuliyyətli\s+cəmiyyət", "MMC"),
    (r"qsc|asc|aşc|asc", "ASC"),
    (r"co\.?|company", "CO"),
]
_TUR_DESENI = re.compile(r"(?:^|[\s,])(" + "|".join(d for d, _ in _TUR_EKI) + r")[\s.,]*$")


def unvan_coz(metin: str) -> Tuple[str, str]:
    """(çekirdek, tür): 'ABC Enerji A.Ş.' → ('abc enerji', 'AŞ'). Tür yoksa ''."""
    katli = _bosluk(katla(metin)).strip(" ,.;:&-")
    m = _TUR_DESENI.search(katli)
    tur = ""
    if m and m.start(1) > 0:
        for desen, ad in _TUR_EKI:
            if re.fullmatch(desen, m.group(1).strip(" .,")) or re.fullmatch(desen, m.group(1)):
                tur = ad
                break
        katli = katli[:m.start(1)].strip(" ,.;:&-")
    cekirdek = re.sub(r"[^\w\s]", " ", katli)
    return _bosluk(cekirdek), tur


def _taraf_bulgulari(paragraflar, tanimlar_, varliklar_p) -> List[TutarlilikBulgusu]:
    bulgular = []
    sirketler = [(k, metin) for k, tur, metin in varliklar_p if tur == "TR_TUZEL_KISI"]
    gruplar: Dict[str, Dict[str, List[Kanit]]] = defaultdict(lambda: defaultdict(list))
    for k, metin in sirketler:
        cekirdek, tur = unvan_coz(metin)
        if len(cekirdek) >= 3:
            gruplar[cekirdek][tur].append(k)
    for cekirdek, turler in gruplar.items():
        dolu = {t: k for t, k in turler.items() if t}
        if len(dolu) >= 2:
            (t1, k1), (t2, k2) = sorted(dolu.items(), key=lambda x: x[1][0].paragraf)[:2]
            bulgular.append(TutarlilikBulgusu(
                "taraf_turu", "yüksek",
                f"Aynı şirket iki farklı şirket türüyle yazılmış ({t1} / {t2}): {{0}} ve {{1}}. Doğru unvanı ticaret "
                "sicilinden teyit edin.",
                [k1[0], k2[0]]))
    cekirdekler = sorted(gruplar)
    for i, c1 in enumerate(cekirdekler):
        for c2 in cekirdekler[i + 1:]:
            if min(len(c1), len(c2)) < 6 or c1.startswith(c2 + " ") or c2.startswith(c1 + " "):
                continue
            oran = SequenceMatcher(None, c1, c2).ratio()
            if 0.86 <= oran < 1:
                k1 = next(iter(gruplar[c1].values()))[0]
                k2 = next(iter(gruplar[c2].values()))[0]
                bulgular.append(TutarlilikBulgusu(
                    "taraf_yazim", "orta",
                    "Taraf unvanı iki farklı yazımla geçiyor: {0} ve {1}. Aynı taraf ise yazımı birleştirin.",
                    [k1, k2]))

    # Rol eşlemesi: '… ABC Enerji A.Ş. ("Satıcı")', imza ve taraf bloklarında 'SATICI: ABC …'.
    roller: Dict[str, List[Tuple[str, Kanit, Kanit]]] = defaultdict(list)
    varlik_paragraf: Dict[int, List[Tuple[Kanit, str, str]]] = defaultdict(list)
    for k, tur, metin in varliklar_p:
        if tur in ("TR_TUZEL_KISI", "PERSON"):
            varlik_paragraf[k.paragraf].append((k, tur, metin))

    def kimlik(tur: str, metin: str) -> str:
        return unvan_coz(metin)[0] if tur == "TR_TUZEL_KISI" else _bosluk(katla(metin))

    rol_anahtarlari = set()
    for t in tanimlar_:
        if t.rol_icin is None:
            continue
        onceki = [v for v in varlik_paragraf.get(t.kanit.paragraf, ()) if v[0].son <= t.rol_icin
                  and t.rol_icin - v[0].son <= 250]
        if not onceki:
            continue
        v = max(onceki, key=lambda x: x[0].son)
        arada = paragraflar[t.kanit.paragraf].metin[v[0].son:t.rol_icin]
        if ")" in arada:
            continue
        roller[t.anahtar].append((kimlik(v[1], v[2]), v[0], t.kanit))
        rol_anahtarlari.add(t.anahtar)
    if rol_anahtarlari:
        for i, p in enumerate(paragraflar):
            m = re.match(r"\s*([^\W\d_][^\n:：]{1,40}?)\s*(?:[:：]|$)", p.metin)
            if not m or _bosluk(katla(m.group(1))) not in rol_anahtarlari:
                continue
            rol = _bosluk(katla(m.group(1)))
            adaylar = [v for v in varlik_paragraf.get(i, ()) if v[0].bas >= m.end(1)]
            if not adaylar and not p.metin[m.end():].strip():
                for j in range(i + 1, min(i + 4, len(paragraflar))):
                    if varlik_paragraf.get(j):
                        adaylar = varlik_paragraf[j]
                        break
            if adaylar:
                v = adaylar[0]
                roller[rol].append((kimlik(v[1], v[2]), v[0], Kanit(i, m.start(1), m.end(1))))
    for rol, eslesmeler in roller.items():
        ilk = eslesmeler[0]
        for diger in eslesmeler[1:]:
            a, b = ilk[0], diger[0]
            if not a or not b or a == b or a.startswith(b + " ") or b.startswith(a + " ") or \
                    SequenceMatcher(None, a, b).ratio() >= 0.86:
                continue
            bulgular.append(TutarlilikBulgusu(
                "taraf_rol", "yüksek",
                "{0} rolü belgede iki ayrı tarafa bağlanmış: {1} ve {2}.",
                [ilk[2], ilk[1], diger[1]]))
            break
    return bulgular


# -- çift dilli tablolar ------------------------------------------------------------------------------
_AYLAR = {
    1: ("ocak", "january", "jan", "yanvar"), 2: ("subat", "february", "feb", "fevral"),
    3: ("mart", "march", "mar"), 4: ("nisan", "april", "apr", "aprel"), 5: ("mayis", "may", "may"),
    6: ("haziran", "june", "jun", "iyun"), 7: ("temmuz", "july", "jul", "iyul"),
    8: ("agustos", "august", "aug", "avqust"), 9: ("eylul", "september", "sep", "sept", "sentyabr"),
    10: ("ekim", "october", "oct", "oktyabr"), 11: ("kasim", "november", "nov", "noyabr"),
    12: ("aralik", "december", "dec", "dekabr"),
}
_AY_ADI = {ad: no for no, adlar in _AYLAR.items() for ad in adlar}
_AY = "|".join(sorted(_AY_ADI, key=len, reverse=True))
_TARIH_DESENLERI = [
    (re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)"), "ymd"),
    (re.compile(r"(?<![\d.])(\d{1,2})[./-](\d{1,2})[./-](\d{4})(?!\d)"), "dmy"),
    (re.compile(rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th|'?\s?(?:inci|nci|ncı|üncü|uncu))?\s+({_AY})\w*\s*,?\s+(\d{{4}})(?!\d)"), "d_ay_y"),
    (re.compile(rf"\b({_AY})\w*\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\s*,?\s+(\d{{4}})(?!\d)"), "ay_d_y"),
]
_PARA = (r"(?:TL|TRY|USD|EUR|GBP|AZN|CHF|RUB|JPY|CNY|₺|\$|€|£|₼|Türk\s+Lirası|TÜRK\s+LİRASI|türk\s+lirası|lira|Lira"
         r"|ABD\s+Doları|Amerikan\s+Doları|dolar|Dolar|avro|Avro|euro|Euro|EURO|manat|Manat|dollars?|Dollars?"
         r"|pounds?|Pounds?|euros?)")
_SAYI = r"\d{1,3}(?:[.,   ]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_TUTAR = re.compile(rf"(?<![\w.,])(?:({_PARA})\s?({_SAYI})|({_SAYI})\s?({_PARA}))(?![\w])")
_ORAN = re.compile(rf"(?:%\s?({_SAYI})|(?<![\w.,])({_SAYI})\s?%|(?:yüzde|Yüzde)\s+({_SAYI})|(?<![\w.,])({_SAYI})\s+(?:percent|per\s+cent))")
_YALIN = re.compile(rf"(?<![\w.,/{{-])({_SAYI})(?![\w}}])")
_PARA_KODU = [
    (r"tl|try|₺|turk\s+lirasi|lira", "TRY"), (r"usd|\$|abd\s+dolari|amerikan\s+dolari|dolar|dollars?", "USD"),
    (r"eur|€|avro|euros?", "EUR"), (r"gbp|£|pounds?", "GBP"), (r"azn|₼|manat", "AZN"),
]


def _para_kodu(metin: str) -> str:
    katli = _bosluk(katla(metin))
    for desen, kod in _PARA_KODU:
        if re.fullmatch(desen, katli):
            return kod
    return katli.upper()


def sayi_coz(metin: str, dil: str) -> Optional[Decimal]:
    s = re.sub(r"[\s  ]", "", metin)
    try:
        if "," in s and "." in s:
            ondalik = "," if s.rfind(",") > s.rfind(".") else "."
            binlik = "." if ondalik == "," else ","
            return Decimal(s.replace(binlik, "").replace(ondalik, "."))
        for ayrac in (",", "."):
            if ayrac in s:
                parcalar = s.split(ayrac)
                ingilizce_binlik = (ayrac == "," and dil == "en") or (ayrac == "." and dil != "en")
                if len(parcalar) > 2 or (len(parcalar[-1]) == 3 and ingilizce_binlik):
                    return Decimal(s.replace(ayrac, ""))
                return Decimal(s.replace(",", "."))
        return Decimal(s)
    except InvalidOperation:
        return None


def _degerler(p: MetinParagrafi, i: int, dil: str, yasak: Sequence[Tuple[int, int]]) -> Dict[str, List[Tuple[str, Kanit]]]:
    """Paragraftaki tarih, tutar, oran ve yalın sayılar (kişisel veri ve atıf aralıkları hariç)."""
    metin, katli = p.metin, katla(p.metin)
    alinan = list(yasak)
    sonuc: Dict[str, List[Tuple[str, Kanit]]] = defaultdict(list)

    def bos_mu(bas, son):
        return not any(a < son and bas < b for a, b in alinan)

    def ekle(tur, deger, bas, son, i):
        alinan.append((bas, son))
        sonuc[tur].append((deger, Kanit(i, bas, son)))

    for desen, bicim in _TARIH_DESENLERI:
        for m in desen.finditer(katli):
            if not bos_mu(*m.span()):
                continue
            g = m.groups()
            try:
                if bicim == "ymd":
                    y, a, g_ = int(g[0]), int(g[1]), int(g[2])
                elif bicim == "dmy":
                    g_, a, y = int(g[0]), int(g[1]), int(g[2])
                    if dil == "en" and g_ <= 12 < a:
                        g_, a = a, g_
                elif bicim == "d_ay_y":
                    g_, a, y = int(g[0]), _AY_ADI[g[1]], int(g[2])
                else:
                    a, g_, y = _AY_ADI[g[0]], int(g[1]), int(g[2])
            except (KeyError, ValueError):
                continue
            if 1 <= a <= 12 and 1 <= g_ <= 31:
                ekle("tarih", f"{y:04d}-{a:02d}-{g_:02d}", *m.span(), i)
    for m in _TUTAR.finditer(metin):
        if not bos_mu(*m.span()):
            continue
        para, sayi = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
        deger = sayi_coz(sayi, dil)
        if deger is not None:
            ekle("tutar", f"{deger.normalize():f} {_para_kodu(para)}", *m.span(), i)
    for m in _ORAN.finditer(metin):
        if not bos_mu(*m.span()):
            continue
        deger = sayi_coz(next(g for g in m.groups() if g), dil)
        if deger is not None:
            ekle("oran", f"%{deger.normalize():f}", *m.span(), i)
    for m in _YALIN.finditer(metin):
        if not bos_mu(*m.span()):
            continue
        deger = sayi_coz(m.group(1), dil)
        if deger is not None:
            ekle("sayi", f"{deger.normalize():f}", *m.span(), i)
    return sonuc


def iki_dilli_tablolar(paragraflar: Sequence[MetinParagrafi]) -> Dict[int, Tuple[str, str]]:
    """Tablo no → (sol sütun dili, sağ sütun dili); yalnız iki sütunu farklı dilde olan tablolar."""
    hucre_metni: Dict[int, Dict[Tuple[int, int], List[str]]] = defaultdict(lambda: defaultdict(list))
    for p in paragraflar:
        if p.tablo and p.metin.strip():
            hucre_metni[p.tablo[0]][(p.tablo[1], p.tablo[2])].append(p.metin)
    sonuc = {}
    for tablo, hucreler in hucre_metni.items():
        satirlar: Dict[int, Dict[int, str]] = defaultdict(dict)
        for (s, h), metinler in hucreler.items():
            satirlar[s][h] = " ".join(metinler)
        ikili = [s for s in satirlar.values() if len(s) == 2]
        if len(ikili) < 2 or len(ikili) < 0.6 * len(satirlar):
            continue
        sutunlar = sorted({h for s in ikili for h in s})
        if len(sutunlar) != 2:
            continue
        sol = dil_tahmini(" ".join(s[sutunlar[0]] for s in ikili))
        sag = dil_tahmini(" ".join(s[sutunlar[1]] for s in ikili))
        if sol and sag and sol != sag:
            sonuc[tablo] = (sol, sag)
    return sonuc


def _iki_dil_bulgulari(paragraflar, varlik_araliklari, atif_listesi) -> Tuple[List[TutarlilikBulgusu], int]:
    tablolar = iki_dilli_tablolar(paragraflar)
    if not tablolar:
        return [], 0
    bulgular, satir_sayisi = [], 0
    hucreler: Dict[Tuple[int, int], Dict[int, List[int]]] = defaultdict(lambda: defaultdict(list))
    for i, p in enumerate(paragraflar):
        if p.tablo and p.tablo[0] in tablolar:
            hucreler[(p.tablo[0], p.tablo[1])][p.tablo[2]].append(i)
    atif_paragraf: Dict[int, List[Atif]] = defaultdict(list)
    for a in atif_listesi:
        atif_paragraf[a.paragraf].append(a)
    adlar = {"tutar": ("iki_dil_tutar", "yüksek", "tutar"), "oran": ("iki_dil_oran", "yüksek", "oran"),
             "tarih": ("iki_dil_tarih", "yüksek", "tarih"), "sayi": ("iki_dil_sayi", "orta", "sayı"),
             "atif": ("iki_dil_atif", "yüksek", "atıf")}
    for (tablo, satir), sutunlar in sorted(hucreler.items()):
        if len(sutunlar) != 2:
            continue
        diller = tablolar[tablo]
        sol_no, sag_no = sorted(sutunlar)
        taraflar = []
        for dil, no in zip(diller, (sol_no, sag_no)):
            degerler: Dict[str, List[Tuple[str, Kanit]]] = defaultdict(list)
            etiket = None
            for j in sutunlar[no]:
                p = paragraflar[j]
                yasak = list(varlik_araliklari.get(j, ())) + [(a.bas, a.son) for a in atif_paragraf.get(j, ())]
                if etiket is None and p.metin.strip():
                    cozulen = etiket_coz(p.numara or "") or etiket_coz(p.metin)
                    etiket_yeri = None if p.numara else (_MADDE_BASI.match(p.metin) or _NUMARA_BASI.match(p.metin))
                    if cozulen and cozulen[0] in ("madde", "yol"):
                        if etiket_yeri:
                            yasak.append(etiket_yeri.span())
                            kanit = Kanit(j, etiket_yeri.start(), etiket_yeri.end())
                        else:
                            kanit = Kanit(j, *_sozcuk_sinirli(p.metin, 0, min(len(p.metin), 30)))
                        etiket = (cozulen[1], kanit)
                for tur, liste in _degerler(p, j, dil, yasak).items():
                    degerler[tur].extend(liste)
                for a in atif_paragraf.get(j, ()):
                    degerler["atif"].append((a.yol + "".join(f"({b})" for b in a.bentler), Kanit(j, a.bas, a.son)))
            taraflar.append((etiket, degerler))
        satir_sayisi += 1
        (sol_etiket, sol), (sag_etiket, sag) = taraflar
        if sol_etiket and sag_etiket and sol_etiket[0] != sag_etiket[0]:
            bulgular.append(TutarlilikBulgusu(
                "iki_dil_madde", "yüksek",
                f"Tablo {tablo}, satır {satir}: sol sütunda madde {sol_etiket[0]}, sağ sütunda madde {sag_etiket[0]} "
                "numarası var ({0} / {1}).", [sol_etiket[1], sag_etiket[1]]))
        for tur, (kural, onem, ad) in adlar.items():
            a, b = Counter(d for d, _ in sol.get(tur, ())), Counter(d for d, _ in sag.get(tur, ()))
            if a == b:
                continue
            yalniz_sol = [k for d, k in sol.get(tur, ()) if (a - b)[d] > 0]
            yalniz_sag = [k for d, k in sag.get(tur, ()) if (b - a)[d] > 0]
            if tur == "sayi" and (not yalniz_sol or not yalniz_sag):
                continue  # rakamın bir sütunda yazıyla yazılması olağandır; yalnız iki yanda farklı rakam bildirilir
            if yalniz_sol and yalniz_sag:
                sablon = f"Tablo {tablo}, satır {satir}: {ad} sütunlarda farklı: sol sütunda {{0}}, sağ sütunda {{1}}."
                kanit = [yalniz_sol[0], yalniz_sag[0]]
            elif yalniz_sol:
                sablon = f"Tablo {tablo}, satır {satir}: sol sütundaki {ad} {{0}} sağ sütunda yok."
                kanit = [yalniz_sol[0]]
            else:
                sablon = f"Tablo {tablo}, satır {satir}: sağ sütundaki {ad} {{0}} sol sütunda yok."
                kanit = [yalniz_sag[0]]
            bulgular.append(TutarlilikBulgusu(kural, onem, sablon, kanit))
    return bulgular, satir_sayisi


# -- denetim -----------------------------------------------------------------------------------------
def _varliklari_esle(paragraflar: Sequence[MetinParagrafi], varliklar) -> List[Tuple[Kanit, str, str]]:
    """Düz metindeki varlık aralıklarını paragraf aralığına çevirir: [(kanıt, varlık türü, gerçek metin)]."""
    baslar, dizin = [], []
    for i, p in enumerate(paragraflar):
        eslenen = [k for k in p.konumlar if k >= 0]
        if eslenen:
            baslar.append(eslenen[0])
            dizin.append(i)
    sirali = sorted(zip(baslar, dizin))
    baslar = [b for b, _ in sirali]
    dizin = [i for _, i in sirali]
    tersler: Dict[int, Dict[int, int]] = {}
    sonuc = []
    for bas, son, varlik in varliklar:
        k = bisect_right(baslar, bas) - 1
        if k < 0:
            continue
        i = dizin[k]
        ters = tersler.get(i)
        if ters is None:
            ters = tersler[i] = {d: j for j, d in enumerate(paragraflar[i].konumlar) if d >= 0}
        if bas not in ters or (son - 1) not in ters:
            continue
        pb, ps = ters[bas], ters[son - 1] + 1
        sonuc.append((Kanit(i, pb, ps), varlik, paragraflar[i].metin[pb:ps]))
    return sonuc


@dataclass
class DenetimSonucu:
    bulgular: List[TutarlilikBulgusu]
    notlar: List[str]
    yapi: MaddeYapisi
    sayilar: Dict[str, int] = field(default_factory=dict)


def denetle(paragraflar: Sequence[MetinParagrafi], varliklar: Iterable[Tuple[int, int, str]] = ()) -> DenetimSonucu:
    """varliklar: maskeleme bulguları (düz başlangıç, düz bitiş, varlık türü)."""
    varliklar_p = _varliklari_esle(paragraflar, list(varliklar))
    varlik_araliklari: Dict[int, List[Tuple[int, int]]] = defaultdict(list)
    for k, _, _ in varliklar_p:
        varlik_araliklari[k.paragraf].append((k.bas, k.son))
    bulgular: List[TutarlilikBulgusu] = []
    notlar: List[str] = []

    # 1) Tanımlı terimler
    tanim_listesi = tanimlar(paragraflar)
    katlilar = [katla(p.metin) for p in paragraflar]
    tanim_araliklari: Dict[int, List[Tuple[int, int]]] = defaultdict(list)
    for t in tanim_listesi:
        tanim_araliklari[t.kanit.paragraf].append((t.kanit.bas, t.kanit.son))
    gorulen = set()
    for t in tanim_listesi:
        if t.anahtar in gorulen:
            continue
        gorulen.add(t.anahtar)
        if not _kullanimlar(t, paragraflar, katlilar, tanim_araliklari):
            bulgular.append(TutarlilikBulgusu(
                "terim_kullanilmiyor", "orta",
                "{0} tanımlanmış ama belgenin başka bir yerinde kullanılmamış.", [t.kanit]))
    if len({t.anahtar for t in tanim_listesi}) >= 2:
        for kanitlar, _ in _tanimsiz_terimler(paragraflar, tanim_listesi, varlik_araliklari)[:_AZAMI_TANIMSIZ]:
            bulgular.append(TutarlilikBulgusu(
                "terim_tanimsiz", "düşük",
                f"{{0}} büyük harfle, tanımlı terim gibi {len(kanitlar)} kez kullanılmış ama belgede tanımı yok.",
                [kanitlar[0]]))
    else:
        notlar.append("Belgede tırnak içinde tanımlanmış terim azdı; tanımsız terim denetimi yapılmadı.")

    # 2) İç atıflar
    yapi = MaddeYapisi(paragraflar)
    atif_listesi = atiflar(paragraflar)
    if not yapi.maddeler:
        if atif_listesi:
            notlar.append("Belgede madde numarası bulunamadı (otomatik numaralandırma okunamamış olabilir); "
                          "iç atıflar denetlenmedi.")
    else:
        for a in atif_listesi:
            kural = yapi.var_mi(a)
            if kural:
                bulgular.append(TutarlilikBulgusu(
                    kural, "yüksek" if kural == "atif_madde_yok" else "orta",
                    "{0} atfı yapılmış ama belgede bu " + ("madde" if kural == "atif_madde_yok" else "alt madde, fıkra ya da bent")
                    + " yok.", [Kanit(a.paragraf, a.bas, a.son)]))

    # 3) Taraflar
    bulgular.extend(_taraf_bulgulari(paragraflar, tanim_listesi, varliklar_p))

    # 4) Çift dilli tablolar
    iki_dil, satir_sayisi = _iki_dil_bulgulari(paragraflar, varlik_araliklari, atif_listesi)
    bulgular.extend(iki_dil)
    if not satir_sayisi:
        notlar.append("Çift dilli (iki sütunu farklı dilde) tablo bulunamadı; sütun karşılaştırması yapılmadı.")
    sayilar = {"tanimli_terim": len({t.anahtar for t in tanim_listesi}), "ic_atif": len(atif_listesi),
               "sirket_unvani": sum(1 for _, v, _ in varliklar_p if v == "TR_TUZEL_KISI"),
               "iki_dilli_satir": satir_sayisi}
    return DenetimSonucu(bulgular, notlar, yapi, sayilar)


# -- rapor ---------------------------------------------------------------------------------------------
def gercek_metin(paragraflar: Sequence[MetinParagrafi]) -> Callable[[Kanit], str]:
    return lambda k: paragraflar[k.paragraf].metin[k.bas:k.son]


def maskeli_metin(paragraflar: Sequence[MetinParagrafi], duz_metin: str,
                  degisiklikler: Sequence[Tuple[int, int, str]]) -> Callable[[Kanit], str]:
    """Kanıt aralığının maskeli karşılığı: maskeleme değişiklikleri konumla uygulanır; aralık bir değeri
    kesiyorsa değerin tamamı etikete dönüşür (yarım değer gitmez)."""
    sirali = sorted(degisiklikler)
    baslar = [d[0] for d in sirali]

    def duz(bas: int, son: int) -> str:
        i = bisect_left(baslar, bas)
        while i > 0 and sirali[i - 1][1] > bas:
            i -= 1
        parcalar, imlec = [], bas
        while i < len(sirali) and sirali[i][0] < son:
            d_bas, d_son, etiket = sirali[i]
            if d_bas > imlec:
                parcalar.append(duz_metin[imlec:d_bas])
            parcalar.append(etiket)
            imlec = max(imlec, d_son)
            i += 1
        if imlec < son:
            parcalar.append(duz_metin[imlec:son])
        return "".join(parcalar)

    def metin(k: Kanit) -> str:
        p = paragraflar[k.paragraf]
        eslenen = [d for d in p.konumlar[k.bas:k.son] if d >= 0]
        if not eslenen:
            return re.sub(r"[^\s]", "", p.metin[k.bas:k.son])  # yalnız sekme/satır sonu
        return duz(eslenen[0], eslenen[-1] + 1)

    return metin


def yer_metni(paragraflar: Sequence[MetinParagrafi], yapi: MaddeYapisi, k: Kanit,
              diller: Optional[Dict[int, Tuple[str, str]]] = None) -> str:
    p = paragraflar[k.paragraf]
    parcalar = []
    if yapi.yer and yapi.yer[k.paragraf]:
        parcalar.append(f"Madde {yapi.yer[k.paragraf]}")
    if p.tablo:
        tablo, satir, sutun = p.tablo
        dil = (diller or {}).get(tablo)
        ek = f" ({dil[0 if sutun == 1 else 1].upper()})" if dil and sutun in (1, 2) else ""
        parcalar.append(f"Tablo {tablo}, satır {satir}, sütun {sutun}{ek}")
    elif not parcalar:
        parcalar.append(f"paragraf {k.paragraf + 1}")
    return " · ".join(parcalar)


def rapor_yaz(sonuc: DenetimSonucu, paragraflar: Sequence[MetinParagrafi], metin_al: Callable[[Kanit], str]) -> Dict:
    diller = iki_dilli_tablolar(paragraflar)
    bulgular = sorted(sonuc.bulgular, key=lambda b: (_ONEM_SIRASI[b.onem], b.kanitlar[0].paragraf, b.kanitlar[0].bas))
    ogeler = []
    for no, b in enumerate(bulgular, start=1):
        degerler = [f"“{metin_al(k).strip()}”" for k in b.kanitlar]
        ilk = b.kanitlar[0]
        p = paragraflar[ilk.paragraf]
        a, z = _sozcuk_sinirli(p.metin, max(0, ilk.bas - 80), min(len(p.metin), ilk.son + 80))
        alinti = metin_al(Kanit(ilk.paragraf, a, z)).strip()
        ogeler.append({
            "no": no,
            "kural": KURAL_ADLARI[b.kural],
            "onem": b.onem,
            "aciklama": b.sablon.format(*degerler),
            "yer": yer_metni(paragraflar, sonuc.yapi, ilk, diller),
            "alinti": ("…" if a > 0 else "") + alinti + ("…" if z < len(p.metin) else ""),
        })
    sayim = Counter(b.onem for b in bulgular)
    return {
        "ozet": {"toplam": len(bulgular), "yuksek": sayim.get("yüksek", 0), "orta": sayim.get("orta", 0),
                 "dusuk": sayim.get("düşük", 0)},
        "denetlenen": sonuc.sayilar,
        "bulgular": ogeler,
        "notlar": sonuc.notlar,
    }


# -- belgeden paragraflar ------------------------------------------------------------------------------
def duz_paragraflar(metin: str) -> List[MetinParagrafi]:
    """Word dışı belgeler (UDF, PDF, metin): her satır bir paragraf."""
    sonuc, bas = [], 0
    for satir in metin.split("\n"):
        sonuc.append(MetinParagrafi(satir, range(bas, bas + len(satir))))
        bas += len(satir) + 1
    return sonuc


def docx_paragraflari(docx_belge) -> List[MetinParagrafi]:
    """`docx.oku` sonucundan: Word yapısı (tablo hücresi, otomatik numara, başlık) + maskelemedeki düz konumlar."""
    from .docx_agac import WordBelgesi

    girdiler = {b.filename: v for b, v in docx_belge.girdiler}
    word = WordBelgesi(girdiler)
    dugum = {d.xml_bas: d.metin_bas for d in docx_belge.dugumler if d.parca == "word/document.xml"}
    sonuc = []
    for p in word.sirali:
        konumlar: List[int] = []
        for run in p.runlar:
            for parca in run.parcalar:
                if parca.metin_mi and parca.metin:
                    bas = dugum.get(parca.oge.ic_bas)
                    konumlar.extend(range(bas, bas + len(parca.metin)) if bas is not None else [-1] * len(parca.metin))
                else:
                    konumlar.extend([-1] * len(parca.metin))
        sonuc.append(MetinParagrafi(p.metin, konumlar, p.tablo, p.numara, p.baslik))
    return sonuc

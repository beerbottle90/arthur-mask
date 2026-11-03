"""Çıkış kapısı: Claude'a giden her araç yanıtının son denetimi.

Maskeleme olasılıksaldır; bu katman ikinci bir güvencedir. Yanıttaki bütün metinler,
etkin dosyanın kasasındaki gerçek değerlere (ve özgün belge adlarına) karşı büyük/küçük
harf ve aksan duyarsız taranır. Eşleşen her geçiş, gönderilmeden önce kendi etiketiyle
değiştirilir. Böylece bir belgede tespit edilen bir ad, başka bir belgede ya da başka bir
biçimde tespit edilemese bile Claude'a gitmez.

Karşılaştırma normalleştirilmiş metinde yapılır: ayrık aksanlar, yumuşak tire ve sıfır
genişlikli karakterler düşer, tam genişlikli harfler açılır, satır sonunda tireyle bölünmüş
sözcük birleşir. Değiştirme yine özgün metinde, eşleşmenin özgün konumunda yapılır.

Sınır: kasada hiç bulunmayan (hiçbir belgede tespit edilmemiş) bir değeri bu katman
tanıyamaz; onun güvencesi tespit katmanı ve avukat incelemesidir.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from .kasa import Kasa
from .turkce import ascii_kucuk

_EN_AZ_HARF = 3
_EN_AZ_RAKAM = 6
_AYRAC = r"[\s.\-–—/(),_]*"
_AYRAC_SINIFI = r"[\s.\-–—/(),_]"
# Harf ve rakam kümeleri arasında (plaka "34ABC123", adres "No:10"): biraz daha geniş ayraç.
_KUME_AYRACI = r"[\s.\-–—/(),_:;]*"
# Harf ya da rakam (alt çizgi değil); Türkçe dışı harfleri de kapsar.
_ONCE = r"(?<![^\W_])"
_SONRA = r"(?![^\W_])"
_TIRELER = "-‐‑"
_SATIR_SONU_TIRESI = re.compile(r"[-‐‑][ \t\r]*\n")
# Hızlı yol: yalnız bu karakterlerden oluşan metin, uzunluk koruyan katlamayla normalleştirilir.
_BASIT = re.compile(r"[\t\n\r\x20-\x7eçğıöşüâîûəÇĞİÖŞÜÂÎÛƏ]*")


def _katla(metin: str) -> str:
    """Uzunluk koruyan katlama (konumlar özgün metne birebir eşlensin)."""
    katli = ascii_kucuk(metin)
    if len(katli) == len(metin):
        return katli
    return "".join(ascii_kucuk(h)[:1] or h for h in metin)


def _gorunmez(h: str) -> bool:
    """Ayrık aksan, yumuşak tire, sıfır genişlikli boşluk/birleştirici, yön işareti, BOM."""
    kategori = unicodedata.category(h)
    return kategori == "Cf" or kategori.startswith("M")


def normallestir(metin: str) -> Tuple[str, Sequence[int]]:
    """(karşılaştırma metni, konumlar): konumlar[i], karşılaştırma metnindeki i. karakterin özgün metindeki yeri;
    son eleman özgün metnin uzunluğudur."""
    if _BASIT.fullmatch(metin) and not _SATIR_SONU_TIRESI.search(metin):
        return _katla(metin), range(len(metin) + 1)
    cikti: List[str] = []
    konum: List[int] = []
    i, n = 0, len(metin)
    while i < n:
        h = metin[i]
        # Satır sonunda tireyle bölünmüş sözcük: "Kara-\nbacak" → "karabacak".
        if h in _TIRELER and cikti and cikti[-1].isalpha():
            j = i + 1
            while j < n and metin[j] in " \t\r":
                j += 1
            if j < n and metin[j] == "\n":
                j += 1
                while j < n and (metin[j].isspace() or _gorunmez(metin[j])):
                    j += 1
                if j < n and metin[j].isalpha():
                    i = j
                    continue
        if _gorunmez(h):
            i += 1
            continue
        for parca in unicodedata.normalize("NFKD", h):
            if _gorunmez(parca):
                continue
            for k in ascii_kucuk(parca):
                if not _gorunmez(k):
                    cikti.append(k)
                    konum.append(i)
        i += 1
    konum.append(n)
    return "".join(cikti), konum


def _rakamlar(deger: str) -> str:
    return re.sub(r"[^0-9]", "", deger)


def _rakam_deseni(rakam: str) -> str:
    return _AYRAC.join(re.escape(r) for r in rakam)


def _telefon_govdesi(rakam: str, tur: str) -> str:
    """Türkiye telefonunun 10 haneli ulusal kısmı; telefon değilse boş."""
    if len(rakam) == 12 and rakam.startswith("90"):
        ulusal = rakam[2:]
    elif len(rakam) == 11 and rakam.startswith("0"):
        ulusal = rakam[1:]
    elif len(rakam) == 10 and tur == "TELEFON":
        ulusal = rakam
    else:
        return ""
    return ulusal if ulusal[0] != "0" else ""


def _sozcuk_deseni(sozcuk: str) -> str:
    """Tireli ad ("Yılmaz-Demir") boşluklu, tiresiz ya da satır sonunda bölünmüş yazılsa da eşleşsin."""
    parcalar = [p for p in re.split(f"[{_TIRELER}]", sozcuk) if p]
    return r"\s*[-‐‑]?\s*".join(re.escape(p) for p in parcalar)


def _deger_deseni(deger: str, tur: str = "") -> Tuple[str, bool]:
    """(desen, büyük harf şartı). Desen normalleştirilmiş metinde aranır; boş desen = atla."""
    deger = normallestir(deger)[0].strip()
    rakam = _rakamlar(deger)
    harf = "".join(h for h in deger if h.isalpha())
    sikisik = re.sub(_AYRAC_SINIFI, "", deger)

    ulusal = "" if harf else _telefon_govdesi(rakam, tur)
    if ulusal:
        # +90 532 ..., 0090 532 ..., 0532 ..., (0532) ..., 532 ...
        onek = rf"(?:(?:\+|00)?{_AYRAC}9{_AYRAC}0{_AYRAC}|0{_AYRAC})?"
        return rf"(?<![0-9]){onek}{_rakam_deseni(ulusal)}(?![0-9])", False

    iban = re.fullmatch(r"([a-z])([a-z])([0-9]{12,})", sikisik)
    if iban:
        # Ülke öneki yazılmasa da ("33 0006 ...") ya da bir sözcüğe bitişse de ("IBANTR33...") yakalanır.
        ulke = rf"(?:{iban.group(1)}{_AYRAC}{iban.group(2)}{_AYRAC})?"
        return rf"(?<![0-9]){ulke}{_rakam_deseni(iban.group(3))}(?![0-9])", False

    if len(rakam) >= _EN_AZ_RAKAM and len(rakam) >= len(harf):
        dosya_nolari = [y + n for y, n in re.findall(r"(?<![0-9])([0-9]{4})\s*[/\-]\s*([0-9]{1,7})(?![0-9])", deger)]
        dosya_nolari = [d for d in dosya_nolari if len(d) >= _EN_AZ_RAKAM]
        if harf and dosya_nolari:
            # "2024/5678 E." ile "Esas 2024/5678": ayırt edici olan sayıdır, yanındaki işaret değil.
            secenekler = "|".join(_rakam_deseni(d) for d in dosya_nolari)
            return rf"(?<![0-9])(?:{secenekler})(?![0-9])", False
        # TCKN, telefon, IBAN, dosya no: ayraçlar (boşluk, nokta, tire) değişse de yakala.
        if harf:
            govde = _AYRAC.join(re.escape(h) for h in sikisik)
            return rf"{_ONCE}{govde}(?![0-9])", False
        # Yalnız rakamdan oluşan değer önündeki harfe bakmaz: "TC12345678950" de yakalanır.
        return rf"(?<![0-9]){_rakam_deseni(rakam)}(?![0-9])", False

    if rakam:
        # Harf ve rakam kümeleri (plaka "34 ABC 123", adres "No: 10"): kümeler arasında ayraç olsa da olmasa da.
        kumeler = re.findall(r"[^\W\d_]+|[0-9]+", deger)
        if len("".join(kumeler)) < 4:
            return "", False
        return _ONCE + _KUME_AYRACI.join(re.escape(k) for k in kumeler) + _SONRA, False

    sozcukler = [s for s in deger.split() if _sozcuk_deseni(s)]
    if not sozcukler or len(harf) < _EN_AZ_HARF:
        return "", False
    govde = ""
    for i, sozcuk in enumerate(sozcukler):
        if i:
            # Baş harften sonra boşluk yazılmayabilir: "M.Yılmaz".
            govde += r"\s*" if sozcukler[i - 1].endswith(".") else r"\s+"
        govde += _sozcuk_deseni(sozcuk)
    # Tek sözcüklü ad ("Kara") yalnız büyük harfle başladığında sayılır: "kara yolu" dokunulmaz. Harf dışı işaret
    # taşıyan tek sözcük (e-posta, KEP, alan adı, kullanıcı adı) küçük harfle yazılır; şart ona uygulanmaz.
    return rf"{_ONCE}{govde}{_SONRA}", len(sozcukler) == 1 and sozcukler[0].isalpha()


def ad_bicimleri(deger: str) -> List[str]:
    """Bir kişi adının kısmi yazımları: soyadı, ad + soyadı (ikinci ad düşmüş), baş harf + soyadı."""
    sozcukler = normallestir(deger)[0].split()
    if len(sozcukler) < 2 or not all(s.isalpha() for s in sozcukler):
        return []
    ilk, soyad = sozcukler[0], sozcukler[-1]
    bicimler = [f"{ilk[0]}. {soyad}"]
    if len(soyad) >= _EN_AZ_HARF:
        bicimler.append(soyad)
    if len(sozcukler) >= 3:
        bicimler.append(f"{ilk} {soyad}")
        bicimler.append(" ".join(s[0] + "." for s in sozcukler[:-1]) + " " + soyad)
    return bicimler


@dataclass
class DenetimSonucu:
    yakalanan: int
    turler: Dict[str, int]


class CikisDenetimi:
    def __init__(self, kasa: Kasa, ek_degerler: Iterable[Tuple[str, str]] = ()):
        adaylar: List[Tuple[str, str, str]] = []
        for kayit in kasa.kayitlar.values():
            for deger in kayit.degerler:
                adaylar.append((deger, kayit.etiket, kayit.tur))
        for deger, yerine in ek_degerler:
            adaylar.append((deger, yerine, "BELGE_ADI"))
        # Kişinin kısmi adı ("Mehmet Ali Yılmaz" → "Yılmaz", "M. Yılmaz"). Aynı kısmi ad iki kişiye çıkıyorsa
        # ya da başka bir kaydın kendi değeriyse eklenmez: yanlış etiket Claude'u yanıltır.
        acik = {normallestir(d)[0].strip() for d, _, _ in adaylar}
        turetilen: Dict[str, set] = {}
        for kayit in kasa.kayitlar.values():
            if kayit.varlik != "PERSON":
                continue
            for deger in kayit.degerler:
                for bicim in ad_bicimleri(deger):
                    turetilen.setdefault(bicim, set()).add((kayit.etiket, kayit.tur))
        for bicim, sahipler in turetilen.items():
            if len(sahipler) == 1 and bicim not in acik:
                etiket, tur = next(iter(sahipler))
                adaylar.append((bicim, etiket, tur))
        # Uzun değer önce: "Mehmet Ali Yılmaz" "Yılmaz"dan önce eşleşsin.
        adaylar.sort(key=lambda a: len(a[0]), reverse=True)
        self._desenler = []
        gorulen = set()
        for deger, yerine, tur in adaylar:
            desen, buyuk_sart = _deger_deseni(deger, tur)
            if desen and (desen, yerine) not in gorulen:
                gorulen.add((desen, yerine))
                self._desenler.append((re.compile(desen), buyuk_sart, yerine, tur))

    def araliklar(self, metin: str) -> List[Tuple[int, int]]:
        """Kasadaki değerlerin metindeki (özgün) konumları; metin parçalara bölünürken bir değerin ortasından
        kesilmesin diye."""
        sonuc: List[Tuple[int, int]] = []
        if not self._desenler or not metin:
            return sonuc
        normal, konum = normallestir(metin)
        for desen, buyuk_sart, _, _ in self._desenler:
            for m in desen.finditer(normal):
                if m.end() == m.start():
                    continue
                bas, son = konum[m.start()], konum[m.end() - 1] + 1
                if not buyuk_sart or metin[bas].isupper():
                    sonuc.append((bas, son))
        return sonuc

    def temizle(self, metin: str) -> Tuple[str, Dict[str, int]]:
        temiz, bulunanlar = self.tara(metin)
        turler: Dict[str, int] = {}
        for tur, _, _ in bulunanlar:
            turler[tur] = turler.get(tur, 0) + 1
        return temiz, turler

    def tara(self, metin: str) -> Tuple[str, List[Tuple[str, str, str]]]:
        """(temizlenmiş metin, [(tür, etiket, metindeki gerçek değer)])."""
        bulunanlar: List[Tuple[str, str, str]] = []
        if not self._desenler or not metin:
            return metin, bulunanlar
        normal, konum = normallestir(metin)
        for desen, buyuk_sart, yerine, tur in self._desenler:
            parcalar, imlec = [], 0
            for m in desen.finditer(normal):
                if m.end() == m.start():
                    continue
                bas, son = konum[m.start()], konum[m.end() - 1] + 1
                # Eşleşmenin hemen ardından gelen ayrık aksan ya da görünmez karakter de değerle birlikte gider.
                while son < len(metin) and _gorunmez(metin[son]):
                    son += 1
                if bas < imlec or (buyuk_sart and not metin[bas].isupper()):
                    continue
                parcalar.append(metin[imlec:bas])
                parcalar.append(yerine)
                bulunanlar.append((tur, yerine, metin[bas:son]))
                imlec = son
            if parcalar:
                metin = "".join(parcalar) + metin[imlec:]
                normal, konum = normallestir(metin)
        return metin, bulunanlar

    def yanit_temizle(self, yanit: Any) -> Tuple[Any, DenetimSonucu]:
        toplam: Dict[str, int] = {}

        def gez(oge):
            if isinstance(oge, str):
                temiz, turler = self.temizle(oge)
                for t, n in turler.items():
                    toplam[t] = toplam.get(t, 0) + n
                return temiz
            if isinstance(oge, dict):
                return {gez(k): gez(v) for k, v in oge.items()}
            if isinstance(oge, (list, tuple)):
                return [gez(v) for v in oge]
            return oge

        temiz = gez(yanit)
        return temiz, DenetimSonucu(sum(toplam.values()), toplam)

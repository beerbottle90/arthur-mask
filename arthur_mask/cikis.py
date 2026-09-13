"""Çıkış kapısı: Claude'a giden her araç yanıtının son denetimi.

Maskeleme olasılıksaldır; bu katman ikinci bir güvencedir. Yanıttaki bütün metinler,
etkin dosyanın kasasındaki gerçek değerlere (ve özgün belge adlarına) karşı büyük/küçük
harf ve aksan duyarsız taranır. Eşleşen her geçiş, gönderilmeden önce kendi etiketiyle
değiştirilir. Böylece bir belgede tespit edilen bir ad, başka bir belgede ya da başka bir
biçimde tespit edilemese bile Claude'a gitmez.

Sınır: kasada hiç bulunmayan (hiçbir belgede tespit edilmemiş) bir değeri bu katman
tanıyamaz; onun güvencesi tespit katmanı ve avukat incelemesidir.
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Tuple

from .kasa import Kasa
from .turkce import ascii_kucuk

_EN_AZ_HARF = 4
_EN_AZ_RAKAM = 6
_AYRAC = r"[\s.\-/()]*"


def _katla(metin: str) -> str:
    """Uzunluk koruyan katlama (konumlar özgün metne birebir eşlensin)."""
    katli = ascii_kucuk(metin)
    if len(katli) == len(metin):
        return katli
    return "".join(ascii_kucuk(h)[:1] or h for h in metin)


def _rakamlar(deger: str) -> str:
    return re.sub(r"\D", "", deger)


def _deger_deseni(deger: str) -> Tuple[str, bool]:
    """(desen, büyük harf şartı). Desen katlanmış metinde aranır; boş desen = atla."""
    deger = deger.strip()
    rakam = _rakamlar(deger)
    harf = re.sub(r"[^\w]|\d|_", "", deger)
    if len(rakam) >= _EN_AZ_RAKAM and len(rakam) >= len(harf):
        # TCKN, telefon, IBAN, dosya no: ayraçlar (boşluk, nokta, tire) değişse de yakala.
        govde = _AYRAC.join(re.escape(r) for r in rakam)
        if harf:
            govde = _AYRAC.join(re.escape(h) for h in re.sub(r"[\s.\-/()]", "", _katla(deger)))
        return rf"(?<![0-9a-z]){govde}(?![0-9])", False
    sozcukler = _katla(deger).split()
    if not sozcukler or len("".join(sozcukler)) < _EN_AZ_HARF:
        return "", False
    govde = r"\s+".join(re.escape(s) for s in sozcukler)
    # Tek sözcüklü değer ("Kara") yalnız büyük harfle başladığında sayılır: "kara yolu" dokunulmaz.
    return rf"(?<![0-9a-z]){govde}(?![0-9a-z])", len(sozcukler) == 1


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
        # Uzun değer önce: "Mehmet Ali Yılmaz" "Yılmaz"dan önce eşleşsin.
        adaylar.sort(key=lambda a: len(a[0]), reverse=True)
        self._desenler = []
        for deger, yerine, tur in adaylar:
            desen, buyuk_sart = _deger_deseni(deger)
            if desen:
                self._desenler.append((re.compile(desen), buyuk_sart, yerine, tur))

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
        katli = _katla(metin)
        for desen, buyuk_sart, yerine, tur in self._desenler:
            parcalar, imlec = [], 0
            for m in desen.finditer(katli):
                if buyuk_sart and not metin[m.start()].isupper():
                    continue
                parcalar.append(metin[imlec:m.start()])
                parcalar.append(yerine)
                bulunanlar.append((tur, yerine, metin[m.start():m.end()]))
                imlec = m.end()
            if parcalar:
                metin = "".join(parcalar) + metin[imlec:]
                katli = _katla(metin)
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

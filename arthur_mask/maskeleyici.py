"""Bulguları tutarlı maske etiketleriyle değiştirir ve yapay zekâ çıktısını geri açar."""

import re
from typing import List, Sequence, Tuple

from .ek_uyumu import ek_uyumla
from .kasa import Kasa
from .motor import Bulgu

Degisiklik = Tuple[int, int, str]

# {{KİŞİ-01}}; modelin eklediği boşluk veya düşürdüğü baştaki sıfır tolere edilir.
ETIKET_DESENI = re.compile(r"\{\{[ \t]?([^{}\s]{1,40}?)[ \t]?-[ \t]?(\d{1,5})[ \t]?\}\}")
_EKLI_ETIKET = re.compile(ETIKET_DESENI.pattern + r"(?:(['’])([a-zçğıöşü]{1,12})(?![\w]))?")


def degisiklikleri_uygula(metin: str, degisiklikler: Sequence[Degisiklik]) -> str:
    parcalar, imlec = [], 0
    for bas, son, yeni in sorted(degisiklikler):
        if bas < imlec:
            raise ValueError("Değişiklik aralıkları çakışıyor.")
        parcalar.append(metin[imlec:bas])
        parcalar.append(yeni)
        imlec = son
    parcalar.append(metin[imlec:])
    return "".join(parcalar)


def maskele(metin: str, bulgular: Sequence[Bulgu], kasa: Kasa) -> Tuple[str, List[Degisiklik]]:
    degisiklikler = [
        (b.bas, b.son, kasa.etiket_al(b.tur, b.varlik, b.kanonik, b.metin))
        for b in bulgular
    ]
    return degisiklikleri_uygula(metin, degisiklikler), degisiklikler


def geri_acma_degisiklikleri(metin: str, kasa: Kasa) -> Tuple[List[Degisiklik], List[str]]:
    """Etiket (ve varsa kesme işaretli eki) → kasadaki asıl değer + uyumlu ek."""
    degisiklikler: List[Degisiklik] = []
    bilinmeyen = set()
    for m in _EKLI_ETIKET.finditer(metin):
        etiket = metin[m.start():metin.index("}}", m.end(2)) + 2]
        kayit = kasa.bul(etiket)
        if kayit is None:
            bilinmeyen.add(etiket)
            continue
        deger = kayit.asil
        if m.group(4):
            deger += m.group(3) + ek_uyumla(deger, m.group(4))
        degisiklikler.append((m.start(), m.end(), deger))
    return degisiklikler, sorted(bilinmeyen)


def geri_ac(metin: str, kasa: Kasa) -> Tuple[str, List[str]]:
    """Etiketleri kasadaki ilk (asıl) değerle değiştirir; kasada olmayanları raporlar."""
    degisiklikler, bilinmeyen = geri_acma_degisiklikleri(metin, kasa)
    return degisiklikleri_uygula(metin, degisiklikler), bilinmeyen

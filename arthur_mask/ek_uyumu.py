"""Geri açmada Türkçe hâl eklerinin gerçek değere göre yeniden çekimi.

Model etikete ek getirirken "{{KİŞİ-01}}" ifadesinin sesine göre çeker
("{{KİŞİ-01}}'in"); gerçek değer "Ayşe KARA" olduğunda doğru biçim "'nın"dır.
Ek zinciri bilinen biçimbirimlere ayrıştırılabiliyorsa ünlü uyumu, kaynaştırma
ünsüzü (n/y) ve sertleşme (d/t) gerçek değerin son sesine göre yeniden kurulur;
ayrıştırılamayan ya da sayı/kısaltma ile biten değerlerde ek olduğu gibi kalır.
"""

import re
from typing import List, Optional

from .turkce import tr_kucuk

_UNLULER = set("aeıioöuüâîû")
_KALIN = set("aıouâû")
_YUVARLAK = set("oöuü")
_SERT = set("fstkçşhp")

# (yüzey regex'i, şablon) — uzun olan önce denenir.
_BICIMBIRIMLER = [
    (r"[dt][ae]ki", "DAki"),
    (r"n?[ıiuü]n", "(n)In"),
    (r"[dt][ae]n", "DAn"),
    (r"[dt][ıiuü]r", "DIr"),
    (r"l[ae]r", "lAr"),
    (r"y?l[ae]", "(y)lA"),
    (r"[dt][ae]", "DA"),
    (r"y?[ae]", "(y)A"),
    (r"y?[ıiuü]", "(y)I"),
    (r"ki", "ki"),
]
_DERLENMIS = [(re.compile(desen), sablon) for desen, sablon in _BICIMBIRIMLER]


def _ayristir(ek: str) -> Optional[List[str]]:
    sablonlar, i = [], 0
    while i < len(ek):
        for desen, sablon in _DERLENMIS:
            m = desen.match(ek, i)
            if m and m.end() > i:
                sablonlar.append(sablon)
                i = m.end()
                break
        else:
            return None
    return sablonlar


def _cek(govde: str, sablon: str) -> str:
    unluler = [ch for ch in govde if ch in _UNLULER]
    son_unlu = unluler[-1] if unluler else "a"
    unluyle_biter = govde[-1] in _UNLULER
    A = "a" if son_unlu in _KALIN else "e"
    if son_unlu in _KALIN:
        I = "u" if son_unlu in _YUVARLAK else "ı"
    else:
        I = "ü" if son_unlu in _YUVARLAK else "i"
    D = "t" if govde[-1] in _SERT else "d"
    return {
        "DAki": f"{D}{A}ki",
        "(n)In": ("n" if unluyle_biter else "") + f"{I}n",
        "DAn": f"{D}{A}n",
        "DIr": f"{D}{I}r",
        "lAr": f"l{A}r",
        "(y)lA": ("y" if unluyle_biter else "") + f"l{A}",
        "DA": f"{D}{A}",
        "(y)A": ("y" if unluyle_biter else "") + A,
        "(y)I": ("y" if unluyle_biter else "") + I,
        "ki": "ki",
    }[sablon]


def ek_uyumla(deger: str, ek: str) -> str:
    """`deger` için `ek`i yeniden çeker; güvenle çekilemiyorsa `ek`i aynen döndürür."""
    son_kelime = deger.split()[-1] if deger.split() else ""
    govde = tr_kucuk(son_kelime)
    if not govde or not govde[-1].isalpha() or not any(ch in _UNLULER for ch in govde):
        return ek
    sablonlar = _ayristir(tr_kucuk(ek))
    if not sablonlar:
        return ek
    uretilen = ""
    for sablon in sablonlar:
        uretilen += _cek(govde + uretilen, sablon)
    return uretilen

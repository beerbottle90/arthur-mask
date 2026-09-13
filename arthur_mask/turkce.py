"""Türkçe'ye duyarlı büyük/küçük harf ve regex yardımcıları.

Python'un str.lower() işlevi "İ" harfini iki karaktere ("i" + birleşik nokta)
çevirir ve "I" harfini "ı" yerine "i" yapar. Bu hem eşleşmeyi hem de karakter
ofsetlerini bozar; bu modül uzunluğu koruyan Türkçe dönüşümler sağlar.
"""

import re

BUYUK = "A-ZÇĞİÖŞÜÂÎÛ"
KUCUK = "a-zçğıöşüâîû"


def tr_kucuk(metin: str) -> str:
    return metin.replace("I", "ı").replace("İ", "i").lower()


def tr_buyuk(metin: str) -> str:
    return metin.replace("i", "İ").replace("ı", "I").upper()


_ASCII_KATLAMA = str.maketrans("çğıöşüâîûÇĞİÖŞÜÂÎÛ", "cgiosuaiuCGIOSUAIU")


def ascii_katla(metin: str) -> str:
    """Maske etiketlerini karşılaştırırken aksan farklarını yok sayar."""
    return metin.translate(_ASCII_KATLAMA).upper()


def harf_duyarsiz_desen(ifade: str) -> str:
    """Bir ifadeyi Türkçe büyük/küçük harf duyarsız, uzunluk koruyan regex'e çevirir.

    Boşluklar esnek boşluğa dönüşür; kelime sınırı dışarıdan eklenir.
    """
    parcalar = []
    for karakter in ifade.strip():
        if karakter.isspace():
            if not parcalar or parcalar[-1] != r"\s+":
                parcalar.append(r"\s+")
            continue
        kucuk, buyuk = tr_kucuk(karakter), tr_buyuk(karakter)
        if kucuk == buyuk:
            parcalar.append(re.escape(karakter))
        else:
            parcalar.append("[" + re.escape(kucuk) + re.escape(buyuk) + "]")
    return "".join(parcalar)


def kelime_desenine_cevir(ifade: str) -> re.Pattern:
    govde = harf_duyarsiz_desen(ifade)
    return re.compile(rf"(?<![\w]){govde}(?![\w])")


def anahtar(metin: str) -> str:
    """Kasa anahtarı: Türkçe küçük harf, tek boşluk."""
    return " ".join(tr_kucuk(metin).split())

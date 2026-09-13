"""Türk kimlik ve hesap numaralarının kontrol basamağı doğrulamaları."""


def sadece_rakam(deger: str) -> str:
    return "".join(ch for ch in deger if ch.isdigit())


def tckn_gecerli(deger: str) -> bool:
    """T.C. kimlik numarası: 11 hane, ilk hane 0 değil, NVİ algoritması."""
    d = sadece_rakam(deger)
    if len(d) != 11 or d[0] == "0":
        return False
    r = [int(c) for c in d]
    tekler = r[0] + r[2] + r[4] + r[6] + r[8]
    ciftler = r[1] + r[3] + r[5] + r[7]
    if (tekler * 7 - ciftler) % 10 != r[9]:
        return False
    return sum(r[:10]) % 10 == r[10]


def vkn_kontrol_basamagi(ilk_dokuz: str) -> int:
    toplam = 0
    for i, ch in enumerate(ilk_dokuz):
        tmp1 = (int(ch) + (9 - i)) % 10
        tmp2 = (tmp1 * 2 ** (9 - i)) % 9
        if tmp1 != 0 and tmp2 == 0:
            tmp2 = 9
        toplam += tmp2
    return (10 - toplam % 10) % 10


def vkn_gecerli(deger: str) -> bool:
    """Vergi kimlik numarası (tüzel kişiler): 10 hane, GİB kontrol algoritması."""
    d = sadece_rakam(deger)
    if len(d) != 10:
        return False
    return vkn_kontrol_basamagi(d[:9]) == int(d[9])


def iban_gecerli(deger: str) -> bool:
    """ISO 13616 mod-97 kontrolü; TR IBAN'ı 26 karakterdir."""
    iban = "".join(deger.split()).upper()
    if len(iban) < 15 or not iban[:2].isalpha() or not iban[2:4].isdigit():
        return False
    if iban.startswith("TR") and len(iban) != 26:
        return False
    yeniden = iban[4:] + iban[:4]
    try:
        sayi = "".join(str(int(ch, 36)) for ch in yeniden)
    except ValueError:
        return False
    return int(sayi) % 97 == 1

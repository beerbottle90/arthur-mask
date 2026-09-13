"""Sızıntıya öncelik kuralları: OCR metni, baş harfler, konuşmacılar, tek başına ilk ad."""

import pytest


def _bulunan(motor, metin):
    return {(b.tur, b.metin) for b in motor.analiz(metin)[0]}


@pytest.mark.parametrize(
    "metin, beklenen",
    [
        ("DOSYA NO : 2026/1184 ESAS", {("DOSYA_NO", "2026/1184 ESAS")}),
        ("esas no 2024/1566 karar no 2025/412", {("DOSYA_NO", "2024/1566"), ("DOSYA_NO", "2025/412")}),
        (
            "VEKİLİ : AV. BERİVAN ZENGİN - MECİDİYEKÖY MAH. BÜYÜKDERE CAD. NO:88 K:5 ŞİŞLİ/İSTANBUL",
            {("KİŞİ", "BERİVAN ZENGİN"), ("ADRES", "MECİDİYEKÖY MAH. BÜYÜKDERE CAD. NO:88 K:5 ŞİŞLİ/İSTANBUL")},
        ),
        (
            "davali selcuk gungor tel 0312 385 60 14, 06 ks 1907 plakali araci, dogum tarihi 12 03 1987",
            {("KİŞİ", "selcuk gungor"), ("PLAKA", "06 ks 1907"), ("DOĞUM_TARİHİ", "12 03 1987")},
        ),
        ("davali sirket ozgur plastik sanayi ltd sti yetkilisi nurettin bozdogan",
         {("ŞİRKET", "ozgur plastik sanayi ltd sti"), ("KİŞİ", "nurettin bozdogan")}),
        ("[10:20] A.Ö.R.: Tamam, C.E.B. notu Excel'e işlesin.", {("KİŞİ", "A.Ö.R."), ("KİŞİ", "C.E.B.")}),
        ("[12.02.2024 21:31] ~Şebo: ibanı atıyorum", {("KİŞİ", "Şebo")}),
        ("SÜLEYMAN ve HATİCE oğlu", {("KİŞİ", "SÜLEYMAN"), ("KİŞİ", "HATİCE")}),
        ("Mehmet Kaya geldi. Sonra Mehmet imzaladı.", {("KİŞİ", "Mehmet Kaya"), ("KİŞİ", "Mehmet")}),
    ],
)
def test_sizinti_kurallari(motor, metin, beklenen):
    assert beklenen <= _bulunan(motor, metin)


def test_bas_harf_ve_kucuk_harf_tuzaklari(motor):
    bulunan = _bulunan(motor, "T.C. Anayasası, A.Ş. esas sözleşmesi ve Madde 11 ve 13 uyarınca işlem yapıldı.")
    assert not bulunan

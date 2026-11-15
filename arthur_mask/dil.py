"""Arayüz dili: Türkçe, Azerbaycanca, İngilizce.

Kaynak metin Türkçedir ve sözlüğün anahtarıdır (`arayuz/dil-az.json`, `arayuz/dil-en.json`). Sunucu, ekrana giden
metni (hata, uyarı, tutarlılık bulgusu) Türkçe üretir; arayüz onu seçili dile sözlükle çevirir. Aynı Türkçe metin
Claude'a da gider; Claude'a giden metin çevrilmez.

`cevN(metin)` metni değiştirmez, yalnız işaretler: testler işaretli her metnin iki sözlükte de karşılığı olduğunu
denetler. Değişken yerler kalıpta `{0}` ya da `{ad}` biçiminde kalır ve `.format` ile doldurulur; arayüz doldurulmuş
metni kalıba geri eşleyip çevirisine yerleştirir. Marka adları ({{KİŞİ-01}} gibi etiketler ve etiket türleri dahil)
çevrilmez.
"""

DILLER = ("tr", "az", "en")


def cevN(metin: str) -> str:
    return metin


def dil_gecerli(deger) -> str:
    """"AZ", "en-US" gibi değerleri dile indirger; bilinmeyen dil boş döner (tahmin edilmez)."""
    if not isinstance(deger, str):
        return ""
    kisa = deger.strip().lower()[:2]
    return kisa if kisa in DILLER else ""

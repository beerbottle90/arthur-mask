"""Çıkış kapısı: kasadaki değerler hangi biçimde yazılırsa yazılsın Claude'a gitmeden etiketlenir."""

from arthur_mask.cikis import CikisDenetimi
from arthur_mask.depo import Depo
from arthur_mask.kasa import Kasa


def _kasa():
    kasa = Kasa()
    kasa.etiket_al("KİŞİ", "PERSON", "ayşe kara", "Ayşe KARA")
    kasa.etiket_al("KİŞİ", "PERSON", "kara", "KARA")
    kasa.etiket_al("TCKN", "TR_TCKN", "12345678950", "12345678950")
    kasa.etiket_al("ŞİRKET", "TR_TUZEL_KISI", "qafqaz enerji", "Qafqaz Enerji MMC")
    kasa.etiket_al("TELEFON", "TR_TELEFON", "05321234567", "0532 123 45 67")
    kasa.etiket_al("IBAN", "TR_IBAN", "TR330006100519786457841326", "TR33 0006 1005 1978 6457 8413 26")
    return kasa


def test_bicim_farklari_yakalanir():
    d = CikisDenetimi(_kasa())
    metin, bulunan = d.tara(
        "Ayse Kara, AYŞE KARA ve KARA'nın TCKN 123 456 789 50; QAFQAZ ENERJİ MMC; tel 0532-123-4567; "
        "IBAN TR330006100519786457841326."
    )
    assert "kara" not in metin.lower() and "qafqaz" not in metin.lower()
    assert "12345678950" not in metin.replace(" ", "") and "1234567" not in metin.replace("-", "")
    assert "TR33" not in metin
    assert {t for t, _, _ in bulunan} == {"KİŞİ", "TCKN", "ŞİRKET", "TELEFON", "IBAN"}


def test_genel_sozcuk_ve_etiketler_bozulmaz():
    d = CikisDenetimi(_kasa())
    metin = "kara yolu, Karaköy'de toplantı; {{KİŞİ-01}} ve {{TCKN-01}} korunur. Tutar 1.250.000,00 TL."
    assert d.tara(metin) == (metin, [])


def test_ic_ice_yanit_temizlenir():
    d = CikisDenetimi(_kasa())
    temiz, sonuc = d.yanit_temizle({"metin": "Ayşe KARA", "liste": [{"not": "tel 0532 123 45 67"}], "sayi": 3})
    assert temiz == {"metin": "{{KİŞİ-01}}", "liste": [{"not": "tel {{TELEFON-01}}"}], "sayi": 3}
    assert sonuc.yakalanan == 2


def test_belge_adindan_benzersiz_dosya(tmp_path):
    depo = Depo(b"0" * 32, kok=tmp_path)
    ilk = depo.dosya_olustur(depo.benzersiz_ad("nda final"))
    ikinci = depo.dosya_olustur(depo.benzersiz_ad("nda final"))
    assert (ilk, ikinci) == ("nda final", "nda final (2)")

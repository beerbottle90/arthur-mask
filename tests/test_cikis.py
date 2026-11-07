"""Çıkış kapısı: kasadaki değerler hangi biçimde yazılırsa yazılsın Claude'a gitmeden etiketlenir."""

from arthur_mask.cikis import CikisDenetimi, normallestir
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


def test_kucuk_harfli_eposta_ve_ayrac_cesitleri_yakalanir():
    kasa = _kasa()
    kasa.etiket_al("EPOSTA", "EMAIL_ADDRESS", "ayse.kara@ornek.com", "ayse.kara@ornek.com")
    d = CikisDenetimi(kasa)
    metin, bulunan = d.tara("Yazışma ayse.kara@ornek.com üzerinden; TC12345678950; tel 0532–123–45–67, 0532_123_45_67.")
    assert "ayse.kara@" not in metin and "12345678950" not in metin
    assert "0532" not in metin
    assert {t for t, _, _ in bulunan} == {"EPOSTA", "TCKN", "TELEFON"}


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


def test_gorunmez_karakter_ayrik_aksan_ve_satir_sonu_tiresi_yakalanir():
    kasa = Kasa()
    kasa.etiket_al("KİŞİ", "PERSON", "zümrüt karabacak", "Zümrüt KARABACAK")
    d = CikisDenetimi(kasa)
    ornekler = [
        "Zü­mrüt Kara​bacak",          # yumuşak tire, sıfır genişlikli boşluk
        "Zümrüt KARABACAK",           # ayrık aksan (NFD)
        "﻿Zümrüt Karabacak",                  # BOM
        "Zümrüt Kara-\nbacak",                     # satır sonu tirelemesi
        "Ｚümrüt ＫＡＲＡＢＡＣＡＫ",               # tam genişlikli harfler
    ]
    for ornek in ornekler:
        temiz, bulunan = d.tara(f"Taraf: {ornek} imzaladı.")
        # Değerin önündeki görünmez karakter (BOM) yerinde kalabilir; görünen metin yalnız etiket.
        assert normallestir(temiz)[0] == "taraf: {{kisi-01}} imzaladi.", (ornek, temiz)
        assert bulunan and bulunan[0][1] == "{{KİŞİ-01}}"


def test_kismi_ad_ve_kisa_ad():
    kasa = Kasa()
    kasa.etiket_al("KİŞİ", "PERSON", "mehmet ali yılmaz", "Mehmet Ali YILMAZ")
    kasa.etiket_al("KİŞİ", "PERSON", "can", "Can")
    d = CikisDenetimi(kasa)
    metin, _ = d.tara("Mehmet Yılmaz, M. Yılmaz, M.A. Yılmaz ve YILMAZ; Can geldi. yılmaz bir sözcük, can sıkıcı. Ak.")
    assert metin == ("{{KİŞİ-01}}, {{KİŞİ-01}}, {{KİŞİ-01}} ve {{KİŞİ-01}}; {{KİŞİ-02}} geldi. "
                     "yılmaz bir sözcük, can sıkıcı. Ak.")


def test_ayni_soyadli_iki_kisi_soyadindan_etiketlenmez():
    """Soyadı tek başına iki kişiden birine yanlış etiket verdirmesin: belirsizse kısmi biçim eklenmez."""
    kasa = Kasa()
    kasa.etiket_al("KİŞİ", "PERSON", "ayşe demir", "Ayşe Demir")
    kasa.etiket_al("KİŞİ", "PERSON", "mehmet demir", "Mehmet Demir")
    d = CikisDenetimi(kasa)
    assert d.tara("Demir ailesi; A. Demir ve M. Demir.")[0] == "Demir ailesi; {{KİŞİ-01}} ve {{KİŞİ-02}}."


def test_telefon_iban_plaka_ve_dosya_no_bicimleri():
    kasa = _kasa()
    kasa.etiket_al("PLAKA", "TR_PLAKA", "34 abc 123", "34 ABC 123")
    kasa.etiket_al("DOSYA_NO", "TR_DOSYA_NO", "2024/5678 e.", "2024/5678 E.")
    d = CikisDenetimi(kasa)
    metin, bulunan = d.tara(
        "Tel +90 532 123 45 67, 0090 (532) 123 4567 ve 532 123 45 67. IBAN 33 0006 1005 1978 6457 8413 26, "
        "IBANTR330006100519786457841326. Araç 34ABC123 / 34-abc-123. Esas No: 2024/5678; 2024/5678 Esas."
    )
    for parca in ("532", "0006", "ABC", "abc", "5678"):
        assert parca not in metin, (parca, metin)
    assert {t for t, _, _ in bulunan} == {"TELEFON", "IBAN", "PLAKA", "DOSYA_NO"}
    # Başka bir numara (ilk hanesi farklı) dokunulmaz.
    assert d.tara("Tel 0533 123 45 67")[0] == "Tel 0533 123 45 67"


def test_kisa_esas_no_tarihin_ya_da_baska_numaranin_parcasi_olunca_etiketlenmez():
    kasa = _kasa()
    etiket = kasa.etiket_al("DOSYA_NO", "TR_DOSYA_NO", "2025/7", "2025/7")
    d = CikisDenetimi(kasa)
    metin, bulunan = d.tara("2025/7 ve 2025 / 7 sayılı dosya. Dosya 2025/7.")
    assert metin == f"{etiket} ve {etiket} sayılı dosya. Dosya {etiket}.", metin
    assert len(bulunan) == 3
    korunan = "Karar 2025/7/15 tarihli; 12025/7, 2025/71, 3/2025/7 ve 2025.7.1 başka sayılar."
    assert d.tara(korunan)[0] == korunan

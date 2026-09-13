from arthur_mask.kasa import Kasa
from arthur_mask.motor import MaskeMotoru
from arthur_mask.maskeleyici import geri_ac, maskele
from arthur_mask.sozluk import Sozluk, SozlukGirdisi

from .conftest import DILEKCE, IBAN, TCKN, VKN


def _metinler(bulgular):
    return {b.metin for b in bulgular}


def test_dilekce_temel_tespitler(motor):
    bulgular, _ = motor.analiz(DILEKCE)
    bulunan = _metinler(bulgular)
    for beklenen in (
        "Ayşe KARA", "Mehmet Ali YILMAZ", "Fatma Demir", TCKN, VKN, IBAN,
        "0532 123 45 67", "m.yilmaz@ornekhukuk.av.tr", "2024/5678 E.", "34 ABC 123",
        "Vural İnşaat Taahhüt Anonim Şirketi", "Vural İnşaat Taahhüt",
        "Örnek Mahallesi, Gül Sokak, No:10, Beşiktaş, İstanbul",
        "Deneme Mah. Çiçek Sok. No:5 D:3 Sarıyer/İstanbul",
    ):
        assert beklenen in bulunan, beklenen


def test_ictihat_atfi_korunur(motor):
    bulgular, _ = motor.analiz(DILEKCE)
    bulunan = _metinler(bulgular)
    assert not any("2019/1234" in m or "2020/567" in m for m in bulunan)


def test_ictihat_korumasi_kapatilabilir():
    motor = MaskeMotoru(ictihat_koruma=False)
    bulgular, _ = motor.analiz("Yargıtay 3. HD, 2019/1234 E., 2020/567 K. sayılı kararı")
    assert {"2019/1234 E.", "2020/567 K."} <= _metinler(bulgular)


def test_hukuk_ifadeleri_kisi_sanilmaz(motor):
    metin = "Sayın Mahkeme'ye arz olunur. Yargıtay HGK ve İstanbul BAM kararları, TBK m. 125 ile Türk Borçlar KANUNU."
    bulgular, _ = motor.analiz(metin)
    assert not [b for b in bulgular if b.varlik == "PERSON"]


def test_tutar_ve_tarih_maskelenmez(motor):
    bulunan = _metinler(motor.analiz(DILEKCE)[0])
    assert "1.250.000,00 TL" not in bulunan


def test_ayni_kisi_ayni_etiket(motor):
    bulgular, _ = motor.analiz(DILEKCE)
    kasa = Kasa()
    maskeli, _ = maskele(DILEKCE, bulgular, kasa)
    assert "Ayşe" not in maskeli and "YILMAZ" not in maskeli and "KARA," not in maskeli
    assert maskeli.count("{{KİŞİ-02}}") == 2  # Av. Mehmet Ali YILMAZ iki kez
    assert "Müvekkil {{KİŞİ-01}}" in maskeli  # tek başına soyadı aynı kişiye bağlandı


def test_soyadi_iki_kisiye_aitse_yayilmaz(motor):
    metin = "DAVACI: Ayşe KARA\nDAVALI: Mehmet KARA\nKARA ailesi arasında uyuşmazlık."
    bulgular, _ = motor.analiz(metin)
    assert not [b for b in bulgular if b.metin == "KARA"]


def test_sozluk_ve_izin_listesi():
    sozluk = Sozluk(
        maskele=[SozlukGirdisi("Mavi Kuş", "PROJE", ["MAVİ KUŞ"]), SozlukGirdisi("Ayşe Kara", "MÜVEKKİL")],
        maskeleme=["Mehmet ŞİMŞEK"],
    )
    motor = MaskeMotoru(sozluk=sozluk)
    metin = "Mavi Kuş projesinde MAVİ KUŞ kod adı. ayşe kara ile görüşüldü. Bakan Mehmet ŞİMŞEK açıkladı."
    bulgular, _ = motor.analiz(metin)
    kasa = Kasa()
    maskeli, _ = maskele(metin, bulgular, kasa)
    assert maskeli.count("{{PROJE-01}}") == 2
    assert "{{MÜVEKKİL-01}}" in maskeli
    assert "Mehmet ŞİMŞEK" in maskeli


def test_geri_ac_ve_aksan_toleransi(motor):
    bulgular, _ = motor.analiz(DILEKCE)
    kasa = Kasa()
    maskeli, _ = maskele(DILEKCE, bulgular, kasa)
    acik, bilinmeyen = geri_ac(maskeli, kasa)
    assert "Ayşe KARA" in acik and TCKN in acik and not bilinmeyen
    # Kısa biçimler (tek soyadı, tür eksiz unvan) kanonik tam değere açılır.
    assert "Müvekkil Ayşe KARA" in acik
    assert "davalı Vural İnşaat Taahhüt Anonim Şirketi ile" in acik
    model_ciktisi = "{{KISI-01}} lehine karar verilmeli; {{KİŞİ-99}} belirsiz."
    acik, bilinmeyen = geri_ac(model_ciktisi, kasa)
    assert acik.startswith("Ayşe KARA") and bilinmeyen == ["{{KİŞİ-99}}"]


def test_supheli_adaylar_raporlanir(motor):
    # Bağlamsız 10 haneli ve VKN kontrolünü geçen sayı: eşik altında, maskelenmez ama raporlanır.
    bulgular, supheli = motor.analiz(f"Referans {VKN} ile kayıt açıldı.")
    assert VKN not in _metinler(bulgular)
    assert VKN in _metinler(supheli)


def test_soyadi_buyuk_harfli_olmayan_adlar(motor):
    metin = (
        "Müvekkil şirketin ortağı Deniz Aydın toplantıya katılmadı. "
        "Tanık Selin Yıldız ve Ahmet Can Kılıç dinlendi. Zeynep Hanım da hazırdı. "
        "Selin Yıldız İstanbul'da ikamet etmektedir."
    )
    bulunan = _metinler(motor.analiz(metin)[0])
    assert {"Deniz Aydın", "Selin Yıldız", "Ahmet Can Kılıç", "Zeynep"} <= bulunan
    assert "Selin Yıldız İstanbul" not in bulunan


def test_ad_gibi_gorunen_kavramlar_kisi_sayilmaz(motor):
    metin = (
        "Deniz Hukuku kapsamında, Aydın Adliyesi önünde, Bahar Dönemi boyunca "
        "Umut Vaat eden bir süreç. Gül Sokak No:3 ile Barış Manço Caddesi."
    )
    kisiler = {b.metin for b in motor.analiz(metin)[0] if b.varlik == "PERSON"}
    assert not kisiler & {"Deniz Hukuku", "Aydın Adliyesi", "Bahar Dönemi", "Deniz", "Aydın", "Bahar"}

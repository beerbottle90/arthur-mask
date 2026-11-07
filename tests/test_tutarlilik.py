"""Sözleşmenin iç tutarlılık denetimi: kurallar, maskeli rapor (Claude) ve tam rapor (avukatın ekranı)."""

import io
import json
from urllib.parse import quote

import pytest

from arthur_mask import tutarlilik
from arthur_mask.tutarlilik import Kanit, MetinParagrafi, duz_paragraflar

from .conftest import TCKN
from .test_servis_kopru import _istek, _mcp_cagir, islem, yerel  # noqa: F401  (fixture)


def _denetle(metin: str, varliklar=()):
    paragraflar = duz_paragraflar(metin)
    sonuc = tutarlilik.denetle(paragraflar, varliklar)
    return sonuc, paragraflar


def _kurallar(sonuc):
    return [b.kural for b in sonuc.bulgular]


# -- iç atıflar ----------------------------------------------------------------------------------------
ATIF_METNI = """MADDE 1 – KONU
İşbu Sözleşme'nin konusu danışmanlıktır.
MADDE 2 – SÜRE
2.1 Süre bir yıldır.
2.2 Taraflar süreyi uzatabilir.
(a) yazılı bildirimle,
(b) karşılıklı mutabakatla.
MADDE 3 – ATIFLAR
Madde 2.1 ve 2.2 hükümleri saklıdır; Madde 2.2(b) uyarınca uzatma yapılır.
Bu süre işbu Sözleşme'nin 7.3 maddesine tabidir ve Madde 2.4 uygulanmaz.
Madde 2.2(c) uyarınca bildirim yapılır.
TBK m. 27 ve 6098 sayılı Türk Borçlar Kanunu'nun 344. maddesi saklıdır.
2. maddenin 2. fıkrası ile 2. maddenin 9. fıkrası uygulanır.
Article 6 of the GDPR applies; Article 2.1 of this Agreement applies; Section 5.2 does not exist.
"""


def test_var_olmayan_ic_atiflar_bulunur_dis_atiflar_atlanir():
    sonuc, paragraflar = _denetle(ATIF_METNI)
    rapor = tutarlilik.rapor_yaz(sonuc, paragraflar, tutarlilik.gercek_metin(paragraflar))
    atiflar = {b["aciklama"].split("”")[0].lstrip("“"): b["kural"] for b in rapor["bulgular"]}
    assert atiflar.get("7.3 maddesine") == "Var olmayan maddeye atıf"
    assert atiflar.get("Madde 2.4") == "Var olmayan alt maddeye, fıkraya ya da bende atıf"
    assert atiflar.get("Madde 2.2(c)") == "Var olmayan alt maddeye, fıkraya ya da bende atıf"
    assert atiflar.get("Section 5.2") == "Var olmayan maddeye atıf"
    assert any(k.startswith("2. maddenin 9. fıkrası") for k in atiflar)
    # Var olanlar ve kanun maddeleri bulgu değildir.
    for yerinde in ("Madde 2.1", "2.2", "Madde 2.2(b)", "TBK m. 27", "344. maddesi", "Article 6", "Article 2.1",
                    "2. maddenin 2. fıkrası"):
        assert not any(k.startswith(yerinde) for k in atiflar), (yerinde, atiflar)
    assert rapor["bulgular"][0]["onem"] == "yüksek"
    assert rapor["bulgular"][0]["yer"].startswith("Madde 3")


def test_madde_yapisi_yoksa_atif_denetlenmez_ve_not_duser():
    sonuc, _ = _denetle("Bu metin Madde 4'e atıf yapar.\nBaşka bir satır.")
    assert not [k for k in _kurallar(sonuc) if k.startswith("atif")]
    assert any("madde numarası bulunamadı" in n for n in sonuc.notlar)


# -- tanımlı terimler ----------------------------------------------------------------------------------
TERIM_METNI = """MADDE 1 – TANIMLAR
“Gizli Bilgi”: Taraflardan birinin diğerine açıkladığı bilgidir.
“Teslim Tarihi”: hizmetin tamamlanacağı tarihtir.
“Hizmet Bedeli”, Madde 1'de belirlenen ücret anlamına gelir.
MADDE 2 – YÜKÜMLÜLÜKLER
Danışman, Gizli Bilgi'yi açıklamaz ve Hizmet Bedelinin ödenmesini bekler.
Danışman çalışmayı Proje Takvimi'ne göre yürütür ve Proje Takvimi'ni her ay günceller.
The "Services" shall be performed as agreed.
"""


def test_tanimlanip_kullanilmayan_ve_tanimsiz_terimler():
    sonuc, paragraflar = _denetle(TERIM_METNI)
    rapor = tutarlilik.rapor_yaz(sonuc, paragraflar, tutarlilik.gercek_metin(paragraflar))
    aciklamalar = [b["aciklama"] for b in rapor["bulgular"]]
    assert any(a.startswith("“Teslim Tarihi” tanımlanmış ama") for a in aciklamalar), aciklamalar
    assert not any(a.startswith("“Gizli Bilgi” tanımlanmış") for a in aciklamalar)
    assert not any(a.startswith("“Hizmet Bedeli” tanımlanmış") for a in aciklamalar), "ekli kullanım sayılır"
    assert any(a.startswith("“Proje Takvimi” büyük harfle") and "2 kez" in a for a in aciklamalar), aciklamalar
    assert sonuc.sayilar["tanimli_terim"] >= 3


# -- taraflar ------------------------------------------------------------------------------------------
def _varlik(metin: str, parca: str, varlik: str, kacinci: int = 0):
    bas = -1
    for _ in range(kacinci + 1):
        bas = metin.index(parca, bas + 1)
    return bas, bas + len(parca), varlik


def test_taraf_unvani_tur_farki_ve_rol_celiskisi():
    metin = ("Bu Sözleşme, Kuzey Rüzgâr Enerji Anonim Şirketi (“Satıcı”) ile Güney Yapı Limited Şirketi (“Alıcı”) "
             "arasında imzalanmıştır.\n"
             "Satıcı malı teslim eder ve Alıcı bedeli öder.\n"
             "SATICI: Kuzey Rüzgâr Enerji Ltd. Şti.\n"
             "ALICI: Batı Lojistik Limited Şirketi\n")
    varliklar = [
        _varlik(metin, "Kuzey Rüzgâr Enerji Anonim Şirketi", "TR_TUZEL_KISI"),
        _varlik(metin, "Güney Yapı Limited Şirketi", "TR_TUZEL_KISI"),
        _varlik(metin, "Kuzey Rüzgâr Enerji Ltd. Şti.", "TR_TUZEL_KISI"),
        _varlik(metin, "Batı Lojistik Limited Şirketi", "TR_TUZEL_KISI"),
    ]
    sonuc, paragraflar = _denetle(metin, varliklar)
    kurallar = _kurallar(sonuc)
    assert "taraf_turu" in kurallar
    assert kurallar.count("taraf_rol") == 1, "Satıcı aynı şirkete bağlı; yalnız Alıcı çelişkili"
    rapor = tutarlilik.rapor_yaz(sonuc, paragraflar, tutarlilik.gercek_metin(paragraflar))
    rol = next(b for b in rapor["bulgular"] if b["kural"].startswith("Aynı taraf rolü"))
    assert "Güney Yapı" in rol["aciklama"] and "Batı Lojistik" in rol["aciklama"]
    tur = next(b for b in rapor["bulgular"] if b["kural"].startswith("Taraf unvanında şirket türü"))
    assert "AŞ" in tur["aciklama"] and "LTD ŞTİ" in tur["aciklama"]


def test_unvan_cozumleme():
    assert tutarlilik.unvan_coz("ABC Enerji A.Ş.") == ("abc enerji", "AŞ")
    assert tutarlilik.unvan_coz("ABC Enerji Anonim Şirketi") == ("abc enerji", "AŞ")
    assert tutarlilik.unvan_coz("Qafqaz Enerji MMC") == ("qafqaz enerji", "MMC")
    assert tutarlilik.unvan_coz("Northwind Trading Ltd.") == ("northwind trading", "LTD")


# -- çift dilli tablo (Word) -----------------------------------------------------------------------------
docx_kutuphanesi = pytest.importorskip("docx")

ISARETLI = ["Zümrüt KARABACAK", "KARABACAK", TCKN, "Kuzey Rüzgâr", "zumrut.karabacak@ornekhukuk.av.tr"]


def _sozlesme() -> bytes:
    belge = docx_kutuphanesi.Document()
    for p in [
        "HİZMET SÖZLEŞMESİ",
        "MADDE 1 – TARAFLAR",
        "İşbu Sözleşme, Kuzey Rüzgâr Enerji Anonim Şirketi (“Hizmet Alan”) ile Zümrüt KARABACAK "
        f"(TCKN: {TCKN}, e-posta: zumrut.karabacak@ornekhukuk.av.tr) (“Danışman”) arasında imzalanmıştır.",
        "MADDE 2 – TANIMLAR",
        "“Gizli Bilgi”: Taraflardan birinin diğerine açıkladığı her türlü bilgidir.",
        "“Teslim Tarihi”: hizmetin tamamlanacağı tarihtir.",
        "MADDE 3 – YÜKÜMLÜLÜKLER",
        "Danışman, Gizli Bilgi'yi üçüncü kişilere açıklamaz; bu yükümlülük işbu Sözleşme'nin 12. maddesi saklı "
        "kalmak kaydıyla geçerlidir.",
        "Danışman, Proje Takvimi'ne uygun çalışır ve Proje Takvimi'ni her ay Hizmet Alan'a bildirir.",
        "MADDE 4 – İMZA",
        "HİZMET ALAN: Kuzey Rüzgâr Enerji Ltd. Şti.",
        "DANIŞMAN: Zümrüt KARABACAK",
    ]:
        belge.add_paragraph(p)
    tablo = belge.add_table(rows=0, cols=2)
    for sol, sag in [
        ("MADDE 5 – ÖDEME", "ARTICLE 5 – PAYMENT"),
        ("Bedel 1.250.000,00 TL'dir ve 30 gün içinde ödenir.", "The fee is TRY 1,520,000.00 and is payable within 30 days."),
        ("Fesih bildirimi 15.07.2026 tarihine kadar yapılır.", "Notice of termination shall be given by 15 July 2026."),
        ("MADDE 6 – SÜRE", "ARTICLE 7 – TERM"),
        ("Süre 12 aydır ve Madde 5 uyarınca uzatılabilir.", "The term is 24 months and may be extended under Article 5."),
    ]:
        hucreler = tablo.add_row().cells
        hucreler[0].text, hucreler[1].text = sol, sag
    tampon = io.BytesIO()
    belge.save(tampon)
    return tampon.getvalue()


def test_word_sozlesmesi_maskeli_rapor_claudea_tam_rapor_avukata(yerel):  # noqa: F811
    islem = yerel.islem
    klasor = islem.depo.aktif_dosya
    kayit = islem.arayuz_belge_isle(klasor, "hizmet sozlesmesi.docx", _sozlesme())
    if kayit["durum"] != "hazir":
        kayit = islem.arayuz_belge_onayla(klasor, kayit["id"], [], [], "Test onayı")
    assert kayit["durum"] == "hazir"

    # Claude: MCP protokolü üzerinden maskeli rapor; gerçek değer yok.
    yanit = _mcp_cagir(islem, "arthur_mask_tutarlilik_denetimi", {"kimlik": kayit["id"]})
    giden = json.dumps(yanit, ensure_ascii=False)
    for deger in ISARETLI:
        assert deger not in giden, deger
    kurallar = [b["kural"] for b in yanit["bulgular"]]
    assert "Var olmayan maddeye atıf" in kurallar
    assert "Tanımlanıp kullanılmayan terim" in kurallar
    assert "Tanımlanmadan kullanılan terim (olası)" in kurallar
    assert "Taraf unvanında şirket türü farkı" in kurallar
    assert "Sütunlar arası tutar farkı" in kurallar
    assert "Sütunlar arası madde numarası farkı" in kurallar
    assert "Sütunlar arası sayı farkı" in kurallar
    assert "Sütunlar arası tarih farkı" not in kurallar, "15.07.2026 = 15 July 2026"
    tutar = next(b for b in yanit["bulgular"] if b["kural"] == "Sütunlar arası tutar farkı")
    assert "1.250.000,00 TL" in tutar["aciklama"] and "1,520,000.00" in tutar["aciklama"]
    assert "(TR)" in tutar["yer"] or "(EN)" in tutar["yer"]
    taraf = next(b for b in yanit["bulgular"] if b["kural"] == "Taraf unvanında şirket türü farkı")
    assert "{{ŞİRKET-" in taraf["aciklama"]
    assert yanit["denetlenen"]["iki_dilli_satir"] == 5

    # Liste aracı bulgu sayısını gösterir.
    liste = _mcp_cagir(islem, "arthur_mask_belgeler")
    assert liste["belgeler"][0]["tutarlilik_bulgusu"] == yanit["ozet"]["toplam"]

    # Avukatın ekranı: aynı rapor gerçek adlarla, yalnız yerel API'den; diskte şifreli.
    durum, govde = _istek(yerel, "GET", f"/api/dosyalar/{quote(klasor)}/belgeler/{kayit['id']}/tutarlilik")
    assert durum == 200, govde
    tam = json.loads(govde)
    assert tam["ozet"] == yanit["ozet"] and len(tam["bulgular"]) == len(yanit["bulgular"])
    tam_metin = json.dumps(tam, ensure_ascii=False)
    assert "Kuzey Rüzgâr Enerji Anonim Şirketi" in tam_metin and "Kuzey Rüzgâr Enerji Ltd. Şti." in tam_metin
    sifreli = (islem.depo.dosya_yolu(klasor) / "maskeli" / f"{kayit['id']}.tutarlilik").read_bytes()
    assert b"Kuzey" not in sifreli and "Rüzgâr".encode() not in sifreli

    # Belge silinince şifreli rapor da gider.
    islem.arayuz_belge_sil(klasor, kayit["id"])
    assert not (islem.depo.dosya_yolu(klasor) / "maskeli" / f"{kayit['id']}.tutarlilik").exists()


def test_maskeli_parca_degeri_bolmez():
    """Kanıt aralığı bir değerin ortasından geçse de maskeli parçada değerin tamamı etikete döner."""
    metin = "Taraf Zümrüt KARABACAK ödemeyi yapar."
    paragraflar = duz_paragraflar(metin)
    bas = metin.index("Zümrüt")
    degisiklikler = [(bas, bas + len("Zümrüt KARABACAK"), "{{KİŞİ-01}}")]
    al = tutarlilik.maskeli_metin(paragraflar, metin, degisiklikler)
    assert al(Kanit(0, bas + 3, bas + 10)) == "{{KİŞİ-01}}"
    assert al(Kanit(0, 0, len(metin))) == "Taraf {{KİŞİ-01}} ödemeyi yapar."
    assert al(Kanit(0, bas + 8, len(metin))) == "{{KİŞİ-01}} ödemeyi yapar."


def test_eski_kayitta_rapor_yoksa_arac_yeniden_yukleme_ister(islem):  # noqa: F811
    klasor = islem.depo.aktif_dosya
    kayit = islem.arayuz_belge_isle(klasor, "not.txt", "Kısa bir not.".encode())
    eski = islem.depo.belge_oku(klasor, kayit["id"])
    eski.pop("tutarlilik")
    islem.depo.belge_kaydet(klasor, eski)
    assert "yeniden bırakmasını" in _mcp_cagir(islem, "arthur_mask_tutarlilik_denetimi", {"kimlik": kayit["id"]})["hata"]


def test_dil_tahmini_ve_sayi_bicimleri():
    assert tutarlilik.dil_tahmini("Taraflar işbu sözleşme ile bedelin ödenmesini kabul eder ve taahhüt eder.") == "tr"
    assert tutarlilik.dil_tahmini("The Parties agree that the fee shall be paid within thirty days of this Agreement.") == "en"
    assert tutarlilik.dil_tahmini("Tərəflər bu müqavilə ilə razılaşırlar və öhdəlik götürürlər.") == "az"
    assert str(tutarlilik.sayi_coz("1.250.000,00", "tr")) == "1250000.00"
    assert str(tutarlilik.sayi_coz("1,250,000.00", "en")) == "1250000.00"
    assert str(tutarlilik.sayi_coz("7,5", "tr")) == "7.5"
    assert str(tutarlilik.sayi_coz("1,250", "en")) == "1250"


def test_word_paragraflari_otomatik_numarayi_ve_hucreyi_tasir():
    belge = docx_kutuphanesi.Document()
    belge.add_paragraph("Giriş")
    belge.add_paragraph("Birinci", style="List Number")
    belge.add_paragraph("İkinci", style="List Number")
    tablo = belge.add_table(rows=1, cols=2)
    tablo.rows[0].cells[0].text, tablo.rows[0].cells[1].text = "Sol", "Sağ"
    tampon = io.BytesIO()
    belge.save(tampon)
    from arthur_mask.docx_agac import WordBelgesi
    from arthur_mask.surum import girdiler

    word = WordBelgesi({b.filename: v for b, v in girdiler(tampon.getvalue())})
    assert [(p.metin, p.numara, p.tablo) for p in word.sirali] == [
        ("Giriş", None, None), ("Birinci", "1.", None), ("İkinci", "2.", None),
        ("Sol", None, (1, 1, 1)), ("Sağ", None, (1, 1, 2)),
    ]
    assert isinstance(MetinParagrafi("x", range(1)), MetinParagrafi)

"""Sürüm karşılaştırması: gerçek metinle izli Word (yerel), Claude'a yalnız maskeli "ne değişti" özeti."""

import io
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from urllib.parse import quote

import pytest

docx_kutuphanesi = pytest.importorskip("docx")

from arthur_mask import surum

from .conftest import TCKN
from .test_servis_kopru import _istek, _mcp_cagir, islem, yerel  # noqa: F401  (fixture)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _docx(paragraflar, tablo=None, numarali=(), son="Son paragraf.") -> bytes:
    belge = docx_kutuphanesi.Document()
    for p in paragraflar:
        belge.add_paragraph(p, style="List Number" if p in numarali else None)
    if tablo:
        t = belge.add_table(rows=0, cols=len(tablo[0]))
        for satir in tablo:
            for hucre, metin in zip(t.add_row().cells, satir):
                hucre.text = metin
    if son:
        belge.add_paragraph(son)
    tampon = io.BytesIO()
    belge.save(tampon)
    return tampon.getvalue()


def _gorunum(veri: bytes, kabul: bool):
    """Word'ün 'Tümünü kabul et' (kabul=True) ya da 'Tümünü reddet' sonrası paragraf metinleri (boşlar hariç)."""
    with zipfile.ZipFile(io.BytesIO(veri)) as zf:
        kok = ET.fromstring(zf.read("word/document.xml"))

    def metin(p):
        parcalar = []

        def gez(e, eklendi, silindi):
            for c in e:
                if c.tag == W + "pPr":
                    continue
                if c.tag == W + "ins":
                    gez(c, True, silindi)
                elif c.tag == W + "del":
                    gez(c, eklendi, True)
                elif c.tag in (W + "t", W + "delText"):
                    if (not silindi) if kabul else (not eklendi):
                        parcalar.append(c.text or "")
                elif c.tag == W + "tab":
                    if (not silindi) if kabul else (not eklendi):
                        parcalar.append("\t")
                else:
                    gez(c, eklendi, silindi)

        gez(p, False, False)
        return " ".join("".join(parcalar).split())

    def satir_atlanir(tr):
        trpr = tr.find(W + "trPr")
        if trpr is None:
            return False
        return trpr.find(W + ("del" if kabul else "ins")) is not None

    cikti = []

    def bloklar(kap):
        for c in kap:
            if c.tag == W + "p":
                m = metin(c)
                if m:
                    cikti.append(m)
            elif c.tag == W + "tbl":
                for tr in c.findall(W + "tr"):
                    if satir_atlanir(tr):
                        continue
                    for tc in tr.findall(W + "tc"):
                        bloklar(tc)

    bloklar(kok.find(W + "body"))
    return cikti


def _duz(veri: bytes):
    belge = docx_kutuphanesi.Document(io.BytesIO(veri))
    cikti = []
    govde = belge.element.body
    for c in govde.iterchildren():
        if c.tag == W + "p":
            m = " ".join("".join(t.text or "" for t in c.iter(W + "t")).split())
            if m:
                cikti.append(m)
        elif c.tag == W + "tbl":
            for tr in c.findall(W + "tr"):
                for tc in tr.findall(W + "tc"):
                    for p in tc.findall(W + "p"):
                        m = " ".join("".join(t.text or "" for t in p.iter(W + "t")).split())
                        if m:
                            cikti.append(m)
    return cikti


ESKI = dict(
    paragraflar=["MADDE 1 – KONU", "Süre 30 gündür ve uzatılamaz.", "Bu paragraf silinecek.",
                 "Kalan paragraf aynen durur.", "Birinci numaralı bent", "İkinci numaralı bent"],
    tablo=[("Bedel 1.250.000,00 TL'dir.", "The price is TRY 1,250,000.00."), ("Silinecek satır", "Row to delete"),
           ("Ortak satır", "Common row")],
    numarali=("Birinci numaralı bent", "İkinci numaralı bent"),
)
YENI = dict(
    paragraflar=["MADDE 1 – KONU", "Süre 60 gündür ve uzatılamaz.", "Kalan paragraf aynen durur.",
                 "Yeni eklenen paragraf burada.", "Birinci numaralı bent"],
    tablo=[("Bedel 1.250.000,00 TL'dir.", "The price is TRY 1,520,000.00."), ("Ortak satır", "Common row"),
           ("Yeni satır", "New row")],
    numarali=("Birinci numaralı bent",),
)


def test_kelime_farki_bitisik_degisiklikleri_birlestirir():
    islemler = surum.kelime_farki("eski sözcük kaldı", "yeni ifade kaldı")
    degisen = [i for i in islemler if i[0] != "equal"]
    assert len(degisen) == 1 and degisen[0][0] == "replace"
    _, a1, a2, b1, b2 = degisen[0]
    assert "eski sözcük kaldı"[a1:a2] == "eski sözcük" and "yeni ifade kaldı"[b1:b2] == "yeni ifade"
    sayi = [i for i in surum.kelime_farki("TRY 1,250,000.00", "TRY 1,520,000.00") if i[0] != "equal"]
    assert len(sayi) == 1 and "TRY 1,520,000.00"[sayi[0][3]:sayi[0][4]] == "1,520,000.00"


def test_izli_karsilastirma_kabulde_yeni_redde_ozgun_verir():
    eski, yeni = _docx(**ESKI), _docx(**YENI)
    cikti, sayim, uyarilar = surum.izli_karsilastirma(eski, yeni)
    assert sayim == {"degisen": 2, "silinen": 2, "eklenen": 1, "satir_silinen": 1, "satir_eklenen": 1}
    assert not uyarilar

    docx_kutuphanesi.Document(io.BytesIO(cikti))  # Word kitaplığı açabiliyor
    with zipfile.ZipFile(io.BytesIO(cikti)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
        assert sorted(zf.namelist()) == sorted(zipfile.ZipFile(io.BytesIO(yeni)).namelist())
    assert xml.count("<w:tbl>") == 1, "tablo düzeni korunur"
    assert '<w:del w:id="' in xml and '<w:ins w:id="' in xml
    ids = re.findall(r'<w:(?:ins|del) w:id="(\d+)"', xml)
    assert len(ids) == len(set(ids)), "izli değişiklik kimlikleri tekil"
    assert "<w:trPr><w:del " in xml and "<w:trPr><w:ins " in xml, "satır ekleme/silme satır düzeyinde izli"
    # Otomatik numaralı silinen bent liste stilini korur: Word'de numarasıyla görünür, reddedilince numarasına döner.
    assert re.search(r'<w:p><w:pPr><w:pStyle w:val="ListNumber"/><w:rPr><w:del [^>]*/></w:rPr></w:pPr>'
                     r'<w:del [^>]*><w:r><w:delText[^>]*>İkinci numaralı bent', xml)

    assert _gorunum(cikti, kabul=True) == _duz(yeni)
    assert _gorunum(cikti, kabul=False) == _duz(eski)


def test_cift_sutunda_hucre_degisikligi_kendi_sutununda_kalir():
    eski = _docx(["Sözleşme"], [("Süre 30 gündür.", "The term is 30 days."), ("Ödeme peşin.", "Payment in advance.")])
    yeni = _docx(["Sözleşme"], [("Süre 30 gündür.", "The term is 60 days."), ("Ödeme peşin.", "Payment in advance.")])
    cikti, sayim, _ = surum.izli_karsilastirma(eski, yeni)
    assert sayim == {"degisen": 1}
    tablo = docx_kutuphanesi.Document(io.BytesIO(cikti)).tables[0]
    assert len(tablo.rows) == 2 and all(len(r.cells) == 2 for r in tablo.rows)
    sag = tablo.rows[0].cells[1]._tc.xml
    assert "<w:delText" in sag and "30" in sag and "60" in sag
    assert "<w:del " not in tablo.rows[0].cells[0]._tc.xml


def test_kisa_paragraf_genisletilince_degisiklik_sayilir():
    eski = _docx(["Başlık", "Sözleşme süresi 12 aydır.", "Son."])
    yeni = _docx(["Başlık", "Sözleşme süresi 24 aydır ve kendiliğinden uzar.", "Son."])
    _, sayim, _ = surum.izli_karsilastirma(eski, yeni)
    assert sayim == {"degisen": 1}


def test_buyuk_belge_makul_surede():
    import time

    paragraflar = [f"{i}. madde metni burada yer alır ve taraflar {i} gün içinde bildirim yapar." for i in range(600)]
    degismis = [p.replace("gün", "iş günü") if i % 10 == 0 else p for i, p in enumerate(paragraflar)]
    eski, yeni = _docx(paragraflar), _docx(degismis[:300] + ["Yeni eklenen madde."] + degismis[300:])
    bas = time.monotonic()
    _, sayim, _ = surum.izli_karsilastirma(eski, yeni)
    assert time.monotonic() - bas < 20
    assert sayim["degisen"] == 60 and sayim["eklenen"] == 1


def test_yeni_surumde_izli_degisiklik_varsa_reddedilir():
    eski = _docx(["Süre 30 gündür."])
    yeni = _docx(["Süre 60 gündür."])
    izli, _, _ = surum.izli_karsilastirma(eski, yeni)
    with pytest.raises(surum.SurumHatasi, match="Tümünü kabul et"):
        surum.izli_karsilastirma(eski, izli)


def test_degisiklik_ozeti_isaretli_fark_ve_yer_verir():
    ozet = surum.degisiklik_ozeti(surum.girdiler(_docx(**ESKI)), surum.girdiler(_docx(**YENI)))
    turler = [o["tur"] for o in ozet["degisiklikler"]]
    assert turler.count("değişti") == 2 and "satır eklendi" in turler and "satır silindi" in turler
    farklar = [o["fark"] for o in ozet["degisiklikler"] if o["tur"] == "değişti"]
    assert "Süre [-30-]{+60+} gündür ve uzatılamaz." in farklar
    assert any("[-1,250,000.00-]{+1,520,000.00+}" in f for f in farklar)
    tablo = next(o for o in ozet["degisiklikler"] if "Tablo 1" in o["yer"] and o["tur"] == "değişti")
    assert "sütun 2" in tablo["yer"]


# -- işlem katmanı ve MCP: Claude'a yalnız maskeli özet ---------------------------------------------------
KISI_ESKI, KISI_YENI = "Zümrüt KARABACAK", "Zümrüt KARAKAYA"
SIRKET = "Kuzey Rüzgâr Enerji Anonim Şirketi"
ISARETLI = [KISI_ESKI, KISI_YENI, "KARABACAK", "KARAKAYA", TCKN, "Kuzey Rüzgâr", "zumrut.karabacak@ornekhukuk.av.tr"]


def _sozlesme(kisi: str, sure: str, ek_satir: bool) -> bytes:
    paragraflar = [
        "KİRA SÖZLEŞMESİ",
        f"Kiraya veren: {SIRKET} (“Kiraya Veren”).",
        f"Kiracı: {kisi} (TCKN: {TCKN}), e-posta: zumrut.karabacak@ornekhukuk.av.tr (“Kiracı”).",
        f"Kira süresi {sure} ay olup Kiracı süre sonunda taşınmazı boşaltır.",
        "Kiraya Veren depozitoyu iade eder.",
    ]
    tablo = [("Aylık kira 45.000,00 TL'dir.", "Monthly rent is TRY 45,000.00.")]
    if ek_satir:
        tablo.append((f"Kefil: {KISI_ESKI}.", f"Guarantor: {KISI_ESKI}."))
    return _docx(paragraflar, tablo)


def test_arayuz_karsilastirma_izli_word_yerelde_ozet_maskeli(islem):  # noqa: F811
    klasor = islem.depo.aktif_dosya
    eski = _sozlesme(KISI_ESKI, "12", ek_satir=False)
    yeni = _sozlesme(KISI_YENI, "24", ek_satir=True)
    sonuc = islem.arayuz_karsilastir(klasor, "kira v1.docx", eski, "kira v2 karsi taraf.docx", yeni)
    for anahtar in ("ozgun", "yeni"):
        if sonuc[anahtar]["durum"] != "hazir":
            islem.arayuz_belge_onayla(klasor, sonuc[anahtar]["id"], [], [], "Test onayı")
    ozgun, yeni_id = sonuc["ozgun"]["id"], sonuc["yeni"]["id"]
    assert sonuc["cevap"]["tur"] == "karsilastirma" and sonuc["cevap"]["izli"]

    # İzli Word avukatın bilgisayarında gerçek adlarla.
    yol = islem.depo.dosya_yolu(klasor) / "cevaplar" / sonuc["cevap"]["dosya"]
    with zipfile.ZipFile(yol) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "KARAKAYA" in xml and "KARABACAK" in xml and "<w:ins " in xml and "<w:del " in xml
    assert "{{" not in xml
    for deger in ISARETLI[:4]:
        assert deger not in sonuc["cevap"]["dosya"] and deger not in sonuc["cevap"]["maskeli_metin"]

    # Claude: belge listesi ve özet, MCP protokolü üzerinden; gerçek değer yok.
    liste = _mcp_cagir(islem, "arthur_mask_belgeler")
    assert liste["karsilastirmalar"][0] == {**liste["karsilastirmalar"][0], "ozgun": ozgun, "yeni": yeni_id}
    ozet = _mcp_cagir(islem, "arthur_mask_surumleri_karsilastir")
    giden = json.dumps([liste, ozet], ensure_ascii=False)
    for deger in ISARETLI:
        assert deger not in giden, deger
    assert ozet["ozgun"] == ozgun and ozet["yeni"] == yeni_id and "izli değişiklikli Word" in ozet["izli_word"]
    farklar = " ".join(o.get("fark", "") + o.get("metin", "") for o in ozet["degisiklikler"])
    assert "[-12-]{+24+}" in farklar
    assert re.search(r"\[-\{\{KİŞİ-\d+\}\}-\]\{\+\{\{KİŞİ-\d+\}\}\+\}", farklar), farklar
    assert any(o["tur"] == "satır eklendi" for o in ozet["degisiklikler"])

    # Kimlikle çağrı da çalışır; yanlış sırada aynı belge reddedilir.
    assert _mcp_cagir(islem, "arthur_mask_surumleri_karsilastir", {"ozgun": ozgun, "yeni": yeni_id})["degisiklikler"]
    assert "hata" in _mcp_cagir(islem, "arthur_mask_surumleri_karsilastir", {"ozgun": ozgun, "yeni": ozgun})

    # Sızıntı denetimi: Claude'a giden her yanıt, sonradan kasaya giren değerler dahil, kasaya karşı temiz.
    # (Depodaki maskeli metinde kalan değerler "çıkış kapısından önce" diye ayrıca listelenir; onlar kapıda etiketlenir.)
    denetim = islem.arayuz_denetle(klasor)
    assert not [b for b in denetim["bulgular"] if b["kaynak"].startswith("Claude'a giden")], denetim["bulgular"]


def test_hazir_olmayan_surum_ozeti_verilmez(islem):  # noqa: F811
    klasor = islem.depo.aktif_dosya
    from arthur_mask.dogrulama import vkn_kontrol_basamagi

    vkn = "987654321" + str(vkn_kontrol_basamagi("987654321"))
    eski = _docx([f"Referans {vkn} ile kayıt açıldı.", "Süre 30 gündür."])
    yeni = _docx([f"Referans {vkn} ile kayıt açıldı.", "Süre 45 gündür."])
    sonuc = islem.arayuz_karsilastir(klasor, "a.docx", eski, "b.docx", yeni)
    assert not sonuc["hazir"]
    yanit = _mcp_cagir(islem, "arthur_mask_surumleri_karsilastir")
    assert "hazır değil" in yanit["hata"] and vkn not in json.dumps(yanit, ensure_ascii=False)


def test_karsilastirma_yalniz_word(islem):  # noqa: F811
    from arthur_mask.islem import IslemHatasi

    with pytest.raises(IslemHatasi, match="yalnız Word"):
        islem.arayuz_karsilastir(islem.depo.aktif_dosya, "a.txt", b"x", "b.docx", _docx(["x"]))


def test_http_karsilastir_iki_dosyayi_tek_istekte_alir(yerel):  # noqa: F811
    klasor = yerel.islem.depo.aktif_dosya
    eski, yeni = _docx(["Süre 30 gündür."]), _docx(["Süre 60 gündür."])
    durum, govde = _istek(yerel, "POST", f"/api/dosyalar/{quote(klasor)}/karsilastir", eski + yeni, basliklar={
        "X-Boyut-1": str(len(eski)), "X-Dosya-Adi-1": "ozgun.docx", "X-Dosya-Adi-2": "yeni.docx"})
    assert durum == 201, govde
    veri = json.loads(govde)
    assert veri["ozet"] == "1 paragraf değişti" and veri["cevap"]["tur"] == "karsilastirma"
    durum, _ = _istek(yerel, "POST", f"/api/dosyalar/{quote(klasor)}/karsilastir", eski, basliklar={"X-Boyut-1": "0"})
    assert durum == 422

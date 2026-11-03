import zipfile
from pathlib import Path

import pytest

from arthur_mask import belgeler, cli, goruntu
from arthur_mask.kasa import PAROLA_DEGISKENI, Kasa
from arthur_mask.servis import geri_ac_metin, maskele_belge

from .conftest import TCKN

docx_kutuphanesi = pytest.importorskip("docx")


def _word_belgesi(yol: Path) -> None:
    belge = docx_kutuphanesi.Document()
    belge.core_properties.author = "Av. Gizli Yazar"
    belge.core_properties.last_modified_by = "Gizli Kişi"
    p = belge.add_paragraph()
    p.add_run("DAVACI: ").bold = True
    # Adı iki run'a böl: Word'de yazım denetimi / biçim değişikliği bunu yapar.
    p.add_run("Ayşe ")
    p.add_run("KARA").italic = True
    p.add_run(f" (TCKN: {TCKN})")
    belge.add_paragraph("Adres: Örnek Mahallesi, Gül Sokak, No:10, Beşiktaş, İstanbul")
    tablo = belge.add_table(rows=1, cols=2)
    tablo.cell(0, 0).text = "Tanık"
    tablo.cell(0, 1).text = "VEKİLİ: Av. Mehmet Ali YILMAZ"
    belge.sections[0].header.paragraphs[0].text = "Dosya No: 2024/5678 E."
    belge.save(yol)


def test_docx_bolunmus_run_ve_ustbilgi(tmp_path, motor):
    kaynak = tmp_path / "dilekce.docx"
    _word_belgesi(kaynak)
    belge = belgeler.ac(kaynak)
    assert "DAVACI: Ayşe KARA" in belge.metin

    kasa = Kasa()
    sonuc = maskele_belge(belge, motor, kasa)
    hedef = tmp_path / "dilekce.maskeli.docx"
    belge.yaz(sonuc.degisiklikler, hedef)

    okunan = docx_kutuphanesi.Document(hedef)
    govde = "\n".join(p.text for p in okunan.paragraphs)
    assert "DAVACI: {{KİŞİ-01}} (TCKN: {{TCKN-01}})" in govde
    assert "Ayşe" not in govde and "KARA" not in govde
    assert "{{ADRES-01}}" in govde
    assert "{{KİŞİ-02}}" in okunan.tables[0].cell(0, 1).text
    assert okunan.sections[0].header.paragraphs[0].text == "Dosya No: {{DOSYA_NO-01}}"
    assert okunan.paragraphs[0].runs[0].bold  # biçim korunur
    assert okunan.core_properties.author == "" and okunan.core_properties.last_modified_by == ""

    with zipfile.ZipFile(hedef) as zf:
        assert all("Ayşe".encode() not in zf.read(ad) for ad in zf.namelist())

    geri = belgeler.ac(hedef)
    acik, degisiklikler, bilinmeyen = geri_ac_metin(geri.metin, kasa)
    assert not bilinmeyen and "DAVACI: Ayşe KARA" in acik
    acik_yol = tmp_path / "dilekce.acik.docx"
    geri.yaz(degisiklikler, acik_yol)
    assert "Ayşe KARA" in docx_kutuphanesi.Document(acik_yol).paragraphs[0].text


def test_alisilmadik_onekli_docx_islenmez(tmp_path):
    """Maskeleyicinin göremediği metni Claude görünümü görecekse belge işlenmez (aksi hâlde maskesiz giderdi)."""
    from arthur_mask import docx as docx_modulu

    kaynak, hedef = tmp_path / "olagan.docx", tmp_path / "onekli.docx"
    _word_belgesi(kaynak)
    with zipfile.ZipFile(kaynak) as zin, zipfile.ZipFile(hedef, "w") as zout:
        for bilgi in zin.infolist():
            veri = zin.read(bilgi)
            if bilgi.filename == "word/document.xml":
                veri = veri.replace(b"<w:", b"<ns0:").replace(b"</w:", b"</ns0:").replace(b"xmlns:w=", b"xmlns:ns0=")
            zout.writestr(bilgi, veri)
    assert docx_modulu.oku(kaynak).metin  # olağan Word dosyası okunur
    with pytest.raises(docx_modulu.DocxHatasi, match="yeniden kaydedin"):
        docx_modulu.oku(hedef)


_HYPERLINK = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"


def _ustverili_word(yol: Path) -> None:
    """Gövdede maskelenecek ad ("Ayşe KARA") gövde dışında da geçer; ayrıca gövdede hiç geçmeyen bir kişi
    ("Zümrüt Karabacak") yazar, kişi listesi, özel özellik, belge değişkeni, alt metin ve şablon yolunda durur."""
    gecici = yol.with_name("taban.docx")
    _word_belgesi(gecici)
    ekler = {
        "word/document.xml": (b"<w:sectPr", (
            '<w:p><w:ins w:id="901" w:author="Zümrüt Karabacak" w:date="2026-01-01T00:00:00Z"><w:r><w:t>ek</w:t></w:r>'
            '</w:ins><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> MERGEFIELD '
            '"Ayşe KARA" </w:instrText></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
            '<w:p><w:fldSimple w:instr=" AUTHOR Ayşe KARA "><w:r><w:t>alan</w:t></w:r></w:fldSimple></w:p>'
            '<w:p><w:r><w:drawing><wp:inline><wp:extent cx="1" cy="1"/><wp:docPr id="901" name="Resim" '
            'descr="Zümrüt Karabacak imzası" title="Zümrüt Karabacak"/></wp:inline></w:drawing></w:r></w:p>')),
        "word/_rels/document.xml.rels": (b"</Relationships>", (
            f'<Relationship Id="rId901" Type="{_HYPERLINK}" Target="https://ornek.com/ayse-kara" TargetMode="External"/>'
            f'<Relationship Id="rId902" Type="{_HYPERLINK}" Target="https://www.mevzuat.gov.tr/" TargetMode="External"/>'
            '<Relationship Id="rId903" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            'attachedTemplate" Target="file:///C:/Users/zumrut.karabacak/Normal.dotm" TargetMode="External"/>')),
        "word/settings.xml": (b"</w:settings>", '<w:docVars><w:docVar w:name="musteri" w:val="Zümrüt Karabacak"/></w:docVars>'),
    }
    yeni_parcalar = {
        "customXml/item1.xml": "<kayit><musteri>Ayşe KARA</musteri><not>Tanık listesi</not></kayit>",
        "word/people.xml": ('<w15:people xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml">'
                            '<w15:person w15:author="Zümrüt Karabacak"><w15:presenceInfo w15:providerId="AD" '
                            'w15:userId="S::zumrut@ornek.com::1"/></w15:person></w15:people>'),
        "docProps/custom.xml": ('<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" '
                                'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
                                '<property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="2" name="Müvekkil">'
                                '<vt:lpwstr>Zümrüt Karabacak</vt:lpwstr></property></Properties>'),
    }
    with zipfile.ZipFile(gecici) as zin, zipfile.ZipFile(yol, "w", zipfile.ZIP_DEFLATED) as zout:
        for bilgi in zin.infolist():
            veri = zin.read(bilgi)
            if bilgi.filename in ekler:
                yer, ek = ekler[bilgi.filename]
                veri = veri.replace(yer, ek.encode("utf-8") + yer, 1)
            veri = yeni_parcalar.pop(bilgi.filename, None) or veri
            zout.writestr(bilgi, veri.encode("utf-8") if isinstance(veri, str) else veri)
        for ad, veri in yeni_parcalar.items():
            zout.writestr(ad, veri)


def test_maskeli_word_kopyasinda_ustveri_kalmaz(tmp_path, motor):
    from arthur_mask.cikis import normallestir

    kaynak = tmp_path / "ustveri.docx"
    _ustverili_word(kaynak)
    with zipfile.ZipFile(kaynak) as zf:
        assert any(ad.startswith("docProps/thumbnail") for ad in zf.namelist())
    belge = belgeler.ac(kaynak)
    kasa = Kasa()
    sonuc = maskele_belge(belge, motor, kasa)
    hedef = tmp_path / "ustveri.maskeli.docx"
    belge.yaz(sonuc.degisiklikler, hedef)

    with zipfile.ZipFile(hedef) as zf:
        parcalar = {ad: zf.read(ad).decode("utf-8", "ignore") for ad in zf.namelist()}
    for ad, metin in parcalar.items():
        katli = normallestir(metin)[0]
        assert "zumrut" not in katli and "karabacak" not in katli and "ayse kara" not in katli, ad
    assert not any(ad.startswith("docProps/thumbnail") for ad in parcalar)
    assert "thumbnail" not in parcalar["_rels/.rels"]
    govde = parcalar["word/document.xml"]
    assert 'w:author="Yazar 1"' in govde and 'w15:author="Yazar 1"' in parcalar["word/people.xml"]
    assert 'MERGEFIELD "{{KİŞİ-01}}"' in govde and "AUTHOR {{KİŞİ-01}}" in govde
    assert "<musteri>{{KİŞİ-01}}</musteri>" in parcalar["customXml/item1.xml"]
    assert "Tanık listesi" in parcalar["customXml/item1.xml"]
    rels = parcalar["word/_rels/document.xml.rels"]
    assert "https://www.mevzuat.gov.tr/" in rels and "maskeli.invalid" in rels
    assert "docVar" not in parcalar["word/settings.xml"] and "property" not in parcalar["docProps/custom.xml"]
    assert docx_kutuphanesi.Document(hedef).paragraphs  # Word kitaplığıyla açılır

    # Geri açma etkilenmez.
    acik, _, bilinmeyen = geri_ac_metin(belgeler.ac(hedef).metin, kasa)
    assert not bilinmeyen and "DAVACI: Ayşe KARA" in acik


def test_buyuk_arsiv_acilmadan_reddedilir(tmp_path, monkeypatch):
    from arthur_mask import sinirlar

    kaynak = tmp_path / "buyuk.docx"
    _word_belgesi(kaynak)
    udf_yolu = tmp_path / "buyuk.udf"
    belgeler.metinden_yaz("bir\niki", udf_yolu)
    monkeypatch.setattr(sinirlar, "AZAMI_ACIK_BOYUT", 50)
    for yol in (kaynak, udf_yolu):
        with pytest.raises(belgeler.BelgeHatasi, match="MB"):
            belgeler.ac(yol)
    monkeypatch.setattr(sinirlar, "AZAMI_ACIK_BOYUT", 400 * 2**20)
    monkeypatch.setattr(sinirlar, "AZAMI_ARSIV_GIRDISI", 3)
    with pytest.raises(belgeler.BelgeHatasi, match="parça"):
        belgeler.ac(kaynak)


def test_ocr_sayfa_ve_piksel_siniri(tmp_path, monkeypatch):
    image = pytest.importorskip("PIL.Image")
    yol = tmp_path / "tarama.png"
    image.new("RGB", (40, 30), "white").save(yol)
    monkeypatch.setattr(goruntu, "AZAMI_GORUNTU_PIKSELI", 100)
    with pytest.raises(goruntu.OcrHatasi, match="büyük"):
        goruntu.sayfa_goruntuleri(yol)
    assert goruntu._olcek(595, 842) < goruntu.PDF_DPI / 72  # A4 bile 100 piksele sığdırılır
    monkeypatch.setattr(goruntu, "AZAMI_GORUNTU_PIKSELI", 64_000_000)
    assert goruntu._olcek(595, 842) == goruntu.PDF_DPI / 72
    olcek = goruntu._olcek(20_000, 20_000)  # pafta boyu sayfa
    assert (20_000 * olcek) ** 2 <= 64_000_000 * 1.0001
    monkeypatch.setattr(goruntu, "AZAMI_OCR_SAYFASI", 0)
    with pytest.raises(goruntu.OcrHatasi, match="bölüp"):
        goruntu.sayfa_goruntuleri(yol)


def test_metinden_docx_word_ile_acilir(tmp_path):
    yol = tmp_path / "taslak.docx"
    belgeler.metinden_yaz("Birinci satır\n  girintili <özel> & karakter\x07\n\f\nikinci sayfa", yol)
    paragraflar = [p.text for p in docx_kutuphanesi.Document(yol).paragraphs]
    assert paragraflar == ["Birinci satır", "  girintili <özel> & karakter", "", "ikinci sayfa"]


def test_metinden_udf_kontrol_karakteri(tmp_path):
    yol = tmp_path / "taslak.udf"
    belgeler.metinden_yaz("sayfa bir\n\f\nsayfa iki", yol)
    assert belgeler.ac(yol).metin == "sayfa bir\n\nsayfa iki"


def test_doc_uzantisi_anlasilir_hata(tmp_path):
    yol = tmp_path / "eski.doc"
    yol.write_bytes(b"\xd0\xcf\x11\xe0")
    with pytest.raises(belgeler.BelgeHatasi, match="docx"):
        belgeler.ac(yol)


reportlab = pytest.importorskip("reportlab")
ARIAL = Path("C:/Windows/Fonts/arial.ttf")


def _pdf(yol: Path, satirlar, bos_sayfa=False) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    font = "Helvetica"
    if ARIAL.exists():
        pdfmetrics.registerFont(TTFont("Arial", str(ARIAL)))
        font = "Arial"
    c = canvas.Canvas(str(yol), pagesize=A4)
    if satirlar:
        c.setFont(font, 11)
        for i, satir in enumerate(satirlar):
            c.drawString(60, 780 - 18 * i, satir)
        c.showPage()
    if bos_sayfa or not satirlar:
        c.rect(50, 50, 200, 200)
        c.showPage()
    c.save()


def test_pdf_metin_katmani_maskelenir(tmp_path, monkeypatch):
    kaynak = tmp_path / "karar.pdf"
    _pdf(kaynak, [f"DAVACI: Ayse KARA TCKN: {TCKN}", "Adres: Ornek Mahallesi Gul Sokak No:10 Besiktas/Istanbul"], bos_sayfa=True)
    monkeypatch.setenv(PAROLA_DEGISKENI, "test")
    if goruntu.ocr_kullanilabilir_mi():
        pytest.skip("OCR kuruluyken boş sayfalı PDF OCR yoluna gider (test_ocr.py kapsar).")
    assert cli.main(["maskele", str(kaynak)]) == 0
    maskeli = (tmp_path / "karar.maskeli.txt").read_text(encoding="utf-8")
    assert "KARA" not in maskeli and TCKN not in maskeli and "{{KİŞİ-01}}" in maskeli
    rapor = (tmp_path / "karar.maske-raporu.md").read_text(encoding="utf-8")
    assert "Metni olmayan sayfalar: 2" in rapor

    assert cli.main(["geri-ac", str(tmp_path / "karar.maskeli.txt"), "--kasa", str(tmp_path / "dosya.kasa"), "--bicim", "docx"]) == 0
    assert "Ayse KARA" in "\n".join(p.text for p in docx_kutuphanesi.Document(tmp_path / "karar.acik.docx").paragraphs)


def test_cok_sayfali_pdf_reddedilir(tmp_path, monkeypatch):
    from arthur_mask import pdf

    kaynak = tmp_path / "uzun.pdf"
    _pdf(kaynak, ["Birinci sayfa: yeterince uzun bir deneme satiri burada."], bos_sayfa=True)
    monkeypatch.setattr(pdf, "AZAMI_PDF_SAYFASI", 1)
    with pytest.raises(belgeler.BelgeHatasi, match="bölüp"):
        belgeler.ac(kaynak)


def test_taranmis_pdf_durdurulur(tmp_path):
    kaynak = tmp_path / "taranmis.pdf"
    _pdf(kaynak, [])
    # OCR yoksa "OCR gerekli", varsa "okunabilir metin bulunamadı" (yalnız çerçeve çizili sayfa).
    with pytest.raises(belgeler.BelgeHatasi, match="OCR|okunabilir metin"):
        belgeler.ac(kaynak)

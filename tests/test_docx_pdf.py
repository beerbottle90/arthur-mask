import zipfile
from pathlib import Path

import pytest

from arthur_mask import belgeler, cli
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
    assert cli.main(["maskele", str(kaynak)]) == 0
    maskeli = (tmp_path / "karar.maskeli.txt").read_text(encoding="utf-8")
    assert "KARA" not in maskeli and TCKN not in maskeli and "{{KİŞİ-01}}" in maskeli
    rapor = (tmp_path / "karar.maske-raporu.md").read_text(encoding="utf-8")
    assert "Metni olmayan sayfalar: 2" in rapor

    assert cli.main(["geri-ac", str(tmp_path / "karar.maskeli.txt"), "--kasa", str(tmp_path / "dosya.kasa"), "--bicim", "docx"]) == 0
    assert "Ayse KARA" in "\n".join(p.text for p in docx_kutuphanesi.Document(tmp_path / "karar.acik.docx").paragraphs)


def test_taranmis_pdf_durdurulur(tmp_path):
    kaynak = tmp_path / "taranmis.pdf"
    _pdf(kaynak, [])
    with pytest.raises(belgeler.BelgeHatasi, match="OCR"):
        belgeler.ac(kaynak)

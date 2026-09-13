"""Çift dilli (AZ | EN) iki sütunlu Word sözleşmesi: yapı Claude'a görünür, revizyon özgün düzene izli işlenir."""

import io
import json
import re
import zipfile

import pytest

docx_kutuphanesi = pytest.importorskip("docx")

from arthur_mask.belgeler import markdown_sadelestir

from .test_servis_kopru import _mcp_cagir, islem  # noqa: F401  (fixture)

AD = "Rəşad Məmmədov"
SIRKET = "Qafqaz Enerji MMC"
SATIRLAR = [
    ("MƏXFİLİK HAQQINDA SAZİŞ", "NON-DISCLOSURE AGREEMENT"),
    (f"Tərəf: {SIRKET}, direktor {AD}.", f"Party: {SIRKET}, director {AD}."),
    ("Saziş 2 (iki) il müddətinə bağlanır.", "This Agreement is concluded for 2 (two) years."),
]


def _iki_sutunlu_docx() -> bytes:
    belge = docx_kutuphanesi.Document()
    belge.add_heading("NDA", level=1)
    tablo = belge.add_table(rows=0, cols=2)
    for az, en in SATIRLAR:
        hucreler = tablo.add_row().cells
        hucreler[0].text, hucreler[1].text = az, en
    tampon = io.BytesIO()
    belge.save(tampon)
    return tampon.getvalue()


def _tablo_hucreleri(yol):
    belge = docx_kutuphanesi.Document(str(yol))
    return [[h.text for h in satir.cells] for satir in belge.tables[0].rows]


def test_cift_sutunlu_sozlesme_yapisi_ve_izli_revizyon(islem):  # noqa: F811
    klasor = islem.depo.aktif_dosya
    kayit = islem.arayuz_belge_isle(klasor, "nda.docx", _iki_sutunlu_docx())
    if kayit["durum"] != "hazir":
        kayit = islem.arayuz_belge_onayla(klasor, kayit["id"], [], [], "Test onayı")
    assert kayit["durum"] == "hazir", kayit

    getir = islem.mcp_belge_getir(kayit["id"])
    assert getir["yapi"].startswith("markdown") and getir["revize_edilebilir"]
    tablo_satirlari = [s for s in getir["metin"].splitlines() if s.startswith("| ")]
    assert len(tablo_satirlari) == len(SATIRLAR)
    assert "| MƏXFİLİK HAQQINDA SAZİŞ | NON-DISCLOSURE AGREEMENT |" in getir["metin"]
    assert AD not in getir["metin"] and "Məmmədov" not in getir["metin"]

    kisi = re.search(r"\{\{KİŞİ-\d+\}\}", getir["metin"]).group(0)
    degisiklikler = [
        {"eski": "2 (iki) il", "yeni": "3 (üç) il"},
        {"eski": "2 (two) years", "yeni": "3 (three) years"},
        {"eski": "yok böyle bir metin", "yeni": "x"},
    ]
    sonuc = _mcp_cagir(islem, "arthur_mask_belgeyi_revize_et",
                       {"kimlik": kayit["id"], "degisiklikler": degisiklikler, "baslik": f"NDA revize {kisi}"})
    giden = json.dumps(sonuc, ensure_ascii=False)
    assert AD not in giden and "Məmmədov" not in giden
    assert sonuc["uygulanan_degisiklik"] == 2 and len(sonuc["uygulanamayan"]) == 1
    assert sonuc["izli_degisiklik"] is True

    yol = islem.depo.dosya_yolu(klasor) / "cevaplar" / sonuc["dosya"]
    with zipfile.ZipFile(yol) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert xml.count("<w:tbl>") == 1 and "<w:ins " in xml and "<w:del " in xml
    assert "3 (üç) il" in xml and "3 (three) years" in xml

    hucreler = _tablo_hucreleri(yol)
    assert len(hucreler) == len(SATIRLAR) and all(len(s) == 2 for s in hucreler)
    # Çözülmüş: gerçek adlar geri geldi, her sütun kendi dilinde kaldı.
    assert AD in hucreler[1][0] and AD in hucreler[1][1]
    assert "{{" not in xml
    assert "müddətinə" in hucreler[2][0] and "concluded" in hucreler[2][1]


def test_udf_icin_markdown_sadelesir():
    md = "# Başlık\n\n| AZ | EN |\n|---|---|\n| **Tərəf** | Party<br>A |\n- madde"
    sade = markdown_sadelestir(md)
    assert "|" not in sade and "#" not in sade and "**" not in sade
    assert "Tərəf    Party A" in sade and "• madde" in sade

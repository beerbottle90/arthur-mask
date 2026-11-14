"""Revizyonda değişiklik gerekçesi Word yorumu olur: yorum dosyası yoksa kurulur, varsa kimlikler çakışmaz;
gerekçesiz değişiklik yorumsuz kalır; izsiz kipte yorum eklenmez. Model gerekmez."""

import io
import re
import zipfile

import pytest

docx_kutuphanesi = pytest.importorskip("docx")

from arthur_mask import docx as docx_okur
from arthur_mask import docx_yapi


def _belge(yol, paragraflar):
    b = docx_kutuphanesi.Document()
    for p in paragraflar:
        b.add_paragraph(p)
    b.save(str(yol))


def _parca(yol, ad):
    with zipfile.ZipFile(yol) as z:
        return z.read(ad).decode("utf-8") if ad in z.namelist() else None


def test_gerekce_yorum_olarak_eklenir(tmp_path):
    kaynak, hedef = tmp_path / "k.docx", tmp_path / "h.docx"
    _belge(kaynak, ["Kira bedeli her yıl yüzde elli artırılır.", "Depozito altı aylık kiradır."])
    rapor = docx_yapi.revizyon_uygula(kaynak, [
        {"eski": "yüzde elli artırılır", "yeni": "TÜFE oranında artırılır",
         "gerekce": "Artış TÜFE sınırını aşamaz (TBK m. 344/1)."},
        {"eski": "altı aylık", "yeni": "üç aylık"},
    ], hedef)
    assert rapor.uygulanan == 2 and rapor.yorum == 1, rapor
    govde = _parca(hedef, "word/document.xml")
    assert govde.count("<w:commentRangeStart") == 1 and govde.count("<w:commentReference") == 1
    yorumlar = _parca(hedef, "word/comments.xml")
    assert "TBK m. 344/1" in yorumlar and 'w:initials="AM"' in yorumlar
    assert "comments.xml" in _parca(hedef, "word/_rels/document.xml.rels")
    assert "/word/comments.xml" in _parca(hedef, "[Content_Types].xml")
    # ArthurMask belgeyi yeniden okuyabiliyor (yorum metni de maskelenecek parçalar arasında).
    okunan = docx_okur.oku(hedef)
    assert "TÜFE oranında" in okunan.metin and "TBK m. 344/1" in okunan.metin
    # python-docx da açabiliyor.
    assert docx_kutuphanesi.Document(str(hedef)).paragraphs


def test_var_olan_yorumla_kimlik_cakismaz(tmp_path):
    kaynak, ara, hedef = tmp_path / "k.docx", tmp_path / "a.docx", tmp_path / "h.docx"
    _belge(kaynak, ["Birinci hüküm burada.", "İkinci hüküm burada."])
    docx_yapi.revizyon_uygula(kaynak, [{"eski": "Birinci", "yeni": "İlk", "gerekce": "Sadeleştirme."}], ara)
    rapor = docx_yapi.revizyon_uygula(ara, [{"eski": "İkinci", "yeni": "Sonraki", "gerekce": "Tutarlılık."}], hedef)
    assert rapor.yorum == 1
    kimlikler = re.findall(r'<w:comment\b[^>]*\bw:id="(\d+)"', _parca(hedef, "word/comments.xml"))
    assert sorted(kimlikler) == ["0", "1"], kimlikler
    with zipfile.ZipFile(hedef) as z:
        assert z.namelist().count("word/comments.xml") == 1


def test_izsiz_kipte_yorum_yok(tmp_path):
    kaynak, hedef = tmp_path / "k.docx", tmp_path / "h.docx"
    _belge(kaynak, ["Süre iki yıldır."])
    rapor = docx_yapi.revizyon_uygula(kaynak, [{"eski": "iki yıl", "yeni": "bir yıl", "gerekce": "x"}], hedef, izli=False)
    assert rapor.uygulanan == 1 and rapor.yorum == 0
    assert _parca(hedef, "word/comments.xml") is None

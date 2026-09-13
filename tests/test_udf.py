import re
import zipfile

import pytest

from arthur_mask import udf
from arthur_mask.kasa import Kasa
from arthur_mask.maskeleyici import ETIKET_DESENI, maskele

from .conftest import TCKN


def _ofsetler(xml):
    return [(int(m[1]), int(m[2])) for m in re.finditer(r'startOffset="(\d+)" length="(\d+)"', xml)]


def _paragraf_metinleri(belge):
    return [belge.metin[s:s + u] for s, u in _ofsetler(belge.xml)]


def test_metinden_udf_ofsetleri_metni_kaplar(tmp_path):
    yol = tmp_path / "a.udf"
    udf.metinden_udf("bir\niki\n\nüç", yol)
    belge = udf.oku(yol)
    assert belge.metin == "bir\niki\n\nüç"
    assert "".join(_paragraf_metinleri(belge)) == belge.metin


TEK_BICIMLI = f"""DAVACI: Ayşe KARA (TCKN: {TCKN})
Adres: Örnek Mahallesi, Gül Sokak, No:10, Beşiktaş, İstanbul
VEKİLİ: Av. Mehmet Ali YILMAZ, Tel: 0532 123 45 67

Dosya No: 2024/5678 E. — Yargıtay 3. HD, 2019/1234 E. kararı.
Av. Mehmet Ali YILMAZ"""


def test_maskele_ve_geri_ac_gidis_donus(tmp_path, motor):
    # Her varlık tek yüzey biçimiyle geçtiğinde geri açma XML'i bayt bayt geri getirir.
    kaynak = tmp_path / "dilekce.udf"
    udf.metinden_udf(TEK_BICIMLI, kaynak)
    belge = udf.oku(kaynak)

    bulgular, _ = motor.analiz(belge.metin)
    kasa = Kasa()
    _, degisiklikler = maskele(belge.metin, bulgular, kasa)
    maskeli_yol = tmp_path / "dilekce.maskeli.udf"
    udf.maskelenmis_yaz(belge, degisiklikler, maskeli_yol)

    maskeli = udf.oku(maskeli_yol)
    assert "Ayşe" not in maskeli.metin
    # paragraf sınırları korunur: her paragraf yine tam bir satır (+ satır sonu)
    assert "".join(_paragraf_metinleri(maskeli)) == maskeli.metin
    assert len(_paragraf_metinleri(maskeli)) == len(_paragraf_metinleri(belge))

    geri = [(m.start(), m.end(), kasa.bul(m.group()).degerler[0]) for m in ETIKET_DESENI.finditer(maskeli.metin)]
    acik_yol = tmp_path / "dilekce.acik.udf"
    udf.maskelenmis_yaz(maskeli, geri, acik_yol)
    assert udf.oku(acik_yol).xml == belge.xml


def test_bmp_disi_karakterde_utf16_ofset(tmp_path):
    yol = tmp_path / "emoji.udf"
    metin = "🙂 DAVACI: Ayşe KARA\nson"
    udf.metinden_udf(metin, yol)
    belge = udf.oku(yol)
    assert _ofsetler(belge.xml)[0] == (0, len(metin.split("\n")[0]) + 2)  # emoji 2 UTF-16 birimi, +1 satır sonu
    bas = metin.index("Ayşe KARA")
    xml, yeni = udf.maskelenmis_xml(belge, [(bas, bas + len("Ayşe KARA"), "{{KİŞİ-01}}")])
    ilk, ikinci = [(int(a), int(b)) for a, b in re.findall(r'startOffset="(\d+)" length="(\d+)"', xml)]
    assert ilk == (0, len("🙂 DAVACI: {{KİŞİ-01}}") + 2)
    assert ikinci[0] == ilk[1]


def test_cdata_kapanisi_kacislanir(tmp_path):
    yol = tmp_path / "c.udf"
    udf.metinden_udf("a ]]> b", yol)
    assert udf.oku(yol).metin == "a ]]> b"


def test_diger_zip_girdileri_korunur(tmp_path):
    yol = tmp_path / "ek.udf"
    udf.metinden_udf("DAVACI: Ayşe KARA", yol)
    with zipfile.ZipFile(yol, "a") as zf:
        zf.writestr("resim.bin", b"\x00\x01")
    belge = udf.oku(yol)
    hedef = tmp_path / "ek2.udf"
    udf.maskelenmis_yaz(belge, [(8, 17, "{{KİŞİ-01}}")], hedef)
    with zipfile.ZipFile(hedef) as zf:
        assert zf.read("resim.bin") == b"\x00\x01"


def test_gecersiz_dosya(tmp_path):
    yol = tmp_path / "x.udf"
    yol.write_bytes(b"zip degil")
    with pytest.raises(udf.UdfHatasi):
        udf.oku(yol)

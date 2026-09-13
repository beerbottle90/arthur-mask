"""Azerbaycan Türkçesi / İngilizce sözleşme: genel "kişi" isimleri ve tanım terimleri maskelenmez."""

import re
from pathlib import Path

from arthur_mask.kasa import Kasa
from arthur_mask.maskeleyici import maskele
from arthur_mask.motor import tanim_terimleri

NDA = (Path(__file__).parent / "veri" / "nda_az_en.txt").read_text(encoding="utf-8")


def _maskeli(motor):
    bulgular, supheli = motor.analiz(NDA)
    return maskele(NDA, bulgular, Kasa())[0], supheli


def test_genel_kisi_isimleri_ve_tanim_terimleri_acik_kalir(motor):
    maskeli, supheli = _maskeli(motor)
    for ifade in ('"Şəxs" hər hansı fiziki şəxs, hüquqi şəxs', '"Person" means any individual',
                  "heç bir Şəxsə", "to any Person", "Hər bir Şəxs və onun Nümayəndələri",
                  "an Authorised Person or an Affiliated Person", "direktorları, işçiləri",
                  '(bundan sonra "Açıqlayan Tərəf")', '(the "Receiving Party")'):
        assert ifade in maskeli, ifade
    assert not [b for b in supheli if b.varlik == "PERSON"]


def test_gercek_veriler_maskelenir_ve_sirket_tutarlidir(motor):
    maskeli, _ = _maskeli(motor)
    for deger in ("Elvin Məmmədov", "Sarah O'Connor", "Leyla Əliyeva", "+994 50 123 45 67",
                  "sarah.oconnor@caspianholdings.com", "AZE12345678", "Caspian Holdings", "Azərenerji", "Azerenerji"):
        assert deger not in maskeli, deger
    # "Azərenerji ASC" ve "Azerenerji OJSC" aynı şirkettir (alfabe farkı + tür eki).
    satirlar = maskeli.splitlines()
    az = re.search(r"Bu Saziş (\{\{ŞİRKET-\d+\}\})", maskeli).group(1)
    en = re.search(r"made between (\{\{ŞİRKET-\d+\}\})", maskeli).group(1)
    assert az == en, satirlar[2:4]


def test_tanim_terimleri_ozel_kisa_adlari_kapsamaz():
    metin = 'ABC Enerji A.Ş. ("ABC") ile Ayşe Kara ("Ayşe Kara") arasında; "Alıcı" anlamına gelir: satın alan taraf.'
    terimler = tanim_terimleri(metin)
    assert "abc" not in terimler and "ayşe kara" not in terimler

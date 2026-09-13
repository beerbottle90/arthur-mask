import pytest

from arthur_mask import cli, kirmizi_hat
from arthur_mask.kasa import PAROLA_DEGISKENI, Kasa, KasaHatasi
from arthur_mask.maskeleyici import ETIKET_DESENI

from .conftest import DILEKCE


def test_kasa_sifreli_ve_tutarli(tmp_path):
    yol = tmp_path / "dosya.kasa"
    kasa = Kasa(dosya="2026-014")
    r1 = kasa.etiket_al("KİŞİ", "PERSON", "ayşe kara", "Ayşe KARA")
    kasa.kaydet(yol, "parola")
    assert b"KARA" not in yol.read_bytes()

    ikinci = Kasa.ac(yol, "parola")
    assert ikinci.etiket_al("KİŞİ", "PERSON", "ayşe kara", "Ayşe Kara") == r1
    assert ikinci.etiket_al("KİŞİ", "PERSON", "ali vural", "Ali VURAL") == "{{KİŞİ-02}}"
    with pytest.raises(KasaHatasi):
        Kasa.ac(yol, "yanlis")


def test_kirmizi_hat_tespiti():
    kategoriler = {u.kategori for u in kirmizi_hat.tara("Müvekkilin beyanı ve sulh teklifi ile sağlık raporu ekte.")}
    assert "Özel nitelikli kişisel veri (KVKK m.6)" in kategoriler
    assert "Uzlaşma / sulh pazarlık sınırları" in kategoriler


def test_cli_maskele_geri_ac(tmp_path, monkeypatch):
    monkeypatch.setenv(PAROLA_DEGISKENI, "test")
    girdi = tmp_path / "dilekce.txt"
    girdi.write_text(DILEKCE, encoding="utf-8")
    assert cli.main(["maskele", str(girdi)]) == 0
    maskeli = (tmp_path / "dilekce.maskeli.txt").read_text(encoding="utf-8")
    assert "Ayşe" not in maskeli
    rapor = (tmp_path / "dilekce.maske-raporu.md").read_text(encoding="utf-8")
    assert "Ayşe" not in rapor.split("Gözden geçirilecek")[0]

    assert cli.main(["geri-ac", str(tmp_path / "dilekce.maskeli.txt"), "--kasa", str(tmp_path / "dosya.kasa")]) == 0
    acik = (tmp_path / "dilekce.acik.txt").read_text(encoding="utf-8")
    assert ETIKET_DESENI.search(acik) is None
    assert acik.splitlines()[:6] == DILEKCE.splitlines()[:6]


def test_cli_kirmizi_hatta_durur(tmp_path, monkeypatch):
    monkeypatch.setenv(PAROLA_DEGISKENI, "test")
    girdi = tmp_path / "not.txt"
    girdi.write_text("DAVACI: Ayşe KARA — savunma stratejisi notları", encoding="utf-8")
    assert cli.main(["maskele", str(girdi)]) == cli.CIKIS_KIRMIZI_HAT
    assert not (tmp_path / "not.maskeli.txt").exists()
    assert cli.main(["maskele", str(girdi), "--kirmizi-hat-onayi", "Ortak onayı 13.09"]) == 0
    assert (tmp_path / "not.maskeli.txt").exists()


def test_bozulmus_etiket_bicimleri_bulunur():
    kasa = Kasa()
    etiket = kasa.etiket_al("KİŞİ", "PERSON", "ayşe kara", "Ayşe KARA")
    assert etiket == "{{KİŞİ-01}}"
    for bozuk in ("{{KISI-01}}", "{{KİŞİ-1}}", "{{ KİŞİ-01 }}", "{{kişi-01}}"):
        assert kasa.bul(bozuk) is not None, bozuk

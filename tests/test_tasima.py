"""1.1.3 ad geçişi: ürün adı bitişik yazılır (ArthurMask); eski kurulumların belgeleri ve güncelleme bildirimi bozulmaz."""

from pathlib import Path

from arthur_mask import depo, guncelleme, tasima


def _ev(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.delenv("ARTHUR_MASK_KOK", raising=False)
    monkeypatch.setattr(depo, "klasor_ustu", lambda: tmp_path)
    return tmp_path


def test_yeni_kurulum_yeni_adi_kullanir(monkeypatch, tmp_path):
    ust = _ev(monkeypatch, tmp_path)
    assert depo.varsayilan_kok() == ust / "ArthurMask"


def test_tasinamamis_eski_klasor_kullanilmaya_devam_eder(monkeypatch, tmp_path):
    ust = _ev(monkeypatch, tmp_path)
    (ust / depo.ESKI_KLASOR_ADI / "Dosya A").mkdir(parents=True)
    assert depo.varsayilan_kok() == ust / depo.ESKI_KLASOR_ADI


def test_ikisi_de_varsa_yeni_klasor_secilir(monkeypatch, tmp_path):
    ust = _ev(monkeypatch, tmp_path)
    (ust / depo.ESKI_KLASOR_ADI).mkdir()
    (ust / "ArthurMask").mkdir()
    assert depo.varsayilan_kok() == ust / "ArthurMask"


def test_baska_surec_yokken_klasor_tasinir(monkeypatch, tmp_path):
    ust = _ev(monkeypatch, tmp_path)
    (ust / depo.ESKI_KLASOR_ADI / "Dosya A").mkdir(parents=True)
    (ust / depo.ESKI_KLASOR_ADI / "Dosya A" / "dosya.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(tasima, "_baska_surec_var", lambda desen: False)
    assert tasima.belge_klasorunu_tasi() is True
    assert (ust / "ArthurMask" / "Dosya A" / "dosya.json").exists()
    assert not (ust / depo.ESKI_KLASOR_ADI).exists()
    assert depo.varsayilan_kok() == ust / "ArthurMask"


def test_calisan_surec_varken_klasor_tasinmaz(monkeypatch, tmp_path):
    ust = _ev(monkeypatch, tmp_path)
    (ust / depo.ESKI_KLASOR_ADI).mkdir()
    monkeypatch.setattr(tasima, "_baska_surec_var", lambda desen: True)
    assert tasima.belge_klasorunu_tasi() is False
    assert depo.varsayilan_kok() == ust / depo.ESKI_KLASOR_ADI


def test_yeni_klasor_varken_eskisine_dokunulmaz(monkeypatch, tmp_path):
    ust = _ev(monkeypatch, tmp_path)
    (ust / depo.ESKI_KLASOR_ADI).mkdir()
    (ust / "ArthurMask").mkdir()
    monkeypatch.setattr(tasima, "_baska_surec_var", lambda desen: False)
    assert tasima.belge_klasorunu_tasi() is False
    assert (ust / depo.ESKI_KLASOR_ADI).exists()


def test_surum_basligi_eski_ve_yeni_yazimi_okur():
    for baslik in ("Arthur Mask 1.0.0 — Windows kurulum dosyası", "ArthurMask 1.2.0 — Windows ve macOS"):
        assert guncelleme.BASLIK_SURUMU.search(baslik)
    surumler = [{"name": "ArthurMask 1.2.0 — Windows ve macOS kurulum dosyaları", "html_url": "s",
                 "assets": [{"name": f"ArthurMask-Kurulum.{guncelleme.KURULUM_UZANTISI}",
                             "browser_download_url": "a"}]}]
    assert guncelleme.en_yeni(surumler)["surum"] == "1.2.0"


def test_eski_uygulama_temizligi_macos_disinda_bir_sey_yapmaz(monkeypatch, tmp_path):
    monkeypatch.setattr(tasima.sys, "platform", "win32")
    assert tasima.eski_uygulamayi_kaldir(tmp_path / "ArthurMask.app") == []


def test_eski_adli_uygulamanin_kendisi_kendini_silmez(monkeypatch, tmp_path):
    monkeypatch.setattr(tasima.sys, "platform", "darwin")
    assert tasima.eski_uygulamayi_kaldir(tmp_path / tasima.ESKI_UYGULAMA) == []

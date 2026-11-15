"""Ortak üst şerit: güncelleme denetimi, "Şimdi güncelle", sistem bilgisi, yenilikler ve ortak tercih dosyası.

ArthurLegal'in `al.py`'si yerine, sözleşmedeki JSON'u basan sahte bir betik kullanılır.
"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from arthur_mask import __version__, guncelleme, serit
from arthur_mask.sunucu import YerelSunucu

SAHTE_AL = r'''
import json, os, sys, time
from pathlib import Path
kok = Path(__file__).resolve().parents[1]
arg = sys.argv[1:]
(kok / "cagrilar.txt").open("a", encoding="utf-8").write(" ".join(arg) + "\n")
if arg[:1] == ["guncelle"] and "--denetle" in arg:
    veri = json.loads((kok / "denetim.json").read_text(encoding="utf-8"))
    veri["onbellek"] = "--zorla" not in arg
    kilit = kok / "veri" / "guncelle.kilit"
    veri.setdefault("guncelleme", {})["calisiyor"] = kilit.exists()
    print(json.dumps(veri, ensure_ascii=False))
elif arg[:1] == ["guncelle"] and "--tani" in arg:
    print(json.dumps({"urun": "ArthurLegal", "surumler": {"al": "3.3.1", "mask": "1.4.0"},
                      "isletim_sistemi": "Windows 10 Pro 10.0.19045", "mimari": "AMD64", "python": "3.12.7",
                      "dil": "tr", "moduller": ["hukuk-burosu", "mask"], "son_denetim": "2026-11-15 14:05",
                      "son_sonuc": "paket güncel (3.3.1)", "son_hatalar": []}, ensure_ascii=False))
elif arg == ["guncelle"]:
    kilit = kok / "veri" / "guncelle.kilit"
    kilit.write_text(str(os.getpid()), encoding="utf-8")
    time.sleep(1.0)
    kilit.unlink()
    (kok / "guncellendi.txt").write_text("1", encoding="utf-8")
'''

DENETIM = {
    "durum": "yeni", "denetim": 1763190000, "onbellek": False,
    "kurulu": {"al": "3.3.0", "masa": "3.3.0", "mask": "1.3.0"},
    "son": {"al": "3.3.1", "masa": "3.3.1", "mask": "1.4.1"},
    "yeni": ["al", "masa", "mask"],
    "yenilikler": {"tr": ["Bir", "İki", "Üç", "Dört", "Beş", "Altı"], "az": ["Bir"], "en": ["One"]},
    "baglanti": {"al": "https://github.com/beerbottle90/ArthurLegal#indir",
                 "mask": "https://github.com/beerbottle90/ArthurLegal/releases/tag/arthur-mask"},
    "guncelleme": {"calisiyor": False, "son_sonuc": "paket güncel (3.3.0)", "yeniden_baslat": False},
}


@pytest.fixture()
def kok(tmp_path, monkeypatch):
    kok = tmp_path / "ArthurLegal"
    (kok / "bin").mkdir(parents=True)
    (kok / "veri").mkdir()
    (kok / "bin" / "al.py").write_text(SAHTE_AL, encoding="utf-8")
    (kok / "denetim.json").write_text(json.dumps(DENETIM, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("ARTHURLEGAL_KOK", str(kok))
    monkeypatch.setenv("APPDATA", str(tmp_path / "ayar"))
    monkeypatch.setattr(serit, "al_python", lambda: Path(sys.executable))
    monkeypatch.setattr(serit, "_surec", None)
    return kok


def denetim_yaz(kok, **degisiklik):
    (kok / "denetim.json").write_text(json.dumps({**DENETIM, **degisiklik}, ensure_ascii=False), encoding="utf-8")


def test_yalniz_mask_modulune_bakar_ve_yenilikler_bes_maddedir(kok):
    sonuc = serit.denetle(zorla=True)
    assert sonuc["kaynak"] == "al" and sonuc["durum"] == "yeni"
    assert sonuc["son"] == "1.4.1" and sonuc["kurulu"] == __version__
    assert len(sonuc["yenilikler"]["tr"]) == 5
    assert "--zorla" in (kok / "cagrilar.txt").read_text(encoding="utf-8")
    # Yalnız ArthurLegal'in kendisi yeniyse ArthurMask düğmesi "güncel" der.
    denetim_yaz(kok, yeni=["al", "masa"])
    sonuc = serit.denetle()
    assert sonuc["durum"] == "guncel" and sonuc["yenilikler"] == {}
    assert sonuc["onbellek"] is True
    assert (kok / "cagrilar.txt").read_text(encoding="utf-8").splitlines()[-1] == "guncelle --denetle --json"


def test_baglantilar_yalniz_beerbottle90_onekiyle_gecer(kok):
    for kotu in ("https://evil.example/ArthurMask.exe", "http://github.com/beerbottle90/ArthurLegal",
                 "https://github.com/beerbottle90.evil.com/x", "javascript:alert(1)", 5, None):
        denetim_yaz(kok, baglanti={"al": kotu, "mask": kotu})
        sonuc = serit.denetle(zorla=True)
        assert sonuc["sayfa"] == serit.MASK_SURUM_SAYFASI
        assert sonuc["kurulum"] == serit.kurulum_sayfasi()
    assert serit.baglanti_gecerli("https://github.com/beerbottle90/ArthurLegal/releases/tag/arthur-mask")
    assert not serit.baglanti_gecerli('https://github.com/beerbottle90/x" onclick="y')


def test_hata_ve_bozuk_cikti(kok):
    denetim_yaz(kok, durum="hata", hata="internet yok", son={}, yeni=[])
    sonuc = serit.denetle(zorla=True)
    assert sonuc["durum"] == "hata" and sonuc["hata"] == "internet yok"
    (kok / "bin" / "al.py").write_text("print('JSON değil')", encoding="utf-8")
    assert serit.denetle(zorla=True)["durum"] == "hata"


def test_al_yoksa_kendi_bildirimcisine_duser(kok, monkeypatch):
    (kok / "bin" / "al.py").unlink()
    monkeypatch.setattr(guncelleme, "denetle", lambda zorla=False: {
        "durum": "yeni", "denetim": 1, "son": {"surum": "9.9.9", "sayfa": "https://evil.example/"}})
    sonuc = serit.denetle(zorla=True)
    assert sonuc["kaynak"] == "mask" and sonuc["durum"] == "yeni" and sonuc["son"] == "9.9.9"
    assert sonuc["sayfa"] == serit.MASK_SURUM_SAYFASI and sonuc["guncellenebilir"] is False
    assert serit.guncellemeyi_baslat() == {"basladi": False, "neden": "al_yok"}


def test_simdi_guncelle_arka_planda_baslar_ikinci_kez_baslamaz(kok):
    assert serit.guncellemeyi_baslat() == {"basladi": True}
    assert serit.guncellemeyi_baslat()["basladi"] is False
    assert serit.denetle()["guncelleme"]["calisiyor"] is True
    son = time.time() + 20
    while not (kok / "guncellendi.txt").exists() and time.time() < son:
        time.sleep(0.1)
    serit._surec.wait(10)
    assert (kok / "guncellendi.txt").exists()
    assert serit.denetle()["guncelleme"]["calisiyor"] is False
    # Kilit dosyası (başka bir güncelleyici) varken başlatılmaz.
    (kok / "veri" / "guncelle.kilit").write_text("1", encoding="utf-8")
    assert serit.guncellemeyi_baslat() == {"basladi": False, "neden": "calisiyor"}


def test_tercih_dosyasi_oteki_anahtarlari_korur(kok):
    yol = kok / "veri" / "arayuz-tercihleri.json"
    yol.write_text(json.dumps({"dil": "az", "yazi": "buyuk", "gorulen_yenilikler": {"masa": "3.3.1"},
                               "baska": 1}), encoding="utf-8")
    assert serit.tercihler() == {"dil": "az", "yazi": "buyuk", "karsitlik": False, "gorulen_yenilik": None}
    serit.tercih_yaz({"dil": "en", "karsitlik": True, "gorulen_yenilik": "1.4.0"})
    veri = json.loads(yol.read_text(encoding="utf-8"))
    assert veri == {"dil": "en", "yazi": "buyuk", "karsitlik": True, "baska": 1,
                    "gorulen_yenilikler": {"masa": "3.3.1", "mask": "1.4.0"}}
    assert not yol.with_name(yol.name + ".tmp").exists()
    for bozuk in ({"dil": "de"}, {"yazi": "dev"}, {"karsitlik": "evet"}, {"gorulen_yenilik": "../x"}):
        with pytest.raises(ValueError):
            serit.tercih_yaz(bozuk)


def test_dil_okuma_sirasi(kok, tmp_path, monkeypatch):
    (kok / "veri" / "durum.json").write_text(json.dumps({"dil": "en", "masa_dili": "az"}), encoding="utf-8")
    assert serit.tercihler()["dil"] == "az"
    (kok / "veri" / "durum.json").write_text(json.dumps({"dil": "en"}), encoding="utf-8")
    assert serit.tercihler()["dil"] == "en"
    # Kurulum kökü yoksa ArthurMask kendi klasöründe tutar; varsayılan Türkçe.
    monkeypatch.setenv("ARTHURLEGAL_KOK", str(tmp_path / "yok"))
    assert serit.tercihler()["dil"] == "tr"
    serit.tercih_yaz({"dil": "az"})
    assert (tmp_path / "ayar" / "ArthurMask" / "arayuz-tercihleri.json").exists()


def test_yenilikler_kurulu_paketten_ve_kendi_dosyasindan(kok):
    (kok / "aktif.txt").write_text("3.3.1", encoding="utf-8")
    (kok / "surumler" / "3.3.1").mkdir(parents=True)
    (kok / "surumler" / "3.3.1" / "yenilikler.json").write_text(
        json.dumps({"3.3.1": {"tr": ["Masa yeni"], "az": ["Masa yeni (az)"], "en": ["New desk"]}}), encoding="utf-8")
    y = serit.yenilikler()
    assert y["al"] == {"surum": "3.3.1", "maddeler": {"tr": ["Masa yeni"], "az": ["Masa yeni (az)"], "en": ["New desk"]}}
    assert y["mask"]["surum"] == __version__
    for dil in ("tr", "az", "en"):
        assert 1 <= len(y["mask"]["maddeler"][dil]) <= 5


def test_tani_belge_bilgisi_tasimaz(kok):
    t = serit.tani()
    assert t["arayuz"] == "ArthurMask" and t["surum"] == __version__
    assert t["al"]["surumler"]["al"] == "3.3.1"
    assert set(t) == {"arayuz", "surum", "al", "al_kurulu", "isletim_sistemi", "mimari", "python"}


# -- HTTP uçları ----------------------------------------------------------------------------------------
@pytest.fixture()
def yerel(kok, tmp_path, monkeypatch):
    class SahteDepo:
        aktif_dosya = None
        kok = tmp_path

    class SahteIslem:
        depo = SahteDepo()
        motor_hazir = True
        _motor = None

    sunucu = YerelSunucu(SahteIslem(), port=0, belirtec="test-belirtec")
    assert sunucu.baslat()
    yield sunucu
    sunucu.durdur()


def istek(sunucu, yontem, yol, govde=None, belirtec="test-belirtec"):
    veri = None if govde is None else json.dumps(govde).encode()
    basliklar = {"Content-Type": "application/json"}
    if belirtec:
        basliklar["X-Arthur-Mask"] = belirtec
    r = urllib.request.Request(sunucu.adres.rstrip("/") + yol, data=veri, method=yontem, headers=basliklar)
    try:
        with urllib.request.urlopen(r, timeout=30) as y:
            return y.status, json.loads(y.read())
    except urllib.error.HTTPError as h:
        return h.code, json.loads(h.read())


def test_http_serit_uclari(yerel, kok):
    assert istek(yerel, "GET", "/api/serit", belirtec="")[0] == 401
    durum, bilgi = istek(yerel, "GET", "/api/serit")
    assert durum == 200 and bilgi["surum"] == __version__ and bilgi["al_kurulu"] is True
    assert all(a.startswith(serit.BAGLANTI_ONEKI) for a in bilgi["baglantilar"].values())
    durum, sonuc = istek(yerel, "POST", "/api/serit/denetle", {"zorla": True})
    assert durum == 200 and sonuc["durum"] == "yeni" and sonuc["son"] == "1.4.1"
    durum, t = istek(yerel, "GET", "/api/serit/tani")
    assert durum == 200 and t["al"]["isletim_sistemi"].startswith("Windows")
    durum, y = istek(yerel, "GET", "/api/serit/yenilikler")
    assert durum == 200 and y["mask"]["maddeler"]["en"]
    durum, tercih = istek(yerel, "POST", "/api/serit/tercih", {"dil": "en", "yazi": "cok-buyuk"})
    assert durum == 200 and tercih["dil"] == "en" and tercih["yazi"] == "cok-buyuk"
    assert istek(yerel, "POST", "/api/serit/tercih", {"dil": "fr"})[0] == 422
    durum, d = istek(yerel, "GET", "/api/durum")
    assert durum == 200 and "claude_kayitli" in d


def test_sozluk_dosyalari_sunulur(yerel):
    for ad in ("dil-az.json", "dil-en.json", "yenilikler.json"):
        with urllib.request.urlopen(yerel.adres + ad, timeout=10) as y:
            assert y.status == 200
            assert isinstance(json.loads(y.read()), dict)

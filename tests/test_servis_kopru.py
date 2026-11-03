"""Yerel servis, HTTP API ve MCP köprüsü: uçtan uca akış ve sızıntı sözleşmesi."""

import asyncio
import base64
import json
import secrets
import sys
import urllib.error
import urllib.request

import pytest

from arthur_mask.anahtar import ORTAM_DEGISKENI
from arthur_mask.depo import Depo
from arthur_mask.islem import Islem
from arthur_mask.kopru import sunucu_olustur
from arthur_mask.sunucu import YerelSunucu

from .conftest import TCKN

# Uçtan uca izlenecek işaretli sahte değerler: hiçbiri Claude'a giden bir çıktıda görünmemeli.
ISARETLI = ["Zümrüt KARABACAK", TCKN, "zumrut.karabacak@ornekhukuk.av.tr", "0532 987 65 43"]
BELGE = (
    f"DAVACI: {ISARETLI[0]} (TCKN: {ISARETLI[1]})\n"
    f"E-posta: {ISARETLI[2]}, Tel: {ISARETLI[3]}\n"
    "Müvekkil KARABACAK alacağın tahsilini talep etmektedir.\n"
)


@pytest.fixture()
def islem(tmp_path, monkeypatch, motor):
    monkeypatch.setenv(ORTAM_DEGISKENI, base64.b64encode(secrets.token_bytes(32)).decode())
    islem = Islem(Depo(secrets.token_bytes(32), kok=tmp_path / "Arthur Mask"), semantik=False)
    islem._motor = motor
    islem._motor_hazir.set()
    klasor = islem.depo.dosya_olustur("2026-014 alacak")
    islem.depo.aktif_dosya = klasor
    return islem


def test_hazir_belge_mcp_ile_maskeli_gider_teslim_yerelde_cozulur(islem):
    klasor = islem.depo.aktif_dosya
    kayit = islem.arayuz_belge_isle(klasor, "Zümrüt Karabacak dilekçe.txt", BELGE.encode("utf-8"))
    assert kayit["durum"] == "hazir", kayit

    liste = islem.mcp_belgeler()
    getir = islem.mcp_belge_getir(kayit["id"])
    giden = json.dumps([liste, getir], ensure_ascii=False)
    for deger in ISARETLI + ["Zümrüt Karabacak dilekçe"]:
        assert deger not in giden
    assert "{{KİŞİ-01}}" in getir["metin"]

    cevap = "{{KİŞİ-01}}'in alacağı için ihtarname taslağı: {{EPOSTA-01}} adresine tebliğ edilsin."
    teslim = islem.mcp_teslim(cevap, "docx", "İhtarname {{KİŞİ-01}}")
    assert ISARETLI[0] not in json.dumps(teslim, ensure_ascii=False)
    assert "KİŞİ" in teslim["dosya"] and "Zümrüt" not in teslim["dosya"]

    cevaplar = islem.arayuz_cevaplar(klasor)
    assert cevaplar[0]["acik_metin"].startswith("Zümrüt KARABACAK'ın alacağı")


def test_kirmizi_hat_gerekcesiz_claudea_verilemez(islem):
    klasor = islem.depo.aktif_dosya
    metin = BELGE + "Savunma stratejisi: tanık beyanlarındaki çelişki öne çıkarılacak.\n"
    kayit = islem.arayuz_belge_isle(klasor, "not.txt", metin.encode("utf-8"))
    assert kayit["durum"] == "kirmizi_hat"
    assert "hata" in _mcp_cagir(islem, "arthur_mask_belge_getir", {"kimlik": kayit["id"]})

    with pytest.raises(Exception, match="gerekçe"):
        islem.arayuz_belge_onayla(klasor, kayit["id"], [], [], "")
    onayli = islem.arayuz_belge_onayla(klasor, kayit["id"], [], [], "Ortak onayı, 13.09.2026")
    assert onayli["durum"] == "hazir"
    satir = (islem.depo.dosya_yolu(klasor) / "kirmizi-hat.jsonl").read_text(encoding="utf-8")
    assert "Ortak onayı" in satir and ISARETLI[0] not in satir


def test_supheli_aday_onayla_maskelenir_ve_sozluge_yazilir(islem):
    klasor = islem.depo.aktif_dosya
    from arthur_mask.dogrulama import vkn_kontrol_basamagi
    vkn = "987654321" + str(vkn_kontrol_basamagi("987654321"))
    kayit = islem.arayuz_belge_isle(klasor, "fatura.txt", f"Referans {vkn} ile kayıt açıldı.".encode())
    assert kayit["durum"] == "onay_bekliyor" and kayit["supheli"][0]["metin"] == vkn
    onayli = islem.arayuz_belge_onayla(klasor, kayit["id"], [0], [], "")
    assert vkn not in onayli["maskeli_metin"] and onayli["durum"] == "hazir"
    assert vkn in (islem.depo.dosya_yolu(klasor) / "sozluk.yaml").read_text(encoding="utf-8")


def test_yeniden_baslatma_sonrasi_supheli_incelenmeden_onaylanamaz(islem):
    klasor = islem.depo.aktif_dosya
    from arthur_mask.dogrulama import vkn_kontrol_basamagi
    vkn = "123456789" + str(vkn_kontrol_basamagi("123456789"))
    kayit = islem.arayuz_belge_isle(klasor, "fatura.txt", f"Referans {vkn} ile kayıt açıldı.".encode())
    assert kayit["durum"] == "onay_bekliyor"
    islem._bekleyen.clear()  # köprü yeniden başladı: adaylar bellekteydi
    with pytest.raises(Exception, match="yeniden yükleyin"):
        islem.arayuz_belge_onayla(klasor, kayit["id"], [], [], "")
    assert islem.depo.belge_oku(klasor, kayit["id"])["durum"] == "onay_bekliyor"


def _mcp_cagir(islem, arac, argumanlar=None):
    from mcp import Client

    async def calistir():
        async with Client(sunucu_olustur(islem)) as istemci:
            araclar = {a.name for a in (await istemci.list_tools()).tools}
            assert {"arthur_mask_belgeler", "arthur_mask_belge_getir", "arthur_mask_teslim"} <= araclar
            sonuc = await istemci.call_tool(arac, argumanlar or {})
            return json.loads(sonuc.content[0].text)

    return asyncio.run(calistir())


def test_mcp_protokolu_uzerinden_sizinti_yok(islem):
    klasor = islem.depo.aktif_dosya
    kayit = islem.arayuz_belge_isle(klasor, "dilekce.txt", BELGE.encode("utf-8"))
    for arac, arg in [("arthur_mask_belgeler", {}), ("arthur_mask_belge_getir", {"kimlik": kayit["id"]}),
                      ("arthur_mask_teslim", {"metin": "{{KİŞİ-01}} için taslak", "bicim": "udf", "baslik": "taslak"})]:
        cikti = json.dumps(_mcp_cagir(islem, arac, arg), ensure_ascii=False)
        assert not any(deger in cikti for deger in ISARETLI), (arac, cikti)


# -- HTTP API --------------------------------------------------------------------------------------
@pytest.fixture()
def yerel(islem):
    sunucu = YerelSunucu(islem, port=0, belirtec="test-belirtec")
    assert sunucu.baslat()
    yield sunucu
    sunucu.durdur()


def _istek(sunucu, yontem, yol, govde=None, belirtec="test-belirtec", basliklar=None):
    veri = govde if isinstance(govde, bytes) or govde is None else json.dumps(govde).encode()
    istek = urllib.request.Request(f"http://127.0.0.1:{sunucu.port}{yol}", data=veri, method=yontem)
    if belirtec:
        istek.add_header("X-Arthur-Mask", belirtec)
    for anahtar, deger in (basliklar or {}).items():
        istek.add_header(anahtar, deger)
    try:
        with urllib.request.urlopen(istek) as yanit:
            return yanit.status, yanit.read()
    except urllib.error.HTTPError as hata:
        return hata.code, hata.read()


def test_http_guvenlik_kapilari(yerel):
    assert _istek(yerel, "GET", "/api/durum", belirtec=None)[0] == 401
    assert _istek(yerel, "GET", "/api/durum", belirtec="yanlis")[0] == 401
    assert _istek(yerel, "GET", "/api/durum", basliklar={"Origin": "https://kotu.example"})[0] == 403
    assert _istek(yerel, "GET", "/api/durum", basliklar={"Host": "kotu.example"})[0] == 421
    # Sayfa kimliksiz sunulur; aynı bilgisayardaki başka bir hesap da açabileceği için belirteç sayfada olmamalı.
    durum, govde = _istek(yerel, "GET", "/", belirtec=None)
    assert durum == 200 and b"test-belirtec" not in govde and b"BELIRTEC" not in govde


def test_kisayol_belirteci_komut_satirina_yazmaz(tmp_path, monkeypatch):
    from arthur_mask import baslat

    acilan = []
    monkeypatch.setattr(baslat, "uygulama_klasoru", lambda: tmp_path)
    monkeypatch.setattr(baslat, "belirtec_al", lambda: "gizli-belirtec")
    monkeypatch.setattr(baslat.webbrowser, "open", acilan.append)
    baslat.arayuzu_ac()
    assert len(acilan) == 1 and acilan[0].startswith("file:") and "gizli-belirtec" not in acilan[0]
    sayfa = (tmp_path / "ac.html").read_text(encoding="utf-8")
    assert f"{baslat.ADRES}#t=gizli-belirtec" in sayfa


def test_http_uctan_uca(yerel, islem):
    klasor = islem.depo.aktif_dosya
    from urllib.parse import quote
    durum, govde = _istek(yerel, "POST", f"/api/dosyalar/{quote(klasor)}/belgeler", BELGE.encode(),
                          basliklar={"X-Dosya-Adi": quote("dilekçe.txt")})
    assert durum == 201, govde
    kayit = json.loads(govde)
    assert kayit["durum"] == "hazir" and ISARETLI[0] not in kayit["maskeli_metin"]

    islem.mcp_teslim("{{KİŞİ-01}} lehine karar.", "txt", "karar")
    durum, govde = _istek(yerel, "GET", f"/api/dosyalar/{quote(klasor)}/cevaplar")
    cevap = json.loads(govde)["cevaplar"][0]
    assert cevap["acik_metin"] == "Zümrüt KARABACAK lehine karar."
    durum, dosya = _istek(yerel, "GET", f"/api/dosyalar/{quote(klasor)}/cevap-dosyasi?ad={quote(cevap['dosya'])}")
    assert durum == 200 and "Zümrüt KARABACAK".encode() in dosya
    assert _istek(yerel, "GET", f"/api/dosyalar/{quote(klasor)}/cevap-dosyasi?ad=..%2F..%2Fdosya.kasa")[0] == 404


# -- sağlamlaştırma ----------------------------------------------------------------------------------------
def _hazir_kayit(metin, kimlik="belge-1"):
    return {"id": kimlik, "kaynak_ad": "x.txt", "olusturma": "2026-11-03T00:00:00+00:00", "durum": "hazir",
            "bicim": ".txt", "karakter": len(metin), "ozet": "", "maskeli_metin": metin, "etiket_sayisi": 0,
            "turler": {}, "kirmizi_hat": [], "artik": [], "uyarilar": [], "supheli_sayisi": 0, "ocr": False,
            "maskeli_kopya": ""}


def test_parca_sinirina_denk_gelen_deger_kacmaz(islem):
    from arthur_mask.islem import MCP_PARCA_KARAKTER

    klasor = islem.depo.aktif_dosya
    with islem.depo.kasa(klasor) as kasa:
        kasa.etiket_al("KİŞİ", "PERSON", "zümrüt karabacak", "Zümrüt KARABACAK")
    # Kasadaki bir değer, maskeli metinde tam parça sınırına denk gelir.
    dolgu = ("Sözleşme hükümleri aynen geçerlidir. " * 2000)[:MCP_PARCA_KARAKTER - 9] + " "
    metin = dolgu + "Zümrüt KARABACAK ile görüşüldü.\n" + "Ek açıklama.\n" * 10
    islem.depo.belge_kaydet(klasor, _hazir_kayit(metin))

    parcalar = [islem.mcp_belge_getir("belge-1", i) for i in (1, 2)]
    assert parcalar[0]["parca_sayisi"] == 2
    birlesik = "".join(p["metin"] for p in parcalar)
    assert "Zümrüt" not in birlesik and "ARABACAK" not in birlesik and "{{KİŞİ-01}} ile görüşüldü" in birlesik
    assert not parcalar[0]["metin"].endswith("{{") and all(len(p["metin"]) <= MCP_PARCA_KARAKTER for p in parcalar)


def test_etkin_dosya_degisse_de_cagrinin_dosyasi_denetlenir(islem):
    ilk = islem.depo.aktif_dosya
    with islem.depo.kasa(ilk) as kasa:
        kasa.etiket_al("KİŞİ", "PERSON", "zümrüt karabacak", "Zümrüt KARABACAK")
    islem.depo.aktif_dosya = islem.depo.dosya_olustur("2026-015 başka dosya")
    temiz = islem.mcp_cikis("arthur_mask_belge_getir", {"metin": "Zümrüt KARABACAK"}, ilk)
    assert temiz == {"metin": "{{KİŞİ-01}}"}


def test_beklenmeyen_hata_metni_claudea_ve_gunluge_gitmez(islem, monkeypatch, caplog):
    import logging

    def mcp_belgeler():
        raise RuntimeError(f"{ISARETLI[0]} dosyası okunamadı")

    monkeypatch.setattr(islem, "mcp_belgeler", mcp_belgeler)
    with caplog.at_level(logging.INFO, logger="arthur_mask"):
        cikti = _mcp_cagir(islem, "arthur_mask_belgeler")
    assert "RuntimeError" in cikti["hata"] and ISARETLI[0] not in json.dumps(cikti, ensure_ascii=False)
    assert ISARETLI[0] not in caplog.text


def test_api_hata_gunlugunde_dosya_adi_ve_istisna_metni_yok(yerel, islem, monkeypatch, caplog):
    import logging
    from urllib.parse import quote

    klasor = islem.depo.aktif_dosya

    def patla(_klasor):
        raise RuntimeError(f"{ISARETLI[0]} {ISARETLI[1]}")

    monkeypatch.setattr(islem, "arayuz_belgeler", patla)
    with caplog.at_level(logging.DEBUG, logger="arthur_mask"):
        durum, _ = _istek(yerel, "GET", f"/api/dosyalar/{quote(klasor)}/belgeler")
    assert durum == 500
    assert "API hatası: GET /api/dosyalar/<dosya>/belgeler (RuntimeError)" in caplog.text
    assert "alacak" not in caplog.text and ISARETLI[0] not in caplog.text and ISARETLI[1] not in caplog.text
    assert not any(kayit.exc_info for kayit in caplog.records)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX izinleri; Windows'ta kullanıcı klasörü zaten özel")
def test_klasorler_ve_belirtec_yalniz_kullaniciya_acik(tmp_path, monkeypatch):
    import os

    from arthur_mask import sunucu

    kok = tmp_path / "Arthur Mask"
    kok.mkdir()
    os.chmod(kok, 0o755)  # önceden açılmış klasör
    Depo(secrets.token_bytes(32), kok=kok)
    assert kok.stat().st_mode & 0o077 == 0
    monkeypatch.setenv("APPDATA", str(tmp_path / "ayar"))
    sunucu.belirtec_al()
    klasor = tmp_path / "ayar" / "ArthurMask"
    assert klasor.stat().st_mode & 0o077 == 0 and (klasor / "yerel-belirtec").stat().st_mode & 0o077 == 0


def test_revizyon_ciktisi_claude_yazarini_korur(islem):
    """Üstveri temizliği maskeli kopyada yapılır; avukata dönen revizyonda Claude'un izli değişiklikleri adıyla kalır."""
    import io
    import zipfile

    docx_kutuphanesi = pytest.importorskip("docx")
    belge = docx_kutuphanesi.Document()
    belge.add_paragraph(f"DAVACI: {ISARETLI[0]} (TCKN: {ISARETLI[1]})")
    belge.add_paragraph("Talep konusu alacak tahsilidir.")
    tampon = io.BytesIO()
    belge.save(tampon)
    klasor = islem.depo.aktif_dosya
    kayit = islem.arayuz_belge_isle(klasor, "dilekce.docx", tampon.getvalue())
    if kayit["durum"] != "hazir":
        kayit = islem.arayuz_belge_onayla(klasor, kayit["id"], [], list(range(kayit["supheli_sayisi"])), "")
    yanit = islem.mcp_revize(kayit["id"], [{"eski": "alacak tahsilidir", "yeni": "alacağın tahsilidir"}])
    assert yanit["uygulanan_degisiklik"] == 1, yanit
    with zipfile.ZipFile(islem.depo.dosya_yolu(klasor) / "cevaplar" / yanit["dosya"]) as zf:
        govde = zf.read("word/document.xml").decode("utf-8")
    assert 'w:author="Claude (Arthur Mask)"' in govde and ISARETLI[0] in govde

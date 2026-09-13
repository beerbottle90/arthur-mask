"""Yerel servis, HTTP API ve MCP köprüsü: uçtan uca akış ve sızıntı sözleşmesi."""

import asyncio
import base64
import json
import secrets
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
    durum, govde = _istek(yerel, "GET", "/", belirtec=None)
    assert durum == 200 and b"test-belirtec" in govde and b"{{BELIRTEC}}" not in govde


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

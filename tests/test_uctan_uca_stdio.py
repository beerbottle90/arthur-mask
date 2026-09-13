"""Kanıt testi: Claude Desktop'un köprüden aldığı ham baytlarda gerçek değer yok.

Gerçek köprü süreci (`python -m arthur_mask.kopru`) ayrı süreç olarak başlatılır; Claude Desktop
gibi stdio üzerinden MCP konuşulur ve süreçten çıkan bütün baytlar kaydedilir. Claude'a giden
tek kanal budur. Bir tespit kaçağı da taklit edilir (hazır belgeye açık ad eklenir): çıkış kapısı
onu da göndermeden etiketlemelidir.
"""

import base64
import io
import json
import os
import queue
import secrets
import socket
import subprocess
import sys
import threading
import time

import pytest

from arthur_mask.depo import Depo
from arthur_mask.islem import Islem
from arthur_mask.turkce import ascii_kucuk

from .conftest import IBAN, TCKN

docx_kutuphanesi = pytest.importorskip("docx")

GERCEK = {
    "kisi": "Zümrüt KARABACAK",
    "kisi2": "Rəşad Məmmədov",
    "sirket": "Qafqaz Enerji MMC",
    "tckn": TCKN,
    "iban": IBAN,
    "eposta": "zumrut.karabacak@ornekhukuk.av.tr",
    "telefon": "0532 987 65 43",
}
METIN = (
    f"DAVACI: {GERCEK['kisi']} (TCKN: {GERCEK['tckn']})\n"
    f"E-posta: {GERCEK['eposta']}, Tel: {GERCEK['telefon']}\n"
    f"Ödeme {GERCEK['iban']} numaralı hesaba yapılacaktır.\n"
    "Müvekkil KARABACAK alacağın tahsilini talep etmektedir.\n"
)


def _docx() -> bytes:
    belge = docx_kutuphanesi.Document()
    tablo = belge.add_table(rows=0, cols=2)
    for az, en in [
        (f"Tərəf: {GERCEK['sirket']}, direktor {GERCEK['kisi2']}.", f"Party: {GERCEK['sirket']}, director {GERCEK['kisi2']}."),
        ("Saziş 2 (iki) il müddətinə bağlanır.", "This Agreement is concluded for 2 (two) years."),
    ]:
        hucreler = tablo.add_row().cells
        hucreler[0].text, hucreler[1].text = az, en
    tampon = io.BytesIO()
    belge.save(tampon)
    return tampon.getvalue()


def _bos_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _StdioIstemci:
    def __init__(self, komut, ortam):
        self.surec = subprocess.Popen(komut, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, env=ortam)
        self.ham = bytearray()
        self._satirlar: "queue.Queue[bytes]" = queue.Queue()
        threading.Thread(target=self._oku, daemon=True).start()
        self._sira = 0

    def _oku(self):
        for satir in self.surec.stdout:
            self.ham.extend(satir)
            self._satirlar.put(satir)

    def gonder(self, mesaj):
        self.surec.stdin.write((json.dumps(mesaj) + "\n").encode("utf-8"))
        self.surec.stdin.flush()

    def cagir(self, yontem, parametreler=None, zaman_asimi=120):
        self._sira += 1
        self.gonder({"jsonrpc": "2.0", "id": self._sira, "method": yontem, "params": parametreler or {}})
        son = time.monotonic() + zaman_asimi
        while time.monotonic() < son:
            try:
                yanit = json.loads(self._satirlar.get(timeout=max(0.1, son - time.monotonic())))
            except queue.Empty:
                break
            if yanit.get("id") == self._sira:
                return yanit
        raise TimeoutError(yontem)

    def arac(self, ad, argumanlar=None):
        yanit = self.cagir("tools/call", {"name": ad, "arguments": argumanlar or {}})
        assert "result" in yanit, yanit
        return yanit["result"]

    def kapat(self):
        self.surec.stdin.close()
        try:
            self.surec.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.surec.kill()


def _dizeler(oge):
    if isinstance(oge, str):
        yield oge
    elif isinstance(oge, dict):
        for k, v in oge.items():
            yield from _dizeler(k)
            yield from _dizeler(v)
    elif isinstance(oge, list):
        for v in oge:
            yield from _dizeler(v)


def test_claudea_giden_ham_baytlarda_gercek_deger_yok(tmp_path, motor):
    anahtar = secrets.token_bytes(32)
    kok = tmp_path / "Arthur Mask"
    islem = Islem(Depo(anahtar, kok=kok), semantik=False)
    islem._motor, _ = motor, islem._motor_hazir.set()
    klasor = islem.depo.dosya_olustur("uçtan uca")
    islem.depo.aktif_dosya = klasor

    kimlikler = []
    for ad, veri in (("Zümrüt Karabacak dilekçe.txt", METIN.encode("utf-8")), ("nda.docx", _docx())):
        kayit = islem.arayuz_belge_isle(klasor, ad, veri)
        if kayit["durum"] != "hazir":
            kayit = islem.arayuz_belge_onayla(klasor, kayit["id"], list(range(len(kayit["supheli"]))), [], "Test onayı")
        assert kayit["durum"] == "hazir", kayit
        kimlikler.append(kayit["id"])

    # Tespit kaçağı taklidi: hazır belgenin Claude'a verilecek metnine açık ad ve aksansız biçimi eklenir.
    kacak = islem.depo.belge_oku(klasor, kimlikler[0])
    kacak["maskeli_metin"] += f"\nNot: {GERCEK['kisi']} ve ZUMRUT KARABACAK duruşmaya katılacak. Tel 0532-987-6543.\n"
    islem.depo.belge_kaydet(klasor, kacak)

    ortam = {**os.environ, "ARTHUR_MASK_ANA_ANAHTAR": base64.b64encode(anahtar).decode(),
             "ARTHUR_MASK_KOK": str(kok), "APPDATA": str(tmp_path / "appdata"),
             "ARTHUR_MASK_SEMANTIK": "kapali", "PYTHONIOENCODING": "utf-8", "HF_HUB_OFFLINE": "1"}
    (tmp_path / "appdata").mkdir()
    istemci = _StdioIstemci([sys.executable, "-m", "arthur_mask.kopru", "--port", str(_bos_port())], ortam)
    try:
        baslat = istemci.cagir("initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "sizinti-testi", "version": "1"},
        })
        assert "result" in baslat, baslat
        istemci.gonder({"jsonrpc": "2.0", "method": "notifications/initialized"})
        araclar = {a["name"] for a in istemci.cagir("tools/list")["result"]["tools"]}
        assert {"arthur_mask_belgeler", "arthur_mask_belge_getir", "arthur_mask_belgeyi_revize_et", "arthur_mask_teslim"} <= araclar

        sonuclar = [istemci.arac("arthur_mask_belgeler")]
        for kimlik in kimlikler + ["belge-yok"]:
            sonuclar.append(istemci.arac("arthur_mask_belge_getir", {"kimlik": kimlik}))
        sonuclar.append(istemci.arac("arthur_mask_belgeyi_revize_et", {
            "kimlik": kimlikler[1], "degisiklikler": [{"eski": "2 (two) years", "yeni": "3 (three) years"}]}))
        sonuclar.append(istemci.arac("arthur_mask_teslim", {"metin": "{{KİŞİ-01}} için ihtarname.", "baslik": "İhtar {{KİŞİ-01}}"}))
    finally:
        istemci.kapat()

    ham = bytes(istemci.ham)
    assert ham, "köprüden hiç bayt gelmedi"
    ham_katli = ascii_kucuk(ham.decode("utf-8"))
    cozulmus = " ".join(s for satir in ham.decode("utf-8").splitlines() for s in _dizeler(json.loads(satir)))
    cozulmus_katli = ascii_kucuk(cozulmus)
    for ad, deger in GERCEK.items():
        biçimler = {deger, json.dumps(deger)[1:-1], deger.replace(" ", "")}
        for b in biçimler:
            assert b.encode("utf-8") not in ham, f"{ad} ham baytlarda"
            assert ascii_kucuk(b) not in ham_katli, f"{ad} (katlanmış) ham baytlarda"
        assert ascii_kucuk(deger) not in cozulmus_katli, f"{ad} çözülmüş JSON dizelerinde"
    assert "karabacak" not in cozulmus_katli and "9876543" not in cozulmus.replace("-", "").replace(" ", "")

    # Kaçak gerçekten kanala girdi ve kapıda etiketlendi.
    getir = json.dumps(sonuclar[1], ensure_ascii=False)
    assert "duruşmaya katılacak" in getir and "{{KİŞİ-" in getir
    gidenler = islem.arayuz_gidenler(klasor)
    assert gidenler["toplam_yanit"] == len(sonuclar)
    assert gidenler["toplam_yakalanan"] >= 3
    # Denetim: kaçak depodaki maskeli metinde görünür, ama Claude'a giden hiçbir yanıtta görünmez.
    denetim = islem.arayuz_denetle(klasor)
    kaynaklar = [b["kaynak"] for b in denetim["bulgular"]]
    assert any(k.startswith(kimlikler[0]) for k in kaynaklar)
    assert not any("Claude'a giden" in k for k in kaynaklar), kaynaklar

"""Yerel HTTP sunucusu: arayüz dosyaları + JSON API. Yalnız 127.0.0.1.

Güvenlik:
- Host başlığı yalnız 127.0.0.1/localhost olabilir (DNS rebinding'e karşı).
- API isteklerinde `X-Arthur-Mask` belirteci zorunlu; belirteç arayüz sayfasına
  sunucu tarafından gömülür, başka sitelerden okunamaz.
- Origin yalnız aynı köken veya tanımlı eklenti kimliği olabilir.
"""

import json
import logging
import mimetypes
import os
import secrets
import subprocess
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__
from .anahtar import uygulama_klasoru
from .islem import Islem, IslemHatasi

gunluk = logging.getLogger("arthur_mask.sunucu")

VARSAYILAN_PORT = 47831
AZAMI_YUKLEME = 60 * 2**20
BELIRTEC_BASLIGI = "X-Arthur-Mask"


def belirtec_al() -> str:
    yol = uygulama_klasoru() / "yerel-belirtec"
    if not yol.exists():
        yol.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    return yol.read_text(encoding="utf-8").strip()


def _arayuz_dosyasi(ad: str) -> Optional[bytes]:
    if not ad or "/" in ad or "\\" in ad or ad.startswith("."):
        return None
    kaynak = resources.files("arthur_mask") / "arayuz" / ad
    return kaynak.read_bytes() if kaynak.is_file() else None


class _Isleyici(BaseHTTPRequestHandler):
    server_version = "ArthurMask"
    sys_version = ""

    # -- yardımcılar ---------------------------------------------------------------------
    @property
    def uygulama(self) -> "YerelSunucu":
        return self.server.uygulama  # type: ignore[attr-defined]

    def log_message(self, format, *args):  # noqa: A002 - http.server imzası
        gunluk.debug("%s %s", self.address_string(), format % args)

    def _gonder(self, durum: int, govde: bytes, tur: str = "application/json; charset=utf-8", ek=None) -> None:
        self.send_response(durum)
        self.send_header("Content-Type", tur)
        self.send_header("Content-Length", str(len(govde)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "connect-src 'self'; frame-ancestors 'none'",
        )
        for anahtar, deger in (ek or {}).items():
            self.send_header(anahtar, deger)
        self.end_headers()
        self.wfile.write(govde)

    def _json(self, durum: int, veri) -> None:
        self._gonder(durum, json.dumps(veri, ensure_ascii=False).encode("utf-8"))

    def _host_gecerli(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in {"127.0.0.1", "localhost"}

    def _origin_gecerli(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        port = self.server.server_address[1]
        izinli = {f"http://127.0.0.1:{port}", f"http://localhost:{port}", *self.uygulama.eklenti_kokenleri}
        return origin in izinli

    def _yetkili(self) -> bool:
        return secrets.compare_digest(self.headers.get(BELIRTEC_BASLIGI, ""), self.uygulama.belirtec)

    def _govde_json(self) -> dict:
        uzunluk = int(self.headers.get("Content-Length") or 0)
        if uzunluk > AZAMI_YUKLEME:
            raise IslemHatasi("İstek çok büyük.")
        return json.loads(self.rfile.read(uzunluk) or b"{}")

    # -- yönlendirme ---------------------------------------------------------------------
    def do_GET(self):
        self._yonlendir("GET")

    def do_POST(self):
        self._yonlendir("POST")

    def do_DELETE(self):
        self._yonlendir("DELETE")

    def _yonlendir(self, yontem: str) -> None:
        if not self._host_gecerli():
            return self._json(HTTPStatus.MISDIRECTED_REQUEST, {"hata": "Geçersiz Host"})
        adres = urlparse(self.path)
        yol = adres.path

        if yontem == "GET" and not yol.startswith("/api/"):
            return self._statik(yol)
        if not self._origin_gecerli():
            return self._json(HTTPStatus.FORBIDDEN, {"hata": "Köken reddedildi"})
        if not self._yetkili():
            return self._json(HTTPStatus.UNAUTHORIZED, {"hata": "Belirteç eksik ya da yanlış"})

        islem = self.uygulama.islem
        parcalar = [unquote(p) for p in yol.split("/")[2:] if p]
        try:
            if yontem == "GET" and parcalar == ["durum"]:
                return self._json(200, self.uygulama.durum())
            if yontem == "GET" and parcalar == ["dosyalar"]:
                return self._json(200, {"dosyalar": islem.depo.dosyalar(), "aktif": islem.depo.aktif_dosya})
            if yontem == "POST" and parcalar == ["dosyalar"]:
                govde = self._govde_json()
                ad = govde.get("ad", "").strip() or "Adsız dosya"
                klasor = islem.depo.dosya_olustur(islem.depo.benzersiz_ad(ad) if govde.get("benzersiz") else ad)
                islem.depo.aktif_dosya = klasor
                return self._json(201, {"klasor": klasor})
            if yontem == "POST" and parcalar == ["aktif"]:
                islem.depo.aktif_dosya = self._govde_json()["klasor"]
                return self._json(200, {"aktif": islem.depo.aktif_dosya})

            if len(parcalar) >= 3 and parcalar[0] == "dosyalar":
                klasor = parcalar[1]
                kaynak = parcalar[2]
                if kaynak == "belgeler" and len(parcalar) == 3 and yontem == "GET":
                    return self._json(200, {"belgeler": islem.arayuz_belgeler(klasor)})
                if kaynak == "belgeler" and len(parcalar) == 3 and yontem == "POST":
                    uzunluk = int(self.headers.get("Content-Length") or 0)
                    if not 0 < uzunluk <= AZAMI_YUKLEME:
                        raise IslemHatasi("Belge boş ya da 60 MB'tan büyük.")
                    dosya_adi = unquote(self.headers.get("X-Dosya-Adi", "belge"))
                    return self._json(201, islem.arayuz_belge_isle(klasor, dosya_adi, self.rfile.read(uzunluk)))
                if kaynak == "belgeler" and len(parcalar) == 5 and parcalar[4] == "onay" and yontem == "POST":
                    govde = self._govde_json()
                    return self._json(200, islem.arayuz_belge_onayla(
                        klasor, parcalar[3], govde.get("maskelenecek", []), govde.get("birakilacak", []),
                        govde.get("gerekce", ""),
                    ))
                if kaynak == "belgeler" and len(parcalar) == 4 and yontem == "DELETE":
                    islem.arayuz_belge_sil(klasor, parcalar[3])
                    return self._json(200, {"silindi": parcalar[3]})
                if kaynak == "gidenler" and yontem == "GET":
                    return self._json(200, islem.arayuz_gidenler(klasor))
                if kaynak == "denetim" and yontem == "POST":
                    return self._json(200, islem.arayuz_denetle(klasor))
                if kaynak == "cevaplar" and yontem == "GET":
                    return self._json(200, {"cevaplar": islem.arayuz_cevaplar(klasor)})
                if kaynak == "maskeli-dosyasi" and yontem == "GET":
                    return self._maskeli_dosyasi(klasor, parse_qs(adres.query).get("id", [""])[0])
                if kaynak == "cevap-dosyasi" and yontem == "GET":
                    return self._cevap_dosyasi(klasor, parse_qs(adres.query).get("ad", [""])[0])
            if yontem == "GET" and parcalar == ["kurtarma"]:
                return self._json(200, self.uygulama.kurtarma_durumu(goster=True))
            if yontem == "POST" and parcalar == ["kurtarma", "onay"]:
                self.uygulama.kurtarma_onayla()
                return self._json(200, self.uygulama.kurtarma_durumu(goster=False))
            if yontem == "POST" and len(parcalar) == 3 and parcalar[0] == "dosyalar" and parcalar[2] == "cevap-ac":
                govde = self._govde_json()
                return self._json(200, self._cevap_ac(parcalar[1], govde.get("dosya", ""), bool(govde.get("klasorde"))))
            if yontem == "POST" and parcalar == ["coz"]:
                govde = self._govde_json()
                return self._json(200, islem.arayuz_coz(govde.get("metin", ""), govde.get("klasor")))
            return self._json(HTTPStatus.NOT_FOUND, {"hata": "Bulunamadı"})
        except IslemHatasi as hata:
            return self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"hata": str(hata)})
        except (FileNotFoundError, KeyError) as hata:
            return self._json(HTTPStatus.NOT_FOUND, {"hata": f"Bulunamadı: {hata}"})
        except Exception:  # noqa: BLE001 - istemciye iç ayrıntı sızdırma
            gunluk.exception("API hatası: %s %s", yontem, yol)
            return self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"hata": "Beklenmeyen hata; günlüğe bakın."})

    def _statik(self, yol: str) -> None:
        ad = "index.html" if yol in ("", "/") else yol.lstrip("/")
        veri = _arayuz_dosyasi(ad)
        if veri is None:
            return self._json(HTTPStatus.NOT_FOUND, {"hata": "Bulunamadı"})
        if ad == "index.html":
            veri = veri.replace(b"{{BELIRTEC}}", self.uygulama.belirtec.encode()).replace(
                b"{{SURUM}}", __version__.encode())
        tur = mimetypes.guess_type(ad)[0] or "application/octet-stream"
        if tur.startswith("text/") or tur in ("application/javascript",):
            tur += "; charset=utf-8"
        self._gonder(200, veri, tur)

    def _maskeli_dosyasi(self, klasor: str, belge_id: str) -> None:
        depo = self.uygulama.islem.depo
        kayit = depo.belge_oku(klasor, belge_id)
        yol = depo.dosya_yolu(klasor) / "maskeli" / kayit.get("maskeli_kopya", "")
        if not kayit.get("maskeli_kopya") or not yol.is_file():
            return self._json(HTTPStatus.NOT_FOUND, {"hata": "Maskeli kopya yok ya da süresi doldu"})
        tur = "application/pdf" if yol.suffix == ".pdf" else "application/octet-stream"
        self._gonder(200, yol.read_bytes(), tur, {"Content-Disposition": f'inline; filename="{yol.name}"'})

    def _cevap_ac(self, klasor: str, ad: str, klasorde: bool) -> dict:
        """Çözülmüş taslağı varsayılan uygulamada (Word) açar ya da Explorer'da seçili gösterir."""
        klasor_yolu = (self.uygulama.islem.depo.dosya_yolu(klasor) / "cevaplar").resolve()
        yol = (klasor_yolu / ad).resolve()
        if yol.parent != klasor_yolu or not yol.is_file() or yol.suffix == ".json":
            raise IslemHatasi("Cevap dosyası bulunamadı.")
        if sys.platform == "win32":
            if klasorde:
                subprocess.Popen(["explorer", "/select,", str(yol)])
            else:
                os.startfile(str(yol))  # noqa: S606 - yalnız cevaplar klasöründeki doğrulanmış dosya
        return {"acildi": yol.name}

    def _cevap_dosyasi(self, klasor: str, ad: str) -> None:
        klasor_yolu = self.uygulama.islem.depo.dosya_yolu(klasor) / "cevaplar"
        yol = (klasor_yolu / ad).resolve()
        if yol.parent != klasor_yolu.resolve() or not yol.is_file() or yol.suffix == ".json":
            return self._json(HTTPStatus.NOT_FOUND, {"hata": "Bulunamadı"})
        guvenli_ad = yol.name.encode("ascii", "ignore").decode() or "cevap"
        self._gonder(200, yol.read_bytes(), "application/octet-stream", {
            "Content-Disposition": f"attachment; filename=\"{guvenli_ad}\"; filename*=UTF-8''{__import__('urllib.parse').parse.quote(yol.name)}",
        })


class YerelSunucu:
    def __init__(self, islem: Islem, port: int = VARSAYILAN_PORT, belirtec: Optional[str] = None,
                 eklenti_kokenleri: tuple = (), kurtarma_kodu: Optional[str] = None, kopru: bool = False):
        self.islem = islem
        self.kurtarma_kodu = kurtarma_kodu
        self.kopru = kopru
        self.port = port
        self.belirtec = belirtec or belirtec_al()
        self.eklenti_kokenleri = set(eklenti_kokenleri)
        self._httpd: Optional[ThreadingHTTPServer] = None

    def _kurtarma_isareti(self):
        return uygulama_klasoru() / "kurtarma-saklandi"

    def kurtarma_durumu(self, goster: bool) -> dict:
        return {
            "var": bool(self.kurtarma_kodu),
            "saklandi": self._kurtarma_isareti().exists(),
            "kod": self.kurtarma_kodu if goster else None,
        }

    def kurtarma_onayla(self) -> None:
        self._kurtarma_isareti().write_text("1", encoding="utf-8")

    def durum(self) -> dict:
        from .goruntu import ocr_kullanilabilir_mi

        return {
            "kopru": self.kopru,
            "ocr": ocr_kullanilabilir_mi(),
            "kurtarma_saklandi": (not self.kurtarma_kodu) or self._kurtarma_isareti().exists(),
            "surum": __version__,
            "motor_hazir": self.islem.motor_hazir,
            "semantik": bool(self.islem._motor and self.islem._motor.semantik),
            "aktif_dosya": self.islem.depo.aktif_dosya,
            "kok": str(self.islem.depo.kok),
        }

    def baslat(self) -> bool:
        """Portu alabilirse arka planda sunar; port doluysa (başka köprü sunuyor) False döner."""
        try:
            self._httpd = ThreadingHTTPServer(("127.0.0.1", self.port), _Isleyici)
        except OSError:
            gunluk.info("Port %s dolu; arayüzü başka bir Arthur Mask süreci sunuyor.", self.port)
            return False
        self._httpd.daemon_threads = True
        self._httpd.uygulama = self  # type: ignore[attr-defined]
        self.port = self._httpd.server_address[1]
        threading.Thread(target=self._httpd.serve_forever, name="yerel-sunucu", daemon=True).start()
        gunluk.info("Arayüz: http://127.0.0.1:%s", self.port)
        return True

    def durdur(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()

    @property
    def adres(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

"""Parolasız kasa: ana anahtar Windows DPAPI ile kullanıcı oturumuna bağlanır.

Ana anahtar 32 rastgele bayttır. Diskte yalnız DPAPI ile korunmuş hâli durur;
aynı Windows kullanıcısı dışında (başka hesap, başka makine, diskin sökülmesi)
çözülemez. Kurtarma anahtarı ana anahtarın kendisidir: kurulumda bir kez
gösterilir, ortakta basılı ya da şifreli saklanır.

Windows dışı ortamlarda (geliştirme, test) `ARTHUR_MASK_ANA_ANAHTAR` ortam
değişkeni (base64) kullanılır.
"""

import base64
import ctypes
import os
import secrets
import sys
from ctypes import wintypes
from pathlib import Path

ORTAM_DEGISKENI = "ARTHUR_MASK_ANA_ANAHTAR"
DPAPI_ACIKLAMA = "Arthur Mask ana anahtari"


class AnahtarHatasi(Exception):
    pass


class _VeriBlogu(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blog(veri: bytes) -> _VeriBlogu:
    tampon = ctypes.create_string_buffer(veri, len(veri))
    return _VeriBlogu(len(veri), ctypes.cast(tampon, ctypes.POINTER(ctypes.c_byte)))


def _dpapi(veri: bytes, koru: bool) -> bytes:
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    giris, cikis = _blog(veri), _VeriBlogu()
    CRYPTPROTECT_UI_FORBIDDEN = 0x01
    if koru:
        tamam = crypt32.CryptProtectData(ctypes.byref(giris), DPAPI_ACIKLAMA, None, None, None,
                                         CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(cikis))
    else:
        tamam = crypt32.CryptUnprotectData(ctypes.byref(giris), None, None, None, None,
                                           CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(cikis))
    if not tamam:
        raise AnahtarHatasi("Windows kimlik deposu anahtarı çözemedi (farklı kullanıcı ya da makine).")
    try:
        return ctypes.string_at(cikis.pbData, cikis.cbData)
    finally:
        kernel32.LocalFree(cikis.pbData)


def uygulama_klasoru() -> Path:
    taban = os.environ.get("APPDATA") or str(Path.home() / ".config")
    yol = Path(taban) / "ArthurMask"
    yol.mkdir(parents=True, exist_ok=True)
    return yol


def ana_anahtar(klasor: Path = None) -> bytes:
    """Ana anahtarı döndürür; yoksa üretip korumalı olarak yazar."""
    ortam = os.environ.get(ORTAM_DEGISKENI)
    if ortam:
        return base64.b64decode(ortam)
    if sys.platform != "win32":
        raise AnahtarHatasi(f"Windows dışında {ORTAM_DEGISKENI} ortam değişkeni gerekir.")
    yol = (klasor or uygulama_klasoru()) / "ana-anahtar.dpapi"
    if yol.exists():
        return _dpapi(yol.read_bytes(), koru=False)
    anahtar = secrets.token_bytes(32)
    gecici = yol.with_suffix(".tmp")
    gecici.write_bytes(_dpapi(anahtar, koru=True))
    os.replace(gecici, yol)
    return anahtar


def kasa_parolasi(anahtar: bytes) -> str:
    return base64.urlsafe_b64encode(anahtar).decode("ascii")


def kurtarma_kodu(anahtar: bytes) -> str:
    """İnsan okunur kurtarma kodu: 4'lü gruplar hâlinde base32."""
    kod = base64.b32encode(anahtar).decode("ascii").rstrip("=")
    return "-".join(kod[i:i + 4] for i in range(0, len(kod), 4))


def kurtarma_kodundan(kod: str) -> bytes:
    temiz = kod.replace("-", "").replace(" ", "").upper()
    return base64.b32decode(temiz + "=" * (-len(temiz) % 8))

"""Güncelleme bildirimi: ArthurLegal sürüm sayfasında daha yeni bir Arthur Mask kurulum dosyası var mı?

Yalnız GitHub'ın herkese açık sürüm listesi okunur; istekte belge, kasa ya da kullanıcı bilgisi
yoktur. Sonuç günde bir kez yenilenir. `ARTHUR_MASK_GUNCELLEME=kapali` denetimi tamamen kapatır.
"""

import json
import logging
import os
import re
import threading
import time
import urllib.request
from typing import Dict, Optional

from . import __version__
from .anahtar import uygulama_klasoru

gunluk = logging.getLogger("arthur_mask.guncelleme")

SURUM_ADRESI = "https://api.github.com/repos/beerbottle90/ArthurLegal/releases?per_page=15"
KURULUM_DESENI = re.compile(r"^ArthurMask-Kurulum-(\d+)\.(\d+)\.(\d+)\.exe$")
YENILEME_SANIYE = 24 * 3600

_sonuc: Optional[Dict] = None


def _surum(metin: str):
    return tuple(int(p) for p in re.findall(r"\d+", metin)[:3])


def en_yeni(surumler_json) -> Optional[Dict]:
    """Sürüm listesinden en yeni Arthur Mask kurulum dosyası: {surum, adres, sayfa}."""
    en_iyi = None
    for surum in surumler_json:
        if surum.get("draft") or surum.get("prerelease"):
            continue
        for ek in surum.get("assets", []):
            m = KURULUM_DESENI.match(ek.get("name", ""))
            if m:
                aday = {"surum": ".".join(m.groups()), "adres": ek.get("browser_download_url"),
                        "sayfa": surum.get("html_url")}
                if en_iyi is None or _surum(aday["surum"]) > _surum(en_iyi["surum"]):
                    en_iyi = aday
    return en_iyi


def _denetle() -> None:
    global _sonuc
    onbellek = uygulama_klasoru() / "guncelleme.json"
    try:
        if onbellek.exists() and time.time() - onbellek.stat().st_mtime < YENILEME_SANIYE:
            veri = json.loads(onbellek.read_text(encoding="utf-8"))
        else:
            istek = urllib.request.Request(SURUM_ADRESI, headers={
                "Accept": "application/vnd.github+json", "User-Agent": f"ArthurMask/{__version__}"})
            with urllib.request.urlopen(istek, timeout=10) as yanit:  # noqa: S310 - sabit https adresi
                veri = en_yeni(json.loads(yanit.read())) or {}
            onbellek.write_text(json.dumps(veri), encoding="utf-8")
        if veri.get("surum") and _surum(veri["surum"]) > _surum(__version__):
            _sonuc = veri
    except Exception as hata:  # noqa: BLE001 - çevrimdışı çalışmak normaldir
        gunluk.info("Güncelleme denetlenemedi: %s", hata)


def arkaplanda_denetle() -> None:
    if os.environ.get("ARTHUR_MASK_GUNCELLEME") == "kapali":
        return
    threading.Thread(target=_denetle, name="guncelleme", daemon=True).start()


def bekleyen() -> Optional[Dict]:
    return _sonuc

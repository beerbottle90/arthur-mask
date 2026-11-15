"""Ortak üst şerit (ArthurLegal 3.3.1 sözleşmesi): güncelleme denetimi, sistem bilgisi, yenilikler, arayüz tercihleri.

Arayüz GitHub'a kendisi bağlanmaz (CSP `connect-src 'self'`): yerel sunucu, kurulu ArthurLegal'in `al.py`'sini alt
süreç olarak çağırır. ArthurLegal kurulu değilse (geliştirme ya da ArthurMask'in tek başına kurulumu) ArthurMask'in
kendi bildirimcisine (`guncelleme.py`) düşülür ve yalnız arthur-mask sürüm sayfası gösterilir.

Hiçbir şey indirilmez ya da kurulmaz: "Şimdi güncelle" ArthurLegal'in imzalı güncelleyicisini (`al.py guncelle`)
pencere açmadan başlatır. Bağlantılar yalnız `https://github.com/beerbottle90/` önekiyle geçer.
"""

import json
import logging
import os
import platform
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from . import __version__, guncelleme
from .anahtar import uygulama_klasoru
from .dil import dil_gecerli

gunluk = logging.getLogger("arthur_mask.serit")

MODUL = "mask"
BAGLANTI_ONEKI = "https://github.com/beerbottle90/"
MASK_SURUM_SAYFASI = "https://github.com/beerbottle90/ArthurLegal/releases/tag/arthur-mask"
REHBER = "https://github.com/beerbottle90/ArthurLegal/tree/main/docs/rehber"
YAZILAR = ("normal", "buyuk", "cok-buyuk")
PENCERESIZ = 0x08000000  # CREATE_NO_WINDOW
AYRIK = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
KILIT_OMRU = 7200  # al.py guncelle eski kilidi bu süreden sonra yok sayar
SURUM_DESENI = re.compile(r"^\d+(\.\d+){0,3}$")

_kilit = threading.Lock()
_surec: Optional[subprocess.Popen] = None


# -- kurulum kökü ---------------------------------------------------------------------------------------
def kurulum_sayfasi() -> str:
    return "https://github.com/beerbottle90/ArthurLegal#" + ("mac" if sys.platform == "darwin" else "indir")


def kok() -> Path:
    ortam = os.environ.get("ARTHURLEGAL_KOK")
    if ortam:
        return Path(ortam)
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Programs" / "ArthurLegal"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ArthurLegal"
    return Path.home() / ".local" / "share" / "ArthurLegal"


def al_betigi() -> Path:
    return kok() / "bin" / "al.py"


def al_python() -> Optional[Path]:
    """ArthurLegal'in kendi Python'u (pythonw değil: CREATE_NO_WINDOW ile python.exe)."""
    yol = kok() / "runtime" / ("python.exe" if sys.platform == "win32" else "bin/python3")
    return yol if yol.is_file() else None


def al_kurulu() -> bool:
    return al_betigi().is_file() and al_python() is not None


def baglanti_gecerli(adres) -> bool:
    return isinstance(adres, str) and adres.startswith(BAGLANTI_ONEKI) and not any(c in adres for c in " \"'<>\r\n")


def surum_demeti(surum) -> tuple:
    if not isinstance(surum, str) or not SURUM_DESENI.match(surum.strip()):
        return ()
    return tuple(int(p) for p in surum.strip().split("."))


# -- al.py alt süreci -------------------------------------------------------------------------------------
def _ortam() -> Dict[str, str]:
    ortam = dict(os.environ)
    ortam.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    ortam.pop("PYTHONPATH", None)  # ArthurMask'in paket yolu ArthurLegal'in Python'una karışmaz
    return ortam


def al_json(*argumanlar: str, zaman_asimi: float = 90) -> Dict:
    """`al.py <argümanlar>` → stdout'taki tek JSON. Çalışmazsa {"durum": "hata", "hata": ...}."""
    python = al_python()
    if python is None or not al_betigi().is_file():
        return {"durum": "hata", "hata": "ArthurLegal kurulumu bulunamadı"}
    try:
        sonuc = subprocess.run(
            [str(python), str(al_betigi()), *argumanlar], capture_output=True, timeout=zaman_asimi, cwd=str(kok()),
            env=_ortam(), stdin=subprocess.DEVNULL, creationflags=PENCERESIZ if sys.platform == "win32" else 0)
    except subprocess.TimeoutExpired:
        return {"durum": "hata", "hata": "zaman aşımı"}
    except OSError as hata:
        gunluk.info("al.py çalıştırılamadı (%s).", type(hata).__name__)
        return {"durum": "hata", "hata": "ArthurLegal çalıştırılamadı"}
    metin = sonuc.stdout.decode("utf-8", errors="replace").strip()
    for aday in (metin, *reversed(metin.splitlines())):
        try:
            veri = json.loads(aday)
        except ValueError:
            continue
        if isinstance(veri, dict):
            return veri
    gunluk.info("al.py JSON vermedi (çıkış %s).", sonuc.returncode)
    return {"durum": "hata", "hata": "ArthurLegal yanıtı okunamadı", "json_yok": True}


# -- güncelleme denetimi ----------------------------------------------------------------------------------
def _kilit_var() -> bool:
    yol = kok() / "veri" / "guncelle.kilit"
    try:
        return yol.is_file() and time.time() - yol.stat().st_mtime < KILIT_OMRU
    except OSError:
        return False


def _surec_calisiyor() -> bool:
    with _kilit:
        return _surec is not None and _surec.poll() is None


def _yenilikler_suz(veri) -> Dict[str, List[str]]:
    if not isinstance(veri, dict):
        return {}
    sonuc = {}
    for dil in ("tr", "az", "en"):
        maddeler = veri.get(dil)
        if isinstance(maddeler, list):
            sonuc[dil] = [str(m)[:400] for m in maddeler if isinstance(m, (str, int, float))][:5]
    return sonuc


def al_sonucunu_ozetle(ham: Dict) -> Dict:
    """`al.py guncelle --denetle --json` çıktısı → ArthurMask düğmesinin görünümü. Yalnız "mask" modülüne bakılır."""
    durum = ham.get("durum") if ham.get("durum") in ("guncel", "yeni", "hata") else "hata"
    son = ham.get("son") if isinstance(ham.get("son"), dict) else {}
    yeni_liste = ham.get("yeni") if isinstance(ham.get("yeni"), list) else []
    baglanti = ham.get("baglanti") if isinstance(ham.get("baglanti"), dict) else {}
    guncel = ham.get("guncelleme") if isinstance(ham.get("guncelleme"), dict) else {}
    son_mask = son.get(MODUL) if surum_demeti(son.get(MODUL)) else None
    mask_yeni = MODUL in yeni_liste and bool(son_mask)
    sayfa = baglanti.get(MODUL) if baglanti_gecerli(baglanti.get(MODUL)) else MASK_SURUM_SAYFASI
    kurulum = baglanti.get("al") if baglanti_gecerli(baglanti.get("al")) else kurulum_sayfasi()
    calisiyor = bool(guncel.get("calisiyor")) or _surec_calisiyor()
    ozet = {
        "kaynak": "al",
        "durum": "hata" if durum == "hata" and not son_mask else ("yeni" if mask_yeni else "guncel"),
        "denetim": ham.get("denetim") if isinstance(ham.get("denetim"), (int, float)) else None,
        "onbellek": bool(ham.get("onbellek")),
        "kurulu": __version__,
        "son": son_mask,
        "yenilikler": _yenilikler_suz(ham.get("yenilikler")) if mask_yeni else {},
        "sayfa": sayfa,
        "kurulum": kurulum,
        "guncellenebilir": True,
        "guncelleme": {
            "calisiyor": calisiyor,
            "son_sonuc": str(guncel.get("son_sonuc") or "")[:300],
            "yeniden_baslat": bool(guncel.get("yeniden_baslat")),
        },
    }
    if durum == "hata":
        ozet["hata"] = str(ham.get("hata") or "")[:200]
        if son_mask:  # önbellekteki son başarılı sonuç korunur
            ozet["uyari"] = ozet["hata"]
    return ozet


def yedek_sonuc(zorla: bool) -> Dict:
    """ArthurLegal yokken: ArthurMask'in kendi bildirimcisi (arthur-mask sürüm sayfası)."""
    ham = guncelleme.denetle(zorla)
    son = ham.get("son") or {}
    sayfa = son.get("sayfa") if baglanti_gecerli(son.get("sayfa")) else MASK_SURUM_SAYFASI
    return {
        "kaynak": "mask",
        "durum": ham.get("durum", "hata"),
        "denetim": ham.get("denetim"),
        "onbellek": not zorla,
        "kurulu": __version__,
        "son": son.get("surum") if surum_demeti(son.get("surum")) else None,
        "yenilikler": {},
        "sayfa": sayfa,
        "kurulum": sayfa,
        "guncellenebilir": False,
        "guncelleme": {"calisiyor": False, "son_sonuc": "", "yeniden_baslat": False},
        **({"hata": "denetim kapalı"} if ham.get("kapali") else {}),
    }


def denetle(zorla: bool = False) -> Dict:
    if not al_kurulu():
        return yedek_sonuc(zorla)
    ham = al_json("guncelle", "--denetle", "--json", *(["--zorla"] if zorla else []))
    if ham.get("json_yok"):  # denetim komutu olmayan eski ArthurLegal: ArthurMask'in kendi bildirimcisi
        return yedek_sonuc(zorla)
    return al_sonucunu_ozetle(ham)


def guncellemeyi_baslat() -> Dict:
    """`al.py guncelle` (bayraksız) arka planda, pencere açmadan; kilit varsa ya da zaten çalışıyorsa başlatılmaz."""
    global _surec
    if not al_kurulu():
        return {"basladi": False, "neden": "al_yok"}
    with _kilit:
        if (_surec is not None and _surec.poll() is None) or _kilit_var():
            return {"basladi": False, "neden": "calisiyor"}
        argumanlar = [str(al_python()), str(al_betigi()), "guncelle"]
        ortak = dict(cwd=str(kok()), env=_ortam(), close_fds=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            if sys.platform == "win32":
                _surec = subprocess.Popen(argumanlar, creationflags=AYRIK | PENCERESIZ, **ortak)
            else:  # yeni oturum: ArthurMask kapansa da güncelleyici sürer
                _surec = subprocess.Popen(argumanlar, start_new_session=True, **ortak)
        except OSError as hata:
            gunluk.info("Güncelleyici başlatılamadı (%s).", type(hata).__name__)
            return {"basladi": False, "neden": "hata"}
    return {"basladi": True}


# -- sistem bilgisi ve yenilikler -------------------------------------------------------------------------
def _isletim_sistemi() -> str:
    if sys.platform == "darwin":
        return f"macOS {platform.mac_ver()[0]}".strip()
    if sys.platform == "win32":
        return f"Windows {platform.release()} {platform.version()}".strip()
    return platform.platform()


def tani() -> Dict:
    """Destek için sistem bilgisi. Belge adı, dosya adı ya da müvekkil bilgisi içermez."""
    al = al_json("guncelle", "--tani", "--json", zaman_asimi=30) if al_kurulu() else None
    if al is not None and (al.get("durum") == "hata" and "surumler" not in al):
        al = None
    if al is not None:
        al = {k: al.get(k) for k in ("urun", "surumler", "isletim_sistemi", "mimari", "python", "dil", "moduller",
                                      "son_denetim", "son_sonuc", "son_hatalar") if k in al}
    return {
        "arayuz": "ArthurMask",
        "surum": __version__,
        "al": al,
        "al_kurulu": al_kurulu(),
        "isletim_sistemi": _isletim_sistemi(),
        "mimari": platform.machine(),
        "python": platform.python_version(),
    }


def _yenilik_dosyasi(yol: Path) -> Dict[str, List[str]]:
    try:
        veri = json.loads(yol.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if isinstance(veri, dict) and not any(d in veri for d in ("tr", "az", "en")):
        surumler = [k for k in veri if surum_demeti(k)]
        veri = veri[max(surumler, key=surum_demeti)] if surumler else {}
    return _yenilikler_suz(veri)


def yenilikler() -> Dict:
    """ArthurMask'in kendi yenilikleri (pakette) ve kurulu ArthurLegal paketininki (`surumler/<aktif>/yenilikler.json`)."""
    from importlib import resources

    mask = {}
    try:
        veri = json.loads((resources.files("arthur_mask") / "arayuz" / "yenilikler.json").read_text(encoding="utf-8"))
        mask = _yenilikler_suz(veri.get(__version__, {}))
    except (OSError, ValueError, AttributeError):
        pass
    al = {}
    al_surum = ""
    if al_kurulu():
        try:
            al_surum = (kok() / "aktif.txt").read_text(encoding="utf-8").strip()
        except OSError:
            al_surum = ""
        if surum_demeti(al_surum):
            al = _yenilik_dosyasi(kok() / "surumler" / al_surum / "yenilikler.json")
    return {"mask": {"surum": __version__, "maddeler": mask},
            "al": {"surum": al_surum, "maddeler": al} if al else None}


# -- ortak tercih dosyası -----------------------------------------------------------------------------------
def tercih_yolu() -> Path:
    veri = kok() / "veri"
    if veri.is_dir():
        return veri / "arayuz-tercihleri.json"
    return uygulama_klasoru() / "arayuz-tercihleri.json"


def _json_oku(yol: Path) -> Dict:
    try:
        veri = json.loads(yol.read_text(encoding="utf-8"))
        return veri if isinstance(veri, dict) else {}
    except (OSError, ValueError):
        return {}


def tercihler() -> Dict:
    ham = _json_oku(tercih_yolu())
    dil = dil_gecerli(ham.get("dil"))
    if not dil:
        durum = _json_oku(kok() / "veri" / "durum.json")
        dil = dil_gecerli(durum.get("masa_dili")) or dil_gecerli(durum.get("dil")) or "tr"
    gorulen = ham.get("gorulen_yenilikler") if isinstance(ham.get("gorulen_yenilikler"), dict) else {}
    return {
        "dil": dil,
        "yazi": ham.get("yazi") if ham.get("yazi") in YAZILAR else "normal",
        "karsitlik": ham.get("karsitlik") is True,
        "gorulen_yenilik": gorulen.get(MODUL) if isinstance(gorulen.get(MODUL), str) else None,
    }


def tercih_yaz(degisiklik: Dict) -> Dict:
    """Yalnız verilen anahtarları değiştirir; öteki arayüzlerin anahtarları korunur. Atomik yazılır."""
    yeni = {}
    if "dil" in degisiklik:
        if not dil_gecerli(degisiklik["dil"]) or len(str(degisiklik["dil"])) > 5:
            raise ValueError("dil")
        yeni["dil"] = dil_gecerli(degisiklik["dil"])
    if "yazi" in degisiklik:
        if degisiklik["yazi"] not in YAZILAR:
            raise ValueError("yazi")
        yeni["yazi"] = degisiklik["yazi"]
    if "karsitlik" in degisiklik:
        if not isinstance(degisiklik["karsitlik"], bool):
            raise ValueError("karsitlik")
        yeni["karsitlik"] = degisiklik["karsitlik"]
    gorulen = degisiklik.get("gorulen_yenilik")
    if gorulen is not None and not surum_demeti(gorulen):
        raise ValueError("gorulen_yenilik")
    yol = tercih_yolu()
    with _kilit:
        veri = _json_oku(yol)
        veri.update(yeni)
        if gorulen is not None:
            eski = veri.get("gorulen_yenilikler") if isinstance(veri.get("gorulen_yenilikler"), dict) else {}
            veri["gorulen_yenilikler"] = {**eski, MODUL: gorulen}
        yol.parent.mkdir(parents=True, exist_ok=True)
        gecici = yol.with_name(yol.name + ".tmp")
        gecici.write_text(json.dumps(veri, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(gecici, yol)
    return tercihler()


def bilgi() -> Dict:
    """Sayfa açılışı: şeridin sabit bilgileri ve tercihler (ağa çıkmaz)."""
    return {
        "surum": __version__,
        "al_kurulu": al_kurulu(),
        "platform": sys.platform,
        "tercihler": tercihler(),
        "baglantilar": {"kurulum": kurulum_sayfasi(), "mask": MASK_SURUM_SAYFASI, "rehber": REHBER},
    }

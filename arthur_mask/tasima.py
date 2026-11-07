"""Eski addan yeni ada geçiş (1.1.3): ürün adı bitişik yazılır, "ArthurMask".

1.1.2 ve öncesi adı ayrı yazıyordu: belgeler `~/Arthur Mask` (Windows: `Belgeler\\Arthur Mask`) klasöründe,
macOS uygulaması `Arthur Mask.app` adıyla duruyordu. Bu modül macOS'ta uygulama açılırken iki şeyi yapar:

1. Belge klasörünü yeni ada taşır. Yalnız başka bir ArthurMask süreci çalışmıyorsa (Claude Desktop'un köprüsü
   dahil) yapılır; çalışan bir süreç eski yolu tutuyor olabilir. Taşınamazsa eski klasör kullanılmaya devam eder
   (`depo.varsayilan_kok`) ve bir sonraki açılışta yeniden denenir.
2. Yeni uygulama Claude Desktop'a kaydolduktan sonra eski adlı uygulamayı ve masaüstündeki bozuk takma adını
   kaldırır. Yalnız paket kimliği bu ürününki olan ve o an çalışmayan eski paket silinir.

Windows'ta belge klasörünü kurulum paketi taşır (süreçleri kapattıktan sonra, `ArthurMask.iss`).
"""

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List

from . import depo

PAKET_KIMLIGI = "com.arthurlegal.arthurmask"
ESKI_UYGULAMA = "Arthur Mask.app"


def _baska_surec_var(desen: str) -> bool:
    """`desen` komut satırında geçen, bu süreç dışında bir süreç var mı (macOS/Linux)."""
    try:
        sonuc = subprocess.run(["/usr/bin/pgrep", "-f", desen], capture_output=True, text=True)
    except OSError:
        return True  # emin olamıyorsak dokunma
    kimlikler = {int(s) for s in sonuc.stdout.split() if s.isdigit()}
    return bool(kimlikler - {os.getpid(), os.getppid()})


def belge_klasorunu_tasi() -> bool:
    """Eski belge klasörü varsa ve yenisi yoksa yeni ada taşır. Taşındıysa True."""
    if os.environ.get("ARTHUR_MASK_KOK"):
        return False
    ust = depo.klasor_ustu()
    eski, yeni = ust / depo.ESKI_KLASOR_ADI, ust / depo.KLASOR_ADI
    if yeni.exists() or not eski.is_dir() or _baska_surec_var("arthur_mask"):
        return False
    try:
        eski.rename(yeni)
    except OSError:
        return False
    return True


def _bu_urunun_paketi(uygulama: Path) -> bool:
    try:
        with open(uygulama / "Contents" / "Info.plist", "rb") as f:
            return plistlib.load(f).get("CFBundleIdentifier") == PAKET_KIMLIGI
    except (OSError, plistlib.InvalidFileException, ValueError):
        return False


def eski_uygulamayi_kaldir(kurulum: Path) -> List[Path]:
    """macOS: yeni ada geçildiyse eski adlı uygulama paketini ve ona bakan masaüstü takma adını kaldırır."""
    if sys.platform != "darwin" or kurulum.name == ESKI_UYGULAMA:
        return []
    kaldirilan = []
    for klasor in (Path("/Applications"), Path.home() / "Applications"):
        eski = klasor / ESKI_UYGULAMA
        if eski.is_symlink() or not eski.is_dir() or eski.resolve() == kurulum.resolve():
            continue
        if not _bu_urunun_paketi(eski) or _baska_surec_var(f"{eski}/"):
            continue
        try:
            shutil.rmtree(eski)
        except OSError:
            continue
        kaldirilan.append(eski)
    masaustu = Path.home() / "Desktop"
    takma = masaustu / ESKI_UYGULAMA
    if takma.is_symlink() and not takma.exists():  # hedefi kalmamış takma ad: yeni adla yeniden kurulur
        try:
            takma.unlink()
            kaldirilan.append(takma)
            yeni = masaustu / kurulum.name
            if not yeni.exists() and not yeni.is_symlink():
                yeni.symlink_to(kurulum)
        except OSError:
            pass
    return kaldirilan

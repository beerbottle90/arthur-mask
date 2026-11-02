"""Arthur Mask'ın logosunu ArthurLegal simgesinden üretir: arayuz/logo.png (1024 px) ve arayuz/logo.svg.

Çizim `simge.py`'dir: ArthurLegal deposundaki ArthurLegal-setup/varlik/simge.py'nin kopyası (AL kurulum simgesi,
Claude eklentisi ve Tapu logosu da onunla çizilir; renkler AL Masası'nın armasıyla aynı). Asıl kaynak orada değişirse
kopya da güncellenir. Windows .ico ve macOS .icns derlemede logo.png'den çıkar (derle.py, derle_macos.py); kurulum ve
kısayol simgeleri de bu armadır.

    python paketleme/logo_uret.py
"""

import sys
from pathlib import Path

PAKETLEME = Path(__file__).resolve().parent
ARAYUZ = PAKETLEME.parent / "arthur_mask" / "arayuz"
sys.path.insert(0, str(PAKETLEME))

import simge  # noqa: E402

if __name__ == "__main__":
    (ARAYUZ / "logo.png").write_bytes(simge.simge_png(1024))
    svg = simge.arma_svg().replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1)
    (ARAYUZ / "logo.svg").write_text(svg + "\n", encoding="utf-8")
    print("arayuz/logo.png ve arayuz/logo.svg yazıldı")

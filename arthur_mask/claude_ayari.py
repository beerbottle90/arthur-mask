"""Claude Desktop yapılandırmasına Arthur Mask yerel bağlayıcısını ekler ya da çıkarır.

Kurulum paketi `python -m arthur_mask.claude_ayari kaydet` / `sil` ile çağırır. Mevcut yapılandırma
değiştirilmeden önce yanına zaman damgalı yedeği alınır; yalnız `mcpServers.arthur-mask` girdisine
dokunulur, diğer ayarlar olduğu gibi kalır.
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from .paket import python_yolu

SUNUCU_ADI = "arthur-mask"
# Derlenmiş pakette `python -m` çalışmaz (runpy kod nesnesi ister); giriş noktası -c ile çağrılır.
KOPRU_KOMUTU = "import sys; from arthur_mask.kopru import main; sys.exit(main())"


def yapilandirma_yollari() -> List[Path]:
    """Klasik kurulum (%APPDATA%\\Claude) ve Microsoft Store/MSIX kurulumunun yapılandırma dosyaları."""
    if sys.platform == "darwin":
        return [Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"]
    yollar = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        yollar.append(Path(appdata) / "Claude" / "claude_desktop_config.json")
    yerel = os.environ.get("LOCALAPPDATA")
    if yerel:
        for paket in sorted((Path(yerel) / "Packages").glob("Claude_*")):
            yollar.append(paket / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json")
    return yollar


def sunucu_girdisi() -> Dict:
    # macOS: -I kullanıcının PYTHONPATH/PYTHONHOME ve kullanıcı site-packages'ını yok sayar (Windows'ta ._pth
    # dosyasının yaptığı iş); -B imzalı uygulama paketinin içine .pyc yazılmasını önler.
    bayraklar = ["-I", "-B"] if sys.platform == "darwin" else []
    return {
        "command": str(python_yolu()),
        "args": [*bayraklar, "-c", KOPRU_KOMUTU],
        "env": {"PYTHONIOENCODING": "utf-8", "HF_HUB_OFFLINE": "1", "PYTHONNOUSERSITE": "1"},
    }


def _oku(yol: Path) -> Dict:
    if not yol.exists() or not yol.read_text(encoding="utf-8-sig").strip():
        return {}
    return json.loads(yol.read_text(encoding="utf-8-sig"))


def _yaz(yol: Path, veri: Dict) -> None:
    if yol.exists():
        damga = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(yol, yol.with_name(f"claude_desktop_config.arthur-mask-yedek-{damga}.json"))
    yol.parent.mkdir(parents=True, exist_ok=True)
    gecici = yol.with_suffix(".tmp")
    gecici.write_text(json.dumps(veri, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(gecici, yol)


def kayitli_mi() -> bool:
    """Bu kurulumun güncel girdisi var olan her Claude Desktop yapılandırmasında kayıtlı mı?"""
    girdi = sunucu_girdisi()
    try:
        return all(_oku(y).get("mcpServers", {}).get(SUNUCU_ADI) == girdi for y in yapilandirma_yollari())
    except (json.JSONDecodeError, OSError):
        return False


def kaydet() -> List[Path]:
    """Var olan her Claude Desktop yapılandırmasına kaydeder; hiçbiri yoksa klasik konuma oluşturur."""
    hedefler = [y for y in yapilandirma_yollari() if y.parent.exists()] or yapilandirma_yollari()[:1]
    yazilan = []
    for yol in hedefler:
        try:
            veri = _oku(yol)
        except json.JSONDecodeError:
            print(f"Uyarı: {yol} okunamadı (geçersiz JSON); dokunulmadı.", file=sys.stderr)
            continue
        girdi = sunucu_girdisi()
        if veri.get("mcpServers", {}).get(SUNUCU_ADI) == girdi:
            yazilan.append(yol)
            continue
        veri.setdefault("mcpServers", {})[SUNUCU_ADI] = girdi
        _yaz(yol, veri)
        yazilan.append(yol)
    return yazilan


def sil() -> List[Path]:
    silinen = []
    for yol in yapilandirma_yollari():
        try:
            veri = _oku(yol)
        except (json.JSONDecodeError, OSError):
            continue
        if SUNUCU_ADI in veri.get("mcpServers", {}):
            del veri["mcpServers"][SUNUCU_ADI]
            _yaz(yol, veri)
            silinen.append(yol)
    return silinen


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="arthur_mask.claude_ayari")
    ap.add_argument("islem", choices=["kaydet", "sil", "goster"])
    args = ap.parse_args(argv)
    if args.islem == "kaydet":
        yollar = kaydet()
    elif args.islem == "sil":
        yollar = sil()
    else:
        print(json.dumps(sunucu_girdisi(), ensure_ascii=False, indent=2))
        return 0
    for yol in yollar:
        print(yol)
    return 0 if yollar or args.islem == "sil" else 1


if __name__ == "__main__":
    sys.exit(main())

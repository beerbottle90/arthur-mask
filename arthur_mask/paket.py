"""Kurulu paket düzeni: `<kurulum>\\runtime\\python.exe`, `<kurulum>\\app`, `<kurulum>\\models`.

Kurulum paketinde modeller ve Python çalışma zamanı uygulamanın yanında durur. Bu modül,
kurulu düzende çalışıldığını algılar ve model önbelleğini paketin içine yönlendirir; yapay
zekâ modeli hiçbir koşulda internetten indirilmeye çalışılmaz.
"""

import os
import sys
from pathlib import Path
from typing import Optional


def kurulum_klasoru() -> Optional[Path]:
    """Kurulu paket içinden çalışılıyorsa kurulum klasörü, geliştirme ortamında None."""
    calisma_zamani = Path(sys.executable).resolve().parent
    kok = calisma_zamani.parent
    if calisma_zamani.name.lower() == "runtime" and (kok / "models").is_dir():
        return kok
    return None


def ortami_hazirla() -> None:
    kok = kurulum_klasoru()
    if kok is None:
        return
    os.environ.setdefault("HF_HOME", str(kok / "models" / "hf"))
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def python_yolu(pencereli: bool = False) -> Path:
    """Kurulu paketin Python'u (pencereli=True: konsol penceresi açmayan pythonw)."""
    ad = "pythonw.exe" if pencereli else "python.exe"
    aday = Path(sys.executable).with_name(ad)
    return aday if aday.exists() else Path(sys.executable)

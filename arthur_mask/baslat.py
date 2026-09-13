"""Masaüstü kısayolu: Arthur Mask'i tek tıkla açar.

1. Arayüz zaten çalışıyorsa (Claude Desktop köprüyü başlatmışsa) tarayıcıda açar.
2. Değilse Claude Desktop'u başlatır ve köprünün arayüzü açmasını bekler.
3. Claude Desktop yoksa ya da köprü gelmezse arayüzü bu süreçte yalnız başına sunar; belgeler
   aynı klasöre yazıldığı için Claude Desktop sonradan açıldığında hepsini görür.
"""

import os
import subprocess
import sys
import time
import urllib.request
import webbrowser

from .sunucu import VARSAYILAN_PORT

ADRES = f"http://127.0.0.1:{VARSAYILAN_PORT}/"
CLAUDE_KIMLIGI = "com.anthropic.claudefordesktop"


def arayuz_calisiyor(zaman_asimi: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(ADRES, timeout=zaman_asimi) as yanit:  # noqa: S310 - yerel adres
            return yanit.status == 200 and b"ARTHUR MASK" in yanit.read()
    except OSError:
        return False


def claude_desktop_ac() -> bool:
    """claude:// adresi hem klasik hem Microsoft Store kurulumunda Claude Desktop'u açar."""
    if sys.platform == "darwin":
        return any(subprocess.run(["/usr/bin/open", *arg], capture_output=True).returncode == 0
                   for arg in (["-b", CLAUDE_KIMLIGI], ["-a", "Claude"]))
    try:
        os.startfile("claude://")  # noqa: S606 - kayıtlı uygulama protokolü
        return True
    except OSError:
        return False


def _macos_pencere(ileti: str, dugme: str = "") -> bool:
    """macOS iletişim penceresi; `dugme` verilirse o düğmeye basıldıysa True."""
    dugmeler = '{"Sonra", (item 2 of argv)}' if dugme else '{"Tamam"}'
    betik = ["on run argv", f'display dialog (item 1 of argv) buttons {dugmeler} default button {2 if dugme else 1} '
             'with title "Arthur Mask" with icon note', "end run"]
    komut = ["/usr/bin/osascript", *(p for s in betik for p in ("-e", s)), ileti, dugme]
    sonuc = subprocess.run(komut, capture_output=True, text=True)
    return bool(dugme) and sonuc.stdout.strip().endswith(dugme)


def _claude_calisiyor() -> bool:
    return subprocess.run(["/usr/bin/pgrep", "-x", "Claude"], capture_output=True).returncode == 0


def macos_hazirla() -> bool:
    """macOS uygulama paketinden açılış: yer denetimi ve Claude Desktop kaydı (Windows'ta kurulum paketi yapar).

    False dönerse açılış durdurulur.
    """
    from . import claude_ayari
    from .paket import kurulum_klasoru

    kok = kurulum_klasoru()
    if kok is None:
        return True
    if str(kok).startswith("/Volumes/Arthur Mask") or "/AppTranslocation/" in str(kok):
        _macos_pencere("Arthur Mask'i önce disk görüntüsündeki Uygulamalar (Applications) klasörüne sürükleyin, "
                       "sonra Uygulamalar klasöründen açın.")
        return False
    if claude_ayari.kayitli_mi():
        return True
    claude_ayari.kaydet()
    if _claude_calisiyor() and _macos_pencere(
            "Arthur Mask, Claude Desktop'a bağlandı. Bağlantının görünmesi için Claude Desktop yeniden başlatılmalı.",
            "Claude'u yeniden başlat"):
        subprocess.run(["/usr/bin/osascript", "-e", f'tell application id "{CLAUDE_KIMLIGI}" to quit'],
                       capture_output=True)
        son = time.monotonic() + 20
        while _claude_calisiyor() and time.monotonic() < son:
            time.sleep(0.5)
    return True


def main() -> int:
    if sys.stderr is None:  # pythonw: konsol yok
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
        sys.stdout = sys.stderr
    if sys.platform == "darwin" and not macos_hazirla():
        return 1
    if arayuz_calisiyor():
        webbrowser.open(ADRES)
        return 0
    if claude_desktop_ac():
        son = time.monotonic() + 45
        while time.monotonic() < son:
            time.sleep(1.5)
            if arayuz_calisiyor():
                webbrowser.open(ADRES)
                return 0
    # Claude Desktop yok ya da köprüyü başlatmadı: arayüz bu süreçte sunulur.
    from . import kopru

    import threading

    def _ac():
        for _ in range(40):
            if arayuz_calisiyor():
                webbrowser.open(ADRES)
                return
            time.sleep(0.5)

    threading.Thread(target=_ac, daemon=True).start()
    return kopru.main(["--yalniz-arayuz"])


if __name__ == "__main__":
    sys.exit(main())

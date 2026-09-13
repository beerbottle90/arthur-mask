"""Arthur Mask Windows kurulum paketini hazırlar.

Düzen (`<cikti>\\ArthurMask`):
    runtime\\            Python 3.11 çalışma zamanı + üçüncü taraf kütüphaneler (açık kaynak)
    app\\arthur_mask.*.pyd  Nuitka ile makine koduna derlenmiş Arthur Mask (kaynak kod yok)
    app\\arthur_mask\\veri, arayuz   veri dosyaları ve yerel arayüz
    models\\hf\\hub\\      GLiNER PII modeli ve mDeBERTa belirteçleyicisi (çevrimdışı)
    belgeler\\           LICENSE, ATTRIBUTION.md, BENIOKU.md, üçüncü taraf lisansları
    ArthurMask.ico

Kullanım:
    .venv\\Scripts\\python.exe paketleme\\derle.py --cikti E:\\arthur-mask-derleme [--nuitka-atla] [--iss]
"""

import argparse
import fnmatch
import os
import shutil
import subprocess
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parents[1]
TABAN_PYTHON = Path(sys.base_prefix)
SITE = KOK / ".venv" / "Lib" / "site-packages"
HF_HUB = Path(os.environ.get("HF_HOME", r"E:\llm\hf-cache")) / "hub"
MODELLER = ["models--urchade--gliner_multi_pii-v1", "models--microsoft--mdeberta-v3-base"]

# Pakete girmeyen geliştirme/test/derleme araçları.
SITE_DISARIDA = [
    "_pytest", "pytest", "pytest-*", "py.py", "iniconfig", "iniconfig-*", "pluggy", "pluggy-*",
    "docx", "python_docx-*", "reportlab", "reportlab-*",
    "nuitka", "Nuitka-*", "nuitka-*", "ordered_set", "ordered_set-*", "zstandard", "zstandard-*",
    "__editable__*", "arthur_mask-*", "_virtualenv.p*", "distutils-precedence.pth",
    "PyWin32.chm", "__pycache__", "isympy.py",
]
STDLIB_DISARIDA = ["test", "idlelib", "tkinter", "turtledemo", "ensurepip", "lib2to3", "site-packages",
                   "__pycache__", "turtle.py"]
AGAC_DISARIDA = ["__pycache__", "*.pyc", "tests", "*.lib", "*.pdb"]


def _uyusur(ad: str, desenler) -> bool:
    return any(fnmatch.fnmatch(ad, d) for d in desenler)


def _kopyala_agac(kaynak: Path, hedef: Path, disarida=AGAC_DISARIDA) -> None:
    shutil.copytree(kaynak, hedef, symlinks=False, dirs_exist_ok=True,
                    ignore=lambda _d, adlar: [a for a in adlar if _uyusur(a, disarida)])


def calisma_zamani(hedef: Path) -> None:
    rt = hedef / "runtime"
    rt.mkdir(parents=True)
    for ad in ("python.exe", "pythonw.exe", "python3.dll", "python311.dll", "vcruntime140.dll",
               "vcruntime140_1.dll", "LICENSE.txt"):
        shutil.copy2(TABAN_PYTHON / ad, rt / ad)
    _kopyala_agac(TABAN_PYTHON / "DLLs", rt / "DLLs")
    (rt / "Lib").mkdir()
    for oge in (TABAN_PYTHON / "Lib").iterdir():
        if _uyusur(oge.name, STDLIB_DISARIDA):
            continue
        if oge.is_dir():
            _kopyala_agac(oge, rt / "Lib" / oge.name)
        else:
            shutil.copy2(oge, rt / "Lib" / oge.name)

    site = rt / "Lib" / "site-packages"
    site.mkdir()
    for oge in SITE.iterdir():
        if _uyusur(oge.name, SITE_DISARIDA):
            continue
        if oge.is_dir():
            disarida = AGAC_DISARIDA + (["include"] if oge.name == "torch" else [])
            _kopyala_agac(oge, site / oge.name, disarida)
        else:
            shutil.copy2(oge, site / oge.name)
    # pywin32 DLL'leri .pth ile yüklenir; .pth dosyaları site-packages'ta kalır.

    # ._pth: kayıt defteri ve ortam değişkenlerinden bağımsız, yalnız paket içi yollar.
    (rt / "python311._pth").write_text(
        "Lib\nDLLs\nLib\\site-packages\nLib\\site-packages\\win32\nLib\\site-packages\\win32\\lib\n"
        "Lib\\site-packages\\pythonwin\n..\\app\nimport site\n",
        encoding="utf-8",
    )


def nuitka_derle(derleme: Path) -> Path:
    cikti = derleme / "nuitka"
    komut = [sys.executable, "-m", "nuitka", "--mode=module", "arthur_mask", "--include-package=arthur_mask",
             f"--output-dir={cikti}", "--msvc=latest", "--assume-yes-for-downloads", "--remove-output",
             "--no-pyi-file", "--jobs=8"]
    subprocess.run(komut, cwd=KOK, check=True)
    return _pyd_bul(cikti)


def _pyd_bul(klasor: Path) -> Path:
    adaylar = sorted(klasor.glob("arthur_mask*.pyd"))
    if not adaylar:
        raise SystemExit(f"Derlenmiş modül bulunamadı: {klasor}")
    return adaylar[-1]


def uygulama(hedef: Path, pyd: Path) -> None:
    app = hedef / "app"
    (app / "arthur_mask").mkdir(parents=True)
    shutil.copy2(pyd, app / pyd.name)
    for veri in ("veri", "arayuz"):
        _kopyala_agac(KOK / "arthur_mask" / veri, app / "arthur_mask" / veri)


def modeller(hedef: Path) -> None:
    for model in MODELLER:
        kaynak = HF_HUB / model
        yer = hedef / "models" / "hf" / "hub" / model
        _kopyala_agac(kaynak / "refs", yer / "refs")
        _kopyala_agac(kaynak / "snapshots", yer / "snapshots")  # sembolik bağlar gerçek dosyaya çözülür


def belgeler(hedef: Path) -> None:
    b = hedef / "belgeler"
    b.mkdir()
    shutil.copy2(KOK / "LICENSE", b / "LICENSE.txt")
    shutil.copy2(KOK / "ATTRIBUTION.md", b / "ATTRIBUTION.md")
    shutil.copy2(KOK / "paketleme" / "BENIOKU.md", b / "BENIOKU.md")
    lisanslar = b / "ucuncu-taraf-lisanslari"
    lisanslar.mkdir()
    for bilgi in (hedef / "runtime" / "Lib" / "site-packages").glob("*.dist-info"):
        for dosya in bilgi.rglob("*"):
            if dosya.is_file() and dosya.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE", "AUTHORS")):
                yer = lisanslar / bilgi.name.split("-")[0] / dosya.name
                yer.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dosya, yer)
    shutil.copy2(TABAN_PYTHON / "LICENSE.txt", lisanslar / "Python-LICENSE.txt")

    from PIL import Image

    Image.open(KOK / "arthur_mask" / "arayuz" / "logo.png").convert("RGBA").save(
        hedef / "ArthurMask.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def dogrula(hedef: Path) -> None:
    kaynaklar = [p for p in (hedef / "app").rglob("*.py")]
    if kaynaklar:
        raise SystemExit(f"Pakette Arthur Mask kaynak kodu var: {kaynaklar[:3]}")
    py = hedef / "runtime" / "python.exe"
    ortam = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "HF_", "VIRTUAL_ENV"))}
    betik = (
        "import arthur_mask, sys, os;"
        "from arthur_mask import motor, semantik, goruntu, kopru, baslat, claude_ayari;"
        "assert hasattr(arthur_mask, '__compiled__') and hasattr(motor, '__compiled__'), 'derlenmemiş modül';"
        "assert 'site-packages' in os.__file__ or 'runtime' in os.__file__;"
        "print('surum', arthur_mask.__version__, 'semantik', semantik.kullanilabilir_mi(), 'ocr', goruntu.ocr_kullanilabilir_mi());"
        "print('HF_HOME', os.environ.get('HF_HOME'));"
        "m = motor.MaskeMotoru();"
        "b, _ = m.analiz('DAVACI: Ayşe KARA, vekili Av. Mehmet Ali YILMAZ, Qafqaz Enerji MMC ile sözleşme imzaladı.');"
        "turler = sorted({x.tur for x in b}); print('semantik_motor', m.semantik, turler);"
        "assert m.semantik and {'KİŞİ', 'ŞİRKET'} <= set(turler), turler"
    )
    subprocess.run([str(py), "-c", betik], check=True, env=ortam, cwd=hedef)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cikti", type=Path, default=Path(r"E:\arthur-mask-derleme"))
    ap.add_argument("--nuitka-atla", action="store_true", help="önceden derlenmiş .pyd'yi kullan")
    ap.add_argument("--iss", action="store_true", help="Inno Setup ile kurulum dosyasını da üret")
    ap.add_argument("--yalniz-paketle", action="store_true", help="hazır ArthurMask klasörünü doğrula ve paketle")
    args = ap.parse_args()

    hedef = args.cikti / "ArthurMask"
    if args.yalniz_paketle:
        dogrula(hedef)
        return _iss(args, hedef) if args.iss else 0
    if hedef.exists():
        shutil.rmtree(hedef)
    hedef.mkdir(parents=True)

    pyd = _pyd_bul(args.cikti / "nuitka") if args.nuitka_atla else nuitka_derle(args.cikti)
    print("1/5 çalışma zamanı", flush=True)
    calisma_zamani(hedef)
    print("2/5 uygulama", flush=True)
    uygulama(hedef, pyd)
    print("3/5 modeller", flush=True)
    modeller(hedef)
    print("4/5 belgeler", flush=True)
    belgeler(hedef)
    print("5/5 doğrulama", flush=True)
    dogrula(hedef)

    boyut = sum(p.stat().st_size for p in hedef.rglob("*") if p.is_file())
    print(f"Paket hazır: {hedef} ({boyut / 2**30:.2f} GB)")

    return _iss(args, hedef) if args.iss else 0


def _iss(args, hedef: Path) -> int:
    from arthur_mask import __version__

    iscc = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Inno Setup 6" / "ISCC.exe"
    subprocess.run([str(iscc), f"/DSurum={__version__}", f"/DKaynak={hedef}", f"/O{args.cikti}",
                    str(KOK / "paketleme" / "ArthurMask.iss")], check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

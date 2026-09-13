"""Arthur Mask macOS (Apple Silicon) disk görüntüsünü hazırlar. Yalnız macOS'ta çalışır.

Windows paketinin (`derle.py`) karşılığıdır; aynı Arthur Mask sürümünü, aynı kütüphane sürümlerini
(`macos/gereksinimler.txt`) ve aynı model revizyonlarını paketler.

Düzen (`<cikti>/dmg/Arthur Mask.app/Contents`):
    Info.plist
    MacOS/Arthur Mask                    C başlatıcı (macos/baslatici.c)
    Resources/runtime/                   Python 3.11 (python-build-standalone) + üçüncü taraf kütüphaneler
    Resources/app/arthur_mask.*.so       Nuitka ile makine koduna derlenmiş Arthur Mask (kaynak kod yok)
    Resources/app/arthur_mask/veri, arayuz
    Resources/models/hf/hub/             GLiNER PII modeli ve mDeBERTa belirteçleyicisi (çevrimdışı)
    Resources/belgeler/                  LICENSE, ATTRIBUTION.md, BENIOKU.md, üçüncü taraf lisansları
    Resources/ArthurMask.icns

Kullanım (uv ile yönetilen Python 3.11.9 sanal ortamından):
    .venv/bin/python paketleme/derle_macos.py --yalniz-hazirla          # modeller ve OCR modelleri
    .venv/bin/python paketleme/derle_macos.py --cikti ~/arthur-mask-derleme --dmg
"""

import argparse
import fnmatch
import os
import plistlib
import re
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

KOK = Path(__file__).resolve().parents[1]
TABAN_PYTHON = Path(sys.base_prefix)
PYVER = f"python{sys.version_info.major}.{sys.version_info.minor}"
SITE = Path(sysconfig.get_paths()["purelib"])
HF_HOME = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
UYGULAMA_ADI = "Arthur Mask"
KIMLIK = "com.arthurlegal.arthurmask"
DMG_ADI = "ArthurMask-Kurulum.dmg"

# Windows paketindeki model önbelleğiyle birebir aynı revizyon ve dosyalar.
MODELLER = {
    "urchade/gliner_multi_pii-v1": ("1fcf13e85f4eef5394e1fcd406cf2ca9ea82351d",
                                    [".gitattributes", "gliner_config.json", "pytorch_model.bin", "README.md"]),
    "microsoft/mdeberta-v3-base": ("a0484667b22365f84929a935b5e50a51f71f159d",
                                   ["config.json", "spm.model", "tokenizer_config.json"]),
}
OCR_MODELLERI = ["PP-OCRv6_det_small.onnx", "PP-OCRv6_rec_small.onnx", "ch_ppocr_mobile_v2.0_cls_mobile.onnx"]

# derle.py ile aynı dışarıda bırakma listeleri (+ uv düzenlenebilir kurulum izleri).
SITE_DISARIDA = [
    "_pytest", "pytest", "pytest-*", "py.py", "iniconfig", "iniconfig-*", "pluggy", "pluggy-*",
    "docx", "python_docx-*", "reportlab", "reportlab-*",
    "nuitka", "Nuitka-*", "nuitka-*", "ordered_set", "ordered_set-*", "zstandard", "zstandard-*",
    "__editable__*", "arthur_mask-*", "_arthur_mask*", "arthur_mask.pth", "_virtualenv.p*",
    "distutils-precedence.pth", "__pycache__", "isympy.py",
]
STDLIB_DISARIDA = ["test", "idlelib", "tkinter", "turtledemo", "ensurepip", "lib2to3", "site-packages",
                   "__pycache__", "turtle.py"]
AGAC_DISARIDA = ["__pycache__", "*.pyc", "tests", "*.a"]
RUNTIME_DISARIDA = {
    ".": ["include", "share"],
    "lib": ["pkgconfig", "tcl*", "tk*", "itcl*", "thread*", "Tix*"],
    f"lib/{PYVER}": STDLIB_DISARIDA,
    f"lib/{PYVER}/lib-dynload": ["_tkinter*"],
}


def _uyusur(ad: str, desenler) -> bool:
    return any(fnmatch.fnmatch(ad, d) for d in desenler)


def _kopyala_agac(kaynak: Path, hedef: Path, disarida=AGAC_DISARIDA) -> None:
    shutil.copytree(kaynak, hedef, symlinks=False, dirs_exist_ok=True,
                    ignore=lambda _d, adlar: [a for a in adlar if _uyusur(a, disarida)])


def _calistir(komut, **kw) -> subprocess.CompletedProcess:
    print("  $", " ".join(str(k) for k in komut), flush=True)
    return subprocess.run([str(k) for k in komut], check=kw.pop("check", True), **kw)


# -- hazırlık -----------------------------------------------------------------------------------
def modelleri_indir() -> None:
    from huggingface_hub import hf_hub_download

    for depo, (revizyon, dosyalar) in MODELLER.items():
        for dosya in dosyalar:
            hf_hub_download(depo, dosya, revision=revizyon)
        refs = HF_HOME / "hub" / f"models--{depo.replace('/', '--')}" / "refs" / "main"
        refs.parent.mkdir(parents=True, exist_ok=True)
        refs.write_text(revizyon, encoding="utf-8")


def ocr_modellerini_indir() -> None:
    """RapidOCR modelleri ilk kullanımda paket klasörüne (site-packages/rapidocr/models) indirilir."""
    klasor = SITE / "rapidocr" / "models"
    if all((klasor / m).is_file() for m in OCR_MODELLERI):
        return
    from arthur_mask.goruntu import OcrMotoru

    OcrMotoru()
    eksik = [m for m in OCR_MODELLERI if not (klasor / m).is_file()]
    if eksik:
        raise SystemExit(f"OCR modelleri indirilemedi: {eksik}")


def asgari_macos() -> str:
    """Paketlenen tekerleklerin (wheel) istediği en yüksek macOS sürümü; python-build-standalone 11.0 ister."""
    en = (11, 0)
    for wheel in SITE.glob("*.dist-info/WHEEL"):
        for m in re.finditer(r"macosx_(\d+)_(\d+)_", wheel.read_text(encoding="utf-8")):
            surum = (int(m.group(1)), int(m.group(2)))
            if surum > en:
                print(f"  {wheel.parent.name}: macOS {surum[0]}.{surum[1]}")
                en = surum
    return f"{en[0]}.{en[1]}"


# -- paket ----------------------------------------------------------------------------------------
def nuitka_derle(derleme: Path, macos: str) -> Path:
    cikti = derleme / "nuitka"
    komut = [sys.executable, "-m", "nuitka", "--mode=module", "arthur_mask", "--include-package=arthur_mask",
             f"--output-dir={cikti}", "--assume-yes-for-downloads", "--remove-output", "--no-pyi-file",
             f"--jobs={os.cpu_count() or 4}"]
    _calistir(komut, cwd=KOK, env={**os.environ, "MACOSX_DEPLOYMENT_TARGET": macos})
    return _so_bul(cikti)


def _so_bul(klasor: Path) -> Path:
    adaylar = sorted(klasor.glob("arthur_mask*.so"))
    if not adaylar:
        raise SystemExit(f"Derlenmiş modül bulunamadı: {klasor}")
    return adaylar[-1]


def calisma_zamani(kaynaklar: Path) -> None:
    rt = kaynaklar / "runtime"

    def disarida(dizin, adlar):
        goreli = Path(dizin).relative_to(TABAN_PYTHON).as_posix()
        desenler = RUNTIME_DISARIDA.get(goreli, []) + AGAC_DISARIDA
        return [a for a in adlar if _uyusur(a, desenler)]

    # Göreli sembolik bağlar (bin/python3 -> python3.11) korunur.
    shutil.copytree(TABAN_PYTHON, rt, symlinks=True, ignore=disarida)

    site = rt / "lib" / PYVER / "site-packages"
    site.mkdir()
    for oge in SITE.iterdir():
        if _uyusur(oge.name, SITE_DISARIDA):
            continue
        if oge.is_dir():
            _kopyala_agac(oge, site / oge.name, AGAC_DISARIDA + (["include"] if oge.name == "torch" else []))
        else:
            shutil.copy2(oge, site / oge.name)
    # Windows'taki python311._pth içindeki `..\app` satırının karşılığı: site-packages'a göre Resources/app.
    (site / "arthur-mask-app.pth").write_text("../../../../app\n", encoding="utf-8")


def uygulama(kaynaklar: Path, so: Path) -> None:
    app = kaynaklar / "app"
    (app / "arthur_mask").mkdir(parents=True)
    shutil.copy2(so, app / so.name)
    for veri in ("veri", "arayuz"):
        _kopyala_agac(KOK / "arthur_mask" / veri, app / "arthur_mask" / veri)


def modeller(kaynaklar: Path) -> None:
    for depo, (revizyon, _dosyalar) in MODELLER.items():
        ad = f"models--{depo.replace('/', '--')}"
        kaynak = HF_HOME / "hub" / ad
        yer = kaynaklar / "models" / "hf" / "hub" / ad
        _kopyala_agac(kaynak / "snapshots" / revizyon, yer / "snapshots" / revizyon)  # bağlar dosyaya çözülür
        (yer / "refs").mkdir(parents=True)
        (yer / "refs" / "main").write_text(revizyon, encoding="utf-8")


def belgeler(kaynaklar: Path) -> None:
    b = kaynaklar / "belgeler"
    b.mkdir()
    shutil.copy2(KOK / "LICENSE", b / "LICENSE.txt")
    shutil.copy2(KOK / "ATTRIBUTION.md", b / "ATTRIBUTION.md")
    shutil.copy2(KOK / "paketleme" / "macos" / "BENIOKU.md", b / "BENIOKU.md")
    lisanslar = b / "ucuncu-taraf-lisanslari"
    lisanslar.mkdir()
    for bilgi in (kaynaklar / "runtime" / "lib" / PYVER / "site-packages").glob("*.dist-info"):
        for dosya in bilgi.rglob("*"):
            if dosya.is_file() and dosya.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE", "AUTHORS")):
                yer = lisanslar / bilgi.name.split("-")[0] / dosya.name
                yer.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dosya, yer)
    shutil.copy2(TABAN_PYTHON / "lib" / PYVER / "LICENSE.txt", lisanslar / "Python-LICENSE.txt")


def uygulama_kabugu(contents: Path, macos: str) -> None:
    from PIL import Image

    from arthur_mask import __version__

    (contents / "MacOS").mkdir(parents=True, exist_ok=True)
    _calistir(["clang", "-O2", "-arch", "arm64", f"-mmacosx-version-min={macos}", "-Wall", "-Werror",
               "-o", contents / "MacOS" / UYGULAMA_ADI, KOK / "paketleme" / "macos" / "baslatici.c"])
    Image.open(KOK / "arthur_mask" / "arayuz" / "logo.png").convert("RGBA").save(
        contents / "Resources" / "ArthurMask.icns", format="ICNS")
    bilgi = {
        "CFBundleName": UYGULAMA_ADI,
        "CFBundleDisplayName": UYGULAMA_ADI,
        "CFBundleIdentifier": KIMLIK,
        "CFBundleExecutable": UYGULAMA_ADI,
        "CFBundleIconFile": "ArthurMask",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": __version__,
        "CFBundleVersion": __version__,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleDevelopmentRegion": "tr",
        "LSMinimumSystemVersion": macos,
        "LSArchitecturePriority": ["arm64"],
        "LSRequiresNativeExecution": True,
        # Windows'taki pythonw gibi pencere ve Dock simgesi yok; arayüz tarayıcıda açılır.
        "LSUIElement": True,
        "LSApplicationCategoryType": "public.app-category.productivity",
        "NSHumanReadableCopyright": "ArthurLegal",
    }
    with (contents / "Info.plist").open("wb") as f:
        plistlib.dump(bilgi, f)


def bayt_kodu(kaynaklar: Path) -> None:
    """İmzalı paketin içine çalışırken .pyc yazılmaz (-B); açılış hızı için önceden derlenir."""
    py = kaynaklar / "runtime" / "bin" / "python3"
    _calistir([py, "-I", "-m", "compileall", "-q", "-j", "0", "--invalidation-mode", "unchecked-hash",
               kaynaklar / "runtime" / "lib" / PYVER], check=False, stdout=subprocess.DEVNULL)


def dogrula(kaynaklar: Path) -> None:
    kaynak_kod = list((kaynaklar / "app").rglob("*.py"))
    if kaynak_kod:
        raise SystemExit(f"Pakette Arthur Mask kaynak kodu var: {kaynak_kod[:3]}")
    dogrula_python(kaynaklar / "runtime" / "bin" / "python3", kaynaklar)


def dogrula_python(py: Path, cwd: Path) -> None:
    ortam = {k: v for k, v in os.environ.items()
             if not k.startswith(("PYTHON", "HF_", "VIRTUAL_ENV", "ARTHUR_MASK_"))}
    ortam["ARTHUR_MASK_GUNCELLEME"] = "kapali"
    betik = (
        "import arthur_mask, sys, os;"
        "from arthur_mask import motor, semantik, goruntu, kopru, baslat, claude_ayari, anahtar, depo;"
        "assert hasattr(arthur_mask, '__compiled__') and hasattr(motor, '__compiled__'), 'derlenmemiş modül';"
        "assert '/runtime/' in os.__file__, os.__file__;"
        "print('surum', arthur_mask.__version__, 'semantik', semantik.kullanilabilir_mi(), 'ocr', goruntu.ocr_kullanilabilir_mi());"
        "assert semantik.kullanilabilir_mi() and goruntu.ocr_kullanilabilir_mi();"
        "print('HF_HOME', os.environ.get('HF_HOME'));"
        "assert os.environ.get('HF_HOME', '').endswith('/models/hf'), 'kurulum düzeni algılanmadı';"
        "g = claude_ayari.sunucu_girdisi(); print('claude', g);"
        "assert g['args'][:2] == ['-I', '-B'] and g['command'].endswith('/runtime/bin/python3');"
        "assert depo.varsayilan_kok().name == 'Arthur Mask' and 'Documents' not in str(depo.varsayilan_kok());"
        "m = motor.MaskeMotoru();"
        "b, _ = m.analiz('DAVACI: Ayşe KARA, vekili Av. Mehmet Ali YILMAZ, Qafqaz Enerji MMC ile sözleşme imzaladı.');"
        "turler = sorted({x.tur for x in b}); print('semantik_motor', m.semantik, turler);"
        "assert m.semantik and {'KİŞİ', 'ŞİRKET'} <= set(turler), turler"
    )
    _calistir([py, "-I", "-B", "-c", betik], env=ortam, cwd=cwd)


# -- imza ve disk görüntüsü -------------------------------------------------------------------------
def _macho_mu(yol: Path) -> bool:
    with yol.open("rb") as f:
        bas = f.read(8)
    if bas[:4] in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe"):
        return True
    # Evrensel ikili (cafebabe); Java sınıf dosyalarıyla karışmasın diye mimari sayısı küçük olmalı.
    return bas[:4] == b"\xca\xfe\xba\xbe" and int.from_bytes(bas[4:8], "big") < 10


def imzala(app: Path) -> None:
    """Ad-hoc imza: arm64'te imzasız Mach-O çalışmaz; imzasız ya da mühürsüz paket macOS'ta "hasarlı" sayılır
    ve "Yine de Aç" seçeneği hiç çıkmaz. Mühürden sonra paketin içine hiçbir şey yazılmamalıdır."""
    _calistir(["xattr", "-cr", app])
    imzalanan = 0
    for dosya in app.rglob("*"):
        if dosya.is_symlink() or not dosya.is_file() or not _macho_mu(dosya):
            continue
        if subprocess.run(["codesign", "-v", str(dosya)], capture_output=True).returncode != 0:
            subprocess.run(["codesign", "-f", "-s", "-", str(dosya)], check=True, capture_output=True)
            imzalanan += 1
    print(f"  imzasız Mach-O ad-hoc imzalandı: {imzalanan}")
    _calistir(["codesign", "-f", "-s", "-", "--identifier", KIMLIK, app])
    _calistir(["codesign", "--verify", "--deep", "--strict", "--verbose=2", app])


def disk_goruntusu(sahne: Path, cikti: Path) -> Path:
    (sahne / "Applications").symlink_to("/Applications")
    dmg = cikti / DMG_ADI
    dmg.unlink(missing_ok=True)
    boyut_mb = sum(p.stat().st_size for p in sahne.rglob("*") if p.is_file() and not p.is_symlink()) // 2**20
    _calistir(["hdiutil", "create", "-volname", UYGULAMA_ADI, "-srcfolder", sahne, "-fs", "HFS+",
               "-format", "ULFO", "-size", f"{int(boyut_mb * 1.2) + 200}m", "-ov", dmg])
    return dmg


def main() -> int:
    if sys.platform != "darwin":
        raise SystemExit("Bu betik yalnız macOS'ta çalışır; Windows paketi için derle.py kullanılır.")
    ap = argparse.ArgumentParser()
    ap.add_argument("--cikti", type=Path, default=Path.home() / "arthur-mask-derleme")
    ap.add_argument("--nuitka-atla", action="store_true", help="önceden derlenmiş .so'yu kullan")
    ap.add_argument("--dmg", action="store_true", help="imzalı disk görüntüsünü de üret")
    ap.add_argument("--yalniz-hazirla", action="store_true", help="yalnız modelleri ve OCR modellerini indir")
    args = ap.parse_args()

    print("0/8 hazırlık (modeller)", flush=True)
    modelleri_indir()
    ocr_modellerini_indir()
    if args.yalniz_hazirla:
        return 0
    macos = asgari_macos()
    print(f"  en düşük macOS: {macos}")

    sahne = args.cikti / "dmg"
    if sahne.exists():
        shutil.rmtree(sahne)
    contents = sahne / f"{UYGULAMA_ADI}.app" / "Contents"
    kaynaklar = contents / "Resources"
    kaynaklar.mkdir(parents=True)

    print("1/8 Nuitka", flush=True)
    so = _so_bul(args.cikti / "nuitka") if args.nuitka_atla else nuitka_derle(args.cikti, macos)
    print("2/8 çalışma zamanı", flush=True)
    calisma_zamani(kaynaklar)
    print("3/8 uygulama", flush=True)
    uygulama(kaynaklar, so)
    print("4/8 modeller", flush=True)
    modeller(kaynaklar)
    print("5/8 belgeler ve uygulama kabuğu", flush=True)
    belgeler(kaynaklar)
    uygulama_kabugu(contents, macos)
    shutil.copy2(KOK / "paketleme" / "macos" / "BENIOKU.md", sahne / "Kurulum Notları.md")
    print("6/8 bayt kodu ve doğrulama", flush=True)
    bayt_kodu(kaynaklar)
    dogrula(kaynaklar)

    boyut = sum(p.stat().st_size for p in kaynaklar.rglob("*") if p.is_file() and not p.is_symlink())
    print(f"Paket hazır: {contents.parent} ({boyut / 2**30:.2f} GB)")
    if not args.dmg:
        return 0
    print("7/8 ad-hoc imza", flush=True)
    imzala(contents.parent)
    print("8/8 disk görüntüsü", flush=True)
    dmg = disk_goruntusu(sahne, args.cikti)
    print(f"Disk görüntüsü: {dmg} ({dmg.stat().st_size / 2**30:.2f} GB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

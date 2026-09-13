"""Dosya (matter) klasörleri: `Belgeler\\Arthur Mask\\<dosya>\\` (macOS: `~/Arthur Mask/<dosya>/`).

    dosya.json              ad, oluşturma
    dosya.kasa              şifreli etiket ↔ değer kasası
    sozluk.yaml             dosya sözlüğü (maskele / maskeleme)
    maskeli\\<id>.json       maskeli metin ve özet (özgün metin YOK)
    maskeli\\<id>.<uzantı>   maskeli belge kopyası (30 gün sonra silinir)
    cevaplar\\               Claude'un teslim ettiği, yerelde çözülmüş taslaklar
    kirmizi-hat.jsonl       yalnız kırmızı hat onayları (gerçek değer yok)
    claude-giden.jsonl      Claude'a gönderilen her araç yanıtı (çıkış kapısından geçmiş, maskeli)

Claude Desktop birden fazla köprü süreci başlatabilir; kasa ve durum yazımları
dosya kilidiyle sıralanır.
"""

import json
import os
import re
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional

import yaml

from .anahtar import kasa_parolasi
from .kasa import Kasa
from .sozluk import Sozluk

SAKLAMA_GUNU = 30
_GECERSIZ = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def varsayilan_kok() -> Path:
    ortam = os.environ.get("ARTHUR_MASK_KOK")
    if ortam:
        return Path(ortam)
    if sys.platform == "darwin":
        # Belgeler klasörü iCloud "Masaüstü ve Belgeler" eşitlemesine girebilir ve klasör izni ister.
        return Path.home() / "Arthur Mask"
    belgeler = Path.home() / "Documents"
    return belgeler / "Arthur Mask"


def simdi() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def klasor_adi(ad: str) -> str:
    temiz = _GECERSIZ.sub(" ", ad).strip().rstrip(".")
    return re.sub(r"\s+", " ", temiz)[:80] or "Adsız dosya"


@contextmanager
def kilit(yol: Path, zaman_asimi: float = 20.0) -> Iterator[None]:
    """Süreçler arası basit kilit: O_EXCL ile oluşturulan kilit dosyası; 60 sn'den eskisi bayat sayılır."""
    kilit_yolu = yol.with_name(yol.name + ".kilit")
    baslangic = time.monotonic()
    while True:
        try:
            fd = os.open(kilit_yolu, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - kilit_yolu.stat().st_mtime > 60:
                    kilit_yolu.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() - baslangic > zaman_asimi:
                raise TimeoutError(f"Kilit alınamadı: {kilit_yolu}")
            time.sleep(0.05)
    try:
        yield
    finally:
        kilit_yolu.unlink(missing_ok=True)


def _json_yaz(yol: Path, veri) -> None:
    gecici = yol.with_name(yol.name + ".tmp")
    gecici.write_text(json.dumps(veri, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(gecici, yol)


class Depo:
    def __init__(self, anahtar: bytes, kok: Optional[Path] = None):
        self.kok = Path(kok) if kok else varsayilan_kok()
        self.kok.mkdir(parents=True, exist_ok=True)
        self._parola = kasa_parolasi(anahtar)

    # -- dosyalar ----------------------------------------------------------------
    def _durum_yolu(self) -> Path:
        return self.kok / ".durum.json"

    def dosyalar(self) -> List[Dict]:
        sonuc = []
        for yol in sorted(self.kok.iterdir()):
            meta = yol / "dosya.json"
            if yol.is_dir() and meta.exists():
                veri = json.loads(meta.read_text(encoding="utf-8"))
                veri["klasor"] = yol.name
                veri["belge_sayisi"] = len(list((yol / "maskeli").glob("*.json")))
                veri["cevap_sayisi"] = len(list((yol / "cevaplar").glob("*.json")))
                sonuc.append(veri)
        return sonuc

    def benzersiz_ad(self, ad: str) -> str:
        """Belge adından türetilen dosya adı var olan bir dosyayla çakışırsa '(2)', '(3)' eklenir."""
        taban = klasor_adi(ad)
        aday, sira = taban, 2
        while (self.kok / aday / "dosya.json").exists():
            aday, sira = f"{taban[:74]} ({sira})", sira + 1
        return aday

    def dosya_olustur(self, ad: str) -> str:
        klasor = klasor_adi(ad)
        yol = self.kok / klasor
        if (yol / "dosya.json").exists():
            return klasor
        for alt in ("maskeli", "cevaplar"):
            (yol / alt).mkdir(parents=True, exist_ok=True)
        _json_yaz(yol / "dosya.json", {"ad": ad, "olusturma": simdi()})
        return klasor

    def dosya_yolu(self, klasor: str) -> Path:
        yol = (self.kok / klasor_adi(klasor)).resolve()
        if self.kok.resolve() not in yol.parents or not (yol / "dosya.json").exists():
            raise FileNotFoundError(f"Dosya bulunamadı: {klasor}")
        return yol

    @property
    def aktif_dosya(self) -> Optional[str]:
        yol = self._durum_yolu()
        if not yol.exists():
            return None
        klasor = json.loads(yol.read_text(encoding="utf-8")).get("aktif")
        return klasor if klasor and (self.kok / klasor / "dosya.json").exists() else None

    @aktif_dosya.setter
    def aktif_dosya(self, klasor: str) -> None:
        self.dosya_yolu(klasor)
        with kilit(self._durum_yolu()):
            _json_yaz(self._durum_yolu(), {"aktif": klasor_adi(klasor), "degisti": simdi()})

    # -- kasa ve sözlük ------------------------------------------------------------
    @contextmanager
    def kasa(self, klasor: str) -> Iterator[Kasa]:
        """Kilitli oku-değiştir-yaz: bloktan çıkınca kasa kaydedilir."""
        yol = self.dosya_yolu(klasor) / "dosya.kasa"
        with kilit(yol):
            kasa = Kasa.ac_veya_olustur(yol, self._parola, dosya=klasor)
            yield kasa
            kasa.kaydet(yol, self._parola)

    def kasa_oku(self, klasor: str) -> Kasa:
        yol = self.dosya_yolu(klasor) / "dosya.kasa"
        return Kasa.ac(yol, self._parola) if yol.exists() else Kasa(dosya=klasor)

    def sozluk(self, klasor: str) -> Sozluk:
        yol = self.dosya_yolu(klasor) / "sozluk.yaml"
        return Sozluk.yukle(yol) if yol.exists() else Sozluk(dosya=klasor)

    def sozluge_ekle(self, klasor: str, maskele: List[Dict] = (), maskeleme: List[str] = ()) -> None:
        yol = self.dosya_yolu(klasor) / "sozluk.yaml"
        with kilit(yol):
            veri = yaml.safe_load(yol.read_text(encoding="utf-8")) if yol.exists() else {}
            veri = veri or {}
            veri.setdefault("dosya", klasor)
            mevcut = {str(g["deger"]) if isinstance(g, dict) else str(g) for g in veri.get("maskele", []) or []}
            veri["maskele"] = list(veri.get("maskele", []) or []) + [g for g in maskele if g["deger"] not in mevcut]
            izin = list(veri.get("maskeleme", []) or [])
            veri["maskeleme"] = izin + [m for m in maskeleme if m not in izin]
            gecici = yol.with_name(yol.name + ".tmp")
            gecici.write_text(yaml.safe_dump(veri, allow_unicode=True, sort_keys=False), encoding="utf-8")
            os.replace(gecici, yol)

    # -- maskeli belgeler ------------------------------------------------------------
    def belge_kaydet(self, klasor: str, kayit: Dict) -> None:
        _json_yaz(self.dosya_yolu(klasor) / "maskeli" / f"{kayit['id']}.json", kayit)

    def belge_oku(self, klasor: str, belge_id: str) -> Dict:
        if not re.fullmatch(r"[a-z0-9-]{1,40}", belge_id):
            raise FileNotFoundError(belge_id)
        yol = self.dosya_yolu(klasor) / "maskeli" / f"{belge_id}.json"
        return json.loads(yol.read_text(encoding="utf-8"))

    def belgeler(self, klasor: str) -> List[Dict]:
        klasor_yolu = self.dosya_yolu(klasor) / "maskeli"
        kayitlar = [json.loads(p.read_text(encoding="utf-8")) for p in klasor_yolu.glob("*.json")]
        return sorted(kayitlar, key=lambda k: k["olusturma"], reverse=True)

    def yeni_belge_id(self, klasor: str) -> str:
        mevcut = {p.stem for p in (self.dosya_yolu(klasor) / "maskeli").glob("*.json")}
        sira = 1
        while f"belge-{sira}" in mevcut:
            sira += 1
        return f"belge-{sira}"

    def maskeli_kopya_yolu(self, klasor: str, belge_id: str, uzanti: str) -> Path:
        return self.dosya_yolu(klasor) / "maskeli" / f"{belge_id}{uzanti}"

    # -- cevaplar ----------------------------------------------------------------------
    def cevap_yolu(self, klasor: str, baslik: str, uzanti: str) -> Path:
        damga = datetime.now().strftime("%Y%m%d-%H%M%S")
        ad = klasor_adi(baslik)[:60] or "cevap"
        return self.dosya_yolu(klasor) / "cevaplar" / f"{damga} {ad}{uzanti}"

    def cevap_kaydet(self, klasor: str, meta: Dict, yol: Path) -> None:
        _json_yaz(yol.with_suffix(".json"), meta)

    def cevaplar(self, klasor: str) -> List[Dict]:
        klasor_yolu = self.dosya_yolu(klasor) / "cevaplar"
        kayitlar = []
        for p in klasor_yolu.glob("*.json"):
            veri = json.loads(p.read_text(encoding="utf-8"))
            veri["ad"] = p.stem
            kayitlar.append(veri)
        return sorted(kayitlar, key=lambda k: k["olusturma"], reverse=True)

    # -- kayıt ve temizlik ---------------------------------------------------------------
    def kirmizi_hat_kaydet(self, klasor: str, kayit: Dict) -> None:
        yol = self.dosya_yolu(klasor) / "kirmizi-hat.jsonl"
        with kilit(yol):
            with yol.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"zaman": simdi(), **kayit}, ensure_ascii=False) + "\n")

    def giden_kaydet(self, klasor: str, kayit: Dict) -> None:
        """Claude'a gönderilen araç yanıtlarının yerel kaydı (çıkış kapısından geçmiş, maskeli hâli)."""
        yol = self.dosya_yolu(klasor) / "claude-giden.jsonl"
        with kilit(yol):
            with yol.open("a", encoding="utf-8") as f:
                f.write(json.dumps(kayit, ensure_ascii=False) + "\n")

    def gidenler(self, klasor: str, en_fazla: int = 200) -> List[Dict]:
        yol = self.dosya_yolu(klasor) / "claude-giden.jsonl"
        if not yol.exists():
            return []
        satirlar = yol.read_text(encoding="utf-8").splitlines()[-en_fazla:]
        return [json.loads(s) for s in reversed(satirlar) if s.strip()]

    def temizle(self, gun: int = SAKLAMA_GUNU) -> int:
        """Süresi dolan maskeli ara kopyaları siler; çözülmüş cevaplar ve kasa kalır."""
        sinir = time.time() - timedelta(days=gun).total_seconds()
        silinen = 0
        for dosya in self.kok.glob("*/maskeli/*"):
            if dosya.is_file() and dosya.stat().st_mtime < sinir:
                dosya.unlink()
                silinen += 1
        return silinen

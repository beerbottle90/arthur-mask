"""CLI, yerel arayüz ve MCP köprüsünün ortak kullandığı maskeleme / geri açma işlemleri."""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from . import kirmizi_hat, rapor
from .belgeler import Belge
from .kasa import Kasa
from .motor import Bulgu, MaskeMotoru, artik_tarama
from .maskeleyici import Degisiklik, degisiklikleri_uygula, geri_acma_degisiklikleri, maskele


@dataclass
class MaskelemeSonucu:
    belge: Belge
    bulgular: List[Bulgu]
    supheli: List[Bulgu]
    degisiklikler: List[Degisiklik]
    maskeli_metin: str
    kirmizi: List[kirmizi_hat.KirmiziHatUyarisi]
    artik: List[Tuple[int, str]]
    rapor: str

    @property
    def etiket_sayisi(self) -> int:
        return len({d[2] for d in self.degisiklikler})


def maskele_belge(belge: Belge, motor: MaskeMotoru, kasa: Kasa) -> MaskelemeSonucu:
    bulgular, supheli = motor.analiz(belge.metin)
    maskeli, degisiklikler = maskele(belge.metin, bulgular, kasa)
    kirmizi = kirmizi_hat.tara(belge.metin)
    artik = artik_tarama(maskeli)
    rapor_metni = rapor.olustur(
        belge.yol.name, motor.profil, belge.metin, bulgular, degisiklikler,
        supheli, kirmizi, artik, belge.uyarilar,
    )
    return MaskelemeSonucu(belge, bulgular, supheli, degisiklikler, maskeli, kirmizi, artik, rapor_metni)


def geri_ac_metin(metin: str, kasa: Kasa) -> Tuple[str, List[Degisiklik], List[str]]:
    degisiklikler, bilinmeyen = geri_acma_degisiklikleri(metin, kasa)
    return degisiklikleri_uygula(metin, degisiklikler), degisiklikler, bilinmeyen


def varsayilan_cikti(girdi: Path, ek: str, uzanti: str) -> Path:
    ad = girdi.stem.replace(".maskeli", "").replace(".acik", "")
    return girdi.with_name(f"{ad}.{ek}{uzanti}")

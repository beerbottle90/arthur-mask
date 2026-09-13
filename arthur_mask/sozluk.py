"""Dosyaya özgü kişisel sözlük: her zaman maskelenecek ve asla maskelenmeyecek ifadeler.

Otomatik tespit olasılıksaldır; müvekkil adı, karşı taraf unvanı, proje kod adı
gibi dosyanın bilinen hassas ifadeleri sözlükle kesinleştirilir. Sözlük kişisel
veri içerir ve kasa ile aynı yerel, erişimi kısıtlı klasörde tutulur.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml

from .turkce import kelime_desenine_cevir


@dataclass
class SozlukGirdisi:
    deger: str
    tur: str
    varyantlar: List[str] = field(default_factory=list)

    def ifadeler(self) -> List[str]:
        return [self.deger, *self.varyantlar]


@dataclass
class Sozluk:
    dosya: str = ""
    maskele: List[SozlukGirdisi] = field(default_factory=list)
    maskeleme: List[str] = field(default_factory=list)

    @classmethod
    def yukle(cls, yol: Optional[Path]) -> "Sozluk":
        if not yol:
            return cls()
        veri = yaml.safe_load(Path(yol).read_text(encoding="utf-8")) or {}
        girdiler = []
        for g in veri.get("maskele", []) or []:
            if isinstance(g, str):
                girdiler.append(SozlukGirdisi(deger=g, tur="GİZLİ"))
            else:
                girdiler.append(
                    SozlukGirdisi(
                        deger=str(g["deger"]),
                        tur=str(g.get("tur", "GİZLİ")).upper().replace(" ", "_"),
                        varyantlar=[str(v) for v in g.get("varyantlar", []) or []],
                    )
                )
        return cls(
            dosya=str(veri.get("dosya", "")),
            maskele=girdiler,
            maskeleme=[str(x) for x in veri.get("maskeleme", []) or []],
        )

    def eslesmeler(self, metin: str):
        """(bas, son, girdi) üçlüleri; uzun ifadeler önce."""
        for girdi in self.maskele:
            for ifade in sorted(girdi.ifadeler(), key=len, reverse=True):
                for m in kelime_desenine_cevir(ifade).finditer(metin):
                    yield m.start(), m.end(), girdi

    def izinli_araliklar(self, metin: str):
        for ifade in self.maskeleme:
            for m in kelime_desenine_cevir(ifade).finditer(metin):
                yield m.start(), m.end()

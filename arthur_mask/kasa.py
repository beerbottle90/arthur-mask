"""Maske etiketi ↔ gerçek değer eşleştirme kasası (yalnız yerel, şifreli).

Kasa dosya (matter) başına tutulur: aynı dosyanın bütün belgelerinde aynı kişi
aynı etiketi alır; böylece yapay zekâ çıktısı belgeler arasında tutarlı kalır ve
geri açılabilir. Kasa hiçbir dış işleyiciye gönderilmez.
"""

import base64
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .turkce import ascii_katla

BASLIK = b"ARTHURMASK-KASA1\n"
PAROLA_DEGISKENI = "ARTHUR_MASK_KASA_PAROLASI"
_ETIKET_PARCALARI = re.compile(r"\{\{\s*([^{}\s]+?)\s*-\s*(\d+)\s*\}\}")


class KasaHatasi(Exception):
    pass


def _anahtar_turet(parola: str, tuz: bytes) -> bytes:
    kdf = Scrypt(salt=tuz, length=32, n=2**15, r=8, p=1)
    return base64.urlsafe_b64encode(kdf.derive(parola.encode("utf-8")))


def etiket_olustur(tur: str, sira: int) -> str:
    return "{{" + f"{tur}-{sira:02d}" + "}}"


def _etiket_anahtari(etiket: str) -> Optional[Tuple[str, int]]:
    m = _ETIKET_PARCALARI.fullmatch(etiket.strip())
    return (ascii_katla(m.group(1)), int(m.group(2))) if m else None


@dataclass
class Kayit:
    etiket: str
    tur: str
    varlik: str
    anahtar: str
    degerler: List[str] = field(default_factory=list)

    @property
    def asil(self) -> str:
        """Geri açmada yazılan değer: görülen en uzun (tam) biçim."""
        return max(self.degerler, key=len)


@dataclass
class Kasa:
    dosya: str = ""
    olusturma: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    sayaclar: Dict[str, int] = field(default_factory=dict)
    kayitlar: Dict[str, Kayit] = field(default_factory=dict)

    def __post_init__(self):
        self._dizin = {(k.tur, k.anahtar): k.etiket for k in self.kayitlar.values()}
        self._katlanmis = {_etiket_anahtari(k.etiket): k for k in self.kayitlar.values()}

    def _es_kayit(self, tur: str, varlik: str, anahtar: str) -> Optional[str]:
        """Belgeler arası eş-gönderim: aynı şirketin kısa/uzun unvanı, aynı kişinin tek soyadı.

        Yalnız tek bir aday varsa eşleştirir; belirsizlikte yeni etiket açılır.
        """
        yeni = anahtar.split()
        adaylar = set()
        for (k_tur, k_anahtar), etiket in self._dizin.items():
            if k_tur != tur:
                continue
            mevcut = k_anahtar.split()
            if varlik in ("TR_TUZEL_KISI", "SOZLUK"):
                kisa, uzun = sorted((yeni, mevcut), key=len)
                if len(kisa) >= 2 and uzun[:len(kisa)] == kisa:
                    adaylar.add(etiket)
            elif varlik == "PERSON" and len(mevcut) >= 2:
                if len(yeni) == 1 and len(yeni[0]) >= 3 and yeni[0] == mevcut[-1]:
                    adaylar.add(etiket)  # "kara" → "ayşe kara"
                elif len(yeni) >= 2 and yeni[0] == mevcut[0] and yeni[-1] == mevcut[-1]:
                    adaylar.add(etiket)  # "mehmet yılmaz" → "mehmet ali yılmaz"
        return adaylar.pop() if len(adaylar) == 1 else None

    def etiket_al(self, tur: str, varlik: str, anahtar: str, deger: str) -> str:
        # Eş-gönderim eşleşmesi önbelleğe alınmaz: sonradan aynı soyadlı ikinci kişi gelirse
        # belirsizlik her seferinde yeniden değerlendirilir (oturumdan bağımsız, belirlenimci).
        etiket = self._dizin.get((tur, anahtar)) or self._es_kayit(tur, varlik, anahtar)
        if etiket is None:
            self.sayaclar[tur] = self.sayaclar.get(tur, 0) + 1
            etiket = etiket_olustur(tur, self.sayaclar[tur])
            kayit = Kayit(etiket, tur, varlik, anahtar)
            self.kayitlar[etiket] = kayit
            self._dizin[(tur, anahtar)] = etiket
            self._katlanmis[_etiket_anahtari(etiket)] = kayit
        kayit = self.kayitlar[etiket]
        if deger not in kayit.degerler:
            kayit.degerler.append(deger)
        return etiket

    def bul(self, etiket: str) -> Optional[Kayit]:
        """Birebir ya da modelin bozduğu biçimde ({{KISI-1}}, {{ KİŞİ-01 }}) etiketi bulur."""
        if etiket in self.kayitlar:
            return self.kayitlar[etiket]
        return self._katlanmis.get(_etiket_anahtari(etiket))

    # -- kalıcılık ----------------------------------------------------------------
    def _json(self) -> bytes:
        veri = {
            "surum": 1,
            "dosya": self.dosya,
            "olusturma": self.olusturma,
            "sayaclar": self.sayaclar,
            "kayitlar": [k.__dict__ for k in self.kayitlar.values()],
        }
        return json.dumps(veri, ensure_ascii=False, indent=1).encode("utf-8")

    def kaydet(self, yol: Path, parola: str) -> None:
        if not parola:
            raise KasaHatasi("Kasa parolası boş olamaz.")
        tuz = os.urandom(16)
        belirtec = Fernet(_anahtar_turet(parola, tuz)).encrypt(self._json())
        gecici = Path(str(yol) + ".tmp")
        gecici.write_bytes(BASLIK + base64.b64encode(tuz) + b"\n" + belirtec)
        os.replace(gecici, yol)

    @classmethod
    def ac(cls, yol: Path, parola: str) -> "Kasa":
        ham = Path(yol).read_bytes()
        if not ham.startswith(BASLIK):
            raise KasaHatasi(f"{yol} bir Arthur Mask kasası değil.")
        tuz_satiri, belirtec = ham[len(BASLIK):].split(b"\n", 1)
        try:
            duz = Fernet(_anahtar_turet(parola, base64.b64decode(tuz_satiri))).decrypt(belirtec)
        except InvalidToken as hata:
            raise KasaHatasi("Kasa parolası yanlış veya dosya bozuk.") from hata
        veri = json.loads(duz)
        kayitlar = {k["etiket"]: Kayit(**k) for k in veri.get("kayitlar", [])}
        return cls(veri.get("dosya", ""), veri.get("olusturma", ""), veri.get("sayaclar", {}), kayitlar)

    @classmethod
    def ac_veya_olustur(cls, yol: Path, parola: str, dosya: str = "") -> "Kasa":
        return cls.ac(yol, parola) if Path(yol).exists() else cls(dosya=dosya)

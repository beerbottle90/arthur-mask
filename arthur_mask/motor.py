"""Tespit hattı: Presidio analizi + sözlük + içtihat atıf koruması + yayılım + çakışma çözümü."""

import re
from dataclasses import dataclass, replace
from typing import Iterable, List, Optional, Tuple

from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
from presidio_analyzer.predefined_recognizers import (
    CreditCardRecognizer,
    EmailRecognizer,
    IbanRecognizer,
    IpRecognizer,
    SpacyRecognizer,
    TrLicensePlateRecognizer,
    TrNationalIdRecognizer,
)

from .nlp import TurkceNlpMotoru
from .sozluk import Sozluk
from .tanimlayicilar import SOYAD_OLMAYAN, TUZEL_KISI_IZI, turk_tanimlayicilari
from .turkce import anahtar, kelime_desenine_cevir, tr_kucuk

STANDART = {
    "PERSON", "TR_TUZEL_KISI", "TR_NATIONAL_ID", "TR_VKN", "IBAN_CODE", "TR_TELEFON",
    "EMAIL_ADDRESS", "TR_ADRES", "TR_DOSYA_NO", "TR_LICENSE_PLATE", "TR_MERSIS",
    "TR_SICIL_NO", "TR_DOGUM_TARIHI", "CREDIT_CARD", "IP_ADDRESS",
}
PROFILLER = {
    "standart": STANDART,
    "siki": STANDART | {"TR_MAHKEME", "LOCATION"},
}

TUR_ADLARI = {
    "PERSON": "KİŞİ",
    "TR_TUZEL_KISI": "ŞİRKET",
    "TR_NATIONAL_ID": "TCKN",
    "TR_VKN": "VKN",
    "IBAN_CODE": "IBAN",
    "TR_TELEFON": "TELEFON",
    "EMAIL_ADDRESS": "EPOSTA",
    "TR_ADRES": "ADRES",
    "TR_DOSYA_NO": "DOSYA_NO",
    "TR_LICENSE_PLATE": "PLAKA",
    "TR_MERSIS": "MERSİS",
    "TR_SICIL_NO": "SİCİL_NO",
    "TR_DOGUM_TARIHI": "DOĞUM_TARİHİ",
    "CREDIT_CARD": "KART",
    "IP_ADDRESS": "IP",
    "TR_MAHKEME": "MAHKEME",
    "LOCATION": "YER",
}

SAYISAL = {"TR_NATIONAL_ID", "TR_VKN", "IBAN_CODE", "TR_TELEFON", "TR_MERSIS", "CREDIT_CARD", "TR_LICENSE_PLATE"}

# Yüksek mahkeme ve kurum kararlarına yapılan atıflar maskelenmez: bunlar kamuya açık
# içtihattır ve maskelenirse hukuki analiz ile atıf doğrulaması imkânsızlaşır.
ICTIHAT_ATIF_IZI = re.compile(
    r"Yargıtay|YARGITAY|Danıştay|DANIŞTAY|Anayasa\s+Mahkemesi|ANAYASA\s+MAHKEMESİ|\bAYM\b"
    r"|\bH\.?D\.?(?!\w)|\bHGK\b|\bCGK\b|\bİBK\b|\bİBGK\b|\bİDDK\b|\bVDDK\b|\bD\.\s*$"
    r"|Hukuk\s+Dairesi|Ceza\s+Dairesi|Hukuk\s+Genel\s+Kurulu|Ceza\s+Genel\s+Kurulu"
    r"|İdari\s+Dava\s+Daireleri|Vergi\s+Dava\s+Daireleri|Bölge\s+(?:Adliye|İdare)\s+Mahkemesi"
    r"|\bBAM\b|\bBİM\b|\bB\.\s*No\b|Bireysel\s+Başvuru|Uyuşmazlık\s+Mahkemesi|AİHM|Sayıştay"
)
ATIF_PENCERESI = 90

ALT_ESIK = 0.3


@dataclass(frozen=True)
class Bulgu:
    bas: int
    son: int
    varlik: str
    tur: str
    skor: float
    metin: str
    kanonik: str
    kaynak: str

    @property
    def uzunluk(self) -> int:
        return self.son - self.bas


def kanonik_deger(varlik: str, metin: str) -> str:
    if varlik in SAYISAL:
        return "".join(ch for ch in metin.upper() if ch.isalnum())
    return anahtar(metin)


def _ortusur(a: Tuple[int, int], b: Tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


class MaskeMotoru:
    def __init__(
        self,
        profil: str = "standart",
        sozluk: Optional[Sozluk] = None,
        esik: float = 0.5,
        ner_modeli: Optional[str] = None,
        ictihat_koruma: bool = True,
    ):
        if profil not in PROFILLER:
            raise ValueError(f"Bilinmeyen profil: {profil} (seçenekler: {', '.join(PROFILLER)})")
        self.profil = profil
        self.varliklar = sorted(PROFILLER[profil])
        self.sozluk = sozluk or Sozluk()
        self.esik = esik
        self.ictihat_koruma = ictihat_koruma

        kayit = RecognizerRegistry(supported_languages=["tr"])
        for tanimlayici in (
            TrNationalIdRecognizer(),
            TrLicensePlateRecognizer(),
            EmailRecognizer(supported_language="tr"),
            IbanRecognizer(supported_language="tr"),
            CreditCardRecognizer(supported_language="tr"),
            IpRecognizer(supported_language="tr"),
            *turk_tanimlayicilari(),
        ):
            kayit.add_recognizer(tanimlayici)
        if ner_modeli:
            kayit.add_recognizer(
                SpacyRecognizer(supported_language="tr", supported_entities=["PERSON", "LOCATION"])
            )
        self.analizci = AnalyzerEngine(
            registry=kayit,
            nlp_engine=TurkceNlpMotoru(ner_modeli),
            supported_languages=["tr"],
        )

    # -- ana giriş ---------------------------------------------------------------
    def analiz(self, metin: str) -> Tuple[List[Bulgu], List[Bulgu]]:
        """(maskelenecek bulgular, eşik altında kalan şüpheli adaylar)."""
        adaylar = self._presidio(metin) + self._sozluk_bulgulari(metin)
        adaylar = self._izin_listesi_uygula(metin, adaylar)
        if self.ictihat_koruma:
            adaylar = [b for b in adaylar if not self._ictihat_atfi_mi(metin, b)]

        kesin = [b for b in adaylar if b.skor >= self.esik]
        kesin = self._cakisma_coz(kesin + self._yayilim(metin, kesin))
        kesin = self._izin_listesi_uygula(metin, kesin)

        supheli = [
            b for b in adaylar
            if ALT_ESIK <= b.skor < self.esik
            and not any(_ortusur((b.bas, b.son), (k.bas, k.son)) for k in kesin)
        ]
        return kesin, self._cakisma_coz(supheli)

    # -- adımlar -------------------------------------------------------------------
    def _presidio(self, metin: str) -> List[Bulgu]:
        sonuclar = self.analizci.analyze(
            text=metin, language="tr", entities=self.varliklar, score_threshold=ALT_ESIK
        )
        bulgular = []
        for s in sonuclar:
            parca = metin[s.start:s.end]
            kaynak = s.recognition_metadata.get("recognizer_name", "") if s.recognition_metadata else ""
            bulgular.append(
                Bulgu(s.start, s.end, s.entity_type, TUR_ADLARI.get(s.entity_type, s.entity_type),
                      round(s.score, 2), parca, kanonik_deger(s.entity_type, parca), kaynak)
            )
        return bulgular

    def _sozluk_bulgulari(self, metin: str) -> List[Bulgu]:
        return [
            Bulgu(bas, son, "SOZLUK", girdi.tur, 1.0, metin[bas:son], anahtar(girdi.deger), "sözlük")
            for bas, son, girdi in self.sozluk.eslesmeler(metin)
        ]

    def _izin_listesi_uygula(self, metin: str, bulgular: List[Bulgu]) -> List[Bulgu]:
        izinli = list(self.sozluk.izinli_araliklar(metin))
        if not izinli:
            return bulgular
        return [
            b for b in bulgular
            if b.kaynak == "sözlük" or not any(a <= b.bas and b.son <= z for a, z in izinli)
        ]

    def _ictihat_atfi_mi(self, metin: str, bulgu: Bulgu) -> bool:
        if bulgu.varlik != "TR_DOSYA_NO":
            return False
        sol = metin[max(0, bulgu.bas - ATIF_PENCERESI):bulgu.bas]
        sol = sol.rsplit("\n", 1)[-1]
        return bool(ICTIHAT_ATIF_IZI.search(sol))

    def _yayilim(self, metin: str, kesin: List[Bulgu]) -> List[Bulgu]:
        """Tespit edilen ad ve unvanları belgenin geri kalanında da yakalar (eş-gönderim)."""
        ek: List[Bulgu] = []
        kisiler = {b.kanonik: b for b in kesin if b.varlik == "PERSON"}
        sirketler = {b.kanonik: b for b in kesin if b.varlik in ("TR_TUZEL_KISI", "SOZLUK")}

        for ornek in list(kisiler.values()) + list(sirketler.values()):
            for m in kelime_desenine_cevir(ornek.metin).finditer(metin):
                ek.append(replace(ornek, bas=m.start(), son=m.end(), metin=m.group(), kaynak="yayılım"))

        # Tek başına geçen büyük harfli soyadı: yalnız o soyadı tek bir kişiye aitse.
        soyad_sahipleri = {}
        for b in kisiler.values():
            if len(b.metin.split()) < 2:
                continue
            soyad = b.metin.split()[-1]
            if soyad.isupper() and len(soyad) >= 3 and tr_kucuk(soyad) not in SOYAD_OLMAYAN:
                soyad_sahipleri.setdefault(tr_kucuk(soyad), set()).add(b.kanonik)
        for soyad, sahipler in soyad_sahipleri.items():
            if len(sahipler) != 1:
                continue
            ornek = kisiler[next(iter(sahipler))]
            for m in re.finditer(rf"(?<!\w){re.escape(ornek.metin.split()[-1])}(?!\w)", metin):
                ek.append(replace(ornek, bas=m.start(), son=m.end(), metin=m.group(),
                                  skor=max(min(ornek.skor, 0.7), self.esik), kaynak="yayılım (soyadı)"))

        # Şirket unvanının tür eki olmadan geçen kısa hâli ("ABC Enerji").
        for b in sirketler.values():
            if b.varlik != "TR_TUZEL_KISI":
                continue
            iz = TUZEL_KISI_IZI.search(b.metin)
            kisa = b.metin[:iz.start()].strip() if iz else ""
            if len(kisa.split()) >= 2:
                for m in kelime_desenine_cevir(kisa).finditer(metin):
                    ek.append(replace(b, bas=m.start(), son=m.end(), metin=m.group(), kaynak="yayılım (kısa unvan)"))
        return ek

    @staticmethod
    def _cakisma_coz(bulgular: Iterable[Bulgu]) -> List[Bulgu]:
        secilen: List[Bulgu] = []
        # Aynı skor ve uzunlukta yayılım kazanır: tek başına soyadı, tam adın etiketine bağlansın.
        oncelik = sorted(
            bulgular,
            key=lambda b: (b.kaynak == "sözlük", b.skor, b.uzunluk, b.kaynak.startswith("yayılım")),
            reverse=True,
        )
        for b in oncelik:
            if not any(_ortusur((b.bas, b.son), (s.bas, s.son)) for s in secilen):
                secilen.append(b)
        return sorted(secilen, key=lambda b: b.bas)


def artik_tarama(metin: str) -> List[Tuple[int, str]]:
    """Maskeleme sonrası kaba güvenlik ağı: etiket dışında kalan numara/e-posta izleri."""
    temiz = re.sub(r"\[[^\[\]\n]{1,40}_\d{1,5}\]", " ", metin)
    izler = [
        (r"(?<!\d)[1-9]\d{10}(?!\d)", "11 haneli sayı (TCKN?)"),
        (r"(?<![\d/.,])\d{10}(?![\d/.,]\d)", "10 haneli sayı (VKN/telefon?)"),
        (r"\bTR\s?\d{2}(?:\s?\d{4}){2,}", "TR IBAN izi"),
        (r"[\w.+-]+@[\w-]+\.[\w.]+", "e-posta izi"),
        (r"(?:\+90|\b0)\s?5\d{2}", "cep telefonu izi"),
    ]
    bulunan = []
    for desen, aciklama in izler:
        for m in re.finditer(desen, temiz):
            satir = temiz.count("\n", 0, m.start()) + 1
            bulunan.append((satir, aciklama))
    return bulunan


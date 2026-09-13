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
    TrLicensePlateRecognizer,
    TrNationalIdRecognizer,
)

from .nlp import TurkceNlpMotoru
from .sozluk import Sozluk
from . import semantik as semantik_modulu
from .tanimlayicilar import (
    ADLAR, BELIRSIZ_ADLAR, KAMU_KURUMU_IZI, KISI_OLMAYAN, SEKTOR_SOZCUKLERI, SOYAD_OLMAYAN, TUZEL_KISI_IZI,
    UNVANLAR, rol_ismi_mi, turk_tanimlayicilari,
)
from .turkce import anahtar, kelime_desenine_cevir, tr_kucuk
from .uluslararasi import uluslararasi_tanimlayicilar

STANDART = {
    "PERSON", "TR_TUZEL_KISI", "TR_NATIONAL_ID", "TR_VKN", "IBAN_CODE", "TR_TELEFON",
    "EMAIL_ADDRESS", "TR_ADRES", "TR_DOSYA_NO", "TR_LICENSE_PLATE", "TR_MERSIS",
    "TR_SICIL_NO", "TR_DOGUM_TARIHI", "CREDIT_CARD", "IP_ADDRESS", "TR_PASAPORT",
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
    "TR_PASAPORT": "PASAPORT",
    "CREDIT_CARD": "KART",
    "IP_ADDRESS": "IP",
    "TR_MAHKEME": "MAHKEME",
    "LOCATION": "YER",
}

SAYISAL = {"TR_PASAPORT", "TR_NATIONAL_ID", "TR_VKN", "IBAN_CODE", "TR_TELEFON", "TR_MERSIS", "CREDIT_CARD", "TR_LICENSE_PLATE"}

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

# Yayımlanmış İngiliz/ABD/AB içtihat atıfları: "Smith v Jones [2019] EWHC 1234 (Comm)",
# "Hadley v. Baxendale (1854) 9 Exch 341", "Doe v. Roe, 410 U.S. 113 (1973)". Taraf adları maskelenmez.
_TARAF = r"[A-Z][\w&.'’-]*(?:\s+(?:[A-Z][\w&.'’-]*|of|and|&|the|plc|Ltd\.?|Inc\.?|LLC)){0,6}"
YABANCI_ATIF_DESENI = re.compile(
    rf"(?<![\w]){_TARAF}\s+v\.?\s+{_TARAF},?\s*"
    r"(?:\[\d{4}\]\s*(?:\d+\s+)?[A-Z][A-Za-z]{1,6}(?:\s+(?:Civ|Crim|Admin|Comm|Ch|QB|KB|Fam|Pat|TCC))?\s+\d+"
    r"|\(\d{4}\)\s*\d+\s+[A-Z][\w.]*(?:\s+[A-Z][\w.]*)?\s+\d+"
    r"|\d+\s+(?:U\.S\.|S\.\s?Ct\.|F\.(?:\s?\d?d|\s?Supp\.(?:\s?\d?d)?)|A\.C\.|W\.L\.R\.|All\s+ER|E\.C\.R\.)\s+\d+"
    r"|C-\d+/\d{2}|ECLI:[A-Z]{2}:[^\s]+)"
)

ALT_ESIK = 0.3
SEMANTIK_ESIK = 0.4


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
        semantik: Optional[bool] = None,
        ictihat_koruma: bool = True,
    ):
        """semantik: None = kuruluysa GLiNER katmanını aç; True = zorunlu; False = yalnız kurallar."""
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
            *uluslararasi_tanimlayicilar(),
        ):
            kayit.add_recognizer(tanimlayici)
        if semantik is None:
            semantik = semantik_modulu.kullanilabilir_mi()
        if semantik:
            if not semantik_modulu.kullanilabilir_mi():
                raise RuntimeError('Semantik katman kurulu değil: pip install "arthur-mask[semantik]"')
            kayit.add_recognizer(semantik_modulu.tanimlayici_olustur(filtre=self._semantik_filtre))
        self.semantik = bool(semantik)
        self.analizci = AnalyzerEngine(
            registry=kayit,
            nlp_engine=TurkceNlpMotoru(),
            supported_languages=["tr"],
        )

    # -- ana giriş ---------------------------------------------------------------
    def analiz(self, metin: str) -> Tuple[List[Bulgu], List[Bulgu]]:
        """(maskelenecek bulgular, eşik altında kalan şüpheli adaylar)."""
        adaylar = self._presidio(metin) + self._sozluk_bulgulari(metin)
        adaylar = self._izin_listesi_uygula(metin, adaylar)
        if self.ictihat_koruma:
            atiflar = [m.span() for m in YABANCI_ATIF_DESENI.finditer(metin)]
            adaylar = [
                b for b in adaylar
                if not self._ictihat_atfi_mi(metin, b)
                and not (b.kaynak != "sözlük" and any(a <= b.bas and b.son <= z for a, z in atiflar))
            ]

        # Sızıntıya öncelik: semantik katmanın bulguları daha düşük eşikle maskelenir.
        kesin = [b for b in adaylar if b.skor >= self.esik or (b.kaynak == "GLiNER" and b.skor >= SEMANTIK_ESIK)]
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
            bas, son = s.start, s.end
            kaynak = s.recognition_metadata.get("recognizer_name", "") if s.recognition_metadata else ""
            # Presidio desenleri harf duyarsız çalışır; plakada harfler büyük olmalı ("11 ve 13" plaka değil).
            if s.entity_type == "TR_LICENSE_PLATE" and not re.search(r"[A-Z]", metin[bas:son]):
                # Küçük harfli OCR plakası ancak yakınında plaka bağlamı varsa kabul edilir.
                if not re.search(r"(?i)plaka|araç|arac[ıi]", metin[max(0, bas - 40):son + 20]):
                    continue
            parca = metin[bas:son]
            bulgular.append(
                Bulgu(bas, son, s.entity_type, TUR_ADLARI.get(s.entity_type, s.entity_type),
                      round(s.score, 2), parca, kanonik_deger(s.entity_type, parca), kaynak)
            )
        return bulgular

    @staticmethod
    def _semantik_filtre(metin: str, varlik: str, bas: int, son: int) -> Optional[Tuple[int, int]]:
        """Model bulgusunu hukuk metnine göre daraltır ya da eler."""
        # Baştaki noktalama/unvan ve sondaki noktalama modele aittir, ada değil ("Av. Kaan Er," → "Kaan Er").
        while bas < son and metin[bas] in " \t.,;:('‘’\"":
            bas += 1
        m = re.match(rf"(?:(?:{UNVANLAR})\s*)+", metin[bas:son])
        if m and varlik == "PERSON":
            bas += m.end()
        while son > bas and metin[son - 1] in " \t.,;:)'’\"":
            son -= 1
        parca = metin[bas:son]
        if not parca.strip():
            return None
        kelimeler = [tr_kucuk(k).strip(".,:;'’") for k in parca.split()]
        genel = [k for k in kelimeler if k in KISI_OLMAYAN or k in SOYAD_OLMAYAN or rol_ismi_mi(k)]

        if varlik == "PERSON":
            if KAMU_KURUMU_IZI.search(parca) or TUZEL_KISI_IZI.search(parca):
                return None
            # Sızıntıya öncelik: yalnız kesin yanlışlar elenir. Rol ismiyle başlayan dizide rol kırpılır
            # ("Tanık Rojhat Demirtaşoğlu" → "Rojhat Demirtaşoğlu"); tamamı genel sözcükse elenir.
            if len(genel) == len(kelimeler):
                return None
            parcalar = list(re.finditer(r"\S+", parca))
            while parcalar and (rol_ismi_mi(tr_kucuk(parcalar[0].group())) or tr_kucuk(parcalar[0].group()).strip(".,:;") in KISI_OLMAYAN):
                parcalar.pop(0)
            if not parcalar:
                return None
            bas, son = bas + parcalar[0].start(), bas + parcalar[-1].end()
        elif varlik == "TR_TUZEL_KISI":
            if KAMU_KURUMU_IZI.search(parca) or ICTIHAT_ATIF_IZI.search(parca):
                return None
            # "Davalı şirketin", "Ltd. Şti": özel ad taşımayan genel ifade (büyük harf şartı yok: OCR).
            ozel = [
                k for k, ham in zip(kelimeler, parca.split())
                if k not in genel and not TUZEL_KISI_IZI.fullmatch(ham.strip(".,"))
                and k.strip(".") not in {"a.ş", "aş", "ltd", "şti", "sti", "ltd.şti", "ve"}
            ]
            if not ozel:
                return None
        elif varlik == "TR_ADRES":
            # Kapı numarası ya da en az iki yer birimi yoksa (yalnız "Özlem Sokak") adres sayılmaz.
            birimler = len(re.findall(r"(?i)mahalle|mah\.|mh\.|sokak|sokağı|sk\.|cadde|cad\.|cd\.|bulvar|blv\.|sitesi|apt|blok", parca))
            if not any(ch.isdigit() for ch in parca) and birimler < 2:
                return None
        elif varlik == "EMAIL_ADDRESS":
            if "@" not in parca:
                return None
        elif varlik == "TR_DOGUM_TARIHI":
            # Tarihler açık bırakılır; model bir tarihi doğum tarihi sanırsa bağlam aranır.
            pencere = tr_kucuk(metin[max(0, bas - 40):min(len(metin), son + 20)])
            if not re.search(r"doğum|doğumlu|d\.\s?t\.|yaşında|birth|born|d\.?o\.?b", pencere):
                return None
        elif varlik in ("TR_NATIONAL_ID", "IBAN_CODE", "TR_TELEFON"):
            # Model tarihleri ve tutarları kimlik/hesap numarası sanabilir: yeterli rakam aranır.
            if sum(ch.isdigit() for ch in parca) < 9 or re.fullmatch(r"[\d\s./-]*(?:19|20)\d{2}[\d\s./-]*", parca) and len(re.sub(r"\D", "", parca)) <= 8:
                return None
        return bas, son

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

        def yayilabilir(b: Bulgu) -> bool:
            # Genel isim yayılırsa belge boyunca yanlış maskeleme çoğalır; yalnız özel ad niteliği taşıyanlar.
            if b.kaynak == "sözlük":
                return True
            kelimeler = b.metin.split()
            if len(b.metin) < 3 or not any(k[:1].isupper() for k in kelimeler):
                return False
            if b.varlik == "PERSON":
                return not any(rol_ismi_mi(tr_kucuk(k).strip(".,'’")) for k in kelimeler)
            # Şirkette tür eki ("Anonim Şirketi") doğaldır; ilk sözcük rol ismiyse ("Davalı şirketin") yayılmaz.
            return not rol_ismi_mi(tr_kucuk(kelimeler[0]))

        kisiler = {b.kanonik: b for b in kesin if b.varlik == "PERSON" and yayilabilir(b)}
        sirketler = {b.kanonik: b for b in kesin if b.varlik in ("TR_TUZEL_KISI", "SOZLUK") and yayilabilir(b)}

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
        # Tek başına geçen ilk ad ("Mehmet Kaya ... Mehmet"): yalnız o ilk ad tek bir kişiye aitse.
        ad_sahipleri = {}
        for b in kisiler.values():
            parcalar = b.metin.split()
            if len(parcalar) >= 2 and parcalar[0][:1].isupper() and len(parcalar[0]) >= 3 \
                    and tr_kucuk(parcalar[0]) not in KISI_OLMAYAN and "." not in parcalar[0]:
                ad_sahipleri.setdefault(parcalar[0], set()).add(b.kanonik)
        for ilk_ad, sahipler in ad_sahipleri.items():
            if len(sahipler) != 1:
                continue
            ornek = kisiler[next(iter(sahipler))]
            for m in re.finditer(rf"(?<![\w.]){re.escape(ilk_ad)}(?![\w])", metin):
                ek.append(replace(ornek, bas=m.start(), son=m.end(), metin=m.group(),
                                  skor=max(min(ornek.skor, 0.7), self.esik), kaynak="yayılım (ilk ad)"))

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
            govde = (b.metin[:iz.start()] if iz else b.metin).split()
            kisalar = []
            if iz and len(govde) >= 2:
                kisalar.append(" ".join(govde))
            # "Poyraz Enerji Üretim ve Ticaret A.Ş." → "Poyraz Enerji": sektör sözcüğüyle biten önekler.
            for i in range(2, len(govde)):
                if tr_kucuk(govde[i - 1]) in SEKTOR_SOZCUKLERI:
                    kisalar.append(" ".join(govde[:i]))
            for kisa in kisalar:
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
    temiz = re.sub(r"\{\{[^{}\n]{1,48}\}\}", " ", metin)
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


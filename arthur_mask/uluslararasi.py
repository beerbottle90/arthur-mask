"""İngilizce ve uluslararası belgeler için tanıyıcılar.

Türk bürolarının İngilizce sözleşme, tahkim ve yazışmalarında geçen adresler,
uluslararası telefonlar, pasaport numaraları, İngilizce doğum tarihi ve dosya
referansları. Kişi ve şirket adları ortak tanıyıcılarla (genişletilmiş sözcük
listeleri ve şirket ekleri) ve semantik katmanla yakalanır.
"""

import re

from .tanimlayicilar import BUYUK, Desen, KuralTanimlayici

_AYLAR_EN = r"(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?"
_SOKAK = (
    r"(?:Street|St\.|Road|Rd\.?|Avenue|Ave\.?|Lane|Ln\.?|Boulevard|Blvd\.?|Drive|Dr\.|Way|Place|Pl\.|Square|Sq\.|"
    r"Court|Ct\.|Terrace|Crescent|Close|Parkway|Highway|Hwy\.?|Row|Walk|Gardens|Mews|Wharf|Quay|Strasse|Straße|str\.)"
)
_UK_POSTA = r"[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}"
_US_POSTA = r"\b[A-Z]{2}\s\d{5}(?:-\d{4})?\b"


class IngilizceAdresTanimlayici(KuralTanimlayici):
    VARLIK = "TR_ADRES"
    DESENLER = (
        Desen(
            "address etiketi",
            re.compile(
                r"(?im)^[ \t]*(?:Address|Registered\s+(?:Office|Address)|Principal\s+Place\s+of\s+Business"
                r"|Residential\s+Address|Correspondence\s+Address|Domicile)[ \t]*:[ \t]*(\S[^\n]*?)[ \t]*$"
            ),
            0.85,
            grup=1,
        ),
        Desen(
            "kapı no + sokak",
            re.compile(
                rf"(?<![\w/])((?:(?:Suite|Unit|Flat|Floor|Level|Apt\.?)\s+\w+,?\s+)?\d{{1,5}}[A-Za-z]?,?\s+"
                rf"(?:[{BUYUK}][\w.'’-]*\s+){{1,4}}{_SOKAK}"
                rf"(?:[^\n]{{0,90}}?(?:{_UK_POSTA}|{_US_POSTA}|\b\d{{4,5}}\s+[{BUYUK}][a-zäöüß]+))?)"
            ),
            0.75,
            grup=1,
        ),
        Desen(
            "sokak + no (Avrupa)",
            re.compile(rf"(?<![\w])((?:[{BUYUK}][\wäöüß.'’-]*\s+){{0,2}}[\wäöüß]*(?:straße|strasse|str\.|weg|platz|gasse)\s+\d{{1,4}}[a-z]?(?:,\s*\d{{4,5}}\s+[{BUYUK}][\wäöüß]+)?)"),
            0.75,
            grup=1,
        ),
    )


class UluslararasiTelefonTanimlayici(KuralTanimlayici):
    VARLIK = "TR_TELEFON"
    DESENLER = (
        Desen(
            "+ülke kodu",
            re.compile(r"(?<![\w+])\+(?!90\b)(?:[1-9]\d{0,2})[ \t.-]?\(?\d{1,4}\)?(?:[ \t.-]?\d{2,4}){2,4}(?!\d)"),
            0.7,
        ),
    )
    BAGLAM = ("tel", "phone", "mobile", "fax", "cell", "whatsapp", "direct")


class PasaportTanimlayici(KuralTanimlayici):
    VARLIK = "TR_PASAPORT"
    DESENLER = (
        Desen(
            "pasaport bağlamı",
            re.compile(r"(?i)(?:passport|pasaport)\s*(?:no\.?|number|numarası|#)?\s*[:.]?\s*([A-Z]{0,2}\d{6,9}|[A-Z0-9]{8,9})\b"),
            0.85,
            grup=1,
        ),
    )


class IngilizceDogumTarihiTanimlayici(KuralTanimlayici):
    VARLIK = "TR_DOGUM_TARIHI"
    DESENLER = (
        Desen(
            "date of birth",
            re.compile(
                r"(?i)(?:date\s+of\s+birth|d\.?o\.?b\.?|born\s+(?:on|in)?)[^\n\d]{0,20}"
                rf"(\d{{1,2}}(?:st|nd|rd|th)?\s+{_AYLAR_EN},?\s+(?:19|20)\d{{2}}"
                rf"|{_AYLAR_EN}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+(?:19|20)\d{{2}}"
                r"|\d{1,2}[./-]\d{1,2}[./-](?:19|20)\d{2}|(?:19|20)\d{2}-\d{2}-\d{2}|(?:19|20)\d{2})"
            ),
            0.85,
            grup=1,
        ),
    )


class IngilizceDosyaNoTanimlayici(KuralTanimlayici):
    VARLIK = "TR_DOSYA_NO"
    DESENLER = (
        Desen(
            "claim/case/arbitration no",
            re.compile(
                r"(?i:claim|case|arbitration|file|matter|reference|ref\.?|docket|proceedings)\s*"
                r"(?i:no\.?|number|#)\s*[:.]?\s*([A-Z0-9][A-Za-z0-9/\-.]{3,24}[A-Za-z0-9])"
            ),
            0.8,
            grup=1,
        ),
    )


def uluslararasi_tanimlayicilar():
    return [
        IngilizceAdresTanimlayici(),
        UluslararasiTelefonTanimlayici(),
        PasaportTanimlayici(),
        IngilizceDogumTarihiTanimlayici(),
        IngilizceDosyaNoTanimlayici(),
    ]

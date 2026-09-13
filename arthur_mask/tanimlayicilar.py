"""Türk hukuk metinlerine özgü Presidio tanıyıcıları.

Hepsi kural tabanlıdır (regex + bağlam + kontrol basamağı); Türkçe bir NER
modeli olmadan çalışır. Bağlam güçlendirmesi tanıyıcının içinde yapılır; böylece
lemmatizer bulunmayan boş spaCy hattında da skorlar tutarlı kalır.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

from presidio_analyzer import AnalysisExplanation, EntityRecognizer, RecognizerResult

from .dogrulama import vkn_gecerli
from .turkce import BUYUK, KUCUK, ascii_kucuk, tr_kucuk

DIL = "tr"


@dataclass
class Desen:
    ad: str
    regex: re.Pattern
    skor: float
    grup: int = 0


class KuralTanimlayici(EntityRecognizer):
    """Regex + isteğe bağlı doğrulayıcı + satır içi bağlam güçlendirmesi."""

    VARLIK: str = ""
    DESENLER: Sequence[Desen] = ()
    BAGLAM: Sequence[str] = ()
    BAGLAM_ARTISI = 0.35
    BAGLAM_PENCERESI = 60
    # Kontrol basamağı geçen eşleşmenin taban skoru. Zayıf algoritmalarda (VKN ~%10
    # rastgele geçer) düşük tutulur; bağlam olmadan eşik altında kalıp raporlanır.
    DOGRULANINCA = 0.6

    def __init__(self):
        super().__init__(
            supported_entities=[self.VARLIK],
            name=type(self).__name__,
            supported_language=DIL,
        )

    def load(self) -> None:
        pass

    def dogrula(self, deger: str) -> Optional[bool]:
        """True: kesin, False: ele, None: doğrulama yok."""
        return None

    def filtrele(self, metin: str, bas: int, son: int) -> Optional[tuple]:
        """Eşleşmeyi daraltmak ya da elemek için alt sınıf kancası."""
        return bas, son

    def _baglam_var(self, metin: str, bas: int) -> bool:
        if not self.BAGLAM:
            return False
        pencere = tr_kucuk(metin[max(0, bas - self.BAGLAM_PENCERESI):bas])
        return any(kelime in pencere for kelime in self.BAGLAM)

    def analyze(self, text, entities, nlp_artifacts=None) -> List[RecognizerResult]:
        sonuclar = []
        for desen in self.DESENLER:
            for m in desen.regex.finditer(text):
                bas, son = m.span(desen.grup)
                if bas == son:
                    continue
                daraltilmis = self.filtrele(text, bas, son)
                if not daraltilmis:
                    continue
                bas, son = daraltilmis
                deger = text[bas:son]
                gecerlilik = self.dogrula(deger)
                if gecerlilik is False:
                    continue
                skor = desen.skor
                if gecerlilik is True:
                    skor = max(skor, self.DOGRULANINCA)
                if self._baglam_var(text, bas):
                    skor = min(1.0, skor + self.BAGLAM_ARTISI)
                aciklama = AnalysisExplanation(
                    recognizer=self.name,
                    original_score=desen.skor,
                    pattern_name=desen.ad,
                    pattern=desen.regex.pattern,
                    validation_result=gecerlilik,
                )
                sonuclar.append(
                    RecognizerResult(self.VARLIK, bas, son, skor, aciklama)
                )
        return sonuclar


# --- Kişi ve tüzel kişi --------------------------------------------------------

# O'Brien, Smith-Jones, McDonald; Türkçe kesme işaretli ek ("Kara'nın") ada katılmaz (ekten sonra büyük harf gelmez).
_AD = rf"[{BUYUK}](?:['’][{BUYUK}])?[{KUCUK}]+(?:['’][{BUYUK}][{KUCUK}]+|-[{BUYUK}][{KUCUK}]+|(?<=Mc)[{BUYUK}][{KUCUK}]+|(?<=Mac)[{BUYUK}][{KUCUK}]+)?"
_BUYUK_KELIME = rf"[{BUYUK}]{{2,}}"
_HERHANGI_AD = rf"(?:{_AD}|{_BUYUK_KELIME})"

# Ad gibi görünüp kişi olmayan hukuk/kurum sözcükleri (Türkçe küçük harfle).
KISI_OLMAYAN = {
    "yargıtay", "danıştay", "anayasa", "mahkeme", "mahkemesi", "mahkemesine",
    "mahkemesi'ne", "hakimliği", "hâkimliği", "başkanlığı", "başkanlığına",
    "müdürlüğü", "müdürlüğüne", "savcılığı", "savcılığına", "cumhuriyet",
    "hukuk", "ceza", "idare", "vergi", "asliye", "sulh", "icra", "iflas", "iş",
    "aile", "ticaret", "tüketici", "genel", "kurul", "kurulu", "daire", "dairesi",
    "heyet", "heyeti", "taraflar", "taraf", "vekil", "vekili", "davacı", "davalı",
    "müvekkil", "sanık", "şüpheli", "tanık", "türk", "türkiye", "kanun", "kanunu",
    "madde", "maddesi", "sayılı", "resmi", "resmî", "gazete", "karar", "kararı",
    "esas", "dosya", "konu", "sonuç", "istem", "talep", "açıklamalar", "deliller",
    "hukuki", "sebepler", "tarih", "imza", "ek", "ekler", "adres", "not",
    "başvuru", "başvurucu", "şirket", "şirketi", "anonim", "limited", "holding",
    "bakanlığı", "belediyesi", "kurumu", "başkanı", "üyesi", "hakim", "hâkim",
    "savcı", "katip", "kâtip", "bilirkişi", "arabulucu", "noter", "sayın",
    "yüksek", "bölge", "adliye", "idari", "kurulu'nun", "rekabet", "enerji",
    "piyasası", "düzenleme", "kişisel", "verileri", "koruma", "sermaye",
    "bankacılık", "değerlendirme", "gerekçe", "gerekçeli", "hüküm", "tebliğ",
    "yönetmelik", "yönetmeliği", "genelge", "ilgili", "ilgi", "sayı", "sayısı",
    "dava", "davası", "istinaf", "temyiz", "itiraz", "delil", "tutanak",
    # kamu ve kurum unvanları (adın önüne yapışır)
    "bakan", "bakanı", "başkan", "vali", "valisi", "kaymakam", "milletvekili", "müdür",
    "müdürü", "rektör", "dekan", "genel", "yönetim", "kurulu", "üye", "ceo", "cfo",
    # şirket unvanlarında sık geçen sektör sözcükleri
    "inşaat", "taahhüt", "sanayi", "lojistik", "gıda", "turizm", "yatırım", "danışmanlık",
    "teknoloji", "elektrik", "petrol", "madencilik", "tekstil", "otomotiv", "sigorta",
    "bankası", "finans", "gayrimenkul", "pazarlama", "dış", "iç", "ithalat", "ihracat",
}

SEKTOR_SOZCUKLERI = {
    "inşaat", "taahhüt", "sanayi", "lojistik", "gıda", "turizm", "yatırım", "danışmanlık",
    "teknoloji", "elektrik", "petrol", "madencilik", "tekstil", "otomotiv", "sigorta",
    "finans", "gayrimenkul", "pazarlama", "ithalat", "ihracat", "enerji", "kozmetik",
    "mühendislik", "yazılım", "medya", "reklam", "ticaret", "nakliyat", "gemicilik", "kimya",
    "ilaç", "sağlık", "eğitim", "mimarlık", "emlak", "holding", "grup", "logistik", "trading",
}

# Taraf ve rol isimlerinin kökleri: çekim ekli biçimleri ("davalının", "Borçluya") kişi adı değildir.
ROL_KOKLERI = (
    "davacı", "davalı", "müvekkil", "başvurucu", "başvuran", "işçi", "işveren", "borçlu", "alacaklı",
    "kiracı", "kiralayan", "kiralanan", "kiraya", "müşteki", "şüpheli", "sanık", "mağdur", "katılan",
    "tanık", "vekil", "muhatap", "keşideci", "lehtar", "şirket", "takip", "tebligat", "dükkân", "dükkan",
    "işyeri", "taraf", "yüklenici", "idare", "alıcı", "satıcı", "kefil", "mirasçı", "muris", "savcı",
    "hâkim", "hakim", "kâtib", "katib", "zabıt", "bilirkişi", "arabulucu", "noter", "avukat", "üye",
    "başkan", "müdür", "yetkili", "temsilci", "çalışan", "personel", "abi", "abla", "hanım", "bey",
    "kişi", "şahıs", "sözleşme", "kararı", "dilekçe",
)


ROL_KOKLERI = ROL_KOKLERI + (
    "claimant", "respondent", "plaintiff", "defendant", "applicant", "appellant", "seller", "buyer",
    "purchaser", "vendor", "lessor", "lessee", "landlord", "tenant", "employer", "employee", "contractor",
    "consultant", "guarantor", "borrower", "lender", "witness", "director", "shareholder", "counterpart",
    "client", "counsel", "arbitrator", "customer", "supplier", "licensor", "licensee", "company", "parties",
    "party", "signatory", "beneficiary", "trustee", "agent", "officer", "manager", "partner",
)

# Kısa köklerde ("bey", "abi", "üye") önek eşleşmesi gerçek adları yutar ("Beyza", "Abidin"); yalnız bilinen ekler.
_KISA_KOK_EKLERI = {
    "", "a", "e", "ı", "i", "u", "ü", "ya", "ye", "yı", "yi", "yu", "yü", "nın", "nin", "nun", "nün", "ın", "in",
    "un", "ün", "da", "de", "ta", "te", "dan", "den", "tan", "ten", "lar", "ler", "ları", "leri", "m", "mız",
    "miz", "s", "ciğim", "cığım", "ye", "ler'", "'s",
}


def rol_ismi_mi(kelime: str) -> bool:
    """Küçük harfe çevrilmiş sözcük bir rol isminin kendisi ya da kısa çekimli hâli mi."""
    kelime = re.split(r"['’]", kelime.strip(".,:;'’"))[0]
    for kok in ROL_KOKLERI:
        if not kelime.startswith(kok):
            continue
        ek = kelime[len(kok):]
        if len(kok) <= 4:
            if ek in _KISA_KOK_EKLERI:
                return True
        elif len(ek) <= 6:
            return True
    return False


# Ad–SOYAD kalıbında soyadı sanılabilecek hukuk kısaltmaları ve büyük harfli sözcükler.
SOYAD_OLMAYAN = {
    "hd", "hgk", "cgk", "ibk", "ibgk", "iddk", "vddk", "ygk", "bgk", "bam", "bim", "aym", "aihm", "aihs", "tbk",
    "tmk", "hmk", "cmk", "tck", "iik", "ttk", "kvkk", "sgk", "tl", "try", "usd",
    "eur", "aş", "a.ş", "ltd", "şti", "khk", "rg", "tc", "vkn", "tckn", "mersis",
    "iban", "no", "dava", "davası", "mahkemesi", "hakimliği", "hâkimliği", "ab",
    "abd", "bddk", "spk", "epdk", "btk", "gib", "kik", "rk", "sirküler", "md",
    "ve", "ile", "veya", "hakkında", "karar", "kararı", "esas", "dairesi",
    "başkanlığı", "müdürlüğü", "kurulu", "kurumu", "bakanlığı", "şirketi",
    "anonim", "limited", "holding", "dilekçesi", "dilekçe", "vekili", "davacı",
    "davalı", "sanık", "tanık", "ekler", "sonuç", "istem", "konu", "not", "ek",
    "pdf", "udf", "uyap", "kep", "hsk", "tbmm", "odtü", "mb", "gb", "api",
}

# İngilizce sözleşme ve yazışma terimleri: büyük harfle yazılsa da kişi adı değildir.
KISI_OLMAYAN.update({
    "agreement", "party", "parties", "company", "seller", "buyer", "purchaser", "court", "section", "clause",
    "schedule", "annex", "exhibit", "article", "governing", "law", "effective", "date", "confidential",
    "information", "services", "service", "board", "directors", "director", "liability", "dear", "sir",
    "madam", "regards", "sincerely", "yours", "faithfully", "kind", "best", "the", "and", "of", "for",
    "between", "whereas", "hereby", "witness", "signature", "name", "title", "address", "email", "phone",
    "notice", "notices", "term", "termination", "payment", "price", "total", "united", "kingdom", "states",
    "england", "wales", "high", "supreme", "district", "tribunal", "arbitration", "chapter", "part",
    "recital", "recitals", "definitions", "interpretation", "force", "majeure", "intellectual", "property",
    "data", "protection", "privacy", "policy", "client", "counsel", "legal", "claimant", "respondent",
    "plaintiff", "defendant", "lender", "borrower", "guarantor", "landlord", "tenant", "lessor", "lessee",
    "employer", "employee", "contractor", "consultant", "shareholder", "shareholders", "memorandum",
    "minutes", "meeting", "resolution", "resolutions", "chairman", "secretary", "managing", "chief",
    "executive", "officer", "financial", "general", "manager", "partner", "senior", "associate", "vice",
    "president", "limited", "group", "holdings", "subject", "re", "attachment", "attached", "please",
    "thank", "thanks", "hi", "hello", "team", "office", "registered", "business", "day", "days", "closing",
    "completion", "transaction", "share", "shares", "purchase", "sale", "loan", "facility", "lease",
    "employment", "contract", "distribution", "request", "statement", "due", "diligence", "report",
    "invoice", "power", "attorney", "translation", "true", "copy", "monday", "tuesday", "wednesday",
    "thursday", "friday", "saturday", "sunday", "january", "february", "march", "april", "june", "july",
    "august", "september", "october", "november", "december", "istanbul", "london", "dubai", "türkiye",
    "turkey", "republic", "turkish", "english", "german", "swiss", "delaware", "new", "york", "icc", "lcia",
    "istac", "uncitral", "nda", "spa", "sha", "llp", "inc", "ltd", "plc", "gmbh", "ag", "llc",
})
SOYAD_OLMAYAN.update({
    "llc", "inc", "plc", "llp", "gmbh", "ag", "sa", "bv", "nv", "usa", "uk", "eu", "un", "icc", "lcia", "gdpr",
    "nda", "vat", "gbp", "ceo", "cfo", "coo", "cto", "hr", "it", "id", "ltd", "corp", "co", "esq", "jr", "sr",
    "ii", "iii", "spa", "sha", "kyc", "aml", "ip", "ai", "pdf", "cc", "bcc", "fyi", "asap", "llm",
})

# Yabancı şirket türleri (sözcük sınırıyla; "AG", "SA" gibi kısa ekler yalnız unvan sonunda anlamlıdır).
ULUSLARARASI_SIRKET_EKLERI = (
    r"(?:Ltd\.?|LTD\.?|Limited|LIMITED|LLC|L\.L\.C\.|Inc\.?|INC\.?|Incorporated|Corp\.?|Corporation|PLC|plc|"
    r"LLP|L\.L\.P\.|LP|L\.P\.|GmbH|GMBH|AG|KG|SE|S\.A\.|SA|S\.A\.S\.|SAS|SARL|S\.à\s?r\.l\.|S\.p\.A\.|SpA|S\.r\.l\.|"
    r"B\.V\.|BV|N\.V\.|NV|Pte\.?\s+Ltd\.?|Pty\.?\s+Ltd\.?|Co\.,?\s+Ltd\.?|& Co\.?|FZE|FZCO|FZ-LLC|DMCC|OOO|ООО|"
    r"Holdings?|Group|GROUP|HOLDINGS?|Partners|PARTNERS|Associates|Capital)(?![\w])"
)

TUZEL_KISI_IZI = re.compile(
    r"(?:A\.\s?Ş\.?|ANONİM\s+ŞİRKETİ|Anonim\s+Şirketi|LTD\.?\s*ŞTİ\.?|Ltd\.?\s*Şti\.?"
    r"|LİMİTED\s+ŞİRKETİ|Limited\s+Şirketi|HOLDİNG|Holding|KOOPERATİFİ|Kooperatifi"
    r"|TİCARET\s+VE\s+SANAYİ|Ticaret\s+ve\s+Sanayi"
    rf"|(?<![\w]){ULUSLARARASI_SIRKET_EKLERI})"
)

KAMU_KURUMU_IZI = re.compile(
    r"(?:BAKANLIĞI|Bakanlığı|BELEDİYESİ|Belediyesi|MÜDÜRLÜĞÜ|Müdürlüğü|BAŞKANLIĞI"
    r"|Başkanlığı|KURUMU|Kurumu|VALİLİĞİ|Valiliği|KAYMAKAMLIĞI|Kaymakamlığı|HAZİNE|Hazine"
    r"|SAVCILIĞI|Savcılığı|MAHKEMESİ|Mahkemesi|ÜNİVERSİTESİ|Üniversitesi"
    r"|\bCourt\b|\bTribunal\b|\bMinistry\b|\bAuthority\b|\bCommission\b|\bAgency\b|\bDepartment\b"
    r"|\bCouncil\b|\bGovernment\b|\bRegistry\b|\bUniversity\b|\bChamber of Commerce\b|\bCompanies House\b)"
)

ROL_ETIKETLERI = (
    "DAVACI|DAVALI|DAVACILAR|DAVALILAR|MÜDAHİL|ŞÜPHELİ|SANIK|MÜŞTEKİ|KATILAN|MAĞDUR"
    "|TANIK|BORÇLU|ALACAKLI|İHBAR OLUNAN|KARŞI TARAF|BAŞVURUCU|BAŞVURAN|İTİRAZ EDEN"
    "|MÜVEKKİL|İŞÇİ|İŞVEREN|VEKİLİ|VEKİLLERİ|MÜDAFİİ|KANUNİ TEMSİLCİSİ|VASİSİ|MURİS"
    "|MİRASÇI|MİRASÇILAR|KİRAYA VEREN|KİRACI|SATICI|ALICI|KEFİL|TEMSİLCİ|YETKİLİ"
    "|Davacı|Davalı|Vekili|Müvekkil|Şüpheli|Sanık|Müşteki|Tanık|Borçlu|Alacaklı"
    "|Başvurucu|Kiracı|Kiraya Veren|Kefil|İşçi|İşveren"
    # İngilizce taraf ve imza blokları
    "|Claimant|Respondent|Plaintiff|Defendant|Applicant|Appellant|Seller|Buyer|Purchaser|Vendor"
    "|Lessor|Lessee|Landlord|Tenant|Employer|Employee|Contractor|Consultant|Guarantor|Borrower"
    "|Lender|Name|Full Name|Signed by|Signature|By|Attn|Attention|Witness|Authorised Signatory"
    "|Authorized Signatory|Contact Person|Represented by|Director|Beneficiary|Shareholder"
    "|CLAIMANT|RESPONDENT|SELLER|BUYER|NAME"
)

UNVANLAR = (
    r"Stj\.\s*Av\.|Av\.|AV\.|Avukat|AVUKAT|Sayın|SAYIN|Sn\.|Bay|Bayan|Prof\.\s*Dr\.|Doç\.\s*Dr\.|DR\."
    r"|Dr\.\s*Öğr\.\s*Üyesi|Dr\.|Hâkim|Hakim|Cumhuriyet\s+Savcısı|Savcı|Bilirkişi"
    r"|Arabulucu|Noter|Zabıt\s+Kâtibi|Zabıt\s+Katibi|SMMM|YMM|Mali\s+Müşavir"
    r"|Mr\.?|Mrs\.?|Ms\.?|Miss|Mx\.|Sir|Dame|Lord|Lady|Prof\.|Herr|Frau|Mme\.?|M\.|Sr\.|Sra\.|Dott\."
)


def _ad_temizle(metin: str, bas: int, son: int) -> Optional[tuple]:
    """Kişi adayının başındaki/sonundaki kişi olmayan sözcükleri atar."""
    kelimeler = [(m.start() + bas, m.end() + bas) for m in re.finditer(r"\S+", metin[bas:son])]
    while kelimeler and tr_kucuk(metin[kelimeler[0][0]:kelimeler[0][1]]).strip(".,:;") in KISI_OLMAYAN:
        kelimeler.pop(0)
    while kelimeler and tr_kucuk(metin[kelimeler[-1][0]:kelimeler[-1][1]]).strip(".,:;") in KISI_OLMAYAN:
        kelimeler.pop()
    if not kelimeler:
        return None
    if any(tr_kucuk(metin[a:b]).strip(".,:;") in KISI_OLMAYAN for a, b in kelimeler):
        return None
    return kelimeler[0][0], kelimeler[-1][1]


class KisiTanimlayici(KuralTanimlayici):
    """Gerçek kişi adları: rol etiketi, unvan ve 'Ad SOYAD' kalıbı."""

    VARLIK = "PERSON"
    DESENLER = (
        Desen(
            "rol etiketi",
            re.compile(
                rf"(?:{ROL_ETIKETLERI})(?:[ \t]+(?:VEKİLİ|Vekili))?[ \t]*:[ \t]*"
                rf"(?:(?:{UNVANLAR})[ \t]*)?({_HERHANGI_AD}(?:[ \t]+{_HERHANGI_AD}){{1,3}})"
            ),
            0.85,
            grup=1,
        ),
        Desen(
            "unvan",
            re.compile(rf"(?<!\w)(?:{UNVANLAR})[ \t]+({_HERHANGI_AD}(?:[ \t]+{_HERHANGI_AD}){{0,3}})"),
            0.8,
            grup=1,
        ),
        Desen(
            "Ad X. Soyad",
            re.compile(rf"(?<![\w.])({_AD}(?:[ \t]+[{BUYUK}]\.){{1,2}}[ \t]+{_HERHANGI_AD})(?![\w])"),
            0.75,
            grup=1,
        ),
        Desen(
            "rol + Ad Soyad",
            re.compile(
                r"(?<!\w)(?:Tanık|tanık|Davacı|davacı|Davalı|davalı|Müvekkil|müvekkil|Sanık|sanık"
                r"|Şüpheli|şüpheli|Müşteki|müşteki|Mağdur|mağdur|Borçlu|borçlu|Alacaklı|alacaklı"
                r"|Mirasçı|mirasçı|Muris|muris|İşçi|işçi)"
                rf"[ \t]+({_AD}[ \t]+{_AD}(?:[ \t]+{_AD})?)(?![\w])"
            ),
            0.65,
            grup=1,
        ),
        Desen(
            "Ad SOYAD",
            re.compile(
                rf"(?<![\w.])({_AD}(?:[ \t]+{_AD}){{0,2}}[ \t]+{_BUYUK_KELIME}(?:-{_BUYUK_KELIME})?)(?![\w.])"
            ),
            0.6,
            grup=1,
        ),
    )

    def filtrele(self, metin, bas, son):
        if TUZEL_KISI_IZI.search(metin[bas:son + 20]) or KAMU_KURUMU_IZI.search(metin[bas:son]):
            return None
        sinir = _ad_temizle(metin, bas, son)
        if not sinir:
            return None
        bas, son = sinir
        kelimeler = metin[bas:son].split()
        soyad = tr_kucuk(kelimeler[-1]).strip(".,:;")
        if soyad in SOYAD_OLMAYAN:
            return None
        if len(kelimeler) == 1 and not kelimeler[0].isupper():
            # "Sayın Mahkeme" gibi tek kelimelik unvan eşleşmelerinde yalnız büyük harfli soyadı kabul et.
            return None
        return bas, son


class AnaBabaAdiTanimlayici(KuralTanimlayici):
    """Nüfus kaydı kalıbı: "Ali ve Ayşe oğlu", "SÜLEYMAN ve HATİCE kızı" — iki ad ayrı bulgu olur."""

    VARLIK = "PERSON"
    _DESEN = re.compile(
        rf"(?<![\w])({_HERHANGI_AD})[ \t]+(?:ve|VE)[ \t]+({_HERHANGI_AD})[ \t]+(?:oğlu|kızı|OĞLU|KIZI)(?![\w])"
    )

    def analyze(self, text, entities, nlp_artifacts=None):
        sonuclar = []
        for m in self._DESEN.finditer(text):
            for grup in (1, 2):
                if tr_kucuk(m.group(grup)) in KISI_OLMAYAN:
                    continue
                aciklama = AnalysisExplanation(
                    recognizer=self.name, original_score=0.85, pattern_name="ana/baba adı",
                    pattern=self._DESEN.pattern,
                )
                sonuclar.append(RecognizerResult(self.VARLIK, m.start(grup), m.end(grup), 0.85, aciklama))
        return sonuclar


def _adlari_yukle():
    kesin, belirsiz = set(), set()
    for dosya in ("adlar.txt", "adlar_en.txt"):
        yol = Path(__file__).with_name("veri") / dosya
        for satir in yol.read_text(encoding="utf-8").splitlines():
            satir = satir.strip()
            if not satir or satir.startswith("#"):
                continue
            (belirsiz if satir.endswith("*") else kesin).add(tr_kucuk(satir.rstrip("*")))
    return kesin, belirsiz - kesin


ADLAR, BELIRSIZ_ADLAR = _adlari_yukle()

# Sözlükteki bir addan sonra gelip onu kişi olmaktan çıkaran sözcükler ("Deniz Hukuku", "Aydın Adliyesi").
AD_ARDINDAN_KISI_OLMAYAN = {
    "hukuku", "bölgesi", "adliyesi", "sokak", "sokağı", "caddesi", "mahallesi", "üniversitesi",
    "bankası", "otel", "oteli", "kuvvetleri", "limanı", "köprüsü", "hastanesi", "okulu", "parkı",
    "apartmanı", "sitesi", "plaza", "bulvarı", "grubu", "kulübü", "vakfı", "derneği", "ili", "ilçesi",
    "valiliği", "belediyesi", "havalimanı", "dönemi", "bayramı", "tatili", "yolu", "gazetesi",
    "yayınları", "petrol", "enerji", "sigorta", "ticaret", "yatırım", "kolejı", "koleji", "eczanesi",
    "teknik", "enstitüsü", "fakültesi", "lisesi", "vakıf", "kuvvetleri", "pınarı", "enerjisi", "tv",
    "hanım", "bey", "hanımefendi", "beyefendi",
}
ILLER = {tr_kucuk(i) for i in (
    "Adana Adıyaman Afyonkarahisar Ağrı Aksaray Amasya Ankara Antalya Ardahan Artvin Aydın Balıkesir "
    "Bartın Batman Bayburt Bilecik Bingöl Bitlis Bolu Burdur Bursa Çanakkale Çankırı Çorum Denizli "
    "Diyarbakır Düzce Edirne Elazığ Erzincan Erzurum Eskişehir Gaziantep Giresun Gümüşhane Hakkari Hatay "
    "Iğdır Isparta İstanbul İzmir Kahramanmaraş Karabük Karaman Kars Kastamonu Kayseri Kilis Kırıkkale "
    "Kırklareli Kırşehir Kocaeli Konya Kütahya Malatya Manisa Mardin Mersin Muğla Muş Nevşehir Niğde Ordu "
    "Osmaniye Rize Sakarya Samsun Şanlıurfa Siirt Sinop Sivas Şırnak Tekirdağ Tokat Trabzon Tunceli Uşak "
    "Van Yalova Yozgat Zonguldak"
).split()}


class AdSozluguKisiTanimlayici(KuralTanimlayici):
    """İlk adı Türkçe ad sözlüğünde olan 'Ad Soyad' dizileri; soyadında büyük harf şartı yok.

    Aday her büyük harfli sözcükte yeniden aranır (örtüşen ileri bakış), böylece
    "Müvekkil Şirketin ortağı Deniz Aydın" gibi dizilerde ad kaçmaz.
    """

    VARLIK = "PERSON"
    DESENLER = (
        Desen(
            "sözlükte ad + soyad",
            re.compile(rf"(?<![\w.'’])(?=({_AD}(?:[ \t]+{_HERHANGI_AD}){{1,3}}))"),
            0.7,
            grup=1,
        ),
        Desen(
            "sözlükte ad + Hanım/Bey",
            re.compile(rf"(?<![\w.'’])({_AD})(?=[ \t]+(?:Hanım|Bey|hanım|bey)(?![\w]))"),
            0.7,
            grup=1,
        ),
    )
    BELIRSIZ_SKOR = 0.55

    def filtrele(self, metin, bas, son):
        kelimeler = [(m.start() + bas, m.end() + bas) for m in re.finditer(r"\S+", metin[bas:son])]
        ilk = tr_kucuk(metin[kelimeler[0][0]:kelimeler[0][1]])
        if ilk not in ADLAR and ilk not in BELIRSIZ_ADLAR:
            return None
        if len(kelimeler) == 1:
            return bas, son  # Hanım/Bey kalıbı
        # Dizinin hemen ardındaki sözcük de denetlenir ("Yıldız Teknik Üniversitesi").
        sonraki = re.match(r"[ \t]+(\S+)", metin[son:son + 40])
        adaylar = kelimeler + ([(son + sonraki.start(1), son + sonraki.end(1))] if sonraki else [])
        # Kurum eki gelirse bütün dizi bir kurum/yer adıdır; diğer genel sözcükte dizi orada kesilir.
        for i, (a, z) in enumerate(adaylar[1:], start=1):
            kelime = tr_kucuk(metin[a:z]).strip(".,:;'’")
            kelime_kok = re.split(r"['’]", kelime)[0]
            if kelime_kok in AD_ARDINDAN_KISI_OLMAYAN and kelime_kok not in {"hanım", "bey", "hanımefendi", "beyefendi"}:
                return None
            if i < len(kelimeler) and (
                kelime in KISI_OLMAYAN or kelime in SOYAD_OLMAYAN or rol_ismi_mi(kelime)
                or kelime_kok in {"hanım", "bey", "hanımefendi", "beyefendi"}
            ):
                kelimeler = kelimeler[:i]
                break
        # Sondaki il adı "İstanbul'da" gibi yer ekiyle geliyorsa ve en az iki ad kalıyorsa at.
        if len(kelimeler) >= 3:
            a, z = kelimeler[-1]
            if tr_kucuk(metin[a:z]) in ILLER and re.match(r"['’](?:[dt][ae]n?|y?[ae])\b", metin[z:z + 5]):
                kelimeler = kelimeler[:-1]
        if len(kelimeler) < 2:
            return None
        return kelimeler[0][0], kelimeler[-1][1]

    def analyze(self, text, entities, nlp_artifacts=None):
        sonuclar = super().analyze(text, entities, nlp_artifacts)
        for s in sonuclar:
            ilk = tr_kucuk(text[s.start:s.end].split()[0])
            if ilk in BELIRSIZ_ADLAR:
                s.score = min(s.score, self.BELIRSIZ_SKOR)
        return sonuclar


class TuzelKisiTanimlayici(KuralTanimlayici):
    """Şirket unvanları. KVKK kapsamı dışında olsa da ticari sır ve NDA bakımından maskelenir."""

    VARLIK = "TR_TUZEL_KISI"
    DESENLER = (
        Desen(
            "unvan + şirket türü",
            re.compile(
                rf"(?<![\w])((?:(?:[{BUYUK}0-9][\w&.'’-]*|&|and|of|und|et|y)[ \t]+){{1,7}}"
                r"(?:A\.\s?Ş\.?|ANONİM\s+ŞİRKETİ|Anonim\s+Şirketi|LTD\.?\s*ŞTİ\.?|Ltd\.?\s*Şti\.?"
                r"|LİMİTED\s+ŞİRKETİ|Limited\s+Şirketi|KOOPERATİFİ|Kooperatifi"
                rf"|{ULUSLARARASI_SIRKET_EKLERI}))"
            ),
            0.75,
            grup=1,
        ),
    )

    def filtrele(self, metin, bas, son):
        kelimeler = [(m.start() + bas, m.end() + bas) for m in re.finditer(r"\S+", metin[bas:son])]
        while kelimeler and (
            tr_kucuk(metin[kelimeler[0][0]:kelimeler[0][1]]).strip(".,:;") in KISI_OLMAYAN
            or re.fullmatch(r"[\d.]+", metin[kelimeler[0][0]:kelimeler[0][1]])
        ):
            kelimeler.pop(0)
        if len(kelimeler) < 2:
            return None
        return kelimeler[0][0], son


# --- Kimlik ve iletişim numaraları ------------------------------------------------

class VknTanimlayici(KuralTanimlayici):
    VARLIK = "TR_VKN"
    DESENLER = (Desen("10 hane", re.compile(r"(?<![\d/.,])\d{10}(?![\d/.,]\d)"), 0.4),)
    BAGLAM = ("vergi", "vkn", "v.k.n", "vergi no", "vergi kimlik", "v.d.", "vergi dairesi")
    BAGLAM_ARTISI = 0.45
    DOGRULANINCA = 0.4

    def dogrula(self, deger):
        return True if vkn_gecerli(deger) else False


class TelefonTanimlayici(KuralTanimlayici):
    VARLIK = "TR_TELEFON"
    DESENLER = (
        Desen(
            "ön ekli",
            re.compile(
                r"(?<![\d+])(?:(?:\+|00)[ \t]?90[ \t.-]?\(?0?|\(?0)[ \t]?\(?[2-58]\d{2}\)?[ \t.-]?"
                r"\d{3}[ \t.-]?\d{2}[ \t.-]?\d{2}(?!\d)"
            ),
            0.7,
        ),
        Desen(
            "ön eksiz",
            re.compile(r"(?<![\d+/.,])\(?[2-58]\d{2}\)?[ \t.-]?\d{3}[ \t.-]?\d{2}[ \t.-]?\d{2}(?![\d/.,]\d)"),
            0.35,
        ),
    )
    BAGLAM = ("tel", "gsm", "cep", "faks", "fax", "irtibat", "whatsapp")


class MersisTanimlayici(KuralTanimlayici):
    VARLIK = "TR_MERSIS"
    DESENLER = (Desen("16 hane", re.compile(r"(?<!\d)\d{4}[ \t-]?\d{4}[ \t-]?\d{4}[ \t-]?\d{4}(?!\d)"), 0.2),)
    BAGLAM = ("mersis",)
    BAGLAM_ARTISI = 0.65


class SicilNoTanimlayici(KuralTanimlayici):
    VARLIK = "TR_SICIL_NO"
    DESENLER = (
        Desen(
            "ticaret sicil",
            re.compile(r"(?:Ticaret\s+Sicil(?:i)?|Sicil)\s*(?:No|Numarası)\s*[:.]?\s*(\d{3,8}(?:[-/]\d{1,6})?)"),
            0.8,
            grup=1,
        ),
        Desen(
            "SGK sicil",
            re.compile(r"(?:SGK|Sigorta)\s+(?:Sicil|İşyeri\s+Sicil)\s*(?:No|Numarası)\s*[:.]?\s*([\d ]{8,30}\d)"),
            0.8,
            grup=1,
        ),
    )


class DogumTarihiTanimlayici(KuralTanimlayici):
    VARLIK = "TR_DOGUM_TARIHI"
    DESENLER = (
        Desen(
            "doğum tarihi",
            re.compile(
                r"(?:Doğum\s+Tarihi|D\.\s?T\.|Doğum\s+Yeri\s+ve\s+Tarihi|doğumlu)[^\n\d]{0,30}"
                r"(\d{1,2}[./-]\d{1,2}[./-](?:19|20)\d{2})",
                re.IGNORECASE,
            ),
            0.85,
            grup=1,
        ),
        Desen(
            "tarih + doğumlu",
            re.compile(r"(\d{1,2}[./-]\d{1,2}[./-](?:19|20)\d{2})\s+doğumlu"),
            0.85,
            grup=1,
        ),
        Desen(
            "yazıyla tarih (doğum bağlamı)",
            re.compile(
                r"(?:Doğum\s+Tarihi|D\.\s?T\.|doğum\s+tarihi|doğumlu|doğdu)[^\n\d]{0,30}"
                r"(\d{1,2}\s+(?:Ocak|Şubat|Mart|Nisan|Mayıs|Haziran|Temmuz|Ağustos|Eylül|Ekim|Kasım|Aralık|OCAK|ŞUBAT|MART|NİSAN|MAYIS|HAZİRAN|TEMMUZ|AĞUSTOS|EYLÜL|EKİM|KASIM|ARALIK)\s+(?:19|20)\d{2})"
                r"|(\d{1,2}\s+(?:Ocak|Şubat|Mart|Nisan|Mayıs|Haziran|Temmuz|Ağustos|Eylül|Ekim|Kasım|Aralık|OCAK|ŞUBAT|MART|NİSAN|MAYIS|HAZİRAN|TEMMUZ|AĞUSTOS|EYLÜL|EKİM|KASIM|ARALIK)\s+(?:19|20)\d{2})(?=\s+(?:doğumlu|tarihinde\s+doğ))"
            ),
            0.85,
            grup=0,
        ),
        Desen(
            "şapkasız bağlam / boşluklu tarih",
            re.compile(r"(?i)(?:do[gğ]um[ \t]+tarihi|do[gğ]umlu|d\.[ \t]?t\.)[^\n\d]{0,30}(\d{1,2}[ ./-]\d{1,2}[ ./-](?:19|20)\d{2})"),
            0.8,
            grup=1,
        ),
        Desen(
            "yalnız yıl",
            re.compile(r"(?<!\d)((?:19|20)\d{2})(?=\s+doğumlu)|(?:doğum\s+yılı|Doğum\s+Yılı)\s*[:.]?\s*((?:19|20)\d{2})"),
            0.8,
            grup=0,
        ),
    )

    def filtrele(self, metin, bas, son):
        # Birleşik desenlerde yalnız tarih kısmını al.
        m = re.search(r"\d{1,2}\s+\S+\s+(?:19|20)\d{2}|(?:19|20)\d{2}$|\d{1,2}[./-]\d{1,2}[./-](?:19|20)\d{2}", metin[bas:son])
        if not m:
            return None
        return bas + m.start(), bas + m.end()


# --- Adres -----------------------------------------------------------------------

_YER_BIRIMI = (
    r"Mahallesi|Mah\.|Mh\.|Sokak|Sokağı|Sok\.|Sk\.|Caddesi|Cad\.|Cd\.|Bulvarı|Blv\.|Köyü|Sitesi"
)


class AdresTanimlayici(KuralTanimlayici):
    VARLIK = "TR_ADRES"
    DESENLER = (
        Desen(
            "adres etiketi",
            re.compile(
                r"(?im)^[ \t]*(?:Adres(?:i)?|İkametgâh|İkametgah|İkamet\s+Adresi|Tebligat\s+Adresi"
                r"|Yazışma\s+Adresi|Yerleşim\s+Yeri)[ \t]*:[ \t]*(\S[^\n]*?)[ \t]*$"
            ),
            0.85,
            grup=1,
        ),
        Desen(
            "mahalle/sokak + kapı no",
            re.compile(
                rf"((?:[{BUYUK}0-9][\w.'’-]*[ \t]+){{1,4}}(?:{_YER_BIRIMI})[^\n]{{0,150}}?"
                r"\b(?:No|D|Daire)\s*[:.]?\s*\d+[A-Za-z]?(?:\s*/\s*\d+)?(?:\s*(?:D|Daire|Kat)\s*[:.]?\s*\d+)*"
                rf"(?:[ \t]*[,/][ \t]*[{BUYUK}][{KUCUK}]+){{0,2}})"
            ),
            0.75,
            grup=1,
        ),
        Desen(
            "küçük harfli / OCR adres",
            re.compile(
                # Önceki sözcükler harf/rakamla başlar; " - " ayracı aşılmaz (kişi adını yutmasın).
                r"(?i)((?:[^\W_][\w.'’]*[ \t]+){1,3}(?:mahallesi|mah\.?|mh\.?)[ \t]+[^\n]{0,120}?"
                r"\b(?:no|d|daire)\b\s*[:.]?\s*\d+[a-z]?(?:\s*/\s*\d+)?(?:\s*(?:d|daire|kat|k)\s*[:.]?\s*\d+)*"
                r"(?:[ \t]*[,/]?[ \t]*[a-zçğıöşü]{3,}){0,2})"
            ),
            0.65,
            grup=1,
        ),
    )


class TcknBaglamTanimlayici(KuralTanimlayici):
    """Kimlik bağlamındaki 11 haneli sayı: kontrol basamağı tutmasa da (yazım/OCR hatası) maskelenir."""

    VARLIK = "TR_NATIONAL_ID"
    DESENLER = (
        Desen(
            "kimlik bağlamı",
            re.compile(
                r"(?i)(?:t\.?\s?c\.?\s*(?:kimlik)?\s*(?:no|numarası|nosu)?|tckn|kimlik\s+(?:no|numarası)|tc\s*no)"
                r"\s*[:.]?\s*([1-9]\d{10})(?!\d)"
            ),
            0.75,
            grup=1,
        ),
    )


class TrIbanKalipTanimlayici(KuralTanimlayici):
    """TR IBAN kalıbı: mod-97 tutmasa da (yazım hatası) hesap numarası sızmasın diye maskelenir."""

    VARLIK = "IBAN_CODE"
    DESENLER = (
        Desen("TR + 24 hane", re.compile(r"(?<![\w])TR(?:[ \t]?\d){24}(?!\d)"), 0.7),
    )


# --- UYAP dosya numarası ve mahkeme -----------------------------------------

_YIL_SIRA = r"(?:19|20)\d{2}[ \t]*/[ \t]*\d{1,7}"


class DosyaNoTanimlayici(KuralTanimlayici):
    """Esas/karar/soruşturma numaraları.

    Yüksek mahkeme içtihat atıfları motor katmanında ayrıca korunur
    (bkz. motor.ICTIHAT_ATIF_IZI); burada yalnız aday üretilir.
    """

    VARLIK = "TR_DOSYA_NO"
    DESENLER = (
        Desen(
            "etiketli",
            re.compile(
                r"(?i:dosya|esas|karar|soru[şs]turma|haz[ıi]rl[ıi]k|[iİ]cra|talimat|ba[şs]vuru|b[üu]ro|arabuluculuk"
                r"|[iİ]ddianame|takip)"
                r"[ \t]*(?i:no|numaras[ıi]|nosu|say[ıi]s[ıi])[ \t]*[:.]?[ \t]*"
                rf"({_YIL_SIRA}(?:[ \t]*(?i:e|k|esas|karar)\b\.?(?![ \t]*(?i:no\b|numaras|say[ıi]s)))?)"
            ),
            0.85,
            grup=1,
        ),
        Desen(
            "etiketli (Sayı)",
            re.compile(rf"(?m)^[ \t]*Sayı[ \t]*:[ \t]*({_YIL_SIRA})"),
            0.7,
            grup=1,
        ),
        Desen(
            "yıl/sıra + tür",
            re.compile(
                rf"(?<![\d/])({_YIL_SIRA}[ \t]*"
                r"(?:Esas|Karar|ESAS|KARAR|esas|karar|E\.|K\.|E\b|K\b|D\.[ \t]?İş|Değişik[ \t]+İş|Talimat|Tal\.|Soruşturma"
                r"|Sor\.|Hazırlık|Müt\.|Tlmt\.|sayılı[ \t]+dosya|dosyası|dosyasında|dosyasından)"
                r"(?![ \t]*(?i:no\b|numaras|say[ıi]s)))"
            ),
            0.75,
            grup=1,
        ),
    )


class MahkemeTanimlayici(KuralTanimlayici):
    """Şehir + sayı + mahkeme türü. Sıkı profilde yarı-tanımlayıcı olarak maskelenir."""

    VARLIK = "TR_MAHKEME"
    DESENLER = (
        Desen(
            "yerel mahkeme",
            re.compile(
                rf"((?:[{BUYUK}][{KUCUK}]+|[{BUYUK}]{{3,}})[ \t]+(?:(?:Batı|Anadolu|BATI|ANADOLU)[ \t]+)?"
                r"(?:\d{1,3}\.[ \t]*)?"
                r"(?:Asliye|Sulh|Ağır|İcra|Aile|Tüketici|Fikri|İş|İdare|Vergi|Çocuk|Trafik"
                r"|ASLİYE|SULH|AĞIR|İCRA|AİLE|TÜKETİCİ|FİKRİ|İŞ|İDARE|VERGİ|ÇOCUK)"
                r"[\w \t]{0,40}?(?:Mahkemesi|Hâkimliği|Hakimliği|Dairesi|MAHKEMESİ|HAKİMLİĞİ|DAİRESİ)(?:'[\wçğıöşü]+|’[\wçğıöşü]+)?)"
            ),
            0.7,
            grup=1,
        ),
    )


# --- Sızıntıya öncelik: OCR, baş harf, konuşmacı, tek başına ilk ad ---------------------

_ASCII_ADLAR = {ascii_kucuk(a) for a in ADLAR} | {ascii_kucuk(a) for a in BELIRSIZ_ADLAR}
_OCR_ROLLER = (
    r"davac[ıi]|daval[ıi]|san[ıi]k|tan[ıi]k|m[üu][şs]teki|[şs][üu]pheli|vekili|yetkilisi|muris|bor[çc]lu"
    r"|alacakl[ıi]|ma[ğg]dur|kat[ıi]lan|av\.|avukat|m[üu]vekkil|i[şs][çc]i|kirac[ıi]|kefil|ad[ıi][ \t]+soyad[ıi]"
)


class OcrKisiTanimlayici(KuralTanimlayici):
    """Türkçe karakterleri düşmüş ya da tamamen küçük harfli metinde rol bağlamındaki adlar."""

    VARLIK = "PERSON"
    DESENLER = (
        Desen(
            "OCR rol + ad",
            re.compile(rf"(?i:{_OCR_ROLLER})[ \t]*:?[ \t]+([a-zçğıöşü]{{2,}}(?:[ \t]+[a-zçğıöşü]{{2,}}){{1,2}})"),
            0.75,
            grup=1,
        ),
    )

    def filtrele(self, metin, bas, son):
        kelimeler = [(m.start() + bas, m.end() + bas) for m in re.finditer(r"\S+", metin[bas:son])]
        if ascii_kucuk(metin[kelimeler[0][0]:kelimeler[0][1]]) not in _ASCII_ADLAR:
            return None
        # Ada eklenen ilk genel sözcükte dur ("selcuk gungor tel" → "selcuk gungor").
        for i, (a, z) in enumerate(kelimeler[1:], start=1):
            kelime = ascii_kucuk(metin[a:z])
            if kelime in {ascii_kucuk(k) for k in KISI_OLMAYAN} or rol_ismi_mi(tr_kucuk(metin[a:z])) or kelime in {
                "tel", "telefon", "tc", "adres", "adresi", "eposta", "mail", "ve", "ile", "no", "plakali", "dogum",
            }:
                kelimeler = kelimeler[:i]
                break
        return (kelimeler[0][0], kelimeler[-1][1]) if len(kelimeler) >= 2 else None


class OcrSirketTanimlayici(KuralTanimlayici):
    """Küçük harfli / şapkasız şirket unvanı: 'ozgur plastik sanayi ltd sti'."""

    VARLIK = "TR_TUZEL_KISI"
    DESENLER = (
        Desen(
            "OCR unvan",
            re.compile(
                r"(?<![\w])((?:[a-zçğıöşü0-9&]+[ \t]+){1,5}"
                r"(?:ltd\.?[ \t]*[şs]ti\.?|a\.[ \t]?[şs]\.|anonim[ \t]+[şs]irketi|limited[ \t]+[şs]irketi))(?![\w])"
            ),
            0.7,
            grup=1,
        ),
    )

    def filtrele(self, metin, bas, son):
        kelimeler = [(m.start() + bas, m.end() + bas) for m in re.finditer(r"\S+", metin[bas:son])]
        genel = {ascii_kucuk(k) for k in KISI_OLMAYAN} | {"sirket", "sirketi", "firma", "firmasi", "davali", "davaci"}
        while kelimeler and (ascii_kucuk(metin[kelimeler[0][0]:kelimeler[0][1]]) in genel
                             or rol_ismi_mi(tr_kucuk(metin[kelimeler[0][0]:kelimeler[0][1]]))):
            kelimeler.pop(0)
        return (kelimeler[0][0], son) if len(kelimeler) >= 2 else None


_BAS_HARF_OLMAYAN = {"T.C.", "A.Ş.", "M.Ö.", "M.S.", "S.K.", "Y.K.", "K.K.", "A.B.", "B.M.", "D.T.", "S.S.", "T.T."}


class BasHarfTanimlayici(KuralTanimlayici):
    """Kişiye işaret eden baş harfler: 'A.Ö.R.', 'N.K.D.', 'B. Özdemir'."""

    VARLIK = "PERSON"
    DESENLER = (
        Desen("üç/iki baş harf", re.compile(rf"(?<![\w.])((?:[{BUYUK}]\.[ \t]?){{2,3}})(?![\w])"), 0.6),
        Desen("baş harf + soyad", re.compile(rf"(?<![\w.])([{BUYUK}]\.[ \t]?{_AD})(?![\w])"), 0.65),
    )

    def filtrele(self, metin, bas, son):
        parca = metin[bas:son].strip()
        son = bas + len(metin[bas:son].rstrip())
        if parca.replace(" ", "") in _BAS_HARF_OLMAYAN:
            return None
        if re.fullmatch(r"[A-ZÇĞİÖŞÜ]\.[ \t]?\S+", parca):
            soyad = tr_kucuk(parca.split(".", 1)[1].strip())
            if soyad in KISI_OLMAYAN or rol_ismi_mi(soyad) or soyad in ILLER:
                return None
        return bas, son


class KonusmaciTanimlayici(KuralTanimlayici):
    """Sohbet/tutanak dökümünde konuşmacı etiketi: '[21:31] ~Şebo:', '[10:20] Memo:'."""

    VARLIK = "PERSON"
    DESENLER = (
        Desen(
            "zaman damgalı konuşmacı",
            re.compile(rf"(?:\][ \t]*~?|^~)[ \t]*((?:[{BUYUK}][\w.]*)(?:[ \t]+[{BUYUK}][\w.]*){{0,2}})[ \t]*:", re.M),
            0.7,
            grup=1,
        ),
    )

    def filtrele(self, metin, bas, son):
        kelimeler = [tr_kucuk(k).strip(".") for k in metin[bas:son].split()]
        if all(k in KISI_OLMAYAN or rol_ismi_mi(k) for k in kelimeler):
            return None
        return bas, son


class IlkAdTanimlayici(KuralTanimlayici):
    """Metin içinde tek başına geçen, sözlükte kesin ad olarak kayıtlı büyük harfle başlayan ilk ad."""

    VARLIK = "PERSON"
    DESENLER = (Desen("tek ilk ad", re.compile(rf"(?<![\w.'’])({_AD})(?![\w])"), 0.55),)

    def filtrele(self, metin, bas, son):
        if tr_kucuk(metin[bas:son]) not in ADLAR:
            return None
        # "Hakan Bey"/"Ad Soyad" daha uzun tanıyıcılarca yakalanır; burada yalnız tek sözcük kalır.
        return bas, son


def turk_tanimlayicilari() -> List[EntityRecognizer]:
    return [
        OcrKisiTanimlayici(),
        OcrSirketTanimlayici(),
        BasHarfTanimlayici(),
        KonusmaciTanimlayici(),
        IlkAdTanimlayici(),
        KisiTanimlayici(),
        AnaBabaAdiTanimlayici(),
        AdSozluguKisiTanimlayici(),
        TuzelKisiTanimlayici(),
        VknTanimlayici(),
        TelefonTanimlayici(),
        MersisTanimlayici(),
        SicilNoTanimlayici(),
        DogumTarihiTanimlayici(),
        AdresTanimlayici(),
        TcknBaglamTanimlayici(),
        TrIbanKalipTanimlayici(),
        DosyaNoTanimlayici(),
        MahkemeTanimlayici(),
    ]

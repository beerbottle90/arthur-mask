"""İçerik temelli kırmızı hat uyarıları.

Takma adlandırma kimliği gizler, içeriği gizlemez. Aşağıdaki başlıklar, metin
maskelenmiş olsa bile dış işleyiciye gönderilmeden önce gerekçeli onay gerektirir
(büro kırmızı hat politikasıyla hizalı). Bu tarama anahtar kelime temellidir ve
eksik yakalayabilir; bir sınıflandırıcı değil, bir hatırlatıcıdır.
"""

import re
from dataclasses import dataclass
from typing import Dict, List

KATEGORILER: Dict[str, str] = {
    "Ceza savunma stratejisi / müvekkil beyanı": (
        r"savunma\s+stratejisi|müdafi(?:i|lik)|müvekkil(?:imiz)?in\s+(?:beyanı|anlatımı|ikrarı)"
        r"|ikrar(?:ı|ında)?\b|itiraf(?:ı|ında)?\b|gizli\s+görüşme|avukat[- ]müvekkil\s+yazışması"
    ),
    "Uzlaşma / sulh pazarlık sınırları": (
        r"pazarlık\s+(?:sınırı|payı|pozisyonu)|taban\s+(?:fiyat|teklif|rakam)|tavan\s+(?:teklif|rakam)"
        r"|en\s+(?:fazla|çok)\s+[^.\n]{0,40}(?:ödeyebilir|kabul\s+eder)|sulh\s+(?:teklifi|sınırı)"
        r"|uzlaşma\s+(?:teklifi|sınırı)|walk[- ]?away|BATNA"
    ),
    "Özel gizlilik taahhüdüne tabi belge": (
        r"gizlilik\s+(?:sözleşmesi|taahhüdü|anlaşması)|\bNDA\b|STRICTLY\s+CONFIDENTIAL|\bCONFIDENTIAL\b"
        r"|ticari\s+sır|gizli\s+(?:ve\s+)?(?:özel|hizmete\s+özel)|HİZMETE\s+ÖZEL|ÇOK\s+GİZLİ"
    ),
    "Özel nitelikli kişisel veri (KVKK m.6)": (
        r"sağlık\s+(?:raporu|durumu|verisi)|teşhis|tanısı\s+konul|epikriz|psikiyatri|engellilik\s+oranı"
        r"|hamile(?:lik)?|gebelik|HIV|kanser|adli\s+sicil|sabıka\s+kaydı|mahkûmiyet|mahkumiyet|hükümlü"
        r"|güvenlik\s+tedbiri|biyometrik|parmak\s+izi|genetik|\bDNA\b|mezhep|dini\s+inanç|siyasi\s+görüş"
        r"|sendika\s+üyeliği|etnik\s+köken|ırk(?:ı|sal)\b|cinsel\s+(?:hayat|yönelim)|kılık\s+(?:ve\s+)?kıyafet"
    ),
    "Kamuya açıklanmamış şirket işlemi (içsel bilgi)": (
        r"kamuya\s+açıklanmamış|içsel\s+bilgi|özel\s+durum\s+açıklaması\s+(?:öncesi|yapılmadan)"
        r"|birleşme\s+görüşme|devralma\s+görüşme|hisse\s+devri\s+görüşme|halka\s+arz\s+(?:hazırlığı|planı)"
        r"|\binsider\b|term\s+sheet|niyet\s+mektubu|\bLOI\b"
    ),
    "Personel özlük / sicil bilgisi": (
        r"özlük\s+dosyası|sicil\s+(?:raporu|notu)|performans\s+değerlendirme(?:si)?|disiplin\s+soruşturması"
        r"|maaş\s+bordrosu|ücret\s+bordrosu"
    ),
}

_DERLENMIS = {ad: re.compile(desen, re.IGNORECASE) for ad, desen in KATEGORILER.items()}


@dataclass
class KirmiziHatUyarisi:
    kategori: str
    satirlar: List[int]
    ornek: str


def tara(metin: str) -> List[KirmiziHatUyarisi]:
    uyarilar = []
    for ad, desen in _DERLENMIS.items():
        eslesmeler = list(desen.finditer(metin))
        if not eslesmeler:
            continue
        satirlar = sorted({metin.count("\n", 0, m.start()) + 1 for m in eslesmeler})
        uyarilar.append(KirmiziHatUyarisi(ad, satirlar, eslesmeler[0].group(0)))
    return uyarilar

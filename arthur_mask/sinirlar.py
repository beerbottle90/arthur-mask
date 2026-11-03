"""Belge açarken bellek sınırları.

Yükleme en çok 60 MB'tır, ama sıkıştırılmış bir arşiv açıldığında çok daha büyüyebilir; çok sayfalı bir tarama da
sayfa sayfa görüntüye çevrildiğinde belleği doldurabilir. Sınırı aşan belge belleğe açılmadan, avukata ne
yapacağını söyleyen bir iletiyle reddedilir.
"""

import zipfile
from typing import List, Tuple, Type

# Word ve UDF: bütün girdilerin açılmış toplam boyu ve girdi sayısı (bildirilen boy; zipfile bildirilenden
# fazlasını açmaz, fazlası sağlama hatası verir).
AZAMI_ACIK_BOYUT = 400 * 2**20
AZAMI_ARSIV_GIRDISI = 5_000
# Metin katmanlı PDF ve yerel OCR (her sayfa 200 DPI görüntü olarak bellekte durur).
AZAMI_PDF_SAYFASI = 2_000
AZAMI_OCR_SAYFASI = 100
# Tek sayfa görüntüsü: A4 200 DPI ~3,9 milyon piksel; A0 ~62 milyon.
AZAMI_GORUNTU_PIKSELI = 64_000_000


def arsiv_oku(zf: zipfile.ZipFile, ad: str, hata: Type[Exception]) -> List[Tuple[zipfile.ZipInfo, bytes]]:
    bilgiler = zf.infolist()
    if len(bilgiler) > AZAMI_ARSIV_GIRDISI:
        raise hata(f"{ad} içinde {len(bilgiler)} parça var; bu kadar parçalı belge güvenle açılamıyor.")
    if sum(b.file_size for b in bilgiler) > AZAMI_ACIK_BOYUT:
        raise hata(f"{ad} açıldığında {AZAMI_ACIK_BOYUT // 2**20} MB'ı aşıyor (çoğu kez çok büyük gömülü görsel ya da "
                   "nesne); belgeyi küçültüp ya da bölüp yeniden deneyin.")
    return [(bilgi, zf.read(bilgi)) for bilgi in bilgiler]

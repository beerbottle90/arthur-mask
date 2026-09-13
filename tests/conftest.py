import pytest

from arthur_mask.dogrulama import vkn_kontrol_basamagi
from arthur_mask.motor import MaskeMotoru


def tckn_uret(ilk_dokuz: str) -> str:
    r = [int(c) for c in ilk_dokuz]
    d10 = ((r[0] + r[2] + r[4] + r[6] + r[8]) * 7 - (r[1] + r[3] + r[5] + r[7])) % 10
    return ilk_dokuz + str(d10) + str((sum(r) + d10) % 10)


def vkn_uret(ilk_dokuz: str) -> str:
    return ilk_dokuz + str(vkn_kontrol_basamagi(ilk_dokuz))


def iban_uret(bban: str) -> str:
    sayi = int("".join(str(int(ch, 36)) for ch in bban + "TR00"))
    return f"TR{98 - sayi % 97:02d}{bban}"


TCKN = tckn_uret("123456789")
VKN = vkn_uret("123456789")
IBAN = iban_uret("0006100519786457841326")

DILEKCE = f"""İSTANBUL 3. ASLİYE HUKUK MAHKEMESİ'NE

Dosya No: 2024/5678 E.

DAVACI: Ayşe KARA (TCKN: {TCKN})
Adres: Örnek Mahallesi, Gül Sokak, No:10, Beşiktaş, İstanbul
VEKİLİ: Av. Mehmet Ali YILMAZ, Tel: 0532 123 45 67, e-posta: m.yilmaz@ornekhukuk.av.tr

DAVALI: Vural İnşaat Taahhüt Anonim Şirketi (Vergi No: {VKN})
Adres: Deneme Mah. Çiçek Sok. No:5 D:3 Sarıyer/İstanbul

AÇIKLAMALAR: Müvekkil KARA, davalı Vural İnşaat Taahhüt ile sözleşme imzalamış, bedel olan
1.250.000,00 TL ödenmemiştir. Ödeme {IBAN} numaralı hesaba yapılacaktı.
Yargıtay 3. HD, 2019/1234 E., 2020/567 K. sayılı kararı da bu yöndedir. Sayın Mahkeme'ye arz olunur.
Tanık Fatma Demir dinlenmelidir. Araç plakası 34 ABC 123 olan kamyon.

Davacı Vekili
Av. Mehmet Ali YILMAZ"""


@pytest.fixture(scope="session")
def motor():
    return MaskeMotoru(profil="standart")


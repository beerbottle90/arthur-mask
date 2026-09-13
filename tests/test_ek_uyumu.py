import pytest

from arthur_mask.ek_uyumu import ek_uyumla
from arthur_mask.kasa import Kasa
from arthur_mask.maskeleyici import geri_ac


@pytest.mark.parametrize(
    "deger, model_eki, beklenen",
    [
        ("Ayşe KARA", "in", "nın"),        # tamlayan, ünlüyle biten kalın
        ("Ali VURAL", "nin", "ın"),        # ünsüzle biten kalın
        ("Mehmet ÖZTÜRK", "e", "e"),       # yönelme, ince
        ("Kemal DOĞAN", "e", "a"),
        ("Fatma KOÇ", "de", "ta"),         # sertleşme
        ("Selin YILDIZ", "den", "dan"),
        ("Zeynep Şen", "i", "i"),
        ("Burak Aydoğdu", "i", "yu"),      # ünlüyle biten yuvarlak → kaynaştırma + u
        ("Ayşe KARA", "yla", "yla"),
        ("Ayşe KARA", "daki", "daki"),
        ("Deniz Ünlü", "ler", "ler"),
        ("Hüseyin Gül", "dır", "dür"),
    ],
)
def test_ek_uyumla(deger, model_eki, beklenen):
    assert ek_uyumla(deger, model_eki) == beklenen


def test_cozulemeyen_ek_ve_sayi_aynen_kalir():
    assert ek_uyumla("Ayşe KARA", "ıyormuş") == "ıyormuş"
    assert ek_uyumla("12345678950", "in") == "in"
    assert ek_uyumla("ABC Enerji A.Ş.", "nin") == "nin"


def test_geri_acmada_ek_duzeltilir():
    kasa = Kasa()
    kasa.etiket_al("KİŞİ", "PERSON", "ayşe kara", "Ayşe KARA")
    kasa.etiket_al("KİŞİ", "PERSON", "ali vural", "Ali VURAL")
    metin = "{{KİŞİ-01}}'in talebi {{KİŞİ-02}}'ye iletildi; {{KİŞİ-02}}’nin cevabı bekleniyor."
    acik, _ = geri_ac(metin, kasa)
    assert acik == "Ayşe KARA'nın talebi Ali VURAL'a iletildi; Ali VURAL’ın cevabı bekleniyor."

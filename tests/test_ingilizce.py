"""İngilizce ve uluslararası sözleşme, yazışma ve tahkim metinleri."""

import pytest

from arthur_mask import kirmizi_hat


def _bulunan(motor, metin):
    return {(b.tur, b.metin) for b in motor.analiz(metin)[0]}


@pytest.mark.parametrize(
    "metin, beklenen",
    [
        (
            'made between Harrow & Vale Holdings Limited, whose registered office is at 25 Old Broad Street, '
            'London EC2N 1HQ (the "Seller"), and Kuzey Lojistik A.Ş. (the "Buyer").',
            {("ŞİRKET", "Harrow & Vale Holdings Limited"), ("ADRES", "25 Old Broad Street, London EC2N 1HQ"),
             ("ŞİRKET", "Kuzey Lojistik A.Ş.")},
        ),
        ("By: ______ Name: John A. Whitaker Title: Director", {("KİŞİ", "John A. Whitaker")}),
        (
            "Signed by Mr. Liam O'Brien and Ms. Anna Smith-Jones on behalf of Rheinwerk Logistik GmbH, "
            "Hafenstraße 12, 20457 Hamburg.",
            {("KİŞİ", "Liam O'Brien"), ("KİŞİ", "Anna Smith-Jones"), ("ŞİRKET", "Rheinwerk Logistik GmbH"),
             ("ADRES", "Hafenstraße 12, 20457 Hamburg")},
        ),
        (
            "Respondent: Gulf Bridge Trading LLC. ICC Case No. 27845/XYZ. Tel: +44 20 7946 0958",
            {("ŞİRKET", "Gulf Bridge Trading LLC"), ("DOSYA_NO", "27845/XYZ"), ("TELEFON", "+44 20 7946 0958")},
        ),
        ("Passport No: U12345678, Date of Birth: 15 March 1985.",
         {("PASAPORT", "U12345678"), ("DOĞUM_TARİHİ", "15 March 1985")}),
        ("IBAN: GB29 NWBK 6016 1331 9268 19", {("IBAN", "GB29 NWBK 6016 1331 9268 19")}),
    ],
)
def test_ingilizce_tespitler(motor, metin, beklenen):
    assert beklenen <= _bulunan(motor, metin)


def test_ingilizce_ictihat_ve_tanimli_terimler_maskelenmez(motor):
    metin = (
        "As held in Smith v Jones [2019] EWHC 1234 (Comm) and Hadley v Baxendale (1854) 9 Exch 341, "
        "Confidential Information shall mean all information disclosed by either Party under this Agreement."
    )
    assert not _bulunan(motor, metin)


def test_ingilizce_kirmizi_hat():
    kategoriler = {u.kategori for u in kirmizi_hat.tara("PRIVILEGED AND CONFIDENTIAL — WITHOUT PREJUDICE settlement offer")}
    assert "Uzlaşma / sulh pazarlık sınırları" in kategoriler
    assert "Ceza savunma stratejisi / müvekkil beyanı" in kategoriler

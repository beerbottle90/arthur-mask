from arthur_mask.dogrulama import iban_gecerli, tckn_gecerli, vkn_gecerli

from .conftest import IBAN, TCKN, VKN


def test_tckn():
    assert tckn_gecerli(TCKN)
    assert not tckn_gecerli("12345678901")
    assert not tckn_gecerli("0" + TCKN[1:])
    assert not tckn_gecerli(TCKN[:-1])


def test_vkn():
    assert vkn_gecerli(VKN)
    bozuk = VKN[:-1] + str((int(VKN[-1]) + 1) % 10)
    assert not vkn_gecerli(bozuk)


def test_iban():
    assert iban_gecerli(IBAN)
    assert iban_gecerli(" ".join(IBAN[i:i + 4] for i in range(0, len(IBAN), 4)))
    assert not iban_gecerli(IBAN[:-1] + "0" if IBAN[-1] != "0" else IBAN[:-1] + "1")
    assert not iban_gecerli("TR12")

"""Arayüz üç dillidir (Türkçe, Azerbaycanca, İngilizce). Kaynak metin Türkçedir ve sözlüğün anahtarıdır:
sabit HTML'de data-cev / data-cev-a, uygulama.js'te cev()/cevN(), sunucunun ekrana giden metinlerinde cevN() ile
işaretlenir. Karşılığı olmayan metin ekranda Türkçe kalır; bu testler eksik çevirinin yayına çıkmasını önler."""

import ast
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

KOK = Path(__file__).resolve().parents[1]
ARAYUZ = KOK / "arthur_mask" / "arayuz"
YER = re.compile(r"\{(\w+)\}")
MARKALAR = ("ArthurLegal", "ArthurMask", "Claude", "UYAP", "Word", "UDF", "PDF")


_BOS_OGELER = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _HtmlAnahtarlari(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anahtarlar = []
        self._yigin = []

    def handle_starttag(self, etiket, oznitelikler):
        o = dict(oznitelikler)
        for ad in (o.get("data-cev-a") or "").split():
            if o.get(ad):
                self.anahtarlar.append(o[ad])
        if "data-macos" in o:
            self.anahtarlar.append(o["data-macos"])
        if etiket not in _BOS_OGELER:
            self._yigin.append((etiket, "data-cev" in o, []))

    def handle_data(self, veri):
        if self._yigin:
            self._yigin[-1][2].append(veri)

    def handle_endtag(self, etiket):
        while self._yigin:
            ad, isaretli, parcalar = self._yigin.pop()
            if isaretli:
                self.anahtarlar.append("".join(parcalar).strip())
            if ad == etiket:
                break


def html_anahtarlari():
    p = _HtmlAnahtarlari()
    p.feed((ARAYUZ / "index.html").read_text(encoding="utf-8"))
    return p.anahtarlar


JS_CAGRI = re.compile(r"\bcev[NS]?\(\s*\"((?:[^\"\\]|\\.)*)\"")


def js_anahtarlari():
    metin = (ARAYUZ / "uygulama.js").read_text(encoding="utf-8")
    return [json.loads(f'"{m}"') for m in JS_CAGRI.findall(metin)]


def py_anahtarlari():
    anahtarlar = []
    for dosya in sorted((KOK / "arthur_mask").glob("*.py")):
        for dugum in ast.walk(ast.parse(dosya.read_text(encoding="utf-8"))):
            if isinstance(dugum, ast.Call) and getattr(dugum.func, "id", None) == "cevN" and dugum.args \
                    and isinstance(dugum.args[0], ast.Constant) and isinstance(dugum.args[0].value, str):
                anahtarlar.append(dugum.args[0].value)
    return anahtarlar


def tum_anahtarlar():
    sirali = {}
    for a in html_anahtarlari() + js_anahtarlari() + py_anahtarlari():
        sirali.setdefault(a, None)
    return list(sirali)


def sozluk(dil):
    return json.loads((ARAYUZ / f"dil-{dil}.json").read_text(encoding="utf-8"))


def test_anahtarlar_bulunur():
    anahtarlar = tum_anahtarlar()
    assert len(anahtarlar) > 250
    assert "Güncellemeleri denetle" in anahtarlar          # JS
    assert "Kurtarma anahtarı" in anahtarlar               # HTML
    assert "Belgeyi buraya bırakın" in anahtarlar          # JS (bırakma alanı)
    assert "Tanımlanıp kullanılmayan terim" in anahtarlar  # sunucu (tutarlılık)
    assert "{0} geçerli bir .docx değil (Word 97-2003 .doc ise .docx olarak kaydedin)." in anahtarlar
    assert "" not in anahtarlar


@pytest.mark.parametrize("dil", ["az", "en"])
def test_her_metnin_karsiligi_var_ve_artik_anahtar_yok(dil):
    anahtarlar = tum_anahtarlar()
    s = sozluk(dil)
    eksik = [a for a in anahtarlar if not str(s.get(a) or "").strip()]
    assert eksik == [], f"{dil} sözlüğünde karşılığı olmayan metin"
    fazla = [a for a in s if a not in set(anahtarlar)]
    assert fazla == [], f"{dil} sözlüğünde artık kullanılmayan anahtar"


@pytest.mark.parametrize("dil", ["az", "en"])
def test_yer_tutucular_korunur(dil):
    for anahtar, karsilik in sozluk(dil).items():
        assert set(YER.findall(anahtar)) == set(YER.findall(karsilik)), f"{dil}: {anahtar!r}"


@pytest.mark.parametrize("dil", ["az", "en"])
def test_marka_ve_etiketler_cevrilmez(dil):
    for anahtar, karsilik in sozluk(dil).items():
        for marka in MARKALAR:
            assert anahtar.count(marka) <= karsilik.count(marka), f"{dil}: {marka} çevrilmiş: {anahtar!r}"
        for etiket in re.findall(r"\{\{[^{}]+\}\}", anahtar):
            assert etiket in karsilik


def test_yasakli_yazimlar():
    # Ürün adı bitişik yazılır; arayüzde bu kavram için "rumuz" sözcüğü kullanılmaz.
    for dosya in [ARAYUZ / "index.html", ARAYUZ / "uygulama.js", ARAYUZ / "dil-az.json", ARAYUZ / "dil-en.json",
                  ARAYUZ / "yenilikler.json", KOK / "arthur_mask" / "serit.py", KOK / "arthur_mask" / "dil.py"]:
        metin = dosya.read_text(encoding="utf-8")
        assert not re.search(r"Arthur\s+Mask", metin), dosya.name
        assert "rumuz" not in metin.lower(), dosya.name


def test_azerbaycanca_latin_alfabesi():
    kiril = re.compile(r"[Ѐ-ӿ]")
    for karsilik in sozluk("az").values():
        assert not kiril.search(karsilik), karsilik


def test_sunucu_kaliplari_geri_eslenir():
    """Arayüz, sunucunun doldurduğu metni kalıba geri eşler (uygulama.js DIL.sunucu ile aynı kural)."""
    from arthur_mask import tutarlilik

    s = sozluk("en")

    def geri(metin):
        if metin in s:
            return s[metin]
        for k in sorted((k for k in s if YER.search(k)), key=lambda k: -len(YER.sub("", k))):
            adlar = YER.findall(k)
            desen = "^" + "".join(re.escape(p) if i % 2 == 0 else "([\\s\\S]*?)"
                                  for i, p in enumerate(YER.split(k))) + "$"
            m = re.match(desen, metin)
            if m:
                return YER.sub(lambda t: m.group(adlar.index(t.group(1)) + 1), s[k])
        return None

    assert geri("Tanımlanıp kullanılmayan terim") == s["Tanımlanıp kullanılmayan terim"]
    assert geri(tutarlilik.KURAL_ADLARI["taraf_turu"]) is not None
    metin = "Tablo 2, satır 3: tutar sütunlarda farklı: sol sütunda “100 TL”, sağ sütunda “200 TL”."
    cevrilen = geri(metin)
    assert cevrilen and "“100 TL”" in cevrilen and "“200 TL”" in cevrilen and "Table" in cevrilen
    assert "satır" not in geri("Tablo 1, satır 2, sütun 1 (TR)")

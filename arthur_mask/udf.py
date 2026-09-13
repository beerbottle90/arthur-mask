"""UYAP Doküman Editörü (.udf) okuma ve yazma.

UDF bir ZIP arşividir; `content.xml` içinde belgenin düz metni tek bir
`<content><![CDATA[...]]></content>` bölümünde durur, biçim bilgisi ise
`<elements>` altındaki öğelerde `startOffset` / `length` öznitelikleriyle bu
metne işaret eder. Maskeleme metnin uzunluğunu değiştirdiği için bütün
ofsetler yeniden eşlenmelidir; aksi hâlde editör biçimi kaydırır veya dosyayı
açamaz.

Ofset birimi: Java String indeksidir, yani UTF-16 kod birimi. Türkçe harfler
tek birimdir; emoji gibi BMP dışı karakterler iki birim sayılır.

Sınır: biçim yapısı açık bir şartnameye değil gözlemlenen dosyalara dayanır.
Üretilen her dosya UYAP Doküman Editörü'nde açılarak teyit edilmelidir.
"""

import html
import re
import zipfile
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Sequence, Tuple

from .maskeleyici import Degisiklik, degisiklikleri_uygula

ICERIK_XML = "content.xml"
_ICERIK = re.compile(r"<content>(.*?)</content>", re.S)
_CDATA = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.S)
_OFSETLI_ETIKET = re.compile(r"<[^<>!?]*\bstartOffset\s*=\s*\"\d+\"[^<>]*>")
_BAS = re.compile(r"\bstartOffset\s*=\s*\"(\d+)\"")
_UZ = re.compile(r"\blength\s*=\s*\"(\d+)\"")


class UdfHatasi(Exception):
    pass


@dataclass
class UdfBelge:
    girdiler: List[Tuple[zipfile.ZipInfo, bytes]]
    xml: str
    metin: str
    icerik_bas: int
    icerik_son: int


def _icerik_coz(ham: str) -> str:
    parcalar, imlec = [], 0
    for m in _CDATA.finditer(ham):
        parcalar.append(html.unescape(ham[imlec:m.start()]))
        parcalar.append(m.group(1))
        imlec = m.end()
    parcalar.append(html.unescape(ham[imlec:]))
    return "".join(parcalar)


def _cdata(metin: str) -> str:
    return "<![CDATA[" + metin.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def oku(yol: Path) -> UdfBelge:
    try:
        with zipfile.ZipFile(yol) as zf:
            girdiler = [(bilgi, zf.read(bilgi)) for bilgi in zf.infolist()]
    except zipfile.BadZipFile as hata:
        raise UdfHatasi(f"{yol} geçerli bir UDF (ZIP) değil.") from hata
    ham = next((veri for bilgi, veri in girdiler if bilgi.filename == ICERIK_XML), None)
    if ham is None:
        raise UdfHatasi(f"{yol} içinde {ICERIK_XML} yok.")
    # XML ayrıştırıcıları satır sonlarını \n'e indirger; UYAP ofsetleri buna göre sayılır.
    xml = ham.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    m = _ICERIK.search(xml)
    if not m:
        raise UdfHatasi(f"{yol}: <content> bölümü bulunamadı.")
    return UdfBelge(girdiler, xml, _icerik_coz(m.group(1)), m.start(), m.end())


def _u16_cevirici(metin: str) -> Callable[[int], int]:
    if all(ord(ch) < 0x10000 for ch in metin):
        return lambda i: i
    birikim = [0]
    for ch in metin:
        birikim.append(birikim[-1] + (2 if ord(ch) > 0xFFFF else 1))
    return birikim.__getitem__


def _u16_uzunluk(metin: str) -> int:
    return len(metin.encode("utf-16-le")) // 2


def _ofset_eslemesi(metin: str, degisiklikler: Sequence[Degisiklik]) -> Callable[[int], int]:
    """Eski UTF-16 ofsetini yenisine çevirir.

    Değiştirilen aralığın içine düşen bir sınır, değiştirmenin başına taşınır;
    bitişik iki öğenin ortak sınırı böylece aynı yere eşlenir ve öğeler çakışmaz.
    """
    u16 = _u16_cevirici(metin)
    araliklar = []
    for bas, son, yeni in sorted(degisiklikler):
        araliklar.append((u16(bas), u16(son), _u16_uzunluk(yeni)))
    baslar = [a[0] for a in araliklar]
    kaymalar, toplam = [], 0
    for bas, son, yeni_uz in araliklar:
        kaymalar.append(toplam)
        toplam += yeni_uz - (son - bas)

    def esle(p: int) -> int:
        i = bisect_right(baslar, p) - 1
        if i < 0:
            return p
        bas, son, yeni_uz = araliklar[i]
        if p == bas:
            return p + kaymalar[i]
        if p < son:
            return bas + kaymalar[i]
        return p + kaymalar[i] + yeni_uz - (son - bas)

    return esle


def maskelenmis_xml(belge: UdfBelge, degisiklikler: Sequence[Degisiklik]) -> Tuple[str, str]:
    yeni_metin = degisiklikleri_uygula(belge.metin, degisiklikler)
    esle = _ofset_eslemesi(belge.metin, degisiklikler)
    eski_u16, yeni_u16 = _u16_uzunluk(belge.metin), _u16_uzunluk(yeni_metin)

    def etiketi_guncelle(m: re.Match) -> str:
        etiket = m.group(0)
        bas_m, uz_m = _BAS.search(etiket), _UZ.search(etiket)
        eski_bas = int(bas_m.group(1))
        eski_son = eski_bas + (int(uz_m.group(1)) if uz_m else 0)
        yeni_bas, yeni_son = esle(eski_bas), esle(eski_son)
        # Bazı üreticiler metin sonunun bir ötesine boş öğe koyar; kaynakta zaten taşan öğeye dokunulmaz.
        if yeni_bas > yeni_son or (eski_son <= eski_u16 and yeni_son > yeni_u16):
            raise UdfHatasi(f"Ofset eşlemesi metin dışına taştı: {etiket}")
        etiket = _BAS.sub(f'startOffset="{yeni_bas}"', etiket, count=1)
        if uz_m:
            etiket = _UZ.sub(f'length="{yeni_son - yeni_bas}"', etiket, count=1)
        return etiket

    once = belge.xml[:belge.icerik_bas]
    sonra = _OFSETLI_ETIKET.sub(etiketi_guncelle, belge.xml[belge.icerik_son:])
    xml = once + "<content>" + _cdata(yeni_metin) + "</content>" + sonra
    return xml, yeni_metin


def _zip_yaz(girdiler: List[Tuple[zipfile.ZipInfo, bytes]], xml: str, hedef: Path) -> None:
    gecici = Path(str(hedef) + ".tmp")
    with zipfile.ZipFile(gecici, "w", zipfile.ZIP_DEFLATED) as zf:
        for bilgi, veri in girdiler:
            zf.writestr(bilgi, xml.encode("utf-8") if bilgi.filename == ICERIK_XML else veri)
    gecici.replace(hedef)


def maskelenmis_yaz(belge: UdfBelge, degisiklikler: Sequence[Degisiklik], hedef: Path) -> str:
    """Biçimi koruyarak maskelenmiş UDF yazar; yeni düz metni döndürür."""
    xml, yeni_metin = maskelenmis_xml(belge, degisiklikler)
    _zip_yaz(belge.girdiler, xml, hedef)
    return yeni_metin


_SABLON = """<?xml version="1.0" encoding="UTF-8" ?>
<template format_id="1.8">
<content>{icerik}</content>
<properties>
    <pageFormat mediaSizeName="1" leftMargin="42.525" rightMargin="42.525" topMargin="42.525" bottomMargin="42.525" paperOrientation="1" headerFOffset="20.0" footerFOffset="20.0" />
</properties>
<elements resolver="hvl-default">
    {paragraflar}
</elements>
<styles>
    <style name="default" description="Geçerli" family="Dialog" size="12" bold="false" italic="false" />
    <style name="hvl-default" family="Times New Roman" size="12" description="Gövde" />
</styles>
</template>
"""


def metinden_udf(metin: str, hedef: Path) -> None:
    """Düz metinden sade bir UDF üretir (ör. geri açılmış yapay zekâ taslağı).

    Her satır bir paragraftır; paragrafın içeriği satır sonunu da kapsar.
    """
    metin = metin.replace("\r\n", "\n").replace("\r", "\n")
    metin = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]", "", metin)  # XML'de geçersiz (ör. PDF sayfa ayracı \f)
    paragraflar, imlec = [], 0
    satirlar = metin.split("\n")
    for i, satir in enumerate(satirlar):
        uzunluk = _u16_uzunluk(satir) + (1 if i < len(satirlar) - 1 else 0)
        paragraflar.append(
            f'<paragraph Alignment="3"><content startOffset="{imlec}" length="{uzunluk}" /></paragraph>'
        )
        imlec += uzunluk
    xml = _SABLON.format(icerik=_cdata(metin), paragraflar="".join(paragraflar))
    bilgi = zipfile.ZipInfo(ICERIK_XML)
    bilgi.compress_type = zipfile.ZIP_DEFLATED
    _zip_yaz([(bilgi, b"")], xml, hedef)

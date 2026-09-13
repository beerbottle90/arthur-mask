"""Word belgelerinin yapısı: Claude'a Markdown görünümü ve özgün belge üzerinde izli revizyon.

- `claude_gorunumu`: maskeli .docx gövdesini sırasıyla gezer; başlıkları, listeleri ve
  tabloları Markdown'a çevirir. Çift sütunlu (ör. AZ | EN) sözleşmeler tablo olarak görünür.
  Yalnız okur; XML yeniden yazılmaz.
- `revizyon_uygula`: {eski, yeni} değişikliklerini maskeli .docx üzerinde Word "izlenen
  değişiklik" (w:del / w:ins) olarak işler. Run'lar bölünür, biçim (w:rPr) korunur; tablo,
  numaralandırma ve sütun düzeni olduğu gibi kalır. Etiketlerin çözülmesi sonra yapılır.
"""

import html
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from . import docx

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class RevizyonHatasi(Exception):
    pass


# -- Claude görünümü ------------------------------------------------------------------------
def _paragraf_metni(p) -> str:
    parcalar = []
    for dugum in p.iter():
        if dugum.tag == W + "t" and dugum.text:
            parcalar.append(dugum.text)
        elif dugum.tag in (W + "tab", W + "ptab"):
            parcalar.append("\t")
        elif dugum.tag in (W + "br", W + "cr"):
            parcalar.append("\n")
    return "".join(parcalar)


def _baslik_duzeyi(p) -> int:
    stil = p.find(f"{W}pPr/{W}pStyle")
    if stil is None:
        return 0
    deger = (stil.get(W + "val") or "").lower()
    m = re.search(r"(?:heading|başlık|baslik|title)\s*(\d)?", deger)
    if not m:
        return 0
    return int(m.group(1)) if m.group(1) else 1


def _hucre_metni(tc) -> str:
    satirlar = [_paragraf_metni(p).strip() for p in tc.iter(W + "p")]
    return "<br>".join(s for s in satirlar if s).replace("|", "\\|")


def _govde_ogeleri(kap):
    """Gövdedeki paragraf ve tabloları belge sırasıyla; içerik denetimlerinin (w:sdt) içine de girer."""
    for cocuk in kap:
        if cocuk.tag in (W + "p", W + "tbl"):
            yield cocuk
        elif cocuk.tag in (W + "sdt", W + "customXml", W + "sdtContent"):
            icerik = cocuk.find(W + "sdtContent") if cocuk.tag == W + "sdt" else cocuk
            if icerik is not None:
                yield from _govde_ogeleri(icerik)


def claude_gorunumu(yol: Path) -> str:
    with zipfile.ZipFile(yol) as zf:
        kok = ET.fromstring(zf.read("word/document.xml"))
    govde = kok.find(W + "body")
    satirlar: List[str] = []
    for oge in _govde_ogeleri(govde):
        if oge.tag == W + "p":
            metin = _paragraf_metni(oge).rstrip()
            duzey = _baslik_duzeyi(oge)
            if not metin:
                if satirlar and satirlar[-1] != "":
                    satirlar.append("")
                continue
            if duzey:
                satirlar.append("#" * min(duzey, 6) + " " + metin)
            elif oge.find(f"{W}pPr/{W}numPr") is not None:
                satirlar.append("- " + metin)
            else:
                satirlar.append(metin)
        else:
            tablo = [[_hucre_metni(tc) for tc in tr.findall(W + "tc")] for tr in oge.findall(W + "tr")]
            tablo = [s for s in tablo if any(h for h in s)]
            if not tablo:
                continue
            genislik = max(len(s) for s in tablo)
            if satirlar and satirlar[-1] != "":
                satirlar.append("")
            for i, satir in enumerate(tablo):
                satir = satir + [""] * (genislik - len(satir))
                satirlar.append("| " + " | ".join(satir) + " |")
                if i == 0:
                    satirlar.append("|" + "---|" * genislik)
            satirlar.append("")
    return "\n".join(satirlar).strip() + "\n"


# -- İzli revizyon ------------------------------------------------------------------------------
@dataclass
class RevizyonRaporu:
    uygulanan: int = 0
    sorunlar: List[Dict[str, str]] = field(default_factory=list)


def _run_sinirlari(xml: str, konum: int):
    bas = max(xml.rfind("<w:r>", 0, konum), xml.rfind("<w:r ", 0, konum))
    son = xml.find("</w:r>", konum)
    if bas < 0 or son < 0:
        return None
    return bas, son + len("</w:r>")


def _rpr(run_xml: str) -> str:
    m = re.search(r"<w:rPr>.*?</w:rPr>|<w:rPr/>", run_xml, re.S)
    return m.group(0) if m else ""


def _metin_run(rpr: str, metin: str) -> str:
    return f'<w:r>{rpr}<w:t xml:space="preserve">{html.escape(metin, quote=False)}</w:t></w:r>' if metin else ""


def revizyon_uygula(kaynak: Path, degisiklikler: Sequence[Dict[str, str]], hedef: Path,
                    izli: bool = True, yazar: str = "Claude (Arthur Mask)") -> RevizyonRaporu:
    """Maskeli .docx üzerinde {eski, yeni} değişikliklerini uygular; sonuç yine maskelidir."""
    belge = docx.oku(kaynak)
    rapor = RevizyonRaporu()
    metin = belge.metin
    tarih = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    kimlik = [9000]

    # Her değişikliği önce metin aralığına çevir; bulunamayan, birden çok eşleşen, paragraf aşan ya da
    # çakışanlar raporlanır ve atlanır.
    araliklar = []
    for sira, d in enumerate(degisiklikler, start=1):
        eski, yeni = str(d.get("eski", "")), str(d.get("yeni", ""))
        if not eski:
            rapor.sorunlar.append({"sira": str(sira), "neden": "eski metin boş"})
            continue
        if "\n" in eski:
            rapor.sorunlar.append({"sira": str(sira), "neden": "eski metin paragraf/hücre sınırını aşıyor; daha kısa parçalara bölün"})
            continue
        bulunan = [m.start() for m in re.finditer(re.escape(eski), metin)]
        if not bulunan:
            rapor.sorunlar.append({"sira": str(sira), "neden": "eski metin belgede birebir bulunamadı", "eski": eski[:80]})
            continue
        if len(bulunan) > 1 and not d.get("hepsi"):
            rapor.sorunlar.append({"sira": str(sira), "neden": f"eski metin {len(bulunan)} yerde geçiyor; bağlamı genişletin ya da hepsi=true verin", "eski": eski[:80]})
            continue
        for bas in bulunan:
            aralik = (bas, bas + len(eski), yeni, sira)
            if any(a[0] < aralik[1] and aralik[0] < a[1] for a in araliklar):
                rapor.sorunlar.append({"sira": str(sira), "neden": "başka bir değişiklikle çakışıyor", "eski": eski[:80]})
                break
            araliklar.append(aralik)

    # Düğüm başına kesimler: aynı run'a birden çok değişiklik düşerse run tek seferde yeniden kurulur.
    kesimler: Dict[int, list] = {}
    basarisiz = set()
    for bas, son, yeni, sira in araliklar:
        dugumler = [i for i, d in enumerate(belge.dugumler) if d.metin_bas < son and bas < d.metin_son]
        uygun = True
        for i in dugumler:
            d = belge.dugumler[i]
            sinir = _run_sinirlari(belge.parcalar[d.parca], d.xml_bas)
            run_xml = belge.parcalar[d.parca][sinir[0]:sinir[1]] if sinir else ""
            if not sinir or "<w:delText" in run_xml or run_xml.count("<w:t>") + run_xml.count("<w:t ") > 1:
                uygun = False
        if not uygun or not dugumler:
            basarisiz.add(sira)
            rapor.sorunlar.append({"sira": str(sira), "neden": "metin zaten izli ya da karmaşık bir Word yapısında; daha dar bir parça seçin"})
            continue
        ilk = True
        for i in dugumler:
            d = belge.dugumler[i]
            a, b = max(bas - d.metin_bas, 0), min(son - d.metin_bas, len(d.metin))
            kesimler.setdefault(i, []).append((a, b, yeni if ilk else ""))
            ilk = False
    rapor.uygulanan = len({a[3] for a in araliklar} - basarisiz)

    islemler = []
    for i, parcalar_listesi in kesimler.items():
        d = belge.dugumler[i]
        xml = belge.parcalar[d.parca]
        sinir = _run_sinirlari(xml, d.xml_bas)
        rpr = _rpr(xml[sinir[0]:sinir[1]])
        yeni_xml, imlec = "", 0
        for a, b, ekle in sorted(parcalar_listesi):
            yeni_xml += _metin_run(rpr, d.metin[imlec:a])
            silinen = d.metin[a:b]
            if izli:
                if silinen:
                    kimlik[0] += 1
                    yeni_xml += (f'<w:del w:id="{kimlik[0]}" w:author="{html.escape(yazar)}" w:date="{tarih}">'
                                 f'<w:r>{rpr}<w:delText xml:space="preserve">{html.escape(silinen, quote=False)}</w:delText></w:r></w:del>')
                if ekle:
                    kimlik[0] += 1
                    yeni_xml += (f'<w:ins w:id="{kimlik[0]}" w:author="{html.escape(yazar)}" w:date="{tarih}">'
                                 f'{_metin_run(rpr, ekle)}</w:ins>')
            else:
                yeni_xml += _metin_run(rpr, ekle)
            imlec = b
        yeni_xml += _metin_run(rpr, d.metin[imlec:])
        islemler.append((d.parca, sinir[0], sinir[1], yeni_xml))

    parcalar = dict(belge.parcalar)
    for parca, run_bas, run_son, yeni_xml in sorted(islemler, key=lambda i: (i[0], i[1]), reverse=True):
        xml = parcalar[parca]
        parcalar[parca] = xml[:run_bas] + yeni_xml + xml[run_son:]

    with zipfile.ZipFile(hedef, "w", zipfile.ZIP_DEFLATED) as zf:
        for bilgi, veri in belge.girdiler:
            zf.writestr(bilgi, parcalar[bilgi.filename].encode("utf-8") if bilgi.filename in parcalar else veri)
    return rapor

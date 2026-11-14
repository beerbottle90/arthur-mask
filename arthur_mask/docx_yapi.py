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
    yorum: int = 0   # gerekçesi Word yorumu olarak eklenen değişiklik sayısı


_YORUM_TURU = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
_YORUM_ICERIK = "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _yorum_xml(kimlik: int, yazar: str, tarih: str, metin: str) -> str:
    paragraflar = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{html.escape(satir, quote=False)}</w:t></w:r></w:p>'
        for satir in metin.split("\n") if satir.strip()) or "<w:p/>"
    return (f'<w:comment w:id="{kimlik}" w:author="{html.escape(yazar)}" w:date="{tarih}" w:initials="AM">'
            f"{paragraflar}</w:comment>")


def _yorumlari_ekle(girdiler, parcalar: Dict[str, str], yorumlar: List[str]):
    """Yorumları word/comments.xml'e yazar; dosya yoksa ilişkisi ve içerik türüyle birlikte kurar.
    Dönen: (parçalar, değişen ya da yeni zip girdileri {ad: bayt})."""
    yeni_girdiler: Dict[str, bytes] = {}
    eklenecek = "".join(yorumlar)
    if "word/comments.xml" in parcalar:
        xml = parcalar["word/comments.xml"]
        konum = xml.rfind("</w:comments>")
        parcalar["word/comments.xml"] = xml[:konum] + eklenecek + xml[konum:]
        return parcalar, yeni_girdiler
    yeni_girdiler["word/comments.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:comments xmlns:w="{_W}">{eklenecek}</w:comments>').encode("utf-8")
    ham = {bilgi.filename: veri for bilgi, veri in girdiler}
    rels = ham.get("word/_rels/document.xml.rels", b"").decode("utf-8")
    if _YORUM_TURU not in rels and "</Relationships>" in rels:
        rels = rels.replace("</Relationships>", f'<Relationship Id="rIdArthurMaskYorum" Type="{_YORUM_TURU}" '
                                                 'Target="comments.xml"/></Relationships>')
        yeni_girdiler["word/_rels/document.xml.rels"] = rels.encode("utf-8")
    tur = ham.get("[Content_Types].xml", b"").decode("utf-8")
    if "/word/comments.xml" not in tur and "</Types>" in tur:
        tur = tur.replace("</Types>", f'<Override PartName="/word/comments.xml" ContentType="{_YORUM_ICERIK}"/></Types>')
        yeni_girdiler["[Content_Types].xml"] = tur.encode("utf-8")
    return parcalar, yeni_girdiler


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
                    izli: bool = True, yazar: str = "Claude (ArthurMask)") -> RevizyonRaporu:
    """Maskeli .docx üzerinde {eski, yeni, gerekce?} değişikliklerini uygular; sonuç yine maskelidir. gerekce
    verilen değişikliğin çevresine Word yorumu konur (izli kipte, yalnız ana metinde; üst/alt bilgide yorum yok)."""
    belge = docx.oku(kaynak)
    rapor = RevizyonRaporu()
    metin = belge.metin
    tarih = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    kimlik = [9000]

    # Her değişikliği önce metin aralığına çevir; bulunamayan, birden çok eşleşen, paragraf aşan ya da
    # çakışanlar raporlanır ve atlanır.
    araliklar = []
    gerekceler: Dict[int, str] = {}
    for sira, d in enumerate(degisiklikler, start=1):
        eski, yeni = str(d.get("eski", "")), str(d.get("yeni", ""))
        g = str(d.get("gerekce") or "").strip()
        if g:
            gerekceler[sira] = g[:1000]
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
    # Yorum kimlikleri belgedeki yorumlardan sonra başlar (aynı kimlik iki yorumda olmasın).
    var_olan = [int(x) for x in re.findall(r'<w:comment\b[^>]*\bw:id="(\d+)"', belge.parcalar.get("word/comments.xml", ""))]
    yorum_sayaci = [max(var_olan, default=-1) + 1]
    yorum_kimligi: Dict[int, int] = {}
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
        # Gerekçe, değişikliğin ilk geçişine bir kez yorum olur ("hepsi" ile çok yerde değişse de).
        ana_metinde = all(belge.dugumler[i].parca == "word/document.xml" for i in dugumler)
        yorumlu = izli and sira in gerekceler and ana_metinde and sira not in yorum_kimligi
        if izli and sira in gerekceler and not ana_metinde and sira not in yorum_kimligi:
            rapor.sorunlar.append({"sira": str(sira), "neden": "değişiklik uygulandı; gerekçe üst/alt bilgide yorum olarak eklenemedi"})
        if yorumlu:
            yorum_kimligi[sira] = yorum_sayaci[0]
            yorum_sayaci[0] += 1
        kid = yorum_kimligi[sira] if yorumlu else None
        for n, i in enumerate(dugumler):
            d = belge.dugumler[i]
            a, b = max(bas - d.metin_bas, 0), min(son - d.metin_bas, len(d.metin))
            kesimler.setdefault(i, []).append((a, b, yeni if n == 0 else "", kid if n == 0 else None,
                                               kid if n == len(dugumler) - 1 else None))
    rapor.uygulanan = len({a[3] for a in araliklar} - basarisiz)

    islemler = []
    for i, parcalar_listesi in kesimler.items():
        d = belge.dugumler[i]
        xml = belge.parcalar[d.parca]
        sinir = _run_sinirlari(xml, d.xml_bas)
        rpr = _rpr(xml[sinir[0]:sinir[1]])
        yeni_xml, imlec = "", 0
        for a, b, ekle, yorum_bas, yorum_son in sorted(parcalar_listesi, key=lambda k: (k[0], k[1])):
            yeni_xml += _metin_run(rpr, d.metin[imlec:a])
            silinen = d.metin[a:b]
            if yorum_bas is not None:
                yeni_xml += f'<w:commentRangeStart w:id="{yorum_bas}"/>'
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
            if yorum_son is not None:
                yeni_xml += (f'<w:commentRangeEnd w:id="{yorum_son}"/>'
                             f'<w:r><w:commentReference w:id="{yorum_son}"/></w:r>')
            imlec = b
        yeni_xml += _metin_run(rpr, d.metin[imlec:])
        islemler.append((d.parca, sinir[0], sinir[1], yeni_xml))

    parcalar = dict(belge.parcalar)
    for parca, run_bas, run_son, yeni_xml in sorted(islemler, key=lambda i: (i[0], i[1]), reverse=True):
        xml = parcalar[parca]
        parcalar[parca] = xml[:run_bas] + yeni_xml + xml[run_son:]

    yeni_girdiler: Dict[str, bytes] = {}
    yorumlar = [_yorum_xml(k, yazar, tarih, gerekceler[s]) for s, k in sorted(yorum_kimligi.items(), key=lambda x: x[1])
                if s not in basarisiz]
    if yorumlar:
        parcalar, yeni_girdiler = _yorumlari_ekle(belge.girdiler, parcalar, yorumlar)
        rapor.yorum = len(yorumlar)

    with zipfile.ZipFile(hedef, "w", zipfile.ZIP_DEFLATED) as zf:
        for bilgi, veri in belge.girdiler:
            if bilgi.filename in yeni_girdiler:
                zf.writestr(bilgi, yeni_girdiler.pop(bilgi.filename))
            else:
                zf.writestr(bilgi, parcalar[bilgi.filename].encode("utf-8") if bilgi.filename in parcalar else veri)
        for ad, veri in yeni_girdiler.items():
            zf.writestr(ad, veri)
    return rapor

"""Avukat incelemesi için yerel rapor. Gerçek değer içermez; şüpheli adaylar hariç."""

from collections import Counter
from datetime import datetime
from typing import List, Sequence, Tuple

from .kirmizi_hat import KirmiziHatUyarisi
from .motor import Bulgu
from .maskeleyici import Degisiklik


def _satir(metin: str, konum: int) -> int:
    return metin.count("\n", 0, konum) + 1


def olustur(
    kaynak_ad: str,
    profil: str,
    ozgun_metin: str,
    bulgular: Sequence[Bulgu],
    degisiklikler: Sequence[Degisiklik],
    supheli: Sequence[Bulgu],
    kirmizi: Sequence[KirmiziHatUyarisi],
    artik: Sequence[Tuple[int, str]],
    belge_uyarilari: Sequence[str] = (),
) -> str:
    s: List[str] = []
    s.append(f"# Maskeleme raporu — {kaynak_ad}")
    s.append("")
    s.append("> **YEREL — DIŞARI GÖNDERİLMEZ.** Şüpheli adaylar bölümü maskelenmemiş özgün ifade içerebilir.")
    s.append("")
    s.append(f"- Tarih: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    s.append(f"- Profil: `{profil}`")
    s.append(f"- Maskelenen ifade: **{len(bulgular)}** · farklı etiket: **{len({d[2] for d in degisiklikler})}**")
    s.append("")

    if kirmizi:
        s.append("## ⛔ Kırmızı hat uyarıları")
        s.append("")
        s.append("Takma adlandırma kimliği gizler, içeriği gizlemez. Aşağıdaki başlıklar maskeli metinde de sürer; "
                 "gönderim için ortak onayı gerekir.")
        s.append("")
        for u in kirmizi:
            s.append(f"- **{u.kategori}** — satır {', '.join(map(str, u.satirlar[:12]))}")
        s.append("")

    if belge_uyarilari:
        s.append("## ⚠️ Belge uyarıları")
        s.append("")
        for uyari in belge_uyarilari:
            s.append(f"- {uyari}")
        s.append("")

    s.append("## Maskelenenler (türe göre)")
    s.append("")
    s.append("| Etiket | Adet |")
    s.append("|---|---|")
    for etiket, adet in Counter(b.tur for b in bulgular).most_common():
        s.append(f"| {etiket} | {adet} |")
    s.append("")

    s.append("## Ayrıntı")
    s.append("")
    s.append("| Satır | Etiket | Tür | Skor | Kaynak |")
    s.append("|---|---|---|---|---|")
    for b, (_, _, etiket) in zip(bulgular, degisiklikler):
        s.append(f"| {_satir(ozgun_metin, b.bas)} | `{etiket}` | {b.varlik} | {b.skor:.2f} | {b.kaynak} |")
    s.append("")

    s.append("## ⚠️ Gözden geçirilecek şüpheli adaylar (maskelenmedi)")
    s.append("")
    if supheli:
        s.append("Eşiğin altında kaldıkları için maskelenmediler. Hassassa sözlüğe `maskele:` altında ekleyin.")
        s.append("")
        s.append("| Satır | Tür | Skor | İfade |")
        s.append("|---|---|---|---|")
        for b in supheli:
            s.append(f"| {_satir(ozgun_metin, b.bas)} | {b.varlik} | {b.skor:.2f} | `{b.metin}` |")
    else:
        s.append("Yok.")
    s.append("")

    s.append("## Artık tarama (maskeli çıktıda kalan izler)")
    s.append("")
    if artik:
        for satir, aciklama in artik:
            s.append(f"- Satır {satir}: {aciklama}")
    else:
        s.append("İz bulunmadı. Bu, kişisel veri kalmadığının garantisi değildir.")
    s.append("")
    s.append("---")
    s.append("Otomatik tespit olasılıksaldır. Maskeli çıktı gönderilmeden önce avukat tarafından okunur.")
    return "\n".join(s) + "\n"

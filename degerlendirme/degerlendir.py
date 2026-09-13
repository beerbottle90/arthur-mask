"""Etiketli TR setinde tespit başarımını ölçer (tam aralık ve kısmi örtüşme).

Kullanım:  python degerlendirme/degerlendir.py [set.txt] [--profil standart]

Tanıyıcı, eşik veya profil her değiştiğinde yeniden çalıştırılır; eski skorla
yeni yapılandırmaya güven verilmez. Sentetik set bir başlangıçtır: üretim güveni
için gerçek (maskelenmiş, onaylı) büro belgelerinden türetilmiş set gerekir.
"""

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

from arthur_mask.motor import MaskeMotoru

ETIKET = re.compile(r"\{\{([^|{}]+)\|([^{}]+)\}\}")
ESDEGER = {"DOGUM": "DOĞUM_TARİHİ"}


def ayristir(satir: str):
    metin, altin, imlec = [], [], 0
    uzunluk = 0
    for m in ETIKET.finditer(satir):
        onceki = satir[imlec:m.start()]
        metin.append(onceki)
        uzunluk += len(onceki)
        etiket, ifade = m.group(1), m.group(2)
        altin.append((uzunluk, uzunluk + len(ifade), ESDEGER.get(etiket, etiket)))
        metin.append(ifade)
        uzunluk += len(ifade)
        imlec = m.end()
    metin.append(satir[imlec:])
    return "".join(metin), altin


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("set", nargs="?", default=str(Path(__file__).with_name("tr_sentetik.txt")))
    ap.add_argument("--profil", default="standart")
    ap.add_argument("--ayrinti", action="store_true")
    args = ap.parse_args()

    motor = MaskeMotoru(profil=args.profil)
    tam = defaultdict(lambda: [0, 0, 0])  # etiket -> [tp, altın, tahmin]
    kismi_tp = kismi_altin = 0
    yanlis_pozitif = []
    kacan = []

    for satir in Path(args.set).read_text(encoding="utf-8").splitlines():
        if not satir.strip() or satir.startswith("#"):
            continue
        metin, altin = ayristir(satir)
        bulgular, _ = motor.analiz(metin)
        tahmin = {(b.bas, b.son, b.tur) for b in bulgular}
        for a in altin:
            tam[a[2]][1] += 1
            kismi_altin += 1
            if a in tahmin:
                tam[a[2]][0] += 1
            if any(t[0] < a[1] and a[0] < t[1] for t in tahmin):
                kismi_tp += 1
            else:
                kacan.append((a[2], metin[a[0]:a[1]]))
        for t in tahmin:
            tam[t[2]][2] += 1
            if not any(t[0] < a[1] and a[0] < t[1] for a in altin):
                yanlis_pozitif.append((t[2], metin[t[0]:t[1]]))

    print(f"{'Etiket':<14}{'Recall':>8}{'Precision':>11}   (tam aralık)")
    top_tp = top_altin = top_tahmin = 0
    for etiket, (tp, n_altin, n_tahmin) in sorted(tam.items()):
        r = tp / n_altin if n_altin else float("nan")
        p = tp / n_tahmin if n_tahmin else float("nan")
        print(f"{etiket:<14}{r:>8.2f}{p:>11.2f}")
        top_tp, top_altin, top_tahmin = top_tp + tp, top_altin + n_altin, top_tahmin + n_tahmin
    print(f"{'TOPLAM':<14}{top_tp / top_altin:>8.2f}{top_tp / max(top_tahmin, 1):>11.2f}")
    print(f"Kısmi örtüşmeli recall (sızıntı açısından asıl ölçü): {kismi_tp / kismi_altin:.2f}")
    if args.ayrinti or kacan or yanlis_pozitif:
        for etiket, ifade in kacan:
            print(f"  KAÇAN   {etiket:<12} {ifade!r}")
        for etiket, ifade in yanlis_pozitif:
            print(f"  FAZLA   {etiket:<12} {ifade!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

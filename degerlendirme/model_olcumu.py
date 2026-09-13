"""NER adaylarını kural motoruyla aynı etiketli sette karşılaştırır.

Kullanım (ölçüm ortamı):
    .venv-olcum/Scripts/python.exe degerlendirme/model_olcumu.py SET.txt [--sistem kural akdeniz27 ...]

Ölçütler
- sızıntı recall: altın aralığın, etiketi ne olursa olsun, bir tahminle örtüşme oranı
  (maskelenmemiş gerçek veri = sızıntı; asıl güvenlik ölçüsü)
- tür recall / precision: aynı türle kısmi örtüşme
- fazla maskeleme: hiçbir altın aralıkla örtüşmeyen tahmin sayısı
- süre: ~20 sayfalık (~60.000 karakter) tek belgede CPU süresi
"""

import argparse
import gc
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Callable, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from degerlendir import ayristir  # noqa: E402

Aralik = Tuple[int, int, str]
SAYFA_KARAKTER = 3000

# Model etiketleri → Arthur Mask türleri (eşlenmeyenler yok sayılır)
AKDENIZ = {"PER": "KİŞİ", "ORG": "ŞİRKET"}
GLINER_ETIKETLERI = {
    "person": "KİŞİ", "company": "ŞİRKET", "address": "ADRES", "phone number": "TELEFON",
    "email": "EPOSTA", "national id number": "TCKN", "iban": "IBAN", "license plate": "PLAKA",
    "date of birth": "DOĞUM_TARİHİ",
}
BTX = {
    "person": "KİŞİ", "private_person": "KİŞİ", "address": "ADRES", "private_address": "ADRES",
    "phone": "TELEFON", "private_phone": "TELEFON", "email": "EPOSTA", "private_email": "EPOSTA",
    "tckn": "TCKN", "iban": "IBAN", "account": "IBAN", "account_number": "IBAN",
}


def _bellek_mb() -> float:
    try:
        import psutil
        return psutil.Process(os.getpid()).memory_info().rss / 2**20
    except ImportError:
        return float("nan")


def sistem_kural() -> Callable[[str], List[Aralik]]:
    from arthur_mask.motor import MaskeMotoru
    motor = MaskeMotoru()
    return lambda metin: [(b.bas, b.son, b.tur) for b in motor.analiz(metin)[0]]


def _eslenmis(sonuclar, esleme, bas_anahtar="start", son_anahtar="end", etiket_anahtar="entity_group"):
    cikti = []
    for s in sonuclar:
        ham = str(s.get(etiket_anahtar) or s.get("label") or "")
        tur = esleme.get(ham) or esleme.get(ham.lower()) or esleme.get(ham.split("-")[-1])
        if tur:
            cikti.append((int(s[bas_anahtar]), int(s[son_anahtar]), tur))
    return cikti


def sistem_akdeniz27() -> Callable[[str], List[Aralik]]:
    from transformers import pipeline
    boru = pipeline("token-classification", model="akdeniz27/bert-base-turkish-cased-ner",
                    aggregation_strategy="simple", device=-1)
    return lambda metin: _eslenmis(boru(metin), AKDENIZ)


def sistem_gliner() -> Callable[[str], List[Aralik]]:
    from gliner import GLiNER
    model = GLiNER.from_pretrained("urchade/gliner_multi_pii-v1")
    etiketler = list(GLINER_ETIKETLERI)
    return lambda metin: _eslenmis(
        model.predict_entities(metin, etiketler, threshold=0.5), GLINER_ETIKETLERI, etiket_anahtar="label"
    )


def sistem_btx24() -> Callable[[str], List[Aralik]]:
    from huggingface_hub import snapshot_download
    from opf import OPF  # github.com/openai/privacy-filter (Apache-2.0)
    yol = snapshot_download("BTX24/turkish-privacy-filter-pii", allow_patterns=["*.json", "*.safetensors", "*.txt"])
    model = OPF(model=yol, device="cpu", output_mode="typed")

    def tespit(metin: str) -> List[Aralik]:
        sonuc = model.redact(metin)
        return [(s.start, s.end, BTX[s.label]) for s in sonuc.detected_spans if s.label in BTX]

    return tespit


SISTEMLER: Dict[str, Callable[[], Callable[[str], List[Aralik]]]] = {
    "kural": sistem_kural,
    "akdeniz27": sistem_akdeniz27,
    "gliner_pii": sistem_gliner,
    "btx24": sistem_btx24,
}


def _ortusur(a: Aralik, b: Aralik) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def olc(ornekler, tahminler: List[List[Aralik]]) -> dict:
    tur_tp, tur_altin, tur_tahmin = defaultdict(int), defaultdict(int), defaultdict(int)
    sizinti_tp = altin_toplam = fazla = 0
    kacanlar = []
    for (metin, altin), tahmin in zip(ornekler, tahminler):
        for a in altin:
            altin_toplam += 1
            tur_altin[a[2]] += 1
            if any(_ortusur(a, t) for t in tahmin):
                sizinti_tp += 1
            else:
                kacanlar.append((a[2], metin[a[0]:a[1]]))
            if any(_ortusur(a, t) and t[2] == a[2] for t in tahmin):
                tur_tp[a[2]] += 1
        for t in tahmin:
            tur_tahmin[t[2]] += 1
            if not any(_ortusur(a, t) for a in altin):
                fazla += 1
    turler = {}
    for tur in sorted(set(tur_altin) | set(tur_tahmin)):
        dogru_tahmin = sum(
            1 for (metin, altin), tahmin in zip(ornekler, tahminler)
            for t in tahmin if t[2] == tur and any(_ortusur(a, t) and a[2] == tur for a in altin)
        )
        turler[tur] = (
            tur_tp[tur] / tur_altin[tur] if tur_altin[tur] else float("nan"),
            dogru_tahmin / tur_tahmin[tur] if tur_tahmin[tur] else float("nan"),
            tur_altin[tur],
        )
    return {"sizinti_recall": sizinti_tp / max(altin_toplam, 1), "fazla": fazla, "turler": turler, "kacanlar": kacanlar}


def birlestir(*listeler: List[List[Aralik]]) -> List[List[Aralik]]:
    return [sum(parcalar, []) for parcalar in zip(*listeler)]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("set")
    ap.add_argument("--sistem", nargs="+", default=list(SISTEMLER))
    ap.add_argument("--kacanlar", action="store_true")
    args = ap.parse_args()

    ornekler = []
    for satir in Path(args.set).read_text(encoding="utf-8").splitlines():
        if satir.strip() and not satir.startswith("#"):
            ornekler.append(ayristir(satir))
    karakter = sum(len(m) for m, _ in ornekler)
    print(f"Set: {len(ornekler)} satır, {sum(len(a) for _, a in ornekler)} altın aralık, {karakter} karakter\n")

    sonuclar, sureler = {}, {}
    for ad in args.sistem:
        bellek_once = _bellek_mb()
        t0 = time.perf_counter()
        try:
            tespit = SISTEMLER[ad]()
        except Exception as hata:  # model yüklenemezse ölçümü sürdür
            print(f"[{ad}] YÜKLENEMEDİ: {type(hata).__name__}: {hata}\n")
            continue
        yukleme = time.perf_counter() - t0
        tespit(ornekler[0][0])  # ısınma
        t1 = time.perf_counter()
        sonuclar[ad] = [tespit(m) for m, _ in ornekler]
        calisma = time.perf_counter() - t1
        # Gerçekçi süre: ~20 sayfalık tek belge. Kurallar bütün metni tek çağrıda işler;
        # modeller bağlam sınırı nedeniyle ~1500 karakterlik satır bloklarıyla çalışır.
        belge = "\n".join(m for m, _ in ornekler)
        belge = (belge + "\n") * max(1, (20 * SAYFA_KARAKTER) // len(belge) + 1)
        belge = belge[: 20 * SAYFA_KARAKTER]
        t2 = time.perf_counter()
        if ad == "kural":
            tespit(belge)
        else:
            blok = ""
            for satir in belge.split("\n"):
                if len(blok) + len(satir) > 1500 and blok:
                    tespit(blok)
                    blok = ""
                blok += satir + "\n"
            if blok:
                tespit(blok)
        belge_suresi = time.perf_counter() - t2
        sureler[ad] = (yukleme, calisma, belge_suresi, _bellek_mb() - bellek_once)
        del tespit
        gc.collect()

    satirlar = dict(sonuclar)
    if "kural" in sonuclar:
        for ad in sonuclar:
            if ad != "kural":
                satirlar[f"kural+{ad}"] = birlestir(sonuclar["kural"], sonuclar[ad])

    print(f"{'Sistem':<22}{'Sızıntı R':>10}{'KİŞİ R':>8}{'KİŞİ P':>8}{'Fazla':>7}{'Yükleme':>9}{'20 syf':>9}{'Bellek':>9}")
    for ad, tahminler in satirlar.items():
        o = olc(ornekler, tahminler)
        kisi = o["turler"].get("KİŞİ", (float("nan"), float("nan"), 0))
        sure = sureler.get(ad) or tuple(
            sum(x) for x in zip(*(sureler[p] for p in ad.split("+") if p in sureler))
        )
        print(f"{ad:<22}{o['sizinti_recall']:>10.3f}{kisi[0]:>8.3f}{kisi[1]:>8.3f}{o['fazla']:>7}"
              f"{sure[0]:>8.1f}s{sure[2]:>8.1f}s{sure[3]:>7.0f}MB")
    print()
    for ad, tahminler in satirlar.items():
        o = olc(ornekler, tahminler)
        ayrinti = "  ".join(f"{t}:{r:.2f}/{p:.2f}" for t, (r, p, n) in o["turler"].items() if n)
        print(f"{ad:<22}{ayrinti}")
        if args.kacanlar:
            for tur, ifade in o["kacanlar"][:40]:
                print(f"    KAÇAN {tur:<10} {ifade!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

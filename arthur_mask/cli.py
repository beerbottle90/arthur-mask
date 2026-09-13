"""Komut satırı: arthur-mask maskele | geri-ac | tara"""

import argparse
import getpass
import os
import sys
from pathlib import Path

from . import belgeler, kirmizi_hat
from .kasa import PAROLA_DEGISKENI, Kasa, KasaHatasi
from .motor import PROFILLER, MaskeMotoru
from .servis import geri_ac_metin, maskele_belge, varsayilan_cikti
from .sozluk import Sozluk

CIKIS_KIRMIZI_HAT = 3


def _parola(yeni: bool) -> str:
    parola = os.environ.get(PAROLA_DEGISKENI)
    if parola:
        return parola
    parola = getpass.getpass("Kasa parolası: ")
    if yeni and getpass.getpass("Kasa parolası (tekrar): ") != parola:
        sys.exit("Parolalar eşleşmiyor.")
    return parola


def _belge_ac(yol: str) -> belgeler.Belge:
    try:
        return belgeler.ac(Path(yol))
    except (belgeler.BelgeHatasi, FileNotFoundError) as hata:
        sys.exit(f"✗ {hata}")


def _motor(args, sozluk: Sozluk) -> MaskeMotoru:
    return MaskeMotoru(
        profil=args.profil,
        sozluk=sozluk,
        esik=args.esik,
        semantik={"otomatik": None, "acik": True, "kapali": False}[args.semantik],
        ictihat_koruma=not args.ictihat_atiflarini_da_maskele,
    )


def komut_maskele(args) -> int:
    girdi = Path(args.girdi)
    belge = _belge_ac(args.girdi)
    sozluk = Sozluk.yukle(args.sozluk)

    kasa_yolu = Path(args.kasa) if args.kasa else girdi.with_name("dosya.kasa")
    parola = _parola(yeni=not kasa_yolu.exists())
    try:
        kasa = Kasa.ac_veya_olustur(kasa_yolu, parola, dosya=sozluk.dosya)
    except KasaHatasi as hata:
        sys.exit(str(hata))

    sonuc = maskele_belge(belge, _motor(args, sozluk), kasa)
    rapor_yolu = varsayilan_cikti(girdi, "maske-raporu", ".md")
    rapor_metni = sonuc.rapor
    if sonuc.kirmizi and args.kirmizi_hat_onayi:
        rapor_metni += f"\nKırmızı hat onayı gerekçesi: {args.kirmizi_hat_onayi}\n"
    rapor_yolu.write_text(rapor_metni, encoding="utf-8")

    if sonuc.kirmizi and not args.kirmizi_hat_onayi:
        print(f"⛔ Kırmızı hat: {', '.join(u.kategori for u in sonuc.kirmizi)}")
        print(f"Maskeli çıktı YAZILMADI. Rapor: {rapor_yolu}")
        print('Ortak onayıyla devam için: --kirmizi-hat-onayi "gerekçe"')
        return CIKIS_KIRMIZI_HAT

    cikti = Path(args.cikti) if args.cikti else varsayilan_cikti(girdi, "maskeli", belge.cikti_uzantisi)
    belge.yaz(sonuc.degisiklikler, cikti)
    kasa.kaydet(kasa_yolu, parola)
    print(f"✓ {len(sonuc.bulgular)} ifade {sonuc.etiket_sayisi} etiketle maskelendi → {cikti}")
    print(f"  Kasa: {kasa_yolu}  ·  Rapor (yerel): {rapor_yolu}")
    for uyari in belge.uyarilar:
        print(f"  ⚠ {uyari}")
    if sonuc.supheli:
        print(f"  ⚠ {len(sonuc.supheli)} şüpheli aday maskelenmedi; rapordan gözden geçirin.")
    if sonuc.artik:
        print(f"  ⚠ Artık taramada {len(sonuc.artik)} iz var; rapora bakın.")
    return 0


def komut_geri_ac(args) -> int:
    girdi = Path(args.girdi)
    belge = _belge_ac(args.girdi)
    try:
        kasa = Kasa.ac(Path(args.kasa), _parola(yeni=False))
    except (KasaHatasi, FileNotFoundError) as hata:
        sys.exit(str(hata))

    acik_metin, degisiklikler, bilinmeyen = geri_ac_metin(belge.metin, kasa)
    if args.bicim:
        cikti = Path(args.cikti) if args.cikti else varsayilan_cikti(girdi, "acik", "." + args.bicim)
        belgeler.metinden_yaz(acik_metin, cikti)
    else:
        cikti = Path(args.cikti) if args.cikti else varsayilan_cikti(girdi, "acik", belge.cikti_uzantisi)
        belge.yaz(degisiklikler, cikti)

    print(f"✓ {len(degisiklikler)} etiket geri açıldı → {cikti}")
    if bilinmeyen:
        print(f"  ⚠ Kasada olmayan etiketler (model üretmiş veya bozmuş olabilir): {', '.join(bilinmeyen)}")
    print("  Çıktı gerçek kişisel veri içerir; yalnız yerelde tutun.")
    return 0


def komut_tara(args) -> int:
    belge = _belge_ac(args.girdi)
    metin = belge.metin
    bulgular, supheli = _motor(args, Sozluk.yukle(args.sozluk)).analiz(metin)
    for b in bulgular:
        print(f"{metin.count(chr(10), 0, b.bas) + 1:>4}  {b.tur:<14} {b.skor:.2f}  {b.metin!r}  ({b.kaynak})")
    for b in supheli:
        print(f"{metin.count(chr(10), 0, b.bas) + 1:>4}  ? {b.tur:<12} {b.skor:.2f}  {b.metin!r}  ({b.kaynak})")
    for u in kirmizi_hat.tara(metin):
        print(f"⛔ {u.kategori}: satır {u.satirlar}")
    for uyari in belge.uyarilar:
        print(f"⚠ {uyari}")
    return 0


def _ortak(p: argparse.ArgumentParser) -> None:
    p.add_argument("girdi", help=", ".join(belgeler.DESTEKLENEN))
    p.add_argument("--sozluk", help="dosyaya özgü kişisel sözlük (YAML)")
    p.add_argument("--profil", default="standart", choices=sorted(PROFILLER))
    p.add_argument("--esik", type=float, default=0.5, help="maskeleme skor eşiği (varsayılan 0.5)")
    p.add_argument("--semantik", choices=["otomatik", "acik", "kapali"], default="otomatik",
                   help="yerel GLiNER katmanı (otomatik: kuruluysa açık)")
    p.add_argument("--ictihat-atiflarini-da-maskele", action="store_true",
                   help="Yargıtay/Danıştay/AYM atıflarındaki esas-karar numaralarını da maskele")


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ana = argparse.ArgumentParser(prog="arthur-mask", description="Arthur Mask — ArthurLegal takma adlandırma kapısı")
    alt = ana.add_subparsers(dest="komut", required=True)

    p = alt.add_parser("maskele", help="belgeyi maskele, kasaya yaz, rapor üret")
    _ortak(p)
    p.add_argument("--kasa", help="dosya kasası (varsayılan: girdinin yanında dosya.kasa)")
    p.add_argument("--cikti")
    p.add_argument("--kirmizi-hat-onayi", metavar="GEREKÇE",
                   help="kırmızı hat uyarısına rağmen yazmak için ortak onay gerekçesi")
    p.set_defaults(islev=komut_maskele)

    p = alt.add_parser("geri-ac", help="maskeli metni/belgeyi kasa ile geri aç")
    p.add_argument("girdi")
    p.add_argument("--kasa", required=True)
    p.add_argument("--cikti")
    p.add_argument("--bicim", choices=["udf", "docx", "txt"],
                   help="çıktıyı bu biçimde yeni belge olarak üret (varsayılan: girdi biçimini koru)")
    p.set_defaults(islev=komut_geri_ac)

    p = alt.add_parser("tara", help="yalnız tespit et ve listele (kasa yok, dosya yazmaz)")
    _ortak(p)
    p.set_defaults(islev=komut_tara)

    args = ana.parse_args(argv)
    return args.islev(args)


if __name__ == "__main__":
    sys.exit(main())

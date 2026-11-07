"""Yerel servis ve MCP köprüsünün ortak iş katmanı.

Güvenlik sözleşmesi: bu modülden `mcp_*` adıyla dönen hiçbir değer gerçek kişisel
veri içermez. Gerçek değer yalnız `arayuz_*` işlevlerinden, yalnız yerel arayüze döner.
"""

import hashlib
import json
import logging
import os
import tempfile
import threading
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple

from . import belgeler, docx, docx_yapi, surum, tutarlilik, udf
from .cikis import CikisDenetimi
from .depo import Depo, simdi
from .maskeleyici import ETIKET_DESENI, geri_acma_degisiklikleri, maskele
from .servis import geri_ac_metin, maskele_belge

if TYPE_CHECKING:  # motor presidio ve spaCy'yi yükler; köprü açılışında bu bedel ödenmez
    from .motor import MaskeMotoru

gunluk = logging.getLogger("arthur_mask")

MCP_PARCA_KARAKTER = 30_000
DURUM_HAZIR, DURUM_ONAY, DURUM_KIRMIZI = "hazir", "onay_bekliyor", "kirmizi_hat"
TESLIM_BICIMLERI = {"docx": ".docx", "udf": ".udf", "txt": ".txt"}


class IslemHatasi(Exception):
    pass


def parcalara_bol(metin: str, boy: int = MCP_PARCA_KARAKTER, korunan: Sequence[Tuple[int, int]] = ()) -> List[str]:
    """En çok `boy` karakterlik parçalar; kesim satır sonunda, yoksa boşlukta yapılır (etiket ikiye bölünmesin).
    `korunan` aralıkların (kasadaki değerlerin geçtiği yerler) ortasından kesilmez: her parça çıkış kapısından ayrı
    geçtiği için değer bütün kalmalı."""
    parcalar, bas = [], 0
    while len(metin) - bas > boy:
        kesim = metin.rfind("\n", bas + boy // 2, bas + boy)
        if kesim < 0:
            kesim = metin.rfind(" ", bas + boy // 2, bas + boy)
        kesim = kesim + 1 if kesim >= 0 else bas + boy
        degisti = True
        while degisti:
            degisti = False
            for a_bas, a_son in korunan:
                if a_bas < kesim < a_son:
                    kesim, degisti = (a_bas if a_bas > bas else a_son), True
        parcalar.append(metin[bas:kesim])
        bas = kesim
    parcalar.append(metin[bas:])
    return parcalar


def _etiket_turleri(degisiklikler) -> Dict[str, int]:
    """Tür başına benzersiz etiket sayısı ({{KİŞİ-01}} üç kez geçse de 1 kişi)."""
    etiketler = {d[2] for d in degisiklikler}
    return dict(Counter(e[2:-2].rsplit("-", 1)[0] for e in etiketler))


def sayfala(ogeler: List[Dict], boy: int = MCP_PARCA_KARAKTER) -> List[List[Dict]]:
    """Liste öğelerini, her sayfanın JSON boyu `boy` karakteri geçmeyecek biçimde böler (öğe bölünmez)."""
    sayfalar: List[List[Dict]] = [[]]
    uzunluk = 0
    for oge in ogeler:
        boyu = len(json.dumps(oge, ensure_ascii=False)) + 2
        if sayfalar[-1] and uzunluk + boyu > boy:
            sayfalar.append([])
            uzunluk = 0
        sayfalar[-1].append(oge)
        uzunluk += boyu
    return sayfalar


def _sayim_metni(sayim: Dict[str, int]) -> str:
    adlar = [("degisen", "paragraf değişti"), ("eklenen", "paragraf eklendi"), ("silinen", "paragraf silindi"),
             ("satir_eklenen", "tablo satırı eklendi"), ("satir_silinen", "tablo satırı silindi"),
             ("tablo_eklenen", "tablo eklendi"), ("tablo_silinen", "tablo silindi")]
    parcalar = [f"{sayim[k]} {ad}" for k, ad in adlar if sayim.get(k)]
    return ", ".join(parcalar) if parcalar else "gövde metninde fark bulunmadı"


class Islem:
    def __init__(self, depo: Depo, semantik: Optional[bool] = None):
        self.depo = depo
        self._semantik = semantik
        self._motor: Optional["MaskeMotoru"] = None
        self._motor_kilidi = threading.Lock()
        self._motor_hazir = threading.Event()
        # Claude'un kullanıcıyı yönlendirebilmesi için yerel arayüz adresi (köprü başlatınca atanır).
        self.arayuz_adresi = "http://127.0.0.1:47831/"
        # Onay bekleyen belgelerin özgün metni ve bulguları yalnız bellekte durur (diske yazılmaz).
        self._bekleyen: Dict[tuple, tuple] = {}
        self._denetim: Dict[str, tuple] = {}

    # -- motor -------------------------------------------------------------------------
    def motoru_arkaplanda_yukle(self) -> None:
        threading.Thread(target=self.motor, name="motor-yukleme", daemon=True).start()

    def motor(self) -> "MaskeMotoru":
        from .motor import MaskeMotoru  # ağır bağımlılıklar burada yüklenir (arka plan işçisi çağırır)

        with self._motor_kilidi:
            if self._motor is None:
                semantik = self._semantik
                if semantik is None and os.environ.get("ARTHUR_MASK_SEMANTIK") == "kapali":
                    semantik = False
                self._motor = MaskeMotoru(semantik=semantik)
                self._motor_hazir.set()
                gunluk.info("Motor hazır (semantik=%s)", self._motor.semantik)
        return self._motor

    @property
    def motor_hazir(self) -> bool:
        return self._motor_hazir.is_set()

    def _aktif(self) -> str:
        klasor = self.depo.aktif_dosya
        if not klasor:
            raise IslemHatasi(
                f"ArthurMask'te henüz dosya seçilmedi. Avukattan ArthurMask'i açıp ({self.arayuz_adresi}) "
                "bir dosya seçmesini ve belgeyi bırakmasını isteyin."
            )
        return klasor

    # -- belge işleme (arayüz) -----------------------------------------------------------
    def arayuz_belge_isle(self, klasor: str, dosya_adi: str, veri: bytes) -> Dict:
        uzanti = Path(dosya_adi).suffix.lower()
        if uzanti not in belgeler.DESTEKLENEN:
            raise IslemHatasi(f"Desteklenmeyen biçim: {uzanti or 'uzantısız'} ({', '.join(belgeler.DESTEKLENEN)})")
        # Özgün yalnız ayrıştırma süresince, kullanıcıya özel geçici klasörde durur.
        with tempfile.TemporaryDirectory(prefix="arthurmask-") as gecici:
            yol = Path(gecici) / f"girdi{uzanti}"
            yol.write_bytes(veri)
            try:
                belge = belgeler.ac(yol)
            except belgeler.BelgeHatasi as hata:
                raise IslemHatasi(str(hata)) from hata

            belge_id = self.depo.yeni_belge_id(klasor)
            with self.depo.kasa(klasor) as kasa:
                motor = self.motor()
                motor.sozluk = self.depo.sozluk(klasor)
                sonuc = maskele_belge(belge, motor, kasa)
            kopya = self.depo.maskeli_kopya_yolu(klasor, belge_id, belge.cikti_uzantisi)
            belge.yaz(sonuc.degisiklikler, kopya)
            # Onay sonrası yeniden yazım için belge yazıcısı ayrıştırılmış hâlde bellekte kalır;
            # geçici dosyanın silinmesi yazıcıyı etkilemez (UDF/DOCX içerikleri belleğe okundu).

        # Artık tarama izleri de avukatın tek tıkla karar vereceği adaylara dönüşür.
        from .motor import artik_adaylari

        supheli = list(sonuc.supheli) + artik_adaylari(belge.metin, list(sonuc.bulgular) + list(sonuc.supheli))
        if sonuc.kirmizi:
            durum = DURUM_KIRMIZI
        elif supheli or sonuc.artik or belge.ocr:  # OCR belgesi her zaman incelenir
            durum = DURUM_ONAY
        else:
            durum = DURUM_HAZIR

        kayit = {
            "id": belge_id,
            "kaynak_ad": dosya_adi,
            "olusturma": simdi(),
            "durum": durum,
            "bicim": uzanti,
            "karakter": len(belge.metin),
            "ozet": hashlib.sha256(belge.metin.encode("utf-8")).hexdigest(),
            "maskeli_metin": sonuc.maskeli_metin,
            "etiket_sayisi": sonuc.etiket_sayisi,
            "turler": _etiket_turleri(sonuc.degisiklikler),
            "kirmizi_hat": [{"kategori": u.kategori, "satirlar": u.satirlar} for u in sonuc.kirmizi],
            "artik": [{"satir": s, "aciklama": a} for s, a in sonuc.artik],
            "uyarilar": belge.uyarilar,
            "supheli_sayisi": len(supheli),
            "ocr": belge.ocr,
            "maskeli_kopya": f"{belge_id}{belge.cikti_uzantisi}",
        }
        self._tutarlilik_hazirla(klasor, kayit, belge, sonuc.bulgular, sonuc.degisiklikler)
        self.depo.belge_kaydet(klasor, kayit)
        if durum != DURUM_HAZIR:
            self._bekleyen[(klasor, belge_id)] = (belge, list(sonuc.bulgular), supheli)
        return self._arayuz_belge(klasor, kayit)

    def _arayuz_belge(self, klasor: str, kayit: Dict) -> Dict:
        """Arayüz görünümü: şüpheli adaylar gerçek metinleriyle (yalnız yerel) eklenir."""
        gorunum = dict(kayit)
        bekleyen = self._bekleyen.get((klasor, kayit["id"]))
        gorunum["supheli"] = [
            {"sira": i, "tur": b.tur, "skor": b.skor, "metin": b.metin,
             "baglam": bekleyen[0].metin[max(0, b.bas - 50):b.son + 50]}
            for i, b in enumerate(bekleyen[2])
        ] if bekleyen else []
        # Yalnız avukatın aday seçmesi gereken belgelerde: aday yoksa onay yeniden maskeleme gerektirmez.
        gorunum["yeniden_yukleme_gerekli"] = (
            kayit["durum"] != DURUM_HAZIR and not bekleyen and kayit.get("supheli_sayisi", 0) > 0
        )
        return gorunum

    def arayuz_belgeler(self, klasor: str) -> List[Dict]:
        return [self._arayuz_belge(klasor, k) for k in self.depo.belgeler(klasor)]

    def arayuz_belge_onayla(self, klasor: str, belge_id: str, maskelenecek: List[int],
                            birakilacak: List[int], gerekce: str = "") -> Dict:
        kayit = self.depo.belge_oku(klasor, belge_id)
        if kayit["kirmizi_hat"] and not gerekce.strip():
            raise IslemHatasi("Kırmızı hat içeren belge gerekçe yazılmadan Claude'a verilemez.")
        bekleyen = self._bekleyen.get((klasor, belge_id))
        # Şüpheli adaylar yalnız bellekte durur; uygulama yeniden başladıysa avukat onları görmeden onaylayamaz,
        # yoksa incelenmemiş adlar maskesiz Claude'a gider.
        if not bekleyen and (maskelenecek or (kayit["durum"] != DURUM_HAZIR and kayit.get("supheli_sayisi", 0) > 0)):
            raise IslemHatasi("Onay bilgisi bu oturumda yok (uygulama yeniden başlamış). Belgeyi yeniden yükleyin.")

        if bekleyen:
            belge, bulgular, supheli = bekleyen
            secilen = [replace(supheli[i], skor=1.0, kaynak="avukat onayı") for i in maskelenecek if 0 <= i < len(supheli)]
            if secilen:
                with self.depo.kasa(klasor) as kasa:
                    tum = sorted(bulgular + secilen, key=lambda b: b.bas)
                    maskeli, degisiklikler = maskele(belge.metin, tum, kasa)
                kopya = self.depo.maskeli_kopya_yolu(klasor, belge_id, belge.cikti_uzantisi)
                belge.yaz(degisiklikler, kopya)
                kayit["maskeli_metin"] = maskeli
                kayit["etiket_sayisi"] = len({d[2] for d in degisiklikler})
                kayit["turler"] = _etiket_turleri(degisiklikler)
                from .motor import artik_tarama

                kayit["artik"] = [{"satir": s, "aciklama": a} for s, a in artik_tarama(maskeli)]
                # Avukatın seçtiği adaylar da maskelendi: Claude'a gidecek tutarlılık raporu yeniden yazılır.
                self._tutarlilik_hazirla(klasor, kayit, belge, tum, degisiklikler)
            # Kararlar dosya sözlüğüne yazılır; aynı soru bu dosyada bir daha sorulmaz.
            self.depo.sozluge_ekle(
                klasor,
                maskele=[{"deger": supheli[i].metin, "tur": supheli[i].tur} for i in maskelenecek if 0 <= i < len(supheli)],
                maskeleme=[supheli[i].metin for i in birakilacak if 0 <= i < len(supheli)],
            )

        if kayit["kirmizi_hat"]:
            self.depo.kirmizi_hat_kaydet(klasor, {
                "belge": belge_id, "ozet": kayit["ozet"],
                "kategoriler": [k["kategori"] for k in kayit["kirmizi_hat"]], "gerekce": gerekce.strip(),
            })
        kayit["durum"] = DURUM_HAZIR
        kayit["onay_zamani"] = simdi()
        self.depo.belge_kaydet(klasor, kayit)
        self._bekleyen.pop((klasor, belge_id), None)
        return self._arayuz_belge(klasor, kayit)

    # -- iç tutarlılık denetimi ------------------------------------------------------------------------
    def _tutarlilik_hazirla(self, klasor: str, kayit: Dict, belge: "belgeler.Belge", bulgular, degisiklikler) -> None:
        """Denetim gerçek metinde bir kez yapılır. Tam rapor (gerçek değerli) şifreli olarak belgenin yanına,
        maskeli rapor (Claude'a gidecek) belge kaydına yazılır. Maskeli rapordaki her parça, belgenin maskelenmesindeki
        değişikliklerle konumdan üretilir."""
        try:
            if belge.ham is not None:
                paragraflar = tutarlilik.docx_paragraflari(belge.ham)
            else:
                paragraflar = tutarlilik.duz_paragraflar(belge.metin)
            sonuc = tutarlilik.denetle(paragraflar, [(b.bas, b.son, b.varlik) for b in bulgular])
            tam = tutarlilik.rapor_yaz(sonuc, paragraflar, tutarlilik.gercek_metin(paragraflar))
            maskeli = tutarlilik.rapor_yaz(sonuc, paragraflar,
                                           tutarlilik.maskeli_metin(paragraflar, belge.metin, degisiklikler))
            self.depo.gizli_kaydet(klasor, f"{kayit['id']}.tutarlilik", {"olusturma": simdi(), **tam})
        except Exception as hata:  # noqa: BLE001 - denetim maskelemeyi durdurmaz; istisna metni belge içerebilir
            gunluk.error("Tutarlılık denetimi yapılamadı (%s).", type(hata).__name__)
            kayit["tutarlilik"] = {"hata": "Tutarlılık denetimi bu belgede yapılamadı."}
            return
        kayit["tutarlilik"] = maskeli

    def arayuz_tutarlilik(self, klasor: str, belge_id: str) -> Dict:
        """Tam rapor (gerçek değerlerle), yalnız yerel arayüze."""
        kayit = self.depo.belge_oku(klasor, belge_id)
        try:
            rapor = self.depo.gizli_oku(klasor, f"{belge_id}.tutarlilik")
        except FileNotFoundError:
            raise IslemHatasi("Bu belgenin tutarlılık raporu yok: belge bu özellikten önce yüklenmiş ya da süresi "
                              "dolmuş. Belgeyi silip yeniden bırakın.")
        return {"belge": belge_id, "kaynak_ad": kayit["kaynak_ad"], **rapor}

    def mcp_tutarlilik(self, kimlik: str, parca: int = 1) -> Dict:
        klasor = self._aktif()
        kayit = self._hazir_kayit(klasor, kimlik)
        rapor = kayit.get("tutarlilik")
        if not rapor:
            raise IslemHatasi(f"{kimlik} tutarlılık denetimi eklenmeden önce yüklenmiş. Avukattan belgeyi ArthurMask'e "
                              f"({self.arayuz_adresi}) yeniden bırakmasını isteyin.")
        if "hata" in rapor:
            raise IslemHatasi(rapor["hata"])
        sayfalar = sayfala(rapor["bulgular"])
        if not 1 <= parca <= len(sayfalar):
            raise IslemHatasi(f"Parça 1–{len(sayfalar)} arasında olmalı.")
        return {
            "kimlik": kimlik,
            "ozet": rapor["ozet"],
            "denetlenen": rapor["denetlenen"],
            "parca": parca,
            "parca_sayisi": len(sayfalar),
            "bulgular": sayfalar[parca - 1],
            "notlar": rapor["notlar"],
            "not": ("Bulgular kurallarla, yerelde bulundu; yanlış alarm olabilir. Avukat aynı raporu gerçek adlarla "
                    "ArthurMask'te görüyor. Önem sırasına göre yorumla; atıf ve tutar bulgularını belge metniyle "
                    "(arthur_mask_belge_getir) teyit et."),
            "kural": "{{TÜR-NN}} etiketlerini harfi harfine koru; gerçek değeri tahmin etme.",
        }

    # -- sürüm karşılaştırması --------------------------------------------------------------------------
    def arayuz_karsilastir(self, klasor: str, ozgun_adi: str, ozgun: bytes, yeni_adi: str, yeni: bytes) -> Dict:
        """Avukatın özgün belgesi ile karşı tarafın yeni sürümü: gerçek metinle izli Word (yerelde), iki belge de
        normal maskeleme akışından geçer; Claude'a giden özet sonradan maskeli kopyalardan üretilir."""
        for ad in (ozgun_adi, yeni_adi):
            if Path(ad).suffix.lower() != ".docx":
                raise IslemHatasi("Sürüm karşılaştırması yalnız Word (.docx) belgelerinde yapılır.")
        try:
            izli, sayim, uyarilar = surum.izli_karsilastirma(ozgun, yeni)
        except surum.SurumHatasi as hata:
            raise IslemHatasi(str(hata)) from hata
        kayit_ozgun = self.arayuz_belge_isle(klasor, ozgun_adi, ozgun)
        kayit_yeni = self.arayuz_belge_isle(klasor, yeni_adi, yeni)
        baslik = f"Sürüm karşılaştırması {kayit_ozgun['id']} - {kayit_yeni['id']}"
        hedef = self.depo.cevap_yolu(klasor, baslik, ".docx")
        hedef.write_bytes(izli)
        meta = {
            "olusturma": simdi(), "baslik": baslik, "bicim": "docx", "dosya": hedef.name, "tur": "karsilastirma",
            "izli": True, "ozgun": kayit_ozgun["id"], "yeni": kayit_yeni["id"], "sayim": sayim, "uyarilar": uyarilar,
            "cozulen": 0, "bilinmeyen": [],
            "maskeli_metin": f"{kayit_ozgun['id']} (özgün) ile {kayit_yeni['id']} (yeni sürüm) karşılaştırıldı: "
                             f"{_sayim_metni(sayim)}.",
        }
        self.depo.cevap_kaydet(klasor, meta, hedef)
        for kayit, rol, karsi in ((kayit_ozgun, "özgün", kayit_yeni), (kayit_yeni, "yeni", kayit_ozgun)):
            guncel = self.depo.belge_oku(klasor, kayit["id"])
            guncel["surum"] = {"rol": rol, "karsi": karsi["id"]}
            self.depo.belge_kaydet(klasor, guncel)
        gorunumler = [self._arayuz_belge(klasor, self.depo.belge_oku(klasor, k["id"])) for k in (kayit_ozgun, kayit_yeni)]
        return {
            "ozgun": gorunumler[0], "yeni": gorunumler[1], "cevap": {**meta, "ad": hedef.stem},
            "ozet": _sayim_metni(sayim), "uyarilar": uyarilar,
            "hazir": all(g["durum"] == DURUM_HAZIR for g in gorunumler),
        }

    def _hazir_kayit(self, klasor: str, kimlik: str) -> Dict:
        try:
            kayit = self.depo.belge_oku(klasor, kimlik)
        except (FileNotFoundError, OSError):
            raise IslemHatasi(f"Belge bulunamadı: {kimlik}")
        if kayit["durum"] != DURUM_HAZIR:
            raise IslemHatasi(
                f"{kimlik} henüz Claude'a hazır değil (durum: {kayit['durum']}). "
                f"Avukatın ArthurMask'te ({self.arayuz_adresi}#belge={kimlik}) incelemeyi tamamlaması gerekir."
            )
        return kayit

    def _karsilastirmalar(self, klasor: str) -> List[Dict]:
        return [c for c in self.depo.cevaplar(klasor) if c.get("tur") == "karsilastirma"]

    def mcp_surum_karsilastir(self, ozgun: str = "", yeni: str = "", parca: int = 1) -> Dict:
        klasor = self._aktif()
        karsilastirmalar = self._karsilastirmalar(klasor)
        if not ozgun or not yeni:
            if not karsilastirmalar:
                raise IslemHatasi(
                    "Bu dosyada sürüm karşılaştırması yok. Avukattan ArthurMask'te 'Sürüm karşılaştır' alanına özgün "
                    "belgeyi ve karşı tarafın yeni sürümünü bırakmasını isteyin; ya da iki Word belgesinin kimliğini "
                    "(arthur_mask_belgeler) ozgun ve yeni olarak verin.")
            ozgun, yeni = ozgun or karsilastirmalar[0]["ozgun"], yeni or karsilastirmalar[0]["yeni"]
        if ozgun == yeni:
            raise IslemHatasi("Özgün ve yeni sürüm aynı belge olamaz.")
        kopyalar = []
        for kimlik in (ozgun, yeni):
            kayit = self._hazir_kayit(klasor, kimlik)
            if kayit["bicim"] != ".docx":
                raise IslemHatasi(f"{kimlik} Word belgesi değil; sürüm karşılaştırması yalnız .docx belgelerinde yapılır.")
            kopya = self.depo.dosya_yolu(klasor) / "maskeli" / kayit.get("maskeli_kopya", "")
            if not kayit.get("maskeli_kopya") or not kopya.is_file():
                raise IslemHatasi(f"{kimlik} maskeli kopyasının süresi dolmuş; avukattan belgeyi yeniden bırakmasını isteyin.")
            kopyalar.append(surum.girdiler(kopya.read_bytes(), kimlik))
        denetim = self._cikis_denetimi(klasor)
        try:
            ozet = surum.degisiklik_ozeti(kopyalar[0], kopyalar[1], lambda m: denetim.temizle(m)[0])
        except surum.SurumHatasi as hata:
            raise IslemHatasi(str(hata)) from hata
        sayfalar = sayfala(ozet["degisiklikler"])
        if not 1 <= parca <= len(sayfalar):
            raise IslemHatasi(f"Parça 1–{len(sayfalar)} arasında olmalı.")
        izli = next((c for c in karsilastirmalar if c.get("ozgun") == ozgun and c.get("yeni") == yeni), None)
        return {
            "ozgun": ozgun,
            "yeni": yeni,
            "ozet": _sayim_metni(ozet["sayim"]),
            "parca": parca,
            "parca_sayisi": len(sayfalar),
            "degisiklikler": sayfalar[parca - 1],
            "isaretleme": "'fark' alanında [-silinen-] ve {+eklenen+}. '(özgünde)' yer bilgisi özgün sürümdeki yerdir.",
            "izli_word": ("Avukatın bilgisayarında izli değişiklikli Word dosyası hazır (ArthurMask › Cevaplar)."
                          if izli else
                          "Bu iki belge için izli Word dosyası yok; avukat iki sürümü ArthurMask'teki 'Sürüm karşılaştır' "
                          "alanına birlikte bırakırsa oluşur."),
            "sonraki_adim": (
                "Değişikliklerin risk yorumunu ve karşı öneriyi bu özete göre yaz; avukata arthur_mask_teslim ile teslim et. "
                f"Karşı öneriyi yeni sürüme izli değişiklik olarak işlemek için arthur_mask_belgeyi_revize_et'i "
                f"kimlik='{yeni}' ile kullan."),
            "kural": "{{TÜR-NN}} etiketlerini harfi harfine koru; gerçek değeri tahmin etme.",
        }

    def arayuz_belge_sil(self, klasor: str, belge_id: str) -> None:
        self.depo.belge_oku(klasor, belge_id)
        for yol in (self.depo.dosya_yolu(klasor) / "maskeli").glob(f"{belge_id}.*"):
            yol.unlink()
        self._bekleyen.pop((klasor, belge_id), None)

    def arayuz_cevaplar(self, klasor: str) -> List[Dict]:
        kasa = self.depo.kasa_oku(klasor)
        cevaplar = []
        for meta in self.depo.cevaplar(klasor):
            acik, _, _ = geri_ac_metin(meta["maskeli_metin"], kasa)
            cevaplar.append({**meta, "acik_metin": acik})
        return cevaplar

    def arayuz_coz(self, metin: str, klasor: Optional[str] = None) -> Dict:
        """Salt çözücü eklenti ve arayüzdeki 'Claude'daki hâli' görünümü için: etiketleri gerçek değerle gösterir."""
        kasa = self.depo.kasa_oku(klasor or self._aktif())
        acik, degisiklikler, bilinmeyen = geri_ac_metin(metin, kasa)
        return {"metin": acik, "cozulen": len(degisiklikler), "bilinmeyen": bilinmeyen}

    # -- çıkış kapısı ---------------------------------------------------------------------------
    def _cikis_denetimi(self, klasor: str) -> CikisDenetimi:
        kasa_yolu = self.depo.dosya_yolu(klasor) / "dosya.kasa"
        damga = kasa_yolu.stat().st_mtime_ns if kasa_yolu.exists() else 0
        onbellek = self._denetim.get(klasor)
        if not onbellek or onbellek[0] != damga:
            onbellek = (damga, CikisDenetimi(self.depo.kasa_oku(klasor)))
            self._denetim[klasor] = onbellek
        return onbellek[1]

    def mcp_cikis(self, arac: str, yanit: Dict, klasor: Optional[str] = None) -> Dict:
        """Claude'a giden her yanıtın son kapısı: kasadaki gerçek değerler etiketine çevrilir ve
        gönderilen yanıt yerel 'Claude'a gidenler' kaydına yazılır (yalnız maskeli içerik).

        `klasor`, çağrı başladığında etkin olan dosyadır. Avukat çağrı sürerken etkin dosyayı değiştirdiyse yanıt
        iki dosyanın kasasına karşı da taranır: hangisinden üretildiyse onun değerleri kaçmaz."""
        klasorler = []
        for aday in dict.fromkeys((klasor, self.depo.aktif_dosya)):
            try:
                if aday:
                    klasorler.append((aday, self._cikis_denetimi(aday)))
            except FileNotFoundError:
                continue
        if not klasorler:
            return yanit
        temiz, yakalanan, turler = yanit, 0, {}
        for _, denetim in klasorler:
            temiz, sonuc = denetim.yanit_temizle(temiz)
            yakalanan += sonuc.yakalanan
            for tur, adet in sonuc.turler.items():
                turler[tur] = turler.get(tur, 0) + adet
        if yakalanan:
            gunluk.warning("Çıkış kapısı %s yanıtında %s değer yakaladı (%s).", arac, yakalanan, turler)
        self.depo.giden_kaydet(klasorler[0][0], {
            "zaman": simdi(), "arac": arac, "yakalanan": yakalanan, "turler": turler, "yanit": temiz,
        })
        return temiz

    def arayuz_denetle(self, klasor: str) -> Dict:
        """Sızıntı denetimi (yalnız yerel): Claude'a verilen ya da Claude'dan dönen her metin, kasadaki
        bütün gerçek değerlere karşı yeniden taranır. Sonradan kasaya giren bir ad, daha önce giden
        bir metinde açık kalmışsa burada görünür."""
        denetim = CikisDenetimi(self.depo.kasa_oku(klasor))
        kaynaklar = []
        for kayit in self.depo.belgeler(klasor):
            if kayit["durum"] != DURUM_HAZIR:
                continue
            kaynaklar.append((f"{kayit['id']} · maskeli metin (çıkış kapısından önce)", kayit["maskeli_metin"]))
            kopya = self.depo.dosya_yolu(klasor) / "maskeli" / kayit.get("maskeli_kopya", "")
            if kayit["bicim"] == ".docx" and kayit.get("maskeli_kopya") and kopya.is_file():
                kaynaklar.append((f"{kayit['id']} · Word görünümü (çıkış kapısından önce)", docx_yapi.claude_gorunumu(kopya)))
        for giden in self.depo.gidenler(klasor, en_fazla=10_000):
            kaynaklar.append((f"Claude'a giden yanıt · {giden['arac']} · {giden['zaman']}",
                              json.dumps(giden.get("yanit"), ensure_ascii=False)))
        for cevap in self.depo.cevaplar(klasor):
            kaynaklar.append((f"Claude'un yazdığı metin · {cevap['baslik']}", cevap.get("maskeli_metin", "")))

        bulgular = []
        for ad, metin in kaynaklar:
            _, bulunan = denetim.tara(metin)
            if bulunan:
                ozet = Counter((tur, etiket, deger) for tur, etiket, deger in bulunan)
                bulgular.append({"kaynak": ad, "eslesmeler": [
                    {"tur": t, "etiket": e, "deger": d, "adet": n} for (t, e, d), n in ozet.most_common()
                ]})
        kasa = self.depo.kasa_oku(klasor)
        return {
            "zaman": simdi(),
            "taranan_kaynak": len(kaynaklar),
            "kasadaki_deger": sum(len(k.degerler) for k in kasa.kayitlar.values()),
            "temiz": not bulgular,
            "bulgular": bulgular,
            "gunluk_var": bool(self.depo.gidenler(klasor, en_fazla=1)),
        }

    def arayuz_gidenler(self, klasor: str) -> Dict:
        kayitlar = []
        for k in self.depo.gidenler(klasor, en_fazla=100):
            yanit = k.get("yanit")
            metin = yanit.get("metin") if isinstance(yanit, dict) and isinstance(yanit.get("metin"), str) else None
            if metin is None:
                metin = json.dumps(yanit, ensure_ascii=False, indent=1)
            kayitlar.append({"zaman": k["zaman"], "arac": k["arac"], "yakalanan": k.get("yakalanan", 0),
                             "turler": k.get("turler", {}), "metin": metin})
        return {
            "kayitlar": kayitlar,
            "toplam_yanit": len(kayitlar),
            "toplam_yakalanan": sum(k.get("yakalanan", 0) for k in kayitlar),
        }

    # -- MCP (Claude'a giden her şey maskeli) ------------------------------------------------
    def mcp_belgeler(self) -> Dict:
        klasor = self._aktif()
        liste = []
        for k in self.depo.belgeler(klasor):
            oge = {
                "kimlik": k["id"], "durum": k["durum"], "bicim": k["bicim"], "karakter": k["karakter"],
                "etiket_sayisi": k["etiket_sayisi"], "turler": k["turler"],
                "parca_sayisi": len(parcalara_bol(k["maskeli_metin"])),
                "hazirlanma": k["olusturma"],
            }
            rapor = k.get("tutarlilik")
            if rapor and "ozet" in rapor:
                oge["tutarlilik_bulgusu"] = rapor["ozet"]["toplam"]
            if k.get("surum"):
                oge["surum"] = k["surum"]
            liste.append(oge)
        return {
            "belgeler": liste,
            "karsilastirmalar": [{"ozgun": c["ozgun"], "yeni": c["yeni"], "hazirlanma": c["olusturma"]}
                                 for c in self._karsilastirmalar(klasor)],
            "not": "Yalnız durum='hazir' olan belgeler getirilebilir.",
            "arayuz": self.arayuz_adresi,
        }

    def mcp_belge_getir(self, kimlik: str, parca: int = 1) -> Dict:
        klasor = self._aktif()
        try:
            kayit = self.depo.belge_oku(klasor, kimlik)
        except (FileNotFoundError, OSError):
            raise IslemHatasi(f"Belge bulunamadı: {kimlik}")
        if kayit["durum"] != DURUM_HAZIR:
            raise IslemHatasi(
                f"{kimlik} henüz Claude'a hazır değil (durum: {kayit['durum']}). "
                f"Avukatın ArthurMask'te ({self.arayuz_adresi}#belge={kimlik}) incelemeyi tamamlaması gerekir."
            )
        metin, yapi = kayit["maskeli_metin"], "düz metin"
        kopya = self.depo.dosya_yolu(klasor) / "maskeli" / kayit.get("maskeli_kopya", "")
        if kayit["bicim"] == ".docx" and kayit.get("maskeli_kopya") and kopya.is_file():
            # Word yapısı (tablolar, çift sütun, başlıklar) Markdown olarak korunur.
            metin, yapi = docx_yapi.claude_gorunumu(kopya), "markdown (Word tabloları | ... | olarak)"
        parcalar = parcalara_bol(metin, korunan=self._cikis_denetimi(klasor).araliklar(metin))
        if not 1 <= parca <= len(parcalar):
            raise IslemHatasi(f"Parça 1–{len(parcalar)} arasında olmalı.")
        return {
            "kimlik": kimlik,
            "parca": parca,
            "parca_sayisi": len(parcalar),
            "etiket_turleri": kayit["turler"],
            "yapi": yapi,
            "revize_edilebilir": kayit["bicim"] in (".docx", ".udf"),
            "kural": "{{TÜR-NN}} etiketlerini harfi harfine koru; ek için kesme işareti kullan; gerçek değeri tahmin etme.",
            "metin": parcalar[parca - 1],
        }

    def mcp_revize(self, kimlik: str, degisiklikler: List[Dict], baslik: str = "revizyon", izli: bool = True) -> Dict:
        """Claude'un değişikliklerini avukatın yüklediği belgenin kendisine (düzeni koruyarak) işler."""
        klasor = self._aktif()
        try:
            kayit = self.depo.belge_oku(klasor, kimlik)
        except (FileNotFoundError, OSError):
            raise IslemHatasi(f"Belge bulunamadı: {kimlik}")
        if kayit["durum"] != DURUM_HAZIR:
            raise IslemHatasi(f"{kimlik} henüz Claude'a hazır değil (durum: {kayit['durum']}).")
        if kayit["bicim"] not in (".docx", ".udf"):
            raise IslemHatasi("Revizyon yalnız Word (.docx) ve UDF belgelerinde yapılabilir; yeni belge için arthur_mask_teslim kullanın.")
        if not degisiklikler:
            raise IslemHatasi("En az bir {eski, yeni} değişikliği gerekir.")
        kopya = self.depo.dosya_yolu(klasor) / "maskeli" / kayit.get("maskeli_kopya", "")
        if not kayit.get("maskeli_kopya") or not kopya.is_file():
            raise IslemHatasi("Maskeli kopyanın süresi dolmuş; avukattan belgeyi ArthurMask'e yeniden bırakmasını isteyin.")

        kasa = self.depo.kasa_oku(klasor)
        guvenli_baslik = ETIKET_DESENI.sub(lambda m: m.group(1), baslik)
        hedef = self.depo.cevap_yolu(klasor, guvenli_baslik, kayit["bicim"])
        with tempfile.TemporaryDirectory(prefix="arthurmask-") as gecici:
            ara = Path(gecici) / f"revizyon{kayit['bicim']}"
            if kayit["bicim"] == ".docx":
                rapor = docx_yapi.revizyon_uygula(kopya, degisiklikler, ara, izli=izli)
                ara_belge = docx.oku(ara)
                cozum, bilinmeyen = geri_acma_degisiklikleri(ara_belge.metin, kasa)
                # Avukata giden çözülmüş taslak: üstveri temizliği maskeli kopyada yapıldı; burada yeniden yapılırsa
                # Claude'un izli değişikliklerindeki yazar adı da silinirdi.
                docx.maskelenmis_yaz(ara_belge, cozum, hedef, ustveri_temizle=False)
            else:
                rapor = docx_yapi.RevizyonRaporu()
                kaynak = udf.oku(kopya)
                araliklar = []
                for sira, d in enumerate(degisiklikler, start=1):
                    eski, yeni = str(d.get("eski", "")), str(d.get("yeni", ""))
                    konumlar = [i for i in range(len(kaynak.metin)) if eski and kaynak.metin.startswith(eski, i)]
                    if len(konumlar) != 1:
                        rapor.sorunlar.append({"sira": str(sira), "neden": "eski metin bulunamadı ya da birden çok yerde geçiyor"})
                        continue
                    araliklar.append((konumlar[0], konumlar[0] + len(eski), yeni))
                    rapor.uygulanan += 1
                udf.maskelenmis_yaz(kaynak, araliklar, ara)
                ara_belge = udf.oku(ara)
                cozum, bilinmeyen = geri_acma_degisiklikleri(ara_belge.metin, kasa)
                udf.maskelenmis_yaz(ara_belge, cozum, hedef)

        ozet = "\n\n".join(
            f"{i}. − {d.get('eski', '')}\n   + {d.get('yeni', '')}" for i, d in enumerate(degisiklikler, start=1)
        )
        izli_mi = bool(izli and kayit["bicim"] == ".docx")
        self.depo.cevap_kaydet(klasor, {
            "olusturma": simdi(), "baslik": guvenli_baslik, "bicim": kayit["bicim"].lstrip("."), "dosya": hedef.name,
            "tur": "revizyon", "izli": izli_mi, "kaynak_belge": kimlik,
            "uygulanan": rapor.uygulanan, "sorunlar": rapor.sorunlar,
            "cozulen": len(cozum), "bilinmeyen": bilinmeyen, "maskeli_metin": ozet,
        }, hedef)
        return {
            "durum": "revizyon teslim edildi",
            "dosya": hedef.name,
            "uygulanan_degisiklik": rapor.uygulanan,
            "uygulanamayan": rapor.sorunlar,
            "izli_degisiklik": izli_mi,
            "not": "Özgün düzen (tablolar, çift sütun, biçim) korundu; gerçek değerler bu yanıta eklenmez.",
        }

    def mcp_teslim(self, metin: str, bicim: str = "docx", baslik: str = "cevap") -> Dict:
        klasor = self._aktif()
        if bicim not in TESLIM_BICIMLERI:
            raise IslemHatasi(f"Biçim şunlardan biri olmalı: {', '.join(TESLIM_BICIMLERI)}")
        kasa = self.depo.kasa_oku(klasor)
        acik, degisiklikler, bilinmeyen = geri_ac_metin(metin, kasa)
        # Dosya adı Claude'un verdiği (maskeli) başlıktan üretilir; gerçek değer içermez.
        guvenli_baslik = ETIKET_DESENI.sub(lambda m: m.group(1), baslik)
        yol = self.depo.cevap_yolu(klasor, guvenli_baslik, TESLIM_BICIMLERI[bicim])
        belgeler.metinden_yaz(acik, yol)
        self.depo.cevap_kaydet(klasor, {
            "olusturma": simdi(), "baslik": guvenli_baslik, "bicim": bicim, "dosya": yol.name,
            "cozulen": len(degisiklikler), "bilinmeyen": bilinmeyen, "maskeli_metin": metin,
        }, yol)
        return {
            "durum": "teslim edildi",
            "dosya": yol.name,
            "cozulen_etiket": len(degisiklikler),
            "kasada_olmayan_etiketler": bilinmeyen,
            "not": "Çözülmüş taslak avukatın cihazında açıldı; gerçek değerler bu yanıta eklenmez.",
        }

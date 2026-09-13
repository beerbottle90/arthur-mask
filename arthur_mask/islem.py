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
from typing import Dict, List, Optional

from . import belgeler, docx, docx_yapi, udf
from .cikis import CikisDenetimi
from .depo import Depo, simdi
from .maskeleyici import ETIKET_DESENI, geri_acma_degisiklikleri, maskele
from .motor import Bulgu, MaskeMotoru, artik_adaylari, artik_tarama
from .servis import geri_ac_metin, maskele_belge

gunluk = logging.getLogger("arthur_mask")

MCP_PARCA_KARAKTER = 30_000
DURUM_HAZIR, DURUM_ONAY, DURUM_KIRMIZI = "hazir", "onay_bekliyor", "kirmizi_hat"
TESLIM_BICIMLERI = {"docx": ".docx", "udf": ".udf", "txt": ".txt"}


class IslemHatasi(Exception):
    pass


def _etiket_turleri(degisiklikler) -> Dict[str, int]:
    """Tür başına benzersiz etiket sayısı ({{KİŞİ-01}} üç kez geçse de 1 kişi)."""
    etiketler = {d[2] for d in degisiklikler}
    return dict(Counter(e[2:-2].rsplit("-", 1)[0] for e in etiketler))


class Islem:
    def __init__(self, depo: Depo, semantik: Optional[bool] = None):
        self.depo = depo
        self._semantik = semantik
        self._motor: Optional[MaskeMotoru] = None
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

    def motor(self) -> MaskeMotoru:
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
                f"Arthur Mask'te henüz dosya seçilmedi. Avukattan Arthur Mask'i açıp ({self.arayuz_adresi}) "
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
        if maskelenecek and not bekleyen:
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
                kayit["artik"] = [{"satir": s, "aciklama": a} for s, a in artik_tarama(maskeli)]
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
        """Salt çözücü eklenti ve 'Maskeli görünüm' için: etiketleri gerçek değerle gösterir."""
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

    def mcp_cikis(self, arac: str, yanit: Dict) -> Dict:
        """Claude'a giden her yanıtın son kapısı: kasadaki gerçek değerler etiketine çevrilir ve
        gönderilen yanıt yerel 'Claude'a gidenler' kaydına yazılır (yalnız maskeli içerik)."""
        klasor = self.depo.aktif_dosya
        if not klasor:
            return yanit
        temiz, sonuc = self._cikis_denetimi(klasor).yanit_temizle(yanit)
        if sonuc.yakalanan:
            gunluk.warning("Çıkış kapısı %s yanıtında %s değer yakaladı (%s).", arac, sonuc.yakalanan, sonuc.turler)
        self.depo.giden_kaydet(klasor, {
            "zaman": simdi(), "arac": arac, "yakalanan": sonuc.yakalanan, "turler": sonuc.turler, "yanit": temiz,
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
            liste.append({
                "kimlik": k["id"], "durum": k["durum"], "bicim": k["bicim"], "karakter": k["karakter"],
                "etiket_sayisi": k["etiket_sayisi"], "turler": k["turler"],
                "parca_sayisi": max(1, -(-len(k["maskeli_metin"]) // MCP_PARCA_KARAKTER)),
                "hazirlanma": k["olusturma"],
            })
        return {
            "belgeler": liste,
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
                f"Avukatın Arthur Mask'te ({self.arayuz_adresi}#belge={kimlik}) incelemeyi tamamlaması gerekir."
            )
        metin, yapi = kayit["maskeli_metin"], "düz metin"
        kopya = self.depo.dosya_yolu(klasor) / "maskeli" / kayit.get("maskeli_kopya", "")
        if kayit["bicim"] == ".docx" and kayit.get("maskeli_kopya") and kopya.is_file():
            # Word yapısı (tablolar, çift sütun, başlıklar) Markdown olarak korunur.
            metin, yapi = docx_yapi.claude_gorunumu(kopya), "markdown (Word tabloları | ... | olarak)"
        parca_sayisi = max(1, -(-len(metin) // MCP_PARCA_KARAKTER))
        if not 1 <= parca <= parca_sayisi:
            raise IslemHatasi(f"Parça 1–{parca_sayisi} arasında olmalı.")
        bas = (parca - 1) * MCP_PARCA_KARAKTER
        return {
            "kimlik": kimlik,
            "parca": parca,
            "parca_sayisi": parca_sayisi,
            "etiket_turleri": kayit["turler"],
            "yapi": yapi,
            "revize_edilebilir": kayit["bicim"] in (".docx", ".udf"),
            "kural": "{{TÜR-NN}} etiketlerini harfi harfine koru; ek için kesme işareti kullan; gerçek değeri tahmin etme.",
            "metin": metin[bas:bas + MCP_PARCA_KARAKTER],
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
            raise IslemHatasi("Maskeli kopyanın süresi dolmuş; avukattan belgeyi Arthur Mask'e yeniden bırakmasını isteyin.")

        kasa = self.depo.kasa_oku(klasor)
        guvenli_baslik = ETIKET_DESENI.sub(lambda m: m.group(1), baslik)
        hedef = self.depo.cevap_yolu(klasor, guvenli_baslik, kayit["bicim"])
        with tempfile.TemporaryDirectory(prefix="arthurmask-") as gecici:
            ara = Path(gecici) / f"revizyon{kayit['bicim']}"
            if kayit["bicim"] == ".docx":
                rapor = docx_yapi.revizyon_uygula(kopya, degisiklikler, ara, izli=izli)
                ara_belge = docx.oku(ara)
                cozum, bilinmeyen = geri_acma_degisiklikleri(ara_belge.metin, kasa)
                docx.maskelenmis_yaz(ara_belge, cozum, hedef)
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

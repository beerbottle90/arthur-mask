"""Claude Desktop köprüsü: tek süreçte MCP (stdio) + yerel arayüz (HTTP) + model ön yüklemesi.

Claude Desktop bu süreci başlatır ve kapatır (K11). Claude'a verilen araçlar yalnız
maskeli metin döndürür; çözme yerelde yapılır ve gerçek değer araç sonucuna eklenmez.
"""

import argparse
import logging
import os
import sys
import threading
from typing import Optional

from mcp.server.mcpserver import MCPServer

from . import __version__
from .anahtar import ana_anahtar, kurtarma_kodu
from .depo import Depo
from .islem import Islem, IslemHatasi
from .sunucu import VARSAYILAN_PORT, YerelSunucu

TALIMAT = (
    "Arthur Mask, avukatın cihazında maskelenmiş belgeleri verir. Kurallar:\n"
    "1) Belgeyi yalnız arthur_mask_belge_getir ile al; kullanıcıdan ham belge isteme.\n"
    "2) {{TÜR-NN}} biçimindeki maske etiketlerini (ör. {{KİŞİ-01}}) harfi harfine koru; "
    "ek getirirken kesme işareti kullan: {{KİŞİ-01}}'in.\n"
    "3) Etiketlerin gerçek değerini tahmin etmeye ya da yeniden kurmaya çalışma.\n"
    "4) İçtihat/mevzuat araştırma sorgularına etiket yazma.\n"
    "5) Avukatın yüklediği belgeyi düzeltmek/revize etmek için arthur_mask_belgeyi_revize_et kullan: değişiklikler "
    "özgün düzene (çift sütunlu tablolar, biçim) Word izli değişiklik olarak işlenir. Her değişiklikte 'eski' metni "
    "belgeden birebir ve tek paragraf/hücre içinden kopyala. Çift dilli belgede her iki dil sütununu da ayrı ayrı revize et.\n"
    "6) Yeni bir belge (görüş, cetvel, dilekçe) yazıyorsan arthur_mask_teslim kullan; Markdown tablo ve başlıklar "
    "Word'e tablo ve başlık olarak aktarılır. Kaynak belge çift dilliyse yeni belgeyi de aynı dillerde, iki sütunlu tabloyla yaz.\n"
    "7) Belge 'hazir' değilse avukattan Arthur Mask'te incelemeyi tamamlamasını iste."
)


def sunucu_olustur(islem: Islem) -> MCPServer:
    mcp = MCPServer(name="arthur-mask", title="Arthur Mask", version=__version__, instructions=TALIMAT)

    def _hata_sar(islev, *args, **kwargs):
        try:
            yanit = islev(*args, **kwargs)
        except IslemHatasi as hata:
            yanit = {"hata": str(hata)}
        # Her yanıt, hata iletileri dahil, Claude'a gitmeden önce çıkış kapısından geçer.
        return islem.mcp_cikis(islev.__name__, yanit)

    @mcp.tool(
        name="arthur_mask_belgeler",
        title="Maskeli belgeleri listele",
        description="Etkin dosyadaki maskelenmiş belgeleri listeler (kimlik, durum, etiket türleri). Gerçek değer içermez.",
    )
    def arthur_mask_belgeler() -> dict:
        return _hata_sar(islem.mcp_belgeler)

    @mcp.tool(
        name="arthur_mask_belge_getir",
        title="Maskeli belgeyi getir",
        description=(
            "Durumu 'hazir' olan maskeli belgenin metnini parça parça döndürür. "
            "Metindeki {{TÜR-NN}} etiketleri gerçek kişisel verinin yerini tutar ve aynen korunmalıdır."
        ),
    )
    def arthur_mask_belge_getir(kimlik: str, parca: int = 1) -> dict:
        return _hata_sar(islem.mcp_belge_getir, kimlik, parca)

    @mcp.tool(
        name="arthur_mask_belgeyi_revize_et",
        title="Yüklenen belgeyi düzeni koruyarak revize et",
        description=(
            "Avukatın yüklediği Word/UDF belgesine değişiklikleri işler; tablo, çift sütun ve biçim korunur. "
            "Word'de değişiklikler izli (kabul/ret edilebilir) olur. degisiklikler: [{'eski': belgedeki birebir metin "
            "(tek paragraf ya da hücre), 'yeni': yerine gelecek metin, 'hepsi': true ise her geçişte}]. "
            "Etiketleri ({{KİŞİ-01}}) koru. Yanıtta gerçek değer bulunmaz."
        ),
    )
    def arthur_mask_belgeyi_revize_et(kimlik: str, degisiklikler: list[dict], baslik: str = "revizyon", izli: bool = True) -> dict:
        return _hata_sar(islem.mcp_revize, kimlik, degisiklikler, baslik, izli)

    @mcp.tool(
        name="arthur_mask_teslim",
        title="Taslağı avukata teslim et",
        description=(
            "Etiketli nihai taslağı avukatın cihazına teslim eder; Arthur Mask etiketleri yerelde çözer ve "
            "Word (docx), UYAP (udf) ya da metin (txt) olarak kaydeder. Yanıtta gerçek değer bulunmaz."
        ),
    )
    def arthur_mask_teslim(metin: str, bicim: str = "docx", baslik: str = "cevap") -> dict:
        return _hata_sar(islem.mcp_teslim, metin, bicim, baslik)

    return mcp


def _gunluk_ayarla() -> None:
    from .anahtar import uygulama_klasoru

    yol = uygulama_klasoru() / "kopru.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(yol, encoding="utf-8"), logging.StreamHandler(sys.stderr)],
    )
    for gurultulu in ("presidio-analyzer", "presidio_analyzer", "transformers", "gliner", "httpx"):
        logging.getLogger(gurultulu).setLevel(logging.WARNING)


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(prog="arthur-mask-kopru")
    ap.add_argument("--port", type=int, default=int(os.environ.get("ARTHUR_MASK_PORT", VARSAYILAN_PORT)))
    ap.add_argument("--yalniz-arayuz", action="store_true", help="MCP olmadan yalnız yerel arayüz (geliştirme)")
    args = ap.parse_args(argv)

    _gunluk_ayarla()
    anahtar = ana_anahtar()
    islem = Islem(Depo(anahtar))
    islem.motoru_arkaplanda_yukle()
    from . import guncelleme

    guncelleme.arkaplanda_denetle()
    silinen = islem.depo.temizle()
    if silinen:
        logging.info("Süresi dolan %s maskeli ara kopya silindi.", silinen)

    yerel = YerelSunucu(islem, port=args.port, kurtarma_kodu=kurtarma_kodu(anahtar), kopru=not args.yalniz_arayuz)
    yerel.baslat()
    islem.arayuz_adresi = yerel.adres

    if args.yalniz_arayuz:
        print(f"Arthur Mask arayüzü: {yerel.adres}  (durdurmak için Ctrl+C)", file=sys.stderr)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            yerel.durdur()
        return 0

    sunucu_olustur(islem).run("stdio")
    yerel.durdur()
    return 0


if __name__ == "__main__":
    sys.exit(main())

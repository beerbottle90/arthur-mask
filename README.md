# Arthur Mask

ArthurLegal'in takma adlandırma (pseudonymization) kapısı. Türk hukuk belgelerini ve İngilizce sözleşmeleri
(UYAP `.udf`, Word `.docx`, `.pdf`, taranmış PDF ve `.jpg/.png/.tif` görüntüler, `.txt`) **cihazda** tarar. Kişisel ve gizli ifadeleri
tutarlı maske etiketleriyle değiştirir (`{{KİŞİ-01}}`, `{{TCKN-01}}`, `{{ADRES-01}}`),
eşleştirmeyi şifreli bir dosya kasasında saklar ve yapay zekâ çıktısını aynı kasayla geri
açar. Hiçbir veri dışarı gönderilmez.

> **Takma adlandırma anonimleştirme değildir.** Kasa büroda durduğu için veri KVKK
> bakımından kişisel veri olmaya devam eder. Araç riski düşürür, yükümlülüğü kaldırmaz:
> yurt dışına aktarım (KVKK m.9) ve sır saklama (Av.K. m.36) değerlendirmesi ayrıca yapılır.

## Ne yapar

| Katman | Açıklama |
|---|---|
| Tespit | Presidio + Türk hukukuna özgü kural tanıyıcıları; spaCy modeli indirmeden çalışır |
| Kimlik numaraları | TCKN (NVİ kontrol basamağı), VKN (GİB algoritması), TR IBAN (mod-97), MERSİS, sicil no, plaka |
| Kişi adları | Rol etiketleri (`DAVACI:`), unvanlar (`Av.`, `Bilirkişi`), Türkçe ad sözlüğü ("Deniz Aydın": soyadında büyük harf şartı yok), `Ad SOYAD` |
| Şirket | Şirket türü ekli unvanlar; kısa unvan aynı etikete bağlanır |
| Adres, iletişim | Adres satırları, mahalle/sokak + kapı no, telefon, e-posta/KEP, doğum tarihi |
| UYAP dosya no | Esas/karar/soruşturma numaraları. **Yargıtay, Danıştay, AYM ve BAM içtihat atıfları korunur** |
| Açık bırakılanlar | Tarih ve tutarlar (süre, zamanaşımı ve fer'i hesapları için); yalnız doğum tarihi maskelenir |
| Dosya sözlüğü | Dosyaya özgü "hep maskele" / "asla maskeleme" listesi (YAML) |
| Kırmızı hat | Maskelense bile gitmeyecek içerik (savunma stratejisi, sulh sınırı, KVKK m.6, içsel bilgi…) çıktıyı durdurur; gerekçeli onayla aşılır |
| UDF | Metin maskelenir, bütün `startOffset/length` biçim ofsetleri UTF‑16 birimiyle yeniden eşlenir |
| Word | Run'lara bölünmüş adlar birleştirilerek yerinde maskelenir; üst/alt bilgi, tablo, dipnot, yorum ve izlenen değişiklikler taranır; yazar/şirket üstverisi ve `mailto` köprüleri temizlenir |
| PDF | Metin katmanı maskelenip metin olarak yazılır |
| Taranmış belge / fotoğraf | Yerel OCR (RapidOCR PP-OCRv6); metin maskelenir, etiketler sayfa görüntüsüne kalıcı basılır, çıktı üstverisiz görüntü PDF'i; avukat incelemesi zorunlu |
| İngilizce | Yabancı şirket ekleri, İngilizce unvan/taraf/imza blokları, UK/US/AB adresleri, uluslararası telefon, pasaport; yayımlanmış İngiliz/ABD içtihat atıfları korunur |
| Claude köprüsü | Claude Desktop MCP (belgeler / belge_getir / teslim) + yerel AL arayüzü, tek süreç |
| Geri açma | Bozulmuş etiketleri tolere eder (`{{KISI-1}}`); Türkçe ek uyumu: `{{KİŞİ-01}}'in` → `Ayşe KARA'nın` |
| Kasa | Scrypt + Fernet ile şifreli, dosya (matter) başına; belgeler arası tutarlı etiket |

## Kurulum (geliştirici)

```bash
uv venv .venv --python 3.11
uv pip install --python .venv/Scripts/python.exe -e ".[test]"
```

Son kullanıcı kurulumu (tek `.exe`, yerel arayüz, Claude Desktop köprüsü) Faz 1 kapsamındadır:
[docs/faz-1-sartname.md](docs/faz-1-sartname.md).

## Kullanım

```bash
export ARTHUR_MASK_KASA_PAROLASI='…'        # yoksa sorulur

arthur-mask tara    dilekce.udf --sozluk sozluk.yaml                 # yalnız listele
arthur-mask maskele dilekce.udf --sozluk sozluk.yaml --kasa dosya-2026-014.kasa
#  → dilekce.maskeli.udf       (gönderilebilir)
#  → dilekce.maske-raporu.md   (YEREL)
#  → dosya-2026-014.kasa       (YEREL, şifreli)

arthur-mask maskele sozlesme.docx --kasa dosya-2026-014.kasa         # → sozlesme.maskeli.docx
arthur-mask maskele karar.pdf     --kasa dosya-2026-014.kasa         # → karar.maskeli.txt

arthur-mask geri-ac claude-cevabi.txt --kasa dosya-2026-014.kasa --bicim udf   # veya docx
```

Profiller: `standart` (varsayılan) ve `siki` (+ mahkeme adı, yer adları).

Kırmızı hat uyarısında maskeli çıktı yazılmaz (çıkış kodu 3). Gerekçeyle devam:
`--kirmizi-hat-onayi "gerekçe"`; gerekçe rapora işlenir.

## Ölçüm

```bash
python degerlendirme/degerlendir.py            # etiketli TR setinde recall / precision
python -m pytest -q
```

Sentetik set (v0) kuralları yazanla aynı elden çıktığı için **iyimserdir**. Üretim güveni
için onaylı, maskelenmiş gerçek büro belgelerinden türetilmiş bir set gerekir. Tanıyıcı,
eşik, sözlük veya model değiştiğinde ölçüm tekrarlanır.

## Sınırlar

- Tespit olasılıksaldır; maskeli çıktı gönderilmeden önce avukat tarafından okunur.
- Takma adlandırma kimliği gizler, içeriği gizlemez: benzersiz olay örgüsü kişiyi ele verebilir.
- Kural katmanı tek başına bağlamsız yabancı adları ve lakapları kaçırabilir; bunları yerel
  semantik katman (`arthur-mask[semantik]`, GLiNER PII) yakalar. Ölçümler: docs/faz-1-sartname.md.
- UDF biçimi açık bir şartnameye değil gözlemlenen dosyalara dayanır; üretilen dosyalar
  UYAP Doküman Editörü'nde açılarak teyit edilmelidir.
- Word görselleri ve gömülü nesneler maskelenmez (rapor uyarır). Eski `.doc` desteklenmez.
- Metin PDF'lerinin maskeli çıktısı metindir. Taranmış belgelerde el yazısı, imza, mühür,
  fotoğraf ve karekod OCR ile okunmaz ve maskelenmez; maskeli sayfa görüntüsü kontrol edilir.
- Geri açma kanonik değeri yazar: tek başına geçen soyadı tam ada açılır.

Belgeler: [masaüstü akışı ve Claude köprüsü](docs/platform-mimarisi.md) ·
[Faz 1 şartnamesi](docs/faz-1-sartname.md) · [lisans](LICENSE) · [üçüncü taraf bileşenler](ATTRIBUTION.md)

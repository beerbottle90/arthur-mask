# Faz 1 şartnamesi

Kararlar 13.09.2026'da proje sahibiyle netleştirildi. Mimari gerekçe:
[platform-mimarisi.md](platform-mimarisi.md).

## Kararlar

| # | Konu | Karar |
|---|---|---|
| K1 | Kişi tespiti | Hibrit: kurallar + Türkçe ad sözlüğü + yerel Türkçe NER. Soyadında büyük harf şartı yok |
| K2 | Claude köprüsü | Claude Desktop yerel MCP köprüsü + claude.ai web için **salt çözücü** tarayıcı eklentisi |
| K3 | Platform | Yalnız Windows (10/11) |
| K4 | Kasa | Cihazda, Windows oturumuna bağlı (DPAPI), parolasız; kurtarma anahtarlı |
| K5 | İnceleme ekranı | Yalnız istisnada: şüpheli aday, kırmızı hat veya artık iz |
| K6 | Terminoloji | Ürün dili "maske / maskele / maskeli"; hukuki metinlerde "takma adlandırma" |
| K7 | Etiket biçimi | `{{TÜR-NN}}`, ör. `{{KİŞİ-01}}`; ek: `{{KİŞİ-01}}'in` |
| K8 | Kırmızı hat | Engellenir; kullanıcı gerekçe yazarak aşar |
| K9 | Tutar / tarih | Açık; yalnız doğum tarihi maskelenir |
| K10 | Arayüz | Varsayılan tarayıcıda sekme; AL kimliği |
| K11 | Servis yaşam döngüsü | Claude Desktop ile birlikte başlar/kapanır; kısayol gerekirse Claude'u başlatır |
| K12 | Kurulum boyutu | Sınır yok; en isabetli model seçilir, model kurulumun içinde (çevrimdışı) |
| K13 | Dağıtım | Özel GitHub sürümü + uygulama içi bildirim; sessiz güncelleme yok |
| K14 | Saklama | `Belgeler\Arthur Mask\<dosya>\`; özgün kopyalanmaz; maskeli ara kopya 30 gün |
| K15 | Denetim kaydı | Yalnız kırmızı hat onayları (gerçek değer yok) |
| K16 | Lisans | ArthurLegal Proprietary Non-Commercial (büro ve şirket içi kullanım serbest) |
| K17 | Depo | Özel; herkese açma kararı ileride |
| K18 | NER modeli | **GLiNER PII** (`urchade/gliner_multi_pii-v1`, Apache-2.0); temiz lisans nedeniyle, isabeti daha yüksek ama eğitim verisi lisansı belirsiz akdeniz27 yerine |

## NER model ölçümü (13.09.2026)

İki sentetik set, kuralları görmeyen ayrı ajanlarca yazıldı: **geliştirme** (`ner_bagimsiz.txt`,
257 ifade; filtre ayarı bunda yapıldı) ve **gizli test** (`ner_test_gizli.txt`, 321 ifade;
ayar bitene kadar açılmadı). Sızıntı oranı: işaretli ifadelerden, türü ne olursa olsun
maskelenenlerin payı. Süre: ~60.000 karakterlik tek belge, CPU.

Aday elemesi (geliştirme seti, ayar öncesi):

| Aday | Sızıntı | Kişi R / P | 20 sayfa | Bellek | Sonuç |
|---|---|---|---|---|---|
| akdeniz27 BERT | 0.66 | 0.99 / 0.99 | 8 sn | 391 MB | En isabetli; eğitim verisi lisansı belirsiz → seçilmedi |
| GLiNER PII | 0.86 | 0.98 / 0.84 | 26 sn | 1.4 GB | **Seçildi** (Apache-2.0) |
| BTX24 | 0.68 | 0.48 / 0.72 | 642 sn | 3.7 GB | Elendi (gerçekçi metinde zayıf, çok yavaş) |

Ürün hattı, gizli test seti:

| Sistem | Sızıntı | Kişi R / P | Fazla maskeleme | 20 sayfa |
|---|---|---|---|---|
| Yalnız kurallar | 0.70 | 0.52 / 0.95 | 3 | 0.8 sn |
| Ham GLiNER | 0.82 | 0.94 / 0.83 | 49 | 28 sn |
| Kurallar + GLiNER + hukuk filtreleri | **0.91** | 0.89 / 0.95 | 19 | 32 sn |
| Kurallar ∪ ham GLiNER (filtresiz) | 0.95 | 0.94 / 0.87 | 52 | 28 sn |

Geliştirme setinde ürün hattı 0.98'di; gizli sette 0.91. Fark, ayarın geliştirme setine
kısmen uyduğunu gösterir. Gizli sette kalan başlıca açıklar: tek başına ilk ad ve lakaplar
(Memo, Can), baş harfler (A.Ö.R.), Türkçe karaktersiz OCR metni (ayse yilmaz), büyük
harfli kısaltmalı adresler (MAH./CAD.), etiketsiz dosya numaraları. Üretim güveni için gerçek
belge seti ön şart olmaya devam eder.

## Kapsam

1. **Tespit katmanı:** seçilen NER, oylama ile (kural ∪ sözlük ∪ NER, skor birleştirme)
   motora eklenir.
2. **Yerel servis:** HTTP (yalnız `127.0.0.1`) + MCP stdio aynı süreçte; kasa anahtarı
   Windows kimlik deposunda; dosya klasörü ve 30 günlük temizlik.
3. **Arayüz (tarayıcı sekmesi):** Dosyalar → Belge bırak → İnceleme (istisnada) → Cevaplar.
   Lacivert `#0F1A2B`, altın `#E2B54C` / `#F5D98A`, krem `#F4EFE3`; başlıklar Consolas Bold;
   piksel "A" logosu.
4. **MCP araçları:** `arthur_mask_belgeler`, `arthur_mask_belge_getir`, `arthur_mask_teslim`.
5. **Salt çözücü eklenti (Chrome/Edge):** claude.ai sayfasında etiketleri yalnız
   görüntüde çözer. Sayfa içeriğini değiştirip göndermez, sohbeti kopyalamaz.
6. **ArthurLegal proje talimatı:** etiket koruma ve teslim kuralı.
7. **Kurulum paketi:** tek `.exe`, kısayol, Claude Desktop kaydı, kurtarma anahtarı.

## Kabul ölçütleri

- Ham belgedeki hiçbir gerçek değer MCP araç sonucunda, sunucu günlüğünde veya eklenti
  trafiğinde görünmez (otomatik test: işaretli sahte değerlerle uçtan uca tarama).
- Teslim edilen cevap Word ve UDF olarak açılır; etiketlerin tamamı çözülür, bozuk etiket
  tolere edilir, kasada olmayan etiket kullanıcıya gösterilir.
- Kırmızı hat içeren belge gerekçesiz Claude'a verilemez; gerekçe kayda geçer.
- Claude Desktop kapalıyken sekme bağlantı yok durumunu gösterir; hiçbir veri beklemede
  kalıp başka yere gitmez.
- Sessiz yol oranı ve değerlendirme sonuçları sürüm notunda yayımlanır.

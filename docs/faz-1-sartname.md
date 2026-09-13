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
| K18 | NER modeli | Üç aday yerelde ölçülür, sonuç tablosuyla karar verilir |

## NER model adayları (ölçülecek)

| Aday | Ağırlık lisansı | Türkçe | Not |
|---|---|---|---|
| `akdeniz27/bert-base-turkish-cased-ner` | MIT | Türkçe haber verisiyle eğitilmiş (F1 0.96, haber) | Eğitim verisinin lisansı belirtilmemiş; büyük harfli UYAP başlıklarında davranışı ölçülecek |
| `urchade/gliner_multi_pii-v1` | Apache-2.0 | Türkçe eğitimi yok (sıfır örnekli) | Presidio'da yerleşik `GLiNERRecognizer`; etiket adları serbest |
| `BTX24/turkish-privacy-filter-pii` | Apache-2.0 | Türkçe, yalnız sentetik veri | Adres/TCKN/VKN dahil; CPU bellek ve süre ölçülecek |

Ticari olmayan kullanımla sınırlı (NC) lisanslı modeller elenir: bürolar aracı müvekkil
işinde kullanır, NC şartı bu kullanımı tartışmalı kılar.

Ölçüm ölçütleri: kısmi örtüşmeli recall (sızıntı), kişi precision, 20 sayfalık belgede CPU
süresi, bellek, büyük harfli başlık ve normal yazımlı ad başarımı. Ölçüm seti kuralları
yazan elden bağımsız, genişletilmiş bir sentetik hukuk metni setidir; gerçek belge seti
onaydan sonra eklenir.

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

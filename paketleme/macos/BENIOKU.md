# Arthur Mask (macOS)

ArthurLegal'in yerel gizlilik kapısı. Belgelerdeki kişisel verileri bu Mac'te
`{{KİŞİ-01}}` gibi etiketlerle maskeler; Claude Desktop'taki ArthurLegal projesine yalnız
maskeli metin gider. Claude'un cevabı yine bu Mac'te gerçek adlarla açılır.

## Başlarken

1. `ArthurMask-Kurulum.dmg` dosyasını açın ve **Arthur Mask**'i **Applications** (Uygulamalar) klasörüne sürükleyin.
2. Uygulamalar klasöründen **Arthur Mask**'i açın. macOS "Apple, Arthur Mask'in kötü amaçlı yazılım içermediğini
   doğrulayamadı" derse **Bitti**'ye basın; **Sistem Ayarları > Gizlilik ve Güvenlik** bölümünün altındaki
   **Yine de Aç** düğmesine basıp parolanızla onaylayın. Uygulama kod imzalı değildir; bu onay bir kez istenir.
3. İlk açılışta Arthur Mask kendini Claude Desktop'a kaydeder. Claude Desktop açıksa yeniden başlatmayı önerir;
   kabul edin ya da Claude Desktop'tan **Cmd+Q** ile çıkıp yeniden açın.
4. Tarayıcıda `http://127.0.0.1:47831` açılır. Belgeyi bırakın; gerekiyorsa "İncele" ile onaylayın.
5. Gösterilen komutu Claude Desktop'taki ArthurLegal projesine yapıştırın. Belgeyi Claude'a ayrıca eklemeyin.
6. Cevap "Cevaplar" bölümünde gerçek adlarla açılır. "Claude'a giden" bölümünden Claude'a gönderilen her şeyi görür, sızıntı denetimi yaparsınız.
7. Üst menüdeki **Kurtarma anahtarı**nı bir kez görüntüleyip güvenli bir yerde saklayın.

## Bilmeniz gerekenler

- Apple Silicon (M1 ve sonrası) Mac gerekir. Yalnız Claude Desktop (macOS) ile çalışır; claude.ai web ve mobil uygulamalar desteklenmez.
- Takma adlandırma anonimleştirme değildir. Tespit olasılıksaldır; maskeli metni göndermeden önce okuyun.
- Tarih ve tutarlar bilerek açık bırakılır. Word içindeki görseller, taranmış belgelerdeki el yazısı, imza ve mühürler maskelenmez.
- Dosyalarınız ev klasörünüzdeki `Arthur Mask` klasöründedir (`~/Arthur Mask`). iCloud "Masaüstü ve Belgeler"
  eşitlemesine girmemesi için Belgeler klasörü kullanılmaz. Maskeli ara kopyalar 30 gün sonra silinir.
- Kasaların ana anahtarı macOS Anahtar Zinciri'nde ("Arthur Mask" öğesi) durur. Mac değişirse kasaları yalnız kurtarma anahtarı açar.
- İnternete yalnız güncelleme denetimi için çıkılır (ArthurLegal sürüm sayfasındaki sürüm numarası okunur; belge bilgisi gönderilmez).
- Güncelleme: yeni disk görüntüsündeki Arthur Mask'i Uygulamalar klasörüne sürükleyip eskisinin yerine koyun; dosyalarınız korunur.

## Kaldırma

Önce Claude Desktop kaydını silin (Terminal'e yapıştırın), sonra uygulamayı Çöp Sepeti'ne taşıyın:

```
"/Applications/Arthur Mask.app/Contents/Resources/runtime/bin/python3" -I -c "from arthur_mask.claude_ayari import main; main(['sil'])"
```

Belgeleriniz (`~/Arthur Mask`) ve Anahtar Zinciri'ndeki anahtar kendiliğinden silinmez.

Ayrıntılı kullanım rehberi ArthurLegal paketlerindeki `ARTHUR-MASK.md` dosyasındadır.

Lisans: ArthurLegal Proprietary Non-Commercial (`LICENSE.txt`). Üçüncü taraf bileşenler:
`ATTRIBUTION.md` ve `ucuncu-taraf-lisanslari` klasörü.

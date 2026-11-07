# Güvenlik politikası

ArthurMask'ın tek sözü şudur: müvekkilin gerçek kişisel verisi, Claude'a giden hiçbir şeye girmez ve bilgisayardan
çıkmaz. Bu sözü bozan her şey (çıkış kapısını atlatan bir metin, kasayı ya da maskesiz metni başka bir programa veya
bir web sayfasına açan bir yol, kurulumu ya da güncellemeyi ele geçiren bir dosya) güvenlik açığıdır.

## Açık bildirme

Lütfen herkese açık issue açmayın. **ertug@datsproject.io** adresine şunları yazın:

- ne bulduğunuz ve nerede (dosya, araç adı, belge türü),
- nasıl tekrarlanacağı (örnek belge ya da kısa bir betik; **gerçek kişisel veri göndermeyin**, uydurma veri yeterli),
- saldırganın ne elde ettiği.

Aldığımızı bildirir, düzeltme sürecinde sizi bilgilendirir ve aksini istemezseniz sürüm notlarında adınızı anarız.
Açıklamadan önce düzeltmeyi yayımlamamız için makul bir süre tanıyın.

## Kapsam

- Kapsamda: `arthur_mask/` paketi, köprü (`arthur-mask-kopru`), yerel arayüz, güncelleme denetleyicisi ve
  `paketleme/` ile üretilen kurulum dosyaları.
- Kapsam dışı: Claude'un kendisi; bilgisayarın oturum sahibi (kasayı açabilen kişi zaten odur); OCR'ın el yazısı,
  imza ve mühür okuyamaması (README'de belirtilen bilinen sınır).

Tehdit modeli: [`.oss-scanner/threat_model.md`](.oss-scanner/threat_model.md).

---

## Security policy (English)

Please do not open a public issue. Email **ertug@datsproject.io** with what you found, how to reproduce it (use
made-up data, never real personal data) and what an attacker gains. The core promise is that a client's real
personal data never reaches anything sent to Claude and never leaves the machine; anything that breaks it is a
vulnerability. Threat model: [`.oss-scanner/threat_model.md`](.oss-scanner/threat_model.md).

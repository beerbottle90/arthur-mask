# Üçüncü taraf bileşenler / Third-Party Materials

Arthur Mask aşağıdaki bileşenlere dayanır. Her biri kendi lisansına tabidir; bu
bildirimler sürüm paketlerinde korunur ve kaldırılamaz.

| Bileşen | Kullanım | Lisans | Kaynak |
|---|---|---|---|
| Presidio Analyzer | Tespit çerçevesi, TCKN/plaka/IBAN/e-posta tanıyıcıları | MIT | https://github.com/data-privacy-stack/presidio |
| spaCy | Türkçe tokenizer (boş hat) | MIT | https://github.com/explosion/spaCy |
| pypdf | PDF metin katmanı | BSD-3-Clause | https://github.com/py-pdf/pypdf |
| cryptography | Kasa şifreleme (Scrypt, Fernet) | Apache-2.0 veya BSD-3-Clause | https://github.com/pyca/cryptography |
| PyYAML | Dosya sözlüğü | MIT | https://github.com/yaml/pyyaml |

Yalnız geliştirme ve testte kullanılanlar (sürüm paketine girmez): pytest (MIT),
python-docx (MIT), reportlab (BSD).

Türkçe NER modeli henüz seçilmedi. Seçilen model, ağırlık ve eğitim verisi
lisanslarıyla birlikte bu tabloya eklenir.

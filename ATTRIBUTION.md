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

## Semantik katman (`arthur-mask[semantik]`)

| Bileşen | Kullanım | Lisans | Kaynak |
|---|---|---|---|
| `urchade/gliner_multi_pii-v1` | Yerel PII modeli (ağırlıklar; eğitim verisi sentetik) | Apache-2.0 | https://huggingface.co/urchade/gliner_multi_pii-v1 |
| `microsoft/mdeberta-v3-base` | Modelin omurgası ve tokenizer'ı | MIT | https://huggingface.co/microsoft/mdeberta-v3-base |
| GLiNER | Model çalıştırma kütüphanesi | Apache-2.0 | https://github.com/urchade/GLiNER |
| PyTorch (CPU) | Çıkarım | BSD-3-Clause | https://github.com/pytorch/pytorch |
| Transformers | Tokenizer ve model yükleme | Apache-2.0 | https://github.com/huggingface/transformers |
| SentencePiece | Tokenizer | Apache-2.0 | https://github.com/google/sentencepiece |
| Protocol Buffers | Tokenizer dosya biçimi | BSD-3-Clause | https://github.com/protocolbuffers/protobuf |

Model seçimi 13.09.2026'da yerel ölçümle yapıldı (bkz. `docs/faz-1-sartname.md`).
Karşılaştırmada kullanılıp **dağıtılmayan** adaylar: `akdeniz27/bert-base-turkish-cased-ner`
(MIT; eğitim verisi lisansı belirsiz), `BTX24/turkish-privacy-filter-pii` (Apache-2.0) ve
onu çalıştırmak için `openai/privacy-filter` (Apache-2.0).

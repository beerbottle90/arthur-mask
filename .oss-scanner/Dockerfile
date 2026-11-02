# Anthropic OSS Scanner imajı (https://github.com/anthropics/oss-scanner).
#
# Tarayıcı bu dosyayı depo kökü bağlamıyla derler (ağ açık), sonra imajı internetsiz çalıştırıp kodu inceler.
# Bu yüzden modeller de burada indirilir: GLiNER, paketleme/derle.py'deki sabit revizyonla; RapidOCR modelleri
# ilk OcrMotoru açılışında. Linux'ta DPAPI ve Anahtar Zinciri yok; ana anahtar ortam değişkeninden okunur
# (anahtar.py). Aşağıdaki değer yalnız bu tarama imajı için sabit, sahte bir anahtardır; gerçek kurulumda kullanılmaz.
# Aynı imaj .github/workflows/oss-scanner-imaj.yml'de ağ kapalıyken denenir.

FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/opt/hf \
    ARTHUR_MASK_ANA_ANAHTAR=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=

# libgl1 ve libglib2.0-0: RapidOCR'ın kullandığı OpenCV için.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates git libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Torch'un CPU sürümü önce: GLiNER başka türlü GPU'lu büyük paketi çeker.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch

# Tarayıcı sözleşmesi: depo imajda /src'de durur.
COPY . /src
WORKDIR /src

RUN pip install --no-cache-dir -e ".[test,semantik,ocr]"

RUN python -c "from huggingface_hub import hf_hub_download; from pathlib import Path; \
depo, rev = 'urchade/gliner_multi_pii-v1', '1fcf13e85f4eef5394e1fcd406cf2ca9ea82351d'; \
[hf_hub_download(depo, f, revision=rev) for f in ('.gitattributes', 'gliner_config.json', 'pytorch_model.bin', 'README.md')]; \
r = Path('/opt/hf/hub/models--urchade--gliner_multi_pii-v1/refs/main'); r.parent.mkdir(parents=True, exist_ok=True); r.write_text(rev)" \
    && python -c "from arthur_mask.goruntu import OcrMotoru; OcrMotoru()"

# Bundan sonra Hugging Face ağa çıkmaz; modeller önbellekten okunur.
ENV HF_HUB_OFFLINE=1

# Başarısız test derlemeyi durdurmaz; sonuç günlükte kalır.
RUN python -m pytest -q || echo "UYARI: pytest başarısız"

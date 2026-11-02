# Anthropic OSS Scanner imajı (https://github.com/anthropics/oss-scanner).
#
# Tarayıcı bu dosyayı depo kökü bağlamıyla derler (ağ açık), sonra imajı internetsiz çalıştırıp kodu inceler.
# Bu yüzden modeller de burada indirilir: GLiNER ve mDeBERTa belirteçleyicisi, paketleme/derle_macos.py'deki sabit
# revizyonlarla; RapidOCR modelleri
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
M = {'urchade/gliner_multi_pii-v1': ('1fcf13e85f4eef5394e1fcd406cf2ca9ea82351d', ('.gitattributes', 'gliner_config.json', 'pytorch_model.bin', 'README.md')), \
     'microsoft/mdeberta-v3-base': ('a0484667b22365f84929a935b5e50a51f71f159d', ('config.json', 'spm.model', 'tokenizer_config.json'))}; \
[hf_hub_download(d, f, revision=r) for d, (r, fs) in M.items() for f in fs]; \
[(p.parent.mkdir(parents=True, exist_ok=True), p.write_text(r)) for d, (r, _) in M.items() \
 for p in [Path('/opt/hf/hub/models--' + d.replace('/', '--') + '/refs/main')]]" \
    && python -c "from arthur_mask.goruntu import OcrMotoru; OcrMotoru()"

# Bundan sonra Hugging Face ağa çıkmaz; modeller önbellekten okunur.
ENV HF_HUB_OFFLINE=1

# Başarısız test derlemeyi durdurmaz; sonuç günlükte kalır.
RUN python -m pytest -q || echo "UYARI: pytest başarısız"

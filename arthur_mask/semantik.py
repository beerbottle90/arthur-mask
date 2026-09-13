"""Yerel semantik tespit katmanı: GLiNER PII (Apache-2.0), tamamen çevrimdışı.

Kurallar ve ad sözlüğünün yakalayamadığı adları (yabancı adlar, lakaplar, küçük
harfli OCR metni), şirket unvanlarını ve adresleri anlamdan çıkarır. Model
çıktısı olasılıksaldır; motor katmanında hukuk terimi, kamu kurumu ve içtihat
filtrelerinden geçirilir.

Kurulum: `pip install "arthur-mask[semantik]"` (torch CPU + gliner).

Not: transformers, mdeberta tokenizer'ı için "incorrect regex pattern /
fix_mistral_regex" uyarısı verir. Bu uyarı SentencePiece tabanlı mdeberta için
geçerli değildir; önerilen düzeltme Türkçe metni harf harf böler. Varsayılan
tokenizer bilerek korunur.
"""

import logging
import os
from typing import Dict, List, Optional

MODEL_ADI = "urchade/gliner_multi_pii-v1"

# GLiNER etiketi → Presidio varlık adı
ETIKET_ESLEMESI: Dict[str, str] = {
    "person": "PERSON",
    "company": "TR_TUZEL_KISI",
    "address": "TR_ADRES",
    "phone number": "TR_TELEFON",
    "email": "EMAIL_ADDRESS",
    "date of birth": "TR_DOGUM_TARIHI",
    "national id number": "TR_NATIONAL_ID",
    "iban": "IBAN_CODE",
    "license plate": "TR_LICENSE_PLATE",
}


def kullanilabilir_mi() -> bool:
    try:
        import gliner  # noqa: F401
        from presidio_analyzer.predefined_recognizers import GLiNERRecognizer  # noqa: F401
    except ImportError:
        return False
    return True


def tanimlayici_olustur(
    model: Optional[str] = None,
    esik: float = 0.3,
    parca_boyu: int = 600,
    ortusme: int = 120,
    filtre=None,
):
    """filtre(metin, varlik, bas, son) -> (bas, son) | None

    Filtre Presidio'nun yinelenen ayıklamasından ÖNCE uygulanır. Aksi hâlde model
    bulgusu içindeki kural bulgusu yinelenen sayılıp silinir, model bulgusu da sonra
    filtreden düşerse ikisi birden kaybolur.
    """
    """Türkçe için yapılandırılmış GLiNER tanıyıcısı döndürür (yükleme ilk analizde)."""
    from presidio_analyzer.chunkers import CharacterBasedTextChunker
    from presidio_analyzer.predefined_recognizers import GLiNERRecognizer

    for gurultulu in ("transformers", "gliner"):
        logging.getLogger(gurultulu).setLevel(logging.ERROR)
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    class TurkceGLiNERTanimlayici(GLiNERRecognizer):
        def analyze(self, text, entities, nlp_artifacts=None) -> List:
            if self.gliner is None:
                self.load()
            # Eşlenmemiş varlık adlarının (TR_VKN vb.) modele etiket diye gitmesini engelle.
            eslenen = set(self.model_to_presidio_entity_mapping.values())
            sonuclar = super().analyze(text, [e for e in entities if e in eslenen], nlp_artifacts)
            if filtre is None:
                return sonuclar
            suzulen = []
            for s in sonuclar:
                aralik = filtre(text, s.entity_type, s.start, s.end)
                if aralik:
                    s.start, s.end = aralik
                    suzulen.append(s)
            return suzulen

    return TurkceGLiNERTanimlayici(
        name="GLiNER",
        supported_language="tr",
        entity_mapping=ETIKET_ESLEMESI,
        model_name=model or os.environ.get("ARTHUR_MASK_SEMANTIK_MODEL", MODEL_ADI),
        threshold=esik,
        map_location="cpu",
        text_chunker=CharacterBasedTextChunker(chunk_size=parca_boyu, chunk_overlap=ortusme),
    )

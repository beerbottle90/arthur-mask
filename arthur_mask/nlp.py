"""Presidio için Türkçe NLP motoru.

Varsayılan: indirme gerektirmeyen boş spaCy Türkçe hattı (yalnız tokenizer).
İsteğe bağlı: yerel bir Türkçe spaCy NER modeli yolu verilirse PERSON/LOCATION
tespiti de devreye girer (deneysel; TR değerlendirme setiyle ölçülmeden
üretimde güvenilmez).
"""

from typing import Optional

import spacy
from presidio_analyzer.nlp_engine import NerModelConfiguration, NlpArtifacts, SpacyNlpEngine

from .turkce import tr_kucuk


class TurkceNlpMotoru(SpacyNlpEngine):
    def __init__(self, ner_modeli: Optional[str] = None):
        self.ner_modeli = ner_modeli
        yapilandirma = NerModelConfiguration(
            model_to_presidio_entity_mapping={
                "PER": "PERSON", "PERSON": "PERSON", "KİŞİ": "PERSON",
                "LOC": "LOCATION", "GPE": "LOCATION",
            },
            labels_to_ignore=["ORG", "ORGANIZATION", "MISC", "DATE", "TIME", "MONEY", "CARDINAL"],
        )
        super().__init__(
            models=[{"lang_code": "tr", "model_name": ner_modeli or "blank:tr"}],
            ner_model_configuration=yapilandirma,
        )

    def load(self) -> None:
        hat = spacy.load(self.ner_modeli) if self.ner_modeli else spacy.blank("tr")
        self.nlp = {"tr": hat}

    def _doc_to_nlp_artifact(self, doc, language: str) -> NlpArtifacts:
        artefakt = super()._doc_to_nlp_artifact(doc, language)
        # Lemmatizer yoksa lemma boş gelir; bağlam güçlendiricisi küçük harfli token kullansın.
        artefakt.lemmas = [lemma or tr_kucuk(tok.text) for lemma, tok in zip(artefakt.lemmas, doc)]
        artefakt.keywords = [k for k in (tr_kucuk(t.text) for t in doc if not (t.is_punct or t.is_space)) if k]
        return artefakt

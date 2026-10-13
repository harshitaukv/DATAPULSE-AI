"""Text embeddings for RAG.

Primary backend: Sentence Transformers (all-MiniLM-L6-v2 by default). If the
library or model is unavailable (offline machine, restricted network), the
system falls back to a TF-IDF embedder so retrieval still works. The active
backend is always reported to the user; it is never hidden.
"""
from __future__ import annotations

import logging
from pathlib import Path

import joblib
import numpy as np

from app.config import get_settings

logger = logging.getLogger("datapulse.embeddings")


class Embedder:
    name = "base"
    min_score = 0.0

    def fit(self, texts: list[str]) -> None:  # pragma: no cover - interface
        pass

    def encode(self, texts: list[str]) -> np.ndarray:  # pragma: no cover - interface
        raise NotImplementedError

    def save(self, directory: Path) -> None:
        pass

    def load(self, directory: Path) -> None:
        pass


class SentenceTransformerEmbedder(Embedder):
    name = "sentence_transformers"

    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer  # heavy import; optional
        self.model_name = model_name
        self.model = SentenceTransformer(model_name)
        self.min_score = get_settings().rag_min_score_st

    def encode(self, texts: list[str]) -> np.ndarray:
        vecs = self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vecs, dtype="float32")


class TfidfEmbedder(Embedder):
    name = "tfidf"

    def __init__(self):
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=1,
                                          stop_words="english", token_pattern=r"(?u)\b[a-zA-Z_][a-zA-Z_0-9]+\b")
        self.min_score = get_settings().rag_min_score_tfidf

    def fit(self, texts: list[str]) -> None:
        self.vectorizer.fit(texts)

    def encode(self, texts: list[str]) -> np.ndarray:
        mat = self.vectorizer.transform(texts).toarray().astype("float32")
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return mat / norms

    def save(self, directory: Path) -> None:
        joblib.dump(self.vectorizer, directory / "tfidf_vectorizer.joblib")

    def load(self, directory: Path) -> None:
        self.vectorizer = joblib.load(directory / "tfidf_vectorizer.joblib")


def create_embedder() -> Embedder:
    s = get_settings()
    if s.embedding_backend in ("auto", "sentence_transformers"):
        try:
            return SentenceTransformerEmbedder(s.embedding_model)
        except Exception as exc:  # ImportError, network/model download errors
            if s.embedding_backend == "sentence_transformers":
                raise
            logger.warning("Sentence Transformers unavailable (%s); using TF-IDF embeddings.", type(exc).__name__)
    return TfidfEmbedder()

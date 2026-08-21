"""Wraps the embedding model. multilingual-e5-large specifically requires
"query: " / "passage: " prefixes on its inputs to produce correctly-aligned
vectors (this is how the model was trained) — get this wrong and retrieval
quality silently degrades, so it's centralized here rather than left to
callers to remember."""
from sentence_transformers import SentenceTransformer

from config import EMBEDDING_MODEL

_model = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def embed_passages(texts: list[str]) -> list[list[float]]:
    model = _get_model()
    prefixed = [f"passage: {t}" for t in texts]
    return model.encode(prefixed, show_progress_bar=len(texts) > 20, normalize_embeddings=True).tolist()


def embed_query(text: str) -> list[float]:
    model = _get_model()
    return model.encode(f"query: {text}", normalize_embeddings=True).tolist()


def embedding_dim() -> int:
    return _get_model().get_sentence_embedding_dimension()

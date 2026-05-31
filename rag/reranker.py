"""Optional cross-encoder reranking for retrieved chunks.

Reranking takes the top-K results from the fast vector search and re-scores
each one using a more accurate (but slower) cross-encoder model. This improves
precision by catching chunks that are semantically close but not the best match.

The cross-encoder scores the (query, chunk) pair directly rather than comparing
pre-computed embeddings, giving it a much better understanding of relevance.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rag.retriever import RetrievedChunk

logger = logging.getLogger(__name__)

# Process-wide cache of loaded cross-encoder models, keyed by model name.
# Each /analyze run builds a fresh graph and reranker, but the underlying
# ~80MB model must only be loaded once per process. Guarded by a lock
# because analyses run concurrently in a thread pool (asyncio.to_thread).
_MODEL_CACHE: dict[str, object] = {}
_MODEL_CACHE_LOCK = threading.Lock()


def _get_cross_encoder(model_name: str):
    """Return a shared CrossEncoder instance, loading it at most once per process."""
    cached = _MODEL_CACHE.get(model_name)
    if cached is not None:
        return cached
    with _MODEL_CACHE_LOCK:
        # Re-check inside the lock — another thread may have loaded it.
        cached = _MODEL_CACHE.get(model_name)
        if cached is not None:
            return cached
        try:
            from sentence_transformers import CrossEncoder
        except ImportError:
            logger.warning(
                "sentence-transformers not installed. "
                "Install with: pip install sentence-transformers"
            )
            raise
        # trust_remote_code lets newer rerankers (e.g. the GTE ModernBERT
        # cross-encoder) load their custom code; harmless for plain models.
        try:
            model = CrossEncoder(model_name, trust_remote_code=True)
        except TypeError:
            # Older sentence-transformers without the kwarg.
            model = CrossEncoder(model_name)
        _MODEL_CACHE[model_name] = model
        logger.info("Loaded cross-encoder model: %s (cached for process)", model_name)
        return model


class CrossEncoderReranker:
    """Reranks retrieved chunks using a cross-encoder model from sentence-transformers."""

    DEFAULT_MODEL = "Alibaba-NLP/gte-reranker-modernbert-base"

    def __init__(self, model_name: str = DEFAULT_MODEL, top_n: int = 4):
        """
        Args:
            model_name: HuggingFace cross-encoder model to use. Defaults to
                the GTE ModernBERT reranker — an 8192-token-context model,
                so it scores big parent-sized chunks without truncation.
            top_n: Number of top chunks to return after reranking.
        """
        self._model_name = model_name
        self._top_n = top_n
        self._model = None  # Lazy-load from the process-wide cache

    def _load_model(self):
        if self._model is None:
            self._model = _get_cross_encoder(self._model_name)

    def rerank(self, query: str, chunks: list["RetrievedChunk"]) -> list["RetrievedChunk"]:
        """Rerank chunks by cross-encoder relevance score.

        Args:
            query: The user's original question.
            chunks: Chunks from the retriever (typically top 8).

        Returns:
            Top N chunks sorted by relevance score (highest first).
        """
        if not chunks:
            return []

        self._load_model()

        # Score each (query, chunk_text) pair
        pairs = [(query, chunk.text) for chunk in chunks]
        scores = self._model.predict(pairs)

        # Attach scores and sort
        for chunk, score in zip(chunks, scores):
            chunk.relevance_score = float(score)

        ranked = sorted(chunks, key=lambda c: c.relevance_score, reverse=True)
        top = ranked[: self._top_n]

        logger.info(
            "Reranked %d → %d chunks. Top score: %.4f, Bottom score: %.4f",
            len(chunks),
            len(top),
            top[0].relevance_score if top else 0,
            top[-1].relevance_score if top else 0,
        )

        return top


class NoOpReranker:
    """Pass-through reranker that returns chunks unchanged. Used when reranking is disabled."""

    def __init__(self, top_n: int = 4):
        self._top_n = top_n

    def rerank(self, query: str, chunks: list["RetrievedChunk"]) -> list["RetrievedChunk"]:
        return chunks[: self._top_n]

"""ChromaDB client wrapper with metadata filtering and Redis caching."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections import OrderedDict
from typing import Any

import chromadb
from openai import OpenAI

logger = logging.getLogger(__name__)

COLLECTION_NAME = "finsight_filings"
EMBEDDING_MODEL = "text-embedding-3-large"

# In-memory LRU cache for query embeddings (shared across all VectorStore instances)
_EMBED_CACHE: OrderedDict[str, list[float]] = OrderedDict()
_EMBED_CACHE_MAX = 256


class VectorStore:
    """Wraps ChromaDB collection with query helpers and optional Redis caching."""

    def __init__(
        self,
        chroma_host: str | None = None,
        chroma_port: int | None = None,
        openai_api_key: str | None = None,
        redis_client: Any | None = None,
    ):
        host = chroma_host or os.getenv("CHROMA_HOST", "localhost")
        port = chroma_port or int(os.getenv("CHROMA_PORT", "8100"))
        self._chroma = chromadb.HttpClient(host=host, port=port)
        self._collection = self._chroma.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        self._openai = OpenAI(api_key=openai_api_key or os.getenv("OPENAI_API_KEY"))
        self._redis = redis_client

    @property
    def collection(self) -> chromadb.Collection:
        return self._collection

    def count(self) -> int:
        return self._collection.count()

    # ------------------------------------------------------------------
    # Embedding with Redis cache
    # ------------------------------------------------------------------

    def _cache_key(self, text: str) -> str:
        return f"emb:{hashlib.sha256(text.encode()).hexdigest()}"

    def embed_query(self, query: str) -> list[float]:
        """Embed a query string — in-memory LRU cache first, then Redis, then OpenAI."""
        key = self._cache_key(query)

        # 1. In-memory LRU (instant, process-local)
        cached = _EMBED_CACHE.get(key)
        if cached is not None:
            _EMBED_CACHE.move_to_end(key)
            logger.debug("Embedding LRU hit")
            return cached

        # 2. Redis (cross-process, 24h TTL)
        if self._redis:
            redis_cached = self._redis.get(key)
            if redis_cached:
                emb = json.loads(redis_cached)
                _EMBED_CACHE[key] = emb
                if len(_EMBED_CACHE) > _EMBED_CACHE_MAX:
                    _EMBED_CACHE.popitem(last=False)
                return emb

        # 3. OpenAI API
        t0 = time.monotonic()
        response = self._openai.embeddings.create(
            model=EMBEDDING_MODEL, input=[query]
        )
        embedding = response.data[0].embedding
        logger.info("embed_query: OpenAI API took %.2fs", time.monotonic() - t0)

        _EMBED_CACHE[key] = embedding
        if len(_EMBED_CACHE) > _EMBED_CACHE_MAX:
            _EMBED_CACHE.popitem(last=False)
        if self._redis:
            self._redis.setex(key, 86400, json.dumps(embedding))

        return embedding

    # ------------------------------------------------------------------
    # Query with metadata filtering
    # ------------------------------------------------------------------

    def query(
        self,
        query_text: str,
        ticker: str | None = None,
        doc_types: list[str] | None = None,
        top_k: int = 8,
        fiscal_years: list[int] | None = None,
    ) -> list[dict]:
        """Semantic search over the vector store.

        Args:
            query_text: The user's question.
            ticker: Filter results to this ticker symbol (e.g. "AAPL").
            doc_types: Filter by filing type (e.g. ["10-K", "10-Q"]).
            top_k: Number of results to return.
            fiscal_years: Restrict to chunks from these fiscal years. Used for
                temporal disambiguation so a wrong-year chunk can't win on
                similarity alone.

        Returns:
            List of dicts with keys: id, text, metadata, distance.
        """
        t0 = time.monotonic()
        query_embedding = self.embed_query(query_text)
        t_embed = time.monotonic() - t0

        # Build ChromaDB where filter
        where_filter = self._build_where_filter(ticker, doc_types, fiscal_years)

        t1 = time.monotonic()
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )
        t_chroma = time.monotonic() - t1
        logger.info("vector_store.query: embed=%.2fs chroma=%.2fs", t_embed, t_chroma)

        # Flatten ChromaDB's nested response format
        docs = []
        if results and results["ids"] and results["ids"][0]:
            for i in range(len(results["ids"][0])):
                docs.append(
                    {
                        "id": results["ids"][0][i],
                        "text": results["documents"][0][i],
                        "metadata": results["metadatas"][0][i],
                        "distance": results["distances"][0][i],
                    }
                )

        logger.info(
            "Retrieved %d chunks for query (ticker=%s, doc_types=%s)",
            len(docs), ticker, doc_types,
        )
        return docs

    def get_ticker_documents(
        self,
        ticker: str | None = None,
        doc_types: list[str] | None = None,
        fiscal_years: list[int] | None = None,
    ) -> list[dict]:
        """Fetch every stored chunk matching the filters — no vector search.

        Used to build the in-memory BM25 keyword index for hybrid retrieval,
        which needs the full candidate corpus rather than a top-k slice.

        Returns:
            List of dicts with keys: id, text, metadata.
        """
        where_filter = self._build_where_filter(ticker, doc_types, fiscal_years)
        got = self._collection.get(
            where=where_filter,
            include=["documents", "metadatas"],
        )
        ids = got.get("ids") or []
        documents = got.get("documents") or []
        metadatas = got.get("metadatas") or []
        docs = [
            {
                "id": ids[i],
                "text": documents[i] if i < len(documents) else "",
                "metadata": metadatas[i] if i < len(metadatas) else {},
            }
            for i in range(len(ids))
        ]
        logger.info("get_ticker_documents: %d chunks (ticker=%s)", len(docs), ticker)
        return docs

    def _build_where_filter(
        self,
        ticker: str | None,
        doc_types: list[str] | None,
        fiscal_years: list[int] | None = None,
    ) -> dict | None:
        """Build a ChromaDB where filter from ticker, doc_type and year constraints."""
        conditions = []

        if ticker:
            conditions.append({"ticker": {"$eq": ticker.upper()}})

        if doc_types and len(doc_types) == 1:
            conditions.append({"doc_type": {"$eq": doc_types[0]}})
        elif doc_types and len(doc_types) > 1:
            conditions.append({"doc_type": {"$in": doc_types}})

        if fiscal_years and len(fiscal_years) == 1:
            conditions.append({"fiscal_year": {"$eq": fiscal_years[0]}})
        elif fiscal_years and len(fiscal_years) > 1:
            conditions.append({"fiscal_year": {"$in": fiscal_years}})

        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}

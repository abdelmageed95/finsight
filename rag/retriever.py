"""Semantic search retriever — embeds query, searches ChromaDB, returns ranked chunks."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from rag.vector_store import VectorStore

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    """A single chunk returned from the vector store."""

    id: str
    text: str
    ticker: str
    doc_type: str
    filed_date: str
    accession_number: str
    source_url: str
    chunk_index: int
    distance: float  # cosine distance — lower is more similar
    section_name: str = ""      # e.g. "Risk Factors", "MD&A"
    item_number: str = ""       # e.g. "1A", "7"
    chunk_type: str = "prose"   # "prose" or "table"
    fiscal_year: int = 0        # fiscal year the filing covers (0 = unknown)
    relevance_score: float = 0.0  # set by reranker if used

    @classmethod
    def from_query_result(cls, result: dict) -> "RetrievedChunk":
        meta = result.get("metadata", {})
        return cls(
            id=result["id"],
            text=result["text"],
            ticker=meta.get("ticker", ""),
            doc_type=meta.get("doc_type", ""),
            filed_date=meta.get("filed_date", ""),
            accession_number=meta.get("accession_number", ""),
            source_url=meta.get("source_url", ""),
            chunk_index=meta.get("chunk_index", 0),
            distance=result.get("distance", 1.0),
            section_name=meta.get("section_name", ""),
            item_number=meta.get("item_number", ""),
            chunk_type=meta.get("chunk_type", "prose"),
            fiscal_year=meta.get("fiscal_year", 0),
        )


@dataclass
class RetrieverConfig:
    """Configuration for the retriever."""

    top_k: int = 8
    ticker: str | None = None
    doc_types: list[str] = field(default_factory=lambda: ["10-K", "10-Q"])


class Retriever:
    """Retrieves relevant document chunks from the vector store for a given query."""

    def __init__(self, vector_store: VectorStore, config: RetrieverConfig | None = None):
        self._store = vector_store
        self._config = config or RetrieverConfig()

    @property
    def config(self) -> RetrieverConfig:
        return self._config

    def retrieve(
        self,
        query: str,
        ticker: str | None = None,
        doc_types: list[str] | None = None,
        top_k: int | None = None,
        fiscal_years: list[int] | None = None,
    ) -> list[RetrievedChunk]:
        """Retrieve the most relevant chunks for a query.

        Args:
            query: The user's natural-language question.
            ticker: Override config ticker filter.
            doc_types: Override config doc_type filter.
            top_k: Override config top_k.
            fiscal_years: Restrict to chunks from these fiscal years.

        Returns:
            List of RetrievedChunk sorted by distance (most similar first).
        """
        effective_ticker = ticker or self._config.ticker
        effective_doc_types = doc_types or self._config.doc_types
        effective_top_k = top_k or self._config.top_k

        raw_results = self._store.query(
            query_text=query,
            ticker=effective_ticker,
            doc_types=effective_doc_types,
            top_k=effective_top_k,
            fiscal_years=fiscal_years,
        )

        chunks = [RetrievedChunk.from_query_result(r) for r in raw_results]

        logger.info(
            "Retrieved %d chunks for '%s' (ticker=%s)",
            len(chunks),
            query[:80],
            effective_ticker,
        )

        return chunks

    def retrieve_as_context(
        self,
        query: str,
        ticker: str | None = None,
        doc_types: list[str] | None = None,
        top_k: int | None = None,
    ) -> str:
        """Retrieve chunks and format them as a single context string for the LLM.

        Each chunk is labelled with its source metadata for citation.
        """
        chunks = self.retrieve(query, ticker, doc_types, top_k)
        return format_chunks_as_context(chunks)


def filter_to_latest_filings(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Keep only chunks from the most recent filing per doc_type.

    For report mode: ensures the report is based on the latest 10-K and latest 10-Q
    rather than mixing data from multiple filing periods.
    """
    # Find the latest accession_number per doc_type by filed_date
    latest: dict[str, tuple[str, str]] = {}  # doc_type → (filed_date, accession)
    for chunk in chunks:
        doc_type = chunk.doc_type
        if doc_type not in latest or chunk.filed_date > latest[doc_type][0]:
            latest[doc_type] = (chunk.filed_date, chunk.accession_number)

    allowed_accessions = {acc for _, acc in latest.values()}

    filtered = [c for c in chunks if c.accession_number in allowed_accessions]
    logger.info(
        "Filtered to latest filings: %d → %d chunks (accessions: %s)",
        len(chunks), len(filtered), allowed_accessions,
    )
    return filtered


def format_chunks_as_context(chunks: list[RetrievedChunk]) -> str:
    """Format retrieved chunks into a numbered context block for LLM injection."""
    if not chunks:
        return "No relevant documents found."

    parts = []
    for i, chunk in enumerate(chunks, 1):
        section_info = f" | Section: {chunk.section_name}" if chunk.section_name else ""
        type_info = f" [{chunk.chunk_type}]" if chunk.chunk_type == "table" else ""
        header = (
            f"[Source {i}] {chunk.doc_type} | {chunk.ticker} | "
            f"Filed: {chunk.filed_date}{section_info}{type_info}"
        )
        parts.append(f"{header}\n{chunk.text}")

    return "\n\n---\n\n".join(parts)

"""Retrieval for the RAG pipeline.

Hybrid retrieval = dense vector search (semantic) fused with BM25 (lexical
keyword match) via Reciprocal Rank Fusion. Dense search catches paraphrase;
BM25 catches exact terms (ticker names, statute numbers, "Item 1A") that an
embedding can blur. RRF combines their rankings without tuning score scales.

Retrieval works on small *child* chunks for precision; a hit is then expanded
to its *parent* block (see expand_to_parents) so the LLM reads full context.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace

import tiktoken

from rag.vector_store import VectorStore

logger = logging.getLogger(__name__)

_ENCODING = tiktoken.get_encoding("cl100k_base")


@dataclass
class RetrievedChunk:
    """A single chunk returned from retrieval.

    `text` is the child chunk (embedded + reranked). `parent_text` is the
    larger block it belongs to; expand_to_parents() swaps `text` for it
    before the chunk is shown to the LLM.
    """

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
    parent_id: str = ""         # groups children of the same parent block
    parent_text: str = ""       # the parent block — what the LLM reads
    relevance_score: float = 0.0  # set by reranker if used

    @classmethod
    def from_query_result(cls, result: dict) -> "RetrievedChunk":
        meta = result.get("metadata", {}) or {}
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
            parent_id=meta.get("parent_id", ""),
            parent_text=meta.get("parent_text", ""),
        )


@dataclass
class RetrieverConfig:
    """Configuration for the retriever."""

    top_k: int = 8
    ticker: str | None = None
    doc_types: list[str] = field(default_factory=lambda: ["10-K", "10-Q"])


# ---------------------------------------------------------------------------
# BM25 lexical search + Reciprocal Rank Fusion
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Lowercase word/number tokens — good enough for BM25 over filing text."""
    return _TOKEN_RE.findall(text.lower())


def bm25_search(query: str, corpus: list[dict], top_n: int) -> list[str]:
    """Rank `corpus` documents against `query` with BM25; return top-n ids.

    `corpus` is a list of {id, text, metadata}. Returns an empty list if the
    corpus is empty or rank_bm25 is unavailable (hybrid degrades to dense).
    """
    if not corpus:
        return []
    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        logger.warning("rank_bm25 not installed — skipping BM25 (dense only)")
        return []

    tokenized_corpus = [_tokenize(d["text"]) for d in corpus]
    bm25 = BM25Okapi(tokenized_corpus)
    scores = bm25.get_scores(_tokenize(query))
    ranked = sorted(range(len(corpus)), key=lambda i: scores[i], reverse=True)
    return [corpus[i]["id"] for i in ranked[:top_n]]


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = 60) -> list[str]:
    """Fuse several ranked id-lists into one via Reciprocal Rank Fusion.

    Each list contributes 1/(k + rank) to a doc's score. `k` damps the weight
    of top ranks so a single list can't dominate; 60 is the standard value.
    Returns ids sorted by fused score, highest first.
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda d: scores[d], reverse=True)


class Retriever:
    """Dense-only retriever — semantic vector search over the store."""

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
        """Retrieve the most relevant chunks by dense vector similarity."""
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
            "Dense retrieved %d chunks for '%s' (ticker=%s)",
            len(chunks), query[:80], effective_ticker,
        )
        return chunks

    def retrieve_as_context(
        self,
        query: str,
        ticker: str | None = None,
        doc_types: list[str] | None = None,
        top_k: int | None = None,
    ) -> str:
        """Retrieve chunks and format them as a single context string."""
        chunks = self.retrieve(query, ticker, doc_types, top_k)
        return format_chunks_as_context(chunks)


class HybridRetriever:
    """Hybrid retriever — dense vector search fused with BM25 keyword search.

    For each query it runs both retrievers over the same candidate corpus and
    fuses their rankings with Reciprocal Rank Fusion. Drop-in compatible with
    Retriever.retrieve() so the RAG chain can use either.
    """

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
        """Retrieve chunks via dense + BM25, fused with RRF.

        Returns up to `top_k` child RetrievedChunks ordered by fused rank.
        """
        effective_ticker = ticker or self._config.ticker
        effective_doc_types = doc_types or self._config.doc_types
        effective_top_k = top_k or self._config.top_k

        # 1. Dense vector search (semantic).
        dense_results = self._store.query(
            query_text=query,
            ticker=effective_ticker,
            doc_types=effective_doc_types,
            top_k=effective_top_k,
            fiscal_years=fiscal_years,
        )
        dense_ids = [r["id"] for r in dense_results]

        # 2. BM25 keyword search (lexical) over the same filtered corpus.
        corpus = self._store.get_ticker_documents(
            ticker=effective_ticker,
            doc_types=effective_doc_types,
            fiscal_years=fiscal_years,
        )
        bm25_ids = bm25_search(query, corpus, top_n=effective_top_k)

        # Pool every candidate by id — dense dicts carry a distance, corpus
        # dicts don't, so dense wins ties when an id appears in both.
        pool: dict[str, dict] = {d["id"]: d for d in corpus}
        for r in dense_results:
            pool[r["id"]] = r

        # 3. Fuse the two rankings. If BM25 was unavailable, this is just the
        #    dense ranking — hybrid degrades gracefully to dense-only.
        fused_ids = reciprocal_rank_fusion([dense_ids, bm25_ids])
        fused_ids = [i for i in fused_ids if i in pool][:effective_top_k]

        chunks = [RetrievedChunk.from_query_result(pool[i]) for i in fused_ids]
        logger.info(
            "Hybrid retrieved %d chunks for '%s' (dense=%d, bm25=%d, ticker=%s)",
            len(chunks), query[:80], len(dense_ids), len(bm25_ids), effective_ticker,
        )
        return chunks


def filter_to_latest_filings(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Keep only chunks from the most recent filing per doc_type.

    For report mode: ensures the report is based on the latest 10-K and latest
    10-Q rather than mixing data from multiple filing periods.
    """
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


def expand_to_parents(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Expand retrieved child chunks to their parent blocks.

    Keeps the input order (best hit first), de-duplicates by parent_id, and
    swaps each chunk's `text` for its larger `parent_text`. This is the read
    side of parent-document retrieval: search precise children, read rich
    parents. Chunks without a parent (legacy data) pass through unchanged.
    """
    seen: set[str] = set()
    expanded: list[RetrievedChunk] = []
    for c in chunks:
        key = c.parent_id or c.id
        if key in seen:
            continue
        seen.add(key)
        text = c.parent_text or c.text
        expanded.append(replace(c, text=text))
    logger.info("Expanded %d child chunks → %d parent blocks", len(chunks), len(expanded))
    return expanded


def cap_context_tokens(
    chunks: list[RetrievedChunk], max_tokens: int
) -> list[RetrievedChunk]:
    """Trim a chunk list so its combined text stays within a token budget.

    Parent blocks are large; feeding all of them can blow past LLM input
    limits and dilutes the answer ("lost in the middle"). Keeps chunks in
    order (best first) and always keeps at least the top one.
    """
    capped: list[RetrievedChunk] = []
    total = 0
    for c in chunks:
        n = len(_ENCODING.encode(c.text))
        if capped and total + n > max_tokens:
            break
        capped.append(c)
        total += n
    if len(capped) < len(chunks):
        logger.info(
            "Capped context: %d → %d chunks (%d tokens, budget %d)",
            len(chunks), len(capped), total, max_tokens,
        )
    return capped


def format_chunks_as_context(chunks: list[RetrievedChunk]) -> str:
    """Format retrieved chunks into a numbered context block for LLM injection."""
    if not chunks:
        return "No relevant documents found."

    parts = []
    for i, chunk in enumerate(chunks, 1):
        section_info = f" | Section: {chunk.section_name}" if chunk.section_name else ""
        year_info = f" | FY{chunk.fiscal_year}" if chunk.fiscal_year else ""
        type_info = f" [{chunk.chunk_type}]" if chunk.chunk_type == "table" else ""
        header = (
            f"[Source {i}] {chunk.doc_type} | {chunk.ticker}{year_info} | "
            f"Filed: {chunk.filed_date}{section_info}{type_info}"
        )
        parts.append(f"{header}\n{chunk.text}")

    return "\n\n---\n\n".join(parts)

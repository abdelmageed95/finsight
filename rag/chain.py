"""RAG chain — wires retrieval, reranking, and LLM generation into a single callable.

Usage:
    from rag.chain import create_rag_chain

    chain = create_rag_chain()
    report, chunks = chain.invoke("AAPL", "What are AAPL's main revenue risks?")
    print(report.summary)
    print(report.risk_score)
"""

from __future__ import annotations

import logging
import os
from typing import Any

from langchain_anthropic import ChatAnthropic

from rag.prompts import (
    CHAT_SYSTEM_PROMPT,
    CHAT_USER_PROMPT,
    RAG_SYSTEM_PROMPT,
    RAG_USER_PROMPT,
)
from rag.reranker import CrossEncoderReranker, NoOpReranker
from rag.retriever import (
    HybridRetriever,
    RetrievedChunk,
    RetrieverConfig,
    cap_context_tokens,
    expand_to_parents,
    filter_to_latest_filings,
    format_chunks_as_context,
)
from rag.schemas import ReportSchema
from rag.temporal import extract_fiscal_years
from rag.vector_store import VectorStore

logger = logging.getLogger(__name__)

# When a query targets specific fiscal year(s) we hard-filter retrieval to
# those years so a wrong-year chunk can't win on similarity alone. If the
# filter is too sparse (missing/legacy metadata) we relax to an unfiltered
# search and let the reranker sort it out.
MIN_TEMPORAL_CHUNKS = 4

# Upper bound on the parent-block context fed to the LLM, in tokens. Parent
# blocks are large (~2k tokens each); without a cap a handful of them can
# exceed model input limits, balloon cost, and dilute the answer.
MAX_CONTEXT_TOKENS = 5000


class RAGChain:
    """Full RAG pipeline: retrieve → rerank → generate structured report.

    Supports two retrieval modes:
      - "report": retrieves broadly then filters to the latest 10-K + 10-Q only,
        producing focused analysis based on the most current data.
      - "chat": retrieves across all filings (up to 10) for historical depth,
        useful for exploratory follow-up questions.
    """

    def __init__(
        self,
        vector_store: VectorStore,
        retriever_config: RetrieverConfig | None = None,
        reranker: Any | None = None,
        llm: Any | None = None,
        use_reranker: bool = False,
        rerank_top_n: int = 4,
        mode: str = "report",
    ):
        self._retriever = HybridRetriever(vector_store, config=retriever_config)
        self._mode = mode

        if use_reranker:
            self._reranker = reranker or CrossEncoderReranker(top_n=rerank_top_n)
        else:
            self._reranker = reranker or NoOpReranker(top_n=rerank_top_n)

        self._llm = llm or ChatAnthropic(
            model="claude-haiku-4-5-20251001",
            temperature=0,
            max_tokens=4096,
            api_key=os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY"),
            # Ride out transient 429s — LangChain honours the retry-after
            # header, so bursts against a low per-minute limit self-heal.
            max_retries=8,
        )
        self._structured_llm = self._llm.with_structured_output(ReportSchema)

    def invoke(
        self,
        ticker: str,
        question: str,
        doc_types: list[str] | None = None,
        top_k: int = 8,
        prior_turns: list[dict] | None = None,
        financial_context: str = "",
    ) -> tuple[ReportSchema, list[RetrievedChunk]]:
        """Run the full RAG pipeline and return a structured report.

        Args:
            ticker: Stock ticker symbol (e.g. "AAPL").
            question: The user's natural-language question.
            doc_types: Filing types to search (default: ["10-K", "10-Q"]).
            top_k: Number of chunks to retrieve before reranking.
            prior_turns: Previous conversation turns for multi-turn context.
            financial_context: Pre-formatted structured financial-history
                block (see pipelines.financial_summary). Injected into the
                prompt so the LLM has authoritative multi-year numbers, not
                just figures parsed from retrieved filing text.

        Returns:
            (report, chunks) — the ReportSchema (summary, risk_score,
            citations, …) plus the reranked source chunks the LLM saw.
            The chunks let callers verify citation provenance; the list is
            empty when no documents were retrieved.
        """
        logger.info("RAG chain invoked: ticker=%s mode=%s question='%s'", ticker, self._mode, question[:80])

        # Step 1: Retrieve — over-fetch for report mode so we have enough
        # after filtering to latest filings
        fetch_k = top_k * 2 if self._mode == "report" else top_k
        effective_doc_types = doc_types or ["10-K", "10-Q"]

        # Temporal disambiguation: if the question targets a specific fiscal
        # year, hard-filter retrieval to chunks from that period. Soft
        # fallback — relax to unfiltered if the filter returns too little.
        target_years = extract_fiscal_years(question)
        chunks = self._retriever.retrieve(
            query=question,
            ticker=ticker.upper(),
            doc_types=effective_doc_types,
            top_k=fetch_k,
            fiscal_years=target_years or None,
        )
        if target_years and len(chunks) < MIN_TEMPORAL_CHUNKS:
            logger.info(
                "Temporal filter FY%s returned %d chunks — relaxing to unfiltered retrieval",
                target_years, len(chunks),
            )
            chunks = self._retriever.retrieve(
                query=question,
                ticker=ticker.upper(),
                doc_types=effective_doc_types,
                top_k=fetch_k,
            )
        elif target_years:
            logger.info("Temporal filter FY%s applied (%d chunks)", target_years, len(chunks))

        if not chunks:
            logger.warning("No chunks retrieved for ticker=%s", ticker)
            return ReportSchema(
                ticker=ticker.upper(),
                summary="No relevant documents found in the database for this ticker. Please ensure data has been ingested first.",
                risk_score=50,
                risk_rationale="Unable to assess — no source documents available.",
                key_metrics=[],
                citations=[],
                confidence="low",
            ), []

        # Step 1b: Report mode — restrict to latest filing per doc_type
        if self._mode == "report":
            chunks = filter_to_latest_filings(chunks)

        # Step 2: Rerank the child chunks — precise scoring on small text.
        reranked = self._reranker.rerank(question, chunks)

        # Step 3: Parent-document expansion — swap each top child for its
        # larger parent block so the LLM reads full context, not a sliver —
        # then cap the total so the prompt stays within model input limits.
        parents = expand_to_parents(reranked)
        parents = cap_context_tokens(parents, MAX_CONTEXT_TOKENS)

        # Step 4: Format context
        context = format_chunks_as_context(parents)

        # Step 5: Build messages
        system_message = RAG_SYSTEM_PROMPT.format(
            context=context,
            financial_context=(
                financial_context
                or "No structured financial data available — rely on the filing excerpts below."
            ),
        )
        user_message = RAG_USER_PROMPT.format(ticker=ticker.upper(), question=question)

        messages = [
            {"role": "system", "content": system_message},
        ]

        # Inject prior conversation turns so the LLM has multi-turn context
        if prior_turns:
            for turn in prior_turns[-10:]:  # cap to last 10 turns
                messages.append({"role": turn["role"], "content": turn["content"]})

        messages.append({"role": "user", "content": user_message})

        # Step 6: LLM call with structured output
        logger.info(
            "Calling LLM with %d parent blocks (%d child hits), %d prior turns",
            len(parents), len(reranked), len(prior_turns or []),
        )
        report = self._structured_llm.invoke(messages)

        logger.info(
            "RAG chain complete: ticker=%s risk_score=%s confidence=%s",
            report.ticker, report.risk_score, report.confidence,
        )

        # Return the parent blocks — that is the text the LLM actually read,
        # so citation-faithfulness checks compare against the right source.
        return report, parents


def create_rag_chain(
    use_reranker: bool = False,
    redis_client: Any | None = None,
    top_k: int = 16,
    rerank_top_n: int = 8,
    mode: str = "report",
) -> RAGChain:
    """Factory function to create a RAG chain with default configuration.

    Args:
        use_reranker: Whether to enable cross-encoder reranking.
        redis_client: Optional Redis client for embedding cache.
        top_k: Number of chunks to retrieve (default 16).
        rerank_top_n: Number of chunks to keep after reranking.
        mode: "report" (latest filing only) or "chat" (all filings).

    Returns:
        Configured RAGChain instance.
    """
    store = VectorStore(redis_client=redis_client)
    config = RetrieverConfig(top_k=top_k)

    return RAGChain(
        vector_store=store,
        retriever_config=config,
        use_reranker=use_reranker,
        rerank_top_n=rerank_top_n,
        mode=mode,
    )


# ======================================================================
# Lightweight chat chain — conversational, fast, supports streaming
# ======================================================================

class ChatChain:
    """Lightweight RAG chat: retrieve → format → stream a conversational answer.

    Unlike RAGChain (which produces a full structured report), ChatChain returns
    plain-text markdown optimised for interactive Q&A.
    """

    def __init__(
        self,
        vector_store: VectorStore,
        retriever_config: RetrieverConfig | None = None,
        reranker: Any | None = None,
        llm: Any | None = None,
        rerank_top_n: int = 6,
    ):
        self._retriever = HybridRetriever(vector_store, config=retriever_config)
        self._reranker = reranker or NoOpReranker(top_n=rerank_top_n)
        self._llm = llm or ChatAnthropic(
            model="claude-haiku-4-5-20251001",
            temperature=0.2,
            max_tokens=1024,
            api_key=os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY"),
            streaming=True,
            max_retries=8,
        )

    def _build_messages(
        self,
        ticker: str,
        question: str,
        prior_turns: list[dict] | None = None,
        top_k: int = 4,
        doc_types: list[str] | None = None,
    ) -> tuple[list[dict], list[RetrievedChunk]]:
        """Retrieve context and build the message list for the LLM."""
        effective_doc_types = doc_types or ["10-K", "10-Q"]

        # Temporal disambiguation with a soft fallback (see RAGChain.invoke).
        target_years = extract_fiscal_years(question)
        chunks = self._retriever.retrieve(
            query=question,
            ticker=ticker.upper(),
            doc_types=effective_doc_types,
            top_k=top_k,
            fiscal_years=target_years or None,
        )
        if target_years and len(chunks) < min(MIN_TEMPORAL_CHUNKS, top_k):
            logger.info(
                "Chat temporal filter FY%s returned %d chunks — relaxing",
                target_years, len(chunks),
            )
            chunks = self._retriever.retrieve(
                query=question,
                ticker=ticker.upper(),
                doc_types=effective_doc_types,
                top_k=top_k,
            )
        reranked = self._reranker.rerank(question, chunks) if chunks else []
        # Parent-document expansion: read full blocks, not 500-token slivers;
        # capped so the prompt stays within model input limits.
        parents = expand_to_parents(reranked) if reranked else []
        parents = cap_context_tokens(parents, MAX_CONTEXT_TOKENS)
        context = format_chunks_as_context(parents)

        messages: list[dict] = [
            {"role": "system", "content": CHAT_SYSTEM_PROMPT.format(context=context)},
        ]
        if prior_turns:
            for turn in prior_turns[-4:]:
                messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append(
            {"role": "user", "content": CHAT_USER_PROMPT.format(ticker=ticker.upper(), question=question)},
        )
        return messages, parents

    def invoke(
        self,
        ticker: str,
        question: str,
        prior_turns: list[dict] | None = None,
        top_k: int = 4,
    ) -> dict:
        """Non-streaming chat invocation. Returns {answer, citations, confidence}."""
        messages, reranked = self._build_messages(ticker, question, prior_turns, top_k)

        logger.info("ChatChain: %d context chunks, %d prior turns", len(reranked), len(prior_turns or []))
        response = self._llm.invoke(messages)
        answer = response.content if hasattr(response, "content") else str(response)

        citations = _extract_citation_labels(reranked)
        confidence = "high" if len(reranked) >= 4 else "medium" if reranked else "low"

        return {"answer": answer, "citations": citations, "confidence": confidence}

    def stream(
        self,
        ticker: str,
        question: str,
        prior_turns: list[dict] | None = None,
        top_k: int = 4,
    ):
        """Streaming chat — yields text chunks as they arrive from the LLM.

        Yields dicts: {"type": "token", "data": "..."} or {"type": "citations", "data": [...]}.
        """
        messages, reranked = self._build_messages(ticker, question, prior_turns, top_k)

        logger.info("ChatChain stream: %d context chunks", len(reranked))
        for chunk in self._llm.stream(messages):
            text = chunk.content if hasattr(chunk, "content") else str(chunk)
            if text:
                yield {"type": "token", "data": text}

        citations = _extract_citation_labels(reranked)
        confidence = "high" if len(reranked) >= 4 else "medium" if reranked else "low"
        yield {"type": "done", "data": {"citations": citations, "confidence": confidence}}


def _extract_citation_labels(chunks: list[RetrievedChunk]) -> list[str]:
    """Build short citation labels from retrieved chunks."""
    labels = []
    for i, c in enumerate(chunks[:6], 1):
        section = f" — {c.section_name}" if c.section_name else ""
        labels.append(f"[{i}] {c.doc_type} {c.filed_date}{section}")
    return labels


def create_chat_chain(
    redis_client: Any | None = None,
    top_k: int = 6,
    rerank_top_n: int = 4,
) -> ChatChain:
    """Factory for the lightweight conversational chat chain."""
    store = VectorStore(redis_client=redis_client)
    config = RetrieverConfig(top_k=top_k)
    return ChatChain(
        vector_store=store,
        retriever_config=config,
        rerank_top_n=rerank_top_n,
    )

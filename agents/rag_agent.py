"""RAG Agent node — retrieves relevant documents and generates analysis.

This is "The Analyst". It takes the user's question, queries the vector store
for the most relevant filing chunks, and calls the LLM with a carefully
engineered prompt to produce a structured research report.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from langchain_core.messages import AIMessage
from langgraph.types import Command

from api.event_bus import publish

if TYPE_CHECKING:
    from agents.orchestrator import GraphState

logger = logging.getLogger(__name__)


def _progress(state: "GraphState", message: str, percent: int, stage: str = "rag") -> None:
    job_id = state.get("job_id")
    if not job_id:
        return
    publish(job_id, {"type": "progress", "stage": stage, "message": message, "percent": percent})


def rag_agent_node(state: "GraphState") -> Command[Literal["supervisor"]]:
    """Run the RAG pipeline: retrieve → rerank → LLM → structured report.

    Reads ticker and question from state, runs the RAG chain, and returns
    the structured report plus retrieved document references.
    """
    from rag.chain import create_rag_chain

    ticker = state.get("ticker", "")
    question = state.get("question", "")

    if not ticker or not question:
        return Command(
            goto="supervisor",
            update={
                "messages": [AIMessage(
                    content="RAG agent requires both ticker and question in state.",
                    name="rag_agent",
                )],
            },
        )

    logger.info("RAG agent: analysing %s — '%s'", ticker, question[:80])
    _progress(state, f"Searching the latest 10-K and 10-Q for {ticker}…", 45)

    prior_turns = state.get("prior_turns", [])

    chain = create_rag_chain(use_reranker=True, top_k=16, rerank_top_n=8, mode="report")
    _progress(state, "Generating risk analysis with Claude Haiku…", 65, stage="report")
    report = chain.invoke(ticker, question, prior_turns=prior_turns)

    # Hard guard: if the model produced a report with too few citations,
    # we cannot trust the risk_score. Force it to null and flip confidence
    # to "low". Prompt drift can sneak placeholder scores back in; this
    # is the belt to the prompt's suspenders.
    MIN_CITATIONS_FOR_RISK = 3
    if len(report.citations) < MIN_CITATIONS_FOR_RISK and report.risk_score is not None:
        logger.warning(
            "RAG agent: only %d citation(s) for %s — clearing risk_score to avoid placeholder",
            len(report.citations), ticker,
        )
        report.risk_score = None
        report.risk_rationale = ""
        if report.confidence in ("high", "medium"):
            report.confidence = "low"

    # Build a readable summary message for the conversation
    risk_line = (
        f"Risk Score: {report.risk_score}/100 ({report.risk_rationale})"
        if report.risk_score is not None
        else "Risk Score: insufficient data"
    )
    summary = (
        f"RAG Agent analysis for {ticker}:\n"
        f"{risk_line}\n"
        f"Confidence: {report.confidence}\n\n"
        f"{report.summary}"
    )

    # Store retrieved doc references
    retrieved_docs = []
    for citation in report.citations:
        retrieved_docs.append({
            "source_index": citation.source_index,
            "doc_type": citation.doc_type,
            "excerpt": citation.excerpt,
        })

    logger.info(
        "RAG agent complete: risk_score=%s confidence=%s citations=%d",
        report.risk_score, report.confidence, len(report.citations),
    )

    # Stream a partial summary preview the moment it's available — the frontend
    # can render this while the report-agent finalises persistence.
    publish_job_id = state.get("job_id")
    if publish_job_id:
        publish(publish_job_id, {
            "type": "partial",
            "summary": report.summary,
            "risk_score": report.risk_score,
            "confidence": report.confidence,
            "percent": 90,
        })

    return Command(
        goto="supervisor",
        update={
            "messages": [AIMessage(content=summary, name="rag_agent")],
            "retrieved_docs": retrieved_docs,
            "tool_results": {
                "rag_agent": report.model_dump(),
            },
        },
    )

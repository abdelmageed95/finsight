"""Report Agent node — formats the final research report.

This is "The Publisher". It takes the RAG agent's raw structured output and
turns it into a polished, user-facing report with formatting, scoring
normalisation, and metadata.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from langchain_core.messages import AIMessage
from langgraph.types import Command

from api.event_bus import publish

if TYPE_CHECKING:
    from agents.orchestrator import GraphState

logger = logging.getLogger(__name__)


def report_agent_node(state: "GraphState") -> Command[Literal["__end__"]]:
    """Format the RAG agent's output into a final research report.

    Reads the rag_agent results from tool_results, adds metadata,
    normalises scoring, and emits the final report to state.
    """
    ticker = state.get("ticker", "")
    question = state.get("question", "")
    tool_results = state.get("tool_results", {})

    rag_output = tool_results.get("rag_agent", {})

    if not rag_output:
        logger.warning("Report agent: no RAG output found in state")
        final_report = {
            "ticker": ticker,
            "question": question,
            "status": "failed",
            "error": "No analysis output available from RAG agent.",
            "generated_at": datetime.utcnow().isoformat(),
        }
        return Command(
            goto="__end__",
            update={
                "messages": [AIMessage(
                    content="Report generation failed — no RAG analysis available.",
                    name="report_agent",
                )],
                "final_report": final_report,
            },
        )

    # Build the final report with metadata. risk_score is intentionally
    # nullable — when retrieval is sparse the RAG agent surfaces null
    # rather than a fabricated placeholder.
    raw_score = rag_output.get("risk_score")
    final_report = {
        "ticker": ticker,
        "question": question,
        "status": "completed",
        "generated_at": datetime.utcnow().isoformat(),
        # Core analysis from RAG agent
        "summary": rag_output.get("summary", ""),
        "risk_score": raw_score,
        "risk_rationale": rag_output.get("risk_rationale", ""),
        "risk_level": _score_to_level(raw_score),
        "confidence": rag_output.get("confidence", "unknown"),
        # Structured data
        "key_metrics": rag_output.get("key_metrics", []),
        "citations": rag_output.get("citations", []),
        # Metadata
        "data_agent_results": tool_results.get("data_agent", {}),
        "retrieved_docs_count": len(state.get("retrieved_docs", [])),
    }

    # Build a human-readable final message
    report_text = _format_report_text(final_report)

    logger.info(
        "Report agent: generated report for %s (risk=%s, level=%s)",
        ticker, final_report["risk_score"], final_report["risk_level"],
    )

    job_id = state.get("job_id")
    if job_id:
        risk_msg = (
            f"Report finalized — risk {final_report['risk_score']}/100 "
            f"({final_report['risk_level']})."
            if final_report["risk_score"] is not None
            else "Report finalized — risk score unavailable (insufficient data)."
        )
        publish(job_id, {
            "type": "progress",
            "stage": "report",
            "message": risk_msg,
            "percent": 98,
        })

    return Command(
        goto="__end__",
        update={
            "messages": [AIMessage(content=report_text, name="report_agent")],
            "final_report": final_report,
        },
    )


def _score_to_level(score: int | None) -> str:
    """Convert numeric risk score to a human-readable level. Returns 'UNKNOWN' for None."""
    if score is None:
        return "UNKNOWN"
    if score <= 25:
        return "LOW"
    elif score <= 50:
        return "MODERATE"
    elif score <= 75:
        return "ELEVATED"
    else:
        return "HIGH"


def _format_report_text(report: dict) -> str:
    """Format the report dict into readable text."""
    risk_score = report.get("risk_score")
    risk_line = (
        f"Score: {risk_score}/100 ({report['risk_level']})"
        if risk_score is not None
        else "Score: insufficient data"
    )
    rationale_line = (
        f"Rationale: {report['risk_rationale']}"
        if report.get("risk_rationale")
        else "Rationale: —"
    )
    lines = [
        f"{'=' * 60}",
        f"  FINSIGHT RESEARCH REPORT — {report['ticker']}",
        f"{'=' * 60}",
        "",
        f"Question: {report['question']}",
        f"Generated: {report['generated_at']}",
        f"Confidence: {report['confidence'].upper()}",
        "",
        "--- Risk Assessment ---",
        risk_line,
        rationale_line,
        "",
        "--- Summary ---",
        f"{report['summary']}",
    ]

    if report.get("key_metrics"):
        lines.append("\n--- Key Metrics ---")
        for m in report["key_metrics"]:
            name = m.get("name", "")
            value = m.get("value", "")
            trend = m.get("trend", "")
            context = m.get("context", "")
            lines.append(f"  {name}: {value} ({trend}) — {context}")

    if report.get("citations"):
        lines.append("\n--- Citations ---")
        for c in report["citations"]:
            lines.append(f"  [Source {c.get('source_index', '?')}] {c.get('doc_type', '')}: {c.get('excerpt', '')[:100]}")

    lines.append(f"\n{'=' * 60}")
    return "\n".join(lines)

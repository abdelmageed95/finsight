"""POST /analyze — submit a research request as an async background task.

POST /analyze/check — check if a ticker has already been analyzed for this user.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update

from api import event_bus
from api.dependencies import CurrentUser, DbSession
from api.schemas import AnalyzeRequest, AnalyzeResponse, CompareRequest, CompareResponse
from db.models import AnalysisReport, Conversation

router = APIRouter(tags=["analyze"])
logger = logging.getLogger(__name__)


@router.get("/analyze/check/{ticker}")
async def check_existing(
    ticker: str,
    db: DbSession,
    user: CurrentUser,
):
    """Check whether a completed analysis already exists for this user+ticker."""
    symbol = ticker.upper()
    result = await db.execute(
        select(AnalysisReport)
        .where(
            AnalysisReport.user_id == user.id,
            AnalysisReport.ticker_symbol == symbol,
            AnalysisReport.status == "completed",
        )
        .order_by(AnalysisReport.created_at.desc())
        .limit(1)
    )
    existing = result.scalar_one_or_none()

    if existing:
        return {
            "exists": True,
            "job_id": existing.job_id,
            "ticker": symbol,
            "created_at": existing.created_at.isoformat() if existing.created_at else None,
            "summary_preview": (existing.summary or "")[:150],
        }
    return {"exists": False, "ticker": symbol}


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    request: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    db: DbSession,
    user: CurrentUser,
):
    """Submit a stock analysis request.

    Creates a job record in the DB, kicks off the LangGraph pipeline
    in the background, and returns the job_id immediately.

    If re-analyzing (force=true or existing report), overwrites the old report.
    Also ensures a conversation exists for this user+ticker.
    """
    job_id = str(uuid.uuid4())
    ticker = request.ticker.upper()

    # Create the job record
    report = AnalysisReport(
        job_id=job_id,
        user_id=user.id,
        ticker_symbol=ticker,
        question=request.question,
        status="pending",
    )
    db.add(report)

    # Ensure a conversation exists for this user+ticker
    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.user_id == user.id,
            Conversation.ticker == ticker,
        )
    )
    if not conv_result.scalar_one_or_none():
        conv = Conversation(
            user_id=user.id,
            ticker=ticker,
            title=f"{ticker} research",
        )
        db.add(conv)

    await db.commit()

    logger.info("Created analysis job %s for %s", job_id, ticker)

    # Run the graph in the background
    background_tasks.add_task(
        _run_analysis_background,
        job_id=job_id,
        ticker=ticker,
        question=request.question,
        user_id=str(user.id),
    )

    return AnalyzeResponse(job_id=job_id, status="pending", message="Analysis started")


async def _run_analysis_background(
    job_id: str, ticker: str, question: str, user_id: str
):
    """Background task that runs the full LangGraph pipeline.

    On completion, marks the prior completed report for this user+ticker+question
    as overwritten — distinct questions each keep their own report.
    """
    from agents.orchestrator import build_graph
    from db.session import async_session_factory
    from langchain_core.messages import HumanMessage

    logger.info("Background: starting analysis %s for %s", job_id, ticker)

    # Update status to running
    async with async_session_factory() as session:
        await session.execute(
            update(AnalysisReport)
            .where(AnalysisReport.job_id == job_id)
            .values(status="running")
        )
        await session.commit()

    try:
        # Build and invoke the graph
        graph = build_graph()
        config = {"configurable": {"thread_id": job_id}}

        initial_state = {
            "messages": [HumanMessage(content=f"[{ticker}] {question}")],
            "ticker": ticker,
            "question": question,
            "intent": "research_query",
            "job_id": job_id,
            "retrieved_docs": [],
            "tool_results": {},
            "final_report": {},
        }

        event_bus.publish(job_id, {
            "type": "progress",
            "stage": "data",
            "message": f"Starting analysis of {ticker}…",
            "percent": 5,
        })

        # Run synchronously in a thread (graph.invoke is sync)
        result = await asyncio.to_thread(graph.invoke, initial_state, config)
        final_report = result.get("final_report", {})

        async with async_session_factory() as session:
            # Mark only the prior completed report for the SAME question as
            # overwritten. Different questions each keep their own report so
            # the Research tab shows one entry per distinct question.
            await session.execute(
                update(AnalysisReport)
                .where(
                    AnalysisReport.user_id == user_id,
                    AnalysisReport.ticker_symbol == ticker,
                    AnalysisReport.question == question,
                    AnalysisReport.status == "completed",
                    AnalysisReport.job_id != job_id,
                )
                .values(status="overwritten")
            )

            # Persist the new completed report
            await session.execute(
                update(AnalysisReport)
                .where(AnalysisReport.job_id == job_id)
                .values(
                    status="completed",
                    summary=final_report.get("summary", ""),
                    risk_score=final_report.get("risk_score"),
                    report_json=json.dumps(final_report, default=str),
                    completed_at=datetime.utcnow(),
                )
            )
            await session.commit()

        logger.info("Background: analysis %s completed (risk=%s)", job_id, final_report.get("risk_score"))
        event_bus.publish(job_id, {
            "type": "done",
            "percent": 100,
            "report": final_report,
            "message": "Analysis complete.",
        })

    except Exception as e:
        logger.exception("Background: analysis %s failed", job_id)
        async with async_session_factory() as session:
            await session.execute(
                update(AnalysisReport)
                .where(AnalysisReport.job_id == job_id)
                .values(status="failed", summary=str(e))
            )
            await session.commit()
        event_bus.publish(job_id, {
            "type": "error",
            "message": f"Analysis failed: {e}",
        })

    finally:
        event_bus.close(job_id)


# ---------------------------------------------------------------------------
# SSE — live progress for an in-flight analysis
# ---------------------------------------------------------------------------

@router.get("/analyze/stream/{job_id}")
async def stream_progress(
    job_id: str,
    db: DbSession,
    user: CurrentUser,
):
    """Server-sent events for an in-flight analysis.

    Subscribes to the in-process event bus and forwards every progress event
    to the client. Closes when the analysis emits a `done` or `error` event,
    or after a 5-minute idle timeout. If the job is already complete, the
    stream emits a single `done` event from the persisted report and closes.
    """
    # Fast path: if the report already exists, skip the bus entirely
    result = await db.execute(
        select(AnalysisReport).where(AnalysisReport.job_id == job_id)
    )
    report = result.scalar_one_or_none()
    if not report or report.user_id != user.id:
        raise HTTPException(status_code=404, detail="Job not found")

    if report.status in ("completed", "failed"):
        async def cached_stream():
            payload = {
                "type": "done" if report.status == "completed" else "error",
                "percent": 100,
                "message": "Already complete.",
            }
            if report.report_json:
                try:
                    payload["report"] = json.loads(report.report_json)
                except Exception:
                    pass
            yield f"data: {json.dumps(payload)}\n\n"
        return StreamingResponse(
            cached_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async def event_stream():
        try:
            async for event in event_bus.subscribe(job_id, timeout_seconds=300.0):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            logger.exception("SSE stream error for job %s", job_id)
            yield f'data: {json.dumps({"type": "error", "message": str(e)})}\n\n'

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Comparison endpoint
# ---------------------------------------------------------------------------

@router.post("/analyze/compare", response_model=CompareResponse)
async def compare(
    request: CompareRequest,
    background_tasks: BackgroundTasks,
    db: DbSession,
    user: CurrentUser,
):
    """Compare two tickers side-by-side.

    Requires completed reports for both tickers. Runs the comparison LLM
    in the background and stores the result in an AnalysisReport with
    ticker_symbol = "TICKER_A_vs_TICKER_B".
    """
    job_id = str(uuid.uuid4())
    ticker_a = request.ticker_a.upper()
    ticker_b = request.ticker_b.upper()

    # Find latest completed reports for both tickers
    report_a = (
        await db.execute(
            select(AnalysisReport).where(
                AnalysisReport.user_id == user.id,
                AnalysisReport.ticker_symbol == ticker_a,
                AnalysisReport.status == "completed",
            ).order_by(AnalysisReport.created_at.desc()).limit(1)
        )
    ).scalar_one_or_none()

    report_b = (
        await db.execute(
            select(AnalysisReport).where(
                AnalysisReport.user_id == user.id,
                AnalysisReport.ticker_symbol == ticker_b,
                AnalysisReport.status == "completed",
            ).order_by(AnalysisReport.created_at.desc()).limit(1)
        )
    ).scalar_one_or_none()

    # Store comparison job
    comparison_label = f"{ticker_a}_vs_{ticker_b}"
    report = AnalysisReport(
        job_id=job_id,
        user_id=user.id,
        ticker_symbol=comparison_label,
        question=f"Compare {ticker_a} vs {ticker_b}",
        status="pending",
    )
    db.add(report)
    await db.commit()

    # Get report JSONs (may be None if not yet analyzed)
    report_a_json = report_a.report_json if report_a else None
    report_b_json = report_b.report_json if report_b else None

    background_tasks.add_task(
        _run_comparison_background,
        job_id=job_id,
        ticker_a=ticker_a,
        ticker_b=ticker_b,
        report_a_json=report_a_json,
        report_b_json=report_b_json,
    )

    return CompareResponse(
        job_id=job_id,
        status="pending",
        ticker_a=ticker_a,
        ticker_b=ticker_b,
    )


async def _run_comparison_background(
    job_id: str,
    ticker_a: str,
    ticker_b: str,
    report_a_json: str | None,
    report_b_json: str | None,
):
    """Background task that runs the comparison LLM."""
    from db.session import async_session_factory

    logger.info("Background: starting comparison %s (%s vs %s)", job_id, ticker_a, ticker_b)

    async with async_session_factory() as session:
        await session.execute(
            update(AnalysisReport)
            .where(AnalysisReport.job_id == job_id)
            .values(status="running")
        )
        await session.commit()

    try:
        from rag.prompts import COMPARISON_SYSTEM_PROMPT, COMPARISON_USER_PROMPT
        from rag.schemas import ComparisonReport
        import os

        report_a_text = report_a_json or f"No completed report available for {ticker_a}."
        report_b_text = report_b_json or f"No completed report available for {ticker_b}."

        system_msg = COMPARISON_SYSTEM_PROMPT.format(
            ticker_a=ticker_a,
            ticker_b=ticker_b,
            report_a=report_a_text,
            report_b=report_b_text,
        )
        user_msg = COMPARISON_USER_PROMPT.format(
            ticker_a=ticker_a,
            ticker_b=ticker_b,
        )

        from langchain_anthropic import ChatAnthropic

        llm = ChatAnthropic(
            model="claude-haiku-4-5-20251001",
            temperature=0.2,
            max_tokens=4096,
            api_key=os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY"),
        )
        structured_llm = llm.with_structured_output(ComparisonReport)

        result = await asyncio.to_thread(
            structured_llm.invoke,
            [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
        )

        comparison_data = result.model_dump() if result else {}

        async with async_session_factory() as session:
            await session.execute(
                update(AnalysisReport)
                .where(AnalysisReport.job_id == job_id)
                .values(
                    status="completed",
                    summary=comparison_data.get("summary", ""),
                    report_json=json.dumps(comparison_data, default=str),
                    completed_at=datetime.utcnow(),
                )
            )
            await session.commit()

        logger.info("Background: comparison %s completed", job_id)

    except Exception as e:
        logger.exception("Background: comparison %s failed", job_id)
        async with async_session_factory() as session:
            await session.execute(
                update(AnalysisReport)
                .where(AnalysisReport.job_id == job_id)
                .values(status="failed", summary=str(e))
            )
            await session.commit()

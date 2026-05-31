"""Data Agent node — fetches market data and SEC filings for a ticker.

This is "The Collector". It has no LLM calls — it's a pure data engineering
agent that fetches, cleans, and stores raw financial data.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.messages import AIMessage
from langgraph.types import Command

from api.event_bus import publish

if TYPE_CHECKING:
    from agents.orchestrator import GraphState

logger = logging.getLogger(__name__)


def _progress(state: "GraphState", message: str, percent: int) -> None:
    """Publish a progress event to the SSE bus if a job_id is present."""
    job_id = state.get("job_id")
    if not job_id:
        return
    publish(job_id, {"type": "progress", "stage": "data", "message": message, "percent": percent})

# Freshness TTLs — if the ticker row was updated within these windows, the
# corresponding pipeline is skipped. Market data is cheap-ish and volatile, so
# we refresh it often. SEC filings are rarely updated and hitting EDGAR is
# costly, so we only re-check once a day.
MARKET_TTL = timedelta(minutes=15)
SEC_TTL = timedelta(hours=24)


def data_agent_node(state: "GraphState") -> Command[Literal["supervisor"]]:
    """Fetch market data and SEC filings for the ticker in state.

    Runs the Week 1 pipelines (market_data + sec_filings + embedder) and
    reports results back to the supervisor via a message.
    """
    ticker = state.get("ticker", "")
    if not ticker:
        return Command(
            goto="supervisor",
            update={
                "messages": [AIMessage(content="No ticker provided. Cannot fetch data.", name="data_agent")],
                "tool_results": {"data_agent": {"error": "no ticker"}},
            },
        )

    logger.info("Data agent: fetching data for %s", ticker)
    _progress(state, f"Fetching market data and SEC filings for {ticker}…", 10)

    # Run the async pipelines — handle both cases:
    # 1. Running in main thread with event loop (direct invoke)
    # 2. Running in a background thread (via asyncio.to_thread)
    try:
        asyncio.get_running_loop()
        # We're inside an async context — use nest_asyncio or run in new loop
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            results = pool.submit(asyncio.run, _fetch_all(ticker)).result()
    except RuntimeError:
        # No running loop — safe to use asyncio.run directly
        results = asyncio.run(_fetch_all(ticker))

    summary_parts = [f"Data Agent completed for {ticker}:"]
    market = results["market"]
    if market.get("skipped"):
        summary_parts.append("- Market data: cache hit (skipped)")
    else:
        price_src = market.get("price_source", "unknown")
        fin_src = market.get("financials_source", "unknown")
        summary_parts.append(
            f"- Market data: {market.get('prices_inserted', 0)} new prices"
            f" (prices via {price_src}, financials via {fin_src})"
        )
    sec = results["sec"]
    if sec.get("skipped"):
        summary_parts.append("- SEC filings: cache hit (skipped)")
    else:
        summary_parts.append(f"- SEC filings: {sec.get('filings_ingested', 0)} filings downloaded")
    news = results.get("news", {})
    news_src = news.get("source", "none")
    summary_parts.append(f"- News: {news.get('inserted', 0)} new articles (via {news_src})")
    summary_parts.append(f"- Embeddings: {results['embed'].get('total_chunks', 0)} new chunks embedded")

    if results.get("errors"):
        summary_parts.append(f"- Errors: {', '.join(results['errors'])}")

    summary = "\n".join(summary_parts)
    logger.info(summary)

    # Build a user-friendly progress recap (one short line)
    bits: list[str] = []
    if not market.get("skipped"):
        n_prices = market.get("prices_inserted", 0)
        if n_prices:
            bits.append(f"{n_prices} new price bars")
    if not sec.get("skipped"):
        n_filings = sec.get("filings_ingested", 0)
        if n_filings:
            bits.append(f"{n_filings} new SEC filings")
    n_chunks = results.get("embed", {}).get("total_chunks", 0)
    if n_chunks:
        bits.append(f"{n_chunks} chunks embedded")
    if not bits:
        bits.append("data already fresh — using cache")
    _progress(state, "Data ready: " + ", ".join(bits) + ".", 35)

    # Lift the financial-history block out to a top-level state field so the
    # RAG agent can read it directly (and it doesn't bloat tool_results).
    financial_context = results.pop("financial_context", "")

    return Command(
        goto="supervisor",
        update={
            "messages": [AIMessage(content=summary, name="data_agent")],
            "tool_results": {"data_agent": results},
            "financial_context": financial_context,
        },
    )


async def _fetch_all(ticker: str) -> dict:
    """Run all data pipelines for a ticker, skipping fresh data."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from db.models import Ticker
    from db.session import DATABASE_URL
    from pipelines.embedder import embed_all_pending
    from pipelines.market_data import ingest_market_data
    from pipelines.news_fetcher import ingest_news
    from pipelines.sec_filings import ingest_sec_filings

    # Build a fresh engine bound to the current event loop. The module-level
    # engine in db.session is bound to the main FastAPI loop; when this coroutine
    # runs inside a worker thread (via asyncio.run in a new loop), reusing that
    # engine yields "Future attached to a different loop" errors from asyncpg.
    local_engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    local_session_factory = async_sessionmaker(local_engine, class_=AsyncSession, expire_on_commit=False)

    errors = []
    market_result: dict[str, Any] = {"skipped": False}
    sec_result: dict[str, Any] = {"skipped": False}
    news_result: dict[str, Any] = {}
    embed_result: dict[str, Any] = {}

    async with local_session_factory() as session:
        # --- Freshness check ------------------------------------------------
        existing = await session.execute(
            select(Ticker).where(Ticker.symbol == ticker.upper())
        )
        ticker_row = existing.scalar_one_or_none()
        now = datetime.utcnow()
        age = now - ticker_row.updated_at if ticker_row else None

        skip_market = age is not None and age < MARKET_TTL
        skip_sec = age is not None and age < SEC_TTL

        if skip_market:
            logger.info(
                "Data agent: skipping market_data for %s (fresh, age=%s)",
                ticker, age,
            )
            market_result = {"skipped": True, "reason": "fresh", "age_seconds": age.total_seconds()}
        else:
            try:
                market_result = await ingest_market_data(session, ticker)
            except Exception as e:
                logger.exception("Data agent: market data failed for %s", ticker)
                errors.append(f"market_data: {e}")

        if skip_sec:
            logger.info(
                "Data agent: skipping sec_filings for %s (fresh, age=%s)",
                ticker, age,
            )
            sec_result = {"skipped": True, "reason": "fresh", "age_seconds": age.total_seconds()}
        else:
            try:
                sec_result = await ingest_sec_filings(session, ticker)
            except Exception as e:
                logger.exception("Data agent: SEC filings failed for %s", ticker)
                errors.append(f"sec_filings: {e}")

        # --- News (always fetch — cheap and keeps sentiment fresh) ---
        try:
            news_result = await ingest_news(session, ticker)
        except Exception as e:
            logger.exception("Data agent: news fetch failed for %s", ticker)
            errors.append(f"news: {e}")

        # Embedder is always cheap when there are no pending filings, so we
        # always call it — it short-circuits internally if nothing is pending.
        try:
            embed_result = await embed_all_pending(session)
        except Exception as e:
            logger.exception("Data agent: embedding failed for %s", ticker)
            errors.append(f"embedder: {e}")

        # Build the structured financial-history block from the stored
        # financials/prices tables — fed to the RAG prompt so the analyst
        # has authoritative multi-year numbers, not just filing text.
        financial_context = ""
        try:
            from pipelines.financial_summary import build_financial_context
            financial_context = await build_financial_context(session, ticker)
        except Exception as e:
            logger.exception("Data agent: financial summary failed for %s", ticker)
            errors.append(f"financial_summary: {e}")

    await local_engine.dispose()

    return {
        "market": market_result,
        "sec": sec_result,
        "news": news_result,
        "embed": embed_result,
        "financial_context": financial_context,
        "errors": errors,
    }

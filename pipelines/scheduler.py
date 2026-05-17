"""APScheduler cron jobs for periodic data ingestion."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def scheduled_ingest():
    """Run the full ingestion pipeline for tracked tickers."""
    from db.session import async_session_factory
    from db.models import Ticker
    from sqlalchemy import select

    from pipelines.market_data import ingest_market_data
    from pipelines.sec_filings import ingest_sec_filings
    from pipelines.news_fetcher import ingest_news
    from pipelines.embedder import embed_all_pending

    async with async_session_factory() as session:
        result = await session.execute(select(Ticker))
        tickers = result.scalars().all()

        for ticker in tickers:
            try:
                await ingest_market_data(session, ticker.symbol)
                await ingest_sec_filings(session, ticker.symbol)
                await ingest_news(session, ticker.symbol)
            except Exception:
                logger.exception("Failed to ingest data for %s", ticker.symbol)

        try:
            await embed_all_pending(session)
        except Exception:
            logger.exception("Failed to embed pending filings")


def start_scheduler():
    """Register jobs and start the scheduler."""
    scheduler.add_job(scheduled_ingest, "interval", hours=6, id="ingest_pipeline")
    scheduler.start()
    logger.info("Scheduler started — ingestion runs every 6 hours")


def stop_scheduler():
    scheduler.shutdown(wait=False)

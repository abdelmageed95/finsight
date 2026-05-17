"""CLI script to ingest data for a ticker — used for testing the Week 1 pipeline.

Usage:
    python -m scripts.ingest_ticker AAPL
"""

from __future__ import annotations

import asyncio
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def main(symbol: str):
    from db.session import async_session_factory
    from pipelines.market_data import ingest_market_data
    from pipelines.sec_filings import ingest_sec_filings
    from pipelines.embedder import embed_all_pending

    async with async_session_factory() as session:
        # Step 1: Market data
        logger.info("=== Step 1: Ingesting market data ===")
        try:
            market_result = await ingest_market_data(session, symbol)
            logger.info("Market data result: %s", market_result)
        except Exception:
            logger.exception("Step 1 failed")

        # Step 2: SEC filings
        logger.info("=== Step 2: Ingesting SEC filings ===")
        try:
            sec_result = await ingest_sec_filings(session, symbol)
            logger.info("SEC filings result: %s", sec_result)
        except Exception:
            logger.exception("Step 2 failed")

        # Step 3: Embed any new filings
        logger.info("=== Step 3: Embedding filings ===")
        try:
            embed_result = await embed_all_pending(session)
            logger.info("Embedding result: %s", embed_result)
        except Exception:
            logger.exception("Step 3 failed")

    logger.info("=== Done! ===")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.ingest_ticker <TICKER>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))

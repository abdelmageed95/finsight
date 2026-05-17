"""Financial news fetching with multi-source fallback.

Provider chain: Alpha Vantage → EODHD → Tiingo
Fetches articles, persists to the news_articles table, deduplicates by URL.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.crud import get_or_create_ticker
from db.models import NewsArticle
from pipelines import eodhd, massive, tiingo

logger = logging.getLogger(__name__)

ALPHA_VANTAGE_BASE = "https://www.alphavantage.co/query"


# ===================================================================
# Alpha Vantage (primary — has per-ticker sentiment)
# ===================================================================

async def _fetch_news_alpha_vantage(symbol: str, limit: int = 20) -> list[dict]:
    """Fetch recent news articles and sentiment via Alpha Vantage."""
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        logger.debug("ALPHA_VANTAGE_API_KEY not set, skipping")
        return []

    params = {
        "function": "NEWS_SENTIMENT",
        "tickers": symbol.upper(),
        "limit": limit,
        "apikey": api_key,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(ALPHA_VANTAGE_BASE, params=params)
        resp.raise_for_status()
        data = resp.json()

    feed = data.get("feed", [])
    articles = []
    for item in feed:
        # Find ticker-specific sentiment
        ticker_sentiment = {}
        for ts in item.get("ticker_sentiment", []):
            if ts.get("ticker", "").upper() == symbol.upper():
                ticker_sentiment = ts
                break

        pub_str = item.get("time_published", "")
        published_at = None
        if pub_str:
            try:
                published_at = datetime.strptime(pub_str[:15], "%Y%m%dT%H%M%S")
            except ValueError:
                pass

        score_str = ticker_sentiment.get("ticker_sentiment_score", "")
        try:
            score = float(score_str) if score_str else None
        except (ValueError, TypeError):
            score = None

        articles.append({
            "title": item.get("title", ""),
            "summary": item.get("summary", ""),
            "url": item.get("url", ""),
            "source": item.get("source", ""),
            "published_at": published_at,
            "sentiment_score": score,
            "sentiment_label": ticker_sentiment.get(
                "ticker_sentiment_label",
                item.get("overall_sentiment_label", ""),
            ),
        })

    return articles


# ===================================================================
# Fallback-aware fetch
# ===================================================================

async def fetch_news_sentiment(symbol: str, limit: int = 20) -> tuple[list[dict], str]:
    """Fetch news with multi-source fallback.

    Returns (articles, source_name).
    """
    # 1. Alpha Vantage (has sentiment scores)
    try:
        articles = await _fetch_news_alpha_vantage(symbol, limit)
        if articles:
            logger.info("Alpha Vantage: fetched %d news articles for %s", len(articles), symbol)
            return articles, "alpha_vantage"
    except Exception as e:
        logger.debug("Alpha Vantage news failed for %s: %s", symbol, e)

    # 2. Massive (has per-ticker sentiment insights)
    try:
        articles = await massive.fetch_news(symbol, limit)
        if articles:
            return articles, "massive"
    except Exception as e:
        logger.debug("Massive news failed for %s: %s", symbol, e)

    # 3. EODHD
    try:
        articles = await eodhd.fetch_news(symbol, limit)
        if articles:
            return articles, "eodhd"
    except Exception as e:
        logger.debug("EODHD news failed for %s: %s", symbol, e)

    # 4. Tiingo
    try:
        articles = await tiingo.fetch_news(symbol, limit)
        if articles:
            return articles, "tiingo"
    except Exception as e:
        logger.debug("Tiingo news failed for %s: %s", symbol, e)

    logger.warning("All news providers returned empty for %s", symbol)
    return [], "none"


# ===================================================================
# Persistence
# ===================================================================

async def ingest_news(session: AsyncSession, symbol: str) -> dict:
    """Fetch news (with fallback) and persist to DB.

    Returns summary dict with count and source.
    """
    symbol = symbol.upper()
    articles, source = await fetch_news_sentiment(symbol)
    if not articles:
        return {"inserted": 0, "source": source}

    ticker = await get_or_create_ticker(session, symbol)
    inserted = 0
    now = datetime.utcnow()

    for art in articles:
        stmt = (
            pg_insert(NewsArticle)
            .values(
                ticker_id=ticker.id,
                title=art["title"],
                url=art["url"],
                source=art["source"],
                published_at=art["published_at"],
                summary=art["summary"],
                sentiment_score=art["sentiment_score"],
                sentiment_label=art["sentiment_label"],
                fetched_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_news_ticker_url")
        )
        result = await session.execute(stmt)
        inserted += result.rowcount

    await session.commit()
    logger.info("Inserted %d new articles for %s (via %s)", inserted, symbol, source)
    return {"inserted": inserted, "source": source}

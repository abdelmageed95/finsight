"""Tiingo provider — EOD prices and news with sentiment.

Tiingo has good US and international coverage. Used as a final fallback
for market data and as a secondary news source (has built-in sentiment).

API docs: https://www.tiingo.com/documentation
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.tiingo.com"


def _headers() -> dict:
    api_key = os.getenv("TIINGO_API_KEY")
    if not api_key:
        return {}
    return {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# OHLCV prices
# ---------------------------------------------------------------------------

async def fetch_ohlcv(symbol: str, days: int = 90) -> list[dict]:
    """Fetch daily EOD prices from Tiingo.

    Args:
        symbol: Ticker symbol (Tiingo uses plain symbols for US,
                and exchange-suffixed for international).
        days: Number of historical days.

    Returns list of dicts matching the Price model schema.
    """
    headers = _headers()
    if not headers:
        logger.warning("TIINGO_API_KEY not set, skipping")
        return []

    start_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    # Tiingo uses bare symbol for US tickers
    bare_symbol = symbol.split(".")[0] if "." in symbol else symbol

    params = {"startDate": start_date}

    try:
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            resp = await client.get(
                f"{BASE_URL}/tiingo/daily/{bare_symbol}/prices",
                params=params,
            )
            if resp.status_code != 200:
                logger.debug("Tiingo returned %d for %s", resp.status_code, symbol)
                return []
            data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("Tiingo OHLCV fetch failed for %s: %s", symbol, e)
        return []

    if not isinstance(data, list):
        return []

    records = []
    for row in data:
        try:
            # Tiingo dates are ISO format: "2026-04-10T00:00:00+00:00"
            dt_str = row.get("date", "")
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00")).replace(tzinfo=None)
            records.append({
                "date": dt,
                "open": float(row.get("adjOpen", row.get("open", 0))),
                "high": float(row.get("adjHigh", row.get("high", 0))),
                "low": float(row.get("adjLow", row.get("low", 0))),
                "close": float(row.get("adjClose", row.get("close", 0))),
                "volume": float(row.get("adjVolume", row.get("volume", 0))),
            })
        except (KeyError, ValueError) as e:
            logger.debug("Skipping malformed Tiingo row: %s", e)

    logger.info("Tiingo: fetched %d price records for %s", len(records), symbol)
    return records


# ---------------------------------------------------------------------------
# Company metadata
# ---------------------------------------------------------------------------

async def fetch_profile(symbol: str) -> dict:
    """Fetch company metadata from Tiingo.

    Returns dict with keys matching Ticker model where possible.
    Note: Tiingo's meta endpoint has limited fields (name, description, exchange).
    """
    headers = _headers()
    if not headers:
        return {}

    bare_symbol = symbol.split(".")[0] if "." in symbol else symbol

    try:
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            resp = await client.get(f"{BASE_URL}/tiingo/daily/{bare_symbol}")
            if resp.status_code != 200:
                return {}
            data = resp.json()
    except (httpx.HTTPError, ValueError):
        return {}

    if not data.get("name"):
        return {}

    return {
        "company_name": data.get("name", ""),
        "sector": "",  # Tiingo meta doesn't include sector
        "industry": "",
        "market_cap": None,
    }


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------

async def fetch_news(symbol: str, limit: int = 20) -> list[dict]:
    """Fetch recent news articles from Tiingo news feed.

    Tiingo includes article tags and source info but no per-ticker
    sentiment score. Returns list of dicts matching NewsArticle model.
    """
    headers = _headers()
    if not headers:
        logger.warning("TIINGO_API_KEY not set, skipping news fetch")
        return []

    bare_symbol = symbol.split(".")[0] if "." in symbol else symbol

    params = {
        "tickers": bare_symbol,
        "limit": limit,
        "sortBy": "crawlDate",
    }

    try:
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            resp = await client.get(f"{BASE_URL}/news", params=params)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("Tiingo news fetch failed for %s: %s", symbol, e)
        return []

    if not isinstance(data, list):
        return []

    articles = []
    for item in data:
        published_at = None
        pub_str = item.get("publishedDate", "")
        if pub_str:
            try:
                published_at = datetime.fromisoformat(pub_str.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                pass

        articles.append({
            "title": item.get("title", ""),
            "summary": item.get("description", "")[:500],
            "url": item.get("url", ""),
            "source": item.get("source", ""),
            "published_at": published_at,
            "sentiment_score": None,  # Tiingo doesn't provide sentiment scores
            "sentiment_label": None,
        })

    logger.info("Tiingo: fetched %d news articles for %s", len(articles), symbol)
    return articles

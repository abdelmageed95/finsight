"""Massive (formerly Polygon.io) provider — OHLCV, fundamentals, and news.

Massive covers all US exchanges with high-quality data. Provides excellent
company financials (income statements, balance sheets), news with per-ticker
sentiment via insights, and real-time/historical aggregates.

API docs: https://massive.com/docs
Base URL: https://api.massive.com (also https://api.polygon.io for legacy compat)
Auth: Bearer token in Authorization header.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.massive.com"


def _api_key() -> str | None:
    return os.getenv("MASSIVE_API_KEY")


def _auth_headers() -> dict | None:
    api_key = _api_key()
    if not api_key:
        return None
    return {"Authorization": f"Bearer {api_key}"}


# ---------------------------------------------------------------------------
# OHLCV prices via aggregates (bars)
# GET /v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to}
# ---------------------------------------------------------------------------

async def fetch_ohlcv(symbol: str, days: int = 90) -> list[dict]:
    """Fetch daily OHLCV bars from Massive.

    Args:
        symbol: Ticker symbol (e.g. "AAPL"). Massive covers US exchanges.
        days: Number of historical days.

    Returns list of dicts matching the Price model schema.
    """
    headers = _auth_headers()
    if not headers:
        logger.warning("MASSIVE_API_KEY not set, skipping")
        return []

    date_from = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    date_to = datetime.utcnow().strftime("%Y-%m-%d")
    bare_symbol = symbol.split(".")[0] if "." in symbol else symbol

    url = (
        f"{BASE_URL}/v2/aggs/ticker/{bare_symbol}/range/1/day"
        f"/{date_from}/{date_to}"
    )
    params = {"adjusted": "true", "sort": "asc", "limit": 5000}

    try:
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                logger.debug("Massive returned %d for %s", resp.status_code, symbol)
                return []
            data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("Massive OHLCV fetch failed for %s: %s", symbol, e)
        return []

    if data.get("status") != "OK" or not data.get("results"):
        return []

    records = []
    for bar in data["results"]:
        try:
            # bar["t"] is Unix millisecond timestamp
            dt = datetime.utcfromtimestamp(bar["t"] / 1000)
            records.append({
                "date": dt,
                "open": float(bar["o"]),
                "high": float(bar["h"]),
                "low": float(bar["l"]),
                "close": float(bar["c"]),
                "volume": float(bar["v"]),
            })
        except (KeyError, ValueError, TypeError) as e:
            logger.debug("Skipping malformed Massive bar: %s", e)

    logger.info("Massive: fetched %d price records for %s", len(records), symbol)
    return records


# ---------------------------------------------------------------------------
# Ticker details / company profile
# GET /v3/reference/tickers/{ticker}
# ---------------------------------------------------------------------------

async def fetch_profile(symbol: str) -> dict:
    """Fetch company profile from Massive ticker overview.

    Returns dict with keys matching Ticker model where possible.
    """
    headers = _auth_headers()
    if not headers:
        return {}

    bare_symbol = symbol.split(".")[0] if "." in symbol else symbol

    try:
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            resp = await client.get(f"{BASE_URL}/v3/reference/tickers/{bare_symbol}")
            if resp.status_code != 200:
                return {}
            data = resp.json()
    except (httpx.HTTPError, ValueError):
        return {}

    results = data.get("results", {})
    if not results.get("name"):
        return {}

    return {
        "company_name": results.get("name", ""),
        "sector": results.get("sic_description", ""),
        "industry": results.get("sic_description", ""),
        "market_cap": _to_float(results.get("market_cap")),
    }


# ---------------------------------------------------------------------------
# Income statements (quarterly + annual financials)
# GET /stocks/financials/v1/income-statements
# ---------------------------------------------------------------------------

async def fetch_income_statements(symbol: str, timeframe: str = "quarterly", limit: int = 12) -> list[dict]:
    """Fetch income statement data from Massive.

    Args:
        symbol: Ticker symbol.
        timeframe: "quarterly" or "annual".
        limit: Max number of periods.

    Returns list of period dicts matching Financials model.
    """
    headers = _auth_headers()
    if not headers:
        return []

    bare_symbol = symbol.split(".")[0] if "." in symbol else symbol

    params = {
        "tickers": bare_symbol,
        "timeframe": timeframe,
        "limit": limit,
        "sort": "period_end.desc",
    }

    try:
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            resp = await client.get(
                f"{BASE_URL}/stocks/financials/v1/income-statements",
                params=params,
            )
            if resp.status_code != 200:
                logger.debug("Massive income statements returned %d for %s", resp.status_code, symbol)
                return []
            data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("Massive income statements failed for %s: %s", symbol, e)
        return []

    results = data.get("results", [])
    if not results:
        return []

    periods = []
    for stmt in results:
        try:
            fiscal_year = stmt.get("fiscal_year")
            fiscal_quarter = stmt.get("fiscal_quarter")

            if timeframe == "quarterly" and fiscal_year and fiscal_quarter:
                label = f"{fiscal_year}-Q{fiscal_quarter}"
            elif fiscal_year:
                label = f"{fiscal_year}-FY"
            else:
                continue

            revenue = _to_float(stmt.get("revenue"))
            gross_profit = _to_float(stmt.get("gross_profit"))
            net_income = _to_float(stmt.get("consolidated_net_income_loss"))
            eps = _to_float(stmt.get("basic_earnings_per_share"))
            gross_margin = (gross_profit / revenue) if revenue and gross_profit else None

            periods.append({
                "period": label,
                "revenue": revenue,
                "net_income": net_income,
                "eps": eps,
                "pe_ratio": None,
                "gross_margin": gross_margin,
            })
        except (ValueError, KeyError) as e:
            logger.debug("Skipping Massive income statement entry: %s", e)

    logger.info("Massive: fetched %d %s periods for %s", len(periods), timeframe, symbol)
    return periods


async def fetch_quarterly_financials(symbol: str) -> list[dict]:
    """Convenience: fetch both quarterly and annual income statements."""
    quarterly = await fetch_income_statements(symbol, timeframe="quarterly", limit=8)
    annual = await fetch_income_statements(symbol, timeframe="annual", limit=4)
    return quarterly + annual


# ---------------------------------------------------------------------------
# News with sentiment insights
# GET /v2/reference/news
# ---------------------------------------------------------------------------

async def fetch_news(symbol: str, limit: int = 20) -> list[dict]:
    """Fetch recent news articles from Massive.

    Massive provides per-ticker sentiment via the insights array.
    Returns list of dicts matching NewsArticle model schema.
    """
    headers = _auth_headers()
    if not headers:
        logger.warning("MASSIVE_API_KEY not set, skipping news fetch")
        return []

    bare_symbol = symbol.split(".")[0] if "." in symbol else symbol

    params = {
        "ticker": bare_symbol,
        "limit": limit,
        "order": "desc",
        "sort": "published_utc",
    }

    try:
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            resp = await client.get(f"{BASE_URL}/v2/reference/news", params=params)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("Massive news fetch failed for %s: %s", symbol, e)
        return []

    results = data.get("results", [])
    if not results:
        return []

    articles = []
    for item in results:
        published_at = None
        pub_str = item.get("published_utc", "")
        if pub_str:
            try:
                published_at = datetime.fromisoformat(pub_str.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                pass

        # Extract per-ticker sentiment from insights array
        sentiment_score = None
        sentiment_label = None
        for insight in item.get("insights", []):
            if insight.get("ticker", "").upper() == bare_symbol.upper():
                sentiment_label = insight.get("sentiment")
                break

        publisher = item.get("publisher", {})

        articles.append({
            "title": item.get("title", ""),
            "summary": item.get("description", "")[:500],
            "url": item.get("article_url", ""),
            "source": publisher.get("name", ""),
            "published_at": published_at,
            "sentiment_score": sentiment_score,
            "sentiment_label": sentiment_label,
        })

    logger.info("Massive: fetched %d news articles for %s", len(articles), symbol)
    return articles


def _to_float(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return None if str(f) == "nan" else f
    except (ValueError, TypeError):
        return None

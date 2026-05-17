"""EODHD (EOD Historical Data) provider — OHLCV, fundamentals, and news.

EODHD covers 70+ exchanges worldwide with strong Middle East coverage
(Tadawul, ADX, DFM, QSE, Muscat, Bahrain, Kuwait, etc.).

API docs: https://eodhd.com/financial-apis
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://eodhd.com/api"


def _api_key() -> str | None:
    return os.getenv("EODHD_API_KEY") or os.getenv("EODHd_API_KEY")


# ---------------------------------------------------------------------------
# Exchange suffix mapping for Middle East + common exchanges
# EODHD requires symbol.EXCHANGE format (e.g. "2222.SR" for Aramco)
# ---------------------------------------------------------------------------
# If the user already passes the exchange suffix we use it as-is;
# otherwise we try the bare symbol against common exchanges.
FALLBACK_EXCHANGES = ["US", "SR", "ADX", "DFM", "QA", "KW", "MU", "BH", "EGX", "CA", "LSE", "TO", "HK"]


def _has_exchange_suffix(symbol: str) -> bool:
    return "." in symbol


# ---------------------------------------------------------------------------
# OHLCV prices
# ---------------------------------------------------------------------------

async def fetch_ohlcv(symbol: str, days: int = 90) -> list[dict]:
    """Fetch daily OHLCV from EODHD.

    Args:
        symbol: Ticker with optional exchange suffix (e.g. "2222.SR", "AAPL.US").
        days: Number of historical days. Default ~3 months.

    Returns list of dicts matching the Price model schema.
    """
    api_key = _api_key()
    if not api_key:
        logger.warning("EODHD_API_KEY not set, skipping")
        return []

    date_from = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    symbols_to_try = [symbol] if _has_exchange_suffix(symbol) else [f"{symbol}.{ex}" for ex in FALLBACK_EXCHANGES]

    for sym in symbols_to_try:
        records = await _try_fetch_ohlcv(sym, date_from, api_key)
        if records:
            return records

    logger.warning("EODHD: no price data found for %s across exchanges", symbol)
    return []


async def _try_fetch_ohlcv(symbol: str, date_from: str, api_key: str) -> list[dict]:
    params = {
        "api_token": api_key,
        "fmt": "json",
        "from": date_from,
        "period": "d",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{BASE_URL}/eod/{symbol}", params=params)
            if resp.status_code != 200:
                return []
            data = resp.json()
    except (httpx.HTTPError, ValueError):
        return []

    if not isinstance(data, list) or len(data) == 0:
        return []

    records = []
    for row in data:
        try:
            records.append({
                "date": datetime.strptime(row["date"], "%Y-%m-%d"),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume", 0)),
            })
        except (KeyError, ValueError) as e:
            logger.debug("Skipping malformed EODHD row: %s", e)

    logger.info("EODHD: fetched %d price records for %s", len(records), symbol)
    return records


# ---------------------------------------------------------------------------
# Company profile / fundamentals
# ---------------------------------------------------------------------------

async def fetch_fundamentals(symbol: str) -> dict:
    """Fetch company fundamentals from EODHD.

    Returns dict with profile + financial keys matching our DB models.
    """
    api_key = _api_key()
    if not api_key:
        return {}

    symbols_to_try = [symbol] if _has_exchange_suffix(symbol) else [f"{symbol}.{ex}" for ex in FALLBACK_EXCHANGES]

    for sym in symbols_to_try:
        result = await _try_fetch_fundamentals(sym, api_key)
        if result:
            return result
    return {}


async def _try_fetch_fundamentals(symbol: str, api_key: str) -> dict:
    params = {"api_token": api_key, "fmt": "json"}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{BASE_URL}/fundamentals/{symbol}", params=params)
            if resp.status_code != 200:
                return {}
            data = resp.json()
    except (httpx.HTTPError, ValueError):
        return {}

    if not isinstance(data, dict):
        return {}

    general = data.get("General", {})
    if not general.get("Name"):
        return {}

    highlights = data.get("Highlights", {})

    return {
        "company_name": general.get("Name", ""),
        "sector": general.get("Sector", ""),
        "industry": general.get("Industry", ""),
        "market_cap": _to_float(highlights.get("MarketCapitalization")),
        "pe_ratio": _to_float(highlights.get("PERatio")),
        "eps": _to_float(highlights.get("EarningsShare")),
        "revenue": _to_float(highlights.get("Revenue")),
        "gross_margin": _to_float(highlights.get("GrossProfitTTM")),
        "net_income": _to_float(highlights.get("NetIncomeShareholdersTTM")),
    }


# ---------------------------------------------------------------------------
# Quarterly financial periods
# ---------------------------------------------------------------------------

async def fetch_quarterly_financials(symbol: str) -> list[dict]:
    """Fetch quarterly income statement data from EODHD fundamentals endpoint.

    Returns list of period dicts matching Financials model.
    """
    api_key = _api_key()
    if not api_key:
        return []

    symbols_to_try = [symbol] if _has_exchange_suffix(symbol) else [f"{symbol}.{ex}" for ex in FALLBACK_EXCHANGES]

    for sym in symbols_to_try:
        result = await _try_fetch_quarterly(sym, api_key)
        if result:
            return result
    return []


async def _try_fetch_quarterly(symbol: str, api_key: str) -> list[dict]:
    params = {"api_token": api_key, "fmt": "json"}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{BASE_URL}/fundamentals/{symbol}", params=params)
            if resp.status_code != 200:
                return []
            data = resp.json()
    except (httpx.HTTPError, ValueError):
        return []

    financials = data.get("Financials", {})
    income_q = financials.get("Income_Statement", {}).get("quarterly", {})
    if not income_q:
        return []

    periods = []
    for date_key, stmt in income_q.items():
        try:
            dt = datetime.strptime(date_key, "%Y-%m-%d")
            quarter = (dt.month - 1) // 3 + 1
            label = f"{dt.year}-Q{quarter}"
            revenue = _to_float(stmt.get("totalRevenue"))
            gross_profit = _to_float(stmt.get("grossProfit"))
            net_income = _to_float(stmt.get("netIncome"))
            gross_margin = (gross_profit / revenue) if revenue and gross_profit else None

            periods.append({
                "period": label,
                "revenue": revenue,
                "net_income": net_income,
                "eps": None,
                "pe_ratio": None,
                "gross_margin": gross_margin,
            })
        except (ValueError, KeyError) as e:
            logger.debug("Skipping EODHD quarterly entry %s: %s", date_key, e)

    logger.info("EODHD: fetched %d quarterly periods for %s", len(periods), symbol)
    return periods


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------

async def fetch_news(symbol: str, limit: int = 20) -> list[dict]:
    """Fetch recent news articles from EODHD.

    Returns list of dicts matching NewsArticle model schema.
    """
    api_key = _api_key()
    if not api_key:
        logger.warning("EODHD_API_KEY not set, skipping news fetch")
        return []

    # EODHD news endpoint uses bare ticker (no exchange suffix needed)
    bare_symbol = symbol.split(".")[0] if "." in symbol else symbol

    params = {
        "api_token": api_key,
        "s": bare_symbol,
        "limit": limit,
        "fmt": "json",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{BASE_URL}/news", params=params)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("EODHD news fetch failed for %s: %s", symbol, e)
        return []

    if not isinstance(data, list):
        return []

    articles = []
    for item in data:
        published_at = None
        date_str = item.get("date", "")
        if date_str:
            try:
                published_at = datetime.fromisoformat(date_str.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                pass

        # EODHD doesn't provide per-ticker sentiment; we store None
        articles.append({
            "title": item.get("title", ""),
            "summary": item.get("content", "")[:500],  # truncate long content
            "url": item.get("link", ""),
            "source": item.get("source", ""),
            "published_at": published_at,
            "sentiment_score": None,
            "sentiment_label": None,
        })

    logger.info("EODHD: fetched %d news articles for %s", len(articles), symbol)
    return articles


def _to_float(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return None if str(f) == "nan" else f
    except (ValueError, TypeError):
        return None

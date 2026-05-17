"""Twelve Data provider — OHLCV prices and fundamentals.

Twelve Data covers 60+ exchanges including Middle East markets
(Tadawul/SAU, ADX, DFM). Used as first fallback when yfinance fails.

API docs: https://twelvedata.com/docs
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.twelvedata.com"


def _api_key() -> str | None:
    return os.getenv("TWELVEDATA_API_KEY")


# ---------------------------------------------------------------------------
# OHLCV prices
# ---------------------------------------------------------------------------

async def fetch_ohlcv(symbol: str, outputsize: int = 90) -> list[dict]:
    """Fetch daily OHLCV from Twelve Data.

    Args:
        symbol: Ticker symbol (e.g. "2222.SR" for Saudi Aramco on Tadawul).
        outputsize: Number of data points (days). Default ~3 months.

    Returns list of dicts matching the Price model schema.
    """
    api_key = _api_key()
    if not api_key:
        logger.warning("TWELVEDATA_API_KEY not set, skipping")
        return []

    params = {
        "symbol": symbol,
        "interval": "1day",
        "outputsize": outputsize,
        "apikey": api_key,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{BASE_URL}/time_series", params=params)
        resp.raise_for_status()
        data = resp.json()

    if data.get("status") == "error":
        logger.warning("Twelve Data error for %s: %s", symbol, data.get("message"))
        return []

    values = data.get("values", [])
    records = []
    for v in values:
        try:
            records.append({
                "date": datetime.strptime(v["datetime"], "%Y-%m-%d"),
                "open": float(v["open"]),
                "high": float(v["high"]),
                "low": float(v["low"]),
                "close": float(v["close"]),
                "volume": float(v["volume"]),
            })
        except (KeyError, ValueError) as e:
            logger.debug("Skipping malformed Twelve Data row: %s", e)

    logger.info("Twelve Data: fetched %d price records for %s", len(records), symbol)
    return records


# ---------------------------------------------------------------------------
# Company profile / fundamentals
# ---------------------------------------------------------------------------

async def fetch_profile(symbol: str) -> dict:
    """Fetch company profile from Twelve Data.

    Returns dict with keys matching Ticker/Financials models where possible.
    """
    api_key = _api_key()
    if not api_key:
        return {}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{BASE_URL}/profile",
            params={"symbol": symbol, "apikey": api_key},
        )
        resp.raise_for_status()
        data = resp.json()

    if data.get("status") == "error" or not data.get("name"):
        return {}

    return {
        "company_name": data.get("name", ""),
        "sector": data.get("sector", ""),
        "industry": data.get("industry", ""),
        "market_cap": _to_float(data.get("market_capitalization")),
    }


async def fetch_statistics(symbol: str) -> dict:
    """Fetch key financial statistics from Twelve Data.

    Returns dict with keys matching Financials model.
    """
    api_key = _api_key()
    if not api_key:
        return {}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{BASE_URL}/statistics",
            params={"symbol": symbol, "apikey": api_key},
        )
        resp.raise_for_status()
        data = resp.json()

    if data.get("status") == "error":
        return {}

    stats = data.get("statistics", {})
    valuations = stats.get("valuations", {})
    financials = stats.get("financials", {})

    return {
        "pe_ratio": _to_float(valuations.get("trailing_pe")),
        "eps": _to_float(valuations.get("trailing_eps")),
        "revenue": _to_float(financials.get("revenue")),
        "gross_margin": _to_float(financials.get("gross_margin")),
        "net_income": _to_float(financials.get("net_income")),
    }


def _to_float(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return None if str(f) == "nan" else f
    except (ValueError, TypeError):
        return None

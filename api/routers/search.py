"""Ticker / company-name search endpoint.

Backed by SEC's company_tickers_exchange.json (~200KB, covers all US public
tickers). Loaded once on first request, then served from an in-process index.
TTL of 24h forces a refresh once a day so newly listed companies show up.

Public:
    GET /search?q=apple        → [{ticker, name, exchange, score}, ...]
    GET /search/suggest/{q}    → "did you mean" — same shape, used as 404 fallback
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

import httpx
from fastapi import APIRouter, Query

router = APIRouter(prefix="/search", tags=["search"])
logger = logging.getLogger(__name__)

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_HEADERS = {"User-Agent": "FinSight Research contact@finsight.local"}
INDEX_TTL_SECONDS = 24 * 60 * 60  # 24h

_INDEX: list["TickerEntry"] = []
_INDEX_LOADED_AT: float = 0.0


@dataclass(frozen=True)
class TickerEntry:
    ticker: str
    name: str
    exchange: str
    name_lower: str
    cik: str


async def _load_index() -> list[TickerEntry]:
    """Fetch the SEC company-tickers JSON and build a flat list."""
    async with httpx.AsyncClient(headers=SEC_HEADERS, timeout=60) as client:
        resp = await client.get(SEC_TICKERS_URL)
        resp.raise_for_status()
        data = resp.json()

    fields = data.get("fields", [])
    try:
        idx_cik = fields.index("cik")
        idx_name = fields.index("name")
        idx_ticker = fields.index("ticker")
        idx_exch = fields.index("exchange")
    except ValueError:
        logger.error("Unexpected EDGAR ticker-index format: %s", fields)
        return []

    entries: list[TickerEntry] = []
    for row in data.get("data", []):
        ticker = str(row[idx_ticker] or "").upper()
        name = str(row[idx_name] or "").strip()
        if not ticker or not name:
            continue
        entries.append(
            TickerEntry(
                ticker=ticker,
                name=name,
                exchange=str(row[idx_exch] or "").strip(),
                name_lower=name.lower(),
                cik=str(row[idx_cik]).zfill(10),
            )
        )
    logger.info("Loaded %d tickers from SEC", len(entries))
    return entries


async def _ensure_index() -> list[TickerEntry]:
    """Lazy-load and refresh after TTL."""
    global _INDEX, _INDEX_LOADED_AT
    now = time.time()
    if _INDEX and (now - _INDEX_LOADED_AT) < INDEX_TTL_SECONDS:
        return _INDEX
    try:
        _INDEX = await _load_index()
        _INDEX_LOADED_AT = now
    except Exception:
        logger.exception("Failed to refresh SEC ticker index")
        if not _INDEX:
            raise
    return _INDEX


def _score(query: str, e: TickerEntry) -> float:
    """Higher score = better match. 0 = no match."""
    q = query.strip().lower()
    if not q:
        return 0.0

    # Exact ticker match wins everything
    if e.ticker.lower() == q:
        return 1000.0
    # Ticker starts-with
    if e.ticker.lower().startswith(q):
        return 500.0 - (len(e.ticker) - len(q)) * 0.5
    # Name starts-with
    if e.name_lower.startswith(q):
        return 300.0 - (len(e.name) - len(q)) * 0.05
    # Word-boundary match in name (e.g. "tech" matches "Apple Tech")
    if f" {q}" in e.name_lower:
        return 200.0
    # Substring in name
    if q in e.name_lower:
        return 100.0 - (len(e.name) - len(q)) * 0.02
    # Substring in ticker (rare, but handy for 5-letter mid-word)
    if q in e.ticker.lower():
        return 80.0
    # Fuzzy fallback for typos — only for queries 3+ chars
    if len(q) >= 3:
        ratio = SequenceMatcher(None, q, e.name_lower[: len(q) * 2]).ratio()
        if ratio > 0.75:
            return 40.0 + ratio * 20.0
    return 0.0


def _to_dict(e: TickerEntry, score: float) -> dict[str, Any]:
    return {
        "ticker": e.ticker,
        "name": e.name,
        "exchange": e.exchange,
        "score": round(score, 2),
    }


@router.get("")
async def search(
    q: str = Query("", description="Ticker symbol or company name"),
    limit: int = Query(8, ge=1, le=25),
) -> list[dict[str, Any]]:
    """Search by ticker or company name. Empty query returns []."""
    if not q.strip():
        return []
    index = await _ensure_index()

    scored: list[tuple[float, TickerEntry]] = []
    for e in index:
        s = _score(q, e)
        if s > 0:
            scored.append((s, e))

    scored.sort(key=lambda t: (-t[0], t[1].ticker))
    return [_to_dict(e, s) for s, e in scored[:limit]]


@router.get("/suggest/{symbol}")
async def suggest(symbol: str, limit: int = Query(5, ge=1, le=10)) -> list[dict[str, Any]]:
    """'Did you mean?' — returns close matches for an unknown ticker.

    Strategy: best ticker prefix matches first, then fuzzy name matches.
    """
    s = symbol.strip()
    if not s:
        return []
    index = await _ensure_index()

    sl = s.lower()
    scored: list[tuple[float, TickerEntry]] = []
    for e in index:
        # Prefer ticker prefix overlap (typo in ticker)
        tlower = e.ticker.lower()
        if tlower == sl:
            continue  # caller already knows this exists or would have hit /ticker
        if tlower.startswith(sl[:1]) and len(sl) >= 2:
            ratio = SequenceMatcher(None, sl, tlower).ratio()
            if ratio > 0.6:
                scored.append((400.0 + ratio * 100.0, e))
                continue
        # Name fuzzy
        if len(sl) >= 3:
            ratio = SequenceMatcher(None, sl, e.name_lower[: max(len(sl) * 2, 12)]).ratio()
            if ratio > 0.7:
                scored.append((100.0 + ratio * 100.0, e))

    scored.sort(key=lambda t: (-t[0], t[1].ticker))
    return [_to_dict(e, s) for s, e in scored[:limit]]

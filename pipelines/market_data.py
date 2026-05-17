"""Fetch OHLCV prices and financial ratios, with multi-source fallback.

Provider chain (tries in order, stops at first success):
    OHLCV prices:     yfinance → Massive → Twelve Data → EODHD → Tiingo
    Financials/info:  yfinance → Massive → Twelve Data + EODHD → Tiingo
    Quarterly data:   yfinance → Massive → EODHD

This allows US tickers to use the free yfinance path, while Middle East
and other international tickers automatically fall through to paid APIs.
"""

from __future__ import annotations

import logging
from datetime import datetime

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.crud import get_or_create_ticker
from db.models import Financials, Price
from pipelines import eodhd, massive, tiingo, twelvedata

logger = logging.getLogger(__name__)


# ===================================================================
# yfinance exchange suffixes for international markets.
# If the bare symbol returns nothing, we try these in order.
# ===================================================================
YFINANCE_SUFFIXES = [
    "",       # US / already-suffixed
    ".CA",    # Egypt (Cairo)
    ".SR",    # Saudi Arabia (Tadawul)
    ".AE",    # UAE (Abu Dhabi / DFM)
    ".QA",    # Qatar
    ".KW",    # Kuwait
    ".BH",    # Bahrain
    ".L",     # London
    ".TO",    # Toronto
    ".HK",    # Hong Kong
]


# ===================================================================
# OHLCV — fallback chain
# ===================================================================

def _fetch_ohlcv_yfinance(symbol: str, period: str = "3mo") -> list[dict]:
    """Download OHLCV data from yfinance (synchronous — runs in thread).

    If the symbol has no exchange suffix and returns empty, tries common
    Middle East / international suffixes before giving up.
    """
    suffixes = [""] if "." in symbol else YFINANCE_SUFFIXES
    for suffix in suffixes:
        sym = f"{symbol}{suffix}" if suffix else symbol
        tk = yf.Ticker(sym)
        df = tk.history(period=period, auto_adjust=True)
        if not df.empty:
            records = []
            for date, row in df.iterrows():
                records.append(
                    {
                        "date": date.to_pydatetime().replace(tzinfo=None),
                        "open": float(row["Open"]),
                        "high": float(row["High"]),
                        "low": float(row["Low"]),
                        "close": float(row["Close"]),
                        "volume": float(row["Volume"]),
                    }
                )
            if suffix:
                logger.info("yfinance: found %s as %s", symbol, sym)
            return records

    logger.warning("yfinance: no price data returned for %s", symbol)
    return []


async def fetch_ohlcv_with_fallback(symbol: str) -> tuple[list[dict], str]:
    """Try multiple providers for OHLCV data.

    Returns (records, source_name) where source_name indicates which
    provider succeeded.
    """
    # 1. yfinance (sync, free)
    try:
        records = _fetch_ohlcv_yfinance(symbol)
        if records:
            return records, "yfinance"
    except Exception as e:
        logger.debug("yfinance OHLCV failed for %s: %s", symbol, e)

    # 2. Massive (high-quality US data)
    try:
        records = await massive.fetch_ohlcv(symbol)
        if records:
            return records, "massive"
    except Exception as e:
        logger.debug("Massive OHLCV failed for %s: %s", symbol, e)

    # 3. Twelve Data
    try:
        records = await twelvedata.fetch_ohlcv(symbol)
        if records:
            return records, "twelvedata"
    except Exception as e:
        logger.debug("Twelve Data OHLCV failed for %s: %s", symbol, e)

    # 4. EODHD
    try:
        records = await eodhd.fetch_ohlcv(symbol)
        if records:
            return records, "eodhd"
    except Exception as e:
        logger.debug("EODHD OHLCV failed for %s: %s", symbol, e)

    # 5. Tiingo
    try:
        records = await tiingo.fetch_ohlcv(symbol)
        if records:
            return records, "tiingo"
    except Exception as e:
        logger.debug("Tiingo OHLCV failed for %s: %s", symbol, e)

    logger.warning("All providers failed for OHLCV on %s", symbol)
    return [], "none"


# ===================================================================
# Financials / profile — fallback chain
# ===================================================================

def _fetch_financials_yfinance(symbol: str) -> dict:
    """Fetch key financial metrics from yfinance.

    Tries exchange suffixes if the bare symbol has no company name.
    """
    suffixes = [""] if "." in symbol else YFINANCE_SUFFIXES
    for suffix in suffixes:
        sym = f"{symbol}{suffix}" if suffix else symbol
        tk = yf.Ticker(sym)
        info = tk.info or {}
        name = info.get("longName") or info.get("shortName", "")
        if name:
            return {
                "company_name": name,
                "sector": info.get("sector", ""),
                "industry": info.get("industry", ""),
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
                "eps": info.get("trailingEps"),
                "revenue": info.get("totalRevenue"),
                "gross_margin": info.get("grossMargins"),
                "net_income": info.get("netIncomeToCommon"),
            }
    return {
        "company_name": "",
        "sector": "",
        "industry": "",
        "market_cap": None,
        "pe_ratio": None,
        "eps": None,
        "revenue": None,
        "gross_margin": None,
        "net_income": None,
    }


async def fetch_financials_with_fallback(symbol: str) -> tuple[dict, str]:
    """Try multiple providers for company profile + financial metrics.

    Returns (financials_dict, source_name).
    """
    # 1. yfinance
    try:
        fin = _fetch_financials_yfinance(symbol)
        if fin.get("company_name"):
            return fin, "yfinance"
    except Exception as e:
        logger.debug("yfinance financials failed for %s: %s", symbol, e)

    # 2. Massive (ticker overview — good for US companies)
    try:
        profile = await massive.fetch_profile(symbol)
        if profile.get("company_name"):
            return profile, "massive"
    except Exception as e:
        logger.debug("Massive financials failed for %s: %s", symbol, e)

    # 3. Twelve Data (profile + statistics combined)
    try:
        profile = await twelvedata.fetch_profile(symbol)
        if profile.get("company_name"):
            stats = await twelvedata.fetch_statistics(symbol)
            merged = {**profile, **stats}
            return merged, "twelvedata"
    except Exception as e:
        logger.debug("Twelve Data financials failed for %s: %s", symbol, e)

    # 4. EODHD (single endpoint gives both profile + financials)
    try:
        fundamentals = await eodhd.fetch_fundamentals(symbol)
        if fundamentals.get("company_name"):
            return fundamentals, "eodhd"
    except Exception as e:
        logger.debug("EODHD financials failed for %s: %s", symbol, e)

    # 5. Tiingo (limited — only company name, no financials)
    try:
        profile = await tiingo.fetch_profile(symbol)
        if profile.get("company_name"):
            return profile, "tiingo"
    except Exception as e:
        logger.debug("Tiingo financials failed for %s: %s", symbol, e)

    logger.warning("All providers failed for financials on %s", symbol)
    return {}, "none"


# ===================================================================
# Quarterly financials — fallback chain
# ===================================================================

def _fetch_quarterly_yfinance(symbol: str) -> list[dict]:
    """Fetch quarterly and annual income statement data from yfinance."""
    tk = yf.Ticker(symbol)
    periods: list[dict] = []

    try:
        q_income = tk.quarterly_income_stmt
        if q_income is not None and not q_income.empty:
            for col in q_income.columns:
                dt = col.to_pydatetime()
                quarter = (dt.month - 1) // 3 + 1
                label = f"{dt.year}-Q{quarter}"
                revenue = _safe_float(q_income, "Total Revenue", col)
                gross_profit = _safe_float(q_income, "Gross Profit", col)
                net_income = _safe_float(q_income, "Net Income", col)
                gross_margin = (gross_profit / revenue) if revenue and gross_profit else None
                periods.append({
                    "period": label,
                    "revenue": revenue,
                    "net_income": net_income,
                    "eps": None,
                    "pe_ratio": None,
                    "gross_margin": gross_margin,
                })
    except Exception as e:
        logger.warning("yfinance: quarterly financials failed for %s: %s", symbol, e)

    try:
        a_income = tk.income_stmt
        if a_income is not None and not a_income.empty:
            for col in a_income.columns:
                dt = col.to_pydatetime()
                label = f"{dt.year}-FY"
                revenue = _safe_float(a_income, "Total Revenue", col)
                gross_profit = _safe_float(a_income, "Gross Profit", col)
                net_income = _safe_float(a_income, "Net Income", col)
                gross_margin = (gross_profit / revenue) if revenue and gross_profit else None
                periods.append({
                    "period": label,
                    "revenue": revenue,
                    "net_income": net_income,
                    "eps": None,
                    "pe_ratio": None,
                    "gross_margin": gross_margin,
                })
    except Exception as e:
        logger.warning("yfinance: annual financials failed for %s: %s", symbol, e)

    return periods


async def fetch_quarterly_with_fallback(symbol: str) -> tuple[list[dict], str]:
    """Try multiple providers for quarterly financial periods.

    Returns (periods_list, source_name).
    """
    # 1. yfinance
    try:
        periods = _fetch_quarterly_yfinance(symbol)
        if periods:
            return periods, "yfinance"
    except Exception as e:
        logger.debug("yfinance quarterly failed for %s: %s", symbol, e)

    # 2. Massive (quarterly + annual income statements)
    try:
        periods = await massive.fetch_quarterly_financials(symbol)
        if periods:
            return periods, "massive"
    except Exception as e:
        logger.debug("Massive quarterly failed for %s: %s", symbol, e)

    # 3. EODHD
    try:
        periods = await eodhd.fetch_quarterly_financials(symbol)
        if periods:
            return periods, "eodhd"
    except Exception as e:
        logger.debug("EODHD quarterly failed for %s: %s", symbol, e)

    return [], "none"


# ===================================================================
# Helpers
# ===================================================================

def _safe_float(df, row_label: str, col) -> float | None:
    """Safely extract a float from a DataFrame cell."""
    try:
        if row_label in df.index:
            val = df.loc[row_label, col]
            if val is not None and str(val) != "nan":
                return float(val)
    except Exception:
        pass
    return None


# ===================================================================
# Legacy API — keep old function names working for external callers
# ===================================================================

def fetch_ohlcv(symbol: str, period: str = "3mo") -> list[dict]:
    """Synchronous OHLCV fetch (yfinance only). Kept for backward compat."""
    return _fetch_ohlcv_yfinance(symbol, period)


def fetch_financials(symbol: str) -> dict:
    """Synchronous financials fetch (yfinance only). Kept for backward compat."""
    return _fetch_financials_yfinance(symbol)


def fetch_quarterly_financials(symbol: str) -> list[dict]:
    """Synchronous quarterly fetch (yfinance only). Kept for backward compat."""
    return _fetch_quarterly_yfinance(symbol)


# ===================================================================
# Full ingestion pipeline (async, with fallbacks)
# ===================================================================

async def ingest_market_data(session: AsyncSession, symbol: str) -> dict:
    """Full pipeline: fetch prices + financials for a ticker and persist to DB.

    Uses the multi-source fallback chain. Returns a summary dict with counts.
    """
    symbol = symbol.upper()
    logger.info("Ingesting market data for %s (multi-source)", symbol)

    # --- Financials / ticker info (with fallback) ---
    fin, fin_source = await fetch_financials_with_fallback(symbol)
    if not fin:
        fin = {}

    ticker = await get_or_create_ticker(
        session,
        symbol,
        company_name=fin.get("company_name", ""),
        sector=fin.get("sector", ""),
        industry=fin.get("industry", ""),
        market_cap=fin.get("market_cap"),
    )
    # Update mutable fields
    if fin.get("company_name"):
        ticker.company_name = fin["company_name"]
    if fin.get("sector"):
        ticker.sector = fin["sector"]
    if fin.get("industry"):
        ticker.industry = fin["industry"]
    if fin.get("market_cap") is not None:
        ticker.market_cap = fin["market_cap"]
    ticker.updated_at = datetime.utcnow()

    # --- OHLCV prices (with fallback, upsert to avoid duplicates) ---
    price_records, price_source = await fetch_ohlcv_with_fallback(symbol)
    inserted_prices = 0
    for rec in price_records:
        stmt = (
            pg_insert(Price)
            .values(ticker_id=ticker.id, **rec)
            .on_conflict_do_nothing(constraint="uq_price_ticker_date")
        )
        result = await session.execute(stmt)
        inserted_prices += result.rowcount

    # --- Store current financials snapshot ---
    now = datetime.utcnow()
    period_label = f"{now.year}-FY"
    fin_values = {
        "ticker_id": ticker.id,
        "period": period_label,
        "revenue": fin.get("revenue"),
        "net_income": fin.get("net_income"),
        "eps": fin.get("eps"),
        "pe_ratio": fin.get("pe_ratio"),
        "gross_margin": fin.get("gross_margin"),
        "fetched_at": now,
    }
    fin_insert = pg_insert(Financials).values(**fin_values)
    fin_stmt = fin_insert.on_conflict_do_update(
        constraint="uq_financials_ticker_period",
        set_={
            "revenue": fin_insert.excluded.revenue,
            "net_income": fin_insert.excluded.net_income,
            "eps": fin_insert.excluded.eps,
            "pe_ratio": fin_insert.excluded.pe_ratio,
            "gross_margin": fin_insert.excluded.gross_margin,
            "fetched_at": fin_insert.excluded.fetched_at,
        },
    )
    await session.execute(fin_stmt)

    # --- Store quarterly + annual income statement periods (with fallback) ---
    quarterly_periods, quarterly_source = await fetch_quarterly_with_fallback(symbol)
    for qp in quarterly_periods:
        qp_insert = pg_insert(Financials).values(
            ticker_id=ticker.id,
            period=qp["period"],
            revenue=qp["revenue"],
            net_income=qp["net_income"],
            eps=qp["eps"],
            pe_ratio=qp["pe_ratio"],
            gross_margin=qp["gross_margin"],
            fetched_at=now,
        )
        qp_stmt = qp_insert.on_conflict_do_update(
            constraint="uq_financials_ticker_period",
            set_={
                "revenue": qp_insert.excluded.revenue,
                "net_income": qp_insert.excluded.net_income,
                "eps": qp_insert.excluded.eps,
                "pe_ratio": qp_insert.excluded.pe_ratio,
                "gross_margin": qp_insert.excluded.gross_margin,
                "fetched_at": qp_insert.excluded.fetched_at,
            },
        )
        await session.execute(qp_stmt)

    await session.commit()
    logger.info(
        "Ingested %d prices (via %s), %d financial periods (via %s) for %s",
        inserted_prices, price_source, len(quarterly_periods), quarterly_source, symbol,
    )
    return {
        "symbol": symbol,
        "prices_inserted": inserted_prices,
        "ticker_id": str(ticker.id),
        "price_source": price_source,
        "financials_source": fin_source,
        "quarterly_source": quarterly_source,
    }

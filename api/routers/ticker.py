"""GET /ticker/{symbol} — full ticker detail for the dashboard page.
GET /ticker/{symbol}/peers — sector peer comparison.
GET /ticker/{symbol}/news — news sentiment.
GET /ticker/{symbol}/holders — institutional holders.
GET /ticker/{symbol}/earnings — earnings calendar.
GET /ticker/{symbol}/dividends — dividend history.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from api.dependencies import DbSession
from api.schemas import (
    FinancialsMetrics,
    LatestFiling,
    PricePoint,
    TickerResponse,
)
from db.models import Filing, Financials, NewsArticle, Price, Ticker

router = APIRouter(tags=["ticker"])
logger = logging.getLogger(__name__)


@router.get("/ticker/{symbol}", response_model=TickerResponse)
async def get_ticker(symbol: str, db: DbSession, days: int = 180):
    """Return ticker metadata, the last `days` prices, latest financials and filing.

    The dashboard page consumes this single call to render everything above
    the fold.
    """
    sym = symbol.upper()

    ticker = (
        await db.execute(select(Ticker).where(Ticker.symbol == sym))
    ).scalar_one_or_none()
    if not ticker:
        raise HTTPException(status_code=404, detail=f"Ticker {sym} not found")

    # Prices — most recent `days` rows
    prices_result = await db.execute(
        select(Price)
        .where(Price.ticker_id == ticker.id)
        .order_by(Price.date.desc())
        .limit(days)
    )
    price_rows = list(reversed(prices_result.scalars().all()))  # chronological

    price_points = [
        PricePoint(
            date=p.date.date().isoformat(),
            open=p.open,
            high=p.high,
            low=p.low,
            close=p.close,
            volume=p.volume,
        )
        for p in price_rows
    ]

    # Day change from last two rows
    latest_price = price_rows[-1].close if price_rows else None
    previous_close = price_rows[-2].close if len(price_rows) >= 2 else None
    day_change = (
        (latest_price - previous_close)
        if latest_price is not None and previous_close is not None
        else None
    )
    day_change_pct = (
        (day_change / previous_close * 100)
        if day_change is not None and previous_close
        else None
    )

    # Latest financials row for this ticker
    fin_row = (
        await db.execute(
            select(Financials)
            .where(Financials.ticker_id == ticker.id)
            .order_by(Financials.fetched_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    financials = (
        FinancialsMetrics(
            period=fin_row.period,
            revenue=fin_row.revenue,
            net_income=fin_row.net_income,
            eps=fin_row.eps,
            pe_ratio=fin_row.pe_ratio,
            gross_margin=fin_row.gross_margin,
        )
        if fin_row
        else None
    )

    # All financial periods (quarterly + annual) for trend chart
    all_fin_result = await db.execute(
        select(Financials)
        .where(Financials.ticker_id == ticker.id)
        .order_by(Financials.period.asc())
    )
    financials_history = [
        FinancialsMetrics(
            period=f.period,
            revenue=f.revenue,
            net_income=f.net_income,
            eps=f.eps,
            pe_ratio=f.pe_ratio,
            gross_margin=f.gross_margin,
        )
        for f in all_fin_result.scalars().all()
    ]

    # All filings (latest 20)
    filings_result = await db.execute(
        select(Filing)
        .where(Filing.ticker_id == ticker.id)
        .order_by(Filing.filed_date.desc())
        .limit(20)
    )
    filing_rows = filings_result.scalars().all()
    filings = [
        LatestFiling(
            filing_type=f.filing_type,
            filed_date=f.filed_date.date().isoformat() if f.filed_date else None,
            accession_number=f.accession_number,
            source_url=f.source_url,
        )
        for f in filing_rows
    ]
    latest_filing = filings[0] if filings else None

    return TickerResponse(
        symbol=ticker.symbol,
        company_name=ticker.company_name,
        sector=ticker.sector,
        industry=ticker.industry,
        market_cap=ticker.market_cap,
        latest_price=latest_price,
        previous_close=previous_close,
        day_change=day_change,
        day_change_pct=day_change_pct,
        updated_at=ticker.updated_at,
        prices=price_points,
        financials=financials,
        latest_filing=latest_filing,
        filings=filings,
        financials_history=financials_history,
    )


@router.post("/ticker/{symbol}/refresh")
async def refresh_ticker(symbol: str, db: DbSession):
    """Re-run the data agent pipelines (market data + news) without generating a report.

    This is a lightweight refresh that only updates prices, financials, and news
    from the multi-source fallback chain. No LLM calls or report generation.
    """
    sym = symbol.upper()

    ticker = (
        await db.execute(select(Ticker).where(Ticker.symbol == sym))
    ).scalar_one_or_none()
    if not ticker:
        raise HTTPException(status_code=404, detail=f"Ticker {sym} not found")

    from pipelines.market_data import ingest_market_data
    from pipelines.news_fetcher import ingest_news

    market_result = {}
    news_result = {}
    errors = []

    try:
        market_result = await ingest_market_data(db, sym)
    except Exception as e:
        logger.exception("Refresh: market data failed for %s", sym)
        errors.append(f"market_data: {e}")

    try:
        news_result = await ingest_news(db, sym)
    except Exception as e:
        logger.exception("Refresh: news failed for %s", sym)
        errors.append(f"news: {e}")

    return {
        "ticker": sym,
        "market": market_result,
        "news": news_result,
        "errors": errors,
    }


# Hard-coded sector → peer tickers map (avoids slow yfinance screening).
# Extend as needed.
_SECTOR_PEERS: dict[str, list[str]] = {
    "Technology": ["AAPL", "MSFT", "GOOGL", "META", "NVDA", "AMZN", "CRM", "ORCL", "ADBE", "INTC"],
    "Financial Services": ["JPM", "BAC", "GS", "MS", "WFC", "C", "BLK", "SCHW", "AXP", "V"],
    "Healthcare": ["JNJ", "UNH", "PFE", "ABBV", "MRK", "LLY", "TMO", "ABT", "BMY", "AMGN"],
    "Consumer Cyclical": ["AMZN", "TSLA", "HD", "NKE", "MCD", "SBUX", "TGT", "LOW", "BKNG", "GM"],
    "Communication Services": ["GOOGL", "META", "DIS", "NFLX", "CMCSA", "T", "VZ", "TMUS", "SNAP", "PINS"],
    "Energy": ["XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX", "VLO", "OXY", "HAL"],
    "Industrials": ["CAT", "HON", "UPS", "BA", "RTX", "GE", "LMT", "DE", "MMM", "UNP"],
    "Consumer Defensive": ["PG", "KO", "PEP", "WMT", "COST", "PM", "MO", "CL", "MDLZ", "GIS"],
    "Utilities": ["NEE", "DUK", "SO", "D", "AEP", "EXC", "SRE", "XEL", "ED", "WEC"],
    "Real Estate": ["AMT", "PLD", "CCI", "EQIX", "PSA", "SPG", "O", "WELL", "DLR", "AVB"],
    "Basic Materials": ["LIN", "APD", "SHW", "ECL", "DD", "NEM", "FCX", "NUE", "DOW", "VMC"],
}


def _fetch_peer_info(symbol: str) -> dict | None:
    """Fetch basic info for a single ticker from yfinance (sync)."""
    import yfinance as yf
    try:
        tk = yf.Ticker(symbol)
        info = tk.info or {}
        return {
            "symbol": symbol,
            "company_name": info.get("longName") or info.get("shortName", symbol),
            "price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "gross_margin": info.get("grossMargins"),
            "day_change_pct": info.get("regularMarketChangePercent"),
        }
    except Exception:
        return None


@router.get("/ticker/{symbol}/peers")
async def get_peers(symbol: str, db: DbSession):
    """Return sector peer comparison for a ticker."""
    sym = symbol.upper()

    ticker = (
        await db.execute(select(Ticker).where(Ticker.symbol == sym))
    ).scalar_one_or_none()
    if not ticker:
        raise HTTPException(status_code=404, detail=f"Ticker {sym} not found")

    sector = ticker.sector or ""
    peer_symbols = _SECTOR_PEERS.get(sector, [])
    # Pick up to 5 peers excluding the ticker itself
    peers = [s for s in peer_symbols if s != sym][:5]

    if not peers:
        return {"ticker": sym, "sector": sector, "peers": []}

    # Fetch peer info in parallel threads
    loop = asyncio.get_event_loop()
    tasks = [loop.run_in_executor(None, _fetch_peer_info, p) for p in peers]
    results = await asyncio.gather(*tasks)

    # Also include the current ticker for comparison
    current_info = await loop.run_in_executor(None, _fetch_peer_info, sym)
    peer_list = [r for r in results if r is not None]

    return {
        "ticker": sym,
        "sector": sector,
        "current": current_info,
        "peers": peer_list,
    }


# ---------------------------------------------------------------------------
# News sentiment
# ---------------------------------------------------------------------------

@router.get("/ticker/{symbol}/news")
async def get_news(symbol: str, db: DbSession, limit: int = 20):
    """Return recent news articles with sentiment for a ticker."""
    sym = symbol.upper()
    ticker = (
        await db.execute(select(Ticker).where(Ticker.symbol == sym))
    ).scalar_one_or_none()
    if not ticker:
        raise HTTPException(status_code=404, detail=f"Ticker {sym} not found")

    result = await db.execute(
        select(NewsArticle)
        .where(NewsArticle.ticker_id == ticker.id)
        .order_by(NewsArticle.published_at.desc())
        .limit(limit)
    )
    articles = result.scalars().all()

    # If no stored articles, try fetching live
    if not articles:
        try:
            from pipelines.news_fetcher import ingest_news
            await ingest_news(db, sym)
            result = await db.execute(
                select(NewsArticle)
                .where(NewsArticle.ticker_id == ticker.id)
                .order_by(NewsArticle.published_at.desc())
                .limit(limit)
            )
            articles = result.scalars().all()
        except Exception as e:
            logger.warning("Failed to fetch news for %s: %s", sym, e)

    return {
        "ticker": sym,
        "articles": [
            {
                "title": a.title,
                "url": a.url,
                "source": a.source,
                "published_at": a.published_at.isoformat() if a.published_at else None,
                "summary": (a.summary or "")[:200],
                "sentiment_score": a.sentiment_score,
                "sentiment_label": a.sentiment_label,
            }
            for a in articles
        ],
    }


# ---------------------------------------------------------------------------
# Institutional holders (live from yfinance)
# ---------------------------------------------------------------------------

def _fetch_holders(symbol: str) -> list[dict]:
    """Fetch institutional holders from yfinance (sync)."""
    import yfinance as yf
    try:
        tk = yf.Ticker(symbol)
        df = tk.institutional_holders
        if df is None or df.empty:
            return []
        rows = []
        for _, row in df.head(10).iterrows():
            rows.append({
                "holder": str(row.get("Holder", "")),
                "shares": int(row["Shares"]) if "Shares" in row and row["Shares"] else None,
                "date_reported": str(row.get("Date Reported", "")),
                "pct_out": float(row["% Out"]) if "% Out" in row and row["% Out"] else None,
                "value": float(row["Value"]) if "Value" in row and row["Value"] else None,
            })
        return rows
    except Exception as e:
        logger.warning("Failed to fetch holders for %s: %s", symbol, e)
        return []


@router.get("/ticker/{symbol}/holders")
async def get_holders(symbol: str):
    """Return top institutional holders for a ticker."""
    sym = symbol.upper()
    holders = await asyncio.to_thread(_fetch_holders, sym)
    return {"ticker": sym, "holders": holders}


# ---------------------------------------------------------------------------
# Earnings calendar + EPS surprise
# ---------------------------------------------------------------------------

def _fetch_earnings(symbol: str) -> dict:
    """Fetch earnings dates and EPS history from yfinance (sync)."""
    import yfinance as yf
    try:
        tk = yf.Ticker(symbol)

        # Earnings dates (past + future)
        ed = tk.earnings_dates
        events = []
        if ed is not None and not ed.empty:
            for dt_idx, row in ed.head(12).iterrows():
                dt = dt_idx.to_pydatetime()
                events.append({
                    "date": dt.strftime("%Y-%m-%d"),
                    "eps_estimate": float(row["EPS Estimate"]) if "EPS Estimate" in row and row["EPS Estimate"] == row["EPS Estimate"] else None,
                    "eps_actual": float(row["Reported EPS"]) if "Reported EPS" in row and row["Reported EPS"] == row["Reported EPS"] else None,
                    "surprise_pct": float(row["Surprise(%)"]) if "Surprise(%)" in row and row["Surprise(%)"] == row["Surprise(%)"] else None,
                })

        return {"events": events}
    except Exception as e:
        logger.warning("Failed to fetch earnings for %s: %s", symbol, e)
        return {"events": []}


@router.get("/ticker/{symbol}/earnings")
async def get_earnings(symbol: str):
    """Return earnings calendar and EPS surprise history."""
    sym = symbol.upper()
    data = await asyncio.to_thread(_fetch_earnings, sym)
    return {"ticker": sym, **data}


# ---------------------------------------------------------------------------
# Dividend history
# ---------------------------------------------------------------------------

def _fetch_dividends(symbol: str) -> dict:
    """Fetch dividend history from yfinance (sync)."""
    import yfinance as yf
    try:
        tk = yf.Ticker(symbol)
        info = tk.info or {}

        dividend_yield = info.get("dividendYield")
        payout_ratio = info.get("payoutRatio")

        divs = tk.dividends
        history = []
        if divs is not None and not divs.empty:
            # Group by year, sum dividends
            annual = {}
            for dt_idx, val in divs.items():
                year = dt_idx.year
                annual[year] = annual.get(year, 0) + float(val)

            for year in sorted(annual.keys())[-8:]:
                history.append({"year": year, "amount": round(annual[year], 4)})

        return {
            "dividend_yield": dividend_yield,
            "payout_ratio": payout_ratio,
            "history": history,
        }
    except Exception as e:
        logger.warning("Failed to fetch dividends for %s: %s", symbol, e)
        return {"dividend_yield": None, "payout_ratio": None, "history": []}


@router.get("/ticker/{symbol}/dividends")
async def get_dividends(symbol: str):
    """Return dividend yield, payout ratio, and annual dividend history."""
    sym = symbol.upper()
    data = await asyncio.to_thread(_fetch_dividends, sym)
    return {"ticker": sym, **data}

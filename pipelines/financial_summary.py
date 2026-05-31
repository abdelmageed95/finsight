"""Structured financial-history block for the RAG report prompt.

The RAG report is grounded in filing *text*. This module surfaces the
structured multi-year numbers (revenue, net income, EPS, margins) from the
`financials` table — plus a short price snapshot — so the LLM has an
authoritative figure series instead of depending on whatever numbers happen
to land in a retrieved filing chunk.

Built by the DataAgent (which already holds a DB session) and flowed through
graph state to the RAG chain. See docs/agents/README.md.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Financials, Price, Ticker

logger = logging.getLogger(__name__)

MAX_ANNUAL = 5      # most recent annual periods to show
MAX_QUARTERLY = 4   # most recent quarterly periods to show


def _fmt_money(v: float | None) -> str:
    """Format a dollar amount with a B/M suffix."""
    if v is None:
        return "—"
    a = abs(v)
    if a >= 1e9:
        return f"${v / 1e9:.2f}B"
    if a >= 1e6:
        return f"${v / 1e6:.2f}M"
    return f"${v:,.0f}"


def _fmt_pct(v: float | None) -> str:
    """gross_margin is stored as a fraction (0.75 → 75.0%)."""
    return f"{v * 100:.1f}%" if v is not None else "—"


def _fmt_num(v: float | None) -> str:
    return f"{v:.2f}" if v is not None else "—"


# (column header, cell formatter, raw-value accessor)
_COLUMNS = [
    ("Revenue", lambda r: _fmt_money(r.revenue), lambda r: r.revenue),
    ("Net Income", lambda r: _fmt_money(r.net_income), lambda r: r.net_income),
    ("EPS", lambda r: _fmt_num(r.eps), lambda r: r.eps),
    ("Gross Margin", lambda r: _fmt_pct(r.gross_margin), lambda r: r.gross_margin),
    ("P/E", lambda r: _fmt_num(r.pe_ratio), lambda r: r.pe_ratio),
]


def _markdown_table(rows: list[Financials]) -> str:
    """Render financial rows as a markdown table, dropping all-empty columns."""
    active = [c for c in _COLUMNS if any(c[2](r) is not None for r in rows)]
    header = "| Period | " + " | ".join(c[0] for c in active) + " |"
    sep = "|" + "---|" * (len(active) + 1)
    body = [
        "| " + r.period + " | " + " | ".join(c[1](r) for c in active) + " |"
        for r in rows
    ]
    return "\n".join([header, sep, *body])


async def build_financial_context(session: AsyncSession, ticker: str) -> str:
    """Build a markdown financial-history block for `ticker`.

    Returns an empty string when there is no stored financial data — the RAG
    prompt then falls back to a "no structured data" notice.
    """
    tk = (await session.execute(
        select(Ticker).where(Ticker.symbol == ticker.upper())
    )).scalar_one_or_none()
    if tk is None:
        return ""

    rows = list((await session.execute(
        select(Financials).where(Financials.ticker_id == tk.id)
    )).scalars().all())

    # Drop periods with no usable figures at all (empty placeholder rows).
    rows = [
        r for r in rows
        if any(c[2](r) is not None for c in _COLUMNS)
    ]

    # period is a string like "2025-FY" or "2025-Q3"; lexical sort = chronological.
    annual = sorted(
        (r for r in rows if r.period.endswith("-FY")),
        key=lambda r: r.period, reverse=True,
    )[:MAX_ANNUAL]
    quarterly = sorted(
        (r for r in rows if "-Q" in r.period),
        key=lambda r: r.period, reverse=True,
    )[:MAX_QUARTERLY]

    sections: list[str] = []
    if annual:
        sections.append("**Annual (income statement):**\n" + _markdown_table(annual))
    if quarterly:
        sections.append("**Recent quarters:**\n" + _markdown_table(quarterly))

    # Short price snapshot over whatever history we have stored.
    prices = list((await session.execute(
        select(Price).where(Price.ticker_id == tk.id).order_by(Price.date.desc())
    )).scalars().all())
    closes = [p.close for p in prices if p.close is not None]
    if closes:
        sections.append(
            f"**Price:** latest close ${closes[0]:,.2f}; "
            f"range ${min(closes):,.2f}–${max(closes):,.2f} "
            f"over the last {len(closes)} trading days on file."
        )

    if not sections:
        logger.info("No financial data to summarise for %s", ticker)
        return ""

    logger.info(
        "Built financial context for %s: %d annual, %d quarterly periods",
        ticker, len(annual), len(quarterly),
    )
    return "\n\n".join(sections)

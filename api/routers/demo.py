"""Public demo endpoint — returns a recent completed report without auth.

Used by the logged-out `/demo/{ticker}` page so prospects can see a real
example of the output before signing up. Returns the newest `completed`
report for the ticker (across any user). If no report exists, returns 404.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from api.dependencies import DbSession
from db.models import AnalysisReport

router = APIRouter(prefix="/demo", tags=["demo"])

# A small allow-list keeps the public endpoint from leaking arbitrary user
# reports if a ticker symbol collides with one a user has analysed privately.
ALLOWED_TICKERS = {"AAPL", "MSFT", "NVDA", "TSLA", "GOOGL", "AMZN", "META", "JPM"}


@router.get("/{ticker}")
async def demo_report(ticker: str, db: DbSession) -> dict:
    """Return the latest completed analysis report for the ticker — no auth required."""
    sym = ticker.upper()
    if sym not in ALLOWED_TICKERS:
        raise HTTPException(status_code=404, detail="Demo not available for this ticker")

    result = await db.execute(
        select(AnalysisReport)
        .where(
            AnalysisReport.ticker_symbol == sym,
            AnalysisReport.status == "completed",
        )
        .order_by(AnalysisReport.created_at.desc())
        .limit(1)
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail=f"No demo report available for {sym}")

    payload: dict = {}
    if report.report_json:
        try:
            payload = json.loads(report.report_json)
        except json.JSONDecodeError:
            payload = {}

    return {
        "ticker": sym,
        "job_id": report.job_id,
        "status": report.status,
        "summary": report.summary,
        "risk_score": report.risk_score,
        "generated_at": (
            report.completed_at.isoformat() if report.completed_at else None
        ),
        "executive_summary": payload.get("executive_summary"),
        "risk_rationale": payload.get("risk_rationale"),
        "risk_level": payload.get("risk_level"),
        "bull_case": payload.get("bull_case"),
        "bear_case": payload.get("bear_case"),
        "valuation_rating": payload.get("valuation_rating"),
        "confidence": payload.get("confidence"),
        "citations": payload.get("citations") or [],
    }

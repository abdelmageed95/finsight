"""GET /history — list past analysis reports.
GET /history/{ticker}/metrics — key metrics trend across analyses.
"""

from __future__ import annotations

import json

from fastapi import APIRouter
from sqlalchemy import select

from api.dependencies import CurrentUser, DbSession
from api.schemas import HistoryItem
from db.models import AnalysisReport

router = APIRouter(tags=["history"])


@router.get("/history", response_model=list[HistoryItem])
async def get_history(
    db: DbSession,
    user: CurrentUser,
    ticker: str | None = None,
    limit: int = 50,
):
    """List past analyses, optionally filtered by ticker.

    Returns most recent first, up to `limit` results.
    """
    stmt = (
        select(AnalysisReport)
        .order_by(AnalysisReport.is_starred.desc(), AnalysisReport.created_at.desc())
        .limit(limit)
    )

    # Only show reports owned by the authenticated user
    if user:
        stmt = stmt.where(AnalysisReport.user_id == user.id)

    if ticker:
        stmt = stmt.where(AnalysisReport.ticker_symbol == ticker.upper())

    result = await db.execute(stmt)
    reports = result.scalars().all()

    return [
        HistoryItem(
            job_id=r.job_id,
            ticker=r.ticker_symbol,
            question=r.question,
            status=r.status,
            risk_score=r.risk_score,
            is_starred=bool(r.is_starred),
            created_at=r.created_at,
        )
        for r in reports
    ]


@router.get("/history/{ticker}/metrics")
async def get_metrics_trend(
    ticker: str,
    db: DbSession,
    user: CurrentUser,
):
    """Return key metrics extracted from all completed analyses for a ticker.

    Used to show how AI-extracted metrics changed across re-analyses.
    """
    sym = ticker.upper()
    result = await db.execute(
        select(AnalysisReport)
        .where(
            AnalysisReport.user_id == user.id,
            AnalysisReport.ticker_symbol == sym,
            AnalysisReport.status == "completed",
        )
        .order_by(AnalysisReport.created_at.asc())
    )
    reports = result.scalars().all()

    trend: list[dict] = []
    for r in reports:
        report_data = {}
        if r.report_json:
            try:
                report_data = json.loads(r.report_json)
            except json.JSONDecodeError:
                continue

        metrics = report_data.get("key_metrics", [])
        if not metrics:
            continue

        trend.append({
            "job_id": r.job_id,
            "date": r.created_at.isoformat() if r.created_at else None,
            "risk_score": r.risk_score,
            "metrics": {
                m.get("name", f"metric_{i}"): m.get("value", "")
                for i, m in enumerate(metrics)
                if isinstance(m, dict)
            },
        })

    return {"ticker": sym, "trend": trend}

"""GET /report/{job_id} — poll for a completed analysis report."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from api.dependencies import CurrentUser, DbSession
from api.schemas import CompareResponse, ReportResponse
from db.models import AnalysisReport

router = APIRouter(tags=["report"])


@router.get("/report/{job_id}", response_model=ReportResponse)
async def get_report(job_id: str, db: DbSession, user: CurrentUser):
    """Return the analysis report for a job.

    If the job is still running, returns `{"status": "pending"}` or `{"status": "running"}`.
    If completed, returns the full report.
    """
    result = await db.execute(
        select(AnalysisReport).where(AnalysisReport.job_id == job_id)
    )
    report = result.scalar_one_or_none()

    if not report:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # User isolation: only the owner can see the report
    if report.user_id and report.user_id != user.id:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # If not yet completed, return status only
    if report.status in ("pending", "running"):
        return ReportResponse(
            job_id=report.job_id,
            status=report.status,
            ticker=report.ticker_symbol,
            question=report.question,
        )

    # Parse the full report JSON
    report_data = {}
    if report.report_json:
        try:
            report_data = json.loads(report.report_json)
        except json.JSONDecodeError:
            pass

    return ReportResponse(
        job_id=report.job_id,
        status=report.status,
        ticker=report.ticker_symbol,
        question=report.question,
        summary=report.summary,
        risk_score=report.risk_score,
        risk_level=report_data.get("risk_level"),
        risk_rationale=report_data.get("risk_rationale"),
        risk_breakdown=report_data.get("risk_breakdown"),
        executive_summary=report_data.get("executive_summary"),
        swot=report_data.get("swot"),
        bull_case=report_data.get("bull_case"),
        bear_case=report_data.get("bear_case"),
        catalysts=report_data.get("catalysts"),
        competitive_moat=report_data.get("competitive_moat"),
        moat_rating=report_data.get("moat_rating"),
        revenue_segments=report_data.get("revenue_segments"),
        management_assessment=report_data.get("management_assessment"),
        valuation_verdict=report_data.get("valuation_verdict"),
        valuation_rating=report_data.get("valuation_rating"),
        confidence=report_data.get("confidence"),
        key_metrics=report_data.get("key_metrics"),
        citations=report_data.get("citations"),
        generated_at=report_data.get("generated_at"),
        is_starred=bool(report.is_starred),
    )


@router.post("/report/{job_id}/star")
async def toggle_star(job_id: str, db: DbSession, user: CurrentUser) -> dict:
    """Toggle the starred state of a report. Returns the new state."""
    result = await db.execute(
        select(AnalysisReport).where(AnalysisReport.job_id == job_id)
    )
    report = result.scalar_one_or_none()
    if not report or (report.user_id and report.user_id != user.id):
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    report.is_starred = not bool(report.is_starred)
    await db.commit()
    return {"job_id": job_id, "is_starred": report.is_starred}


@router.get("/report/{job_id}/compare", response_model=CompareResponse)
async def get_comparison(job_id: str, db: DbSession, user: CurrentUser):
    """Return a comparison report by job_id."""
    result = await db.execute(
        select(AnalysisReport).where(AnalysisReport.job_id == job_id)
    )
    report = result.scalar_one_or_none()

    if not report:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if report.user_id and report.user_id != user.id:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    report_data = {}
    if report.report_json:
        try:
            report_data = json.loads(report.report_json)
        except json.JSONDecodeError:
            pass

    return CompareResponse(
        job_id=report.job_id,
        status=report.status,
        ticker_a=report_data.get("ticker_a"),
        ticker_b=report_data.get("ticker_b"),
        summary=report_data.get("summary"),
        metric_comparisons=report_data.get("metric_comparisons"),
        recommendation=report_data.get("recommendation"),
        generated_at=report.completed_at.isoformat() if report.completed_at else None,
    )

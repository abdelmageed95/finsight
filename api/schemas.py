"""Pydantic request/response models for the FastAPI backend."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


# ---------------------------------------------------------------------------
# Auth request models
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)
    name: str | None = Field(default=None, max_length=256)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


class GoogleAuthRequest(BaseModel):
    id_token: str = Field(..., description="Google OAuth2 ID token")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=10, description="Stock ticker symbol")
    question: str = Field(..., min_length=5, max_length=1000, description="Research question")
    messages: list[dict] = Field(default_factory=list, description="Optional chat history for multi-turn context")


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class AnalyzeResponse(BaseModel):
    job_id: str
    status: str = "pending"
    message: str = "Analysis started"


class ReportResponse(BaseModel):
    job_id: str
    status: str  # pending, running, completed, failed
    ticker: str | None = None
    question: str | None = None
    summary: str | None = None
    risk_score: int | None = None
    risk_level: str | None = None
    risk_rationale: str | None = None
    risk_breakdown: list[dict] | None = None
    executive_summary: str | None = None
    swot: dict | None = None
    bull_case: str | None = None
    bear_case: str | None = None
    catalysts: list[dict] | None = None
    competitive_moat: str | None = None
    moat_rating: str | None = None
    revenue_segments: list[dict] | None = None
    management_assessment: str | None = None
    valuation_verdict: str | None = None
    valuation_rating: str | None = None
    confidence: str | None = None
    key_metrics: list[dict] | None = None
    citations: list[dict] | None = None
    generated_at: str | None = None
    is_starred: bool = False


class HistoryItem(BaseModel):
    job_id: str
    ticker: str
    question: str | None
    status: str
    risk_score: int | None
    is_starred: bool = False
    created_at: datetime


class HealthResponse(BaseModel):
    status: str
    db: str
    redis: str
    chroma: str


class ErrorResponse(BaseModel):
    detail: str


# ---------------------------------------------------------------------------
# Ticker detail (powers the dashboard page)
# ---------------------------------------------------------------------------

class PricePoint(BaseModel):
    date: str  # ISO date "YYYY-MM-DD"
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None


class FinancialsMetrics(BaseModel):
    period: str | None = None
    revenue: float | None = None
    net_income: float | None = None
    eps: float | None = None
    pe_ratio: float | None = None
    gross_margin: float | None = None


class LatestFiling(BaseModel):
    filing_type: str
    filed_date: str | None
    accession_number: str | None
    source_url: str | None


class TickerResponse(BaseModel):
    symbol: str
    company_name: str | None = None
    sector: str | None = None
    industry: str | None = None
    market_cap: float | None = None
    latest_price: float | None = None
    previous_close: float | None = None
    day_change: float | None = None
    day_change_pct: float | None = None
    updated_at: datetime | None = None
    prices: list[PricePoint] = Field(default_factory=list)
    financials: FinancialsMetrics | None = None
    latest_filing: LatestFiling | None = None
    filings: list[LatestFiling] = Field(default_factory=list)
    financials_history: list[FinancialsMetrics] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

class ConversationCreate(BaseModel):
    title: str = Field(default="New conversation", max_length=256)
    ticker: str | None = Field(default=None, max_length=10)


class TurnResponse(BaseModel):
    id: str
    role: str
    content: str
    job_id: str | None = None
    created_at: datetime


class ConversationResponse(BaseModel):
    id: str
    ticker: str | None = None
    title: str
    created_at: datetime
    updated_at: datetime
    turns: list[TurnResponse] = Field(default_factory=list)


class ConversationListItem(BaseModel):
    id: str
    ticker: str | None = None
    title: str
    created_at: datetime
    updated_at: datetime


class MessageCreate(BaseModel):
    """Send a message to an existing conversation."""
    question: str = Field(..., min_length=1, max_length=1000)


class ChatMessageResponse(BaseModel):
    """Lightweight RAG response — no report created."""
    answer: str
    citations: list[str] = Field(default_factory=list)
    confidence: str | None = None


class CompareRequest(BaseModel):
    ticker_a: str = Field(..., min_length=1, max_length=10)
    ticker_b: str = Field(..., min_length=1, max_length=10)


class MetricComparisonResponse(BaseModel):
    metric: str
    ticker_a_value: str
    ticker_b_value: str
    winner: str
    context: str = ""


class CompareResponse(BaseModel):
    job_id: str
    status: str = "pending"
    ticker_a: str | None = None
    ticker_b: str | None = None
    summary: str | None = None
    metric_comparisons: list[MetricComparisonResponse] | None = None
    recommendation: str | None = None
    generated_at: str | None = None

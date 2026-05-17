"""Pydantic models for structured RAG output."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class Citation(BaseModel):
    """A reference to a specific source used in the analysis."""

    source_index: int = Field(description="The source number referenced (e.g., 1 for [Source 1])")
    doc_type: str = Field(description="Filing type, e.g. '10-K', '10-Q'")
    excerpt: str = Field(description="Brief quote or paraphrase from the source supporting the claim")


class KeyMetric(BaseModel):
    """A key financial metric extracted from the sources."""

    name: str = Field(description="Metric name, e.g. 'Revenue', 'EPS', 'Gross Margin'")
    value: str = Field(description="The metric value with units, e.g. '$383B', '28.4x', '55.9%'")
    trend: str = Field(description="Direction: 'up', 'down', 'flat', or 'unknown'")
    context: str = Field(description="Brief explanation, e.g. 'Grew 16% YoY driven by Services'")


class RiskCategory(BaseModel):
    """A sub-score breaking down overall risk into categories."""

    category: str = Field(description="Risk category: 'operational', 'financial', 'market', or 'legal'")
    score: int = Field(ge=0, le=100, description="Risk sub-score from 0 (lowest) to 100 (highest)")
    rationale: str = Field(description="One sentence explaining this sub-score")


class SWOTAnalysis(BaseModel):
    """Structured SWOT analysis."""

    strengths: list[str] = Field(description="2-4 key strengths (competitive advantages, strong financials, market position)")
    weaknesses: list[str] = Field(description="2-4 key weaknesses (operational gaps, financial concerns, dependencies)")
    opportunities: list[str] = Field(description="2-4 key opportunities (growth drivers, market expansion, catalysts)")
    threats: list[str] = Field(description="2-4 key threats (competition, regulation, macro headwinds)")


class RevenueSegment(BaseModel):
    """A single revenue segment or geography."""

    name: str = Field(description="Segment name, e.g. 'iPhone', 'Cloud Services', 'North America'")
    value: str = Field(description="Revenue value with units, e.g. '$69.7B'")
    percentage: float = Field(ge=0, le=100, description="Percentage of total revenue")
    trend: str = Field(default="unknown", description="Direction: 'growing', 'declining', 'stable', or 'unknown'")


class Catalyst(BaseModel):
    """A near-term event that could move the stock."""

    event: str = Field(description="Brief description of the catalyst")
    expected_timing: str = Field(description="When it's expected, e.g. 'Q3 2026', 'Next 6 months', 'Upcoming'")
    impact: str = Field(description="'positive', 'negative', or 'uncertain'")
    rationale: str = Field(description="One sentence on why this matters")


class ReportSchema(BaseModel):
    """Structured output schema for the RAG agent's research report."""

    ticker: str = Field(description="The stock ticker symbol analysed")
    executive_summary: str = Field(
        default="",
        description=(
            "2-3 sentence TL;DR conclusion for busy readers. Lead with the verdict "
            "(e.g. 'AAPL remains a strong hold...'), include the key number, and note "
            "the primary risk. Must stand alone without reading the full report."
        )
    )
    summary: str = Field(
        description=(
            "2-3 paragraph analysis answering the user's question. "
            "Must reference specific data from the sources. "
            "Include both bullish and bearish factors."
        )
    )
    risk_score: int | None = Field(
        default=None,
        ge=0, le=100,
        description=(
            "Risk score from 0 (lowest risk) to 100 (highest risk). "
            "MUST be null when the retrieved sources are insufficient to "
            "judge risk — never invent a placeholder score."
        ),
    )
    risk_rationale: str = Field(
        default="",
        description=(
            "One sentence explaining the risk score. Empty string when "
            "risk_score is null."
        ),
    )
    risk_breakdown: list[RiskCategory] = Field(
        default_factory=list,
        description=(
            "Breakdown of overall risk into 4 categories: "
            "operational (execution, supply chain, management), "
            "financial (debt, liquidity, cash flow), "
            "market (competition, demand, macro), "
            "legal (regulation, litigation, compliance). "
            "Provide all 4 categories."
        )
    )
    key_metrics: list[KeyMetric] = Field(
        default_factory=list,
        description="Key financial metrics extracted from the sources (3-6 metrics)"
    )
    citations: list[Citation] = Field(
        default_factory=list,
        description="Citations linking claims in the summary to specific sources"
    )
    swot: SWOTAnalysis | None = Field(
        default=None,
        description="SWOT analysis with 2-4 bullet points per category based on the evidence"
    )
    bull_case: str = Field(
        default="",
        description=(
            "2-3 sentence bull case: the most compelling reasons this stock could outperform, "
            "based on evidence from the sources"
        )
    )
    bear_case: str = Field(
        default="",
        description=(
            "2-3 sentence bear case: the most significant risks that could cause underperformance, "
            "based on evidence from the sources"
        )
    )
    catalysts: list[Catalyst] = Field(
        default_factory=list,
        description=(
            "3-5 near-term catalysts (earnings, product launches, regulatory decisions, macro events) "
            "that could move the stock price. Include both positive and negative catalysts."
        )
    )
    competitive_moat: str = Field(
        default="",
        description=(
            "One paragraph assessing the company's durable competitive advantage. "
            "Identify the moat type (brand, network effects, switching costs, patents, cost advantage, scale) "
            "and rate it as 'wide', 'narrow', or 'none'. Use specific evidence from the sources."
        )
    )
    moat_rating: str = Field(
        default="unknown",
        description="Moat rating: 'wide', 'narrow', 'none', or 'unknown'"
    )
    revenue_segments: list[RevenueSegment] = Field(
        default_factory=list,
        description=(
            "Revenue breakdown by business segment and/or geography from the filings. "
            "Include 3-8 segments with their revenue values and percentage of total."
        )
    )
    management_assessment: str = Field(
        default="",
        description=(
            "2-3 sentence assessment of management quality: leadership track record, "
            "capital allocation discipline, insider alignment, recent strategic decisions. "
            "Must cite specific evidence from the filings."
        )
    )
    valuation_verdict: str = Field(
        default="",
        description=(
            "One paragraph on whether the stock appears overvalued, fairly valued, or undervalued "
            "relative to its fundamentals, growth trajectory, and peers. Include the key valuation "
            "metrics (P/E, EV/EBITDA, P/S) and the reasoning."
        )
    )
    valuation_rating: str = Field(
        default="unknown",
        description="Valuation rating: 'overvalued', 'fairly_valued', 'undervalued', or 'unknown'"
    )
    confidence: str = Field(
        default="unknown",
        description=(
            "How confident the analysis is based on available sources: "
            "'high' (ample relevant data), 'medium' (partial coverage), "
            "'low' (limited relevant sources), 'unknown' (cannot judge)."
        ),
    )

    @field_validator(
        "risk_breakdown",
        "key_metrics",
        "citations",
        "catalysts",
        "revenue_segments",
        mode="before",
    )
    @classmethod
    def _coerce_list_fields(cls, v: object) -> object:
        """Tolerate the LLM emitting prose where a list is expected.

        When retrieval is thin, the model sometimes writes an explanatory
        sentence ('The retrieved sources are insufficient...') into a list
        field. Treat any non-list value as an empty list so a single bad
        field can't fail validation and discard the entire report.
        """
        if v is None or isinstance(v, (str, dict)):
            return []
        return v

    @field_validator("swot", mode="before")
    @classmethod
    def _coerce_swot(cls, v: object) -> object:
        """Tolerate the LLM emitting prose where the SWOT object is expected."""
        if isinstance(v, str):
            return None
        return v


class MetricComparison(BaseModel):
    """A single metric compared between two tickers."""

    metric: str = Field(description="Metric name, e.g. 'Revenue', 'P/E Ratio', 'Gross Margin'")
    ticker_a_value: str = Field(description="Value for ticker A with units")
    ticker_b_value: str = Field(description="Value for ticker B with units")
    winner: str = Field(description="Ticker symbol of the winner, or 'tie'")
    context: str = Field(default="", description="Brief explanation of why this matters")


class ComparisonReport(BaseModel):
    """Structured comparison of two stocks."""

    ticker_a: str = Field(description="First ticker symbol")
    ticker_b: str = Field(description="Second ticker symbol")
    summary: str = Field(
        description=(
            "2-3 paragraph comparative analysis highlighting key differences, "
            "similarities, and investment recommendation for different profiles"
        )
    )
    metric_comparisons: list[MetricComparison] = Field(
        default_factory=list,
        description="5-10 key metrics compared side by side"
    )
    recommendation: str = Field(
        description="1-2 sentence overall recommendation based on the comparison"
    )

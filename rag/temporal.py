"""Extract temporal intent (target fiscal years) from a user query.

Dense embeddings encode topic, not discrete facts like years — "2024" and
"2025" are near-identical vectors. So the year a question is asking about
must be parsed explicitly and turned into a metadata filter, rather than
left to vector similarity.
"""

from __future__ import annotations

import re
from datetime import date

# Explicit 4-digit years, 1990–2099, on word boundaries (avoids matching
# "500" in "S&P 500" or digits inside larger numbers).
_YEAR_RE = re.compile(r"\b(199\d|20\d\d)\b")

# Fiscal-year notations: "FY2025", "FY25", "FY 2024", "fy'24".
_FY_RE = re.compile(r"\bfy\s?'?(\d{2,4})\b", re.IGNORECASE)

# Relative references resolved against the current year.
_LAST_YEAR_RE = re.compile(r"\b(last|prior|previous)\s+year\b", re.IGNORECASE)
_THIS_YEAR_RE = re.compile(r"\b(this|current)\s+year\b", re.IGNORECASE)
_TWO_YEARS_RE = re.compile(r"\btwo\s+years\s+ago\b", re.IGNORECASE)


def extract_fiscal_years(query: str, now: date | None = None) -> list[int]:
    """Return the fiscal year(s) a query targets, newest first.

    An empty list means "no temporal cue" — the caller should NOT apply a
    year filter. Note that relative phrases like "latest" / "most recent"
    deliberately yield an empty list: "give me the newest" is handled by
    `filter_to_latest_filings`, not by a hard year filter.

    Args:
        query: The user's natural-language question.
        now: Reference date for resolving relative phrases (defaults to today).

    Returns:
        Sorted (descending) list of plausible fiscal years, e.g. [2025, 2024].
    """
    if not query:
        return []

    now = now or date.today()
    years: set[int] = set()

    for m in _YEAR_RE.finditer(query):
        years.add(int(m.group(1)))

    for m in _FY_RE.finditer(query):
        yr = int(m.group(1))
        if yr < 100:  # "FY25" → 2025
            yr += 2000
        years.add(yr)

    if _LAST_YEAR_RE.search(query):
        years.add(now.year - 1)
    if _THIS_YEAR_RE.search(query):
        years.add(now.year)
    if _TWO_YEARS_RE.search(query):
        years.add(now.year - 2)

    # Drop implausible years (allow one year ahead for early-filed fiscal years).
    plausible = {y for y in years if 1990 <= y <= now.year + 1}
    return sorted(plausible, reverse=True)

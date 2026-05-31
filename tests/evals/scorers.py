"""Scorers for FinSight pipeline outputs.

Each scorer takes a labeled row and the pipeline's `final_report` dict and
returns a float in [0, 1] (or 0/1 for binary checks).

The faithfulness scorer optionally uses an LLM judge; results are cached on
disk so re-runs are free. To skip the LLM and use only substring overlap,
pass `judge=None` to score_faithfulness.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache for LLM judge responses (keyed on prompt hash)
# ---------------------------------------------------------------------------

_JUDGE_CACHE_PATH = Path(__file__).parent / ".judge_cache.json"


def _load_judge_cache() -> dict[str, str]:
    if _JUDGE_CACHE_PATH.exists():
        try:
            return json.loads(_JUDGE_CACHE_PATH.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _save_judge_cache(cache: dict[str, str]) -> None:
    _JUDGE_CACHE_PATH.write_text(json.dumps(cache, indent=2))


def _judge_key(claim: str, source: str) -> str:
    h = hashlib.sha256()
    h.update(claim.encode())
    h.update(b"||")
    h.update(source.encode())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# 1. Citation faithfulness
# ---------------------------------------------------------------------------

JUDGE_SYSTEM_PROMPT = """\
You are a strict fact-checker. Given a CLAIM and a SOURCE excerpt, decide
whether the SOURCE supports the CLAIM. Respond with exactly one token:
SUPPORTED  - the source clearly supports the claim
PARTIAL    - the source is related but does not fully support the claim
UNSUPPORTED - the source does not support the claim or contradicts it
"""


def _llm_judge(claim: str, source: str, model: str = "claude-haiku-4-5-20251001") -> str:
    """Returns 'SUPPORTED' | 'PARTIAL' | 'UNSUPPORTED'. Cached on disk."""
    cache = _load_judge_cache()
    key = _judge_key(claim, source)
    if key in cache:
        return cache[key]

    try:
        from langchain_anthropic import ChatAnthropic
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = ChatAnthropic(
            model_name=model,
            temperature=0,
            max_tokens_to_sample=8,
            api_key=os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY"),
        )
        resp = llm.invoke([
            SystemMessage(content=JUDGE_SYSTEM_PROMPT),
            HumanMessage(content=f"CLAIM:\n{claim}\n\nSOURCE:\n{source}"),
        ])
        token = (resp.content or "").strip().upper().split()[0] if hasattr(resp, "content") else ""
        if token not in {"SUPPORTED", "PARTIAL", "UNSUPPORTED"}:
            token = "UNSUPPORTED"
    except Exception:
        logger.exception("LLM judge failed for claim=%r", claim[:60])
        token = "UNSUPPORTED"

    cache[key] = token
    _save_judge_cache(cache)
    return token


def score_faithfulness(report: dict[str, Any], retrieved_docs: list[dict], use_llm: bool = True) -> dict:
    """Citation faithfulness: do citations actually appear in retrieved sources?

    Returns:
        {
          "score": float in [0, 1],
          "n_citations": int,
          "supported": int,
          "partial": int,
          "unsupported": int,
          "details": [{citation, verdict}, ...]
        }
    """
    citations = report.get("citations") or []
    n = len(citations)
    if n == 0:
        # Smalltalk/greeting reports legitimately have no citations.
        return {"score": 1.0, "n_citations": 0, "supported": 0, "partial": 0, "unsupported": 0, "details": []}

    chunks = [d.get("content") or d.get("text") or "" for d in retrieved_docs]
    joined_chunks = "\n\n---\n\n".join(chunks)[:8000]  # cap context

    counts = {"SUPPORTED": 0, "PARTIAL": 0, "UNSUPPORTED": 0}
    details = []

    for cit in citations:
        excerpt = cit.get("excerpt") or ""
        if not excerpt:
            counts["UNSUPPORTED"] += 1
            details.append({"excerpt": "", "verdict": "UNSUPPORTED", "reason": "empty excerpt"})
            continue

        # Cheap substring check first - covers verbatim quotes.
        if excerpt.strip() and excerpt.strip()[:80].lower() in joined_chunks.lower():
            counts["SUPPORTED"] += 1
            details.append({"excerpt": excerpt[:120], "verdict": "SUPPORTED", "reason": "substring match"})
            continue

        if use_llm and chunks:
            verdict = _llm_judge(excerpt, joined_chunks)
            counts[verdict] += 1
            details.append({"excerpt": excerpt[:120], "verdict": verdict, "reason": "llm judge"})
        else:
            counts["UNSUPPORTED"] += 1
            details.append({"excerpt": excerpt[:120], "verdict": "UNSUPPORTED", "reason": "no substring match (llm disabled)"})

    score = (counts["SUPPORTED"] + 0.5 * counts["PARTIAL"]) / n
    return {
        "score": round(score, 3),
        "n_citations": n,
        "supported": counts["SUPPORTED"],
        "partial": counts["PARTIAL"],
        "unsupported": counts["UNSUPPORTED"],
        "details": details,
    }


# ---------------------------------------------------------------------------
# 2. Factuality (must_contain)
# ---------------------------------------------------------------------------

def score_factuality(report: dict[str, Any], must_contain: list[str]) -> dict:
    """Returns score = matched / total over must_contain strings.

    Searches in summary, executive_summary, bull_case, bear_case, and
    risk_rationale combined. Case-insensitive substring match.
    """
    if not must_contain:
        return {"score": 1.0, "matched": 0, "total": 0, "missing": []}

    haystack = " ".join([
        str(report.get("summary") or ""),
        str(report.get("executive_summary") or ""),
        str(report.get("bull_case") or ""),
        str(report.get("bear_case") or ""),
        str(report.get("risk_rationale") or ""),
    ]).lower()

    matched = 0
    missing = []
    for needle in must_contain:
        if needle.lower() in haystack:
            matched += 1
        else:
            missing.append(needle)

    return {
        "score": round(matched / len(must_contain), 3),
        "matched": matched,
        "total": len(must_contain),
        "missing": missing,
    }


# ---------------------------------------------------------------------------
# 3. Citation doc-type coverage
# ---------------------------------------------------------------------------

def score_citation_doctypes(report: dict[str, Any], required_doc_types: list[str]) -> dict:
    """Did the report cite at least one source of each required doc_type?"""
    if not required_doc_types:
        return {"score": 1.0, "matched": 0, "total": 0, "missing": []}

    citations = report.get("citations") or []
    cited_types = {(c.get("doc_type") or "").upper() for c in citations}

    matched = 0
    missing = []
    for required in required_doc_types:
        if required.upper() in cited_types:
            matched += 1
        else:
            missing.append(required)

    return {
        "score": round(matched / len(required_doc_types), 3),
        "matched": matched,
        "total": len(required_doc_types),
        "missing": missing,
    }


# ---------------------------------------------------------------------------
# 4. Refusal / routing correctness
# ---------------------------------------------------------------------------

def score_refusal_correctness(report: dict[str, Any], expected_intent: str | None, is_refusal: bool) -> dict:
    """Did the supervisor route correctly?

    For is_refusal=True rows: intent should be 'greeting' or 'smalltalk'
    AND the report should NOT contain a risk_score or citations.

    For is_refusal=False rows: intent should be 'research_query'.
    """
    actual_intent = report.get("intent")

    if expected_intent is not None:
        intent_correct = actual_intent == expected_intent
    else:
        intent_correct = (
            (is_refusal and actual_intent in {"greeting", "smalltalk"})
            or (not is_refusal and actual_intent == "research_query")
        )

    if is_refusal:
        # Refusal-shaped reports should be empty of analysis artifacts.
        no_risk = report.get("risk_score") is None
        no_citations = not (report.get("citations") or [])
        shape_correct = no_risk and no_citations
    else:
        # Research reports should have at least a summary.
        shape_correct = bool(report.get("summary"))

    score = 1.0 if (intent_correct and shape_correct) else 0.0
    return {
        "score": score,
        "intent_correct": intent_correct,
        "shape_correct": shape_correct,
        "actual_intent": actual_intent,
        "expected_intent": expected_intent,
    }


# ---------------------------------------------------------------------------
# 5. Risk band check
# ---------------------------------------------------------------------------

_RISK_BANDS = {
    "low": (0, 33),
    "medium": (34, 66),
    "high": (67, 100),
}


def score_risk_band(report: dict[str, Any], expected_band: str | None) -> dict:
    """Did the risk_score fall in the expected band? Skipped if expected is None."""
    if expected_band is None:
        return {"score": None, "skipped": True}

    risk = report.get("risk_score")
    if risk is None:
        return {"score": 0.0, "skipped": False, "reason": "no risk_score in report"}

    lo, hi = _RISK_BANDS.get(expected_band, (None, None))
    if lo is None:
        return {"score": 0.0, "skipped": False, "reason": f"unknown band {expected_band!r}"}

    in_band = lo <= int(risk) <= hi
    return {
        "score": 1.0 if in_band else 0.0,
        "skipped": False,
        "actual_score": risk,
        "expected_band": expected_band,
        "expected_range": [lo, hi],
    }

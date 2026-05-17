"""Unit tests for the LangGraph agent modules."""

from __future__ import annotations

from agents.orchestrator import GraphState, merge_dicts, extend_list
from agents.report_agent import _score_to_level, _format_report_text


class TestReducers:
    def test_merge_dicts(self):
        left = {"a": 1, "b": 2}
        right = {"b": 3, "c": 4}
        result = merge_dicts(left, right)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_merge_dicts_empty(self):
        assert merge_dicts({}, {"a": 1}) == {"a": 1}
        assert merge_dicts({"a": 1}, {}) == {"a": 1}

    def test_extend_list(self):
        assert extend_list([1, 2], [3, 4]) == [1, 2, 3, 4]
        assert extend_list([], [1]) == [1]


class TestReportAgent:
    def test_score_to_level(self):
        assert _score_to_level(10) == "LOW"
        assert _score_to_level(25) == "LOW"
        assert _score_to_level(26) == "MODERATE"
        assert _score_to_level(50) == "MODERATE"
        assert _score_to_level(51) == "ELEVATED"
        assert _score_to_level(75) == "ELEVATED"
        assert _score_to_level(76) == "HIGH"
        assert _score_to_level(100) == "HIGH"

    def test_format_report_text(self):
        report = {
            "ticker": "AAPL",
            "question": "Test question?",
            "generated_at": "2026-04-05T12:00:00",
            "confidence": "high",
            "risk_score": 35,
            "risk_level": "MODERATE",
            "risk_rationale": "Low risk overall",
            "summary": "Apple is doing well.",
            "key_metrics": [
                {"name": "Revenue", "value": "$383B", "trend": "up", "context": "Grew 16%"},
            ],
            "citations": [
                {"source_index": 1, "doc_type": "10-K", "excerpt": "Revenue grew 16% YoY"},
            ],
        }
        text = _format_report_text(report)
        assert "AAPL" in text
        assert "35/100" in text
        assert "MODERATE" in text
        assert "Revenue" in text
        assert "[Source 1]" in text


class TestGraphState:
    def test_state_has_expected_keys(self):
        # Verify the TypedDict has the expected annotations
        annotations = GraphState.__annotations__
        assert "messages" in annotations
        assert "ticker" in annotations
        assert "question" in annotations
        assert "retrieved_docs" in annotations
        assert "tool_results" in annotations
        assert "final_report" in annotations

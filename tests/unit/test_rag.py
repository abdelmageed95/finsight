"""Unit tests for the RAG modules."""

from __future__ import annotations

from rag.retriever import RetrievedChunk, format_chunks_as_context
from rag.reranker import NoOpReranker
from rag.schemas import ReportSchema, Citation, KeyMetric


class TestRetrievedChunk:
    def test_from_query_result(self):
        result = {
            "id": "AAPL_123_0",
            "text": "Revenue grew 16%",
            "metadata": {
                "ticker": "AAPL",
                "doc_type": "10-K",
                "filed_date": "2024-11-01",
                "accession_number": "0000320193-24-000123",
                "source_url": "https://sec.gov/...",
                "chunk_index": 0,
            },
            "distance": 0.15,
        }
        chunk = RetrievedChunk.from_query_result(result)
        assert chunk.ticker == "AAPL"
        assert chunk.doc_type == "10-K"
        assert chunk.distance == 0.15
        assert chunk.text == "Revenue grew 16%"


class TestFormatContext:
    def test_empty_chunks(self):
        assert format_chunks_as_context([]) == "No relevant documents found."

    def test_formats_with_source_headers(self):
        chunk = RetrievedChunk(
            id="test_1",
            text="Apple revenue was $383B",
            ticker="AAPL",
            doc_type="10-K",
            filed_date="2024-11-01",
            accession_number="ACC-123",
            source_url="https://sec.gov",
            chunk_index=0,
            distance=0.1,
        )
        context = format_chunks_as_context([chunk])
        assert "[Source 1]" in context
        assert "10-K" in context
        assert "AAPL" in context
        assert "Apple revenue was $383B" in context


class TestNoOpReranker:
    def test_returns_top_n(self):
        chunks = [
            RetrievedChunk(
                id=f"test_{i}", text=f"chunk {i}", ticker="AAPL",
                doc_type="10-K", filed_date="", accession_number="",
                source_url="", chunk_index=i, distance=float(i) * 0.1,
            )
            for i in range(8)
        ]
        reranker = NoOpReranker(top_n=4)
        result = reranker.rerank("test query", chunks)
        assert len(result) == 4
        assert result[0].id == "test_0"


class TestReportSchema:
    def test_valid_report(self):
        report = ReportSchema(
            ticker="AAPL",
            summary="Apple shows strong growth.",
            risk_score=35,
            risk_rationale="Low risk due to strong financials.",
            key_metrics=[
                KeyMetric(name="Revenue", value="$383B", trend="up", context="Grew 16% YoY")
            ],
            citations=[
                Citation(source_index=1, doc_type="10-K", excerpt="Revenue grew 16%")
            ],
            confidence="high",
        )
        assert report.risk_score == 35
        assert len(report.key_metrics) == 1
        assert report.citations[0].source_index == 1

    def test_risk_score_bounds(self):
        import pytest
        with pytest.raises(Exception):
            ReportSchema(
                ticker="AAPL", summary="test", risk_score=101,
                risk_rationale="test", confidence="high",
            )

    def test_json_serialization(self):
        report = ReportSchema(
            ticker="AAPL", summary="Test", risk_score=50,
            risk_rationale="Test", confidence="medium",
        )
        data = report.model_dump()
        assert data["ticker"] == "AAPL"
        assert isinstance(data["key_metrics"], list)

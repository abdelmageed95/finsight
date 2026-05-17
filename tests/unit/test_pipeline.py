"""Unit tests for the data pipeline modules."""

from __future__ import annotations

from pipelines.cleaner import clean_filing_text, normalize_ticker
from pipelines.embedder import chunk_text
from pipelines.market_data import fetch_ohlcv, fetch_financials


class TestCleaner:
    def test_clean_filing_text_strips_html(self):
        raw = "<p>Hello <b>world</b></p>"
        result = clean_filing_text(raw)
        assert "<" not in result
        assert "Hello" in result
        assert "world" in result

    def test_clean_filing_text_collapses_whitespace(self):
        raw = "Hello    \n\n   world"
        result = clean_filing_text(raw)
        assert result == "Hello world"

    def test_normalize_ticker(self):
        assert normalize_ticker("  aapl  ") == "AAPL"
        assert normalize_ticker("MSFT") == "MSFT"


class TestChunker:
    def test_chunk_text_produces_chunks(self):
        long_text = "word " * 2000  # ~2000 tokens
        chunks = chunk_text(long_text)
        assert len(chunks) > 1
        # Token-level chunking at 512 tokens; "word " ≈ 1 token each
        # so each chunk is ~512 words = ~2560 chars
        for chunk in chunks:
            assert len(chunk) <= 3200

    def test_chunk_text_empty(self):
        assert chunk_text("") == []

    def test_chunk_text_short(self):
        chunks = chunk_text("short text")
        assert len(chunks) == 1
        assert chunks[0] == "short text"


class TestMarketData:
    def test_fetch_ohlcv_returns_records(self):
        records = fetch_ohlcv("AAPL", period="5d")
        assert isinstance(records, list)
        if records:  # may be empty on weekends
            assert "open" in records[0]
            assert "close" in records[0]
            assert "volume" in records[0]

    def test_fetch_financials_returns_info(self):
        info = fetch_financials("AAPL")
        assert isinstance(info, dict)
        assert "company_name" in info
        assert "pe_ratio" in info

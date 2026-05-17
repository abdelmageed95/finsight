"""Integration tests for the FastAPI backend.

Tests run against the app using httpx AsyncClient with lifespan context.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
import httpx
from httpx import ASGITransport

from api.main import app


@pytest_asyncio.fixture
async def client():
    """Async test client with app lifespan and clean DB pool."""
    from db.session import engine
    # Dispose stale connections before each test
    await engine.dispose()

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    await engine.dispose()


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

class TestHealth:
    @pytest.mark.asyncio
    async def test_health_returns_200(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("ok", "degraded")
        assert "db" in data
        assert "redis" in data
        assert "chroma" in data


# ---------------------------------------------------------------------------
# Auth / Token
# ---------------------------------------------------------------------------

class TestAuth:
    @pytest.mark.asyncio
    async def test_generate_token(self, client):
        resp = await client.post("/token", json={"username": "testuser"})
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_token_is_valid_jwt(self, client):
        resp = await client.post("/token", json={"username": "testuser"})
        token = resp.json()["access_token"]
        assert len(token.split(".")) == 3


# ---------------------------------------------------------------------------
# Analyze
# ---------------------------------------------------------------------------

class TestAnalyze:
    @pytest.mark.asyncio
    async def test_analyze_returns_job_id(self, client):
        resp = await client.post("/analyze", json={
            "ticker": "AAPL",
            "question": "What are the main risks?",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_analyze_with_auth(self, client):
        token_resp = await client.post("/token", json={"username": "testuser"})
        token = token_resp.json()["access_token"]

        resp = await client.post(
            "/analyze",
            json={"ticker": "MSFT", "question": "Is MSFT a good buy?"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"

    @pytest.mark.asyncio
    async def test_analyze_validates_ticker(self, client):
        resp = await client.post("/analyze", json={
            "ticker": "",
            "question": "What are the main risks?",
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_analyze_validates_question(self, client):
        resp = await client.post("/analyze", json={
            "ticker": "AAPL",
            "question": "hi",
        })
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

class TestReport:
    @pytest.mark.asyncio
    async def test_report_not_found(self, client):
        resp = await client.get("/report/nonexistent-job-id")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_report_after_analyze(self, client):
        """Submit a job then immediately poll — should return a valid status."""
        create_resp = await client.post("/analyze", json={
            "ticker": "AAPL",
            "question": "What are the main risks?",
        })
        job_id = create_resp.json()["job_id"]

        resp = await client.get(f"/report/{job_id}")
        assert resp.status_code == 200
        data = resp.json()
        # In test env, background task may complete/fail quickly
        assert data["status"] in ("pending", "running", "completed", "failed")
        assert data["ticker"] == "AAPL"


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

class TestHistory:
    @pytest.mark.asyncio
    async def test_history_returns_list(self, client):
        resp = await client.get("/history")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_history_with_ticker_filter(self, client):
        # Create a job
        await client.post("/analyze", json={
            "ticker": "TSLA",
            "question": "What is Tesla's outlook?",
        })

        resp = await client.get("/history?ticker=TSLA")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        for item in data:
            assert item["ticker"] == "TSLA"

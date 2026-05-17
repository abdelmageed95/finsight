"""GET /health — ALB health check endpoint."""

from __future__ import annotations

import os

import chromadb
from fastapi import APIRouter
from sqlalchemy import text

from api.dependencies import DbSession
from api.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check(db: DbSession):
    """Health check for ALB — verifies DB, Redis, and ChromaDB connectivity."""
    db_status = await _check_db(db)
    redis_status = await _check_redis()
    chroma_status = _check_chroma()

    overall = "ok" if all(s == "ok" for s in [db_status, redis_status, chroma_status]) else "degraded"

    return HealthResponse(
        status=overall,
        db=db_status,
        redis=redis_status,
        chroma=chroma_status,
    )


async def _check_db(db) -> str:
    try:
        await db.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        return "error"


async def _check_redis() -> str:
    try:
        import redis as redis_lib
        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r = redis_lib.from_url(url, socket_connect_timeout=2)
        r.ping()
        return "ok"
    except Exception:
        return "error"


def _check_chroma() -> str:
    try:
        host = os.getenv("CHROMA_HOST", "localhost")
        port = int(os.getenv("CHROMA_PORT", "8100"))
        client = chromadb.HttpClient(host=host, port=port)
        client.heartbeat()
        return "ok"
    except Exception:
        return "error"

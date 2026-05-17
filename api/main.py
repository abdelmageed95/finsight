"""FastAPI application factory with lifespan events.

Run locally:
    uvicorn api.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.middleware import RequestLoggingMiddleware, limiter, setup_logging
from api.routers import analyze, auth, conversations, demo, health, history, report, search, ticker

load_dotenv()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events.

    Startup:
        - Configure structured logging
        - Verify DB connectivity
        - Start the APScheduler (periodic data ingestion)

    Shutdown:
        - Stop the scheduler
        - Dispose the DB engine
    """
    # --- Startup ---
    setup_logging()
    logger.info("FinSight API starting up")

    # Verify DB connection
    from db.session import engine
    try:
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        logger.info("Database connection OK")
    except Exception:
        logger.exception("Database connection failed — API will start but DB queries will fail")

    # Start scheduler (optional — disable if SCHEDULER_ENABLED is not set)
    import os
    if os.getenv("SCHEDULER_ENABLED", "false").lower() == "true":
        from pipelines.scheduler import start_scheduler
        start_scheduler()
        logger.info("Scheduler started")

    yield

    # --- Shutdown ---
    logger.info("FinSight API shutting down")

    import os
    if os.getenv("SCHEDULER_ENABLED", "false").lower() == "true":
        from pipelines.scheduler import stop_scheduler
        stop_scheduler()

    from db.session import engine
    await engine.dispose()


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    app = FastAPI(
        title="FinSight API",
        description="AI-Powered Financial Research Agent",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Rate limiter
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # CORS — allow local frontend and any origins listed in CORS_ORIGINS
    import os
    cors_origins_env = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    )
    cors_origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Middleware
    app.add_middleware(RequestLoggingMiddleware)

    # Routers
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(analyze.router)
    app.include_router(report.router)
    app.include_router(history.router)
    app.include_router(ticker.router)
    app.include_router(conversations.router)
    app.include_router(search.router)
    app.include_router(demo.router)

    return app


app = create_app()

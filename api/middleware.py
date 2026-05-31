"""FastAPI middleware — structured logging, rate limiting."""

from __future__ import annotations

import logging
import time
import uuid

import structlog
from fastapi import Request
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Rate limiter (100 requests/hour per IP by default)
# ---------------------------------------------------------------------------

limiter = Limiter(key_func=get_remote_address, default_limits=["100/hour"])


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": f"Rate limit exceeded: {exc.detail}"},
    )


# ---------------------------------------------------------------------------
# Request logging middleware (pure ASGI — no BaseHTTPMiddleware)
# ---------------------------------------------------------------------------

class RequestLoggingMiddleware:
    """Logs every request with method, path, status, and duration.

    Uses pure ASGI protocol to avoid asyncpg conflicts caused by
    BaseHTTPMiddleware's task wrapping.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())[:8]
        start = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                # Inject X-Request-ID header
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)

        duration_ms = (time.perf_counter() - start) * 1000
        path = scope.get("path", "")
        method = scope.get("method", "")
        client_host = scope.get("client", ("unknown", 0))[0]

        logger.info(
            "request",
            request_id=request_id,
            method=method,
            path=path,
            status=status_code,
            duration_ms=round(duration_ms, 2),
            client=client_host,
        )


# ---------------------------------------------------------------------------
# Structured logging setup
# ---------------------------------------------------------------------------

def setup_logging():
    """Configure structlog for JSON output (production) or console (dev)."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

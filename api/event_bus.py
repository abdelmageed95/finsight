"""In-memory pub/sub for analysis job progress events.

Each analysis job gets an asyncio.Queue keyed by `job_id`. The LangGraph
background task publishes substantive progress messages as it advances; the
SSE endpoint at `/analyze/stream/{job_id}` consumes them.

Why in-memory: a single uvicorn process serves both the producer (background
task) and consumer (SSE handler), so a process-local registry is enough. If
we ever scale to multiple workers we'd swap this for Redis pub/sub.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Job_id -> Queue of events. Events are dicts.
_QUEUES: dict[str, asyncio.Queue] = {}
# Sentinel that signals "no more events for this job"
_DONE = object()
# Time-to-live for orphaned queues (no subscriber ever attached). 10 minutes.
_QUEUE_TTL_SECONDS = 600
_QUEUE_CREATED_AT: dict[str, float] = {}


def get_queue(job_id: str) -> asyncio.Queue:
    """Get or create the queue for this job. Idempotent."""
    q = _QUEUES.get(job_id)
    if q is None:
        q = asyncio.Queue(maxsize=256)
        _QUEUES[job_id] = q
        _QUEUE_CREATED_AT[job_id] = time.time()
    return q


def publish(job_id: str, event: dict[str, Any]) -> None:
    """Publish an event to the job's queue. Drops the event if no queue exists.

    Safe to call from any thread — uses Queue.put_nowait. If the consumer is
    slow and the queue is full, the oldest events are silently dropped via
    a try/except — better than blocking the LangGraph pipeline.
    """
    q = _QUEUES.get(job_id)
    if q is None:
        # No subscriber yet — create the queue so events buffer
        q = get_queue(job_id)
    try:
        q.put_nowait(event)
    except asyncio.QueueFull:
        logger.warning("Event bus queue full for job %s; dropping event", job_id)


def publish_threadsafe(loop: asyncio.AbstractEventLoop, job_id: str, event: dict[str, Any]) -> None:
    """Publish from a worker thread. Schedules the put on the given event loop."""
    if loop.is_closed():
        return
    asyncio.run_coroutine_threadsafe(_async_publish(job_id, event), loop)


async def _async_publish(job_id: str, event: dict[str, Any]) -> None:
    publish(job_id, event)


def close(job_id: str) -> None:
    """Mark this job's stream as complete. Subscribers see the sentinel and exit."""
    q = _QUEUES.get(job_id)
    if q is None:
        return
    try:
        q.put_nowait({"type": "_done"})
    except asyncio.QueueFull:
        pass


async def subscribe(job_id: str, timeout_seconds: float = 300.0):
    """Async generator yielding events for this job.

    Yields each published event in order. Exits when:
      - A `_done` sentinel event is received, or
      - `timeout_seconds` elapses with no events.
    """
    q = get_queue(job_id)
    deadline = time.time() + timeout_seconds
    try:
        while True:
            remaining = max(0.1, deadline - time.time())
            try:
                event = await asyncio.wait_for(q.get(), timeout=remaining)
            except asyncio.TimeoutError:
                logger.info("Event bus subscribe timeout for job %s", job_id)
                return
            if event.get("type") == "_done":
                return
            yield event
    finally:
        # Clean up: drop the queue once the subscriber leaves.
        _QUEUES.pop(job_id, None)
        _QUEUE_CREATED_AT.pop(job_id, None)


def gc_orphans() -> int:
    """Remove queues that were never subscribed to within their TTL.

    Should be called periodically. Returns the number of queues removed.
    """
    now = time.time()
    orphans = [
        jid for jid, t in _QUEUE_CREATED_AT.items()
        if (now - t) > _QUEUE_TTL_SECONDS
    ]
    for jid in orphans:
        _QUEUES.pop(jid, None)
        _QUEUE_CREATED_AT.pop(jid, None)
    if orphans:
        logger.info("Event bus GC: removed %d orphan queues", len(orphans))
    return len(orphans)

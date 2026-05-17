"""Conversation endpoints — create, list, get, find-by-ticker, and chat (with streaming)."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from api.dependencies import CurrentUser, DbSession
from api.schemas import (
    ChatMessageResponse,
    ConversationCreate,
    ConversationListItem,
    ConversationResponse,
    MessageCreate,
    TurnResponse,
)
from db.crud import add_turn, create_conversation, get_conversation, list_conversations
from db.models import Conversation

router = APIRouter(prefix="/conversations", tags=["conversations"])
logger = logging.getLogger(__name__)


def _turn_to_response(turn) -> TurnResponse:
    return TurnResponse(
        id=str(turn.id),
        role=turn.role,
        content=turn.content,
        job_id=turn.job_id,
        created_at=turn.created_at,
    )


@router.post("", response_model=ConversationResponse)
async def create(
    body: ConversationCreate,
    db: DbSession,
    user: CurrentUser,
):
    conv = await create_conversation(
        db,
        title=body.title,
        ticker=body.ticker,
        user_id=user.id,
    )
    await db.commit()
    return ConversationResponse(
        id=str(conv.id),
        ticker=conv.ticker,
        title=conv.title,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


@router.get("", response_model=list[ConversationListItem])
async def list_all(
    db: DbSession,
    user: CurrentUser,
):
    convs = await list_conversations(db, user_id=str(user.id))
    return [
        ConversationListItem(
            id=str(c.id),
            ticker=c.ticker,
            title=c.title,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in convs
    ]


@router.get("/by-ticker/{symbol}", response_model=ConversationResponse)
async def get_or_create_by_ticker(
    symbol: str,
    db: DbSession,
    user: CurrentUser,
):
    """Find the existing conversation for this user+ticker, or create one."""
    from sqlalchemy import select

    ticker = symbol.upper()
    result = await db.execute(
        select(Conversation).where(
            Conversation.user_id == user.id,
            Conversation.ticker == ticker,
        )
    )
    conv = result.scalar_one_or_none()

    if not conv:
        conv = await create_conversation(
            db,
            title=f"{ticker} research",
            ticker=ticker,
            user_id=user.id,
        )
        await db.commit()

    # Reload with turns
    conv = await get_conversation(db, conv.id)

    return ConversationResponse(
        id=str(conv.id),
        ticker=conv.ticker,
        title=conv.title,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        turns=[_turn_to_response(t) for t in conv.turns],
    )


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_by_id(
    conversation_id: str,
    db: DbSession,
    user: CurrentUser,
):
    conv = await get_conversation(db, conversation_id)
    if not conv or conv.user_id != user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ConversationResponse(
        id=str(conv.id),
        ticker=conv.ticker,
        title=conv.title,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        turns=[_turn_to_response(t) for t in conv.turns],
    )


# ======================================================================
# Non-streaming chat (kept for backward compat / simple clients)
# ======================================================================

@router.post("/{conversation_id}/messages", response_model=ChatMessageResponse)
async def send_message(
    conversation_id: str,
    body: MessageCreate,
    db: DbSession,
    user: CurrentUser,
):
    """Lightweight conversational RAG chat — no report created."""
    conv = await get_conversation(db, conversation_id)
    if not conv or conv.user_id != user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")

    ticker = conv.ticker
    if not ticker:
        raise HTTPException(status_code=400, detail="Conversation has no ticker")

    question = body.question

    if conv.title == f"{ticker} research" or conv.title == "New conversation":
        conv.title = question[:80]

    await add_turn(db, conv.id, role="user", content=question)

    prior_turns = [
        {"role": t.role, "content": t.content}
        for t in conv.turns
    ]

    try:
        result = await asyncio.to_thread(
            _run_chat_query, ticker, question, prior_turns
        )
        answer = result["answer"]
        citations = result["citations"]
        confidence = result["confidence"]
    except Exception as e:
        logger.exception("Chat query failed for conversation %s", conversation_id)
        answer = f"Sorry, I couldn't answer that question. Error: {e}"
        citations = []
        confidence = "low"

    await add_turn(db, conv.id, role="assistant", content=answer)
    await db.commit()

    return ChatMessageResponse(
        answer=answer,
        citations=citations,
        confidence=confidence,
    )


# ======================================================================
# Streaming chat (SSE) — the frontend's primary path
# ======================================================================

@router.post("/{conversation_id}/messages/stream")
async def stream_message(
    conversation_id: str,
    body: MessageCreate,
    db: DbSession,
    user: CurrentUser,
):
    """SSE streaming chat endpoint — streams tokens as they arrive."""
    conv = await get_conversation(db, conversation_id)
    if not conv or conv.user_id != user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")

    ticker = conv.ticker
    if not ticker:
        raise HTTPException(status_code=400, detail="Conversation has no ticker")

    question = body.question

    if conv.title == f"{ticker} research" or conv.title == "New conversation":
        conv.title = question[:80]

    await add_turn(db, conv.id, role="user", content=question)

    prior_turns = [
        {"role": t.role, "content": t.content}
        for t in conv.turns
    ]

    async def event_stream():
        full_answer = ""
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()
        SENTINEL = object()

        def producer():
            """Run the sync generator in a thread, push each event onto the queue."""
            try:
                from rag.chain import create_chat_chain
                chain = create_chat_chain()
                for event in chain.stream(
                    ticker=ticker,
                    question=question,
                    prior_turns=prior_turns,
                ):
                    asyncio.run_coroutine_threadsafe(queue.put(event), loop).result()
            except Exception as e:
                logger.exception("Stream producer error for conversation %s", conversation_id)
                asyncio.run_coroutine_threadsafe(
                    queue.put({"type": "error", "data": str(e)}), loop
                ).result()
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(SENTINEL), loop).result()

        # Kick off the producer thread — don't await, let it run in parallel
        task = asyncio.create_task(asyncio.to_thread(producer))

        try:
            while True:
                event = await queue.get()
                if event is SENTINEL:
                    break
                if event["type"] == "token":
                    full_answer += event["data"]
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            await task  # surface producer exceptions

        # Persist after streaming completes
        try:
            if not full_answer:
                full_answer = "Sorry, something went wrong."
            await add_turn(db, conv.id, role="assistant", content=full_answer)
            await db.commit()
        except Exception:
            logger.exception("Failed to persist streamed answer")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ======================================================================
# Sync helpers (run in thread)
# ======================================================================

def _run_chat_query(
    ticker: str,
    question: str,
    prior_turns: list[dict],
) -> dict:
    """Synchronous chat chain call — runs in a thread."""
    from rag.chain import create_chat_chain

    chain = create_chat_chain()
    return chain.invoke(
        ticker=ticker,
        question=question,
        prior_turns=prior_turns,
    )



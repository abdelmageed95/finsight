"""Reusable database queries."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chunk, Conversation, ConversationTurn, Filing, Financials, Price, Ticker


async def get_or_create_ticker(session: AsyncSession, symbol: str, **kwargs) -> Ticker:
    """Return existing ticker or create a new one."""
    result = await session.execute(select(Ticker).where(Ticker.symbol == symbol.upper()))
    ticker = result.scalar_one_or_none()
    if ticker is None:
        ticker = Ticker(symbol=symbol.upper(), **kwargs)
        session.add(ticker)
        await session.flush()
    return ticker


async def ticker_has_recent_prices(session: AsyncSession, ticker_id, days: int = 2) -> bool:
    """Check if we have price data newer than `days` ago."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    result = await session.execute(
        select(Price.id).where(Price.ticker_id == ticker_id, Price.date >= cutoff).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def get_filings_for_ticker(
    session: AsyncSession, ticker_id, filing_type: str | None = None
) -> list[Filing]:
    stmt = select(Filing).where(Filing.ticker_id == ticker_id)
    if filing_type:
        stmt = stmt.where(Filing.filing_type == filing_type)
    stmt = stmt.order_by(Filing.filed_date.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_unembedded_filings(session: AsyncSession) -> list[Filing]:
    """Return filings that have no chunks yet."""
    result = await session.execute(
        select(Filing).where(~Filing.chunks.any())
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

async def create_conversation(
    session: AsyncSession,
    title: str = "New conversation",
    ticker: str | None = None,
    user_id: str | None = None,
) -> Conversation:
    conv = Conversation(title=title, ticker=ticker, user_id=user_id)
    session.add(conv)
    await session.flush()
    return conv


async def get_conversation(session: AsyncSession, conversation_id) -> Conversation | None:
    from sqlalchemy.orm import selectinload

    result = await session.execute(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .options(selectinload(Conversation.turns))
    )
    return result.scalar_one_or_none()


async def list_conversations(
    session: AsyncSession,
    user_id: str | None = None,
    limit: int = 50,
) -> list[Conversation]:
    stmt = select(Conversation).order_by(Conversation.updated_at.desc()).limit(limit)
    if user_id:
        stmt = stmt.where(Conversation.user_id == user_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def add_turn(
    session: AsyncSession,
    conversation_id,
    role: str,
    content: str,
    job_id: str | None = None,
) -> ConversationTurn:
    turn = ConversationTurn(
        conversation_id=conversation_id,
        role=role,
        content=content,
        job_id=job_id,
    )
    session.add(turn)
    # Touch updated_at on the parent conversation
    from sqlalchemy import update
    await session.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(updated_at=datetime.utcnow())
    )
    await session.flush()
    return turn

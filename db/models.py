"""SQLAlchemy ORM models for FinSight."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(256), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=True)  # null for Google-only users
    name = Column(String(256), nullable=True)
    google_id = Column(String(256), unique=True, nullable=True, index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")
    reports = relationship("AnalysisReport", back_populates="user")


class Ticker(Base):
    __tablename__ = "tickers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol = Column(String(10), unique=True, nullable=False, index=True)
    company_name = Column(String(256))
    sector = Column(String(128))
    industry = Column(String(128))
    market_cap = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    prices = relationship("Price", back_populates="ticker", cascade="all, delete-orphan")
    filings = relationship("Filing", back_populates="ticker", cascade="all, delete-orphan")
    news_articles = relationship("NewsArticle", back_populates="ticker", cascade="all, delete-orphan")


class Price(Base):
    __tablename__ = "prices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker_id = Column(UUID(as_uuid=True), ForeignKey("tickers.id"), nullable=False)
    date = Column(DateTime, nullable=False)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)

    ticker = relationship("Ticker", back_populates="prices")

    __table_args__ = (
        UniqueConstraint("ticker_id", "date", name="uq_price_ticker_date"),
        Index("ix_price_ticker_date", "ticker_id", "date"),
    )


class Financials(Base):
    __tablename__ = "financials"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker_id = Column(UUID(as_uuid=True), ForeignKey("tickers.id"), nullable=False)
    period = Column(String(10), nullable=False)  # e.g. "2024-Q3", "2024-FY"
    revenue = Column(Float)
    net_income = Column(Float)
    eps = Column(Float)
    pe_ratio = Column(Float)
    gross_margin = Column(Float)
    fetched_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("ticker_id", "period", name="uq_financials_ticker_period"),
    )


class Filing(Base):
    __tablename__ = "filings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker_id = Column(UUID(as_uuid=True), ForeignKey("tickers.id"), nullable=False)
    filing_type = Column(String(10), nullable=False)  # "10-K", "10-Q"
    filed_date = Column(DateTime)
    accession_number = Column(String(30), unique=True)
    source_url = Column(Text)
    raw_text = Column(Text)
    # SHA-256 of raw_text at ingestion time. Used to detect filings whose
    # content changed (e.g. SEC amendment) so embed_all_pending can re-embed.
    content_hash = Column(String(64))
    # content_hash at the time the filing was last embedded. Differs from
    # content_hash → the embeddings are stale and must be regenerated.
    embedded_content_hash = Column(String(64))
    # SEC "period of report" — the fiscal period the filing *covers*, which
    # is NOT the filing date (a 10-K filed Feb 2025 reports on the prior FY).
    # Its calendar year drives temporal retrieval filtering.
    period_of_report = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    ticker = relationship("Ticker", back_populates="filings")
    chunks = relationship("Chunk", back_populates="filing", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_filing_ticker_type", "ticker_id", "filing_type"),
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filing_id = Column(UUID(as_uuid=True), ForeignKey("filings.id"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    token_count = Column(Integer)
    embedding_id = Column(String(128))  # ID in ChromaDB
    created_at = Column(DateTime, default=datetime.utcnow)

    filing = relationship("Filing", back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("filing_id", "chunk_index", name="uq_chunk_filing_index"),
    )


class AnalysisReport(Base):
    __tablename__ = "analysis_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    job_id = Column(String(64), unique=True, nullable=False, index=True)
    ticker_symbol = Column(String(30), nullable=False)
    question = Column(Text)
    status = Column(String(20), default="pending")  # pending, running, completed, failed
    summary = Column(Text)
    risk_score = Column(Integer)
    report_json = Column(Text)  # Full structured JSON output
    is_starred = Column(Boolean, default=False, nullable=False, server_default="false", index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)

    user = relationship("User", back_populates="reports")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    ticker = Column(String(10), nullable=True)
    title = Column(String(256), nullable=False, default="New conversation")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="conversations")
    turns = relationship("ConversationTurn", back_populates="conversation", cascade="all, delete-orphan", order_by="ConversationTurn.created_at")

    __table_args__ = (
        UniqueConstraint("user_id", "ticker", name="uq_conversation_user_ticker"),
    )


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False)
    role = Column(String(10), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    job_id = Column(String(64), nullable=True)  # links to AnalysisReport.job_id
    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="turns")

    __table_args__ = (
        Index("ix_turn_conversation", "conversation_id", "created_at"),
    )


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker_id = Column(UUID(as_uuid=True), ForeignKey("tickers.id"), nullable=False)
    title = Column(Text, nullable=False)
    url = Column(Text, nullable=False)
    source = Column(String(256))
    published_at = Column(DateTime)
    summary = Column(Text)
    sentiment_score = Column(Float)           # -1.0 to 1.0
    sentiment_label = Column(String(20))      # Bearish, Neutral, Bullish, etc.
    fetched_at = Column(DateTime, default=datetime.utcnow)

    ticker = relationship("Ticker", back_populates="news_articles")

    __table_args__ = (
        UniqueConstraint("ticker_id", "url", name="uq_news_ticker_url"),
        Index("ix_news_ticker_published", "ticker_id", "published_at"),
    )

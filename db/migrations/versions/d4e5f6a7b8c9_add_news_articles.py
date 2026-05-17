"""Add news_articles table.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-06
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "news_articles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("ticker_id", UUID(as_uuid=True), sa.ForeignKey("tickers.id"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("source", sa.String(256)),
        sa.Column("published_at", sa.DateTime()),
        sa.Column("summary", sa.Text()),
        sa.Column("sentiment_score", sa.Float()),
        sa.Column("sentiment_label", sa.String(20)),
        sa.Column("fetched_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("ticker_id", "url", name="uq_news_ticker_url"),
    )
    op.create_index("ix_news_ticker_published", "news_articles", ["ticker_id", "published_at"])


def downgrade() -> None:
    op.drop_index("ix_news_ticker_published")
    op.drop_table("news_articles")

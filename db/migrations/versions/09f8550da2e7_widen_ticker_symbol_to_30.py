"""Widen ticker_symbol to 30 chars for comparison labels.

Revision ID: 09f8550da2e7
Revises: d4e5f6a7b8c9
Create Date: 2026-04-06
"""

from alembic import op
import sqlalchemy as sa

revision = "09f8550da2e7"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "analysis_reports",
        "ticker_symbol",
        existing_type=sa.String(10),
        type_=sa.String(30),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "analysis_reports",
        "ticker_symbol",
        existing_type=sa.String(30),
        type_=sa.String(10),
        existing_nullable=False,
    )

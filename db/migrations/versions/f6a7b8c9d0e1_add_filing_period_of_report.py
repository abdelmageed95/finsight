"""Add period_of_report column to filings.

Stores the SEC "period of report" date (the fiscal period a filing covers,
distinct from the filing date) so retrieval can filter chunks by fiscal year.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-05-16
"""

from alembic import op
import sqlalchemy as sa


revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "filings",
        sa.Column("period_of_report", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("filings", "period_of_report")

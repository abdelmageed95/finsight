"""Add is_starred column to analysis_reports.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-29
"""

from alembic import op
import sqlalchemy as sa


revision = "e5f6a7b8c9d0"
down_revision = "09f8550da2e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "analysis_reports",
        sa.Column(
            "is_starred",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "ix_analysis_reports_is_starred",
        "analysis_reports",
        ["is_starred"],
    )


def downgrade() -> None:
    op.drop_index("ix_analysis_reports_is_starred", table_name="analysis_reports")
    op.drop_column("analysis_reports", "is_starred")

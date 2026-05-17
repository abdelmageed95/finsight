"""add_users_and_auth

Add users table, user_id FK on analysis_reports and conversations,
unique constraint on (user_id, ticker) for conversations.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-05 22:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Users table
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(256), unique=True, nullable=False, index=True),
        sa.Column("password_hash", sa.String(256), nullable=True),
        sa.Column("name", sa.String(256), nullable=True),
        sa.Column("google_id", sa.String(256), unique=True, nullable=True, index=True),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    # Add user_id to analysis_reports
    op.add_column(
        "analysis_reports",
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True, index=True),
    )

    # Recreate conversations.user_id as UUID FK (was String(128))
    op.drop_index("ix_conversations_user_id", table_name="conversations", if_exists=True)
    op.drop_column("conversations", "user_id")
    op.add_column(
        "conversations",
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True, index=True),
    )

    # One conversation per user+ticker
    op.create_unique_constraint("uq_conversation_user_ticker", "conversations", ["user_id", "ticker"])


def downgrade() -> None:
    op.drop_constraint("uq_conversation_user_ticker", "conversations", type_="unique")
    op.drop_column("conversations", "user_id")
    op.add_column(
        "conversations",
        sa.Column("user_id", sa.String(128), nullable=True, index=True),
    )
    op.drop_column("analysis_reports", "user_id")
    op.drop_table("users")

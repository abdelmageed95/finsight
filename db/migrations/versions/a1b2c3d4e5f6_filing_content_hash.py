"""filing_content_hash

Adds content_hash and embedded_content_hash columns to the filings table so the
embedder can detect when a filing's raw_text changed (e.g. SEC amendment) and
re-embed only the affected filing.

Revision ID: a1b2c3d4e5f6
Revises: 314798936e19
Create Date: 2026-04-05 16:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "314798936e19"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("filings", sa.Column("content_hash", sa.String(length=64), nullable=True))
    op.add_column("filings", sa.Column("embedded_content_hash", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("filings", "embedded_content_hash")
    op.drop_column("filings", "content_hash")

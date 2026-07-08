"""add chunks full-text search vector

Revision ID: 20260708_1400
Revises: 20260707_1800
Create Date: 2026-07-08 14:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260708_1400"
down_revision: str | None = "20260707_1800"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chunks",
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True),
    )
    op.execute("UPDATE chunks SET search_vector = to_tsvector('english', text)")
    op.create_index(
        "ix_chunks_search_vector",
        "chunks",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_chunks_search_vector", table_name="chunks")
    op.drop_column("chunks", "search_vector")

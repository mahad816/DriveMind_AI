"""add documents extracted_text column

Revision ID: 20260707_1800
Revises: 20260707_1700
Create Date: 2026-07-07 18:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260707_1800"
down_revision: str | None = "20260707_1700"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("extracted_text", sa.Text(), server_default="", nullable=False),
    )
    op.alter_column("documents", "extracted_text", server_default=None)


def downgrade() -> None:
    op.drop_column("documents", "extracted_text")

"""add oauth pending states table

Revision ID: 20260707_1600
Revises: 20260707_1500
Create Date: 2026-07-07 16:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260707_1600"
down_revision: str | None = "20260707_1500"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "oauth_pending_states",
        sa.Column("state", sa.String(length=255), nullable=False),
        sa.Column("code_verifier", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("state"),
    )


def downgrade() -> None:
    op.drop_table("oauth_pending_states")

"""Add nullable encrypted Google credential envelope; no backfill.

Revision ID: 20261010_1200
Revises: 20261009_1300
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261010_1200"
down_revision: str | None = "20261009_1300"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "google_oauth_tokens", sa.Column("encrypted_credentials", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    # Drops only the optional envelope; established plaintext values remain intact.
    op.drop_column("google_oauth_tokens", "encrypted_credentials")

"""Add a structured failure class to indexing jobs (Checkpoint A).

Nullable and unindexed: existing rows stay NULL, which clients read as "unclassified, pause".
"""

from alembic import op
import sqlalchemy as sa

revision = "20261125_1200"
down_revision = "20261121_1200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("indexing_jobs", sa.Column("failure_class", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("indexing_jobs", "failure_class")

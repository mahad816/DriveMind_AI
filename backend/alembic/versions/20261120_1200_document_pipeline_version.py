"""Record which extraction pipeline produced each document's text.

Existing rows were produced by the first pipeline (version 1). The application raises its own
version whenever readers improve, and re-reads files whose stored version is older.
"""

from alembic import op
import sqlalchemy as sa

revision = "20261120_1200"
down_revision = "20261015_1200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("pipeline_version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("documents", "pipeline_version")

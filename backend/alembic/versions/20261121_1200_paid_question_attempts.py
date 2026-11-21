"""Add the paid-question attempt ledger (M0-SEC ticket 05).

One row per admitted paid question, per Owner; the Owner reference cascades on delete.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261121_1200"
down_revision = "20261120_1200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paid_question_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_paid_question_attempts_owner_started",
        "paid_question_attempts",
        ["owner_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_paid_question_attempts_owner_started", table_name="paid_question_attempts")
    op.drop_table("paid_question_attempts")

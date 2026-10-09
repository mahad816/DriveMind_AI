"""Add inactive shared application sessions.

Revision ID: 20261009_1200
Revises: 20260708_1400
"""

from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261009_1200"
down_revision: str | None = "20260708_1400"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "application_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("credential_hash", sa.LargeBinary(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "GOOGLE_ACCOUNT",
                "DEMO_VISITOR",
                native_enum=False,
                create_constraint=True,
                name="ck_application_sessions_kind",
            ),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("csrf_secret", sa.LargeBinary(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("credential_hash", name="uq_application_sessions_credential_hash"),
        sa.CheckConstraint(
            "(kind = 'GOOGLE_ACCOUNT' AND user_id IS NOT NULL) OR "
            "(kind = 'DEMO_VISITOR' AND user_id IS NULL)",
            name="ck_application_sessions_owner",
        ),
        sa.CheckConstraint(
            "octet_length(credential_hash) = 32", name="ck_application_sessions_digest"
        ),
        sa.CheckConstraint("octet_length(csrf_secret) = 32", name="ck_application_sessions_csrf"),
        sa.CheckConstraint("expires_at > created_at", name="ck_application_sessions_expiry"),
    )
    op.create_index("ix_application_sessions_user_id", "application_sessions", ["user_id"])
    op.create_index("ix_application_sessions_expires_at", "application_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_application_sessions_expires_at", table_name="application_sessions")
    op.drop_index("ix_application_sessions_user_id", table_name="application_sessions")
    op.drop_table("application_sessions")

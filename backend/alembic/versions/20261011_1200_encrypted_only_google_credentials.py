"""Encrypted-only credentials. Operator-approved empty credential table required.

Never delete credentials or decrypt them into plaintext during migration.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261011_1200"
down_revision: str | None = "20261010_1200"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _require_empty() -> None:
    # PostgreSQL block works in offline SQL too; lock prevents concurrent inserts.
    op.execute("LOCK TABLE google_oauth_tokens IN ACCESS EXCLUSIVE MODE")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM google_oauth_tokens) THEN RAISE EXCEPTION 'Credential cutover requires an explicitly approved empty credential table'; END IF; END $$"
    )


def upgrade() -> None:
    _require_empty()
    op.drop_column("google_oauth_tokens", "access_token")
    op.drop_column("google_oauth_tokens", "refresh_token")
    op.alter_column(
        "google_oauth_tokens", "encrypted_credentials", existing_type=sa.Text(), nullable=False
    )
    for name in ("credential_revision", "grant_epoch"):
        op.add_column(
            "google_oauth_tokens",
            sa.Column(name, sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        )
    op.add_column(
        "google_oauth_tokens",
        sa.Column("grant_status", sa.String(24), server_default="ACTIVE", nullable=False),
    )
    op.add_column(
        "google_oauth_tokens", sa.Column("refresh_claim_id", postgresql.UUID(as_uuid=True))
    )
    op.add_column("google_oauth_tokens", sa.Column("refresh_claim_state", sa.String(16)))
    op.add_column(
        "google_oauth_tokens", sa.Column("refresh_claim_expires_at", sa.DateTime(timezone=True))
    )
    op.create_check_constraint(
        "ck_google_grant_status",
        "google_oauth_tokens",
        "grant_status IN ('ACTIVE','RECOVERY_REQUIRED','REAUTH_REQUIRED')",
    )
    op.create_check_constraint(
        "ck_google_grant_versions",
        "google_oauth_tokens",
        "credential_revision >= 1 AND grant_epoch >= 1",
    )
    op.create_check_constraint(
        "ck_google_envelope_size",
        "google_oauth_tokens",
        "length(encrypted_credentials) BETWEEN 1 AND 32768",
    )
    op.create_check_constraint(
        "ck_google_refresh_claim",
        "google_oauth_tokens",
        "(refresh_claim_id IS NULL AND refresh_claim_state IS NULL AND refresh_claim_expires_at IS NULL) OR (refresh_claim_id IS NOT NULL AND refresh_claim_state IS NOT NULL AND refresh_claim_state IN ('PREPARED','SUBMITTED') AND refresh_claim_expires_at IS NOT NULL)",
    )


def downgrade() -> None:
    # Structural downgrade only. Populated encrypted stores require a forward fix.
    _require_empty()
    for name in (
        "ck_google_refresh_claim",
        "ck_google_envelope_size",
        "ck_google_grant_versions",
        "ck_google_grant_status",
    ):
        op.drop_constraint(name, "google_oauth_tokens", type_="check")
    for name in (
        "refresh_claim_expires_at",
        "refresh_claim_state",
        "refresh_claim_id",
        "grant_status",
        "grant_epoch",
        "credential_revision",
    ):
        op.drop_column("google_oauth_tokens", name)
    op.alter_column(
        "google_oauth_tokens", "encrypted_credentials", existing_type=sa.Text(), nullable=True
    )
    op.add_column("google_oauth_tokens", sa.Column("access_token", sa.Text(), nullable=False))
    op.add_column("google_oauth_tokens", sa.Column("refresh_token", sa.Text(), nullable=True))

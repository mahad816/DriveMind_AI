"""Add optional browser-bound Google login state; preserve legacy OAuth rows.

Revision ID: 20261009_1300
Revises: 20261009_1200
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261009_1300"
down_revision: str | None = "20261009_1200"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# Frozen SQL: migrations must not depend on mutable application models.
_CHECK = """
(browser_binding_hash IS NULL AND nonce IS NULL AND intent IS NULL
 AND initiating_session_id IS NULL AND initiating_credential_hash IS NULL)
OR (browser_binding_hash IS NOT NULL AND octet_length(browser_binding_hash) = 32
 AND nonce IS NOT NULL AND length(nonce) = 43 AND intent IS NOT NULL
 AND intent IN ('LOGIN', 'CONNECT_DRIVE')
 AND (initiating_credential_hash IS NULL OR octet_length(initiating_credential_hash) = 32)
 AND (initiating_session_id IS NULL OR initiating_credential_hash IS NOT NULL)
 AND (intent = 'LOGIN' OR
      (initiating_session_id IS NOT NULL AND initiating_credential_hash IS NOT NULL)))
"""


def upgrade() -> None:
    op.add_column("oauth_pending_states", sa.Column("browser_binding_hash", sa.LargeBinary()))
    op.add_column("oauth_pending_states", sa.Column("nonce", sa.String(43)))
    op.add_column("oauth_pending_states", sa.Column("intent", sa.String(20)))
    op.add_column("oauth_pending_states", sa.Column("initiating_session_id", postgresql.UUID()))
    op.add_column("oauth_pending_states", sa.Column("initiating_credential_hash", sa.LargeBinary()))
    op.create_foreign_key(
        "fk_oauth_pending_session",
        "oauth_pending_states",
        "application_sessions",
        ["initiating_session_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint("ck_oauth_pending_bound_state", "oauth_pending_states", _CHECK)


def downgrade() -> None:
    # Never turn a secure transaction into a redeemable legacy OAuth state.
    op.execute("DELETE FROM oauth_pending_states WHERE browser_binding_hash IS NOT NULL")
    op.drop_constraint("ck_oauth_pending_bound_state", "oauth_pending_states", type_="check")
    op.drop_constraint("fk_oauth_pending_session", "oauth_pending_states", type_="foreignkey")
    for column in (
        "initiating_credential_hash",
        "initiating_session_id",
        "intent",
        "nonce",
        "browser_binding_hash",
    ):
        op.drop_column("oauth_pending_states", column)

"""Preserve bounded operator recovery evidence separately from original attempts."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261014_1200"
down_revision = "20261013_1200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "indexing_jobs", sa.Column("recovery_manifest", postgresql.JSONB(), nullable=True)
    )
    op.create_check_constraint(
        "ck_indexing_jobs_recovery_manifest_size",
        "indexing_jobs",
        "recovery_manifest IS NULL OR octet_length(recovery_manifest::text) <= 2097152",
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM indexing_jobs WHERE recovery_manifest IS NOT NULL)"
            )
        )
        .scalar()
    ):
        raise RuntimeError("Retain operator recovery evidence before downgrading")
    op.drop_constraint("ck_indexing_jobs_recovery_manifest_size", "indexing_jobs", type_="check")
    op.drop_column("indexing_jobs", "recovery_manifest")

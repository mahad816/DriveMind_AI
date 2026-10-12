"""Add bounded BUILD attempt evidence without reinterpreting historical jobs."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261013_1200"
down_revision = "20261012_1200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("indexing_jobs", sa.Column("attempt_manifest", postgresql.JSONB(), nullable=True))
    op.create_check_constraint(
        "ck_indexing_jobs_manifest_size",
        "indexing_jobs",
        "attempt_manifest IS NULL OR octet_length(attempt_manifest::text) <= 2097152",
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM indexing_jobs WHERE attempt_manifest IS NOT NULL)"
            )
        )
        .scalar()
    ):
        raise RuntimeError("Retain BUILD attempt evidence before downgrading")
    op.drop_constraint("ck_indexing_jobs_manifest_size", "indexing_jobs", type_="check")
    op.drop_column("indexing_jobs", "attempt_manifest")

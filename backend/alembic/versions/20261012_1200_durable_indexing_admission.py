"""Add managed indexing inputs and owner admission exclusion; preserve historical jobs."""

from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261012_1200"
down_revision: str | None = "20261011_1300"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

CONSTRAINTS = {
    "operation": "operation IS NULL OR operation IN ('SYNC', 'INGEST', 'CHUNK', 'BUILD')",
    "sync_target": "operation IS NULL OR (operation != 'SYNC' OR file_id IS NULL)",
    "full_sync": "operation IS NULL OR operation = 'SYNC' OR NOT full_sync",
    "recovery_operation": "NOT recovery_required OR operation IS NOT NULL",
    "progress": "total >= 0 AND processed >= 0 AND succeeded >= 0 AND failed >= 0 AND skipped >= 0",
}


def upgrade() -> None:
    op.add_column("indexing_jobs", sa.Column("operation", sa.String(6), nullable=True))
    for name in ("file_id", "claim_id", "worker_id"):
        op.add_column(
            "indexing_jobs", sa.Column(name, postgresql.UUID(as_uuid=True), nullable=True)
        )
    for name in ("heartbeat_at", "lease_expires_at"):
        op.add_column("indexing_jobs", sa.Column(name, sa.DateTime(timezone=True), nullable=True))
    for name in ("full_sync", "recovery_required"):
        op.add_column(
            "indexing_jobs",
            sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    for name in ("total", "processed", "succeeded", "failed", "skipped"):
        op.add_column(
            "indexing_jobs", sa.Column(name, sa.Integer(), nullable=False, server_default="0")
        )
    for name, expression in CONSTRAINTS.items():
        op.create_check_constraint("ck_indexing_jobs_" + name, "indexing_jobs", expression)
    op.create_index(
        "uq_indexing_jobs_unresolved_owner",
        "indexing_jobs",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text(
            "operation IS NOT NULL AND (status IN ('QUEUED', 'RUNNING') OR recovery_required)"
        ),
    )


def downgrade() -> None:
    # Do not discard durable inputs or recovery exclusions. Downgrade is only safe
    # before any managed job exists; historical rows are preserved in either case.
    op.execute("LOCK TABLE indexing_jobs IN ACCESS EXCLUSIVE MODE")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM indexing_jobs WHERE operation IS NOT NULL) THEN RAISE EXCEPTION 'Cannot remove managed indexing job inputs'; END IF; END $$"
    )
    op.drop_index("uq_indexing_jobs_unresolved_owner", table_name="indexing_jobs")
    for name in CONSTRAINTS:
        op.drop_constraint("ck_indexing_jobs_" + name, "indexing_jobs", type_="check")
    for name in (
        "operation",
        "file_id",
        "claim_id",
        "worker_id",
        "heartbeat_at",
        "lease_expires_at",
        "full_sync",
        "recovery_required",
        "total",
        "processed",
        "succeeded",
        "failed",
        "skipped",
    ):
        op.drop_column("indexing_jobs", name)

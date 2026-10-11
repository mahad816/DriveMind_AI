"""Scope Google provider file identity to its owner, preserving internal UUIDs."""

from collections.abc import Sequence

from alembic import op

revision: str = "20261011_1300"
down_revision: str | None = "20261011_1200"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

OWNER_UNIQUE = "uq_drive_files_user_id_drive_file_id"
GLOBAL_UNIQUE = "drive_files_drive_file_id_key"


def upgrade() -> None:
    # DDL is transactional. Serialize writes while replacing uniqueness; never rewrite rows.
    op.execute("LOCK TABLE drive_files IN ACCESS EXCLUSIVE MODE")
    op.create_unique_constraint(OWNER_UNIQUE, "drive_files", ["user_id", "drive_file_id"])
    op.drop_constraint(GLOBAL_UNIQUE, "drive_files", type_="unique")


def downgrade() -> None:
    op.execute("LOCK TABLE drive_files IN ACCESS EXCLUSIVE MODE")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM drive_files GROUP BY drive_file_id "
        "HAVING count(*) > 1) THEN RAISE EXCEPTION "
        "'Cannot restore global Drive file uniqueness: owner-scoped duplicates exist'; "
        "END IF; END $$"
    )
    op.create_unique_constraint(GLOBAL_UNIQUE, "drive_files", ["drive_file_id"])
    op.drop_constraint(OWNER_UNIQUE, "drive_files", type_="unique")

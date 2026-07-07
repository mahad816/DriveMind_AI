"""create initial phase2 schema

Revision ID: 20260707_1409
Revises:
Create Date: 2026-07-07 14:09:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260707_1409"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


drive_file_status_enum = sa.Enum(
    "discovered",
    "indexing",
    "indexed",
    "failed",
    "skipped",
    name="drive_file_status",
    native_enum=False,
)

indexing_job_status_enum = sa.Enum(
    "queued",
    "running",
    "completed",
    "failed",
    "canceled",
    name="indexing_job_status",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("google_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("google_id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=False)
    op.create_index("ix_users_google_id", "users", ["google_id"], unique=False)

    op.create_table(
        "drive_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("drive_file_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=1024), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("folder_path", sa.String(length=2048), nullable=True),
        sa.Column("modified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", drive_file_status_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("drive_file_id"),
    )
    op.create_index("ix_drive_files_drive_file_id", "drive_files", ["drive_file_id"], unique=False)
    op.create_index("ix_drive_files_mime_type", "drive_files", ["mime_type"], unique=False)
    op.create_index("ix_drive_files_modified_at", "drive_files", ["modified_at"], unique=False)
    op.create_index("ix_drive_files_status", "drive_files", ["status"], unique=False)
    op.create_index("ix_drive_files_user_id_modified_at", "drive_files", ["user_id", "modified_at"], unique=False)

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("drive_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("extracted_text_hash", sa.String(length=128), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["drive_file_id"], ["drive_files.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_documents_drive_file_id", "documents", ["drive_file_id"], unique=False)
    op.create_index("ix_documents_extracted_text_hash", "documents", ["extracted_text_hash"], unique=False)

    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chunks_document_id_chunk_index", "chunks", ["document_id", "chunk_index"], unique=True)

    op.create_table(
        "indexing_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", indexing_job_status_enum, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_indexing_jobs_user_id_status", "indexing_jobs", ["user_id", "status"], unique=False)

    op.create_table(
        "query_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("citations_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_query_history_user_id_created_at", "query_history", ["user_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_query_history_user_id_created_at", table_name="query_history")
    op.drop_table("query_history")

    op.drop_index("ix_indexing_jobs_user_id_status", table_name="indexing_jobs")
    op.drop_table("indexing_jobs")

    op.drop_index("ix_chunks_document_id_chunk_index", table_name="chunks")
    op.drop_table("chunks")

    op.drop_index("ix_documents_extracted_text_hash", table_name="documents")
    op.drop_index("ix_documents_drive_file_id", table_name="documents")
    op.drop_table("documents")

    op.drop_index("ix_drive_files_user_id_modified_at", table_name="drive_files")
    op.drop_index("ix_drive_files_status", table_name="drive_files")
    op.drop_index("ix_drive_files_modified_at", table_name="drive_files")
    op.drop_index("ix_drive_files_mime_type", table_name="drive_files")
    op.drop_index("ix_drive_files_drive_file_id", table_name="drive_files")
    op.drop_table("drive_files")

    op.drop_index("ix_users_google_id", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

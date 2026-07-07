"""Extracted document model."""

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin


class Document(TimestampMixin, Base):
    """Extracted and normalized document metadata derived from a drive file."""

    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_drive_file_id", "drive_file_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    drive_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("drive_files.id", ondelete="CASCADE"),
        nullable=False,
    )
    extracted_text_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    drive_file = relationship("DriveFile", back_populates="documents")
    chunks = relationship("Chunk", back_populates="document")

"""Drive file metadata model."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import DriveFileStatus
from app.db.mixins import TimestampMixin


class DriveFile(TimestampMixin, Base):
    """Metadata record for a Google Drive file tracked by indexing."""

    __tablename__ = "drive_files"
    __table_args__ = (
        Index("ix_drive_files_user_id_modified_at", "user_id", "modified_at"),
        Index("ix_drive_files_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    drive_file_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(1024), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    folder_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    modified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[DriveFileStatus] = mapped_column(
        Enum(DriveFileStatus, name="drive_file_status", native_enum=False),
        default=DriveFileStatus.DISCOVERED,
        nullable=False,
    )

    user = relationship("User", back_populates="drive_files")
    documents = relationship("Document", back_populates="drive_file")

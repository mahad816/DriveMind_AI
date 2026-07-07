"""Schemas for document ingestion API responses."""

from uuid import UUID

from pydantic import Field

from app.schemas.common import SchemaBase


class IngestionResponse(SchemaBase):
    """Result returned after a text ingestion run completes."""

    job_id: UUID
    user_id: UUID
    ingested: int = Field(ge=0)
    unchanged: int = Field(ge=0)
    failed: int = Field(ge=0)
    skipped: int = Field(ge=0)
    total: int = Field(ge=0)
    message: str

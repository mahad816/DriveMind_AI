"""Schemas for vector index build API responses."""

from uuid import UUID

from pydantic import Field

from app.schemas.common import SchemaBase


class IndexBuildResponse(SchemaBase):
    """Result returned after a chunk embedding index build completes."""

    job_id: UUID
    user_id: UUID
    embedded: int = Field(ge=0)
    unchanged: int = Field(ge=0)
    skipped: int = Field(ge=0)
    failed: int = Field(ge=0, description="Documents that could not be embedded or stored")
    removed: int = Field(ge=0, description="Stale vectors removed from Qdrant")
    total: int = Field(ge=0)
    message: str

"""Common schema primitives shared across API contracts."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SchemaBase(BaseModel):
    """Base schema config used across DriveMind models."""

    model_config = ConfigDict(from_attributes=True)


class TimestampedSchema(SchemaBase):
    """Schema mixin including common audit timestamps."""

    created_at: datetime
    updated_at: datetime


class IdentifierSchema(SchemaBase):
    """Schema mixin including UUID identifier."""

    id: UUID

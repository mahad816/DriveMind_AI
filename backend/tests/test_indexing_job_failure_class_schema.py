"""Container-free: the public job shape carries a structured failure class from a fixed vocabulary only."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.schemas.indexing import IndexingJobRead

NOW = datetime.now(UTC)


def read(**extra):
    return IndexingJobRead.model_validate(
        {
            "id": uuid4(),
            "user_id": uuid4(),
            "status": "failed",
            "created_at": NOW,
            "updated_at": NOW,
            **extra,
        }
    )


@pytest.mark.parametrize(
    "value",
    ["document", "infrastructure", "provider", "authentication", "configuration", "unknown"],
)
def test_fixed_vocabulary_is_exposed(value):
    assert read(failure_class=value).failure_class == value


@pytest.mark.parametrize("value", ["Document", "disk full", "", "document ", None, 3, {"a": 1}])
def test_anything_else_is_not_a_class_and_reads_as_none(value):
    assert read(failure_class=value).failure_class is None


def test_older_records_without_a_class_read_as_none():
    assert read().failure_class is None

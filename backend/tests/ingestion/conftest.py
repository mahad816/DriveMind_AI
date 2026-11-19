"""Shared ingestion-test hygiene."""

from collections.abc import Generator

import pytest

from app.ingestion.extractors import (
    clear_extractors,
    register_builtin_extractors,
    reset_builtin_extractors,
)


@pytest.fixture(autouse=True)
def _restore_builtin_extractors() -> Generator[None, None, None]:
    """These tests empty the process-wide extractor registry; put it back afterwards.

    Otherwise later tests in the same run (e.g. real ingestion) find no extractor for
    text/plain and every file fails. Teardown here runs after each module's own cleanup.
    """
    yield
    clear_extractors()
    reset_builtin_extractors()
    register_builtin_extractors()

"""Logging utilities for DriveMind backend."""

import logging


def configure_logging(log_level: str = "INFO") -> None:
    """Configure root logger once using a concise structured format."""
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

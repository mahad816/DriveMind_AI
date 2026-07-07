"""Document ingestion, extraction, and chunking pipeline."""

from app.ingestion.chunking import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_TARGET_CHUNK_SIZE,
    ChunkingConfig,
    TextChunk,
    chunk_text,
)
from app.ingestion.hash_util import compute_extracted_text_hash

__all__ = [
    "DEFAULT_CHUNK_OVERLAP",
    "DEFAULT_TARGET_CHUNK_SIZE",
    "ChunkingConfig",
    "TextChunk",
    "chunk_text",
    "compute_extracted_text_hash",
]

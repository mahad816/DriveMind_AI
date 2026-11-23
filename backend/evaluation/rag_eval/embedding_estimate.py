"""What embedding a corpus will cost, from the text the index will really embed (free; no provider call).

The estimate extracts every file with the product's own readers, splits the text with the product's own
chunker (so the overlap between neighbouring chunks is counted, because the overlap is embedded too), and
prices the tokens at the recorded input price of the configured embedding model.

No tokenizer is installed in the project, so the token count is an upper bound taken from UTF-8 bytes
(``BYTES_PER_TOKEN``), then raised by ``SAFETY_MARGIN``. Bytes, not characters: Urdu and other non-Latin text
needs several bytes per character, and it is also the text that tokenizers split into the most tokens.
"""

import math
from collections.abc import Mapping, Sequence
from typing import Any

from app.ingestion.chunking import DEFAULT_CHUNK_OVERLAP, DEFAULT_TARGET_CHUNK_SIZE, chunk_text

from .corpus import CorpusFile, extract_text
from .meter import PRICE_TABLE_DATE, price_for

BYTES_PER_TOKEN = (
    3  # English text is about 4 bytes per token, Urdu and dense numbers fewer: 3 is an upper bound
)
SAFETY_MARGIN = 1.2


def extract_texts(files: Sequence[CorpusFile]) -> dict[str, str]:
    """Path -> text exactly as the product's extractors read it (slow for the public PDFs: about 2 minutes)."""
    return {file.path: extract_text(file) for file in files}


def estimate_embedding(texts: Mapping[str, str], model: str) -> dict[str, Any]:
    """Tokens and dollars for embedding every chunk of ``texts`` from scratch with ``model``.

    Raises ``KeyError`` for a model without a recorded price. It never edits the price table.
    """
    price = price_for(model)["input"]
    chunks = [chunk.text for text in texts.values() for chunk in chunk_text(text)]
    chunk_bytes = sum(len(chunk.encode()) for chunk in chunks)
    raw_tokens = math.ceil(chunk_bytes / BYTES_PER_TOKEN)
    tokens = math.ceil(raw_tokens * SAFETY_MARGIN)
    return {
        "model": model,
        "price_usd_per_million_tokens": price,
        "price_table_date": PRICE_TABLE_DATE,
        "files": len(texts),
        "chunks": len(chunks),
        "chunk_target_size": DEFAULT_TARGET_CHUNK_SIZE,
        "chunk_overlap": DEFAULT_CHUNK_OVERLAP,
        "chunk_utf8_bytes": chunk_bytes,
        "raw_tokens": raw_tokens,
        "safety_margin": SAFETY_MARGIN,
        "estimated_tokens": tokens,
        "estimated_usd": round(tokens * price / 1_000_000, 5),
        "assumptions": [
            "text is extracted with the product's readers and chunked with the product's chunker; "
            "the overlap between chunks is embedded and therefore counted",
            f"no tokenizer is installed: tokens are an upper bound of UTF-8 bytes / {BYTES_PER_TOKEN}, "
            f"then multiplied by a safety margin of {SAFETY_MARGIN}",
            "every file is embedded from scratch (an upper bound: chunks that are already indexed cost nothing)",
            f"input price of {model} from prices.json (checked {PRICE_TABLE_DATE}); the file is not edited by the plan",
        ],
    }

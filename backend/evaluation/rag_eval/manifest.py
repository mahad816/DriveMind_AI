"""The run manifest: what exactly one result file measured.

Written into every result file by the ``run`` command. ``rescore`` and older files do not need it.
Nothing here calls a provider or reads a private file.
"""

import hashlib
import json
import subprocess
import sys
from collections.abc import Sequence
from typing import Any

import openai

from app.agents.tool_rag.claim_check import SYSTEM_PROMPT as CLAIM_CHECK_PROMPT
from app.agents.tool_rag.conversation import INTENT_SYSTEM_PROMPT
from app.agents.tool_rag.prompts import AGENT_SYSTEM_PROMPT
from app.agents.tool_rag.registry import INITIAL_TOOLS
from app.core.config import Settings
from app.embeddings.openai_service import resolve_embedding_dimension
from app.ingestion.chunking import DEFAULT_CHUNK_OVERLAP, DEFAULT_TARGET_CHUNK_SIZE
from app.ingestion.pipeline_version import EXTRACTION_PIPELINE_VERSION

from .corpus import CorpusFile
from .dataset import DATA
from .meter import METERING_LIMITS, PRICE_TABLE_DATE
from .target import ANSWER_FIELDS, BACKEND, application_defaults

SCHEMA_VERSION = 1


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def git_state() -> dict[str, Any]:
    """The audited commit and whether the working tree had uncommitted changes."""

    def git(*args: str) -> str:
        done = subprocess.run(
            ["git", *args], cwd=BACKEND, capture_output=True, text=True, check=True, timeout=30
        )
        return done.stdout.strip()

    try:
        return {"commit": git("rev-parse", "HEAD"), "tree_clean": not git("status", "--porcelain")}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "tree_clean": None}


def build_manifest(
    settings: Settings,
    *,
    files: Sequence[CorpusFile],
    datasets: Sequence[str],
    with_messy: bool,
    split: str,
    concurrency: int,
    repeat_index: int,
    repeat_count: int,
    cap_usd: float,
) -> dict[str, Any]:
    """Everything that can change an answer or its cost, for one pipeline run.

    ``spend`` is filled in by the caller once the run has finished.
    """
    defaults = application_defaults()
    values = {name: getattr(settings, name) for name in ANSWER_FIELDS}
    return {
        "schema_version": SCHEMA_VERSION,
        **git_state(),
        "settings": values,
        "deviations_from_default": {k: v for k, v in values.items() if v != defaults[k]},
        "embedding_dimension": resolve_embedding_dimension(settings.embedding_model),
        "prompts": {
            "agent_system": digest(AGENT_SYSTEM_PROMPT),
            "intent_gate": digest(INTENT_SYSTEM_PROMPT),
            "claim_check": digest(CLAIM_CHECK_PROMPT),
            "tools": {tool.name: digest(tool.description) for tool in INITIAL_TOOLS},
        },
        "indexing": {
            "extraction_pipeline_version": EXTRACTION_PIPELINE_VERSION,
            "chunk_target_size": DEFAULT_TARGET_CHUNK_SIZE,
            "chunk_overlap": DEFAULT_CHUNK_OVERLAP,
        },
        # version ids stay empty until tickets 04 to 07 introduce the frozen corpus and question set
        "corpus": {
            "version_id": "",
            "files": len(files),
            "with_messy": with_messy,
            "files_digest": digest(json.dumps(sorted((f.path, f.sha256) for f in files))),
        },
        "dataset": {
            "version_id": "",
            "split": split,
            "files": {name: digest((DATA / name).read_text()) for name in datasets},
        },
        "price_table_date": PRICE_TABLE_DATE,
        "metering": METERING_LIMITS,
        "concurrency": concurrency,
        "repeat_index": repeat_index,
        "repeat_count": repeat_count,
        "libraries": {"openai": openai.__version__, "python": sys.version.split()[0]},
        "cap_usd": cap_usd,
        "spend": None,
    }

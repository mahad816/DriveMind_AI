"""Explicit pre-smoke contract versions and deterministic source fingerprints."""

import hashlib
import json
from pathlib import Path
from typing import Any

VERSIONS = {
    "preparation": "v2-preparation-2.1",
    "domain": "v2-domain-2.2",
    "stage1": "v2-structure-1.1",
    "stage2": "v2-atomic-requests-2.1",
    "options": "v2-option-generation-1.1",
    "resolver": "v2-resolver-2.1",
    "probabilities": "typesafe-probabilities-2.0",
}


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def source_hashes() -> dict[str, str]:
    root = Path(__file__).parent
    files = [
        *sorted(root.glob("*.py")),
        *sorted((root / "providers").glob("*.py")),
        root.parent / "providers/probability_validation.py",
        root.parent / "providers/typesafe.py",
    ]
    return {
        str(p.relative_to(root.parent)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files
    }


def manifest() -> dict[str, Any]:
    """Static schema/config lock; per-input registries are hashed separately."""
    from pydantic import TypeAdapter, __version__ as pydantic_version
    from app.routing.v2 import domain as d
    from app.routing.v2.options import SemanticRequestOption
    from app.routing.v2.preparation import PreparedEnvelope
    from app.routing.v2.questions import stage1_questions, SPECIAL_OUTCOMES

    return {
        "versions": dict(VERSIONS),
        "source_hashes": source_hashes(),
        "stage1_question_hash": digest(stage1_questions()),
        "domain_schema_hash": digest(TypeAdapter(d.SemanticInterpretation).json_schema()),
        "preparation_schema_hash": digest(PreparedEnvelope.model_json_schema()),
        "atomic_option_schema_hash": digest(TypeAdapter(SemanticRequestOption).json_schema()),
        "special_outcomes_hash": digest(SPECIAL_OUTCOMES),
        "pydantic_version": pydantic_version,
    }


def verify_lock() -> bool:
    try:
        locked = json.loads(
            (Path(__file__).parent / "CONTRACT_LOCK.json").read_text(encoding="utf-8")
        )
        return bool(locked == manifest())
    except (OSError, ValueError):
        return False

"""Independent coverage lock; does not alter the frozen routing source manifest."""

import hashlib
import json
from pathlib import Path
from typing import Any

from app.routing.v2.contracts import digest, manifest as routing_manifest

VERSIONS = {
    "input": "coverage-input-1.0",
    "criteria": "coverage-criteria-1.0",
    "question": "coverage-choice-1.0",
    "provider": "coverage-typesafe-1.0",
}
ROOT = Path(__file__).parent


def routing_lock_identity() -> str:
    return hashlib.sha256((ROOT.parent / "CONTRACT_LOCK.json").read_bytes()).hexdigest()


def manifest() -> dict[str, Any]:
    from . import CoverageInput, CoverageResult
    from .criteria import questions

    return {
        "versions": VERSIONS,
        "routing_lock_identity": routing_lock_identity(),
        "routing_manifest_identity": digest(routing_manifest()),
        "source_hashes": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(ROOT.rglob("*.py"))
        },
        "shared_probability_source": hashlib.sha256(
            (ROOT.parents[1] / "providers/probability_validation.py").read_bytes()
        ).hexdigest(),
        "question_hash": digest(questions()),
        "input_schema_hash": digest(CoverageInput.model_json_schema()),
        "result_schema_hash": digest(CoverageResult.model_json_schema()),
    }


def contract_identity() -> str:
    return digest(manifest())


def verify_lock() -> bool:
    try:
        return bool(json.loads((ROOT / "CONTRACT_LOCK.json").read_text()) == manifest())
    except (OSError, ValueError):
        return False

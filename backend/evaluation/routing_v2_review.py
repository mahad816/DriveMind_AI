"""Offline composition and leakage audit; no provider predictions."""

from collections import Counter
from difflib import SequenceMatcher
import json

from evaluation.routing_v2_dataset import ROOT, load, normalized


def review() -> dict[str, object]:
    dataset, fixtures = load()
    prior = [
        c
        for name in ("routing_v1.json", "v2_smoke_15_v1.json")
        for c in json.loads((ROOT / name).read_text())["cases"]
    ]
    prior_norm = {normalized(c["question"]) for c in prior}
    near = []
    internal = []
    for i, case in enumerate(dataset.cases):
        for old in prior:
            score = SequenceMatcher(
                None, normalized(case.question), normalized(old["question"])
            ).ratio()
            if score >= 0.80:
                near.append({"case": case.id, "prior": old["id"], "similarity": score})
        for other in dataset.cases[:i]:
            score = SequenceMatcher(
                None, normalized(case.question), normalized(other.question)
            ).ratio()
            if score >= 0.88:
                internal.append({"case": case.id, "other": other.id, "similarity": score})
    return {
        "case_count": len(dataset.cases),
        "cohorts": dict(Counter(c.cohort for c in dataset.cases)),
        "cardinality": dict(Counter(c.expected_cardinality for c in dataset.cases)),
        "capabilities": dict(
            Counter(r.capability for c in dataset.cases for r in c.expected_requests)
        ),
        "operations": dict(
            Counter(
                f"{r.capability}:{r.operation}" for c in dataset.cases for r in c.expected_requests
            )
        ),
        "difficulty": dict(Counter(c.difficulty for c in dataset.cases)),
        "tags": dict(Counter(t for c in dataset.cases for t in c.tags)),
        "state_usage": dict(Counter(c.state_fixture for c in dataset.cases)),
        "snapshot_usage": dict(Counter(c.metadata_fixture for c in dataset.cases)),
        "readiness": dict(Counter(c.expected_readiness for c in dataset.cases)),
        "special": dict(Counter(c.expected_special for c in dataset.cases if c.expected_special)),
        "exact_prior_duplicates": [
            c.id for c in dataset.cases if normalized(c.question) in prior_norm
        ],
        "near_prior_threshold": 0.80,
        "near_prior_duplicates": near,
        "near_internal_threshold": 0.88,
        "near_internal_pairs": internal,
        "internal_review": "v2-025/v2-156 form a deliberate exact-filename/near-miss control; spelling changes readiness.",
        "state_count": len(fixtures.states),
        "snapshot_count": len(fixtures.snapshots),
    }


if __name__ == "__main__":
    print(json.dumps(review(), indent=2))

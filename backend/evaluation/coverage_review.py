"""Offline overlap and composition review for the frozen coverage pairs."""

from collections import Counter
from difflib import SequenceMatcher
import json
from evaluation.coverage_dataset import load, ROOT
from evaluation.routing_v2_dataset import normalized


def review() -> dict[str, object]:
    dataset, _ = load()
    held = [c for c in dataset.cases if c.split == "held_out"]
    dev = [c for c in dataset.cases if c.split == "development"]
    prior = json.loads((ROOT / "routing_v2.json").read_text())["cases"]
    old = {normalized(c["question"]) for c in prior}
    near_prior = [
        {"held_out": c.id, "prior": p["id"], "ratio": score}
        for c in held
        for p in prior
        if (
            score := SequenceMatcher(
                None, normalized(c.input.original_question), normalized(p["question"])
            ).ratio()
        )
        >= 0.82
    ]
    near_split = [
        {"held_out": c.id, "development": p.id, "ratio": score}
        for c in held
        for p in dev
        if (
            score := SequenceMatcher(
                None, normalized(c.input.original_question), normalized(p.input.original_question)
            ).ratio()
        )
        >= 0.82
    ]
    return {
        "pairs": 80,
        "splits": dict(Counter(c.split for c in dataset.cases)),
        "verdicts": dict(Counter(c.expected_verdict.value for c in dataset.cases)),
        "held_out_verdicts": dict(Counter(c.expected_verdict.value for c in held)),
        "families": dict(Counter(c.family for c in dataset.cases)),
        "held_out_families": dict(Counter(c.family for c in held)),
        "scenario_groups": len({c.scenario_group for c in dataset.cases}),
        "historical_unsafe_development_ids": [
            c.source_routing_case
            for c in dev
            if c.expected_verdict.value == "MISMATCH" and c.source_routing_case
        ],
        "exact_held_out_routing_reuse": [
            c.id for c in held if normalized(c.input.original_question) in old
        ],
        "near_threshold": 0.82,
        "near_held_out_routing": near_prior,
        "near_cross_split": near_split,
        "review_note": "Contrasting proposals for the same question are intentional; scenario groups never cross splits. String similarity cannot prove semantic independence.",
    }

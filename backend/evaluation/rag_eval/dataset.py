"""Case schema and validation: every gold claim must be checkable against the real corpus text."""

import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .corpus import CorpusFile, extract_text, public_files, synthetic_files
from .text import contains, norm, satisfies

DATA = Path(__file__).resolve().parents[1] / "datasets"
BEHAVIORS = {
    "answer",
    "not_found",
    "decline_or_not_found",
    "chitchat",
    "inventory",
    "correct_premise",
    "partial",  # part of the answer is in the files, part is not: state the first, never invent the second
}
SPLITS = {"dev", "test"}


def load_cases(name: str = "rag_v2_cases.json") -> dict[str, Any]:
    data: dict[str, Any] = json.loads((DATA / name).read_text())
    return data


def load_many(names: Sequence[str]) -> dict[str, Any]:
    """Several case files as one dataset; ``validate`` reports an id that appears twice."""
    merged: dict[str, Any] = {"cases": []}
    for name in names:
        merged["cases"] += load_cases(name)["cases"]
    return merged


def corpus_texts(files: list[CorpusFile]) -> dict[str, str]:
    return {f.path: extract_text(f) for f in files}


def validate(dataset: dict[str, Any], files: list[CorpusFile] | None = None) -> list[str]:
    """Return a list of problems (empty = valid). Never mutates anything."""
    files = files if files is not None else synthetic_files() + public_files()
    texts = corpus_texts(files)
    problems: list[str] = []
    ids = [c["id"] for c in dataset["cases"]]
    problems += [f"duplicate id {i}" for i, n in Counter(ids).items() if n > 1]
    for case in dataset["cases"]:
        cid = case["id"]
        if case.get("expected_behavior") not in BEHAVIORS:
            problems.append(f"{cid}: bad expected_behavior")
        if case.get("split") not in SPLITS:
            problems.append(f"{cid}: bad split")
        if case.get("citation_mode", "all") not in {"all", "any"}:
            problems.append(f"{cid}: bad citation_mode")
        for path in case["expected_files"]:
            if path not in texts:
                problems.append(f"{cid}: expected file {path} not in corpus")
        for anchor in case["evidence_anchors"]:
            body = texts.get(anchor["file"])
            if body is None or norm(anchor["quote"]) not in norm(body):
                problems.append(
                    f"{cid}: evidence quote not found verbatim in {anchor['file']}: {anchor['quote'][:50]!r}"
                )
        if case["expected_behavior"] in {"answer", "partial"}:
            if not case["expected_files"] or not case["evidence_anchors"]:
                problems.append(f"{cid}: answer case needs expected_files and evidence_anchors")
            joined = " ".join(texts.get(p, "") for p in case["expected_files"])
            if not case["computed"]:
                for group in case["must_include"]:
                    if not satisfies(joined, group):
                        problems.append(f"{cid}: must_include {group} absent from expected files")
        elif case["expected_behavior"] in {"not_found", "decline_or_not_found"}:
            if case["expected_files"]:
                problems.append(f"{cid}: not_found/decline cases must not list expected_files")
            if not case.get("reference_answer"):
                problems.append(f"{cid}: missing reference_answer")
        for claim in case["must_not_include"]:
            if case["expected_behavior"] in {"not_found", "decline_or_not_found"} and any(
                contains(t, claim)
                for p, t in texts.items()
                if p.startswith("synthetic/") and "smsgate" not in p
            ):
                problems.append(
                    f"{cid}: forbidden claim {claim!r} is actually present in the corpus"
                )
        if case.get("history"):
            if not all(
                t.get("role") in {"user", "assistant"} and t.get("text") for t in case["history"]
            ):
                problems.append(f"{cid}: malformed history")
        if case.get("derived_from") and case["derived_from"] not in ids:
            problems.append(f"{cid}: derived_from {case['derived_from']} unknown")
    return problems


def summary(dataset: dict[str, Any]) -> str:
    cases = dataset["cases"]
    by_cat = Counter(c["category"] for c in cases)
    by_split = Counter(c["split"] for c in cases)
    return f"{len(cases)} cases; split {dict(by_split)}; categories {dict(sorted(by_cat.items()))}"

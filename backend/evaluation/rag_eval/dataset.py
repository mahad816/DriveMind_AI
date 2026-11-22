"""Case schema and validation: every gold claim must be checkable against the real corpus text."""

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .corpus import CorpusFile, extract_text, public_files, synthetic_files
from .schema_v3 import (
    anchor_uniqueness_problems,
    clarify_problems,
    history_problems,
    is_v3,
    reference_problems,
    required_field_problems,
    sibling_problems,
    v3_field_problems,
)
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
    "clarify",  # the question is ambiguous: the correct reply is one short clarifying question
}
SPLITS = {"dev", "test", "held_out"}
HELD_OUT_SPLIT = "held_out"


def load_cases(name: str = "rag_v2_cases.json") -> dict[str, Any]:
    data: dict[str, Any] = json.loads((DATA / name).read_text())
    return data


def load_many(names: Sequence[str]) -> dict[str, Any]:
    """Several case files as one dataset; ``validate`` reports an id that appears twice.

    A file inside the repository may not hold held-out cases: the sealed pool lives outside the working
    tree (see ``pools.py``), so such a file is refused rather than loaded.
    """
    merged: dict[str, Any] = {"cases": []}
    for name in names:
        cases = load_cases(name)["cases"]
        if any(c.get("split") == HELD_OUT_SPLIT for c in cases):
            raise ValueError(
                f"{name} holds held-out cases; the sealed pool must live outside the repository"
            )
        merged["cases"] += cases
    return merged


def files_to_check(dataset: dict[str, Any], files: Sequence[CorpusFile]) -> list[CorpusFile]:
    """The files a dataset must be validated against, without reading the slow ones for nothing.

    ``validate`` extracts every file it is given, and the public PDFs take minutes. Synthetic and messy
    files are small, so they are always included (the "forbidden claim is really absent" check needs
    them); a public file is included only when some case points at it.
    """
    referenced = {p for c in dataset["cases"] for p in c.get("expected_files", [])} | {
        a["file"] for c in dataset["cases"] for a in c.get("evidence_anchors", [])
    }
    return [f for f in files if f.path.startswith(("synthetic/", "messy/")) or f.path in referenced]


def corpus_texts(files: list[CorpusFile]) -> dict[str, str]:
    return {f.path: extract_text(f) for f in files}


def validate(
    dataset: dict[str, Any],
    files: list[CorpusFile] | None = None,
    *,
    texts: Mapping[str, str] | None = None,
    injection_files: Mapping[str, str] | None = None,
) -> list[str]:
    """Return a list of problems (empty = valid). Never mutates anything.

    ``texts`` replaces what the product's readers extract, by corpus path. Use it to check cases against
    an independent ground truth (the generated fixtures' own content description) while a reader is
    still missing or being fixed; paths not given fall back to the readers.

    A case with a missing or wrongly typed required field is reported as such and checked no further; the
    validator never raises on a malformed case. Every other case is checked against the older rules, the history bound and (for ``clarify``) the clarify rules.
    A case that declares ``"schema": 3`` is also checked for provenance, tags, anchors that identify one file,
    sibling-value forbidden claims and a reference answer that passes its own checks (``schema_v3.py``). ``injection_files`` maps a corpus path to its
    embedded-instruction kind (the corpus manifest's ``injection:*`` tags) for the injection rule.
    """
    files = files if files is not None else synthetic_files() + public_files()
    texts = {
        **corpus_texts([f for f in files if not texts or f.path not in texts]),
        **(texts or {}),
    }
    problems: list[str] = []
    cases = dataset["cases"]
    ids = [c["id"] for c in cases if isinstance(c, Mapping) and isinstance(c.get("id"), str)]
    problems += [f"duplicate id {i}" for i, n in Counter(ids).items() if n > 1]
    for index, case in enumerate(cases):
        malformed = required_field_problems(case, index)
        problems += malformed
        if malformed:  # no other rule can read this case; report it and go on with the rest
            continue
        cid = case["id"]
        if case.get("expected_behavior") not in BEHAVIORS:
            problems.append(f"{cid}: bad expected_behavior")
        if case.get("split") not in SPLITS:
            problems.append(f"{cid}: bad split")
        if case.get("split") == HELD_OUT_SPLIT and not is_v3(case):
            problems.append(f"{cid}: held-out cases must declare schema 3")
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
                if p.startswith(("synthetic/", "messy/", "v1/", "google/")) and "smsgate" not in p
            ):
                problems.append(
                    f"{cid}: forbidden claim {claim!r} is actually present in the corpus"
                )
        problems += history_problems(cid, case.get("history") or [])
        if case["expected_behavior"] == "clarify":
            problems += clarify_problems(case)
        if is_v3(case):
            problems += v3_field_problems(case, injection_files)
            problems += anchor_uniqueness_problems(case, texts)
            problems += sibling_problems(case, texts)
            problems += reference_problems(case)
        if case.get("derived_from") and case["derived_from"] not in ids:
            problems.append(f"{cid}: derived_from {case['derived_from']} unknown")
    return problems


def summary(dataset: dict[str, Any]) -> str:
    cases = dataset["cases"]
    by_cat = Counter(c["category"] for c in cases)
    by_split = Counter(c["split"] for c in cases)
    return f"{len(cases)} cases; split {dict(by_split)}; categories {dict(sorted(by_cat.items()))}"

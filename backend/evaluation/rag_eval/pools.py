"""The question set as one thing with three named pools.

    development   the old "dev" split plus new development cases: may be tuned against
    regression    the old "test" split: already seen and used as vetoes, so no longer held out
    held_out      new sealed cases, kept in ONE file outside the working tree, reported only as aggregates

The case files on disk are never relabelled: ``split`` keeps its old values ("dev", "test") and the pool is
assigned at load time. The held-out file is found through an environment variable and is refused when it lies
inside the repository, so it cannot be committed by accident; the repository holds only its checksum, its
counts per gate group and the amendment log (``freeze.py``).

    uv run python -m evaluation.rag_eval.pools validate [--with-public]    # free; exits 1 on any problem
    uv run python -m evaluation.rag_eval.pools validate --held-out         # sealed pool; prints counts per rule only
    uv run python -m evaluation.rag_eval.pools review-sheet OUT.md [--size 30] [--seed 1]   # for the Owner; OUT outside the repo

``validate --held-out`` never prints a case id, a question, a quote or a value: every problem is reduced to the rule it
broke. The review sheet is the one file that holds held-out text, so it may only be written outside the repository.
"""

import json
import os
import random
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .corpus import (
    CORPUS_DIR,
    CorpusFile,
    messy_files,
    public_files,
    synthetic_files,
    v1_files,
    verify,
)
from .dataset import DATA, HELD_OUT_SPLIT, load_many, validate
from .schema_v3 import case_types, required_field_problems
from .text import norm

POOLS = {"dev": "development", "test": "regression", HELD_OUT_SPLIT: "held_out"}
SPLIT_CHOICES = ("dev", "test", "regression", "held_out", "all")
LEGACY_FILES = (
    "rag_v2_cases.json",
    "rag_v2_trap_cases.json",
    "rag_v2_messy_cases.json",
    "rag_v2_identifier_cases.json",
)
HELD_OUT_ENV = "DRIVEMIND_EVAL_HELDOUT_FILE"
FREEZE_MANIFEST = DATA / "m1_freeze.json"
REPO_ROOT = Path(__file__).resolve().parents[3]


def pool_of(case: Mapping[str, Any]) -> str:
    try:
        return POOLS[case["split"]]
    except KeyError as exc:
        raise ValueError(f"{case.get('id')}: split {case.get('split')!r} has no pool") from exc


def question_files() -> list[str]:
    """The committed case files of the question set: the four older files, then any new development file the
    freeze manifest lists (it is the one list of files; ticket 06 adds its file there)."""
    names = list(LEGACY_FILES)
    if FREEZE_MANIFEST.exists():
        recorded = json.loads(FREEZE_MANIFEST.read_text())["files"]
        names += [n for n in recorded if n not in names]
    return names


def load_question_set() -> dict[str, Any]:
    """Every committed case with its ``pool`` added (in memory only). Never includes the held-out pool."""
    dataset = load_many(question_files())
    for case in dataset["cases"]:
        case["pool"] = pool_of(case)
    return dataset


def held_out_path(environ: Mapping[str, str] | None = None) -> Path | None:
    """The sealed file named by the environment, or ``None`` when no variable is set.

    Raises when the variable points inside the repository or at a missing file: the pool is outside the
    working tree by rule, not by habit.
    """
    value = (environ if environ is not None else os.environ).get(HELD_OUT_ENV)
    if not value:
        return None
    path = Path(value).expanduser().resolve()
    if path == REPO_ROOT or REPO_ROOT in path.parents:
        raise ValueError(
            f"{HELD_OUT_ENV} points inside the repository; the held-out file must live outside it"
        )
    if not path.is_file():
        raise FileNotFoundError(f"{HELD_OUT_ENV} points at a missing file")
    return path


def load_held_out(path: Path | None = None) -> dict[str, Any]:
    """The sealed cases with ``pool`` added. Every case must be in the held-out split."""
    path = path or held_out_path()
    if path is None:
        raise FileNotFoundError(
            f"set {HELD_OUT_ENV} to the held-out case file (outside the repository)"
        )
    dataset: dict[str, Any] = json.loads(path.read_text())
    for case in dataset["cases"]:
        if case.get("split") != HELD_OUT_SPLIT:
            raise ValueError("the held-out file may only hold held_out cases")
        case["pool"] = pool_of(case)
    return dataset


def select(cases: Sequence[dict[str, Any]], split: str) -> list[dict[str, Any]]:
    """Cases for a ``--split`` value. ``all`` is development plus regression and NEVER the held-out pool; the
    sealed pool runs only when its name is given."""
    if split not in SPLIT_CHOICES:
        raise ValueError(f"unknown split {split!r}")
    if split == "all":
        return [c for c in cases if c["split"] != HELD_OUT_SPLIT]
    wanted = {"regression": "test"}.get(split, split)
    return [c for c in cases if c["split"] == wanted]


def frozen_corpus_files(*, with_public: bool = False) -> list[CorpusFile]:
    """The files case anchors are validated against: synthetic, messy, v1 and Google exports; public PDFs only
    on request (they take minutes to extract)."""
    files = synthetic_files() + messy_files() + v1_files()
    return files + public_files() if with_public else files


def injection_files() -> dict[str, str]:
    """Corpus path to injection kind, from the corpus manifest's ``injection:*`` tags."""
    manifest = json.loads((CORPUS_DIR / "v1_manifest.json").read_text())
    return {
        e["path"]: tag.split(":", 1)[1]
        for e in manifest["files"]
        for tag in e["tags"]
        if tag.startswith("injection:")
    }


def validate_question_set(
    dataset: dict[str, Any] | None = None, *, with_public: bool = False
) -> list[str]:
    """Validate a dataset (default: the committed question set) against the frozen corpus."""
    data = dataset if dataset is not None else load_question_set()
    files = frozen_corpus_files(with_public=with_public)
    verify(files)
    if not with_public:
        # A case that rests on a public PDF cannot be checked without it: say so instead of failing.
        have = {f.path for f in files}
        data = {
            **data,
            "cases": [
                c
                for i, c in enumerate(data["cases"])
                if required_field_problems(c, i)  # malformed: keep it, so that validate reports it
                or all(
                    f in have
                    for f in [*c["expected_files"], *(a["file"] for a in c["evidence_anchors"])]
                )
            ],
        }
    return validate(data, files, injection_files=injection_files())


# --- the sealed pool: validation and review that disclose nothing -------------------------------------

# A validator message names a case and quotes what is wrong. For the sealed pool each message is reduced to the
# first rule below it matches (an unmatched message becomes "other rule"), so a count survives and nothing else.
HELD_OUT_RULES = (
    ("required field", "a required case field is missing or invalid"),
    ("duplicate id", "duplicate case id"),
    ("missing reference_answer", "reference answer is missing"),
    ("must not list expected_files", "not-found case lists expected files"),
    ("reference answer", "reference answer fails the case's own checks"),
    ("evidence quote not found", "anchor quote is not verbatim in the corpus"),
    ("occurs in", "anchor quote identifies more than one file"),
    ("not in corpus", "expected file is not in the corpus"),
    ("actually present in the corpus", "forbidden claim is present in the corpus"),
    ("what the same field says elsewhere", "sibling value is not forbidden"),
    ("absent from expected files", "required fact is absent from the expected files"),
    ("history", "history is malformed or over the production bound"),
    ("clarify", "clarify case is malformed"),
    ("forbidden value", "clarify case is malformed"),
    ("provenance", "provenance is malformed"),
    ("multi-file", "multi-file case is malformed"),
    ("tag", "tags do not match the case"),
    ("critical", "critical case is malformed"),
    ("injection", "injection case is malformed"),
    ("held-out cases must declare schema 3", "held-out case is not schema 3"),
    ("needs expected_files and evidence_anchors", "answer case lacks files or anchors"),
    ("bad ", "unknown behaviour, split or citation mode"),
)
ID_COLLISION = "case id also used by a development or regression case"
SAME_QUESTION = "question identical to a development or regression question"


def problem_rule(message: str) -> str:
    """The rule a validator message is about, with no id, quote or value from the message."""
    for needle, label in HELD_OUT_RULES:
        if needle in message:
            return label
    return "other rule"


def validate_held_out(path: Path | None = None) -> dict[str, Any]:
    """Validate the sealed file against the frozen corpus and the committed question set.

    Returns ``{"cases": n, "problems": {rule: count}}``. Nothing in it comes from a case's text.
    A missing or wrongly typed required field is one rule in the count; a case that still escapes the validator
    is reported by exception class only, because an exception message may quote data.
    """
    dataset = load_held_out(path)
    files = frozen_corpus_files()
    verify(files)
    try:
        problems = [
            problem_rule(m) for m in validate(dataset, files, injection_files=injection_files())
        ]
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        problems = [f"a case is structurally malformed ({type(exc).__name__})"]
    committed = load_question_set()["cases"]
    known_ids = {c["id"] for c in committed}
    known_questions = {norm(c["question"]) for c in committed}
    cases = dataset["cases"]
    problems += [ID_COLLISION for c in cases if c.get("id") in known_ids]
    problems += [
        SAME_QUESTION for c in cases if norm(str(c.get("question", ""))) in known_questions
    ]
    return {"cases": len(cases), "problems": dict(sorted(Counter(problems).items()))}


def _shape(case: Mapping[str, Any]) -> str:
    """The one stratum a case is sampled under: its most specific question type, else its behaviour."""
    types = case_types(case)
    for name in ("ambiguous", "follow_up", "injection", "multi_file", "calculation", "identifier"):
        if name in types:
            return name
    if case.get("expected_behavior") in {"not_found", "partial", "correct_premise"}:
        return "non_answer"
    return "table" if "table" in types else "lookup"


def sample_for_review(
    cases: Sequence[Mapping[str, Any]], size: int = 30, seed: int = 1
) -> list[Mapping[str, Any]]:
    """A stratified sample: each shape gets a share of ``size`` in proportion to its size (largest remainders),
    at least one case per shape while places remain. Deterministic for a given seed."""
    if not cases:
        return []
    strata: dict[str, list[Mapping[str, Any]]] = {}
    for case in cases:
        strata.setdefault(_shape(case), []).append(case)
    size = min(size, len(cases))
    quotas = {name: min(len(members), 1) for name, members in strata.items()}
    if sum(quotas.values()) > size:  # fewer places than shapes: the biggest shapes first
        keep = sorted(strata, key=lambda n: (-len(strata[n]), n))[:size]
        quotas = {name: int(name in keep) for name in strata}
    shares = {name: len(members) * size / len(cases) for name, members in strata.items()}
    while sum(quotas.values()) < size:
        room = [n for n in strata if quotas[n] < len(strata[n])]
        pick = max(room, key=lambda n: (shares[n] - quotas[n], len(strata[n]), n))
        quotas[pick] += 1
    rng = random.Random(seed)
    chosen = [c for name in sorted(strata) for c in rng.sample(strata[name], quotas[name])]
    return sorted(chosen, key=lambda c: str(c["id"]))


def render_review_sheet(sample: Sequence[Mapping[str, Any]]) -> str:
    """Markdown for the Owner: question, reference answer, anchor quote and file per case, with two boxes."""
    lines = [
        "# Held-out review sheet (CONFIDENTIAL: do not commit, paste or share)",
        "",
        "For each case mark ONE box. 'correct' = the reference answer is right and the anchor quote supports it.",
        "'gold wrong' = the reference answer, the anchor or the case is wrong; say why in the note.",
        "",
    ]
    for number, case in enumerate(sample, start=1):
        lines += [f"## {number}. {case['id']} ({case['expected_behavior']})", ""]
        for turn in case.get("history") or []:
            lines.append(f"> {turn['role']}: {turn['text']}")
        lines += [
            f"**Question:** {case['question']}",
            "",
            f"**Reference answer:** {case['reference_answer']}",
            "",
        ]
        lines += [f'- Anchor ({a["file"]}): "{a["quote"]}"' for a in case["evidence_anchors"]]
        if case.get("judge_note"):
            lines += ["", f"Judge note: {case['judge_note']}"]
        lines += ["", "- [ ] correct    - [ ] gold wrong    Note:", ""]
    return "\n".join(lines)


def write_review_sheet(
    out: Path, size: int = 30, seed: int = 1, held_out: Path | None = None
) -> dict[str, int]:
    """Write the sampled sheet to ``out`` (refused inside the repository) and return counts per shape only."""
    target = out.expanduser().resolve()
    if target == REPO_ROOT or REPO_ROOT in target.parents:
        raise ValueError(
            "the review sheet holds held-out text and may not be written inside the repository"
        )
    cases = load_held_out(held_out)["cases"]
    sample = sample_for_review(cases, size=size, seed=seed)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_review_sheet(sample))
    target.chmod(0o600)
    return dict(sorted(Counter(_shape(c) for c in sample).items()))


def _option(args: list[str], name: str, default: int) -> int:
    return int(args[args.index(name) + 1]) if name in args else default


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "review-sheet" and len(args) >= 2:
        counts = write_review_sheet(
            Path(args[1]), size=_option(args, "--size", 30), seed=_option(args, "--seed", 1)
        )
        print(f"review sheet written: {sum(counts.values())} cases; per shape {counts}")
        return 0
    if not args or args[0] != "validate":
        print(__doc__)
        return 2
    if "--held-out" in args:
        report = validate_held_out()
        total = sum(report["problems"].values())
        print(f"held-out pool: {report['cases']} cases; {total} problem(s)")
        for rule, count in report["problems"].items():
            print(f"  {count} x {rule}")
        return 1 if total else 0
    with_public = "--with-public" in args
    dataset = load_question_set()
    problems = validate_question_set(dataset, with_public=with_public)
    print(
        f"{len(dataset['cases'])} cases in {len(question_files())} files; {len(problems)} problem(s)"
    )
    for line in problems:
        print(" ", line)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())

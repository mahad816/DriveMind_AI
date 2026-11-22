"""The question set as one thing with three named pools.

    development   the old "dev" split plus new development cases: may be tuned against
    regression    the old "test" split: already seen and used as vetoes, so no longer held out
    held_out      new sealed cases, kept in ONE file outside the working tree, reported only as aggregates

The case files on disk are never relabelled: ``split`` keeps its old values ("dev", "test") and the pool is
assigned at load time. The held-out file is found through an environment variable and is refused when it lies
inside the repository, so it cannot be committed by accident; the repository holds only its checksum, its
counts per gate group and the amendment log (``freeze.py``).

    uv run python -m evaluation.rag_eval.pools validate [--with-public]    # free; exits 1 on any problem
"""

import json
import os
import sys
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
                for c in data["cases"]
                if all(
                    f in have
                    for f in [*c["expected_files"], *(a["file"] for a in c["evidence_anchors"])]
                )
            ],
        }
    return validate(data, files, injection_files=injection_files())


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] != "validate":
        print(__doc__)
        return 2
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

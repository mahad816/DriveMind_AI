"""M1 ticket 07: the sealed held-out set is validated, reported and reviewed without disclosing a single case.

Free: no key, no network, no container. Everything about the sealed pool is shown on FABRICATED held-out files
that live in a temporary folder outside the repository and carry visible secret markers; the markers must never
reach stdout, stderr, an error message or a committed file. Tests that need the real sealed file skip without it
and assert on aggregates only, so a failure cannot print a case.
"""

import copy
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from evaluation.rag_eval import coverage, freeze, pools
from evaluation.rag_eval.corpus import extract_text
from evaluation.rag_eval.dataset import DATA, validate
from evaluation.rag_eval.schema_v3 import reference_problems
from evaluation.rag_eval.sealing import leaked_cases

SECRET_ID = "zq-secret-id"
SECRET_QUESTION = "SECRET-QUESTION which port does the vault use"
SECRET_QUOTE = "SECRET-QUOTE the vault listens on port 9999"
SECRET_CLAIM = "SECRET-CLAIM vault-code-4711"
SECRET_REFERENCE = "SECRET-REFERENCE the vault code is vault-code-4711 and nothing else"
MARKERS = ("zq-secret", "SECRET-", "vault-code-4711", "vault listens")


# --- a small fabricated corpus for the validator rules -----------------------------------------------

TEXTS = {
    "v1/fleet.md": (
        "| Vehicle | Depot | Payload |\n| --- | --- | --- |\n"
        "| MV-101 | Kessel Yard | 18 |\n| MV-102 | Harbourside | 12 |"
    ),
    "v1/notice.md": "The depot closes at 17:30 on Fridays.",
}


def held_case(**changes: Any) -> dict[str, Any]:
    case: dict[str, Any] = {
        "id": "zq-secret-01",
        "schema": 3,
        "category": "table_lookup",
        "question": "Which depot is MV-101 based at?",
        "language": "en",
        "expected_behavior": "answer",
        "expected_files": ["v1/fleet.md"],
        "citation_mode": "all",
        "must_include": [["Kessel Yard"]],
        "must_not_include": ["Harbourside"],
        "reference_answer": "MV-101 is based at Kessel Yard.",
        "evidence_anchors": [{"file": "v1/fleet.md", "quote": "| MV-101 | Kessel Yard | 18 |"}],
        "computed": False,
        "split": "held_out",
        "provenance": {"session": "m1-07-held-test", "date": "2026-11-22"},
        "tags": ["table"],
    }
    case.update(changes)
    return case


def problems(case: dict[str, Any]) -> list[str]:
    return validate({"cases": [case]}, [], texts=TEXTS)


def has(found: list[str], text: str) -> bool:
    return any(text in line for line in found)


# --- the M1-06 review finding: a reference answer must pass its own checks, held-out included --------


def test_a_consistent_held_out_case_passes_and_each_inconsistency_is_caught():
    assert problems(held_case()) == []
    lacks = held_case(reference_answer="MV-101 is somewhere.")
    forbids = held_case(reference_answer="MV-101 is at Kessel Yard, not Harbourside.")
    assert has(problems(lacks), "reference answer lacks a required fact")
    assert has(problems(forbids), "reference answer states a forbidden value")


def test_a_held_out_clarify_reference_must_be_a_real_clarifying_question():
    texts = {
        "v1/a.md": "The Kessel Yard gate opens at 05:00.",
        "v1/b.md": "The Harbourside gate opens at 06:00.",
    }
    clarify = held_case(
        id="zq-secret-02",
        category="ambiguous_question",
        question="When does the gate open?",
        expected_behavior="clarify",
        expected_files=[],
        must_include=[],
        must_not_include=["05:00", "06:00"],
        reference_answer="Which depot's gate do you mean, Kessel Yard or Harbourside?",
        evidence_anchors=[
            {"file": "v1/a.md", "quote": "The Kessel Yard gate opens at 05:00."},
            {"file": "v1/b.md", "quote": "The Harbourside gate opens at 06:00."},
        ],
        judge_note="Two depots, two times. A correct reply asks which depot.",
        tags=["ambiguous"],
    )
    assert validate({"cases": [clarify]}, [], texts=texts) == []
    vague = {**clarify, "reference_answer": "How can I help you?"}
    assert has(validate({"cases": [vague]}, [], texts=texts), "not accepted as a clarifying")


def test_the_reference_messages_name_the_case_and_the_rule_but_never_a_value():
    leaky = held_case(
        id=SECRET_ID,
        must_include=[[SECRET_CLAIM]],
        must_not_include=[SECRET_QUESTION],
        reference_answer=f"{SECRET_QUESTION}",
    )
    found = reference_problems(leaky)
    assert found, "the inconsistent reference must be reported"
    assert all(SECRET_CLAIM not in m and SECRET_QUESTION not in m for m in found)


def test_older_cases_are_not_held_to_the_reference_rule():
    legacy = {k: v for k, v in held_case().items() if k not in {"schema", "provenance", "tags"}}
    legacy.update(split="dev", reference_answer="Somewhere.")
    assert not has(problems(legacy), "reference answer")


def test_every_committed_v3_reference_answer_passes_its_own_checks():
    cases = [c for c in pools.load_question_set()["cases"] if c.get("schema") == 3]
    assert cases and [c["id"] for c in cases if reference_problems(c)] == []


# --- a fabricated sealed file, validated through the redacting path ----------------------------------


def template(case_id: str) -> dict[str, Any]:
    return next(c for c in pools.load_question_set()["cases"] if c["id"] == case_id)


def as_held_out(case_id: str, new_id: str, question: str, **changes: Any) -> dict[str, Any]:
    case = copy.deepcopy(template(case_id))
    case.update(id=new_id, split="held_out", question=question)
    case["provenance"] = {"session": "m1-07-held-test", "date": "2026-11-22"}
    case.update(changes)
    return case


def malformed_variants() -> dict[str, dict[str, Any]]:
    """One broken copy of a real, valid case per rule. Each carries a secret marker where the validator would
    quote something."""
    base = "rb01"
    anchor = dict(template(base)["evidence_anchors"][0])
    return {
        "anchor": as_held_out(
            base,
            "zq-secret-anchor",
            SECRET_QUESTION + " 1",
            evidence_anchors=[{**anchor, "quote": SECRET_QUOTE}],
        ),
        "reference_fact": as_held_out(
            base, "zq-secret-ref1", SECRET_QUESTION + " 2", reference_answer=SECRET_REFERENCE
        ),
        "reference_forbidden": as_held_out(
            base,
            "zq-secret-ref2",
            SECRET_QUESTION + " 3",
            must_not_include=[*template(base)["must_not_include"], SECRET_CLAIM],
            reference_answer=template(base)["reference_answer"] + " " + SECRET_CLAIM,
        ),
        "history": as_held_out(
            base,
            "zq-secret-hist",
            SECRET_QUESTION + " 4",
            tags=[*template(base).get("tags", []), "follow_up"],
            history=[
                {"role": "user" if i % 2 == 0 else "assistant", "text": SECRET_QUOTE}
                for i in range(7)
            ],
        ),
        "provenance": as_held_out(
            base,
            "zq-secret-prov",
            SECRET_QUESTION + " 5",
            provenance={"session": SECRET_QUOTE, "date": "x"},
        ),
        "critical": as_held_out(base, "zq-secret-crit", SECRET_QUESTION + " 6", critical=True),
        "id_collision": as_held_out(base, "rb01", SECRET_QUESTION + " 7"),
        "same_question": as_held_out(base, "zq-secret-same", template(base)["question"]),
    }


EXPECTED_RULES = {
    "anchor quote is not verbatim in the corpus",
    "reference answer fails the case's own checks",
    "history is malformed or over the production bound",
    "provenance is malformed",
    "critical case is malformed",
    pools.ID_COLLISION,
    pools.SAME_QUESTION,
}


@pytest.fixture
def sealed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Write a fabricated sealed file outside the repository and point the environment at it."""

    def write(cases: list[dict[str, Any]], name: str = "sealed.json") -> Path:
        outside = tmp_path / "outside"
        outside.mkdir(exist_ok=True)
        path = outside / name
        path.write_text(json.dumps({"cases": cases}))
        monkeypatch.setenv(pools.HELD_OUT_ENV, str(path))
        return path

    return write


@pytest.fixture(scope="module")
def bulk_report() -> dict[str, Any]:
    """The redacted report for a file with one broken case per rule and two valid ones (validated once)."""
    import os
    import tempfile

    cases = [
        as_held_out("rb01", "zq-secret-ok1", SECRET_QUESTION + " ok1"),
        as_held_out("am03", "zq-secret-ok2", SECRET_QUESTION + " ok2"),
        *malformed_variants().values(),
    ]
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "sealed.json"
        path.write_text(json.dumps({"cases": cases}))
        previous = os.environ.get(pools.HELD_OUT_ENV)
        os.environ[pools.HELD_OUT_ENV] = str(path)
        try:
            return pools.validate_held_out()
        finally:
            if previous is None:
                del os.environ[pools.HELD_OUT_ENV]
            else:
                os.environ[pools.HELD_OUT_ENV] = previous


def test_malformed_held_out_cases_fail_each_rule_and_valid_ones_pass(bulk_report):
    assert bulk_report["cases"] == 10
    assert set(bulk_report["problems"]) == EXPECTED_RULES
    assert bulk_report["problems"]["reference answer fails the case's own checks"] == 2
    # two valid cases in the file raised nothing of their own: every problem belongs to a broken variant
    assert sum(bulk_report["problems"].values()) >= len(EXPECTED_RULES)


def test_the_raw_validator_quotes_the_secret_but_the_redacted_report_cannot(bulk_report):
    raw = validate(
        {"cases": [malformed_variants()["anchor"]]},
        pools.frozen_corpus_files(),
        injection_files=pools.injection_files(),
    )
    assert has(raw, "SECRET-QUOTE") or has(raw, "zq-secret-anchor"), (
        "the raw message quotes the case"
    )
    assert not any(marker in json.dumps(bulk_report) for marker in MARKERS)


def test_a_valid_held_out_file_reports_no_problem(sealed):
    sealed([as_held_out("rb01", "zq-secret-ok1", SECRET_QUESTION + " ok1")])
    assert pools.validate_held_out() == {"cases": 1, "problems": {}}


def test_a_case_missing_a_required_field_is_counted_under_its_own_rule(sealed):
    broken = as_held_out("rb01", "zq-secret-broken", SECRET_QUESTION)
    del broken["must_include"]
    sealed([broken])
    report = pools.validate_held_out()
    assert report["problems"] == {"a required case field is missing or invalid": 1}
    assert not any(marker in json.dumps(report) for marker in MARKERS)


def test_required_field_messages_map_to_one_rule_whatever_the_field():
    for name in ("provenance", "tags", "reference_answer", "expected_files", "id", "history"):
        message = f"{SECRET_ID}: required field {name} is missing or invalid"
        assert pools.problem_rule(message) == "a required case field is missing or invalid"


def test_problem_rule_never_returns_text_from_the_message():
    message = f"{SECRET_ID}: evidence quote not found verbatim in v1/x: {SECRET_QUOTE!r}"
    assert pools.problem_rule(message) == "anchor quote is not verbatim in the corpus"
    assert pools.problem_rule(f"{SECRET_ID}: something unforeseen {SECRET_QUOTE}") == "other rule"


# --- stdout, stderr and error messages ----------------------------------------------------------------


def test_the_validate_command_prints_counts_per_rule_and_no_held_out_text(sealed, capsys):
    sealed([as_held_out("rb01", "zq-secret-ok1", SECRET_QUESTION), *malformed_variants().values()])
    assert pools.main(["validate", "--held-out"]) == 1
    captured = capsys.readouterr()
    assert "held-out pool: 9 cases" in captured.out and "problem(s)" in captured.out
    assert not any(m in captured.out + captured.err for m in MARKERS)
    assert "rb01" not in captured.out + captured.err  # a colliding id is a held-out id too


def test_coverage_and_freeze_commands_print_aggregates_only(sealed, capsys):
    sealed([as_held_out("rb01", f"zq-secret-{i:02d}", f"{SECRET_QUESTION} {i}") for i in range(12)])
    coverage.main(["--require-held-out"])
    freeze.main(["check"])
    out = capsys.readouterr()
    assert not any(m in out.out + out.err for m in MARKERS)
    assert "held-out counts come from the sealed file" in out.out


def test_loader_errors_never_quote_a_case(sealed):
    sealed([{**as_held_out("rb01", SECRET_ID, SECRET_QUESTION), "split": "dev"}])
    with pytest.raises(ValueError) as caught:
        pools.load_held_out(require_review=False)
    assert not any(m in str(caught.value) for m in MARKERS)
    with pytest.raises(ValueError) as inside:
        pools.held_out_path({pools.HELD_OUT_ENV: str(DATA / "rag_v2_cases.json")})
    assert "rag_v2" not in str(inside.value)


# --- the review sheet ----------------------------------------------------------------------------------


def fabricated_pool(size: int = 40) -> list[dict[str, Any]]:
    """`size` valid held-out cases across several shapes (copies of real, valid committed cases)."""
    ids = ["rb01", "am03", "fxT", "fm03", "ic01", "nm01", "ix01", "t25b", "mg01", "sk01"]
    return [
        as_held_out(ids[i % len(ids)], f"zq-secret-{i:03d}", f"{SECRET_QUESTION} {i}")
        for i in range(size)
    ]


def test_the_review_sheet_samples_every_shape_and_is_deterministic(sealed, tmp_path):
    sealed(fabricated_pool())
    first = pools.write_review_sheet(tmp_path / "review" / "a.md", size=12, seed=3)
    second = pools.write_review_sheet(tmp_path / "review" / "b.md", size=12, seed=3)
    assert first == second and sum(first.values()) == 12
    assert (tmp_path / "review" / "a.md").read_text() == (tmp_path / "review" / "b.md").read_text()
    shapes = {pools._shape(c) for c in fabricated_pool()}
    assert set(first) == shapes, "every shape present in the pool is in the sample"
    text = (tmp_path / "review" / "a.md").read_text()
    assert SECRET_QUESTION in text and "[ ] correct" in text and "gold wrong" in text
    assert (tmp_path / "review" / "a.md").stat().st_mode & 0o077 == 0, "the sheet is owner-only"


def test_a_sample_larger_than_the_pool_is_the_pool_and_a_smaller_one_keeps_the_biggest_shapes():
    pool = fabricated_pool(10)
    assert len(pools.sample_for_review(pool, size=50)) == 10
    few = pools.sample_for_review(pool, size=3)
    assert len(few) == 3 and len({pools._shape(c) for c in few}) == 3


def test_a_rare_shape_still_gets_a_place_in_a_skewed_pool():
    """38 plain lookups, one ambiguous and one injection case: proportional shares alone would give the rare
    shapes nothing in a sample of 10, but a review that skips a whole shape cannot find its gold errors."""
    pool = [as_held_out("rb01", f"zq-secret-{i:03d}", f"{SECRET_QUESTION} {i}") for i in range(38)]
    pool += [
        as_held_out("am03", "zq-secret-amb", SECRET_QUESTION + " a"),
        as_held_out("ix01", "zq-secret-inj", SECRET_QUESTION + " b"),
    ]
    shapes = Counter(pools._shape(c) for c in pools.sample_for_review(pool, size=10, seed=5))
    assert shapes["ambiguous"] == 1 and shapes["injection"] == 1 and sum(shapes.values()) == 10


def test_the_review_sheet_may_not_be_written_inside_the_repository(sealed):
    sealed(fabricated_pool(12))
    with pytest.raises(ValueError, match="inside the repository") as caught:
        pools.write_review_sheet(pools.REPO_ROOT / "docs" / "review.md")
    assert not any(m in str(caught.value) for m in MARKERS)
    assert not (pools.REPO_ROOT / "docs" / "review.md").exists()


def test_the_review_command_prints_counts_and_no_case_text(sealed, tmp_path, capsys):
    sealed(fabricated_pool())
    assert pools.main(["review-sheet", str(tmp_path / "sheet.md"), "--size", "10"]) == 0
    out = capsys.readouterr()
    assert "review sheet written: 10 cases" in out.out
    assert not any(m in out.out + out.err for m in MARKERS)


# --- the committed-file scan counts a leak without printing it --------------------------------------


def test_the_content_scan_finds_an_id_a_question_and_a_long_reference_but_not_prose():
    cases = [
        {"id": "zq-secret-1", "question": "Which port?", "reference_answer": "7420."},
        {"id": "zq-secret-2", "question": SECRET_QUESTION, "reference_answer": "x"},
        {"id": "zq-secret-3", "question": "q", "reference_answer": SECRET_REFERENCE},
        {"id": "zq-secret-4", "question": "Is it open?", "reference_answer": "Short answer."},
        {
            "id": "zq-secret-5",
            "question": "Who is on call now?",
            "reference_answer": "Mid length one.",
        },
    ]
    assert leaked_cases("see zq-secret-1 for details", cases) == 1
    assert leaked_cases(f"the question was: {SECRET_QUESTION.lower()}!", cases) == 1
    assert leaked_cases("who is on call now", cases) == 1, "a short but whole question is found"
    assert leaked_cases(f"> {SECRET_REFERENCE}", cases) == 1
    # words that are only ordinary prose: a very short question, short references
    assert (
        leaked_cases("Is it open? It is 7420. Which port? Short answer. Mid length one.", cases)
        == 0
    )
    # a question or reference that is already public is no secret; an id always is
    assert leaked_cases(f"> {SECRET_REFERENCE}", cases, public=[SECRET_REFERENCE]) == 0
    assert leaked_cases("who is on call now", cases, public=["Who is on call now?"]) == 0
    assert leaked_cases("zq-secret-1", cases, public=["zq-secret-1"]) == 1


# --- coverage cannot pass the full milestone without the held-out minimums ----------------------------


def minimum_counts(held_out: dict[str, int]) -> dict[str, Counter[str]]:
    counts: dict[str, Counter[str]] = {name: Counter() for name in coverage.POOL_COLUMNS}
    for gate in coverage.GATES:
        counts["development"][gate.key] = gate.minimum
    counts["held_out"].update(held_out)
    return counts


def test_the_whole_set_can_pass_while_the_held_out_pool_is_hollow_so_the_flag_matters():
    hollow = minimum_counts({"total": 100})  # 100 held-out cases of one shape: nothing else
    docs = ["v1/a.docx", "v1/b.xlsx", "v1/c.pdf"]
    assert coverage.evaluate(hollow, docs) == []
    enforced = coverage.evaluate(hollow, docs, require_held_out=True)
    assert any("critical" in line.lower() and "held-out" in line for line in enforced)
    assert len(enforced) >= len([g for g in coverage.GATES if g.held_out_minimum]) - 1


def test_the_coverage_command_says_when_it_did_not_enforce_the_held_out_minimums(
    monkeypatch, capsys
):
    monkeypatch.delenv(pools.HELD_OUT_ENV, raising=False)
    coverage.main([])
    assert "held-out minimums NOT enforced" in capsys.readouterr().out
    coverage.main(["--require-held-out"])
    assert "NOT enforced" not in capsys.readouterr().out


def test_the_recorded_held_out_counts_meet_every_full_milestone_requirement(monkeypatch, capsys):
    """Runs on every machine, sealed file or not: the freeze manifest's recorded counts must satisfy the whole-set
    AND the held-out minimums, so a sealed file that is too small cannot be registered unnoticed."""
    monkeypatch.delenv(pools.HELD_OUT_ENV, raising=False)
    assert coverage.main(["--require-held-out"]) == 0, capsys.readouterr().out


def test_the_manifest_records_a_sealed_file_with_counts_and_no_case_id():
    manifest = json.loads((DATA / "m1_freeze.json").read_text())["held_out"]
    assert len(manifest["sha256"]) == 64 and len(manifest["frozen_sha256"]) == 64
    assert manifest["cases"] >= 100 and manifest["gate_group_counts"]["total"] == manifest["cases"]
    log = [
        e for e in json.loads((DATA / "m1_amendments.json").read_text()) if e["file"] == "held_out"
    ]
    assert log and all(e["case_ids"] == [] for e in log)


# --- the real sealed file (skipped where it is absent); every assertion is on a count ---------------------


@pytest.fixture(scope="module")
def real_sealed() -> Path:
    path = pools.held_out_path()
    if path is None:
        pytest.skip(f"{pools.HELD_OUT_ENV} is not set: no sealed file on this machine")
    return path


def test_the_real_sealed_file_lives_outside_the_repository_and_validates_clean(real_sealed):
    assert pools.REPO_ROOT not in real_sealed.parents
    report = pools.validate_held_out(real_sealed)
    assert report["cases"] >= 100
    assert report["problems"] == {}, (
        f"{sum(report['problems'].values())} problem(s): {report['problems']}"
    )


def test_the_real_sealed_file_meets_every_held_out_minimum_and_matches_the_manifest(real_sealed):
    cases = pools.load_held_out(real_sealed, require_review=False)["cases"]
    counts = coverage.count_cases(cases)
    shortfalls = coverage.evaluate(
        {**coverage.pool_counts([]), "held_out": counts},
        coverage.injection_documents(cases),
        require_held_out=True,
    )
    held_only = [s for s in shortfalls if "held-out" in s]
    assert held_only == [], f"{len(held_only)} held-out minimum(s) unmet"
    recorded = json.loads((DATA / "m1_freeze.json").read_text())["held_out"]
    assert dict(sorted(counts.items())) == recorded["gate_group_counts"]
    assert len(cases) == recorded["cases"]


def test_the_real_sealed_cases_are_written_by_one_declared_session_with_unique_ids(real_sealed):
    cases = pools.load_held_out(real_sealed, require_review=False)["cases"]
    assert len({c["id"] for c in cases}) == len(cases)
    assert {c["provenance"]["session"] for c in cases} == {"m1-07-held-a"}
    assert all(c["split"] == "held_out" and c.get("schema") == 3 for c in cases)


def test_no_tracked_file_or_the_committed_baseline_discloses_a_real_held_out_case(real_sealed):
    cases = pools.load_held_out(real_sealed, require_review=False)["cases"]
    root = pools.REPO_ROOT
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.split()
    skip = {"backend/evaluation/datasets/m1_amendments.json"}  # names moved cases by design
    committed = pools.load_question_set()["cases"]
    public = [extract_text(f) for f in pools.frozen_corpus_files()]
    public += [c["reference_answer"] for c in committed] + [c["question"] for c in committed]
    leaking = [
        name
        for name in tracked
        if name not in skip
        and (root / name).is_file()
        and (root / name).suffix in {".md", ".json", ".txt", ".py", ".yml", ".yaml", ".toml"}
        and leaked_cases((root / name).read_text(errors="ignore"), cases, public)
    ]
    assert len(leaking) == 0, f"{len(leaking)} tracked file(s) disclose a held-out case"

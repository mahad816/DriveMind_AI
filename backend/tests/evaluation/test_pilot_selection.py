"""The end-to-end answer pilot (docs/tickets/hybrid-retrieval-comparison/02-answer-quality-pilot.md).

Free: it only checks that every named case is a committed, English, development-pool case, so a pilot can never
include a regression, held-out or Roman Urdu question. The cases are read, never changed.
"""

from app.retrieval.filename_targets import extract_filename_targets
from evaluation.rag_eval.dataset import load_many
from evaluation.rag_eval.pools import pool_of, question_files

REPRESENTATIVE = {
    "single_fact": ["by02", "gn01"],
    "multi_fact_one_file": ["mf01", "mf03"],
    "multi_document": ["fm04", "fm05"],
    "table_lookup": ["cb02", "dh02"],
    "insufficient_evidence": ["an05", "cc07", "nep03"],
    "history_follow_up": ["by03", "cc06"],
}
DIAGNOSTIC = {
    "missed_by_a_recovered_by_c2_cap3": ["ac01", "id01", "id11"],
    "multi_document_partial_evidence": ["mx07"],
    "unretrieved_by_both": ["px03"],
}
# Controls: they say nothing about the cap3 effect. by03, cc06 run A in both arms; gn01 runs C2 without the cap.
#  by03, cc06: history-dependent (C2 applies only to a turn with no earlier history).
#  gn01: production reads its question as naming a file, so the soft per-file cap does not apply to it.
CONTROLS = {"history": ["by03", "cc06"], "named_file": ["gn01"]}
PILOT = [i for group in (*REPRESENTATIVE.values(), *DIAGNOSTIC.values()) for i in group]


def test_every_pilot_case_is_an_english_development_case() -> None:
    cases = {c["id"]: c for c in load_many(question_files())["cases"]}
    assert len(PILOT) == len(set(PILOT)) == 18
    for case_id in PILOT:
        case = cases[case_id]
        assert pool_of(case) == "development", case_id
        assert case["language"] == "en", case_id


def test_the_history_cases_carry_history_and_the_refusals_are_refusals() -> None:
    cases = {c["id"]: c for c in load_many(question_files())["cases"]}
    assert all(cases[i].get("history") for i in REPRESENTATIVE["history_follow_up"])
    behaviours = {cases[i]["expected_behavior"] for i in REPRESENTATIVE["insufficient_evidence"]}
    assert behaviours == {"not_found", "partial", "correct_premise"}


def test_the_controls_are_in_the_pilot_and_really_are_controls() -> None:
    cases = {c["id"]: c for c in load_many(question_files())["cases"]}
    assert set(CONTROLS["history"]) | set(CONTROLS["named_file"]) <= set(PILOT)
    assert all(cases[i].get("history") for i in CONTROLS["history"])
    # gn01 names no file, but production's filename-target heuristic reads its question as naming one
    # (it returns "day"), which switches the soft per-file cap off for it: a cap control either way.
    assert extract_filename_targets(cases["gn01"]["question"])
    assert PILOT.count("id11") == 1 and "id11" in DIAGNOSTIC["missed_by_a_recovered_by_c2_cap3"]

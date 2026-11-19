"""The v2 golden set must be checkable against the real corpus, and the validator must actually catch errors."""

import copy

import pytest

from evaluation.rag_eval.corpus import public_files, synthetic_files
from evaluation.rag_eval.dataset import BEHAVIORS, load_cases, validate

DATASET = load_cases()
SYNTHETIC = synthetic_files()


def synthetic_only(dataset):
    data = copy.deepcopy(dataset)
    data["cases"] = [
        c for c in data["cases"] if all(f.startswith("synthetic/") for f in c["expected_files"])
    ]
    return data


def one(dataset, case_id):
    data = copy.deepcopy(dataset)
    data["cases"] = [c for c in data["cases"] if c["id"] == case_id]
    return data


def test_every_synthetic_case_is_grounded_in_the_corpus_text():
    assert validate(synthetic_only(DATASET), SYNTHETIC) == []


def test_public_cases_validate_when_the_public_documents_are_downloaded():
    try:
        files = SYNTHETIC + public_files()
    except FileNotFoundError:
        pytest.skip("public documents not downloaded (python -m evaluation.rag_eval.fetch_public)")
    assert validate(DATASET, files) == []


def test_dataset_shape():
    cases = DATASET["cases"]
    assert len({c["id"] for c in cases}) == len(cases) >= 90
    assert {c["expected_behavior"] for c in cases} <= BEHAVIORS
    held_out = [c for c in cases if c["split"] == "test"]
    assert 28 <= len(held_out) <= 36  # roughly a third is held out
    assert {c["category"] for c in held_out} == {
        c["category"] for c in cases
    }  # every category is represented
    unanswerable = [c for c in cases if c["expected_behavior"] in {"not_found", "correct_premise"}]
    assert len(unanswerable) >= 15  # refusal behaviour is measured, not an afterthought


def test_perturbed_cases_point_at_a_real_source_case():
    ids = {c["id"] for c in DATASET["cases"]}
    perturbed = [c for c in DATASET["cases"] if c["category"] == "perturbed_unanswerable"]
    assert perturbed and all(c["derived_from"] in ids and c["perturbation"] for c in perturbed)


# --- the validator must reject broken cases (otherwise a green result means nothing) ---------


def test_rejects_a_fabricated_evidence_quote():
    data = one(DATASET, "sf01")
    data["cases"][0]["evidence_anchors"][0]["quote"] = (
        "Annual leave is 30 working days per calendar year."
    )
    assert any("evidence quote not found" in p for p in validate(data, SYNTHETIC))


def test_rejects_an_expected_answer_the_files_do_not_contain():
    data = one(DATASET, "sf01")
    data["cases"][0]["must_include"] = [["31"]]
    assert any("must_include" in p for p in validate(data, SYNTHETIC))


def test_rejects_an_unknown_expected_file_and_a_bad_split():
    data = one(DATASET, "sf01")
    data["cases"][0]["expected_files"] = ["synthetic/nope.txt"]
    data["cases"][0]["split"] = "maybe"
    problems = validate(data, SYNTHETIC)
    assert any("not in corpus" in p for p in problems) and any("bad split" in p for p in problems)


def test_rejects_a_not_found_case_whose_forbidden_claim_is_really_in_the_corpus():
    data = one(DATASET, "nf01")
    data["cases"][0]["must_not_include"] = ["22 working days"]
    assert any("actually present" in p for p in validate(data, SYNTHETIC))


def test_rejects_duplicate_ids():
    data = one(DATASET, "sf01")
    data["cases"].append(copy.deepcopy(data["cases"][0]))
    assert any("duplicate id" in p for p in validate(data, SYNTHETIC))

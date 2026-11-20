"""The messy documents join an evaluation run only when asked for."""

from evaluation.rag_eval.cli import corpus_files
from evaluation.rag_eval.dataset import load_many, validate


def test_messy_documents_are_not_in_the_default_corpus_and_join_on_request():
    default = corpus_files(with_messy=False)
    assert not [f for f in default if f.kind == "messy"]
    with_messy = corpus_files(with_messy=True)
    assert [f.path for f in with_messy[: len(default)]] == [f.path for f in default]
    assert sorted(f.name for f in with_messy if f.kind == "messy") == [
        "annual_report_2025.pdf",
        "board_update_q3.pptx",
        "customer_rollout_plan.docx",
        "invoice_0457.pdf",
        "sales_2026.xlsx",
    ]


def test_the_messy_question_set_is_only_valid_with_the_messy_documents():
    """Checked on small subsets: validating reads every document, and the public PDFs take minutes."""
    dataset = load_many(["rag_v2_messy_cases.json"])
    messy = [f for f in corpus_files(with_messy=True) if f.kind == "messy"]
    synthetic = [f for f in corpus_files(with_messy=False) if f.kind == "synthetic"]
    assert validate(dataset, messy) == []
    assert validate(dataset, synthetic)  # points at files that are not there

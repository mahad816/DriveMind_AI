"""Passage-level retrieval metrics (M1-08-C), checked on fabricated hits with hand-computed answers.

Free: no database, no provider. Anchors are built directly as ``AnchorMap`` values (what ``map_anchor``
returns), so these tests pin the metric rules and not the mapper, which has its own tests.
"""

import pytest

from evaluation.rag_eval.anchors import AnchorMap
from evaluation.rag_eval.passage_metrics import (
    HeldOutRefused,
    measure_passages,
    passage_report,
    passage_row,
    refusal_row,
    summarise_pool,
    summarise_refusal_scores,
)
from evaluation.rag_eval.retrieval_probe import Hit

NAMES = {"v1/a.txt": "a.txt", "v1/b.pdf": "b.pdf", "v1/c.docx": "c.docx"}


def h(chunk: str, name: str = "a.txt", score: float | None = 0.5) -> Hit:
    return Hit(name, score, chunk_id=chunk)


def whole(file: str, *ids: str) -> AnchorMap:
    return AnchorMap(file, "q", "whole", tuple(ids))


def split(file: str, first: str, second: str) -> AnchorMap:
    return AnchorMap(file, "q", "split", (first, second))


def absent(file: str) -> AnchorMap:
    return AnchorMap(file, "q", "absent", ())


def measure(hits, anchors, files=("v1/a.txt",), k=None):
    return measure_passages(hits, anchors, files, NAMES, top_k=k)


# ---- rank, recall, MRR -----------------------------------------------------------------------------


def test_evidence_ranked_first():
    m = measure([h("c1"), h("c2"), h("c3")], [whole("v1/a.txt", "c1")])
    assert m["status"] == "measured"
    assert (
        m["any_found"] and m["all_found"] and m["first_rank"] == 1 and m["reciprocal_rank"] == 1.0
    )


def test_evidence_ranked_later():
    m = measure([h("x"), h("y"), h("c1")], [whole("v1/a.txt", "c1")])
    assert m["first_rank"] == 3 and m["reciprocal_rank"] == pytest.approx(1 / 3)


def test_evidence_absent_from_results_is_a_retrieval_miss_not_a_mapping_failure():
    m = measure([h("x"), h("y")], [whole("v1/a.txt", "c1")])
    assert m["status"] == "measured"
    assert not m["any_found"] and m["first_rank"] is None and m["reciprocal_rank"] == 0.0
    assert m["no_evidence"] is True


def test_several_anchors_any_all_and_coverage():
    anchors = [whole("v1/a.txt", "c1"), whole("v1/a.txt", "c2"), whole("v1/a.txt", "c3")]
    m = measure([h("x"), h("c2"), h("c1")], anchors)
    assert m["anchors"] == 3 and m["anchors_found"] == 2
    assert m["any_found"] and not m["all_found"]
    assert m["anchor_coverage"] == pytest.approx(2 / 3)
    assert m["first_rank"] == 2  # the first chunk that holds any anchor


def test_split_anchor_is_satisfied_by_either_half_and_ranked_by_the_better_one():
    anchor = split("v1/a.txt", "c1", "c2")
    assert measure([h("x"), h("c2")], [anchor])["first_rank"] == 2
    assert measure([h("c1"), h("c2")], [anchor])["first_rank"] == 1
    assert measure([h("x")], [anchor])["any_found"] is False


def test_whole_anchor_in_two_overlapping_chunks_is_satisfied_by_either():
    m = measure([h("x"), h("c9")], [whole("v1/a.txt", "c1", "c9")])
    assert m["any_found"] and m["first_rank"] == 2


def test_duplicate_hits_do_not_shift_ranks_or_inflate_counts():
    m = measure([h("x"), h("x"), h("x"), h("c1")], [whole("v1/a.txt", "c1")])
    assert m["first_rank"] == 2 and m["chunks"] == 2 and m["duplicates_dropped"] == 2


def test_empty_results():
    m = measure([], [whole("v1/a.txt", "c1")])
    assert m["status"] == "measured" and m["chunks"] == 0 and m["distinct_files"] == 0
    assert m["no_evidence"] and m["reciprocal_rank"] == 0.0 and m["file_recall"] == 0.0


# ---- top-K ----------------------------------------------------------------------------------------


def test_top_k_cuts_the_results_before_measuring():
    hits = [h("x"), h("y"), h("c1")]
    anchors = [whole("v1/a.txt", "c1")]
    assert measure(hits, anchors, k=2)["any_found"] is False
    assert measure(hits, anchors, k=3)["first_rank"] == 3
    assert measure(hits, anchors, k=None)["first_rank"] == 3


def test_top_k_counts_distinct_chunks_not_raw_hits():
    hits = [h("x"), h("x"), h("c1")]
    assert measure(hits, [whole("v1/a.txt", "c1")], k=2)["first_rank"] == 2


# ---- several documents ----------------------------------------------------------------------------


def test_multi_file_question_needs_every_anchor_for_all_found():
    anchors = [whole("v1/a.txt", "a1"), whole("v1/b.pdf", "b1")]
    hits = [h("a1", "a.txt"), h("z", "c.docx")]
    m = measure(hits, anchors, files=("v1/a.txt", "v1/b.pdf"))
    assert m["any_found"] and not m["all_found"] and m["anchors_found"] == 1
    assert m["files_found"] == 1 and m["file_recall"] == 0.5 and not m["all_files_found"]
    assert m["distinct_files"] == 2


def test_both_documents_retrieved():
    anchors = [whole("v1/a.txt", "a1"), whole("v1/b.pdf", "b1")]
    hits = [h("b1", "b.pdf"), h("a1", "a.txt")]
    m = measure(hits, anchors, files=("v1/a.txt", "v1/b.pdf"))
    assert (
        m["all_found"] and m["all_files_found"] and m["file_recall"] == 1.0 and m["first_rank"] == 1
    )


# ---- file level is not passage level --------------------------------------------------------------


def test_correct_file_but_wrong_passage():
    m = measure([h("other1"), h("other2")], [whole("v1/a.txt", "c1")])
    assert m["any_file_found"] and m["file_recall"] == 1.0
    assert not m["any_found"] and m["right_file_wrong_passage"] is True


def test_wrong_file_is_not_the_right_file_wrong_passage_case():
    m = measure([h("z", "c.docx")], [whole("v1/a.txt", "c1")])
    assert not m["any_file_found"] and m["right_file_wrong_passage"] is False


# ---- anchor-mapping failures are not retrieval failures ---------------------------------------------


def test_unmappable_anchor_is_reported_apart_and_scores_nothing():
    m = measure([h("c1")], [whole("v1/a.txt", "c1"), absent("v1/a.txt")])
    assert m["status"] == "mapping_failure" and m["absent_anchors"] == 1
    for key in ("any_found", "all_found", "first_rank", "reciprocal_rank", "no_evidence"):
        assert m[key] is None


def test_answerable_case_without_anchors_is_not_scored_at_passage_level():
    m = measure([h("c1")], [])
    assert m["status"] == "no_anchors" and m["any_found"] is None


def test_summary_keeps_mapping_failures_out_of_every_denominator():
    ok = passage_row(case("ok"), [h("c1")], [whole("v1/a.txt", "c1")], NAMES, None)
    miss = passage_row(case("miss"), [h("z")], [whole("v1/a.txt", "c1")], NAMES, None)
    bad = passage_row(case("bad"), [h("c1")], [absent("v1/a.txt")], NAMES, None)
    s = summarise_pool([ok, miss, bad])
    assert s["answerable_cases"] == 3 and s["measured"] == 2
    assert s["mapping_failures"] == {"n": 1, "ids": ["bad"]}
    assert s["any_found"]["n"] == 2 and s["any_found"]["passed"] == 1
    assert s["no_evidence"] == {"n": 1, "ids": ["miss"]}


# ---- aggregation ------------------------------------------------------------------------------------


def case(cid, pool_split="dev", behavior="answer", files=("v1/a.txt",), **kw):
    return {
        "id": cid,
        "question": f"question {cid}",
        "split": pool_split,
        "category": kw.pop("category", "single_fact"),
        "language": kw.pop("language", "en"),
        "expected_behavior": behavior,
        "expected_files": list(files),
        "evidence_anchors": [{"file": f, "quote": "q"} for f in files],
        **kw,
    }


def test_mrr_is_the_mean_over_measured_cases_with_zero_for_a_miss():
    rows = [
        passage_row(case("r1"), [h("c1")], [whole("v1/a.txt", "c1")], NAMES, None),  # 1
        passage_row(case("r2"), [h("x"), h("c1")], [whole("v1/a.txt", "c1")], NAMES, None),  # 1/2
        passage_row(case("r4"), [h("x")], [whole("v1/a.txt", "c1")], NAMES, None),  # 0
        passage_row(case("r3"), [h("x"), h("y"), h("c1")], [whole("v1/a.txt", "c1")], NAMES, None),
    ]
    s = summarise_pool(rows)
    assert s["mrr"] == pytest.approx((1 + 0.5 + 0 + 1 / 3) / 4, abs=1e-3)
    assert s["any_found"]["passed"] == 3 and s["any_found"]["n"] == 4
    lo, hi = s["any_found"]["ci95"]
    assert lo == pytest.approx(0.301, abs=1e-3) and hi == pytest.approx(
        0.954, abs=1e-3
    )  # Wilson 3/4
    assert s["first_rank_distribution"] == {"1": 1, "2": 1, "3": 1}


def test_report_separates_pools_and_breaks_down_by_category_format_language():
    rows = [
        passage_row(case("d1"), [h("c1")], [whole("v1/a.txt", "c1")], NAMES, None),
        passage_row(
            case("d2", category="table", files=("v1/b.pdf",), language="ur"),
            [h("z", "b.pdf")],
            [whole("v1/b.pdf", "b1")],
            NAMES,
            None,
        ),
        passage_row(case("t1", "test"), [h("x")], [whole("v1/a.txt", "c1")], NAMES, None),
    ]
    report = passage_report(rows, [])
    assert set(report["pools"]) == {"development", "regression"}
    dev = report["pools"]["development"]
    assert dev["overall"]["answerable_cases"] == 2
    assert report["pools"]["regression"]["overall"]["answerable_cases"] == 1
    assert dev["by_category"]["table"]["any_found"] == {
        "n": 1,
        "passed": 0,
        "rate": 0.0,
        "ci95": pytest.approx([0.0, 0.793], abs=1e-3),
    }
    assert set(dev["by_format"]) == {"txt", "pdf"}
    assert set(dev["by_language"]) == {"en", "ur"}
    assert "overall" not in report  # no number that mixes the pools


def test_held_out_rows_are_refused_not_reported():
    row = passage_row(case("h1", "held_out"), [h("c1")], [whole("v1/a.txt", "c1")], NAMES, None)
    with pytest.raises(HeldOutRefused):
        passage_report([row], [])
    with pytest.raises(HeldOutRefused):
        passage_report([], [refusal_row(case("h2", "held_out", "not_found", ()), [h("c1")], None)])


# ---- refusal / not-found cases ----------------------------------------------------------------------


def test_refusal_best_score_distribution():
    def r(cid, scores):
        c = case(cid, behavior="not_found", files=())
        return refusal_row(c, [h(f"{cid}{i}", score=s) for i, s in enumerate(scores)], None)

    rows = [r("n1", [0.2, 0.4]), r("n2", [0.3]), r("n3", [0.6, 0.1]), r("n4", [None]), r("n5", [])]
    s = summarise_refusal_scores(rows)
    assert s["n"] == 5 and s["with_any_result"] == 4 and s["no_vector_score"] == 2
    assert s["best_score"]["min"] == 0.3 and s["best_score"]["max"] == 0.6
    assert s["best_score"]["median"] == 0.4 and s["best_score"]["n"] == 3


def test_refusal_top_k_applies_before_taking_the_best_score():
    row = refusal_row(
        case("n1", behavior="not_found", files=()), [h("a", score=0.2), h("b", score=0.9)], 1
    )
    assert row["best_vector_score"] == 0.2


def test_refusal_cases_are_not_in_the_answerable_metrics():
    rows = [passage_row(case("a1"), [h("c1")], [whole("v1/a.txt", "c1")], NAMES, None)]
    refusal = [refusal_row(case("n1", behavior="not_found", files=()), [h("z", score=0.3)], None)]
    pool = passage_report(rows, refusal)["pools"]["development"]
    assert pool["overall"]["answerable_cases"] == 1
    assert pool["refusal"]["n"] == 1


# ---- wiring into the probe (still free) -------------------------------------------------------------


def test_probe_captures_plain_hits_once_per_case_without_extra_searches():
    import asyncio

    from evaluation.rag_eval.retrieval_probe import probe

    calls: list[str] = []

    async def search(query: str) -> list[Hit]:
        calls.append(query)
        return [h("c1")]

    cases = [case("a1"), case("n1", behavior="not_found", files=())]
    sink: dict[str, list[Hit]] = {}
    asyncio.run(probe(search, cases, ["plain"], sink))
    assert set(sink) == {"a1", "n1"} and len(calls) == 2
    assert sink["a1"][0].chunk_id == "c1"


def test_make_search_keeps_the_chunk_id():
    import asyncio
    import uuid
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from app.retrieval.types import RetrievedChunk
    from evaluation.rag_eval.retrieval_probe import make_search

    cid = uuid.uuid4()
    chunk = RetrievedChunk(
        chunk_id=cid,
        document_id=uuid.uuid4(),
        drive_file_id=uuid.uuid4(),
        filename="a.txt",
        mime_type="text/plain",
        modified_at=datetime.now(UTC),
        chunk_index=0,
        text="t",
        score=0.5,
        source_scores={"vector": 0.4},
    )

    async def retrieve(_request):
        return [chunk]

    hits = asyncio.run(make_search(SimpleNamespace(retrieve=retrieve))("q"))  # type: ignore[arg-type]
    assert hits == [Hit("a.txt", 0.4, str(cid))]


def test_passage_section_reports_unavailable_when_the_database_cannot_be_read(monkeypatch):
    import asyncio

    from evaluation.rag_eval import passage_metrics, runner
    from evaluation.rag_eval.deep import Resolved

    async def fake(*_a, **_k):
        return Resolved(names=NAMES)  # database=False

    monkeypatch.setattr(runner, "load_resolved", fake)
    out = asyncio.run(
        passage_metrics.passage_section(None, [case("a1"), case("h", history=[1])], [], {}, top_k=8)
    )
    assert out["status"] == "unavailable" and out["skipped_history"] == 1
    assert "pools" not in out  # nothing is invented when anchors could not be mapped


def test_passage_section_builds_rows_and_never_contains_held_out(monkeypatch):
    import asyncio

    from evaluation.rag_eval import passage_metrics, runner
    from evaluation.rag_eval.deep import Resolved

    anchors = {"a1": [whole("v1/a.txt", "c1")], "t1": [whole("v1/a.txt", "c1")]}

    async def fake(*_a, **_k):
        return Resolved(names=NAMES, anchors=anchors, database=True)

    monkeypatch.setattr(runner, "load_resolved", fake)
    cases = [case("a1"), case("t1", "test"), case("n1", behavior="not_found", files=())]
    hits = {"a1": [h("c1")], "t1": [h("z")], "n1": [h("q", score=0.3)]}
    out = asyncio.run(passage_metrics.passage_section(None, cases, [], hits, top_k=8))
    assert out["status"] == "ok" and set(out["pools"]) == {"development", "regression"}
    assert out["pools"]["development"]["overall"]["any_found"]["passed"] == 1
    assert out["pools"]["regression"]["overall"]["any_found"]["passed"] == 0
    held = case("h1", "held_out")
    with pytest.raises(HeldOutRefused):
        asyncio.run(passage_metrics.passage_section(None, [held], [], {"h1": [h("c1")]}, top_k=8))


def test_real_mapper_split_quote_end_to_end():
    from evaluation.rag_eval.anchors import map_anchor

    chunks = [("k1", "The refund window is"), ("k2", "30 days from delivery."), ("k3", "unrelated")]
    anchor = map_anchor("v1/a.txt", "refund window is 30 days", chunks)
    assert anchor.kind == "split"
    m = measure([h("k3"), h("k2")], [anchor])
    assert m["status"] == "measured" and m["first_rank"] == 2 and m["all_found"]
    bad = map_anchor("v1/a.txt", "a sentence the index never held", chunks)
    assert measure([h("k1")], [bad])["status"] == "mapping_failure"

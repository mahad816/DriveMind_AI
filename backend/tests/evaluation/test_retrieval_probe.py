"""The retrieval probe decides which search changes we keep, so its maths and plumbing are pinned here."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.retrieval.types import RetrievedChunk
from app.routing.intent_frame.scope import EligibleCollectionScope
from evaluation.rag_eval.retrieval_probe import (
    CANDIDATE_LIMIT,
    PHRASINGS,
    Hit,
    expected_names,
    lower_first,
    make_search,
    measure,
    probe,
    split_cases,
    summarise_answerable,
    summarise_refusal,
)
from evaluation.rag_eval.target import EVAL_USER_ID


def hit(name: str, score: float | None = 0.5) -> Hit:
    return Hit(name, score)


def case(cid: str, behavior="answer", files=("synthetic/a.txt",), **kw: Any) -> dict[str, Any]:
    return {
        "id": cid,
        "split": "dev",
        "language": "en",
        "question": f"question {cid}",
        "expected_behavior": behavior,
        "expected_files": list(files),
        **kw,
    }


# ---- measure ---------------------------------------------------------------------------------------


def test_rank_is_by_distinct_file_not_by_chunk():
    hits = [hit("a.txt"), hit("a.txt"), hit("a.txt"), hit("b.txt")]
    m = measure(hits, ["b.txt"])
    assert m["rank"] == 2 and m["found"] and m["chunks"] == 4 and m["distinct_files"] == 2


def test_best_of_several_expected_files_counts_and_found_all_needs_every_file():
    hits = [hit("x.txt"), hit("a.txt"), hit("b.txt")]
    both = measure(hits, ["a.txt", "b.txt"])
    assert both["rank"] == 2 and both["found_all"]
    one = measure(hits, ["a.txt", "missing.txt"])
    assert one["found"] and one["rank"] == 2 and not one["found_all"]


def test_nothing_found_and_empty_results():
    m = measure([hit("x.txt")], ["a.txt"])
    assert not m["found"] and m["rank"] is None and not m["found_all"]
    empty = measure([], ["a.txt"])
    assert empty["chunks"] == 0 and empty["top_vector_score"] is None and not empty["found"]


def test_no_expected_file_is_never_found_all():
    assert not measure([hit("x.txt")], [])["found_all"]


def test_top_vector_score_ignores_chunks_without_a_vector_hit():
    m = measure([hit("a.txt", None), hit("b.txt", 0.412), hit("c.txt", 0.3)], [])
    assert m["top_vector_score"] == 0.412


# ---- summaries -------------------------------------------------------------------------------------


def row(cid, rank, expected=("a.txt",), distinct=3, chunks=8, found_all=None):
    return {
        "id": cid,
        "rank": rank,
        "found": rank is not None,
        "expected": list(expected),
        "found_all": rank is not None if found_all is None else found_all,
        "distinct_files": distinct,
        "chunks": chunks,
    }


def test_summary_counts_rank_one_mrr_and_misses():
    rows = [row("c1", 1), row("c2", 2), row("c3", None), row("c4", 4)]
    s = summarise_answerable(rows)
    assert (s["n"], s["found_in_results"], s["ranked_first"]) == (4, 3, 1)
    assert s["mrr"] == pytest.approx((1 + 1 / 2 + 0 + 1 / 4) / 4, abs=1e-3)
    assert s["missed"] == ["c3"] and s["found_pct"] == 75.0
    low, high = s["found_ci95_pct"]
    assert low < 75.0 < high


def test_summary_multi_file_and_single_file_fill():
    rows = [
        row("m1", 1, expected=("a.txt", "b.txt"), found_all=True),
        row("m2", 1, expected=("a.txt", "b.txt"), found_all=False),
        row("s1", 1, distinct=1, chunks=8),  # one file filled all 8 slots
        row("s2", 1, distinct=1, chunks=1),  # a single result is not "crowding"
    ]
    s = summarise_answerable(rows)
    assert (s["multi_file_cases"], s["multi_file_all_found"]) == (2, 1)
    assert s["single_file_results"] == 1


def test_empty_summary_does_not_divide_by_zero():
    assert summarise_answerable([]) == {"n": 0}
    assert summarise_refusal([])["top_vector_score_median"] is None


def test_refusal_summary_reports_results_and_scores():
    rows = [
        {"chunks": 5, "top_vector_score": 0.4},
        {"chunks": 0, "top_vector_score": None},
        {"chunks": 3, "top_vector_score": 0.6},
    ]
    s = summarise_refusal(rows)
    assert s["with_any_result"] == 2 and s["top_vector_score_max"] == 0.6
    assert s["top_vector_score_median"] == 0.5


# ---- wording variants ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("How many days?", "how many days?"),
        ("What is the SMSGate fee?", "what is the SMSGate fee?"),
        ("SMSGate fee?", "SMSGate fee?"),  # acronym-like first word is kept
        ("INC-204 duration?", "INC-204 duration?"),
        ("I want 3 nights", "I want 3 nights"),  # a one-letter word is kept
        (
            "Sara Khan's role?",
            "sara Khan's role?",
        ),  # "Sara" is lower-cased; names are not protected
    ],
)
def test_lower_first(question, expected):
    assert lower_first(question) == expected


def test_every_phrasing_keeps_the_original_question_text():
    q = "What is the nightly hotel limit?"
    for name, make in PHRASINGS.items():
        assert "nightly hotel limit?" in make(q), name
    assert PHRASINGS["plain"](q) == q


# ---- case selection and the run loop ---------------------------------------------------------------


def test_split_cases_separates_and_skips_history_and_file_less_cases():
    cases = [
        case("a1"),
        case("a2", "partial"),
        case("a3", files=()),  # nothing to find: not measurable
        case("h1", history=[{"role": "user"}]),  # needs earlier turns
        case("r1", "not_found", files=()),
        case("r2", "correct_premise", files=()),
        case("c1", "chitchat", files=()),  # not a retrieval case
    ]
    answerable, refusal = split_cases(cases)
    assert [c["id"] for c in answerable] == ["a1", "a2"]
    assert [c["id"] for c in refusal] == ["r1", "r2"]


def test_expected_names_are_file_names_not_paths():
    assert expected_names({"expected_files": ["synthetic/x.txt", "public/y.pdf"]}) == [
        "x.txt",
        "y.pdf",
    ]


async def test_probe_runs_every_phrasing_and_skips_english_lead_ins_for_other_languages():
    asked: list[str] = []

    async def search(query: str) -> list[Hit]:
        asked.append(query)
        return [hit("a.txt", 0.5), hit("b.txt", 0.4)]

    cases = [
        case("e1"),
        case("u1", language="roman_urdu"),
        case("r1", "not_found", files=()),
    ]
    report = await probe(search, cases, ["plain", "which_file"])
    assert report["answerable"]["plain"]["n"] == 2
    assert report["answerable"]["which_file"]["n"] == 1  # the Roman Urdu case is skipped
    assert report["answerable"]["plain"]["found_in_results"] == 2
    assert report["refusal_cases"] == {
        "n": 1,
        "with_any_result": 1,
        "top_vector_score_median": 0.5,
        "top_vector_score_max": 0.5,
    }
    assert asked.count("question r1") == 1  # refusal cases are asked once, plain
    assert "Which file says this: question e1" in asked


async def test_probe_records_a_miss():
    async def search(query: str) -> list[Hit]:
        return [hit("other.txt")]

    report = await probe(search, [case("e1")], ["plain"])
    assert report["answerable"]["plain"]["missed"] == ["e1"]
    assert report["rows"]["plain"][0]["rank"] is None


# ---- the real call shape ---------------------------------------------------------------------------


async def test_make_search_sends_the_same_request_the_agent_tool_sends():
    seen: list[Any] = []
    now = datetime.now(UTC)

    def chunk(name: str, scores: dict[str, float]) -> RetrievedChunk:
        return RetrievedChunk(
            chunk_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            drive_file_id=uuid.uuid4(),
            filename=name,
            mime_type="text/plain",
            modified_at=now,
            chunk_index=0,
            text="t",
            score=0.5,
            source_scores=scores,  # type: ignore[arg-type]
        )

    async def retrieve(request: Any) -> list[RetrievedChunk]:
        seen.append(request)
        return [chunk("a.txt", {"vector": 0.42, "keyword": 0.9}), chunk("b.txt", {"keyword": 0.7})]

    hits = await make_search(SimpleNamespace(retrieve=retrieve))("how many days?")  # type: ignore[arg-type]
    request = seen[0]
    assert request.user_id == EVAL_USER_ID and request.query == "how many days?"
    assert isinstance(request.scope, EligibleCollectionScope)
    assert request.candidate_limit == CANDIDATE_LIMIT == 20
    assert request.candidate_policy == "BOUNDED"
    assert [(h.filename, h.vector_score) for h in hits] == [("a.txt", 0.42), ("b.txt", None)]
    assert all(h.chunk_id and uuid.UUID(h.chunk_id) for h in hits)  # passage metrics match on it

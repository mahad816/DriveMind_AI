"""Deterministic scoring beyond the legacy pass: anchors, citation, retrieval, strict pass, outcomes, causes.

Every row is hand-built, so each expected value is known without running anything. No database, no key.
"""

from typing import Any
from uuid import UUID

import pytest

from app.agents.tool_rag.finalization import FILE_NOT_FOUND_TEXT
from app.llm.prompts import NO_EVIDENCE_ANSWER
from app.services.tool_agent_service import TRUNCATION_NOTICE
from evaluation.rag_eval.anchors import (
    ChunkInfo,
    anchor_problems,
    map_anchor,
    map_case_anchors,
    quote_in_chunk,
)
from evaluation.rag_eval.causes import RULES
from evaluation.rag_eval.deep import Resolved, extend_row, extend_rows
from evaluation.rag_eval.runner import base_row, overall, score_row
from evaluation.rag_eval.score import summarise

OWNER = "owner-1"
HANDBOOK, OTHER = "synthetic/handbook.txt", "synthetic/other.txt"
NAMES = {HANDBOOK: "handbook.txt", OTHER: "other.txt"}
QUOTE = "Annual leave is 22 working days per calendar year."


def cid(n: int) -> str:
    return str(UUID(int=n))


C1, C2, C3, C4, C5 = (cid(i) for i in range(1, 6))
FILE_CHUNKS = {
    "handbook.txt": [
        (C1, f"{QUOTE} Sick leave is 10 days."),
        (C2, "Remote work needs approval. Ticket INC-204 was opened on 5 March 2026."),
        (C3, "The sentence is cut at the very"),
        (C4, "end of the chunk and goes on."),
    ],
    "other.txt": [(C5, "Parking is free on Fridays.")],
}
INFOS = {
    cid_: ChunkInfo(cid_, name, OWNER, i, text)
    for name, chunks in FILE_CHUNKS.items()
    for i, (cid_, text) in enumerate(chunks)
}


def make_case(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "t1",
        "category": "single_fact",
        "split": "dev",
        "language": "en",
        "question": "How many days of annual leave do employees get?",
        "expected_behavior": "answer",
        "expected_files": [HANDBOOK],
        "citation_mode": "all",
        "must_include": [["22"]],
        "must_not_include": ["24 days"],
        "evidence_anchors": [{"file": HANDBOOK, "quote": QUOTE}],
        "computed": False,
    }
    return base | kw


def resolved_for(*cases: dict[str, Any], database: bool = True, chunks: Any = None) -> Resolved:
    return Resolved(
        OWNER,
        NAMES,
        INFOS if chunks is None else chunks,
        {c_id: text for chunk_list in FILE_CHUNKS.values() for c_id, text in chunk_list},
        {c["id"]: map_case_anchors(c, FILE_CHUNKS, NAMES) for c in cases},
        database,
    )


def search(*hits: tuple[str, str]) -> dict[str, Any]:
    return {
        "query": "q",
        "chunks": [
            {"rank": i, "chunk_id": c, "filename": f, "chunk_index": i}
            for i, (c, f) in enumerate(hits, 1)
        ],
    }


def trace(*searches: dict[str, Any], reads: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    calls = [{"tool": "file_evidence", "reads": reads, "result": None}] if reads else []
    return {"schema_version": 1, "searches": list(searches), "tool_calls": calls, "events": []}


def execution(**kw: Any) -> dict[str, Any]:
    base = {
        "path": "tool_agent",
        "outcome": "COMPLETED",
        "search_count": 1,
        "whole_file_reads": 0,
        "claim_check_removed": 0,
    }
    return base | kw


def make_row(
    case: dict[str, Any],
    reply: str = "",
    cited: tuple[tuple[str, str], ...] = (),
    *,
    judge: bool | None = None,
    error: str | None = None,
    trace_: dict[str, Any] | None = None,
    ex: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = base_row(
        case,
        reply=reply,
        cited_files=list(dict.fromkeys(path for _, path in cited)),
        error=error,
        latency_s=1.0,
    )
    row["cited"] = [{"chunk_id": c, "file": p, "score": 0.5, "snippet": ""} for c, p in cited]
    score_row(case, row)
    if judge is not None:
        row["refusal"] = {"ok": judge, "reason": ""}
    row["overall"] = {"pass": overall(row, case["expected_behavior"])}
    row["trace"] = trace_
    row["execution"] = ex
    return row


def run(case: dict[str, Any], row: dict[str, Any], **kw: Any) -> dict[str, Any]:
    return extend_row(case, row, resolved_for(case, **kw))


GOOD_TRACE = trace(search((C2, "handbook.txt"), (C5, "other.txt"), (C1, "handbook.txt")))


# ---- anchors ---------------------------------------------------------------------------------------


def test_a_quote_is_found_with_the_validators_own_normalisation() -> None:
    assert quote_in_chunk("annual leave is 22 working days", FILE_CHUNKS["handbook.txt"][0][1])
    assert not quote_in_chunk("annual leave is 24 working days", FILE_CHUNKS["handbook.txt"][0][1])
    assert not quote_in_chunk("", "anything")


def test_an_anchor_cut_by_a_chunk_boundary_is_classified_split_and_keeps_both_chunks() -> None:
    chunks = FILE_CHUNKS["handbook.txt"]
    whole = map_anchor(HANDBOOK, QUOTE, chunks)
    split = map_anchor(HANDBOOK, "cut at the very end of the chunk", chunks)
    lost = map_anchor(HANDBOOK, "a sentence that is nowhere", chunks)
    assert (whole.kind, whole.chunk_ids) == ("whole", (C1,))
    assert (split.kind, split.chunk_ids) == ("split", (C3, C4))
    assert (lost.kind, lost.chunk_ids) == ("absent", ())


def test_the_validator_fails_on_more_than_two_percent_split_and_on_any_absent_anchor() -> None:
    chunks = FILE_CHUNKS["handbook.txt"]
    whole, split = (
        map_anchor(HANDBOOK, QUOTE, chunks),
        map_anchor(HANDBOOK, "cut at the very end", chunks),
    )
    assert anchor_problems({"a": [whole] * 49 + [split]}) == []  # exactly 2 percent
    assert "cut by a chunk boundary" in anchor_problems({"a": [whole] * 48 + [split] * 2})[0]
    lost = map_anchor(HANDBOOK, "nowhere", chunks)
    assert anchor_problems({"x1": [lost]})[0].startswith("x1: anchor not in any indexed chunk")


def test_a_split_anchor_is_satisfied_by_citing_either_half() -> None:
    case = make_case(
        must_include=[["cut"]],
        evidence_anchors=[{"file": HANDBOOK, "quote": "cut at the very end of the chunk"}],
    )
    for cited in (C3, C4):
        row = run(case, make_row(case, "It is cut.", ((cited, HANDBOOK),), trace_=GOOD_TRACE))
        assert row["citation"]["all_anchors_cited"] is True
        assert row["citation"]["split_anchors"] == 1


# ---- the new scores --------------------------------------------------------------------------------


def test_right_file_wrong_passage_passes_the_legacy_pass_but_not_the_strict_pass() -> None:
    case = make_case()
    row = run(
        case, make_row(case, "22 days.", ((C2, HANDBOOK),), trace_=GOOD_TRACE, ex=execution())
    )
    assert row["overall"]["pass"] is True  # the file was cited and the fact is there
    assert row["citation"]["all_anchors_cited"] is False
    assert row["strict"] == {"deterministic": False, "graded": None}
    assert row["cause"] == {"primary": "citation", "secondary": [], "failed": "strict"}


def test_the_right_passage_cited_passes_both() -> None:
    case = make_case()
    row = run(
        case, make_row(case, "22 days.", ((C1, HANDBOOK),), trace_=GOOD_TRACE, ex=execution())
    )
    assert row["overall"]["pass"] is True and row["strict"]["deterministic"] is True
    assert row["cause"] is None and row["outcome"] == "correct" and row["review"] == []
    assert row["claim_support"] == "ungraded"  # nothing here says the claims are supported


def test_a_correct_fact_beside_an_invented_number_is_flagged_and_passes_only_the_legacy_pass() -> (
    None
):
    case = make_case()
    reply = "22 days, plus 3 bonus days."
    row = run(case, make_row(case, reply, ((C1, HANDBOOK),), trace_=GOOD_TRACE, ex=execution()))
    assert row["overall"]["pass"] is True
    assert row["screen"] == {"clean": False, "flagged": ["number:3"], "unsupported": ["number:3"]}
    assert row["strict"]["deterministic"] is False
    assert row["cause"]["primary"] == "grounding"
    assert "screen_flag" in row["review"]


def test_a_fabricated_chunk_identifier_fails_integrity_and_is_a_critical_candidate() -> None:
    case = make_case()
    fake = cid(999)
    row = run(
        case, make_row(case, "22 days.", ((C1, HANDBOOK), (fake, HANDBOOK)), trace_=GOOD_TRACE)
    )
    assert row["citation"]["integrity"] == {"ok": False, "bad": [f"missing:{fake[:8]}"]}
    assert row["critical_candidates"] == ["citation_integrity"]
    assert row["strict"]["deterministic"] is False


def test_integrity_checks_the_owner_and_the_file_name_the_corpus_maps_to() -> None:
    case = make_case()
    foreign = {**INFOS, C1: ChunkInfo(C1, "handbook.txt", "someone-else", 0, "x")}
    row = run(case, make_row(case, "22 days.", ((C1, HANDBOOK),)), chunks=foreign)
    assert row["citation"]["integrity"]["bad"] == [f"foreign_owner:{C1[:8]}"]
    row = run(case, make_row(case, "22 days.", ((C5, HANDBOOK),)))  # C5 lives in other.txt
    assert row["citation"]["integrity"]["bad"] == [f"wrong_file:{C5[:8]}"]


def test_a_computed_case_may_state_a_derived_number_and_others_may_not() -> None:
    reply = "Total leave is 32 days."
    plain = make_case(must_include=[["32"]])
    computed = make_case(must_include=[["32"]], computed=True)
    flagged = run(plain, make_row(plain, reply, ((C1, HANDBOOK),)))
    allowed = run(computed, make_row(computed, reply, ((C1, HANDBOOK),)))
    assert flagged["screen"]["flagged"] == ["number:32"]
    assert allowed["screen"] == {"clean": True, "flagged": [], "unsupported": []}


def test_fact_recall_gives_partial_credit_next_to_the_all_or_nothing_correctness() -> None:
    case = make_case(must_include=[["22"], ["10"], ["5"]])
    row = run(case, make_row(case, "22 days and 10 sick days.", ((C1, HANDBOOK),)))
    assert row["fact_recall"] == {"required": 3, "present": 2, "recall": 0.667}
    assert row["answer"]["correct"] is False


def test_an_unnecessary_extra_citation_fails_strict_but_precision_stays_a_separate_metric() -> None:
    case = make_case()
    row = run(case, make_row(case, "22 days.", ((C1, HANDBOOK), (C5, OTHER)), trace_=GOOD_TRACE))
    assert row["citation"]["precision"] == 0.5 and row["citation"]["extra_files"] == 1
    assert row["citation"]["unnecessary_files"] == 1  # other.txt holds none of the required facts
    assert row["overall"]["pass"] is True  # legacy is unchanged and kept for comparison
    assert row["strict"]["deterministic"] is False
    assert row["cause"]["primary"] == "citation"


def test_declared_supporting_files_of_a_multi_document_case_are_never_unnecessary() -> None:
    case = make_case(
        expected_files=[HANDBOOK, OTHER],
        must_include=[["22"], ["parking"]],
        evidence_anchors=[{"file": HANDBOOK, "quote": QUOTE}],
    )
    row = run(
        case,
        make_row(
            case, "22 days; parking is free.", ((C1, HANDBOOK), (C5, OTHER)), trace_=GOOD_TRACE
        ),
    )
    assert row["citation"]["extra_files"] == 0 and row["citation"]["unnecessary_files"] == 0
    assert row["strict"]["deterministic"] is True


def test_an_extra_file_that_may_carry_a_required_fact_is_undecided_not_penalised() -> None:
    case = make_case(
        must_include=[["22"], ["parking"]]
    )  # other.txt is NOT declared but holds "Parking"
    row = run(case, make_row(case, "22 days; parking is free.", ((C1, HANDBOOK), (C5, OTHER))))
    assert (
        row["citation"]["unnecessary_files"] == 0 and row["citation"]["undecided_extra_files"] == 1
    )
    assert row["strict"]["deterministic"] is None  # the annotation cannot say; nothing is invented
    computed = make_case(computed=True)  # operands never appear as the answer
    row = run(computed, make_row(computed, "22 days.", ((C1, HANDBOOK), (C5, OTHER))))
    assert row["citation"]["undecided_extra_files"] == 1 and row["strict"]["deterministic"] is None
    unknown_text = run(
        case, make_row(case, "22 days.", ((C1, HANDBOOK), (C5, OTHER))), database=False
    )
    assert unknown_text["citation"]["undecided_extra_files"] == 1  # text unavailable: undecided


def test_strict_stands_on_its_own_criteria_and_not_on_the_legacy_pass_or_the_judge() -> None:
    partial = make_case(expected_behavior="partial", must_not_include=["30 days"])
    row = run(
        partial, make_row(partial, "22 days.", ((C1, HANDBOOK),), judge=False, trace_=GOOD_TRACE)
    )
    assert row["overall"]["pass"] is False  # the refusal judge said fail
    assert row["strict"]["deterministic"] is True  # strict never reads that verdict
    row["overall"] = None  # even with no legacy verdict at all, strict is computed
    assert extend_row(partial, row, resolved_for(partial))["strict"]["deterministic"] is True
    # and a missing fact fails strict by its own fact criterion, with no help from legacy
    case = make_case(must_include=[["22"], ["10"]])
    low = run(case, make_row(case, "22 days.", ((C1, HANDBOOK),), trace_=GOOD_TRACE))
    assert low["strict"]["deterministic"] is False and low["fact_recall"]["recall"] == 0.5


def test_a_refusal_passes_strict_on_deterministic_criteria_only() -> None:
    case = refusal_case()
    ok = run(case, make_row(case, "I could not find that.", judge=False))
    assert ok["strict"]["deterministic"] is True  # judge disagreement is a review item, not strict
    bad = run(case, make_row(case, "Employees get 30 days.", judge=True))
    assert bad["strict"]["deterministic"] is False


def clarify_case_for_strict(**kw: Any) -> dict[str, Any]:
    return make_case(
        **{
            "id": "cl1",
            "category": "ambiguous",
            "question": "Where is Sam Kerrigan based?",
            "expected_behavior": "clarify",
            "expected_files": [],
            "must_include": [],
            "must_not_include": ["Tollbridge", "Northgate"],
            "evidence_anchors": [
                {"file": HANDBOOK, "quote": "Sam Kerrigan the driver is based at Tollbridge."},
                {"file": HANDBOOK, "quote": "Sam Kerrigan the customer contact is at Northgate."},
            ],
        }
        | kw
    )


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ("Which Sam Kerrigan do you mean, the driver or the customer contact?", True),
        ("", False),  # nothing said
        ("Hello!", False),  # a greeting is not a question
        ("That is not in your files.", False),  # an abstention is not a question
        ("I could not find that in your files. Can you rephrase?", False),  # abstention plus a "?"
        ("Sam Kerrigan the driver is based at Tollbridge.", False),  # picked a reading
        ("Tollbridge, or did you mean Northgate?", False),  # states the values of the readings
        (
            "Hello! How can I help you?",
            None,
        ),  # a question that names no reading: undecided, never a pass
    ],
)
def test_a_clarify_case_passes_strict_only_for_a_real_clarifying_question(
    reply: str, expected: bool | None
) -> None:
    case = clarify_case_for_strict()
    # judge=True: the refusal judge would pass every one of these, strict must not depend on it
    row = run(case, make_row(case, reply, judge=True))
    assert row["strict"]["deterministic"] is expected


def test_a_clarifying_reply_that_cites_a_file_fails_strict() -> None:
    case = clarify_case_for_strict()
    reply = "Which Sam Kerrigan do you mean, the driver or the customer contact?"
    row = run(case, make_row(case, reply, ((C1, HANDBOOK),), judge=True))
    assert row["strict"]["deterministic"] is False


def test_the_clarify_rule_leaves_every_other_behaviour_untouched() -> None:
    case = make_case()
    row = run(case, make_row(case, "22 days.", ((C1, HANDBOOK),), trace_=GOOD_TRACE))
    assert row["strict"]["deterministic"] is True
    refusal = refusal_case()
    assert run(refusal, make_row(refusal, "I could not find that."))["strict"]["deterministic"]


def test_retrieval_from_the_recorded_searches() -> None:
    case = make_case()
    row = run(case, make_row(case, "22 days.", ((C1, HANDBOOK),), trace_=GOOD_TRACE))
    assert row["retrieval"] == {
        "anchors": 1,
        "anchors_retrieved": 1,
        "anchor_retrieved": True,
        "anchor_read": False,
        "anchor_seen": True,
        "best_rank": 3,
        "file_retrieved": True,
        "searches": 1,
        "distinct_files_per_search": [2],
    }
    miss = run(
        case,
        make_row(case, "", trace_=trace(search((C5, "other.txt")), search((C2, "handbook.txt")))),
    )
    assert miss["retrieval"]["anchor_retrieved"] is False and miss["retrieval"]["best_rank"] is None
    assert miss["retrieval"]["file_retrieved"] is True  # right file, wrong passage
    read = trace(reads=[{"file": "handbook.txt", "chunks_returned": [{"chunk_id": C1}]}])
    seen = run(case, make_row(case, "22", trace_=read))
    assert seen["retrieval"]["anchor_read"] is True and seen["retrieval"]["anchor_seen"] is True


# ---- outcome matrices and critical candidates --------------------------------------------------------


def refusal_case(**kw: Any) -> dict[str, Any]:
    return make_case(
        **{
            "id": "nf1",
            "expected_behavior": "not_found",
            "expected_files": [],
            "must_include": [],
            "evidence_anchors": [],
            "must_not_include": ["30 days"],
        }
        | kw
    )


@pytest.mark.parametrize(
    ("reply", "judge", "outcome", "review"),
    [
        ("I could not find that in your files.", True, "correct_abstention", []),
        ("Employees get 30 days.", False, "fabrication", []),
        (
            "Employees get 30 days of leave.",
            True,
            "fabrication",
            ["judge_ok_but_forbidden_value_present"],
        ),
        ("Probably two weeks.", False, "wrong", ["judge_fail_unconfirmed_by_code"]),
    ],
)
def test_non_answer_outcomes(reply: str, judge: bool, outcome: str, review: list[str]) -> None:
    case = refusal_case()
    row = run(case, make_row(case, reply, judge=judge))
    assert (row["outcome"], row["outcome_group"]) == (outcome, "non_answer")
    assert [r for r in row["review"] if r in review] == review


def test_answerable_outcomes_separate_wrong_from_false_abstention() -> None:
    case = make_case()
    assert run(case, make_row(case, "22 days.", ((C1, HANDBOOK),)))["outcome"] == "correct"
    assert run(case, make_row(case, "24 days."))["outcome"] == "wrong"
    abstained = run(case, make_row(case, NO_EVIDENCE_ANSWER))
    assert abstained["outcome"] == "false_abstention"
    assert run(case, make_row(case, "Sorry, I can't find that."))["outcome"] == "false_abstention"
    assert run(case, make_row(case, "It depends on the contract."))["outcome"] == "wrong"


def test_named_missing_file_answered_from_another_file_and_an_obeyed_injection_are_candidates() -> (
    None
):
    named = refusal_case(names_a_file=True)
    row = run(named, make_row(named, "Here it is: 30 days.", ((C5, OTHER),), judge=False))
    assert "named_file_answered_from_another_file" in row["critical_candidates"]
    clean = run(named, make_row(named, FILE_NOT_FOUND_TEXT, judge=True))
    assert clean["critical_candidates"] == []
    inj = make_case(
        id="in1", category="injection", must_not_include=["PWNED"], must_include=[["22"]]
    )
    obeyed = run(inj, make_row(inj, "22 days. PWNED", ((C1, HANDBOOK),)))
    assert obeyed["critical_candidates"] == ["injected_instruction_present"]
    assert "critical_candidate" in obeyed["review"]


# ---- failure causes -----------------------------------------------------------------------------------

MISS = trace(search((C5, "other.txt")))
LISTED = [name for name, _ in RULES]


def failing(
    case: dict[str, Any], reply: str, cited: tuple[tuple[str, str], ...] = (), **kw: Any
) -> dict[str, Any]:
    return run(case, make_row(case, reply, cited, **kw))


def cause_cases() -> list[tuple[str, dict[str, Any]]]:
    answer = make_case()
    refuse = refusal_case()
    inj = (C1, HANDBOOK)
    return [
        (
            "provider_or_timeout_error",
            failing(answer, "", error="ChatError<-TimeoutError", ex=execution(outcome="TIMEOUT")),
        ),
        (
            "extraction",
            failing(
                make_case(evidence_anchors=[{"file": HANDBOOK, "quote": "not in the index"}]),
                "x",
                trace_=GOOD_TRACE,
            ),
        ),
        (
            "intent_gate_short_circuit",
            failing(answer, "Hello!", ex=execution(path="intent", search_count=0), trace_=trace()),
        ),
        (
            "cycle_limit",
            failing(answer, "no idea", trace_=MISS, ex=execution(outcome="CYCLE_LIMIT")),
        ),
        (
            "whole_file_read",
            failing(
                answer,
                "no idea",
                trace_=trace(reads=[{"file": "other.txt", "chunks_returned": [{"chunk_id": C5}]}]),
                ex=execution(search_count=0, whole_file_reads=1),
            ),
        ),
        ("no_search", failing(answer, "no idea", trace_=trace(), ex=execution(search_count=0))),
        ("retrieval_miss", failing(answer, "no idea", trace_=MISS, ex=execution())),
        (
            "no_evidence_envelope",
            failing(answer, NO_EVIDENCE_ANSWER, trace_=GOOD_TRACE, ex=execution()),
        ),
        (
            "truncation_notice",
            failing(
                answer,
                TRUNCATION_NOTICE + "\n\nIt is two weeks.",
                trace_=GOOD_TRACE,
                ex=execution(),
            ),
        ),
        (
            "claim_check_removal",
            failing(
                answer, "Leave exists.", trace_=GOOD_TRACE, ex=execution(claim_check_removed=1)
            ),
        ),
        (
            "generation_error",
            failing(answer, "Employees get 24 days.", (inj,), trace_=GOOD_TRACE, ex=execution()),
        ),
        (
            "fabrication",
            failing(refuse, "30 days.", judge=False, ex=execution(), trace_=GOOD_TRACE),
        ),
        (
            "grounding",
            failing(
                answer, "22 days, plus 3 bonus days.", (inj,), trace_=GOOD_TRACE, ex=execution()
            ),
        ),
        (
            "citation",
            failing(answer, "22 days.", ((C2, HANDBOOK),), trace_=GOOD_TRACE, ex=execution()),
        ),
        (
            "false_abstention",
            failing(answer, "I don't have that information.", trace_=GOOD_TRACE, ex=execution()),
        ),
        ("retrieved_not_used", failing(answer, "Leave exists.", trace_=GOOD_TRACE, ex=execution())),
    ]


def test_every_cause_has_a_pinned_example_row() -> None:
    cases = cause_cases()
    for expected, row in cases:
        assert row["cause"] is not None, expected
        assert row["cause"]["primary"] == expected, (expected, row["cause"])
    assert [name for name, _ in cases] == LISTED  # unknown is tested on its own


def test_the_documented_rule_order_is_the_tested_order() -> None:
    assert LISTED == [
        "provider_or_timeout_error", "extraction", "intent_gate_short_circuit", "cycle_limit",
        "whole_file_read", "no_search", "retrieval_miss", "no_evidence_envelope", "truncation_notice",
        "claim_check_removal", "generation_error", "fabrication", "grounding", "citation",
        "false_abstention", "retrieved_not_used",
    ]  # fmt: skip
    # the first matching rule is primary, the others are kept as secondary flags
    case = make_case()
    row = failing(case, NO_EVIDENCE_ANSWER, trace_=MISS, ex=execution())
    assert row["cause"]["primary"] == "retrieval_miss"
    assert row["cause"]["secondary"] == ["no_evidence_envelope", "false_abstention"]


def test_a_failure_no_rule_can_explain_is_unknown_never_forced() -> None:
    case = make_case(must_include=[["22"], ["10"]])
    # facts missing, but no trace and no execution record: nothing says where it went wrong
    row = failing(case, "Leave is generous.")
    assert row["missing"] == ["trace"] and row["cause"]["primary"] == "unknown"
    assert "trace_missing" in row["review"]


def test_a_row_that_did_not_fail_has_no_cause() -> None:
    case = make_case()
    row = failing(case, "22 days.", ((C1, HANDBOOK),), trace_=GOOD_TRACE, ex=execution())
    assert row["cause"] is None


# ---- statuses and missing data ------------------------------------------------------------------------


def test_cap_stopped_failed_and_partial_rows_stay_separate() -> None:
    case = make_case()
    stopped = base_row(case)
    stopped.update(cap_stopped=True, error="cap_stopped", overall=None, answer=None)
    assert extend_row(case, stopped, resolved_for(case))["status"] == "cap_stopped"
    assert stopped["strict"] == {"deterministic": None, "graded": None} and stopped["cause"] is None
    failed = failing(case, "", error="ChatError<-TimeoutError", trace_=GOOD_TRACE, ex=execution())
    assert failed["status"] == "failed" and failed["strict"]["deterministic"] is False
    assert failed["cause"]["primary"] == "provider_or_timeout_error"
    partial = failing(case, "22 days.", ((C1, HANDBOOK),))  # no trace recorded
    assert partial["status"] == "scored_partial" and partial["missing"] == ["trace"]
    assert partial["retrieval"] is None and partial["strict"]["deterministic"] is True


def test_without_the_database_chunk_level_fields_are_unknown_not_guessed() -> None:
    case = make_case()
    row = extend_row(
        case, make_row(case, "22 days.", ((C1, HANDBOOK),), trace_=GOOD_TRACE), Resolved()
    )
    assert row["citation"]["all_anchors_cited"] is None and row["citation"]["integrity"] is None
    assert row["screen"] is None and row["strict"]["deterministic"] is None
    assert "chunk_texts" in row["missing"] and row["status"] == "scored_partial"


def test_a_row_written_before_cited_chunks_were_recorded_keeps_its_file_level_scores() -> None:
    case = make_case()
    row = make_row(case, "22 days.", ((C1, HANDBOOK),), trace_=GOOD_TRACE)
    del row["cited"]
    row = extend_row(case, row, resolved_for(case))
    assert "cited_chunks" in row["missing"]
    assert row["citation"]["all_anchors_cited"] is None and row["citation"]["precision"] == 1.0
    assert row["strict"]["deterministic"] is None and row["screen"] is None


def test_extending_twice_gives_the_same_row() -> None:
    case = make_case()
    row = make_row(case, "22 days.", ((C1, HANDBOOK),), trace_=GOOD_TRACE, ex=execution())
    once = extend_row(case, row, resolved_for(case)).copy()
    assert extend_row(case, row, resolved_for(case)) == once


# ---- summary version 2 and rescoring --------------------------------------------------------------------


OLD_KEYS = {
    "cases", "cap_stopped", "incomplete", "errors", "evidence_found", "answer_correct", "refusal_ok",
    "clean", "overall_pass", "latency_s", "by_category",
}  # fmt: skip


def old_style_rows() -> list[dict[str, Any]]:
    """Rows as written before ticket 01/02: no cited chunks, no trace, no execution, no accounting."""
    case = make_case()
    good = make_row(case, "22 days.", ((C1, HANDBOOK),))
    bad = make_row(case, "24 days.", ((C1, HANDBOOK),))
    for row in (good, bad):
        for key in ("cited", "trace", "execution"):
            row.pop(key)
    return [good, bad]


def test_rescoring_old_and_new_rows_keeps_every_old_field_and_adds_version_two() -> None:
    cases = {"t1": make_case()}
    before = summarise(old_style_rows())
    assert OLD_KEYS <= before.keys() and before["schema_version"] == 2
    assert before["overall_pass"]["passed"] == 1 and before["overall_pass"]["n"] == 2
    for resolved in (Resolved(), resolved_for(cases["t1"])):
        rows = extend_rows(cases, old_style_rows(), resolved)
        after = summarise(rows)
        assert {k: after[k] for k in OLD_KEYS} == {k: before[k] for k in OLD_KEYS}
        assert after["row_status"] == {"scored_partial": 2}
    new_style = [
        make_row(cases["t1"], "22 days.", ((C1, HANDBOOK),), trace_=GOOD_TRACE, ex=execution())
    ]
    after = summarise(extend_rows(cases, new_style, resolved_for(cases["t1"])))
    assert after["strict_deterministic"]["passed"] == 1
    assert after["citation"]["integrity"]["passed"] == 1
    assert after["retrieval"]["best_rank_median"] == 3
    assert after["strict_graded"]["n"] == 0  # the slot exists and is empty until ticket 09
    assert after["outcomes"] == {"answerable": {"correct": 1}}


def test_the_summary_counts_causes_outcomes_and_rolls_up_by_dimension() -> None:
    cases = {
        "t1": make_case(),
        "nf1": refusal_case(),
        "in1": make_case(id="in1", category="injection"),
    }
    rows = [
        make_row(cases["t1"], "22 days.", ((C1, HANDBOOK),), trace_=GOOD_TRACE, ex=execution()),
        make_row(cases["nf1"], "30 days.", judge=False, trace_=GOOD_TRACE, ex=execution()),
        make_row(cases["in1"], "22 days.", ((C2, HANDBOOK),), trace_=GOOD_TRACE, ex=execution()),
    ]
    stopped = base_row(cases["t1"])
    stopped.update(cap_stopped=True, error="cap_stopped")
    rows.append(stopped)
    summary = summarise(extend_rows(cases, rows, resolved_for(*cases.values())))
    assert summary["row_status"] == {"cap_stopped": 1, "scored": 3}
    assert summary["failure_causes"] == {"citation": 1, "fabrication": 1}
    assert summary["outcomes"]["non_answer"] == {"fabrication": 1}
    assert summary["rollups"]["format"]["txt"]["legacy"]["n"] == 2
    assert set(summary["rollups"]) >= {
        "category",
        "split",
        "language",
        "expected_behavior",
        "format",
        "critical_tag",
    }
    assert summary["cap_stopped"] == 1 and summary["incomplete"] is True


# ---- rescore end to end ---------------------------------------------------------------------------------


def _fixture_row(*, new_style: bool) -> dict[str, Any]:
    """A saved row for the real case sf01. The new style carries what tickets 01 and 02 added."""
    row = {
        "id": "sf01", "category": "single_fact", "split": "dev", "language": "en",
        "expected_behavior": "answer", "question": "q", "reply": "22 working days.",
        "cited_files": ["synthetic/employee_handbook.txt"], "error": None, "latency_s": 1.5,
        "evidence": {"found": True, "expected": 1, "hit": 1, "noise_files": 0},
        "answer": {"correct": True, "missing": [], "forbidden_present": []},
        "clean": None, "refusal": None, "overall": {"pass": True}, "repeat": 1,
    }  # fmt: skip
    if new_style:
        row |= {
            "cited": [
                {
                    "chunk_id": C1,
                    "file": "synthetic/employee_handbook.txt",
                    "score": 0.4,
                    "snippet": "",
                }
            ],
            "execution": execution(),
            "trace": GOOD_TRACE,
            "accounting": {"calls": 2},
        }
    return row


@pytest.mark.parametrize("new_style", [False, True], ids=["before-ticket-01", "ticket-01-fixture"])
async def test_rescore_writes_a_version_two_summary_and_keeps_the_old_fields(
    new_style: bool, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse
    import json
    from types import SimpleNamespace

    from evaluation.rag_eval import cli

    saved = {
        "pipeline": "tool_agent", "model": "gpt-5.4-nano", "datasets": ["rag_v2_cases.json"],
        "rows": [_fixture_row(new_style=new_style)], "summary": {},
    }  # fmt: skip
    saved["summary"] = {k: v for k, v in summarise(saved["rows"]).items() if k in OLD_KEYS}
    source = tmp_path / "run.json"
    source.write_text(json.dumps(saved))

    def unreachable(settings: Any) -> Any:
        raise OSError("no database in this test")  # rescoring must still finish, with partial data

    monkeypatch.setattr(cli, "eval_settings", lambda **_: SimpleNamespace())
    monkeypatch.setattr(cli, "session_factory", unreachable)
    args = argparse.Namespace(file=str(source), with_messy=False, dataset=[], plan=False, cap=1.0)
    await cli.rescore(args)

    written = json.loads((tmp_path / "run_rescored.json").read_text())
    summary = written["summary"]
    assert summary["schema_version"] == 2
    assert {k: summary[k] for k in OLD_KEYS} == {k: saved["summary"][k] for k in OLD_KEYS}
    row = written["rows"][0]
    assert row["status"] == "scored_partial" and "chunk_texts" in row["missing"]
    assert row["overall"] == {"pass": True}  # the legacy verdict is untouched
    assert row["format"] == "txt" and row["strict"] == {"deterministic": None, "graded": None}
    assert ("trace" in row["missing"]) is (not new_style)


async def test_a_failure_in_the_free_scores_never_loses_the_paid_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from evaluation.rag_eval import runner, target

    async def fake_case(settings: Any, case: dict[str, Any], *args: Any) -> dict[str, Any]:
        return {"id": case["id"], "category": "x", "reply": "paid answer", "cited_files": [],
                "error": None, "overall": {"pass": True}}  # fmt: skip

    monkeypatch.setattr(runner, "run_case", fake_case)
    monkeypatch.setattr(runner, "session_factory", lambda settings: None)
    incomplete_case = {
        "id": "a",
        "question": "q",
        "must_include": [],
    }  # no behaviour: scoring raises
    result = await runner.run_pipeline(target.eval_settings(), [incomplete_case], [], "legacy")
    assert result["rows"][0]["reply"] == "paid answer"
    assert result["rows"][0]["extend_error"] == "KeyError"


# ---- fixes from the review ---------------------------------------------------------------------------------


def test_a_cycle_limit_is_not_blamed_when_the_facts_are_right_but_the_citation_is_wrong() -> None:
    case = make_case()
    row = failing(
        case, "22 days.", ((C2, HANDBOOK),), trace_=GOOD_TRACE, ex=execution(outcome="CYCLE_LIMIT")
    )
    assert row["cause"]["primary"] == "citation"


def test_retrieval_miss_needs_a_search_or_a_read_to_have_happened() -> None:
    case = make_case()
    row = failing(case, "no idea", trace_=trace(), ex=execution(path="legacy", search_count=0))
    assert row["cause"]["primary"] == "unknown"  # not "retrieval_miss": nothing was searched


def test_an_old_row_that_cited_nothing_has_nothing_to_check_so_integrity_holds() -> None:
    case = refusal_case()
    row = make_row(case, "I could not find that.", judge=True)
    del row["cited"]
    row = extend_row(case, row, resolved_for(case))
    assert row["citation"]["integrity"] == {"ok": True, "bad": []}
    assert row["strict"]["deterministic"] is True


def test_a_failed_extension_leaves_every_input_row_untouched() -> None:
    good, bad = make_case(), make_case(id="t2")
    del bad["expected_files"]
    rows = [make_row(good, "22 days."), make_row(good, "x") | {"id": "t2"}]
    before = [dict(r) for r in rows]
    with pytest.raises(KeyError):
        extend_rows({"t1": good, "t2": bad}, rows, resolved_for(good))
    assert rows == before


async def test_an_index_that_lacks_the_run_files_is_refused_not_trusted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import asynccontextmanager

    from evaluation.rag_eval import runner
    from evaluation.rag_eval.corpus import CorpusFile

    @asynccontextmanager
    async def empty_database() -> Any:
        yield None

    async def nothing(db: Any, owner: Any, names: Any) -> dict[str, Any]:
        return {}

    async def no_chunks(db: Any, ids: Any) -> dict[str, Any]:
        return {}

    monkeypatch.setattr(runner, "load_file_chunks", nothing)
    monkeypatch.setattr(runner, "load_chunks", no_chunks)
    case = make_case()
    files = [CorpusFile(HANDBOOK, "synthetic", "x", {})]
    resolved = await runner.load_resolved(empty_database, {"t1": case}, [], files)
    assert resolved.database is False  # a re-built or empty index would mark every anchor absent


# ---- a case that requires a refusal must visibly refuse -------------------------------------------------------


@pytest.mark.parametrize(
    ("reply", "verdict", "strict"),
    [
        ("I could not find that in your files.", "refused", True),
        (NO_EVIDENCE_ANSWER, "refused", True),
        # a confident invented answer with NO forbidden value to match: only the abstention rule catches it
        ("Employees typically get 25 days of leave.", "substantive", False),
        ("The retreat is on 12 May 2026.", "substantive", False),
        # refusal plus a value, and neither a decline phrase nor a value: not guessed either way
        ("I could not find it, but similar policies say 22 days.", "ambiguous", None),
        ("That is outside what I can help with.", "ambiguous", None),
        ("It depends on the contract.", "ambiguous", None),
        # a genuine refusal in words the decline list lacks, with a number in it: must not be failed
        ("There is no mention of this in the 10 files I searched.", "ambiguous", None),
        ("I couldn't locate anything about that in version 22 of the docs.", "ambiguous", None),
        ("Mujhe is ka koi zikr nahi mila, 10 files dekhi.", "ambiguous", None),
    ],
)
def test_a_refusal_required_case_must_visibly_refuse(
    reply: str, verdict: str, strict: bool | None
) -> None:
    case = refusal_case(must_not_include=["999 days"])
    # cite the passage that holds 22 so the screen cannot be what decides these rows
    row = run(case, make_row(case, reply, ((C1, HANDBOOK),), judge=True, trace_=GOOD_TRACE))
    assert row["abstention"] == verdict
    assert row["strict"]["deterministic"] is strict
    assert ("abstention_ambiguous" in row["review"]) is (verdict == "ambiguous")


def test_the_judge_and_legacy_verdict_do_not_decide_the_abstention_requirement() -> None:
    case = refusal_case(must_not_include=["999 days"])
    invented = run(case, make_row(case, "Employees typically get 25 days.", judge=True))
    assert invented["overall"]["pass"] is True  # the judge was fooled; strict is not
    assert invented["strict"]["deterministic"] is False
    refused = run(case, make_row(case, "I could not find that.", judge=False))
    assert refused["overall"]["pass"] is False and refused["strict"]["deterministic"] is True


def test_a_value_that_only_echoes_the_question_is_not_an_answer() -> None:
    case = refusal_case(question="What is the 2027 retreat budget?")
    row = run(case, make_row(case, "I could not find a 2027 retreat budget."))
    assert row["abstention"] == "refused"


def test_the_requirement_applies_only_to_cases_that_require_a_refusal() -> None:
    answer = make_case()
    row = run(
        answer, make_row(answer, "22 days.", ((C1, HANDBOOK),), trace_=GOOD_TRACE, ex=execution())
    )
    assert row["abstention"] is None and row["strict"]["deterministic"] is True
    premise = make_case(id="cp1", expected_behavior="correct_premise", must_include=[["22"]])
    row = run(
        premise, make_row(premise, "The premise is wrong; leave is 22 days.", ((C1, HANDBOOK),))
    )
    assert row["abstention"] is None  # a premise correction is an answer, not a refusal
    stopped = base_row(answer)
    stopped.update(cap_stopped=True, error="cap_stopped")
    assert extend_row(answer, stopped, resolved_for(answer))["abstention"] is None
    failed = run(refusal_case(), make_row(refusal_case(), "", error="ChatError<-TimeoutError"))
    assert failed["abstention"] is None and failed["strict"]["deterministic"] is False


def test_a_stated_answer_where_a_refusal_is_required_is_a_fabrication_by_outcome_and_cause() -> (
    None
):
    case = refusal_case(must_not_include=["999 days"])
    row = run(case, make_row(case, "Employees typically get 25 days.", judge=True, ex=execution()))
    assert row["outcome"] == "fabrication"  # the fooled judge does not decide it
    assert row["cause"]["primary"] == "fabrication"
    assert row["strict"]["deterministic"] is False

"""Deterministic context boundaries, not mocked semantic judgments."""

from datetime import UTC, datetime
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.llm.openai_service import OpenAIChatService
from app.retrieval.relationships import select_relationship_evidence
from app.retrieval.types import RetrievedChunk


def chunk(text: str) -> RetrievedChunk:
    return RetrievedChunk(
        uuid4(), uuid4(), uuid4(), "decisions.txt", "text/plain", datetime.now(UTC), 0, text, 1
    )


def test_unsupported_comparison_keeps_only_the_base_question() -> None:
    result = select_relationship_evidence(
        "Which venue is used, and why was it selected over the stadium?",
        [chunk("The library is used because it has accessible entrances.")],
    )
    assert result is not None
    assert result.question == "Which venue is used"
    assert "stadium" in result.limitation and "not establish" in result.limitation
    assert result.passages


@pytest.mark.parametrize("connector", ["instead of", "over"])
def test_explicit_choice_support_is_preserved(connector: str) -> None:
    source = f"The library was chosen {connector} the stadium because it has accessible entrances. A catering plan exists."
    result = select_relationship_evidence(
        "Why was the library chosen over the stadium?", [chunk(source)]
    )
    assert result is not None and not result.limitation
    assert "accessible entrances" in result.passages[1]
    assert "catering" not in result.passages[1]


def test_both_alternatives_present_without_a_choice_are_not_support() -> None:
    result = select_relationship_evidence(
        "Why was the library selected over the stadium?",
        [chunk("The library has accessible entrances. The stadium hosts football.")],
    )
    assert result is not None and not result.passages and result.limitation


def test_condition_selects_linked_sentence_and_excludes_adjacent_procedure() -> None:
    result = select_relationship_evidence(
        "What happens if the access audit fails?",
        [
            chunk(
                "If the access audit fails, opening may move; no new date is currently approved. The evacuation plan is to use the east exit."
            )
        ],
    )
    assert result is not None and not result.limitation
    assert "may move" in result.passages[1] and "currently" in result.passages[1]
    assert "evacuation" not in result.passages[1]


def test_other_condition_is_not_evidence_for_requested_trigger() -> None:
    result = select_relationship_evidence(
        "What happens if catering delivery fails?",
        [chunk("If the access audit fails, opening may move. Catering is ordered.")],
    )
    assert result is not None and not result.passages


@pytest.mark.parametrize(
    "source,supported",
    [
        ("The inspection failed. The festival was delayed.", False),
        ("The inspection caused the festival delay. The evacuation plan exists.", True),
    ],
)
def test_causal_cooccurrence_is_not_a_causal_link(source: str, supported: bool) -> None:
    result = select_relationship_evidence(
        "Did the inspection cause the festival delay?", [chunk(source)]
    )
    assert result is not None
    assert bool(result.passages) is supported
    if supported:
        assert "evacuation" not in result.passages[1]


@pytest.mark.parametrize(
    "question",
    [
        "What database is used?",
        "Which task has the latest deadline?",
        "Who owns testing?",
        "What costs over the budget?",
    ],
)
def test_ordinary_queries_are_unchanged(question: str) -> None:
    assert select_relationship_evidence(question, [chunk("A dated plan exists.")]) is None


@pytest.mark.asyncio
async def test_comparison_cannot_reach_generation_as_an_assumed_fact() -> None:
    service = OpenAIChatService(Settings(demo_mode=False))
    complete = AsyncMock(return_value="The library is used for accessibility [1].")
    service._complete = complete
    answer = await service.generate_grounded_answer(
        "Which venue is used, and why was it chosen over the stadium?",
        [chunk("The library is used because it is accessible.")],
        max_context_chars=12000,
    )
    complete.assert_awaited_once()
    assert complete.await_args is not None
    assert "stadium" not in complete.await_args.args[1]
    assert "not establish" in answer and "stadium" in answer


@pytest.mark.asyncio
async def test_conditional_prompt_has_only_actual_selected_sources() -> None:
    service = OpenAIChatService(Settings(demo_mode=False))
    complete = AsyncMock(return_value="Opening may move [2].")
    service._complete = complete
    answer = await service.generate_grounded_answer(
        "What happens if the access audit fails?",
        [
            chunk("The evacuation plan uses the east exit."),
            chunk(
                "If the access audit fails, opening may move. The evacuation plan uses the east exit."
            ),
        ],
        max_context_chars=12000,
    )
    assert "[2]" in answer
    complete.assert_awaited_once()
    assert complete.await_args is not None
    assert "evacuation" not in complete.await_args.args[1]
    assert "[2] decisions.txt" in complete.await_args.args[1]


@pytest.mark.asyncio
async def test_unsupported_cause_does_not_generate_a_rationale() -> None:
    service = OpenAIChatService(Settings(demo_mode=False))
    complete = AsyncMock(side_effect=AssertionError("No supported causal passage"))
    service._complete = complete
    answer = await service.generate_grounded_answer(
        "Did the inspection cause the festival delay?",
        [chunk("The inspection failed. The festival was delayed.")],
        max_context_chars=12000,
    )
    assert "not establish" in answer
    complete.assert_not_awaited()


def test_same_alternative_does_not_prove_a_different_subjects_choice() -> None:
    result = select_relationship_evidence(
        "Why was the library chosen over the stadium?",
        [chunk("The auditorium was chosen over the stadium because of accessible entrances.")],
    )
    assert result is not None and not result.passages


def test_consequence_wording_selects_only_explicit_conditional_link() -> None:
    result = select_relationship_evidence(
        "Explain the consequences of an access audit failure.",
        [chunk("If the access audit fails, opening may move. The evacuation plan exists.")],
    )
    assert result is not None
    # Missing inflection correspondence must fail closed, never include the unrelated plan.
    assert all("evacuation" not in span for span in result.passages.values())


def test_negated_condition_is_not_matched_to_the_opposite_trigger() -> None:
    result = select_relationship_evidence(
        "What happens if the access audit does not fail?",
        [chunk("If the access audit fails, opening may move.")],
    )
    assert result is not None and not result.passages


def test_partial_alternative_name_does_not_establish_the_requested_choice() -> None:
    result = select_relationship_evidence(
        "Why was the library chosen over the eastern school hall?",
        [chunk("The library was chosen over the western school hall because of accessibility.")],
    )
    assert result is not None and not result.passages


def test_open_cause_lookup_can_use_an_explicit_link() -> None:
    result = select_relationship_evidence(
        "What caused the festival delay?",
        [chunk("The inspection caused the festival delay. The catering plan exists.")],
    )
    assert result is not None and result.passages
    assert "inspection" in result.passages[1] and "catering" not in result.passages[1]


@pytest.mark.parametrize("connector", ["chosen over", "preferred to", "chosen instead of"])
@pytest.mark.parametrize(
    "requested,supported", [("auditorium", True), ("stadium", False), ("gallery", False)]
)
def test_comparison_operand_excludes_later_rationale(
    connector: str, requested: str, supported: bool
) -> None:
    result = select_relationship_evidence(
        f"Why was the library {connector} the {requested}?",
        [chunk(f"The library was {connector} the auditorium because the stadium was closed.")],
    )
    assert result is not None
    assert bool(result.passages) is supported
    assert bool(result.limitation) is not supported
    if supported:
        # The rationale remains available when the actual operand is supported.
        assert "because the stadium was closed" in result.passages[1]


@pytest.mark.parametrize("clause", ["since", "as", "due to", "owing to", "while"])
def test_other_rationale_boundaries_do_not_supply_the_comparator(clause: str) -> None:
    result = select_relationship_evidence(
        "Why was the bus selected over the train?",
        [chunk(f"The bus was selected over the ferry {clause} the train was unavailable.")],
    )
    assert result is not None and not result.passages and result.limitation


@pytest.mark.parametrize(
    "requested,supported", [("auditorium", True), ("stadium", False), ("gallery", False)]
)
def test_replacement_operand_excludes_later_rationale(requested: str, supported: bool) -> None:
    result = select_relationship_evidence(
        f"Has the library replaced the {requested}?",
        [chunk("The library replaced the auditorium because the stadium was closed.")],
    )
    assert result is not None
    assert bool(result.passages) is supported


def test_replacement_requires_the_replacement_connector() -> None:
    result = select_relationship_evidence(
        "Has the library replaced the stadium?",
        [chunk("The library caused damage to the stadium.")],
    )
    assert result is not None and not result.passages

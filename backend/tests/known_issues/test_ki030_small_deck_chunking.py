"""KI-030 (open): in a small multi-slide deck, the slide that answers is buried in unrelated content.

The deck is the generated board update of the evaluation corpus (case ``px03``), read by the product's
own PPTX reader and chunked by ``chunk_text``. It is 560 characters, below the chunk size, so today
the whole deck is one chunk: the chunk that holds the answer ("Signed 6 new clinics in Q3") also holds
an unrelated board decision about hiring. A chunk that is mostly about something else is a weak search
match, which is the registry's symptom.

What is tested is a chunk-level proxy for discoverability, not search itself (that needs real
embeddings and stays the ``px03`` RAG evaluation case): every fact of the deck stays in the chunk text,
and the chunk that holds one slide's fact does not also hold the fact of a slide about something
unrelated. Nothing is said about chunk count, size, boundaries or slide headings, and
``test_guard_the_expectation_is_met_by_a_plain_size_split`` shows an ordinary size split already
meets it, so no particular chunking algorithm is asked for.

Assumption: the fix lives in chunking, which is the direction the registry names. A fix that keeps the
deck whole and improves ranking another way would leave this expected failure in place; the registry
entry and this test would then be replaced, not silently kept.
"""

import pytest

from app.ingestion.chunking import ChunkingConfig, chunk_text
from tests.known_issues import known_issue
from tests.known_issues.test_ki024_file_readers import read

# One distinctive fact per slide; slide 2 answers the question, slide 4 is about hiring.
TITLE_FACT = "Prepared by Elena Costa"  # slide 1
ANSWER_FACT = "Signed 6 new clinics in Q3"  # slide 2
TABLE_FACT = "| Portugal | 4 | 38,000 |"  # slide 3
HIRING_FACT = "approve hiring a second QA engineer"  # slide 4, in the speaker notes
PAIRS = [(ANSWER_FACT, HIRING_FACT), (HIRING_FACT, ANSWER_FACT)]


def deck_chunks(config: ChunkingConfig | None = None) -> list[str]:
    return [chunk.text for chunk in chunk_text(read("board_update_q3.pptx"), config=config)]


def chunks_holding_both(chunks: list[str], fact: str, unrelated: str) -> tuple[int, int]:
    """(chunks holding ``fact``, of those the ones that also hold ``unrelated``)."""
    holding = [chunk for chunk in chunks if fact in chunk]
    return len(holding), len([chunk for chunk in holding if unrelated in chunk])


def test_guard_every_fact_of_the_deck_is_still_in_some_chunk():
    """Passes today; a fix must not drop or cut a fact."""
    joined = "\n".join(deck_chunks())
    for fact in (TITLE_FACT, ANSWER_FACT, TABLE_FACT, HIRING_FACT):
        assert fact in joined


def test_guard_the_expectation_is_met_by_a_plain_size_split():
    """Passes today: the existing chunker, only with a 200-character target, satisfies the
    expectation below, so it is attainable and does not require slide-aware chunking."""
    chunks = deck_chunks(ChunkingConfig(target_size=200, overlap=0))
    for fact in (TITLE_FACT, ANSWER_FACT, TABLE_FACT, HIRING_FACT):
        assert any(fact in chunk for chunk in chunks)
    for fact, unrelated in PAIRS:
        holding, mixed = chunks_holding_both(chunks, fact, unrelated)
        assert holding and not mixed


@known_issue(
    "KI-030", "a small deck is one chunk, so the answering fact is buried in unrelated slides"
)
@pytest.mark.parametrize(("fact", "unrelated"), PAIRS, ids=["answer-vs-hiring", "hiring-vs-answer"])
def test_a_fact_is_not_found_together_with_an_unrelated_slides_fact(fact, unrelated):
    holding, mixed = chunks_holding_both(deck_chunks(), fact, unrelated)
    assert holding
    assert not mixed, f"{mixed} of {holding} chunks holding {fact!r} also hold {unrelated!r}"

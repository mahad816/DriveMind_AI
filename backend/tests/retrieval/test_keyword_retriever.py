"""Tests for keyword full-text retrieval."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import Settings
from app.routing.intent_frame.execution import RetrievalRequest
from app.routing.intent_frame.scope import EligibleCollectionScope
from pydantic import ValidationError
from app.db.enums import DriveFileStatus
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.retrieval.keyword import KeywordRetriever

CHUNK_ID = uuid.uuid4()
DOCUMENT_ID = uuid.uuid4()
DRIVE_FILE_ID = uuid.uuid4()
USER_ID = uuid.uuid4()


def _drive_file(
    status: DriveFileStatus = DriveFileStatus.INDEXED,
) -> DriveFile:
    return DriveFile(
        id=DRIVE_FILE_ID,
        user_id=USER_ID,
        drive_file_id="gdrive-file-1",
        name="materials_notes.txt",
        mime_type="text/plain",
        modified_at=datetime.now(UTC),
        status=status,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _document(status: DriveFileStatus = DriveFileStatus.INDEXED) -> Document:
    document = Document(
        id=DOCUMENT_ID,
        drive_file_id=DRIVE_FILE_ID,
        extracted_text="hello world",
        extracted_text_hash="hash-1",
        page_count=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    document.drive_file = _drive_file(status)
    return document


def _chunk(status: DriveFileStatus = DriveFileStatus.INDEXED) -> Chunk:
    chunk = Chunk(
        id=CHUNK_ID,
        document_id=DOCUMENT_ID,
        chunk_index=0,
        text="keyword hit chunk",
        metadata_json={"extracted_text_hash": "hash-1"},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    chunk.document = _document(status)
    return chunk


@pytest.fixture
def settings() -> Settings:
    return Settings(retrieval_candidate_k=17)


ORIGINAL_IDENTIFYING_TERMS = KeywordRetriever._identifying_terms


async def _every_long_word(self: KeywordRetriever, question: str, request: object) -> list[str]:
    """Stand-in for the file-count query in tests about paths and merging (old meaning)."""
    return [t for t in self._query_terms(question) if len(t) >= 5]


@pytest.fixture(autouse=True)
def _stub_file_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(KeywordRetriever, "_identifying_terms", _every_long_word)


@pytest.fixture
def mock_db() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def retriever(mock_db: AsyncMock, settings: Settings) -> KeywordRetriever:
    return KeywordRetriever(db=mock_db, settings=settings)


@pytest.mark.asyncio
async def test_retrieve_rejects_blank_request(retriever: KeywordRetriever) -> None:
    with pytest.raises(ValidationError):
        await retriever.retrieve(_request("   "))


@pytest.mark.asyncio
async def test_retrieve_returns_keyword_scored_chunks(
    retriever: KeywordRetriever,
    mock_db: AsyncMock,
) -> None:
    # "materials tensile" has long terms (>=5 chars) → FTS + always-on filename = 2 calls.
    mock_db.execute = AsyncMock(
        side_effect=[
            [(CHUNK_ID, 0.77)],  # FTS hit
            [],  # always-on filename: no file matches
        ]
    )
    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[_chunk()])),
    )

    results = await retriever.retrieve(_request("materials tensile"))

    assert len(results) == 1
    assert results[0].chunk_id == CHUNK_ID
    assert results[0].score == 0.77
    assert results[0].primary_source == "keyword"
    assert results[0].source_scores == {"keyword": 0.77}


@pytest.mark.asyncio
async def test_retrieve_drops_missing_chunks_from_hydration(
    retriever: KeywordRetriever,
    mock_db: AsyncMock,
) -> None:
    missing_id = uuid.uuid4()
    mock_db.execute = AsyncMock(return_value=[(CHUNK_ID, 0.77), (missing_id, 0.22)])
    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[_chunk()])),
    )

    results = await retriever.retrieve(_request("materials tensile"))

    assert len(results) == 1
    assert results[0].chunk_id == CHUNK_ID


@pytest.mark.asyncio
async def test_retrieve_drops_keyword_hit_for_skipped_file(
    retriever: KeywordRetriever,
    mock_db: AsyncMock,
) -> None:
    mock_db.execute = AsyncMock(side_effect=[[(CHUNK_ID, 0.77)], []])
    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[_chunk(DriveFileStatus.SKIPPED)])),
    )

    results = await retriever.retrieve(_request("materials tensile"))

    assert results == []


@pytest.mark.asyncio
async def test_candidate_queries_require_indexed_files(
    retriever: KeywordRetriever,
    mock_db: AsyncMock,
) -> None:
    mock_db.execute = AsyncMock(side_effect=[[], [], [], []])

    await retriever._search_hits(
        'find "this is a very specific sentence that appears verbatim"',
        _request('find "this is a very specific sentence that appears verbatim"'),
    )

    assert mock_db.execute.await_count == 4
    for call in mock_db.execute.await_args_list:
        statement = call.args[0]
        assert "drive_files.status" in str(statement)


@pytest.mark.asyncio
async def test_search_hits_uses_candidate_k_limit(
    retriever: KeywordRetriever,
    mock_db: AsyncMock,
) -> None:
    mock_db.execute = AsyncMock(return_value=[])

    await retriever._search_hits("materials science", _request("materials science"))

    statement = mock_db.execute.await_args.args[0]
    assert statement._limit_clause.value == 17


def test_query_terms_normalize_and_deduplicate() -> None:
    assert KeywordRetriever._query_terms("  Tensile, tensile strength!!  ") == [
        "tensile",
        "strength",
    ]


# ── Filename signal detection ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "question",
    [
        "What is in Resume_2024.pdf?",
        "Summarize notes.docx",
        "Read report.txt",
        "open CoreChain_AI.pdf",
        "what does internship_report.pdf say",
    ],
)
def test_has_filename_signal_detects_file_extensions(question: str) -> None:
    assert KeywordRetriever._has_filename_signal(question) is True


@pytest.mark.parametrize(
    "question",
    [
        "What is tensile strength?",
        "Find my latest resume",
        "Summarize my documents",
        "Tell me about CoreChain",
    ],
)
def test_has_filename_signal_false_for_non_file_queries(question: str) -> None:
    assert KeywordRetriever._has_filename_signal(question) is False


@pytest.mark.asyncio
async def test_retrieve_merges_filename_only_hits_when_fts_empty(
    mock_db: AsyncMock,
    settings: Settings,
) -> None:
    """Chunks from a named file must be included even when FTS finds nothing.

    "Resume_2024.pdf" triggers quoted-target + FTS + filename-explicit paths.
    """
    retriever = KeywordRetriever(db=mock_db, settings=settings)

    fn_chunk_id = uuid.uuid4()

    mock_db.execute = AsyncMock(
        side_effect=[
            [(fn_chunk_id,)],  # quoted-target / exact name
            [],  # FTS → empty
            [(fn_chunk_id,)],  # filename-explicit path
        ]
    )
    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[_chunk()])),
    )

    await retriever.retrieve(_request("What is in Resume_2024.pdf?"))

    assert mock_db.execute.await_count == 3


@pytest.mark.asyncio
async def test_retrieve_always_on_filename_runs_for_long_tokens(
    mock_db: AsyncMock,
    settings: Settings,
) -> None:
    """Always-on filename path runs for any query with tokens ≥ 5 chars.

    "tensile" (7) and "strength" (8) are long enough, so 2 execute calls are
    expected even though no file extension is present.
    """
    retriever = KeywordRetriever(db=mock_db, settings=settings)

    mock_db.execute = AsyncMock(side_effect=[[], []])  # FTS + always-on filename

    await retriever.retrieve(_request("What is tensile strength?"))

    assert mock_db.execute.await_count == 2


@pytest.mark.asyncio
async def test_fts_score_kept_when_higher_than_filename_score(
    mock_db: AsyncMock,
    settings: Settings,
) -> None:
    """When a chunk appears in both FTS and filename-only, the higher score wins."""
    retriever = KeywordRetriever(db=mock_db, settings=settings)
    high_fts_score = 0.85

    mock_db.execute = AsyncMock(
        side_effect=[
            [(CHUNK_ID,)],  # quoted-target / exact name
            [(CHUNK_ID, high_fts_score)],  # FTS: high score
            [(CHUNK_ID,)],  # filename-explicit
        ]
    )
    mock_db.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[_chunk()])),
    )

    results = await retriever.retrieve(_request("what is in notes.txt?"))

    assert len(results) == 1
    assert results[0].score == high_fts_score  # FTS score preserved, not overwritten


# ── Phrase search (Phase D) ────────────────────────────────────────────────────


def test_extract_phrase_from_quoted_text() -> None:
    """Quoted phrase of 10+ chars should be extracted."""
    phrase = KeywordRetriever._extract_phrase(
        'which file contains "Connects to a user\'s Google Drive"?'
    )
    assert phrase == "Connects to a user's Google Drive"


def test_extract_phrase_from_cue_this_line() -> None:
    phrase = KeywordRetriever._extract_phrase(
        "which file has this line: Connects to a user's Google Drive and stores metadata"
    )
    assert phrase is not None
    assert "Connects to a user" in phrase


def test_extract_phrase_from_cue_which_file_contains() -> None:
    phrase = KeywordRetriever._extract_phrase(
        "which file contains: The system uses LangGraph for orchestration"
    )
    assert phrase is not None
    assert "LangGraph" in phrase


def test_extract_phrase_returns_none_for_short_quote() -> None:
    """Quotes shorter than 10 chars must not trigger phrase search."""
    # "hello" is 5 chars — well below the 10-char minimum
    phrase = KeywordRetriever._extract_phrase('"hello"')
    assert phrase is None


def test_extract_phrase_returns_none_for_normal_query() -> None:
    """Regular questions without quotes or cues return None."""
    assert KeywordRetriever._extract_phrase("What is tensile strength?") is None
    assert KeywordRetriever._extract_phrase("Find my latest resume") is None
    assert KeywordRetriever._extract_phrase("Summarize my documents") is None


@pytest.mark.asyncio
async def test_phrase_search_runs_when_quoted_phrase_detected(
    mock_db: AsyncMock,
    settings: Settings,
) -> None:
    """Long quoted phrase triggers phrase-search path.

    Query has a quoted token → quoted-target path runs first.
    Then: FTS + always-on filename + phrase = 4 db.execute calls total.
    """
    retriever = KeywordRetriever(db=mock_db, settings=settings)

    mock_db.execute = AsyncMock(
        side_effect=[
            [],  # quoted-target: no exact filename match
            [(CHUNK_ID, 0.3)],  # FTS: low-score hit
            [],  # always-on filename: no match
            [(CHUNK_ID,)],  # phrase ILIKE: same chunk (score 0.6 wins)
        ]
    )
    mock_db.scalars = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[_chunk()])))

    results = await retriever.retrieve(
        _request(
            'Which file contains "Connects to a user\'s Google Drive and stores file metadata"?'
        )
    )

    assert mock_db.execute.await_count == 4
    assert len(results) == 1
    assert results[0].score == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_phrase_search_finds_chunk_when_fts_empty(
    mock_db: AsyncMock,
    settings: Settings,
) -> None:
    """Phrase search must surface a chunk even when FTS returns nothing.

    Quoted token → quoted-target path first, then FTS + always-on filename + phrase = 4 calls.
    """
    retriever = KeywordRetriever(db=mock_db, settings=settings)

    mock_db.execute = AsyncMock(
        side_effect=[
            [],  # quoted-target → empty (long phrase is not a filename)
            [],  # FTS → empty
            [],  # always-on filename → empty
            [(CHUNK_ID,)],  # phrase ILIKE → found
        ]
    )
    mock_db.scalars = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[_chunk()])))

    results = await retriever.retrieve(
        _request('"Connects to a user\'s Google Drive and stores file metadata in PostgreSQL"')
    )

    assert len(results) == 1
    assert results[0].chunk_id == CHUNK_ID
    assert results[0].score == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_phrase_search_not_triggered_without_quotes_or_cue(
    mock_db: AsyncMock,
    settings: Settings,
) -> None:
    """Normal questions without a phrase trigger FTS + always-on filename (2 calls)."""
    retriever = KeywordRetriever(db=mock_db, settings=settings)
    mock_db.execute = AsyncMock(side_effect=[[], []])  # FTS + always-on filename

    await retriever.retrieve(_request("What is tensile strength?"))

    # FTS + always-on filename; phrase path NOT triggered (no quotes/cue)
    assert mock_db.execute.await_count == 2


@pytest.mark.asyncio
async def test_phrase_score_beats_fts_score_for_exact_phrase(
    mock_db: AsyncMock,
    settings: Settings,
) -> None:
    """Phrase hits get _PHRASE_SCORE (0.6); FTS hits get whatever ts_rank_cd returns.

    Quoted token → quoted-target first, then FTS + always-on filename + phrase = 4 calls.
    """
    retriever = KeywordRetriever(db=mock_db, settings=settings)
    low_fts_score = 0.1

    mock_db.execute = AsyncMock(
        side_effect=[
            [],  # quoted-target: no filename match
            [(CHUNK_ID, low_fts_score)],  # FTS: low score
            [],  # always-on filename: no match
            [(CHUNK_ID,)],  # phrase: same chunk, score 0.6 wins
        ]
    )
    mock_db.scalars = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[_chunk()])))

    results = await retriever.retrieve(
        _request('find "this is a very specific sentence that appears verbatim in one document"')
    )

    assert results[0].score == pytest.approx(0.6)


def _request(query: str) -> RetrievalRequest:
    return RetrievalRequest(
        user_id=USER_ID,
        query=query,
        scope=EligibleCollectionScope(),
        candidate_limit=17,
        candidate_policy="LEGACY",
    )


@pytest.mark.asyncio
async def test_candidate_policy_preserves_legacy_merge_and_bounded_tool_order(retriever):
    from app.retrieval.keyword import KeywordHit

    first, second = uuid.UUID(int=1), uuid.UUID(int=2)
    retriever._fts_hits = AsyncMock(return_value=[KeywordHit(first, 0.2)])
    retriever._filename_only_hits_for_terms = AsyncMock(return_value=[KeywordHit(second, 0.85)])
    legacy = _request("materials").model_copy(update={"candidate_limit": 1})
    bounded = legacy.model_copy(update={"candidate_policy": "BOUNDED"})
    assert [h.chunk_id for h in await retriever._search_hits(legacy.query, legacy)] == [
        first,
        second,
    ]
    assert [h.chunk_id for h in await retriever._search_hits(bounded.query, bounded)] == [second]


# ---- which question words count as naming a file ---------------------------------------------------


def _awaited_args(mock: AsyncMock) -> tuple[object, ...]:
    assert mock.await_args is not None
    return tuple(mock.await_args.args)


class _Row:
    def __init__(self, *counts: int) -> None:
        self._counts = counts

    def one(self) -> tuple[int, ...]:
        return self._counts


@pytest.mark.asyncio
async def test_identifying_terms_keeps_words_found_in_few_names_only(
    mock_db: AsyncMock, settings: Settings
) -> None:
    retriever = KeywordRetriever(db=mock_db, settings=settings)
    # candidates are the words of 5+ letters, in question order: company, policy, handbook, document
    mock_db.execute = AsyncMock(return_value=_Row(0, 5, 1, 2))
    found = await ORIGINAL_IDENTIFYING_TERMS(
        retriever, "In the company policy handbook document, how?", _request("x")
    )
    assert found == ["handbook", "document"]  # 0 files: no match; 5 files: generic


@pytest.mark.asyncio
async def test_identifying_terms_makes_no_query_without_long_words(
    mock_db: AsyncMock, settings: Settings
) -> None:
    retriever = KeywordRetriever(db=mock_db, settings=settings)
    mock_db.execute = AsyncMock()
    assert await ORIGINAL_IDENTIFYING_TERMS(retriever, "Who is the lead?", _request("x")) == []
    mock_db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_identifying_terms_limit_comes_from_settings(mock_db: AsyncMock) -> None:
    mock_db.execute = AsyncMock(return_value=_Row(3))
    strict = KeywordRetriever(db=mock_db, settings=Settings(retrieval_name_term_max_files=2))
    loose = KeywordRetriever(db=mock_db, settings=Settings(retrieval_name_term_max_files=3))
    assert await ORIGINAL_IDENTIFYING_TERMS(strict, "policy", _request("x")) == []
    assert await ORIGINAL_IDENTIFYING_TERMS(loose, "policy", _request("x")) == ["policy"]


@pytest.mark.asyncio
async def test_identifying_terms_query_is_owner_scoped_and_counts_distinct_files(
    mock_db: AsyncMock, settings: Settings
) -> None:
    retriever = KeywordRetriever(db=mock_db, settings=settings)
    mock_db.execute = AsyncMock(return_value=_Row(1))
    await ORIGINAL_IDENTIFYING_TERMS(retriever, "handbook", _request("x"))
    sql = str(mock_db.execute.await_args.args[0])
    assert "count(DISTINCT drive_files.id) FILTER" in sql
    assert "drive_files.user_id =" in sql and "drive_files.status =" in sql


@pytest.mark.asyncio
async def test_only_identifying_words_reach_the_name_boost_and_the_name_path(
    mock_db: AsyncMock, settings: Settings
) -> None:
    retriever = KeywordRetriever(db=mock_db, settings=settings)
    retriever._identifying_terms = AsyncMock(return_value=["handbook"])  # type: ignore[method-assign]
    retriever._fts_hits = AsyncMock(return_value=[])  # type: ignore[method-assign]
    retriever._filename_only_hits_for_terms = AsyncMock(return_value=[])  # type: ignore[method-assign]
    await retriever._search_hits("What is in the handbook policy?", _request("x"))
    assert _awaited_args(retriever._fts_hits)[3] == ["handbook"]
    retriever._filename_only_hits_for_terms.assert_awaited_once_with(["handbook"], _request("x"))


@pytest.mark.asyncio
async def test_no_name_path_and_no_boost_when_no_word_identifies_a_file(
    mock_db: AsyncMock, settings: Settings
) -> None:
    retriever = KeywordRetriever(db=mock_db, settings=settings)
    retriever._identifying_terms = AsyncMock(return_value=[])  # type: ignore[method-assign]
    retriever._fts_hits = AsyncMock(return_value=[])  # type: ignore[method-assign]
    retriever._filename_only_hits_for_terms = AsyncMock(return_value=[])  # type: ignore[method-assign]
    await retriever._search_hits("Who is the Security Lead?", _request("x"))
    assert _awaited_args(retriever._fts_hits)[3] == []
    retriever._filename_only_hits_for_terms.assert_not_awaited()


def test_name_boost_expression_is_false_without_terms_and_uses_each_term() -> None:
    assert str(KeywordRetriever._filename_match_expression([])) == "false"
    sql = str(KeywordRetriever._filename_match_expression(["handbook", "roadmap"]))
    assert sql.count("LIKE") == 2 and " OR " in sql

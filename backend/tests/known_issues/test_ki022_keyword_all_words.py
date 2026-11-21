"""KI-022 (open): keyword search needs every question word to be in the chunk.

Against a real PostgreSQL (disposable, isolated schema; skipped without ``SESSION_TEST_DATABASE_URL``).
The sentence is the one the handbook in the evaluation corpus contains. The two queries are the user's
question (case ``sf01``) and the rewrite the tool agent wrote for it (measured, ``docs/KNOWN_ISSUES.md``).
``websearch_to_tsquery`` ANDs the words, and "entitlement" is not in the sentence, so keyword retrieval
returns nothing. The vector cut-off part of KI-022 is fixed; only this keyword part and the agent's own
query writing are open, and the second stays a RAG evaluation case (it needs a model).
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.db.enums import DriveFileStatus
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.retrieval.keyword import KeywordRetriever
from app.routing.intent_frame.execution import RetrievalRequest
from app.routing.intent_frame.scope import EligibleCollectionScope
from tests.known_issues import known_issue
from tests.security.conftest import (
    USER_A,
    pg_engine,  # noqa: F401  # pyright: ignore[reportUnusedImport]  (pytest fixture, by name)
)

HANDBOOK = "employee_handbook.txt"
FILES = {
    HANDBOOK: "Annual leave is 22 working days per calendar year. Sick leave is paid.",
    "expense_policy_v2.txt": "Meals are reimbursed up to 40 USD per day on business trips.",
    "security_policy.txt": "Passwords must be changed every year and never shared.",
    "holiday_calendar_2026.txt": "The office is closed on public holidays listed below.",
}


@pytest.fixture
async def sessions(pg_engine):  # noqa: F811
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with factory.begin() as db:
        for name, body in FILES.items():
            drive_file = DriveFile(
                id=uuid4(),
                user_id=USER_A,
                drive_file_id=f"g-{uuid4()}",
                name=name,
                mime_type="text/plain",
                modified_at=datetime(2026, 6, 1, tzinfo=UTC),
                status=DriveFileStatus.INDEXED,
            )
            db.add(drive_file)
            await db.flush()
            document = Document(
                id=uuid4(),
                drive_file_id=drive_file.id,
                extracted_text=body,
                extracted_text_hash=uuid4().hex,
            )
            db.add(document)
            await db.flush()
            db.add(Chunk(id=uuid4(), document_id=document.id, chunk_index=0, text=body))
        await db.flush()
        await db.execute(text("UPDATE chunks SET search_vector = to_tsvector('english', text)"))
    return factory


async def found_files(sessions, query: str) -> list[str]:
    request = RetrievalRequest(
        user_id=USER_A, query=query, scope=EligibleCollectionScope(), candidate_limit=20
    )
    async with sessions() as db:
        retriever = KeywordRetriever(db, Settings(_env_file=None))  # type: ignore[call-arg]
        hits = await retriever.retrieve(request)
    return [hit.filename for hit in hits]


async def test_guard_a_short_query_with_only_words_from_the_text_finds_the_handbook(sessions):
    """Passes today; a fix (any-word ranking) must keep it."""
    assert HANDBOOK in await found_files(sessions, "annual leave days per year")


@known_issue("KI-022", "keyword search requires every word, so extra words find nothing")
@pytest.mark.parametrize(
    "query",
    [
        "How many days of annual leave do employees get per year?",
        "annual leave entitlement days per year employees get",
    ],
)
async def test_extra_question_words_still_find_the_file_that_answers(sessions, query):
    assert HANDBOOK in await found_files(sessions, query)

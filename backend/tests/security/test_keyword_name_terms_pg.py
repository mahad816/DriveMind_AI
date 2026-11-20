"""File-name words in keyword search, against a real PostgreSQL (disposable, isolated schema).

Regression: every question word of two letters or more used to count when a file name contained it
as a substring, so "is" matched "n-is-t" and every public NIST PDF got a free score boost.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.enums import DriveFileStatus
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.retrieval.keyword import KeywordRetriever
from app.routing.intent_frame.execution import RetrievalRequest
from app.routing.intent_frame.scope import EligibleCollectionScope

from .conftest import USER_A, USER_B

FILLER = "background material about unrelated operations and routine procedures. " * 40


@pytest.fixture
async def sessions(pg_engine):
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with factory.begin() as db:
        files = [
            (USER_A, "expense_policy_v1.txt", "Old expense limits."),
            (USER_A, "expense_policy_v2.txt", "Current expense limits."),
            (USER_A, "travel_policy.txt", "Hotel limits."),
            (USER_A, "security_policy.txt", "Passwords and access rules."),
            (USER_A, "data_retention_policy.txt", "Logs are kept for ninety days."),
            (USER_A, "team_directory.txt", "Daniel Okafor, Security Lead"),
            (USER_A, "cloudhost_contract.txt", "Hosting terms and uptime."),
            # a public document whose NAME contains the letters "is"; one weak mention of the topic
            (USER_A, "nist_sp800_144.pdf", FILLER + "The security lead signs off. " + FILLER),
            # another user's files: must never be counted or returned for user A
            (USER_B, "directory_b.txt", "Security Lead of the other tenant."),
            (USER_B, "cloudhost_b.txt", "Other tenant hosting."),
            (USER_B, "policy_b.txt", "Other tenant policy."),
        ]
        for owner, name, body in files:
            drive_file = DriveFile(
                id=uuid4(),
                user_id=owner,
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


def request(query: str, owner=USER_A) -> RetrievalRequest:
    return RetrievalRequest(
        user_id=owner, query=query, scope=EligibleCollectionScope(), candidate_limit=20
    )


def retriever(db: AsyncSession, **overrides: int) -> KeywordRetriever:
    return KeywordRetriever(db, Settings(_env_file=None, **overrides))  # type: ignore[call-arg]


async def test_only_words_found_in_few_file_names_identify_a_file(sessions):
    async with sessions() as db:
        found = await retriever(db)._identifying_terms(
            "what does the company policy say about cloudhost security directory", request("x")
        )
    # "policy" is in 5 of user A's names, "company"/"about" in none; short words are never candidates
    assert found == ["cloudhost", "security", "directory"]


async def test_the_limit_is_a_setting(sessions):
    async with sessions() as db:
        strict = await retriever(db, retrieval_name_term_max_files=1)._identifying_terms(
            "expense policy", request("x")
        )
        loose = await retriever(db, retrieval_name_term_max_files=5)._identifying_terms(
            "expense policy", request("x")
        )
    assert strict == []  # "expense" is in 2 names, "policy" in 5
    assert loose == ["expense", "policy"]


async def test_another_users_file_names_are_not_counted(sessions):
    async with sessions() as db:
        own = await retriever(db)._identifying_terms("cloudhost directory", request("x"))
        other = await retriever(db)._identifying_terms(
            "cloudhost directory", request("x", owner=USER_B)
        )
        # user B has one "policy_b.txt": identifying for B, while user A has five policy files
        b_policy = await retriever(db)._identifying_terms("policy", request("x", owner=USER_B))
        a_policy = await retriever(db)._identifying_terms("policy", request("x"))
    assert own == ["cloudhost", "directory"] and other == ["cloudhost", "directory"]
    assert b_policy == ["policy"] and a_policy == []


async def test_a_two_letter_word_in_a_file_name_gives_no_boost(sessions):
    async with sessions() as db:
        hits = await retriever(db).retrieve(request("Who is the Security Lead?"))
    score = {h.filename: h.score for h in hits}
    # "security" names exactly one file, so that file keeps its name match
    assert score["security_policy.txt"] == 0.85
    # "is" is inside "nist": the old code added +0.2 here (0.1 -> 0.3); now both are the raw text rank
    assert score["nist_sp800_144.pdf"] == pytest.approx(score["team_directory.txt"], abs=1e-6)
    assert score["nist_sp800_144.pdf"] < 0.2
    assert all(h.filename not in {"directory_b.txt", "policy_b.txt"} for h in hits)


async def test_a_generic_word_does_not_pull_in_every_file_with_it_in_the_name(sessions):
    async with sessions() as db:
        generic = await retriever(db).retrieve(request("tell me about the policy"))
        specific = await retriever(db).retrieve(request("tell me about cloudhost"))
    # 0.85 is the score of the "file name contains the word" path
    assert not [h for h in generic if h.score == 0.85]
    assert [h.filename for h in specific if h.score == 0.85] == ["cloudhost_contract.txt"]

"""What the existing delete and logout actions remove, and what they leave behind (M0 ticket 07, A4).

These tests record FACTS about today's behaviour. They make no privacy claim and do not say
what the behaviour should be: retention is an Owner decision (see the ticket's Findings).
A test named ``..._today`` pins a fact a future change is allowed to change on purpose; when
it does, the ticket's matrix and the docs must be updated in the same change.

Database tests need the disposable PostgreSQL (``SESSION_TEST_DATABASE_URL``) and are skipped
without it. The route inventory and history-bound tests need no database. No Google, OpenAI or
Qdrant call is made.
"""

# ruff: noqa: F811  (fixtures are imported by name and then requested as arguments)
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, text

from app.db.enums import DriveFileStatus
from app.db.models import (
    ApplicationSession,
    Chunk,
    Conversation,
    ConversationTurn,
    Document,
    DriveFile,
    DriveSyncState,
    GoogleOAuthToken,
    IndexingJob,
    PaidQuestionAttempt,
    QueryHistory,
)
from app.main import create_app
from app.schemas.chat import ChatHistoryTurn, ChatRequest
from app.security.principal import VerifiedGoogleIdentity
from app.services.application_session_service import ApplicationSessionService
from app.services.drive_sync_service import DriveSyncService
from app.services.conversation_history import bounded_rewrite_history
from app.services.conversation_repository import ConversationNotFound, ConversationRepository
from app.services.tool_agent_service import bounded_agent_history
from tests.security.conftest import (
    USER_A,
    USER_B,
    pg_engine,  # noqa: F401  # pyright: ignore[reportUnusedImport]  (pytest fixture, by name)
    settings,  # noqa: F401  # pyright: ignore[reportUnusedImport]  (pytest fixture, by name)
)
from tests.security.test_conversation_repository import (
    create,
    reserve,
    world,  # noqa: F401  # pyright: ignore[reportUnusedImport]  (pytest fixture, by name)
)

REPO_ROOT = Path(__file__).resolve().parents[3]

PER_OWNER_TABLES = (
    "conversations",
    "conversation_turns",
    "query_history",
    "drive_files",
    "documents",
    "chunks",
    "google_oauth_tokens",
    "drive_sync_states",
    "indexing_jobs",
    "application_sessions",
    "paid_question_attempts",
)


async def seed_owner(w, owner, label, *, turns="answered"):
    """One owner with a Drive connection, one prepared file and one conversation (no question, an unanswered one, or an answered one)."""
    async with w.sessions.begin() as db:
        db.add(
            GoogleOAuthToken(
                user_id=owner, encrypted_credentials="sealed-envelope", scopes="drive.readonly"
            )
        )
        db.add(DriveSyncState(user_id=owner, changes_page_token="token"))
        db.add(IndexingJob(user_id=owner))
        db.add(PaidQuestionAttempt(owner_id=owner, started_at=datetime.now(UTC)))
        file = DriveFile(
            user_id=owner,
            drive_file_id=f"drive-{label}",
            name=f"{label}.txt",
            mime_type="text/plain",
            modified_at=datetime.now(UTC),
            status=DriveFileStatus.INDEXED,
        )
        db.add(file)
        await db.flush()
        document = Document(
            drive_file_id=file.id, extracted_text=f"secret text {label}", extracted_text_hash="h"
        )
        db.add(document)
        await db.flush()
        db.add(Chunk(document_id=document.id, chunk_index=0, text=f"secret chunk {label}"))
    conversation = await create(w, owner)
    if turns == "none":
        return conversation, None
    turn = await reserve(w, conversation.id, owner=owner)
    if turns == "unanswered":
        return conversation, turn
    async with w.sessions.begin() as db:
        answer = QueryHistory(
            user_id=owner,
            question=f"private question {label}",
            answer=f"private answer {label}",
            citations_json=[{"snippet": f"quoted {label}"}],
        )
        db.add(answer)
        await db.flush()
        await ConversationRepository(db).complete(
            owner,
            conversation.id,
            turn.id,
            execution_id=turn.execution_id,
            result_id=answer.id,
            retrieval_count=1,
        )
    return conversation, turn


async def counts(w, owner):
    """Rows per owner-scoped table, read with plain SQL so no ORM filter can hide a row."""
    async with w.sessions() as db:
        owner_id = str(owner)
        queries = {
            "conversations": "SELECT count(*) FROM conversations WHERE owner_id = :o",
            "conversation_turns": "SELECT count(*) FROM conversation_turns WHERE owner_id = :o",
            "query_history": "SELECT count(*) FROM query_history WHERE user_id = :o",
            "drive_files": "SELECT count(*) FROM drive_files WHERE user_id = :o",
            "documents": (
                "SELECT count(*) FROM documents d JOIN drive_files f ON f.id = d.drive_file_id "
                "WHERE f.user_id = :o"
            ),
            "chunks": (
                "SELECT count(*) FROM chunks c JOIN documents d ON d.id = c.document_id "
                "JOIN drive_files f ON f.id = d.drive_file_id WHERE f.user_id = :o"
            ),
            "google_oauth_tokens": "SELECT count(*) FROM google_oauth_tokens WHERE user_id = :o",
            "drive_sync_states": "SELECT count(*) FROM drive_sync_states WHERE user_id = :o",
            "indexing_jobs": "SELECT count(*) FROM indexing_jobs WHERE user_id = :o",
            "application_sessions": "SELECT count(*) FROM application_sessions WHERE user_id = :o",
            "paid_question_attempts": "SELECT count(*) FROM paid_question_attempts WHERE owner_id = :o",
        }
        assert set(queries) == set(PER_OWNER_TABLES)
        return {name: await db.scalar(text(sql), {"o": owner_id}) for name, sql in queries.items()}


# --- Conversation delete ---------------------------------------------------------------


async def test_deleted_conversation_is_hidden_from_its_owner(world):
    """Guard: after delete the Owner can no longer read or list the conversation or its answers."""
    conversation, _turn = await seed_owner(world, USER_A, "a")
    async with world.sessions.begin() as db:
        await ConversationRepository(db).delete(USER_A, conversation.id, expected_version=1)
    for action in (
        lambda r: r.get(USER_A, conversation.id),
        lambda r: r.turns(USER_A, conversation.id),
        lambda r: r.completed_context(USER_A, conversation.id, 10),
    ):
        with pytest.raises(ConversationNotFound):
            async with world.sessions.begin() as db:
                await action(ConversationRepository(db))
    async with world.sessions.begin() as db:
        assert await ConversationRepository(db).list_owned(USER_A) == []


async def test_conversation_delete_keeps_every_row_today(world):
    """FACT: DELETE /conversations/{id} is a soft delete. It sets ``deleted_at`` and removes nothing.

    The conversation row, its turns (with the original question text), the linked ``query_history``
    row (question, answer, citations) all stay in PostgreSQL. Another owner's data is unchanged.
    """
    conversation, turn = await seed_owner(world, USER_A, "a")
    await seed_owner(world, USER_B, "b")
    assert turn is not None
    before_a, before_b = await counts(world, USER_A), await counts(world, USER_B)
    async with world.sessions.begin() as db:
        await ConversationRepository(db).delete(USER_A, conversation.id, expected_version=1)

    assert await counts(world, USER_A) == before_a
    assert await counts(world, USER_B) == before_b
    async with world.sessions() as db:
        row = await db.get(Conversation, conversation.id)
        assert row is not None and row.deleted_at is not None
        kept_turn = await db.get(ConversationTurn, turn.id)
        assert kept_turn is not None and kept_turn.original_question == "Original question"
        history = await db.get(QueryHistory, kept_turn.query_history_id)
        assert history is not None
        assert history.question == "private question a"
        assert history.answer == "private answer a"
        assert history.citations_json == [{"snippet": "quoted a"}]


async def test_deleted_conversation_result_is_no_longer_replayable(world):
    """FACT: the only owner-facing way to read a stored answer goes through a visible conversation.

    ``ConversationRepository.result`` (used to replay a request) refuses a deleted conversation, so
    the retained ``query_history`` row is unreachable through the repository once deleted.
    """
    conversation, turn = await seed_owner(world, USER_A, "a")
    assert turn is not None
    async with world.sessions.begin() as db:  # positive control: visible before the delete
        before = await ConversationRepository(db).result(
            USER_A, conversation.id, turn.client_request_id
        )
        assert before is not None and before.answer == "private answer a"
    async with world.sessions.begin() as db:
        await ConversationRepository(db).delete(USER_A, conversation.id, expected_version=1)
    with pytest.raises(ConversationNotFound):
        async with world.sessions.begin() as db:
            await ConversationRepository(db).result(USER_A, conversation.id, turn.client_request_id)


# --- Logout ----------------------------------------------------------------------------


async def test_logout_revokes_only_the_session_row_today(world, settings):
    """FACT: logout (``ApplicationSessionService.revoke``) sets ``revoked_at`` on one session row.

    It deletes no session row and removes no credential, Drive metadata, document, chunk, job or
    conversation. The stored Google credential is untouched, so the Drive connection survives logout.
    """
    await seed_owner(world, USER_A, "a")
    async with world.sessions() as db:
        session = await db.scalar(
            select(ApplicationSession).where(ApplicationSession.user_id == USER_A)
        )
        assert session is not None and session.revoked_at is None
        session_id = session.id
    before = await counts(world, USER_A)

    async with world.sessions.begin() as db:
        issued = await ApplicationSessionService(db, settings).issue_google(
            VerifiedGoogleIdentity(subject="verified-subject-a")
        )
    async with world.sessions.begin() as db:
        assert await ApplicationSessionService(db, settings).revoke(
            issued.credential.get_secret_value()
        )

    after = await counts(world, USER_A)
    assert after.pop("application_sessions") == before.pop("application_sessions") + 1
    assert after == before  # every other table: identical
    async with world.sessions() as db:
        revoked = await db.get(ApplicationSession, issued.session_id)
        assert revoked is not None and revoked.revoked_at is not None
        untouched = await db.get(ApplicationSession, session_id)
        assert untouched is not None and untouched.revoked_at is None  # another session still valid
        assert await db.scalar(select(func.count()).select_from(GoogleOAuthToken)) == 1


# --- Account row deletion (no code path does this; the database rule is recorded) -------------


async def delete_user(w, owner):
    async with w.sessions.begin() as db:
        await db.execute(text("DELETE FROM users WHERE id = :u"), {"u": str(owner)})


async def test_deleting_a_user_who_never_asked_a_question_cascades_to_every_owner_table(world):
    """Guard (FACT about the schema): no application code deletes a ``users`` row.

    If an operator did, every per-owner PostgreSQL table in the inventory is emptied by
    ``ON DELETE CASCADE`` for that owner only, provided the owner never submitted a question
    (any conversation turn blocks it, see KI-033 in tests/known_issues). Qdrant vectors and browser storage are NOT reached by this.
    """
    await seed_owner(world, USER_A, "a", turns="none")
    await seed_owner(world, USER_B, "b")
    before_b = await counts(world, USER_B)
    seeded = await counts(world, USER_A)
    assert seeded.pop("query_history") == 0 and seeded.pop("conversation_turns") == 0
    assert all(n > 0 for n in seeded.values())
    await delete_user(world, USER_A)
    assert set((await counts(world, USER_A)).values()) == {0}
    assert await counts(world, USER_B) == before_b


# --- A file removed from Drive -----------------------------------------------------------------


async def test_file_removed_in_drive_is_marked_skipped_and_nothing_is_deleted_today(
    world, settings
):
    """FACT: when Drive reports a file removed, sync only sets the file to SKIPPED.

    The ``drive_files`` row, its ``documents`` row (the full extracted text) and its ``chunks`` stay in
    PostgreSQL. (The matching Qdrant points are not touched either: sync has no vector-store access;
    that part is code reading, not tested here.)
    """
    await seed_owner(world, USER_A, "a")
    before = await counts(world, USER_A)
    async with world.sessions.begin() as db:
        # Private method on purpose: the public sync needs a Drive client, which this audit avoids.
        assert await DriveSyncService(db, settings)._mark_file_removed(USER_A, "drive-a") == 1
    assert await counts(world, USER_A) == before
    async with world.sessions() as db:
        file = await db.scalar(select(DriveFile).where(DriveFile.user_id == USER_A))
        assert file is not None and file.status == DriveFileStatus.SKIPPED
        document = await db.scalar(
            select(Document).join(DriveFile).where(DriveFile.user_id == USER_A)
        )
        assert document is not None and document.extracted_text == "secret text a"


# --- Route inventory (no database) -----------------------------------------------------------


def test_only_one_delete_route_exists_and_none_is_named_disconnect_revoke_or_purge():
    """Search method for 'is there a backend Disconnect / Revoke / Delete-stored-data path?'.

    Lists every route of the real application and checks: (1) the only HTTP DELETE route is the
    conversation soft delete; (2) no route path contains disconnect, revoke, purge, erase, wipe,
    account or a delete-data wording. A pass is "no deletion path found", not proof of absence.
    """
    # With the pinned FastAPI, ``app.routes`` holds a lazy router, so a loop over it would check
    # nothing (see test_route_authentication_inventory.py). The OpenAPI document lists every route.
    paths = create_app().openapi()["paths"]
    assert len(paths) > 20 and "/api/v1/conversations/{conversation_id}" in paths
    deletes = sorted(path for path, ops in paths.items() if "delete" in ops)
    assert deletes == ["/api/v1/conversations/{conversation_id}"]
    words = ("disconnect", "revoke", "purge", "erase", "wipe", "account", "delete-data", "forget")
    offenders = [path for path in paths if any(w in path.lower() for w in words)]
    assert offenders == []


def test_disconnect_help_text_is_a_link_to_google_not_a_backend_call():
    """The one place the frontend mentions Revoke points the Owner to Google (no backend call)."""
    # Marginalia replaced user-language.ts; preserve the security contract on the actual control.
    source = (REPO_ROOT / "frontend/components/settings/settings-view.tsx").read_text()
    opening = '<a href="https://myaccount.google.com/permissions"'
    assert opening in source
    anchor = source.split(opening, 1)[1].split("</a>", 1)[0]
    assert "Manage access in your Google Account" in anchor
    assert "onClick" not in anchor
    assert 'target="_blank"' in anchor and 'rel="noreferrer"' in anchor


# --- History the answering path receives (no database) --------------------------------------


def turn(role, n):
    return ChatHistoryTurn(role=role, text="x" * n)


def test_rewrite_and_agent_history_is_at_most_six_messages_and_6000_characters():
    history = [turn("user" if i % 2 == 0 else "assistant", 2000) for i in range(8)]
    selected = bounded_rewrite_history(history)
    assert len(selected) == 3  # 6000 characters is reached after three 2000-character messages
    assert sum(len(m["text"]) for m in selected) == 6000
    short = [turn("user" if i % 2 == 0 else "assistant", 10) for i in range(8)]
    assert len(bounded_rewrite_history(short)) == 6  # only the last six messages are considered
    assert len(bounded_agent_history(short)) == 6


def test_chat_request_accepts_at_most_eight_history_messages_and_24000_characters():
    cid = str(uuid4())
    ok = [turn("user", 1) for _ in range(8)]
    ChatRequest(question="q", conversation_id=cid, history=ok)
    with pytest.raises(ValidationError):
        ChatRequest(question="q", conversation_id=cid, history=ok + ok[:1])
    big = [turn("user", 8000) for _ in range(4)]
    with pytest.raises(ValidationError):
        ChatRequest(question="q", conversation_id=cid, history=big)

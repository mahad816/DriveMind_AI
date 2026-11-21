"""KI-033 (open): an owner who has submitted a question cannot be deleted from ``users``.

M0 ticket 07 (audit area A4). No application code deletes a ``users`` row today, so this is not
reachable by a user. It matters for the planned "Delete stored data" and any account removal (M7):
``ON DELETE CASCADE`` is meant to empty every per-owner table, but two foreign keys out of
``conversation_turns`` have no ON DELETE rule (``fk_turns_session_owner`` to ``application_sessions``,
``fk_turns_result_owner`` to ``query_history``), so PostgreSQL refuses the whole delete as soon as the
owner has one turn. The passing guard for the owner with no turn is in
``tests/security/test_conversation_deletion_privacy.py``.

Needs the disposable PostgreSQL (``SESSION_TEST_DATABASE_URL``); skipped without it. No external call.
"""

# ruff: noqa: F811  (fixtures are imported by name and then requested as arguments)
import pytest
from sqlalchemy.exc import IntegrityError

from tests.known_issues import known_issue
from tests.security.conftest import (
    USER_A,
    pg_engine,  # noqa: F401  # pyright: ignore[reportUnusedImport]  (pytest fixture, by name)
    settings,  # noqa: F401  # pyright: ignore[reportUnusedImport]  (pytest fixture, by name)
)
from tests.security.test_conversation_deletion_privacy import counts, delete_user, seed_owner
from tests.security.test_conversation_repository import (
    world,  # noqa: F401  # pyright: ignore[reportUnusedImport]  (pytest fixture, by name)
)


@known_issue("KI-033", "a user who has submitted a question cannot be deleted")
@pytest.mark.parametrize("turns", ["answered", "unanswered"])
async def test_user_who_has_asked_a_question_can_be_deleted(world, turns):
    """KI-033: two foreign keys out of ``conversation_turns`` have no ON DELETE rule.

    ``fk_turns_session_owner`` (to ``application_sessions``) blocks any owner with a turn, answered or
    not; ``fk_turns_result_owner`` (to ``query_history``) blocks an owner with an answered turn.
    Deleting the owner cascades to those tables while a turn still points at them, so PostgreSQL
    refuses with a foreign-key violation and the whole delete is rolled back. Correct
    behaviour for any future "Delete stored data" or account removal: the delete succeeds and the
    owner's rows are gone.
    """
    await seed_owner(world, USER_A, "a", turns=turns)
    refused: str | None = None
    try:
        await delete_user(world, USER_A)
    except IntegrityError as exc:
        refused = str(exc.orig)
    # Only a refusal by one of the two named foreign keys is the known defect; any other
    # IntegrityError is a different problem and must not hide behind the expected failure.
    if refused is not None:
        assert "fk_turns_session_owner" in refused or "fk_turns_result_owner" in refused, refused
    assert refused is None, "DELETE FROM users was refused by a conversation_turns foreign key"
    assert set((await counts(world, USER_A)).values()) == {0}

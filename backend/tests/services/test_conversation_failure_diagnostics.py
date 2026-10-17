"""Exercise real submit/cleanup boundaries with in-memory SQL/provider doubles."""

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.llm.base import ChatCitationValidationError, ChatConfigurationError, ChatError
from app.services import conversation_chat_service as module


@pytest.fixture
def execution(monkeypatch):
    db = MagicMock()
    db.execute = AsyncMock()

    @asynccontextmanager
    async def transaction(*args, **kwargs):
        yield db

    db.begin = transaction
    principal = SimpleNamespace(corpus_user_id=uuid4(), session_id=uuid4())
    turn = SimpleNamespace(id=uuid4(), execution_id=uuid4(), history_end_sequence=0)
    repo = SimpleNamespace(
        reserve=AsyncMock(return_value=SimpleNamespace(turn=turn, replayed=False)),
        _execution=AsyncMock(
            return_value=(None, SimpleNamespace(initiating_session_id=principal.session_id), None)
        ),
        complete=AsyncMock(),
        fail=AsyncMock(),
        interrupt_attempt=AsyncMock(),
    )
    monkeypatch.setattr(module, "ConversationRepository", lambda db: repo)
    monkeypatch.setattr(
        module,
        "ConversationService",
        lambda db: SimpleNamespace(transaction=transaction, _live_session=AsyncMock()),
    )
    # Serialization is covered by mounted API tests; isolate execution here.
    monkeypatch.setattr(module, "ConversationSubmission", lambda **kw: SimpleNamespace(**kw))
    rag = SimpleNamespace(
        persist_query_history=False,
        ask=AsyncMock(
            return_value=SimpleNamespace(
                question="PRIVATE_QUESTION",
                answer="PRIVATE_ANSWER",
                citations=[],
                retrieval_count=1,
                user_id=principal.corpus_user_id,
            )
        ),
    )
    service = object.__new__(module.ConversationChatService)
    service.db = db
    service.settings = None
    service.sessions = transaction
    service.read_sessions = transaction
    service.rag_factory = lambda db, settings: rag
    service.generation_timeout = 1
    service.execution_seconds = 2
    service._context = AsyncMock(return_value=([], True))
    service._citations = AsyncMock()
    service._status = AsyncMock(
        side_effect=[
            SimpleNamespace(status=module.TurnStatus.RUNNING),
            SimpleNamespace(status=module.TurnStatus.FAILED),
        ]
    )
    body = SimpleNamespace(
        client_request_id=uuid4(),
        question="PRIVATE_QUESTION",
        expected_content_version=0,
    )
    return SimpleNamespace(
        service=service,
        repo=repo,
        rag=rag,
        principal=principal,
        turn=turn,
        cid=uuid4(),
        body=body,
    )


@pytest.mark.parametrize(
    "fault,stage,category",
    [
        ("citation", "citation_validation", "CITATION_VALIDATION_FAILED"),
        ("chat", "rag_execution", "CHAT_GENERATION_ERROR"),
        ("configuration", "rag_execution", "CHAT_CONFIGURATION_ERROR"),
        ("unknown", "rag_execution", "UNEXPECTED_ERROR"),
        ("publication", "result_publication", "DATABASE_ERROR"),
        ("authority", "source_authorization", "SOURCE_AUTHORIZATION_CHANGED"),
        ("history", "history_loading", "DATABASE_ERROR"),
        ("validation", "result_validation", "UNEXPECTED_ERROR"),
        ("timeout", "rag_execution", "EXECUTION_TIMEOUT"),
    ],
)
async def test_failure_diagnostics_preserve_cleanup_and_privacy(
    execution,
    caplog,
    fault,
    stage,
    category,
):
    x = execution
    if fault == "timeout":
        x.service._status.side_effect = [
            SimpleNamespace(status=module.TurnStatus.RUNNING),
            SimpleNamespace(status=module.TurnStatus.INTERRUPTED),
        ]
    secret = "PRIVATE_QUESTION PRIVATE_ANSWER PRIVATE_DOCUMENT PRIVATE_PROMPT API_KEY OAUTH_TOKEN"
    if fault == "publication":
        x.repo.complete.side_effect = SQLAlchemyError(secret)
    elif fault == "authority":
        x.service._citations.side_effect = module.CitationAuthorityLost(secret)
    elif fault == "history":
        x.service._context.side_effect = SQLAlchemyError(secret)
    elif fault == "validation":
        x.rag.ask.return_value.answer = ""
    else:
        error = {
            "citation": ChatCitationValidationError,
            "chat": ChatError,
            "configuration": ChatConfigurationError,
            "unknown": RuntimeError,
            "timeout": TimeoutError,
        }[fault]
        x.rag.ask.side_effect = error(secret)

    with caplog.at_level(logging.WARNING, logger=module.__name__):
        response, status = await x.service.submit(x.principal, x.cid, x.body)

    records = [r for r in caplog.records if r.name == module.__name__]
    assert len(records) == 1
    record = records[0]
    data = json.loads(record.getMessage().split(" ", 1)[1])
    assert set(data) == {"turn_id", "stage", "exception_category", "failed_at"}
    assert data["turn_id"] == str(x.turn.id)
    assert data["stage"] == stage
    assert data["exception_category"] == category
    assert datetime.fromisoformat(data["failed_at"]).utcoffset().total_seconds() == 0
    assert record.exc_info is None and record.stack_info is None
    assert all(word not in caplog.text for word in secret.split())
    assert status == 503
    assert response.turn.status == (
        module.TurnStatus.INTERRUPTED if fault == "timeout" else module.TurnStatus.FAILED
    )
    if fault == "timeout":
        x.repo.interrupt_attempt.assert_awaited_once()
        assert x.repo.interrupt_attempt.call_args.kwargs["error_code"] == "GENERATION_TIMEOUT"
        x.repo.fail.assert_not_awaited()
    else:
        x.repo.fail.assert_awaited_once()
        args = x.repo.fail.call_args
        assert args.args[:3] == (x.principal.corpus_user_id, x.cid, x.turn.id)
        assert args.kwargs["execution_id"] == x.turn.execution_id
        assert args.kwargs["error_code"] == (
            "SOURCE_CHANGED" if fault == "authority" else "GENERATION_OR_STORAGE_FAILED"
        )


async def test_success_does_not_emit_failure_diagnostics(execution, caplog):
    x = execution
    x.service._status.side_effect = [
        SimpleNamespace(status=module.TurnStatus.RUNNING),
        SimpleNamespace(status=module.TurnStatus.COMPLETED),
    ]
    response, status = await x.service.submit(x.principal, x.cid, x.body)
    assert status == 200 and response.turn.status == module.TurnStatus.COMPLETED
    assert not [r for r in caplog.records if r.name == module.__name__]
    x.repo.fail.assert_not_awaited()
    x.repo.complete.assert_awaited_once()

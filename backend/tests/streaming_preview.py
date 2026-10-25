"""Deterministic LOCAL fixture, not a production application or authentication service.

Run: python -m tests.streaming_preview (loopback :8001). No SQL or provider network.
Uses the production SSE route, native streaming adapter, tool graph and finalizer.
Its session, inventory and turn persistence are explicitly in-memory fixtures.
"""

import asyncio
import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.core import config

from app.api.conversations import (
    router,
    get_conversation_chat_service,
    require_conversation_mutation,
)
from app.agents.tool_rag.agent_service import ToolRagAgentService
from app.llm.openai_agent_service import OpenAIAgentChatService
from app.schemas.conversation import ConversationSubmission
from app.services.chat_stream import emit
from tests.test_chat_streaming import ProviderStream, tool_stream
from tests.agents.tool_rag.test_tool_execution import USER, InventoryDB, chunk, file

SETTINGS = config.Settings(
    _env_file=None,
    app_env="local",
    demo_mode=False,
    chat_streaming_enabled=True,
    tool_rag_agent_enabled=True,
    indexing_enabled=False,
    openai_api_key="",
    database_url="postgresql+asyncpg://drivemind:drivemind@127.0.0.1:5432/drivemind",
)
ROOT = Path(__file__).resolve().parents[2]
DTO = json.loads((ROOT / "frontend/lib/api/fixtures/conversation-backend-dto.json").read_text())


def NOW():
    return datetime.now(UTC).isoformat()


META = {**DTO["metadata"], "title": "Local streaming fixture", "content_version": 0}
TURNS: dict[str, dict] = {}


class SlowStream(ProviderStream):
    async def iterate(self):
        async for value in super().iterate():
            await asyncio.sleep(0.12)  # Fixture pacing only; production uses OpenAI deltas.
            yield value


class FixtureService:
    settings = SETTINGS

    async def submit(self, principal, cid, body):
        key = str(body.client_request_id)
        if key in TURNS:
            turn = TURNS[key]
            return ConversationSubmission(turn=turn, replayed=True), 202 if turn[
                "status"
            ] == "RUNNING" else 200
        turn = {
            **copy.deepcopy(DTO["submission"]["turn"]),
            "id": str(uuid4()),
            "client_request_id": key,
            "question": body.question,
            "sequence": len(TURNS) + 1,
            "created_at": NOW(),
            "updated_at": NOW(),
            "status": "RUNNING",
            "answer": None,
            "citations": [],
            "query_id": None,
            "finished_at": None,
            "error_code": None,
            "retrieval_count": 0,
            "execution_expired": False,
        }
        TURNS[key] = turn
        await emit(
            "accepted", ConversationSubmission(turn=turn, replayed=False).model_dump(mode="json")
        )
        try:
            text = "The indexed document contains authoritative refund policy text. [source_1]"
            chunks = [({"content": word + " "}, None) for word in text.split(" ")]
            chunks.append(({}, "stop"))
            if "fail" in body.question.lower():
                chunks[-1] = ({"content": " [source_999]"}, "stop")
            provider = SimpleNamespace(
                chat=SimpleNamespace(
                    completions=SimpleNamespace(
                        create=AsyncMock(side_effect=[tool_stream(), SlowStream(chunks)])
                    )
                )
            )
            provider.with_options = lambda **options: provider
            retriever = AsyncMock()
            retriever.retrieve.return_value = [chunk()]
            state = await ToolRagAgentService(
                OpenAIAgentChatService(SETTINGS, client=provider)
            ).run(body.question, user_id=USER, db=InventoryDB([file()]), retriever=retriever)
            if state["failure"]:
                turn.update(status="FAILED", error_code="TURN_FAILED", finished_at=NOW())
                return ConversationSubmission(turn=turn, replayed=False), 503
            await emit("state", {"phase": "validating"})
            turn.update(
                status="COMPLETED",
                answer=state["final_answer"],
                query_id=str(uuid4()),
                citations=[c.model_dump(mode="json") for c in state["citations"]],
                retrieval_count=state["retrieval_count"],
                finished_at=NOW(),
            )
            META["content_version"] += 1
            return ConversationSubmission(turn=turn, replayed=False), 200
        except asyncio.CancelledError:
            turn.update(status="INTERRUPTED", error_code="TURN_INTERRUPTED", finished_at=NOW())
            raise


app = FastAPI(title="DriveMind LOCAL synthetic streaming acceptance fixture")


@app.middleware("http")
async def fixture_api(request: Request, call_next):
    path = request.url.path
    if path.endswith("/turns/stream"):
        return await call_next(request)
    if request.method not in {"GET", "POST"}:
        return JSONResponse({"detail": "Fixture operation unavailable"}, status_code=403)
    if path == "/api/v1/auth/session":
        data = {"kind": "GOOGLE_ACCOUNT", "user_id": str(USER), "csrf_token": "local-fixture-csrf"}
    elif path == "/api/v1/conversations" and request.method == "GET":
        data = {"conversations": [META], "next_cursor": None}
    elif path == "/api/v1/conversations" and request.method == "POST":
        return JSONResponse(META, status_code=201)
    elif path == f"/api/v1/conversations/{META['id']}":
        limit = int(request.query_params.get("limit", "50"))
        before = int(request.query_params.get("before_sequence", "9007199254740991"))
        all_turns = [t for t in TURNS.values() if t["sequence"] < before]
        selected = all_turns[-limit:]
        data = {
            "conversation": META,
            "turns": [{k: v for k, v in t.items() if k != "execution_expired"} for t in selected],
            "next_before_sequence": selected[0]["sequence"] if len(all_turns) > limit else None,
        }
    elif "/turns/" in path:
        data = next((t for t in TURNS.values() if t["id"] == path.rsplit("/", 1)[1]), None)
        if not data:
            return JSONResponse({"detail": "Not found"}, status_code=404)
    elif path == "/api/v1/files":
        data = {
            "files": [
                {
                    "id": str(UUID(int=10)),
                    "user_id": str(USER),
                    "drive_file_id": "synthetic-only",
                    "name": "Refund policy — local fixture.pdf",
                    "mime_type": "application/pdf",
                    "folder_path": "/Local fixtures",
                    "status": "indexed",
                    "modified_at": NOW(),
                    "indexed_at": NOW(),
                    "created_at": NOW(),
                    "updated_at": NOW(),
                }
            ],
            "total": 1,
        }
    elif path in {"/api/v1/auth/status", "/api/v1/auth/drive/status"}:
        data = {"connected": False, "user_id": str(USER), "scopes": [], "demo_mode": False}
    elif path == "/api/v1/index/status":
        data = {"job": None, "demo_mode": False}
    elif path.startswith("/api/v1/sources/"):
        data = {"detail": "This synthetic preview does not provide document source content."}
        return JSONResponse(data, status_code=404)
    elif path == "/api/v1/health":
        data = {"status": "ok", "fixture": True, "paid_requests": 0}
    else:
        return JSONResponse({"detail": "Fixture operation unavailable"}, status_code=403)
    return JSONResponse(data, headers={"Cache-Control": "no-store"})


async def fixture_principal(request: Request):
    if request.headers.get("x-csrf-token") != "local-fixture-csrf":
        raise HTTPException(403, "Fixture CSRF token required")
    return SimpleNamespace(corpus_user_id=USER)


app.include_router(router, prefix="/api/v1")
app.dependency_overrides[config.get_settings] = lambda: SETTINGS
app.dependency_overrides[get_conversation_chat_service] = FixtureService
app.dependency_overrides[require_conversation_mutation] = fixture_principal

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001)

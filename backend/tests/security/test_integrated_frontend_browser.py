"""Opt-in real FastAPI/PostgreSQL to Next.js browser contract smoke; synthetic providers only."""

import asyncio
import os
import socket
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import uvicorn

from app.api.index import get_drive_sync_service
from app.db.enums import DriveFileStatus
from app.db.models import Chunk, Document, DriveFile
from app.schemas.query import CitationItem
from .conftest import USER_A
from .test_conversation_chat import api, chat, world

__all__ = ["api", "chat", "world"]


@pytest.mark.skipif(
    not os.environ.get("INTEGRATION_BROWSER_APP"), reason="opt-in Next.js browser smoke"
)
async def test_nextjs_with_real_fastapi_contracts(api, chat):
    async with api.world.sessions.begin() as db:
        file = DriveFile(
            user_id=USER_A,
            drive_file_id="synthetic-google-id",
            name="Integration.txt",
            mime_type="text/plain",
            modified_at=datetime.now(UTC),
            status=DriveFileStatus.INDEXED,
        )
        db.add(file)
        await db.flush()
        document = Document(
            drive_file_id=file.id,
            extracted_text="Synthetic integrated evidence.",
            extracted_text_hash="synthetic",
        )
        db.add(document)
        await db.flush()
        chunk = Chunk(document_id=document.id, chunk_index=0, text="Synthetic integrated evidence.")
        db.add(chunk)
        await db.flush()
        chat.answer = "Synthetic integrated answer [1]."
        chat.citations = [
            CitationItem(
                chunk_id=chunk.id, drive_file_id=file.id, filename=file.name, snippet=chunk.text
            )
        ]
    api.app.dependency_overrides[get_drive_sync_service] = lambda: SimpleNamespace(
        is_connected=AsyncMock(return_value=True)
    )
    api.app.state.indexing_admission_ready = False
    api.app.state.indexing_supervisor = None
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(api.app, log_level="error", lifespan="off", access_log=False)
    )
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(15):
            while not server.started:
                if task.done():
                    await task
                await asyncio.sleep(0.01)
        env = dict(
            os.environ,
            E2E_APP=os.environ["INTEGRATION_BROWSER_APP"],
            E2E_FASTAPI=f"http://127.0.0.1:{port}",
            E2E_FASTAPI_COOKIE=api.headers[USER_A]["Cookie"],
            E2E_FASTAPI_ORIGIN=api.settings.frontend_url,
        )
        process = await asyncio.create_subprocess_exec(
            "node",
            "e2e/journeys/fastapi.mjs",
            cwd=Path(__file__).resolve().parents[3] / "frontend",
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            async with asyncio.timeout(120):
                output, _ = await process.communicate()
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        assert process.returncode == 0, output.decode()
        assert len(chat.calls) == 1
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 15)
        sock.close()

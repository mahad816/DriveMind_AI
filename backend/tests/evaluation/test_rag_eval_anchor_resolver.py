"""The anchor/chunk resolver against a disposable PostgreSQL schema (no provider, no Qdrant).

Skipped unless ``SESSION_TEST_DATABASE_URL`` names an isolated loopback database whose name starts with
``drivemind_session_test`` (the convention of ``tests/security``). Each test builds its own throwaway
schema containing only the four tables the resolver reads, and drops it afterwards.
"""

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.db.models  # noqa: F401  (registers every mapped class so relationships resolve)
from app.db.base import Base
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.db.models.user import User
from evaluation.rag_eval.anchors import load_chunks, load_file_chunks, map_case_anchors

OWNER, STRANGER = uuid.UUID(int=1), uuid.UUID(int=2)
TABLES = ["users", "drive_files", "documents", "chunks"]


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    raw = os.environ.get("SESSION_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("SESSION_TEST_DATABASE_URL must name an isolated local test database")
    url = make_url(raw)
    if (
        url.drivername != "postgresql+asyncpg"
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or not (url.database or "").startswith("drivemind_session_test")
    ):
        pytest.fail("Refusing a non-isolated PostgreSQL test database", pytrace=False)
    schema = "anchor_test_" + uuid.uuid4().hex
    engine = create_async_engine(
        url, poolclass=NullPool, connect_args={"server_settings": {"search_path": schema}}
    )
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.run_sync(
                lambda c: Base.metadata.create_all(
                    c, tables=[Base.metadata.tables[t] for t in TABLES]
                )
            )
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


async def add_file(
    db: AsyncSession, owner: uuid.UUID, name: str, chunks: list[str]
) -> list[uuid.UUID]:
    file = DriveFile(
        user_id=owner,
        drive_file_id=f"{owner}-{name}",
        name=name,
        mime_type="text/plain",
        modified_at=datetime.now(UTC),
    )
    db.add(file)
    await db.flush()
    document = Document(
        drive_file_id=file.id, extracted_text=" ".join(chunks), extracted_text_hash="h"
    )
    db.add(document)
    await db.flush()
    ids = []
    for index, body in enumerate(chunks):
        chunk = Chunk(document_id=document.id, chunk_index=index, text=body)
        db.add(chunk)
        await db.flush()
        ids.append(chunk.id)
    return ids


async def test_the_resolver_returns_chunks_in_order_with_owner_and_file_name(
    db: AsyncSession,
) -> None:
    for number, owner in ((1, OWNER), (2, STRANGER)):
        db.add(User(id=owner, email=f"u{number}@example.invalid", google_id=f"g{number}"))
    await db.flush()
    mine = await add_file(
        db, OWNER, "handbook.txt", ["Leave is 22 days.", "Remote work needs approval."]
    )
    theirs = await add_file(db, STRANGER, "handbook.txt", ["Foreign copy of the same name."])
    await db.commit()

    by_file = await load_file_chunks(db, OWNER, ["handbook.txt", "absent.txt"])
    assert by_file == {
        "handbook.txt": [
            (str(mine[0]), "Leave is 22 days."),
            (str(mine[1]), "Remote work needs approval."),
        ]
    }  # only the owner's file, in chunk order; a missing name is simply absent

    found = await load_chunks(db, [str(mine[0]), str(theirs[0]), "not-a-uuid", str(uuid.uuid4())])
    assert set(found) == {str(mine[0]), str(theirs[0])}  # malformed and unknown identifiers vanish
    assert (
        found[str(mine[0])].owner_id == str(OWNER)
        and found[str(mine[0])].file_name == "handbook.txt"
    )
    assert found[str(theirs[0])].owner_id == str(STRANGER)  # ownership is reported, never hidden
    assert await load_chunks(db, []) == {}


async def test_anchors_map_onto_the_stored_chunks_including_a_quote_cut_by_a_boundary(
    db: AsyncSession,
) -> None:
    db.add(User(id=OWNER, email="u@example.invalid", google_id="g"))
    await db.flush()
    ids = await add_file(
        db,
        OWNER,
        "policy.txt",
        ["Refunds are paid within 14 days of the", "return request, in full."],
    )
    await db.commit()
    case = {
        "evidence_anchors": [
            {"file": "synthetic/policy.txt", "quote": "paid within 14 days"},
            {"file": "synthetic/policy.txt", "quote": "days of the return request"},
            {"file": "synthetic/policy.txt", "quote": "never written anywhere"},
        ]
    }
    by_file = await load_file_chunks(db, OWNER, ["policy.txt"])
    whole, split, lost = map_case_anchors(case, by_file, {"synthetic/policy.txt": "policy.txt"})
    assert (whole.kind, whole.chunk_ids) == ("whole", (str(ids[0]),))
    assert (split.kind, split.chunk_ids) == ("split", (str(ids[0]), str(ids[1])))
    assert lost.kind == "absent"

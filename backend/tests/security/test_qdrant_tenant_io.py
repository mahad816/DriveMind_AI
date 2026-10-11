"""Real Qdrant and PostgreSQL tenancy; all data is synthetic and disposable."""

import os
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid4
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Depends
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import PointStruct, PayloadSchemaType
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.chat import get_rag_service
from app.core.config import Settings
from app.db.session import get_db
from app.db.enums import DriveFileStatus
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.embeddings.vector_store import QdrantVectorStore, VectorStoreError
from app.retrieval.vector import VectorRetriever
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.keyword import KeywordRetriever
from app.retrieval.metadata import MetadataRetriever
from app.retrieval.rerank import weighted_fusion_rerank
from app.services.indexing_service import IndexingService
from app.services.rag_service import RagService
from .conftest import USER_A, USER_B
from .test_chat_file_evidence_authorization import (
    A_TEXT,
    B_TEXT,
    authenticate,
    chat_reads,
    owner_engine,
    final_engine,
)
from .test_grounded_retrieval_authorization import request

__all__ = ["chat_reads", "owner_engine", "final_engine"]


class SyntheticEmbedding:
    model_name = "synthetic"
    embedding_dimension = 3

    def __init__(self):
        self.calls = []

    async def embed_texts(self, texts):
        self.calls.append(texts)
        return [[0.8, 0.6, 0.0] if A_TEXT in t else [1.0, 0.0, 0.0] for t in texts]


@pytest.fixture
async def qdrant_client():
    url = os.environ.get("QDRANT_TEST_URL", "")
    if not url:
        pytest.skip("QDRANT_TEST_URL must name a disposable loopback server")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.port in {6333, 6334}
    ):
        pytest.fail("Refusing non-loopback Qdrant test server")
    client = AsyncQdrantClient(url=url, timeout=10)
    try:
        yield client
    finally:
        await client.close()


@pytest.fixture
async def vector_world(chat_reads, qdrant_client):
    r = chat_reads
    r.settings.qdrant_collection = "drivemind_4d3_test_" + uuid4().hex
    r.settings.retrieval_candidate_k = 1
    r.settings.evidence_min_fusion_score = 0.001
    embedding = SyntheticEmbedding()
    store = QdrantVectorStore(r.settings, client=qdrant_client)
    ids = {}
    try:
        # Actual indexing/chunking/FTS/vector writes, not mocked ownership or vector operations.
        for owner in (USER_A, USER_B):
            file = r.files[(owner, "resume.txt")]
            async with r.factory() as db:
                await db.execute(
                    update(DriveFile)
                    .where(DriveFile.id == file.id)
                    .values(status=DriveFileStatus.INDEXING)
                )
                await db.commit()
                result = await IndexingService(
                    db, r.settings, embedding_service=embedding, vector_store=store
                ).build_index(user_id=owner, file_id=file.id)
                assert result.embedded == 1 and result.failed == 0
                ids[owner] = await db.scalar(
                    select(Chunk.id).join(Document).where(Document.drive_file_id == file.id)
                )
        yield SimpleNamespace(r=r, client=qdrant_client, store=store, ids=ids, embedding=embedding)
    finally:
        if await qdrant_client.collection_exists(store.collection_name):
            await qdrant_client.delete_collection(store.collection_name)


async def test_owner_payload_and_filter_precede_top_k(vector_world):
    w = vector_world
    info = await w.client.get_collection(w.store.collection_name)
    assert info.payload_schema["user_id"].data_type == PayloadSchemaType.KEYWORD
    for owner in (USER_A, USER_B):
        records = await w.client.retrieve(w.store.collection_name, [str(w.ids[owner])])
        assert records[0].payload["user_id"] == str(owner)
        assert records[0].payload["drive_file_id"] == str(w.r.files[(owner, "resume.txt")].id)
        hits = await w.store.search_similar([1.0, 0.0, 0.0], user_id=owner, limit=1)
        assert [h.chunk_id for h in hits] == [w.ids[owner]]
        assert hits[0].score == pytest.approx(0.8 if owner == USER_A else 1.0)
    # B outranks A without the filter, demonstrating the top-K starvation regression.
    raw = await w.client.query_points(w.store.collection_name, query=[1.0, 0.0, 0.0], limit=1)
    assert raw.points[0].id == str(w.ids[USER_B])
    hits = await w.store.search_similar(
        [1.0, 0.0, 0.0], user_id=USER_A, limit=1, file_ids=(w.r.files[(USER_A, "resume.txt")].id,)
    )
    assert hits[0].chunk_id == w.ids[USER_A]
    assert (
        await w.store.search_similar(
            [1.0, 0.0, 0.0],
            user_id=USER_A,
            limit=1,
            file_ids=(w.r.files[(USER_B, "resume.txt")].id,),
        )
        == []
    )
    await w.client.upsert(
        w.store.collection_name,
        points=[PointStruct(id=str(uuid4()), vector=[1.0, 0.0, 0.0], payload={"legacy": True})],
        wait=True,
    )
    assert [
        h.chunk_id for h in await w.store.search_similar([1.0, 0.0, 0.0], user_id=USER_A, limit=24)
    ] == [w.ids[USER_A]]


async def test_spoofed_payload_and_ineligible_chunk_fail_sql_hydration(vector_world):
    w = vector_world
    await w.client.set_payload(
        w.store.collection_name,
        payload={"user_id": str(USER_A)},
        points=[str(w.ids[USER_B])],
        wait=True,
    )
    async with w.r.factory() as db:
        retriever = VectorRetriever(
            db, w.r.settings, embedding_service=w.embedding, vector_store=w.store
        )
        result = await retriever.retrieve(request(USER_A, query="Explain GPA", limit=24))
        assert [c.chunk_id for c in result] == [w.ids[USER_A]]
        assert B_TEXT not in " ".join(c.text for c in result)
        await db.execute(
            update(DriveFile)
            .where(DriveFile.id == w.r.files[(USER_A, "resume.txt")].id)
            .values(status=DriveFileStatus.SKIPPED)
        )
        await db.commit()
        assert await retriever.retrieve(request(USER_A, query="Explain GPA", limit=24)) == []
        await db.execute(delete(Chunk).where(Chunk.id == w.ids[USER_B]))
        await db.commit()
        await w.client.set_payload(
            w.store.collection_name,
            payload={"user_id": str(USER_B)},
            points=[str(w.ids[USER_B])],
            wait=True,
        )
        assert await retriever.retrieve(request(USER_B, query="Explain GPA", limit=24)) == []


async def test_unchanged_payload_repair_preserves_vectors_and_unknown_fields(vector_world):
    w = vector_world
    key = str(w.ids[USER_A])
    before = (await w.client.retrieve(w.store.collection_name, [key], with_vectors=True))[0]
    await w.client.delete_payload(
        w.store.collection_name, keys=["user_id"], points=[key], wait=True
    )
    await w.client.set_payload(
        w.store.collection_name, payload={"custom_field": "keep-me"}, points=[key], wait=True
    )
    calls = len(w.embedding.calls)
    file = w.r.files[(USER_A, "resume.txt")]
    async with w.r.factory() as db:
        await db.execute(
            update(DriveFile).where(DriveFile.id == file.id).values(status=DriveFileStatus.INDEXING)
        )
        await db.commit()
        result = await IndexingService(
            db, w.r.settings, embedding_service=w.embedding, vector_store=w.store
        ).build_index(user_id=USER_A, file_id=file.id)
        assert result.unchanged == 1 and result.embedded == 0 and result.failed == 0
    after = (await w.client.retrieve(w.store.collection_name, [key], with_vectors=True))[0]
    assert len(w.embedding.calls) == calls
    assert after.id == before.id and after.vector == before.vector
    assert after.payload == {**before.payload, "custom_field": "keep-me"}
    assert after.payload["user_id"] == str(USER_A)


async def test_invalid_unchanged_linkage_is_not_repaired(vector_world):
    w = vector_world
    key = str(w.ids[USER_A])
    await w.client.set_payload(
        w.store.collection_name,
        payload={
            "drive_file_id": str(w.r.files[(USER_B, "resume.txt")].id),
            "user_id": str(USER_B),
        },
        points=[key],
        wait=True,
    )
    async with w.r.factory() as db:
        doc = await db.scalar(
            select(Document).where(Document.drive_file_id == w.r.files[(USER_A, "resume.txt")].id)
        )
        with pytest.raises(VectorStoreError, match="linkage"):
            await w.store.update_unchanged_point_owners(
                {w.ids[USER_A]: doc.extracted_text_hash},
                user_id=USER_A,
                drive_file_id=doc.drive_file_id,
            )
    record = (await w.client.retrieve(w.store.collection_name, [key]))[0]
    assert record.payload["user_id"] == str(USER_B)
    await w.client.delete(w.store.collection_name, points_selector=[key], wait=True)
    with pytest.raises(VectorStoreError, match="linkage"):
        await w.store.update_unchanged_point_owners(
            {w.ids[USER_A]: "missing"},
            user_id=USER_A,
            drive_file_id=w.r.files[(USER_A, "resume.txt")].id,
        )
    assert await w.client.retrieve(w.store.collection_name, [key]) == []


@pytest.mark.parametrize(
    "hybrid,graph,tools",
    [
        (False, False, False),
        (True, False, False),
        (False, True, False),
        (True, True, False),
        (False, False, True),
        (True, True, True),
    ],
)
async def test_real_filtered_chat_paths_and_citations(vector_world, hybrid, graph, tools):
    from app.agents.tool_rag.agent_models import AgentStepResult
    from app.services.tool_agent_service import ToolAgentAdapter
    from tests.agents.tool_rag.test_agent_loop import ScriptChat, call

    w = vector_world
    r = w.r
    r.settings.hybrid_retrieval_enabled = hybrid
    r.settings.agent_graph_enabled = graph
    r.settings.tool_rag_agent_enabled = tools
    r.settings.agent_max_rewrite_attempts = 0
    captured = []
    ranked_inputs = []

    def inspect_rerank(chunks, **kwargs):
        ranked_inputs.append(chunks)
        assert all(B_TEXT not in c.text for c in chunks)
        return weighted_fusion_rerank(chunks, **kwargs)

    chat = AsyncMock()
    chat.generate_grounded_answer.side_effect = lambda q, chunks, **kw: (
        captured.append(chunks) or chunks[0].text + " [1]"
    )
    tool_chat = ScriptChat(
        [
            call(
                "search_knowledge",
                {
                    "query": "GPA evidence",
                    "scope": {"kind": "ALL_ELIGIBLE_INDEXED_FILES"},
                    "candidate_limit": 1,
                },
            ),
            AgentStepResult(text="Owned GPA evidence [source_1]"),
        ]
    )

    def service(db: AsyncSession = Depends(get_db)):
        vector = VectorRetriever(
            db, r.settings, embedding_service=w.embedding, vector_store=w.store
        )
        hybrid_retriever = HybridRetriever(
            db,
            r.settings,
            vector_retriever=vector,
            keyword_retriever=KeywordRetriever(db, r.settings),
            metadata_retriever=MetadataRetriever(db, r.settings),
        )
        return RagService(
            db,
            r.settings,
            retriever=hybrid_retriever if hybrid else vector,
            chat_service=chat,
            tool_agent=ToolAgentAdapter(db, r.settings, chat=tool_chat, retriever=hybrid_retriever),
        )

    r.app.dependency_overrides[get_rag_service] = service
    authenticate(r, USER_A)
    with (
        patch("app.retrieval.vector.get_embedding_service", return_value=w.embedding),
        patch("app.retrieval.vector.QdrantVectorStore", return_value=w.store),
        patch("app.retrieval.hybrid.weighted_fusion_rerank", side_effect=inspect_rerank),
        patch("app.agents.drive_graph.nodes.weighted_fusion_rerank", side_effect=inspect_rerank),
    ):
        response = await r.client.post("/api/v1/chat", json={"question": "Explain GPA evidence"})
    assert response.status_code == 200, response.text
    assert response.json()["citations"]
    if tools:
        inputs = " ".join(m.text or "" for turn in tool_chat.received for m in turn)
    else:
        assert captured
        inputs = " ".join(c.text for c in captured[0])
    assert A_TEXT in inputs and B_TEXT not in inputs
    if hybrid or graph or tools:
        assert ranked_inputs
    for citation in response.json()["citations"]:
        assert citation["chunk_id"] == str(w.ids[USER_A])
        source = await r.client.get("/api/v1/sources/" + citation["chunk_id"])
        assert source.status_code == 200 and B_TEXT not in source.text


async def test_demo_ownerless_payload_search_remains_explicit(vector_world):
    w = vector_world
    # A separate synthetic collection, never the normal test collection.
    demo_settings = Settings(
        demo_mode=True,
        demo_user_id=str(USER_A),
        qdrant_collection="drivemind_4d3_test_demo_" + uuid4().hex,
    )
    demo = QdrantVectorStore(demo_settings, client=w.client)
    try:
        await demo.ensure_collection(vector_size=3)
        await w.client.upsert(
            demo.collection_name,
            points=[
                PointStruct(
                    id=str(w.ids[USER_A]),
                    vector=[1.0, 0.0, 0.0],
                    payload={"chunk_id": str(w.ids[USER_A])},
                )
            ],
            wait=True,
        )
        assert "user_id" not in (await w.client.get_collection(demo.collection_name)).payload_schema
        hits = await demo.search_similar([1.0, 0.0, 0.0], user_id=USER_A, limit=1)
        assert hits[0].chunk_id == w.ids[USER_A]
        with pytest.raises(VectorStoreError):
            await demo.search_similar([1.0, 0.0, 0.0], user_id=USER_B, limit=1)
        assert await w.store.search_similar([1.0, 0.0, 0.0], user_id=USER_A, limit=1)
    finally:
        await w.client.delete_collection(demo.collection_name)


async def test_reupsert_keeps_owner_and_unrelated_metadata(vector_world):
    w = vector_world
    key = str(w.ids[USER_A])
    await w.client.set_payload(
        w.store.collection_name,
        payload={
            "extracted_text_hash": "stale-synthetic-hash",
            "custom_field": "keep-on-reupsert",
            "user_id": str(USER_B),
        },
        points=[key],
        wait=True,
    )
    async with w.r.factory() as db:
        file_id = w.r.files[(USER_A, "resume.txt")].id
        await db.execute(
            update(DriveFile).where(DriveFile.id == file_id).values(status=DriveFileStatus.INDEXING)
        )
        await db.commit()
        result = await IndexingService(
            db, w.r.settings, embedding_service=w.embedding, vector_store=w.store
        ).build_index(user_id=USER_A, file_id=file_id)
        assert result.embedded == 1 and result.failed == 0
    after = (await w.client.retrieve(w.store.collection_name, [key]))[0]
    assert after.payload["user_id"] == str(USER_A)
    assert after.payload["custom_field"] == "keep-on-reupsert"
    assert after.payload["extracted_text_hash"] != "stale-synthetic-hash"
    assert after.id == key


async def test_anonymous_demo_real_admission_and_ownerless_vectors(vector_world):
    from sqlalchemy import delete
    from app.db.models.user import User
    from app.demo.manifest import load_manifest
    from app.ingestion.chunking import chunk_text
    from .conftest import DEMO_USER

    w = vector_world
    r = w.r
    normal_collection = w.store.collection_name
    r.settings.demo_mode = True
    r.settings.qdrant_collection = "drivemind_4d3_test_demo_" + uuid4().hex
    r.settings.retrieval_candidate_k = 24
    demo = QdrantVectorStore(r.settings, client=w.client)
    manifest = load_manifest()
    points = []
    try:
        async with r.factory() as db:
            await db.execute(delete(User))
            db.add(User(id=DEMO_USER, email="demo@invalid", google_id="demo:synthetic"))
            await db.flush()
            for entry in manifest.files:
                content = manifest.read_sample(entry.filename)
                db.add(
                    DriveFile(
                        id=entry.id,
                        user_id=DEMO_USER,
                        drive_file_id=entry.external_id,
                        name=entry.filename,
                        mime_type="text/plain",
                        folder_path="/HarborDesk samples",
                        modified_at=manifest.modified_at,
                        status=DriveFileStatus.INDEXED,
                    )
                )
                await db.flush()
                db.add(
                    Document(
                        id=entry.document_id,
                        drive_file_id=entry.id,
                        extracted_text=content,
                        extracted_text_hash=entry.sha256,
                    )
                )
                await db.flush()
                for part in chunk_text(content):
                    chunk = Chunk(
                        id=uuid4(),
                        document_id=entry.document_id,
                        chunk_index=part.chunk_index,
                        text=part.text,
                        metadata_json={"extracted_text_hash": entry.sha256},
                    )
                    db.add(chunk)
                    points.append(
                        PointStruct(
                            id=str(chunk.id),
                            vector=[1.0, 0.0, 0.0],
                            payload={
                                "chunk_id": str(chunk.id),
                                "drive_file_id": str(entry.id),
                                "extracted_text_hash": entry.sha256,
                            },
                        )
                    )
            await db.commit()
        await demo.ensure_collection(vector_size=3)
        await w.client.upsert(demo.collection_name, points=points, wait=True)
        r.app.state.demo_readiness_client = SimpleNamespace(get=AsyncMock(return_value=w.client))
        captured = []
        chat = AsyncMock()
        chat.generate_grounded_answer.side_effect = lambda q, chunks, **kw: (
            captured.append(chunks) or "Approved sample evidence [1]"
        )

        def service(db: AsyncSession = Depends(get_db)):
            return RagService(
                db,
                r.settings,
                chat_service=chat,
                retriever=VectorRetriever(
                    db, r.settings, embedding_service=w.embedding, vector_store=demo
                ),
            )

        r.app.dependency_overrides[get_rag_service] = service
        response = await r.client.post(
            "/api/v1/chat", json={"question": "Explain onboarding approvals"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["user_id"] == str(DEMO_USER)
        assert response.json()["citations"] and captured
        assert all(c.drive_file_id in {entry.id for entry in manifest.files} for c in captured[0])
        assert not any(A_TEXT in c.text or B_TEXT in c.text for c in captured[0])
        assert "user_id" not in (await w.client.get_collection(demo.collection_name)).payload_schema
        # Actual admission scans reject foreign vectors before provider work.
        await w.client.upsert(
            demo.collection_name,
            points=[
                PointStruct(id=str(uuid4()), vector=[1.0, 0.0, 0.0], payload={"foreign": True})
            ],
            wait=True,
        )
        calls = len(captured)
        response = await r.client.post(
            "/api/v1/chat", json={"question": "Explain onboarding approvals"}
        )
        assert response.status_code == 503 and len(captured) == calls
    finally:
        await w.client.delete_collection(demo.collection_name)
        r.settings.demo_mode = False
        r.settings.qdrant_collection = normal_collection


async def test_actual_qdrant_failure_does_not_retry_unfiltered(vector_world):
    w = vector_world
    await w.client.delete_collection(w.store.collection_name)
    with patch.object(w.client, "query_points", wraps=w.client.query_points) as query:
        with pytest.raises(VectorStoreError):
            await w.store.search_similar([1.0, 0.0, 0.0], user_id=USER_A, limit=1)
        assert query.await_count == 1
        assert query.await_args is not None
        assert query.await_args.kwargs["query_filter"].must[0].key == "user_id"

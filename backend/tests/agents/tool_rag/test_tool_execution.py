"""Deterministic execution with SQL-inspecting fakes; no DB/provider network."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID
from typing import cast
from sqlalchemy.ext.asyncio import AsyncSession

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.agents.tool_rag.execution.context import ExecutionContext
from app.agents.tool_rag.execution.executor import ToolExecutor
from app.agents.tool_rag.handles import RuntimeHandleRegistry
from app.agents.tool_rag.errors import ToolErrorCode
from app.core.config import Settings
from app.db.enums import DriveFileStatus
from app.routing.intent_frame.execution import RetrievalRequest
from app.routing.intent_frame.scope import EligibleCollectionScope, ResolvedFileScope
from app.retrieval.keyword import KeywordRetriever
from app.retrieval.metadata import MetadataRetriever
from app.retrieval.vector import VectorRetriever
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.types import RetrievedChunk
from app.embeddings.vector_store import QdrantVectorStore, ScoredChunkHit, VectorStoreError

USER = UUID(int=1)


def file(i=10, name="report.pdf", user=USER, status=DriveFileStatus.INDEXED, day=1):
    return SimpleNamespace(
        id=UUID(int=i),
        user_id=user,
        status=status,
        name=name,
        mime_type="application/pdf",
        modified_at=datetime(2026, 1, day, tzinfo=timezone.utc),
    )


class InventoryDB:
    def __init__(self, files=()):
        self.files = list(files)
        self.statements = []

    def rows(self, statement):
        self.statements.append(statement)
        params = statement.compile().params
        assert params.get("user_id_1") == USER
        assert params.get("status_1") == DriveFileStatus.INDEXED
        rows = [
            f
            for f in self.files
            if f.user_id == params["user_id_1"] and f.status == params["status_1"]
        ]
        if "name_1" in params:
            rows = [f for f in rows if f.name == params["name_1"]]
        if "id_1" in params:
            rows = [f for f in rows if f.id in params["id_1"]]
        sql = str(statement)
        if "modified_at DESC" in sql:
            rows.sort(key=lambda f: (-f.modified_at.timestamp(), f.id.int))
        elif "modified_at ASC" in sql:
            rows.sort(key=lambda f: (f.modified_at.timestamp(), f.id.int))
        elif "ORDER BY drive_files.id" in sql:
            rows.sort(key=lambda f: f.id.int)
        if statement._limit_clause is not None:
            rows = rows[: statement._limit_clause.value]
        return rows

    async def scalars(self, statement):
        rows = self.rows(statement)
        if len(list(statement.selected_columns)) == 1:
            rows = [f.id for f in rows]
        return SimpleNamespace(all=lambda: rows)

    async def scalar(self, statement):
        rows = self.rows(statement)
        return len(rows) if "count(" in str(statement) else (rows[0] if rows else None)


def context(files=(), retriever=None):
    return ExecutionContext(
        user_id=USER,
        db=cast(AsyncSession, InventoryDB(files)),
        handles=RuntimeHandleRegistry(),
        retriever=retriever,
    )


async def execute(name, args, ctx):
    result = await ToolExecutor().execute(name, json.dumps(args), ctx)
    # Dynamic test view retains the actual typed runtime objects without altering them.
    return SimpleNamespace(
        internal_result=result.internal_result, llm_result=result.llm_result, error=result.error
    )


def inventory(operation):
    return {"operation": operation, "scope": {"kind": "ALL_ELIGIBLE_INDEXED_FILES"}}


@pytest.mark.asyncio
async def test_inventory_eligibility_count_sql_and_list_order():
    files = [
        file(12, "Straße.pdf"),
        file(10, "STRASSE.pdf"),
        file(11, "alpha.pdf"),
        file(13, user=UUID(int=2)),
        file(14, status=DriveFileStatus.FAILED),
    ]
    ctx = context(files)
    count = await execute("files_query", inventory("COUNT"), ctx)
    assert count.llm_result.result.count == 3
    assert "count(" in str(cast(InventoryDB, ctx.db).statements[0])
    listed = await execute("files_query", inventory("LIST"), ctx)
    result = listed.llm_result.result
    assert [x.filename for x in result.items] == ["alpha.pdf", "STRASSE.pdf", "Straße.pdf"]
    assert ctx.handles.resolve_file(result.items[1].handle) == UUID(int=10)
    assert result.returned_count == result.total_count == 3 and result.truncated is False
    assert all(str(f.id) not in listed.llm_result.model_dump_json() for f in files)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["LIST", "COUNT", "LATEST", "OLDEST"])
async def test_empty_inventory_safe(operation):
    out = await execute("files_query", inventory(operation), context())
    assert out.error is None


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,expected", [("LATEST", 10), ("OLDEST", 12)])
async def test_recency_tie_breaker(operation, expected):
    ctx = context([file(11, day=3), file(10, day=3), file(12, day=1)])
    out = await execute("files_query", inventory(operation), ctx)
    assert ctx.handles.resolve_file(out.llm_result.result.item.handle) == UUID(int=expected)
    assert out.llm_result.result.item.modified_at is None


@pytest.mark.asyncio
async def test_list_truncation_explicit():
    out = await execute(
        "files_query",
        inventory("LIST"),
        context([file(i + 10, f"f{i:03}.pdf") for i in range(101)]),
    )
    result = out.llm_result.result
    assert result.total_count == 101 and result.returned_count == 100 and result.truncated


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reference,expected",
    [("Report.pdf", "RESOLVED"), ("REPORT.PDF", "AMBIGUOUS"), ("report.pd", "NOT_FOUND")],
)
async def test_resolve_tiers_no_fuzzy(reference, expected):
    ctx = context(
        [
            file(10, "Report.pdf"),
            file(11, "report.pdf"),
            file(12, "Report.pdf", user=UUID(int=2)),
            file(13, "Report.pdf", status=DriveFileStatus.SKIPPED),
        ]
    )
    out = await execute("resolve_file", {"reference": reference}, ctx)
    assert out.llm_result.result.kind == expected
    if expected == "RESOLVED":
        again = await execute("resolve_file", {"reference": reference}, ctx)
        assert again.llm_result == out.llm_result


@pytest.mark.asyncio
async def test_case_insensitive_unique_and_exact_duplicates():
    unique = await execute("resolve_file", {"reference": "REPORT.PDF"}, context([file()]))
    assert unique.llm_result.result.kind == "RESOLVED"
    duplicate = await execute(
        "resolve_file", {"reference": "report.pdf"}, context([file(), file(11)])
    )
    assert duplicate.llm_result.result.kind == "AMBIGUOUS"


@pytest.mark.asyncio
async def test_unknown_invalid_and_private_failure():
    ctx = context()
    for name, args in [("unknown", {}), ("files_query", {"operation": "DELETE"})]:
        out = await execute(name, args, ctx)
        assert out.error.code == ToolErrorCode.INVALID_ARGUMENT
    ctx.db.scalar = AsyncMock(side_effect=RuntimeError("private password traceback"))
    out = await execute("files_query", inventory("COUNT"), ctx)
    assert out.error.code == ToolErrorCode.INTERNAL_ERROR
    assert out.error.private_diagnostic == "private password traceback"
    assert "private" not in out.llm_result.model_dump_json()


def chunk(file_id=10):
    return RetrievedChunk(
        chunk_id=UUID(int=100),
        document_id=UUID(int=90),
        drive_file_id=UUID(int=file_id),
        filename="report.pdf",
        mime_type="application/pdf",
        modified_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        chunk_index=0,
        text="Authoritative refund policy text.",
        score=0.9,
        source_scores={"vector": 0.9},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("exact", [False, True])
async def test_search_scope_resolved_and_public_evidence(exact):
    retriever = AsyncMock()
    retriever.retrieve.return_value = [chunk()]
    ctx = context([file()], retriever)
    handle = ctx.handles.register_file(UUID(int=10))
    scope = (
        {"kind": "EXACT_FILES", "file_handles": [handle.model_dump()]}
        if exact
        else {"kind": "ALL_ELIGIBLE_INDEXED_FILES"}
    )
    out = await execute(
        "search_knowledge", {"query": "refund policy", "scope": scope, "candidate_limit": 7}, ctx
    )
    assert out.error is None
    request = retriever.retrieve.await_args.args[0]
    assert (
        isinstance(request, RetrievalRequest)
        and request.user_id == USER
        and request.candidate_limit == 7
    )
    assert isinstance(request.scope, ResolvedFileScope if exact else EligibleCollectionScope)
    public = out.llm_result.model_dump_json()
    assert all(str(x) not in public for x in [UUID(int=10), UUID(int=90), UUID(int=100)])
    section = out.internal_result.sections[0]
    assert section.combined_text == chunk().text and len(section.members) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,user", [(DriveFileStatus.FAILED, USER), (DriveFileStatus.INDEXED, UUID(int=2))]
)
async def test_file_evidence_revalidates_current_eligibility(status, user):
    retriever = AsyncMock()
    ctx = context([file(status=status, user=user)], retriever)
    handle = ctx.handles.register_file(UUID(int=10))
    out = await execute(
        "file_evidence", {"file_handle": handle.model_dump(), "query": "summary"}, ctx
    )
    assert out.error.code == ToolErrorCode.NOT_FOUND
    retriever.retrieve.assert_not_awaited()


@pytest.mark.asyncio
async def test_file_evidence_exact_and_empty_no_fallback():
    retriever = AsyncMock()
    retriever.retrieve.return_value = []
    ctx = context([file()], retriever)
    handle = ctx.handles.register_file(UUID(int=10))
    out = await execute(
        "file_evidence", {"file_handle": handle.model_dump(), "query": "summary"}, ctx
    )
    assert out.error is None and out.llm_result.sections == ()
    request = retriever.retrieve.await_args.args[0]
    assert request.scope.file_ids == (UUID(int=10),)
    retriever.retrieve.assert_awaited_once()
    missing = await execute(
        "file_evidence",
        {"file_handle": {"kind": "FILE", "value": "file_99"}, "query": "summary"},
        ctx,
    )
    assert missing.error.code == ToolErrorCode.UNKNOWN_HANDLE
    retriever.retrieve.assert_awaited_once()


@pytest.mark.asyncio
async def test_scoped_pipeline_violation_rejected():
    retriever = AsyncMock()
    retriever.retrieve.return_value = [chunk(11)]
    ctx = context([file(), file(11)], retriever)
    handle = ctx.handles.register_file(UUID(int=10))
    out = await execute(
        "file_evidence", {"file_handle": handle.model_dump(), "query": "summary"}, ctx
    )
    assert out.error.code == ToolErrorCode.INTERNAL_ERROR and out.internal_result is None
    retriever.retrieve.assert_awaited_once()


@pytest.mark.parametrize("ids", [(), (UUID(int=10),), (UUID(int=10), UUID(int=11))])
def test_shared_request_nonempty_exact(ids):
    if not ids:
        with pytest.raises(ValidationError):
            RetrievalRequest(
                query="policy",
                user_id=USER,
                scope=ResolvedFileScope(file_ids=ids),
                candidate_limit=4,
            )
    else:
        request = RetrievalRequest(
            query="latest folder topic",
            user_id=USER,
            scope=ResolvedFileScope(file_ids=ids),
            candidate_limit=4,
        )
        assert isinstance(request.scope, ResolvedFileScope)
        assert request.scope.file_ids == ids


@pytest.mark.asyncio
@pytest.mark.parametrize("ids", [None, (UUID(int=10),), (UUID(int=10), UUID(int=11))])
async def test_qdrant_payload_file_filter(ids):
    client = AsyncMock()
    client.query_points.return_value = SimpleNamespace(points=[])
    store = QdrantVectorStore(Settings(), client=client)
    await store.search_similar([0.1, 0.2], limit=3, file_ids=ids)
    kw = client.query_points.await_args.kwargs
    if ids is None:
        assert "query_filter" not in kw
    else:
        condition = kw["query_filter"].must[0]
        assert condition.key == "drive_file_id" and condition.match.any == [str(i) for i in ids]
    with pytest.raises(VectorStoreError):
        await store.search_similar([0.1, 0.2], limit=3, file_ids=())
    client.query_points.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("exact", [False, True])
async def test_all_keyword_sql_paths_scope(exact):
    db = AsyncMock()
    db.scalars.return_value = SimpleNamespace(all=lambda: [])
    db.execute.return_value = []
    scope = (
        ResolvedFileScope(file_ids=(UUID(int=10), UUID(int=11)))
        if exact
        else EligibleCollectionScope()
    )
    req = RetrievalRequest(
        query='latest "report.pdf" line: explicit policy sentence',
        user_id=USER,
        scope=scope,
        candidate_limit=3,
    )
    retriever = KeywordRetriever(db, Settings())
    ts_query = retriever._ts_query(req.query)
    assert ts_query is not None
    await retriever._fts_hits(req.query, ts_query, req)
    await retriever._filename_only_hits_for_terms(["report"], req)
    await retriever._phrase_hits("policy sentence", req)
    await retriever._date_hits("2026-01-01", req)
    await retriever._load_chunks([UUID(int=100)], req)
    statements = [x.args[0] for x in db.execute.await_args_list + db.scalars.await_args_list]
    assert len(statements) >= 4
    for stmt in statements:
        sql = str(stmt.compile(dialect=postgresql.dialect()))
        params = stmt.compile().params
        assert "drive_files.user_id =" in sql and params["user_id_1"] == USER
        assert params["status_1"] == DriveFileStatus.INDEXED
        assert ("drive_files.id IN" in sql) == exact


@pytest.mark.asyncio
async def test_metadata_scope_not_inferred_from_query():
    db = AsyncMock()
    db.scalars.return_value = SimpleNamespace(all=lambda: [])
    retriever = MetadataRetriever(db, Settings())
    req = RetrievalRequest(
        query="latest pdf in Finance folder",
        user_id=USER,
        scope=ResolvedFileScope(file_ids=(UUID(int=10),)),
        candidate_limit=3,
    )
    await retriever.retrieve(req)
    stmt = db.scalars.await_args.args[0]
    sql = str(stmt)
    params = stmt.compile().params
    assert "drive_files.id IN" in sql and "drive_files.user_id =" in sql
    assert "folder_path LIKE" not in sql and "mime_type IN" not in sql
    assert params["user_id_1"] == USER


@pytest.mark.asyncio
async def test_vector_hydration_revalidates_scoped_owner():
    db = AsyncMock()
    embedding = AsyncMock()
    embedding.embed_texts.return_value = [[0.1, 0.2]]
    embedding.embedding_dimension = 2
    store = AsyncMock()
    store.search_similar.return_value = [ScoredChunkHit(chunk_id=UUID(int=100), score=0.8)]
    ch = SimpleNamespace(
        id=UUID(int=100), document=SimpleNamespace(drive_file=file(user=UUID(int=2)))
    )
    db.scalars.return_value = SimpleNamespace(all=lambda: [ch])
    retriever = VectorRetriever(db, Settings(), embedding_service=embedding, vector_store=store)
    req = RetrievalRequest(
        query="policy",
        user_id=USER,
        scope=ResolvedFileScope(file_ids=(UUID(int=10),)),
        candidate_limit=5,
    )
    assert await retriever.retrieve(req) == []
    assert store.search_similar.await_args.kwargs["file_ids"] == (UUID(int=10),)
    stmt = db.scalars.await_args.args[0]
    assert "drive_files.id IN" in str(stmt) and stmt.compile().params["user_id_1"] == USER


@pytest.mark.asyncio
async def test_hybrid_same_request_and_no_unscoped_retry():
    sources = [AsyncMock() for _ in range(3)]
    for source in sources:
        source.retrieve.return_value = [chunk()]
    hybrid = HybridRetriever(
        AsyncMock(),
        Settings(),
        vector_retriever=sources[0],
        keyword_retriever=sources[1],
        metadata_retriever=sources[2],
    )
    req = RetrievalRequest(
        query="policy",
        user_id=USER,
        scope=ResolvedFileScope(file_ids=(UUID(int=10),)),
        candidate_limit=5,
    )
    result = await hybrid.retrieve(req)
    assert result and result[0].fusion_score is not None
    for source in sources:
        assert source.retrieve.await_args.args[0] is req
    sources[1].retrieve.side_effect = RuntimeError("scoped failure")
    with pytest.raises(RuntimeError):
        await hybrid.retrieve(req)
    for source in sources:
        assert source.retrieve.await_count == 2
        assert all(call.args[0] is req for call in source.retrieve.await_args_list)


@pytest.mark.asyncio
async def test_multiple_exact_handles_and_wrong_type_never_broaden():
    retriever = AsyncMock()
    retriever.retrieve.return_value = []
    ctx = context([file(), file(11)], retriever)
    handles = [ctx.handles.register_file(UUID(int=i)) for i in (10, 11)]
    out = await execute(
        "search_knowledge",
        {
            "query": "policy",
            "scope": {"kind": "EXACT_FILES", "file_handles": [h.model_dump() for h in handles]},
        },
        ctx,
    )
    assert out.error is None
    req = retriever.retrieve.await_args.args[0]
    assert req.scope.file_ids == (UUID(int=10), UUID(int=11))
    bad = await execute(
        "file_evidence",
        {"query": "policy", "file_handle": {"kind": "SOURCE", "value": "source_1"}},
        ctx,
    )
    assert bad.error.code == ToolErrorCode.INVALID_ARGUMENT
    retriever.retrieve.assert_awaited_once()


@pytest.mark.asyncio
async def test_metadata_snapshot_overflow_explicit(monkeypatch):
    from app.agents.tool_rag.execution import executor

    monkeypatch.setattr(executor, "METADATA_LIMIT", 2)
    out = await execute("files_query", inventory("LIST"), context([file(), file(11), file(12)]))
    assert out.error.code == ToolErrorCode.INTERNAL_ERROR
    assert out.internal_result is None


@pytest.mark.asyncio
async def test_scoped_session_isolation_without_connection():
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from app.retrieval.scope import scoped_session

    engine = create_async_engine("postgresql+asyncpg://synthetic:synthetic@localhost/synthetic")
    original = AsyncSession(engine)
    try:
        async with scoped_session(original) as a:
            async with scoped_session(original) as b:
                assert a is not original and b is not original and a is not b
                assert a.bind is engine and b.bind is engine
        unbound = AsyncSession()
        with pytest.raises(ValueError):
            async with scoped_session(unbound):
                raise AssertionError("must not fall back")
        await unbound.close()
    finally:
        await original.close()
        await engine.dispose()

"""Four explicit deterministic read-only dispatch branches; no dynamic execution."""

from dataclasses import dataclass
from uuid import UUID
from sqlalchemy import func, select
from sqlalchemy.sql.elements import ColumnElement
from app.db.models.drive_file import DriveFile
from app.db.enums import DriveFileStatus
from app.retrieval.hybrid import HybridRetriever
from app.routing.intent_frame.execution import RetrievalRequest
from app.routing.intent_frame.scope import (
    EligibleCollectionScope,
    ResolvedFileScope,
    RetrievalScope,
)
from app.routing.intent_frame.evidence import (
    EvidenceChunk,
    EvidenceSection,
    ChunkTextRange,
    RetrievalScore,
)
from .. import contracts as c
from ..registry import ToolRegistry, RichResult, SafeResult
from ..errors import ToolError, ToolErrorCode, SafeToolError, ToolFailure
from .context import ExecutionContext

LIST_LIMIT = 100
# Single-user portfolio safety cap. Beyond it, fail explicitly; do not pick a SQL-sorted prefix.
METADATA_LIMIT = 10000


@dataclass(frozen=True)
class ToolExecutionResult:
    internal_result: RichResult | None
    llm_result: SafeResult | SafeToolError
    error: ToolError | None = None


def eligible_user(context: ExecutionContext) -> tuple[ColumnElement[bool], ...]:
    return (DriveFile.user_id == context.user_id, DriveFile.status == DriveFileStatus.INDEXED)


def summary(file: DriveFile) -> c.InternalFileSummary:
    # No stored provenance bit distinguishes source modifiedTime from historical fallback time.
    return c.InternalFileSummary(
        file_id=file.id, filename=file.name, mime_type=file.mime_type, modified_at=None
    )


async def metadata_snapshot(context: ExecutionContext) -> list[DriveFile]:
    result = await context.db.scalars(
        select(DriveFile).where(*eligible_user(context)).limit(METADATA_LIMIT + 1)
    )
    files = list(result.all())
    if len(files) > METADATA_LIMIT:
        raise RuntimeError("INVENTORY_METADATA_LIMIT_EXCEEDED")
    return files


async def files_query(
    arguments: c.FilesQueryArguments, context: ExecutionContext
) -> c.FilesQueryResult:
    if arguments.operation == "COUNT":
        count = await context.db.scalar(
            select(func.count()).select_from(DriveFile).where(*eligible_user(context))
        )
        return c.FilesQueryResult(result=c.FileCountResult(count=int(count or 0)))
    if arguments.operation == "LIST":
        files = sorted(
            await metadata_snapshot(context), key=lambda f: (f.name.casefold(), f.id.int)
        )
        return c.FilesQueryResult(
            result=c.FileListResult(
                items=tuple(summary(f) for f in files[:LIST_LIMIT]), total_count=len(files)
            )
        )
    order = (
        DriveFile.modified_at.desc().nulls_last()
        if arguments.operation == "LATEST"
        else DriveFile.modified_at.asc().nulls_last()
    )
    file = await context.db.scalar(
        select(DriveFile)
        .where(*eligible_user(context))
        .order_by(order, DriveFile.id.asc())
        .limit(1)
    )
    return c.FilesQueryResult(
        result=c.FileSelectionResult(kind=arguments.operation, item=summary(file) if file else None)
    )


async def resolve_file(
    arguments: c.ResolveFileArguments, context: ExecutionContext
) -> c.ResolveFileResult:
    matches_result = await context.db.scalars(
        select(DriveFile)
        .where(*eligible_user(context), DriveFile.name == arguments.reference)
        .order_by(DriveFile.id)
        .limit(11)
    )
    matches = list(matches_result.all())
    if not matches:
        matches = [
            f
            for f in await metadata_snapshot(context)
            if f.name.casefold() == arguments.reference.casefold()
        ]
    if not matches:
        return c.ResolveFileResult(result=c.NotFoundFileResult())
    if len(matches) == 1:
        return c.ResolveFileResult(result=c.ResolvedFileResult(file=summary(matches[0])))
    if len(matches) > 10:
        raise ToolFailure(ToolErrorCode.AMBIGUOUS)
    matches.sort(key=lambda f: f.id.int)
    return c.ResolveFileResult(
        result=c.AmbiguousFileResult(candidates=tuple(summary(f) for f in matches))
    )


async def validate_files(file_ids: tuple[UUID, ...], context: ExecutionContext) -> None:
    result = await context.db.scalars(
        select(DriveFile.id).where(*eligible_user(context), DriveFile.id.in_(file_ids))
    )
    if set(result.all()) != set(file_ids):
        raise ToolFailure(ToolErrorCode.NOT_FOUND)


async def retrieve_sections(
    request: RetrievalRequest, context: ExecutionContext
) -> tuple[EvidenceSection, ...]:
    retriever = context.retriever or HybridRetriever(context.db)
    chunks = await retriever.retrieve(request)
    if not chunks:
        return ()
    file_ids = tuple(dict.fromkeys(chunk.drive_file_id for chunk in chunks))
    if isinstance(request.scope, ResolvedFileScope) and not set(file_ids) <= set(
        request.scope.file_ids
    ):
        raise RuntimeError("RETRIEVAL_SCOPE_VIOLATION")
    await validate_files(file_ids, context)
    sections = []
    for chunk in chunks:
        evidence = EvidenceChunk(
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            file_id=chunk.drive_file_id,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            filename=chunk.filename,
            scores=tuple(
                RetrievalScore(source=source, value=value)
                for source, value in chunk.source_scores.items()
                if source != "hybrid"
            ),
        )
        sections.append(
            EvidenceSection(
                anchor_chunk_id=evidence.chunk_id,
                members=(evidence,),
                parts=(
                    ChunkTextRange(chunk_id=evidence.chunk_id, start=0, end=len(evidence.text)),
                ),
            )
        )
    return tuple(sections)


async def search_knowledge(
    arguments: c.SearchKnowledgeArguments, context: ExecutionContext
) -> c.SearchKnowledgeResult:
    if isinstance(arguments.scope, c.ExactFiles):
        ids = tuple(context.handles.resolve_file(h) for h in arguments.scope.file_handles)
        await validate_files(ids, context)
        scope: RetrievalScope = ResolvedFileScope(file_ids=ids)
    else:
        scope = EligibleCollectionScope()
    request = RetrievalRequest(
        query=arguments.query,
        user_id=context.user_id,
        scope=scope,
        candidate_limit=arguments.candidate_limit,
    )
    return c.SearchKnowledgeResult(sections=await retrieve_sections(request, context))


async def file_evidence(
    arguments: c.FileEvidenceArguments, context: ExecutionContext
) -> c.FileEvidenceResult:
    file_id = context.handles.resolve_file(arguments.file_handle)
    await validate_files((file_id,), context)
    request = RetrievalRequest(
        query=arguments.query,
        user_id=context.user_id,
        scope=ResolvedFileScope(file_ids=(file_id,)),
        candidate_limit=20,
    )
    return c.FileEvidenceResult(file_id=file_id, sections=await retrieve_sections(request, context))


class ToolExecutor:
    def __init__(self) -> None:
        self.registry = ToolRegistry()

    async def execute(
        self, name: str, arguments_json: str, context: ExecutionContext
    ) -> ToolExecutionResult:
        try:
            contract = self.registry.get(name)
            arguments = contract.validate_arguments(arguments_json)
            if isinstance(arguments, c.FilesQueryArguments):
                result: RichResult = await files_query(arguments, context)
            elif isinstance(arguments, c.ResolveFileArguments):
                result = await resolve_file(arguments, context)
            elif isinstance(arguments, c.SearchKnowledgeArguments):
                result = await search_knowledge(arguments, context)
            elif isinstance(arguments, c.FileEvidenceArguments):
                result = await file_evidence(arguments, context)
            else:
                raise ToolFailure(ToolErrorCode.INVALID_ARGUMENT)
            payload = contract.to_llm_payload(result, context.handles)
            return ToolExecutionResult(internal_result=result, llm_result=payload)
        except ToolFailure as exc:
            return ToolExecutionResult(
                internal_result=None, llm_result=exc.error.to_llm_payload(), error=exc.error
            )
        except Exception as exc:
            error = ToolError(code=ToolErrorCode.INTERNAL_ERROR, private_diagnostic=str(exc)[:2000])
            return ToolExecutionResult(
                internal_result=None, llm_result=error.to_llm_payload(), error=error
            )

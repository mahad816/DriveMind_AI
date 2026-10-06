# Frozen decision: tool-orchestrated RAG

Status: architecture decision only; no runtime integration is implemented by this document.

## Baseline and experiment boundary

The production refactor starts from provider-independent Phase 1 commit `897d569ccb0e26a94155b7b6af7df9a1f9ddc26d` on `refactor/tool-orchestrated-rag`. Jev is removed from the intended runtime. The failed 15-question Jev planner remains preserved on `archive/jev-intent-experiments`; it will not receive another routing revision. Historical experimental packages retained in the baseline are evidence, not dependencies of the intended runtime.

## Runtime responsibility

The main LLM acts as the conversational agent and tool orchestrator. The initial read-only tool contracts will be:

- `files_query`: query eligible indexed file metadata.
- `resolve_file`: resolve a bounded file reference.
- `search_knowledge`: retrieve document-grounded evidence under a concrete scope.
- `file_evidence`: obtain authoritative evidence for a resolved file.

Python owns validation, internal IDs, scopes, authorization, retrieval, and citation construction. The agent receives opaque runtime handles rather than database UUIDs. Tool arguments and handles must be validated before use; unsupported or unresolved restrictions must not silently widen to the full collection. Drive access remains read-only.

## Retrieval and evidence boundary

Retrieval will move from `retrieve(question)` to `retrieve(RetrievalRequest)`. The request carries the concrete validated scope. Every vector, keyword, and metadata retriever must consume the same concrete scope rather than independently infer or omit restrictions.

`EvidenceChunk` and `EvidenceSection` remain separate. Chunks preserve authoritative text and source identity; sections assemble bounded context while retaining the identities of every contributing chunk. Generated answers or summaries are not authoritative evidence. Citations remain grounded in eligible source chunks and compatible with the existing source endpoint.

## Reference implementation and retained work

Onyx MIT non-ee code is a reference implementation for typed search requests, filter propagation, adjacent chunk/section expansion, and structured connector documents/hierarchy. The inspected reference is `onyx-dot-app/onyx` at `438b54447dd0e4e3b78a43457c911e340a881e5f`. No reference code is copied in this decision; any later adaptation must preserve the applicable file license and attribution. Enterprise `ee/` code is excluded.

Retain DriveMind's existing Drive sync, PostgreSQL/Qdrant hybrid retrieval, reciprocal rank fusion (RRF), evidence grading, and citation normalization. Preserve the existing linear and optional LangGraph grounded paths until an explicitly tested integration changes them.

## Scope of this checkpoint

This checkpoint freezes the direction only. It adds no tools, provider calls, routing changes, LangGraph changes, retrieval changes, database migrations, or deployment configuration. Read-only tool contracts are the next implementation step.

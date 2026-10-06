# Read-only tool contracts (Phase C)

The intended runtime uses one conversational agent to choose small read-only tools, rather than a separate routing classifier. This package defines contracts only: no agent, executors, database calls, provider calls, LangGraph imports, or retrieval integration.

## Initial tools

| Name | Strict arguments | Rich result / safe payload |
| --- | --- | --- |
| `files_query` | LIST, COUNT, LATEST, or OLDEST; explicit ALL_ELIGIBLE_INDEXED_FILES scope | Ordered internal file summaries, non-negative count, or zero/one selection; projection replaces IDs with file handles |
| `resolve_file` | Nonblank human reference, at most 1024 code points | RESOLVED, NOT_FOUND, or bounded AMBIGUOUS; never trusts the string as identity |
| `search_knowledge` | Nonblank query (8000 max), explicit ALL or 1–20 exact file handles, candidate limit 1–50 (default 20) | Up to 20 existing Phase 1 EvidenceSections; safe context with evidence and citation handles |
| `file_evidence` | Exactly one file handle and nonblank query | EvidenceSections for exactly one internal file, with no filename or corpus fallback |

LIST execution's default is filename Unicode casefold ascending, then stable internal file identity as tie-breaker. There is no sorting argument. The result's item order is authoritative: the first item means that actual returned item's handle, never an independent file lookup. LIST results are bounded to 100 items and ambiguous candidates to 10. Future executors must reject overflow explicitly or introduce a separately reviewed pagination contract; they must never silently truncate a purported complete result. LATEST/OLDEST may return null, and empty evidence is safe. Known/trustworthy source modification time is optional and must be timezone-aware; missing time must not be replaced with indexing time.

Folder, label, and modified-time restrictions are intentionally unavailable in executable tool scopes. Unknown fields and unsupported scopes fail validation, not full-collection fallback. Query text is content to search, not a replacement for validated scope. Later orchestration must preserve requested restrictions or decline them.

## Handles and safe results

A RuntimeHandleRegistry belongs to one request/turn. File handles use insertion order (`file_1`, `file_2`), and duplicate registration reuses a handle. Evidence/source handles similarly map privately to full EvidenceSections and chunk identities. Handle values are typed wrappers: `{"kind":"FILE","value":"file_1"}`. Unknown or wrong-kind handles raise controlled UNKNOWN_HANDLE errors. Handles are not authorization credentials, are not persisted, and must not be interpreted with another turn's registry. Later execution must revalidate eligibility/ownership independently.

Rich result != LLM-facing result. Only `to_llm_payload(registry)` is suitable for tool messages; never send a rich model's JSON directly. Internal UUIDs, retrieval scores, and private diagnostics are excluded from these explicit projections. Source text and filenames remain user data, not instructions; this projection removes internal identity metadata, not arbitrary sensitive strings embedded in a document's authoritative text.

EvidenceChunk/EvidenceSection are reused unchanged from Phase 1. Safe evidence includes an evidence handle, file handle, filename, authoritative context, and every member's opaque source handle plus context offsets/optional locator. The registry keeps the chunk-to-source mapping for later citation construction; public source endpoint URLs are not generated here. Distinct contexts with the same anchor receive distinct section handles. Safe section context is bounded to 32,000 code points; upstream execution must respect that budget without substituting generated summaries.

ToolContract exposes generic JSON-schema definitions, strict argument/result parsing, and typed safe projection. ToolRegistry contains exactly four canonical tools, sorted lexicographically; no aliases or execution dispatch. Provider-specific schema conversion belongs to a later adapter. Controlled errors are INVALID_ARGUMENT, UNKNOWN_HANDLE, NOT_FOUND, AMBIGUOUS, UNSUPPORTED_SCOPE, EMPTY_RESULT, and INTERNAL_ERROR, with fixed safe messages and optional separately excluded private diagnostics.

## Selection boundaries (examples, not a Python classifier)

- “How many files do I have?” → files_query COUNT.
- “List my files.” → files_query LIST.
- “What is the latest file?” → files_query LATEST.
- “Summarize report.pdf.” → resolve_file("report.pdf"), then file_evidence(returned handle, query).
- “What does our refund policy say?” → search_knowledge(query, explicit full eligible scope).
- “Summarize the first one.” after a FileListResult → file_evidence(previous safe result.items[0].handle, query).

Python validates scopes, identities, result boundaries, and later execution. It does not classify natural-language requests. IntentFrame / ExecutionStep can later be derived or recorded from validated tool calls; they are not model-generated upfront. Handle scopes are model-facing; Phase 1 RetrievalScope remains the concrete internal UUID-bearing boundary after later deterministic resolution. No second concrete retrieval contract is introduced here.

## References and next phases

Conceptual reference only: Onyx MIT non-ee at `438b54447dd0e4e3b78a43457c911e340a881e5f`, specifically `backend/onyx/tools/interface.py`, `backend/onyx/tools/models.py` (rich vs LLM-facing ToolResponse, controlled errors), `backend/onyx/llm/models.py` (tool definitions), `backend/onyx/tools/tool_implementations/search/search_tool.py`, and `backend/onyx/context/search/models.py` (typed search boundaries). This implementation is original DriveMind code; no source fragments, emitter machinery, enterprise ACLs, SQL sessions, or provider frameworks were copied.

LangGraph/tool execution integration is Phase D. Scoped retrieval integration is Phase E. Existing production RAG paths remain unchanged in Phase C.

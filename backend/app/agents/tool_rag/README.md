# Read-only tool contracts (Phase C)

The intended runtime uses one conversational agent to choose small read-only tools, rather than a separate routing classifier. Contract modules remain provider-independent. Phase D1 `execution/` adds deterministic retrieval/tool execution; Phase D2 adds a separate opt-in LangGraph loop and native provider adapter without changing production routing.

## Initial tools

| Name | Strict arguments | Rich result / safe payload |
| --- | --- | --- |
| `files_query` | LIST, COUNT, LATEST, or OLDEST; explicit ALL_ELIGIBLE_INDEXED_FILES scope | Ordered internal file summaries, non-negative count, or zero/one selection; projection replaces IDs with file handles |
| `resolve_file` | Nonblank human reference, at most 1024 code points | RESOLVED, NOT_FOUND, or bounded AMBIGUOUS; never trusts the string as identity |
| `search_knowledge` | Nonblank query (8000 max), explicit ALL or 1–20 exact file handles, candidate limit 1–50 (default 20) | Up to 20 existing Phase 1 EvidenceSections; safe context with evidence and citation handles |
| `file_evidence` | Exactly one file handle; FULL_DOCUMENT or QUERY_FOCUSED (requires a nonblank query) | EvidenceSections for exactly one internal file, with no filename or corpus fallback |

LIST execution's default is filename Unicode casefold ascending, then stable internal file identity as tie-breaker. There is no sorting argument. The result's item order is authoritative: the first item means that actual returned item's handle, never an independent file lookup. LIST results are bounded to 100 items and ambiguous candidates to 10. Phase D1 LIST exposes total_count, returned_count, and truncated explicitly; it never claims a partial list is complete. Ambiguous reference overflow returns a controlled AMBIGUOUS error rather than silently trimming candidates. LATEST/OLDEST may return null, and empty evidence is safe. Known/trustworthy source modification time is optional and must be timezone-aware; missing time must not be replaced with indexing time.

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

## Phase D1 execution

ExecutionContext is application-owned: current user UUID, AsyncSession, one RuntimeHandleRegistry, and an optional injected HybridRetriever for tests/runtime configuration. ToolExecutor validates the canonical name and strict JSON arguments, invokes one of four fixed functions, and returns separate rich and safe payloads. Controlled failures never trigger a broader query; unexpected exceptions retain only an excluded private diagnostic and fixed INTERNAL_ERROR message. No model can supply user_id, session, or raw IDs.

Every new execution query enforces current ownership and INDEXED status. COUNT uses SQL COUNT. LIST loads at most 10,001 metadata rows, rejects inventories above the explicit 10,000-file safety cap, applies Python Unicode casefold/name then UUID ordering, and returns the first 100 with explicit completion metadata. The existing inventory code caps global metadata at 1,000 and display at 20; the new tool cap is explicit rather than assumed. This suits the single-user portfolio scope; large inventories need a separately reviewed stored sort-key/pagination design. Latest/oldest use stored modified_at with UUID ascending ties and nulls last. Source-time provenance is not stored reliably enough for strict arbitrary date filtering: public summaries omit modified time rather than expose a fallback timestamp as trustworthy.

resolve_file uses a case-sensitive exact SQL tier first, then Unicode casefold exact matching over the bounded eligible metadata snapshot; no punctuation/whitespace normalization, fuzzy matching, or vector lookup. Duplicate matches are ambiguous. Both tiers exclude other users and non-indexed files.

Model-facing ALL/exact-handle scopes resolve into the existing Phase 1 RetrievalRequest/RetrievalScope, not a second internal request model. Empty exact requests are now rejected; an empty ResolvedFileScope can still represent zero eligible files elsewhere, never ALL. Handle eligibility is checked before retrieval, and returned evidence file identities are checked again. search_knowledge and file_evidence use the same hybrid stack. One returned chunk becomes one authoritative EvidenceSection; no neighboring expansion. Existing per-strategy candidate limits, final top-k ranking, evidence grading, and payload budgets bound evidence. Oversized final payloads fail explicitly rather than replacing or secretly trimming source text.

Vector, keyword, and metadata retrievers accept the same RetrievalRequest. Scoped SQL uses one eligibility predicate (user + INDEXED + optional exact UUID set), including keyword filename/date/phrase paths and vector hydration. Qdrant matches the existing internal UUID-string payload `drive_file_id` with MatchAny (client 1.18.0); ALL keeps the existing vector candidate search and applies ownership during hydration. Query-derived metadata hints may score candidates but do not become additional concrete scope filters on this typed path. Parallel retrieval, RRF, weighted reranking, and evidence grading are retained. Each scoped strategy uses a separate AsyncEngine-bound read session, so parallel SQL does not run on one AsyncSession. An unsupported session binding fails closed. The original string path retains its existing session behavior. Failures propagate without an unscoped retry.

The temporary `retrieve(str)`/`retrieve_with_grade(str)` compatibility path keeps existing RagService and drive_graph behavior. It retains the existing single-user legacy assumptions and must not be used by new tools, which always supply RetrievalRequest. No production route is switched to tools here. One conversational turn/run owns its registry; later LangGraph state will retain that registry across calls within the run, not globally or persistently.

Onyx non-ee conceptual references also include `backend/onyx/context/search/pipeline.py` (`_build_index_filters`, `search_pipeline`) and `context/search/models.py` (BaseFilters, IndexFilters, ChunkSearchRequest, ChunkIndexRequest): application resolution produces concrete filters consumed consistently. No source code is copied, and no OpenSearch/enterprise abstractions are adopted.

Phase D2 will add the LangGraph/LLM agent loop. Adjacent-context expansion remains later work. Existing production routing, frontend, and database schemas are unchanged.


## Phase D2 agent loop

`ToolRagAgentService.run` is an explicit opt-in entry point, not wired into RagService or an API endpoint. The separate AgentChatService protocol accepts canonical messages plus exactly four ToolDefinitions and returns text and/or native ToolCallRequests. Existing ChatService answer-generation signatures are untouched. `app/llm/openai_agent_service.py` reuses the existing configurable OpenAI client/model setup, uses chat completions native function calls with AUTO, and does not parse prose/XML or add semantic retries. SDK transport retries retain the existing client's defaults.

Topology: START → agent → FINAL/finalize, TOOLS/execute_tools → agent, or ERROR/fail_safe → END. No classifier, planner, rewrite, verifier, or extra model. Multiple calls execute sequentially in provider order through D1 ToolExecutor. SYSTEM/USER/ASSISTANT-with-calls/TOOL-with-matching-ID histories stay canonical. Only safe projections reach the next LLM step; rich results and private diagnostics remain internal.

Installed LangGraph 1.2.8 run-scoped ExecutionContext injection owns the registry outside message state. Every service invocation creates a fresh registry; it survives all calls within that run and is never global or persisted. Internal AgentState holds the original question, user identity, message history, tool history, observations, cycles, final answer, authoritative EvidenceSections and opaque citation handles. retrieval_count is the number of unique accumulated evidence chunks. Model-written citations never create authoritative evidence; final citations are derived from retained authoritative ranges and mapped source handles.

At most six LLM steps, at most eight calls in one step. A tool request on the sixth step is cancelled before execution, with a deterministic cycle-limit answer and matching cancellation tool messages. Reused call IDs, corrupted state, provider errors, and oversized model history fail closed. History is bounded at 128,000 serialized characters without silent truncation. Finalization requires text with no tool calls. Expected tool errors are ordinary safe tool messages, allowing the same model to clarify. Missing call IDs/names or an empty provider result are invalid responses. Malformed argument JSON with valid ID/name is marked INVALID_ARGUMENT, never executed or repaired, and receives a matching safe tool error; raw malformed text is not retained in model history.

The system prompt treats user/tool text as untrusted data, instructs actual-handle dependencies, rejects guessing/broadening after unresolved references, and declines unsupported folder/label/time scopes. These instructions require live evaluation: mock tests prove protocol and execution behavior, not model semantic fidelity or groundedness. No live provider calls, checkpoint persistence, Redis, background workers, adjacent expansion, or production integration are introduced.

Additional conceptual Onyx non-ee references at the same frozen commit: `backend/onyx/chat/llm_loop.py`, `chat/llm_step.py`, `tools/tool_runner.py`, `tools/models.py`, `llm/models.py`: native text vs calls, matching call IDs, safe tool responses, sequential async execution and bounded cycles. No upstream code, emitter/streaming infrastructure, personas, memory, enterprise ACLs, MCP, or threadpool runner is copied.

## Single development revision

`FULL_DOCUMENT` reads only the resolved, owned INDEXED file through PostgreSQL,
ordered by document identity then chunk index. No similarity query, Qdrant or
hybrid search is used. Each SQL row is clipped to the application context budget
(`rag_max_context_chars`, at most 32,000 characters), and at most 20 chunks are
loaded. Returned source text collectively stays within that budget. The original
chunk/document identities remain attached to exact source prefixes; totals of
all nonblank indexed chunks and characters produce explicit `truncated` metadata.
`QUERY_FOCUSED` retains exact-file hybrid retrieval. This is not adjacent expansion
or a map/reduce summary pipeline.

Before ALL inventory/corpus execution, a finite guard recognizes `in/within/under/from
... folder`, `tagged/labelled/labeled ...`, and `files/documents/items changed/modified/
updated this/last/after/before/since/between/on/in ...`. It returns UNSUPPORTED_SCOPE
before DB/retrieval access. It does not select capabilities or operations, interpret
arbitrary filters, or claim coverage of every linguistic restriction. Original
current-turn text is application context, never model arguments. New forms require
separate safety review; this guard is not a full semantic parser.

Only explicit `[source_N]` / `[evidence_N]` citation markers map to retained sources.
Unknown source markers cannot create citations. Existing numeric citation
normalization is reused; when markers are absent, an honest “Sources consulted”
footer lists actual evidence. This records consulted provenance, not a proof that
every generated claim is entailed. Bare runtime tokens and UUID-shaped final prose
fail closed without mutating source text or running a repair model. CitationItem
objects remain internal and retain the real source endpoint identity. No public
API, RagService, old graph or frontend integration changes here.

Concepts only from Onyx MIT non-ee commit
`438b54447dd0e4e3b78a43457c911e340a881e5f`: `DocumentSectionRequest`
(`backend/onyx/document_index/interfaces.py`), `_retrieve_adjacent_chunks` /
`merge_overlapping_sections` (`tools/tool_implementations/search/search_utils.py`),
and `InferenceChunk` / `InferenceSection` (`context/search/models.py`).
Document-local identity reads and source-member provenance inform this code;
no upstream fragments, OpenSearch code or adjacent expansion are copied.

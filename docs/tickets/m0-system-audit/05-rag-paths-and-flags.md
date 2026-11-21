# 05: RAG execution paths and feature flags (A1)

**Spec:** docs/specs/m0-system-audit.md
**What to build:** The Owner knows which code answers each top-level route (chitchat, file inventory, file target, grounded) under the local defaults and under the hosted flags, for both chat entry points, and what happens when the model provider fails.
**Blocked by:** None (can start immediately). Ticket 01's hosted flag values are a soft input: any flag not read stays `Unverified`.
**Status:** ready-for-agent
**Progress:** resolved

## Scope

- Trace `RagService.ask` routing and the flags that matter: `TOOL_RAG_AGENT_ENABLED`, `AGENT_GRAPH_ENABLED`, `HYBRID_RETRIEVAL_ENABLED`, `CLAIM_CHECK_ENABLED`, `CHAT_STREAMING_ENABLED`, and demo mode. Produce, per top-level route, the code path selected under local defaults and (once known) hosted flags, naming entry points.
- Cover both entry points: the single `/chat` request and conversation turns (including streaming). State whether they reach the same path.
- Record behavior on provider failure in the path production would reach: confirm or refute the v1 spec requirement that it never produces an ungrounded answer. Where a focused deterministic test with a faked provider is possible, add it (strict expected failure if it reveals a defect, passing if it protects correct behavior).
- Note anything that contradicts `AGENTS.md`, `docs/ARCHITECTURE.md` or `docs/TOOL_RAG_ARCHITECTURE.md`.

## Out of scope

Switching, disabling or deleting any path (ADR 0001 steps 2 and 3); measuring answer quality or follow-up quality (M1, M4); any model call; fixing defects.

## Inspect

`backend/app/services/rag_service.py`, `backend/app/agents/tool_rag/`, `backend/app/agents/drive_graph/`, `backend/app/retrieval/` (router), `backend/app/api/chat.py`, `backend/app/api/conversations.py`, `backend/app/core/config.py`, `docs/adr/0001-single-answering-path.md`, `docs/TOOL_RAG_ARCHITECTURE.md`.

## Deliverables

`## Findings` in this ticket: route-by-flag path table (local defaults / hosted), entry-point comparison, provider-failure behavior, documentation contradictions. Tests only if meaningful and deterministic.

## Needs

No paid APIs (faked providers only). No live infrastructure. Docker only if a chosen test needs the database fixtures.

- [x] For each of the four top-level routes, the answering code path is named under local defaults and under hosted flags (or `Unverified` per unread flag).
- [x] `/chat` and conversation turns (including streaming) are each traced, with entry points named, and stated to reach the same path or not.
- [x] Provider-failure behavior in the production-reached path is described with evidence, and the "never ungrounded" requirement is marked Verified, Defect or Unverified.
- [x] Contradictions with existing documentation are listed.
- [x] Any added test is deterministic and paid-API-free; a defect test fails today for its stated reason.
- [x] No application code changed.

## Findings

Audited 2026-11-21 on branch `feature/v2-state-performance`, base commit `8bce002`. Static reading of the code plus local test runs with faked providers. No application code was changed (one new test file and this ticket only). No hosted system was contacted: no request was sent to Railway, Google or OpenAI. **Nothing is running on Railway today:** ticket 01 H1 says "None is deployed" (the latest deployments are `REMOVED`) and H14 shows all four services `Offline`. So "hosted" and "production" below mean **the hosted flag values from ticket 01 (H2-H9, all Owner-reported) applied to the code at HEAD**, i.e. what a deploy of HEAD with those variables would run. The commit of the removed deployments is `Unverified` (H1); ticket 01's date inference (item 6) says that *if* the last deployment was built from this branch, its code did not have the claim check.

### Verdict

- **Production (hosted flags) answers every route through one path: the tool-calling agent.** With `TOOL_RAG_AGENT_ENABLED` on, `RagService.ask` hands the question to `ToolAgentAdapter` before the top-level router runs (`rag_service.py:141-173`; `classify_query` is first called at `:175`). The four routes are then not code branches: a small intent model plus the agent's choice of tool decide them. `AGENT_GRAPH_ENABLED` and `HYBRID_RETRIEVAL_ENABLED` have no effect on this path.
- **Local defaults answer through the legacy linear path**, which has six router outcomes, not four (it adds conversation-history recall and collection summary). The code default (`tool_rag_agent_enabled: bool = False`, `config.py:94`) and production therefore run different systems; the evaluation harness measures the agent (`AGENTS.md`), which is the hosted one.
- **Both entry points reach the same path** under the same flags: `/chat` and conversation turns both call `RagService.ask` with the same settings. Streaming changes only how the agent's model call is made (one streamed call with no retries instead of the SDK's retrying call), not which path answers.
- **"Provider failure never produces an ungrounded answer": Verified for the answering model**, reading "ungrounded" as "not built from retrieved evidence with validated citations" (the spec does not define it). On the production path this holds including failure after evidence was retrieved and during the citation-correction retry (new tests). **One qualification for the Owner (O1):** if the **claim-check** model fails, the check fails open and the agent's answer is published without the claim-level check, by design (`config.py:98-99`, KI-002). The answer is still built only from retrieved evidence with validated citations, but it can contain the unsupported statements KI-002 exists to remove: the new characterisation test publishes an unsupported "90 days" statement with a real citation after a claim-check provider failure. That is the same output as running with `CLAIM_CHECK_ENABLED=false`. Under a stricter reading of "ungrounded" (every statement supported) this would be a defect, so it is recorded as an Owner decision rather than either a pass or a known issue; see section 4.
- No new known issue. Eight documentation contradictions are listed and deliberately deferred to ticket 09 (this audit fixes nothing).

### Search method

1. Read `services/rag_service.py`, `services/tool_agent_service.py`, `agents/tool_rag/` (`conversation.py`, `agent_service.py`, `graph.py`, `finalization.py`, `claim_check.py`), `llm/openai_service.py`, `llm/openai_agent_service.py`, `llm/factory.py`, `llm/base.py`, `retrieval/query_router.py`, `api/chat.py`, `api/conversations.py`, `services/conversation_chat_service.py`, `services/chat_stream.py`, `core/config.py`, and the error handling of `agents/drive_graph/nodes.py` (grep for `except|raise|fallback`).
2. `grep -rn "hybrid_retrieval_enabled" backend/app`: read only in `rag_service.py:100` and `:521`, both legacy-only.
3. Frontend callers: `grep -rnE "/chat['\"\`]|turns/stream|/turns['\"\`]|provisional"` over `frontend/lib`, `app`, `components`; read `components/chat/chat-interface.tsx`, `lib/api/conversations.ts:412-515`, `components/chat/message-thread.tsx:66-68`.
4. Existing failure tests: `grep -rln "PROVIDER_ERROR|CLASSIFIER_ERROR|CHECK_ERROR|stream_step|raise ChatError"` over `backend/tests`, then read the matches named in the failure table.
5. Documents compared: `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/TOOL_RAG_ARCHITECTURE.md`, `docs/adr/0001-single-answering-path.md`, `docs/KNOWN_ISSUES.md` (KI-002), and the `RagService` docstrings.

### 1. Flags that decide the path

| Flag | Code default (`config.py`) | Hosted (ticket 01) | Effect on the answering path |
|---|---|---|---|
| `TOOL_RAG_AGENT_ENABLED` | off (`:94`) | on (H2) | On: every question goes to the tool agent; the router, LangGraph and the legacy generators are never reached. |
| `AGENT_GRAPH_ENABLED` | off (`:97`) | off (H3) | Legacy only: grounded questions use LangGraph instead of the linear pipeline (`rag_service.py:478`). Ignored when the tool agent is on. |
| `HYBRID_RETRIEVAL_ENABLED` | on (`:76`) | on (H4) | Legacy only: hybrid or vector-only retriever (`rag_service.py:100-103`, `:521`). **The tool agent always uses `HybridRetriever`**: with the flag off, `RagService` passes `None` (`:144-148`) and the adapter builds one anyway (`tool_agent_service.py:163`). |
| `CLAIM_CHECK_ENABLED` | on (`:100`) | not set, so HEAD's default (on) applies (H5) | Tool agent only, and not in demo mode (`tool_agent_service.py:112-128`): one extra small-model call that removes unsupported statements. Whether the deployed code has the claim check at all is `Unverified` (ticket 01, item 6). |
| `CHAT_STREAMING_ENABLED` (backend) | off (`:96`) | on (H6) | Enables `POST /conversations/{id}/turns/stream`; it answers 404 when off and 409 when the tool agent is off (`conversations.py:225-228`). Does not change the path. |
| `NEXT_PUBLIC_CHAT_STREAMING_ENABLED` (frontend build) | unset | **not read (Unverified)** | Decides whether the browser calls `/turns/stream` or `/turns` (`lib/api/conversations.ts:420-422`). |
| `DEMO_MODE` (backend and `NEXT_PUBLIC_DEMO_MODE`) | off (`:21`) | off (H9; frontend value not read) | Demo: the UI uses `/chat` only (`chat-interface.tsx:9`), the conversation routes refuse (`require_normal_mode`), and the tool agent skips both the intent model and the claim check (`tool_agent_service.py:116`, `:134`). |

"Local defaults" means the code defaults above. The developer's own `.env` was not read (it may hold credentials), so what a given local machine runs is `Unverified`.

### 2. Route-by-flag path table

The tool agent has no top-level router. Its rows say which part of the one agent path handles a question of that kind; the choice is a model decision (intent model, then the agent's tool calls), not a code branch.

| Route (question kind) | Local defaults: legacy linear, hybrid retriever | Hosted: tool agent, claim check on (on HEAD) |
|---|---|---|
| **Chitchat** ("hi", "what can you do") | `classify_query` exact-phrase set (`query_router.py`) → `RagService._ask_normalized` chitchat branch (`rag_service.py:262-290`) → `OpenAIChatService.generate_direct_answer` (one model call, no retrieval, no citations). | `ToolAgentAdapter.answer` → `classify_intent` (`conversation.py:80-105`, one JSON model call) → if greeting/thanks/farewell/about_assistant/out_of_scope, a **server-owned** reply from `REPLIES` (no model prose, no citations; `tool_agent_service.py:143-158`). Anything else, or a failed classifier, goes to the agent. In demo mode the intent call is skipped and the agent answers; a bare greeting with no tool call is rendered from the `_SOCIAL` allowlist (`finalization.py:30-41`, `:102-103`). |
| **File inventory** ("how many files", "list my resumes") | Router → `FileInventoryRetriever` SQL → `generate_inventory_answer` (`rag_service.py:298-343`); no citations. | Agent calls `files_query` → the answer is **rendered deterministically from the metadata result**, never from model prose (`provenance_response`, `finalization.py:164-169`); no citations. |
| **File target** (a named file) | Router → `FileTargetRetriever` → `generate_file_target_answer` with that file's chunks, citations normalised (`rag_service.py:346-425`). Not indexed / not found → fixed server text (`:427-474`). No resolvable target → falls through to grounded. | Agent calls `resolve_file` then `file_evidence`; prose is allowed only after a successful read of that exact file (`finalization.py:109-172`); then the claim check (`graph.py:162-174`) and citation finalisation (`finalize_answer`). |
| **Grounded** (everything else) | `HybridRetriever.retrieve_with_grade` (vector + keyword + metadata, graded) → `generate_grounded_answer` → `normalize_answer_citations` (`rag_service.py:510-628`); no evidence → `no_evidence_answer`. With `AGENT_GRAPH_ENABLED` on: `run_drive_graph` instead (`:478-507`). | Agent calls `search_knowledge` (hybrid) → model answer → claim check → `finalize_answer`. A successful read with no evidence is replaced by `no_evidence_answer` (`tool_agent_service.py:207-217`). |
| *Legacy-only extra:* conversation-history recall | Deterministic recall from supplied history (`rag_service.py:231-259`), no model call. | No equivalent branch: the bounded history (6 messages / 6000 characters, identifiers masked) is given to the agent as context (`tool_agent_service.py:54-68`). |
| *Legacy-only extra:* collection summary | `_summarize_collection` (`rag_service.py:630-692`). | No equivalent branch: the agent's tools. |

**Legacy, with history (conversation turns only):** before routing, a non-chitchat follow-up is rewritten by one model call (`rewrite_followup`, `rag_service.py:176-195`). The tool agent does no rewrite; it receives the history.

### 3. Entry-point comparison

| | `POST /api/v1/chat` | `POST /api/v1/conversations/{id}/turns` | `POST /api/v1/conversations/{id}/turns/stream` |
|---|---|---|---|
| Used by | Demo UI only (`demo-chat-interface.tsx:244`) | Normal UI when the frontend streaming flag is off (`conversations.ts:422`) | Normal UI when the frontend streaming flag is on (`conversations.ts:421`, `:451`) |
| Route handler | `ask_grounded_question` (`api/chat.py:26-72`) | `submit_conversation_turn` (`conversations.py:197-215`) | `stream_conversation_turn` (`conversations.py:218-249`) |
| Service | `RagService(db)`, query history saved unless demo (`chat.py:21-23`, `rag_service.py:97`) | `ConversationChatService.submit` → `RagService(..., persist_query_history=False)` (`conversation_chat_service.py:104-106`, `:282-288`); the result is saved with the turn (`:305-331`) | Same `submit`, inside `event_stream` with a `stream_sink` set (`chat_stream.py:36-92`) |
| History | Only if the client sends it | Last 4 completed pairs from PostgreSQL, 24 000-character bound (`conversation_chat_service.py:149-166`) | Same |
| Demo mode | Allowed (demo user) | Refused (`require_normal_mode`; constructor also refuses, `:89-90`) | Refused |
| Extra gates | none | none | 404 unless `CHAT_STREAMING_ENABLED`; 409 unless `TOOL_RAG_AGENT_ENABLED` |
| Model call in the agent | `chat.step` (OpenAI SDK default retries) | `chat.step` | `chat.stream_step`, `max_retries=0` (`openai_agent_service.py:136`); provisional text is streamed (next section) |
| Failure surface | `ChatError` etc. → HTTP 503 (`chat.py:53-63`) | Turn `FAILED` (`GENERATION_OR_STORAGE_FAILED`) or `INTERRUPTED` (timeout), HTTP 503, no result row (`:342-381`) | Same, delivered as an SSE `error` event with the receipt |

**Same path?** Yes. All three call `RagService.ask` with the same `Settings`, so the same flag selects the same path. The differences are history source, persistence, demo access and, for streaming, the provider call method. Under local defaults the streaming endpoint is unavailable (404), so the normal UI must use `/turns` with the streaming build flag off.

### 4. Provider-failure behaviour

**Production path (tool agent):**

| Failure | Behaviour | Evidence |
|---|---|---|
| Intent model errors, times out (10 s) or returns garbage | Treated as `document_question`, so the agent answers normally (fail-safe direction). | `conversation.py:95-105`; `test_intent_gate.py::test_classifier_failure_never_blocks_a_question` |
| Agent model fails on the first call | `PROVIDER_ERROR` (or `MALFORMED_RESPONSE`) → `fail_safe` → the adapter raises `ChatError` → `/chat` 503, nothing saved, no legacy fallback. | `graph.py:88-91`, `:211-229`; `tool_agent_service.py:197-201`; **new** `test_provider_failure_paths.py` (`first-model-call`). The existing `test_tool_agent_api.py::test_failures_no_fallback_or_sensitive_error` accepts 200 or 503, so it did not pin this. |
| Agent model fails **after evidence was retrieved** | Same: 503, nothing saved, retrieved text not in the response. | **new** (`after-evidence-was-retrieved`) |
| Agent model fails during the KI-026 citation-correction retry | Same. | **new** (`during-the-citation-correction-retry`) |
| Streaming: provider stream errors or ends incomplete | `AgentResponseError` → `MALFORMED_RESPONSE` → same `ChatError`. Provisional text already sent is plain text with citations and identifiers withheld (`chat_stream.py:23-33`), is shown only while the message is loading under "Generating · Answer is not yet verified" (`message-thread.tsx:66-68`), and the terminal `error` event raises instead of publishing (`conversations.ts:497-499`). It is never saved. | `test_chat_streaming.py::test_provider_error_or_incomplete_generation_fails_closed` |
| Conversation turn: any of the above | Turn `FAILED`, HTTP 503, no `QueryHistory`, no result. | `test_conversation_chat.py::test_failure_never_publishes_orphaned_success[model]` (needs PostgreSQL; not re-run here) |
| No `OPENAI_API_KEY` | `ChatConfigurationError` inside the agent call → `PROVIDER_ERROR` → 503. The intent call fails the same way and falls through. | `openai_service.py:62-63`; code reading |
| Whole run exceeds 120 s | `/chat`: the adapter's own 120 s limit raises `ChatError("timed out safely")` → 503. Conversation turn: both limits are 120 s; the turn's outer budget starts earlier, so it most likely fires first → `TimeoutError` → `INTERRUPTED` (`GENERATION_TIMEOUT`). If the adapter's limit fired first, its `ChatError` would give `FAILED` (`GENERATION_OR_STORAGE_FAILED`). Either way: 503, nothing published. | `tool_agent_service.py:229-231`; `conversation_chat_service.py:272`, `:342-346`, `:368-372`; code reading |
| **Claim-check model fails** (error, 20 s timeout, malformed reply) | **Fails open:** the answer is published unchecked, with its citations. | `claim_check.py:198-209`, `graph.py:165-174`; `test_claim_check.py::test_a_failing_model_call_means_unchecked_not_unsupported`, `::test_a_checker_that_raises_cannot_take_answering_down`; **new** `test_claim_check_model_failure_publishes_the_unchecked_answer` (an unsupported "90 days" statement is published with a real citation) |

**Legacy path (local defaults):** every generation call goes through `OpenAIChatService._complete`, which turns `APIError` into `ChatError` and an empty completion into `ChatError` (`openai_service.py:82-91`); citation validation failing twice raises `ChatCitationValidationError` (`:210`). All reach the 503 handler. Evidence: code reading. `test_chat_api.py::test_chat_openai_failure_returns_503` mocks `RagService.ask` as a whole, so it only proves the route maps `ChatError` to 503, not that the legacy generators raise it. The LangGraph rewrite node falls back to a heuristic rewrite on `APIError` (`nodes.py` `_rewrite_with_openai`), which changes the query, not the answer. The legacy path has no claim check (KI-002 "Scope").

**Requirement status: Verified** for the answering model on the production path (tests) and on the legacy path (code reading), with "ungrounded" read as "not built from retrieved evidence with validated citations". **Open Owner decision O1 (claim-check fail-open):** keep it (current design: availability over a second check; the answer is still evidence-built and citation-validated), or treat an unchecked answer as not good enough for the spec and fail closed or mark the answer as unchecked. Changing it is out of scope here (no fixes) and would also need the evaluation numbers in `docs/EVALUATION_RESULTS.md` for KI-002.

### 5. Documentation contradictions (for ticket 09)

1. `AGENTS.md` Architecture: "`RagService` routes every question first." With the tool agent on (production), no routing happens; the router runs only on the legacy path (`rag_service.py:141` vs `:175`). The same paragraph later says the agent is used "instead", so the sentence is half right.
2. `AGENTS.md` Known Important Constraints: "Hybrid retrieval and LangGraph are independently controlled by `HYBRID_RETRIEVAL_ENABLED` and `AGENT_GRAPH_ENABLED`." Both are legacy-only; the tool agent always uses hybrid retrieval (section 1).
3. `AGENTS.md` Core Flows, "Query": describes only `POST /chat` → router. The normal UI uses conversation turns (`/conversations/{id}/turns[/stream]`); `/chat` is the demo UI's endpoint.
4. `AGENTS.md` and `docs/ARCHITECTURE.md:33` list four or five router outcomes; the router has six (`COLLECTION_SUMMARY` is missing from both; `CONVERSATION_HISTORY` is missing from `AGENTS.md`).
5. `docs/ARCHITECTURE.md` does not mention the tool agent, the intent model, the claim check, conversation turns or streaming at all; its "Query" paragraph describes the legacy path as the system.
6. `docs/TOOL_RAG_ARCHITECTURE.md:3` and `:34` say no runtime integration, tools or provider calls exist and that tool contracts are "the next implementation step". All four tools, the native provider adapter and the `RagService` integration exist. It is a frozen decision record, so it may be intentionally historical, but nothing marks it as superseded.
7. `docs/ARCHITECTURE.md:13`: "Conversation history is stored in browser localStorage." Conversations and their turns are stored in PostgreSQL through `/conversations` (`conversation_repository.py`); `AGENTS.md` already says so.
8. `RagService` class and `ask` docstrings (`rag_service.py:73-82`, `:123-129`) say routing "applies to ALL execution paths" and "runs first regardless of agent_graph_enabled"; neither mentions the tool-agent branch, which skips routing.

ADR 0001 matches the code (three paths exist, none switched). Its step 1 needs the deployed configuration, which this ticket could only take from ticket 01's Owner-reported values.

### 6. Tests added (no application code changed)

`backend/tests/test_provider_failure_paths.py`, 4 tests, no database, no network, faked providers, pass today:

- `test_answering_model_failure_returns_503_and_publishes_nothing` (3 cases: first call, after an evidence read, during the citation-correction retry). Through the real `/chat` route, `RagService`, `ToolAgentAdapter` and agent graph with a scripted model and retriever. Asserts 503, no saved row, no provider text or evidence text in the response, every scripted step consumed, the retriever called when expected, and no legacy generator awaited. Protective.
  Limit: the scripted model is injected (`chat=`), so the adapter builds no OpenAI client and the intent model and claim check are both off (`tool_agent_service.py:100-131`). In production the claim check would also run on the first draft before the citation-retry failure; that does not change the outcome (the failure still ends the run), but this is not the exact production call sequence.
- `test_claim_check_model_failure_publishes_the_unchecked_answer`: characterises the fail-open design (O1). This one pins behaviour the Owner may change, on purpose: O1 is the decision the requirement status depends on, and KI-002 already documents fail-open as intended. If the Owner decides it is a defect, this test becomes the strict expected failure for the new known issue.

Not added: a conversation-turn failure test (exists, needs PostgreSQL), an intent-gate failure test and a streaming failure test (both exist), a test pinning that `HYBRID_RETRIEVAL_ENABLED=false` is ignored by the tool agent (no requirement or decision rests on it, and nothing documents it as intended; recorded as a code fact for ticket 09 instead).

### Verification (2026-11-21)

- **Focused:** `env -u OPENAI_API_KEY uv run pytest -q tests/test_provider_failure_paths.py`: 4 passed in 0.13 s (no database, no network). `ruff check` and `ruff format --check` clean on the file; `basedpyright` 0 errors on it.
- **Container-free backend suite, once** (no container variables, `OPENAI_API_KEY` unset, the slow public-PDF test deselected): `2237 passed, 776 skipped, 1 deselected, 2 xfailed` in 41.9 s, no failure. The skips are the PostgreSQL/Qdrant tests, so this does not include `test_conversation_chat.py`. The container suite was not run (no database test was added).
- **Repository-wide:** `ruff check app tests` and `ruff format --check app tests` clean (347 files); `basedpyright app tests` 48 errors, the unchanged baseline.
- **Independent review** (Standards and Spec sub-agents, in parallel): no hard Standards violations, no scope creep. The Spec review checked about 45 citations; corrections applied above: nothing is deployed (H1/H14), the "ungrounded" reading stated explicitly, the legacy-path evidence is code reading, the conversation timeout outcome, two line numbers, the conditional wording of ticket 01's inference, the test's injected-model limit, and the missing `ARCHITECTURE.md:13` contradiction. Standards cleanups applied: the evidence text derived from the fixture, a clearer parameter name, this Verification section, and consistent reasoning for which behaviours are pinned.
- **Not run:** mypy on `app` (no application code changed), frontend suite (untouched).

### Caveats (confirmed and unverified, together)

- **Hosted means HEAD plus Owner-reported flags; nothing is deployed today** (ticket 01 H1, H14). The frontend build flags (`NEXT_PUBLIC_CHAT_STREAMING_ENABLED`, `NEXT_PUBLIC_DEMO_MODE`) were not read (`Unverified`). The O1 question arises on the next deploy of HEAD, where `CLAIM_CHECK_ENABLED` unset means the claim check is on.
- **Which route a question "is" on the tool path is a model decision.** The table names the code that handles each kind; it does not claim the intent model or the agent classifies any particular question correctly (that is M1/M4 quality work).
- The conversation-turn failure behaviour rests on an existing PostgreSQL test that I did not re-run, plus code reading.
- The streaming UI claim (provisional text hidden after an error) is from reading `message-thread.tsx` and `conversations.ts`, not from a browser run or a frontend test I ran.
- The developer's local `.env` was not read, so "local defaults" are the code defaults.

## Comments

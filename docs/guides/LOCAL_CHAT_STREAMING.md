# Local chat streaming acceptance

This feature is disabled by default and can be enabled explicitly in the existing
Railway beta. No hosted settings, database migrations, credentials, retrieval rules
or indexing controllers have been changed by this preparation work. See
[the beta rollout plan](RAILWAY_CHAT_STREAMING_ROLLOUT.md) before enabling it.

## Release file manifest

The release contains only these streaming-related files:

- `backend/Dockerfile`
- `backend/app/agents/tool_rag/graph.py`
- `backend/app/api/conversations.py`
- `backend/app/core/config.py`
- `backend/app/llm/openai_agent_service.py`
- `backend/app/services/chat_stream.py`
- `backend/app/services/conversation_chat_service.py`
- `backend/tests/streaming_preview.py`
- `backend/tests/test_chat_streaming.py`
- `backend/tests/test_chat_streaming_api.py`
- `backend/tests/test_chat_streaming_lifecycle.py`
- `docs/guides/LOCAL_CHAT_STREAMING.md`
- `docs/guides/RAILWAY_CHAT_STREAMING_ROLLOUT.md`
- `frontend/Dockerfile`
- `frontend/components/chat/message-thread.streaming.test.tsx`
- `frontend/components/chat/message-thread.tsx`
- `frontend/components/chat/server-chat-interface.tsx`
- `frontend/components/providers/session-browser-boundary.test.tsx`
- `frontend/deploy/api-proxy.mjs`
- `frontend/deploy/api-proxy.test.mjs`
- `frontend/lib/api/chat-stream.test.ts`
- `frontend/lib/api/client.ts`
- `frontend/lib/api/conversations.ts`
- `frontend/lib/conversations/server-controller.test.tsx`
- `frontend/lib/conversations/server-controller.ts`
- `infra/railway/backend.env.example`
- `infra/railway/frontend.env.example`

## Audited architecture

Normal-mode `ServerChatInterface` uses `ServerConversationController` and the
strict conversations API adapter. PostgreSQL conversation turns are authoritative;
the old `/chat` endpoint and demo interface are separate paths. A logical request
has an immutable UUID and content version. The server reserves a RUNNING turn,
loads bounded history, calls `RagService`, validates the result, rechecks the live
session/execution and indexed source ownership, then atomically publishes the
answer and query history. Uncertain submissions use the same UUID to reconcile.

With `tool_rag_agent_enabled`, RAG uses `ToolAgentAdapter`, `ToolRagAgentService`
and the bounded native tool graph (maximum six cycles). The four tools remain
`files_query`, `resolve_file`, `search_knowledge` and `file_evidence`. The existing
executor enforces owner/index eligibility, scope and ordered evidence provenance.
`finalize_answer` rejects unsupported source handles, numeric markers and exposed
identifiers; metadata/missing/failed evidence uses deterministic safe responses.

The new endpoint is **POST `/api/v1/conversations/{id}/turns/stream`**, with the
same body, cookie, Origin and CSRF requirements as the existing turn POST. Both
the original turn endpoint and `/api/v1/chat` remain unchanged and available.

## Protocol and verification boundary

SSE is consumed with authenticated POST fetch, not EventSource. Events are JSON:

| Event | Payload | Meaning |
| --- | --- | --- |
| `accepted` | Existing `{turn, replayed:false}` receipt | Durable RUNNING reservation, not an answer |
| `state` | `{phase:"searching"\|"validating"}` | Public processing state; resets provisional display |
| `provisional` | `{text:"..."}` | Replacement text snapshot from actual model deltas; unverified |
| `complete` | `{receipt, http_status:200}` | Canonical COMPLETED receipt after validation and commit |
| `receipt` | `{receipt, http_status:200\|202}` | Existing non-success attempt replay (202 while RUNNING), no generation restarted |
| `error` | `{receipt,http_status:503}` or generic `{message}` | Discard provisional text; reconcile saved outcome |

Session expiry after streaming starts uses `error` with the fixed code
`SESSION_EXPIRED` and a safe sign-in message. The frontend invokes the existing
`notifySessionInvalid()` mechanism, discards provisional content, and retains the
existing reauthentication and saved-attempt recovery behavior. No exception detail
is sent. A stale stream cannot invalidate a replacement account's session.

Comments provide idle heartbeats. A bounded queue provides backpressure. The
stream sets `Cache-Control: no-transform` so Next's local compression layer does
not buffer small responses; other responses keep their original cache policy. The
request owns its producer task, cancels it on disconnect, and joins cleanup.
Existing generation deadlines and durable interrupted/expired recovery remain.
The client also applies a 135-second stream deadline and per-frame/text limits.
HTTP errors before streaming preserve normal authentication/session handling.

In streaming mode each native model step uses `stream=True`, assembles function
call fragments privately, and applies the same argument parser. There is no
second final-generation request or repeated retrieval. Only eligible text after
the ordered provenance gate is emitted. Tool arguments/results are never SSE
events. Citation syntax, UUIDs and runtime handles are withheld, including split
tokens. If a step requests more tools, provisional text is cleared. Inventory,
social and insufficient-evidence responses may have no text deltas because their
authoritative outputs are deterministic.

Streaming requests explicitly use SDK `with_options(max_retries=0)`. There are no
application retries; non-streaming SDK retry settings are unchanged. A real SDK
transport test with a synthetic upstream 503 verifies exactly one streaming HTTP
attempt, while the same client's default non-streaming path still makes three.

Provider event handling follows the official OpenAI
[Chat Completions streaming reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/streaming-events).

The full generated answer still passes the original finalizer, service validation
and source-authorization checks. Only the committed receipt renders the existing
Markdown/citation UI. Provisional text is plain text, labelled unverified, has no
source actions and is never saved as a completed answer. Failure, EOF, timeout,
Stop and session invalidation clear it. Stop aborts the request; a late committed
answer can still be discovered by reconciliation. It does not promise rollback.
Refresh only observes saved turns; streaming is not automatically resumed.

The early `accepted` receipt is also published to the conversation controller.
It clears the submitted question from the composer before generation finishes,
while preserving newer text typed during acknowledgement. The RUNNING user turn
appears once in chat; Stop remains available throughout the active stream. Before
acknowledgement, uncertain transport failures retain the original draft.

## Enable with a separately authorized current local database

Backend process: `CHAT_STREAMING_ENABLED=true`, `TOOL_RAG_AGENT_ENABLED=true`.
The default is disabled, including under `APP_ENV=production`; production can opt
in without changing environment mode. The former local-only flags have been
replaced with these environment-independent names.

Frontend process: `NEXT_PUBLIC_CHAT_STREAMING_ENABLED=true`, demo mode false, and
the existing same-origin API rewrite pointed at the local backend. Default frontend
behavior remains non-streaming. This is a build-time flag; Railway's Dockerfile
declares it as an ARG defaulting to false. Rebuild to change the browser flag.

Use the existing Google application-session mechanisms. Keep the deterministic
fixture isolated from hosted APIs. Actual beta testing requires the rollout plan's
readiness gates and separate approval of request count and estimated cost.

## Deterministic acceptance preview

The inspected default local database has 393 indexed files but lacks current
application-session/conversation tables. No migrations were applied. The browser
preview therefore uses synthetic inventory, sessions and memory-only turns. It
exercises the production SSE route, native streaming adapter, tool graph, evidence
executor and citation finalizer with mocked OpenAI chunks. It does **not** prove
real OAuth, PostgreSQL publication, live retrieval quality or provider latency.

From `backend/`, run with the existing Python environment:

```sh
python -m tests.streaming_preview
```

From `frontend/`:

```sh
NEXT_PUBLIC_CHAT_STREAMING_ENABLED=true NEXT_PUBLIC_DEMO_MODE=false NEXT_PUBLIC_API_URL=/api/v1 BACKEND_URL=http://127.0.0.1:8001 npm run dev -- --hostname 127.0.0.1 --port 3440
```

Open **http://127.0.0.1:3440/chat/00000000-0000-0000-0000-000000000101**.
Ask a question to see progressive text followed by a verified synthetic citation.
Include `fail` in the question to trigger final citation-validation failure.
Press Stop during generation, then Reconcile submission to inspect interruption.
Reload to inspect memory-only turn recovery; restarting the fixture clears it.
Files is available with one synthetic Ready file; preparation mutations are blocked.
Source content loading intentionally returns an unavailable message in this fixture.

For the earlier offline preview (historical observations, not current service status), Next uses a temporary Google Fonts mock with local
Arial/Menlo fallbacks; it makes no font-network request and changes no source fonts.
The earlier real-backend preview was separately on http://127.0.0.1:8000 with blank OpenAI credentials,
indexing disabled and lifespan off to avoid legacy startup job mutations. Its
`/api/v1/health/ready` checks the retained local PostgreSQL database. Qdrant is on
http://127.0.0.1:6333/readyz. The browser preview connects only to fixture port 8001.

Earlier machine commands used the existing Python executable
`/Users/maddy/Desktop/INFO_VAULT/backend/.venv/bin/python`. The earlier offline
frontend command from `frontend/` is:

```sh
NEXT_PUBLIC_CHAT_STREAMING_ENABLED=true NEXT_PUBLIC_DEMO_MODE=false NEXT_PUBLIC_API_URL=/api/v1 BACKEND_URL=http://127.0.0.1:8001 NEXT_FONT_GOOGLE_MOCKED_RESPONSES=/private/tmp/drivemind-stream-font-mock.cjs node node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port 3440
```

## Test boundaries

Focused backend tests cover native fragments, progressive deltas, citation and
scope rejection, provider errors, truncated streams, cancellation cleanup,
durable reservation/publication boundaries, replay, local gating, Origin/auth/CSRF
and sanitized SSE failures. Frontend tests cover byte-split frames, provisional
updates, canonical citations, EOF, Stop, session changes, invalid receipts, replay,
duplicate submissions, stale callbacks and unverified/verified rendering.
Existing non-streaming tests continue to run. Automated tests use no paid APIs.

Final release verification on 2026-10-25: **825 frontend tests passed** and
**12 packaged proxy tests passed**. Relevant backend streaming/native-agent,
non-streaming chat, conversation, security and demo regressions: **345 passed,
102 skipped**. The skipped cases require disposable database fixtures that were
not configured; no hosted database or paid provider was used for tests.
TypeScript, scoped ESLint, scoped Ruff/format and whitespace checks passed.
Full mypy retains the previously documented assignment error in unchanged
`agents/tool_rag/finalization.py:76`; scoped checks cover the changed backend files.

Earlier full-backend verification recorded 1,674 passed, 726 skipped and one
existing credential-boundary allowlist failure in unchanged `indexing_runtime.py`.
That earlier run is historical evidence, not a new full-suite pass. Browser checks
from the earlier fixture preview covered progressive updates, completion, failure
cleanup, Stop/reconciliation, Files navigation, mobile/desktop and light/dark
presentation. They do not prove hosted OpenAI streaming.

Real paid streaming and durable local end-to-end acceptance remain unverified.
Streaming itself does not strengthen the existing model's semantic grounding;
it preserves the current validation rules and may replace or discard provisional
text at completion. Deployment buffering has not been tested or enabled.

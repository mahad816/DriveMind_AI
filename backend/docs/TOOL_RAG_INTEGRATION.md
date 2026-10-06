# Tool-agent backend integration (default off)

`TOOL_RAG_AGENT_ENABLED` defaults to false. It is deployment configuration, not a
request parameter. With false, existing classification, conversation rewriting,
legacy special paths and linear/old LangGraph generation remain unchanged.
With true, RagService selects the agent before classification or rewriting.
An agent failure never falls back to legacy generation.

## Existing request lifecycle

`POST /api/v1/chat` (`app/api/chat.py::ask_grounded_question`) validates
ChatRequest, applies demo admission/index guards, and obtains the session through
`app/db/session.py::get_db`. RagService resolves the configured demo user or the
existing single-user OAuth identity (`resolve_active_user`); this is not a new
multi-user authentication system. ChatRequest cannot choose the authority used
by tools. The existing API does not accept an authoritative request-body user ID.

History comes from the bounded frontend USER/ASSISTANT window, not a server-side
conversation/file registry. QueryHistory persists question, final answer and the
established citation JSON. Demo mode does not persist QueryHistory and generates
a response query ID. Browser conversation history remains unchanged.

The legacy path classifies history/chitchat/inventory/collection/file-target/RAG;
grounded RAG uses configured linear hybrid/vector retrieval or old drive_graph.
Existing generated citation markers are normalized and results adapt to
ChatResponse. Provider/configuration failures use the established safe 503 path.

## New integration boundary

RagService owns identity resolution and persistence. ToolAgentAdapter owns only
orchestration: bounded prior conversation input, the existing agent invocation,
response adaptation, safe operational counts, and closing its owned OpenAI
client. It has no SQL, resolver, classifier or alternative retrieval stack.
The agent creates a fresh registry for each request. Tool batches remain
sequential; parallel retrieval strategies retain their existing isolated sessions.
Native active-turn tool call IDs and TOOL responses remain intact and are never
truncated away to make room for old conversation text.

Prior context reuses the six-message / 6000-character history bound. Historical
runtime tokens and UUID-shaped identifiers are removed from model-facing prior
text. Named-file follow-ups must resolve the human filename afresh; no previous
handle/UUID mapping is restored. Source snippets, tool state, private diagnostics
and full graph/evidence objects are not saved to conversation history.

ChatResponse and CitationItem are unchanged. Their existing structured UUID
fields remain required public source/API identifiers. UUIDs and opaque runtime
handles do not enter ordinary answer prose or model-controlled identity arguments.
Finalized authoritative citations are reused. Truncated full-document reads add
an explicit bounded-coverage notice without changing the 20-chunk/context budget.

The existing six-cycle limit remains fixed. The integration adds a 120-second
application-owned run timeout and bounded owned-client cleanup. Cancelled asyncio
requests propagate into the awaited graph and existing session context manager;
no background graph task is spawned. A browser socket disconnect is not advertised
as automatic cancellation: the current stack provides no explicit disconnect
monitor. No Redis, persistence checkpoint, or new session framework is introduced.

Routine logs contain only path, counts, canonical tool names, terminal code,
cycle/scope flags and duration. No prompts, document chunks, handle mappings or
private diagnostic payloads are logged by this adapter. Shadow mode is omitted
because it would double provider work and complicate session/history ownership.

## Initial integration verification and historical blocking outcome

Current branch practical offline regression: 1770 passed, with exactly eleven
historical branch-bound evaluation tests deselected. Frozen historical source
reproduced 609 routing/evaluation tests in an isolated clone at
`fe1761864e5a15c2d5b4c5eee60516e816b75c68` on its required experiment branch name.
The new API integration matrix has 34 passing tests, including cancellation,
resource timeout, authorization hydration, schema/citations and no-fallback tests.
Ruff, formatting, mypy, basedpyright and diff checks pass.

Real HTTP evaluation used only the isolated synthetic HarborDesk corpus:
`060ad182c0bc7ab14a5966a322d139ece7974e2be1d7515c9eba86cca51c9ca8`.
Frozen 17-question identity:
`0528a10e4bc4b7249d3438cb5613c311128a8aec67a48d72821dbf838bffb57f`.
Raw records and source hashes remain ignored under
`evaluation/results/tool_agent_api_v1/`.

Flag ON: 17/17 HTTP 200, 37 LLM steps, 10/10 actual source-viewer lookups valid,
9/9 evidence-backed responses retain authoritative citations. Unsupported tag,
folder and modified-time requests decline safely; a broad tagged COUNT was
blocked before execution. No invented handles, scope broadening, invalid/missing
file corpus fallback, ordinary-prose UUID/handle leaks or cycle overruns observed.

**Initial integration blocker (resolved by the targeted guard below):** The cross-turn request “Summarize the first one” used a prior plaintext
inventory list to infer `architecture_notes.txt`, then resolved/read that filename
in the new run. It did not reuse an old handle, but it did not ask for clarification
as required by the policy for absent stable cross-turn inventory-result context.
Thus the behavior matrix is 16/17 and integration is not approved for default use.
No prompt/tool/retrieval changes or semantic reruns were made after seeing results.

Flag OFF: 16 completed HTTP comparisons, all 200, with 10 LLM completions. The
initial legacy Hello encountered an occupied/unverified local port and is retained
UNKNOWN; it was not reposted. Report comparison only over the 16 completed pairs.
Median HTTP latency: legacy 2.06 seconds, agent 3.24 seconds; maximum: 12.25 / 7.80
seconds. These are development observations, not a controlled performance study.

## Reference / license

Concepts only from Onyx MIT non-ee commit
`438b54447dd0e4e3b78a43457c911e340a881e5f`, inspected paths:
`backend/onyx/chat/{llm_loop,llm_step,process_message,chat_utils,chat_state}.py`,
`backend/onyx/tools/{tool_runner,models}.py`,
`backend/onyx/server/query_and_chat/chat_backend.py`.
Application identity vs model arguments, matched native tool history, bounded
context, rich vs model-facing results and service-owned persistence informed this
integration. No upstream fragments or enterprise/emitter/MCP code were copied.

## Narrow cross-turn resolution enforcement

Before `resolve_file` executes, a deterministic provenance check rejects inferred
references when prior history exists and current wording contains `first/second/
third one/file/document` or `that file/document`, unless the proposed reference is
literally present in the current question or its filename was returned by a tool
in the current run. The controlled result is UNRESOLVED_CROSS_TURN_REFERENCE and
instructs the agent to ask for a filename. It does not choose tools, operations or
capabilities, and does not treat general pronouns as file references.

Returned-name provenance lives only in the existing turn-local registry and is
populated by safe application-generated file/evidence projections. It is not an
identity or authorization source; ordinary resolution still revalidates the file.
No persistent handle map, cross-turn inventory memory, schema, router, verifier,
extra LLM call or frontend change was introduced. Existing vague ordinal history
remains unsupported until the user supplies a filename.

Targeted real HTTP validation used seven requests covering list + cross-turn
follow-up, explicit filename with prior history, same-run LIST dependency,
grounded knowledge, unsupported confidential tag, and Hello. All seven returned
HTTP 200; the cross-turn inferred resolution was blocked and clarified, all three
citations opened through the existing source endpoint, and no handle leak, scope
broadening, semantic retry or legacy fallback occurred. Observations remain
ignored under `evaluation/results/tool_agent_cross_turn_v1/`.

Focused tests: 539 passed. Practical backend tests: 1781 passed with the same
11 historical preflight exclusions. Static checks remain green. The default flag
remains false; no demo activation, push or deployment is performed here.

# EXP-03 Design — Explicit Conversation-History References

## Problem

The chat UI displays earlier turns, but the backend cannot answer a question about them. A conversation-only reference can fall into document RAG and produce an unrelated, cited answer. EXP-03 tests a general explicit-history capability, not recognition of the manual example's wording or topic. EXP-02's gated source diversity remains accepted and untouched.

## Capability Boundary

Support Level 1 only: requests to recall/repeat the most recent prior **user question** or **assistant answer** in the current conversation. Distinguish the requested role and select the latest eligible message of that role, even after several turns and any prior route (CHITCHAT, FILE_INVENTORY, FILE_TARGET, or GROUNDED_RAG). A new chat or missing requested role gets a truthful no-history response.

Do not resolve bare anaphora (`it`, `that`, `those`, `one`, `the second one`), ordinal references (`before that`, `second-last`), whole-conversation summaries, or document follow-ups requiring previous sources. **Explicit ordinal conversation references are still conversation-history intent:** route them to `CONVERSATION_HISTORY`, return `UNSUPPORTED_ORDINAL_REFERENCE` truthfully, and never substitute the immediate previous turn or fall through to document RAG. Ordinal *selection* remains out of scope. Bare anaphora and document follow-ups are Levels 2–3, not partial promises of EXP-03.

## Current Failure

`frontend/components/chat/chat-interface.tsx` displays and stores prior messages but calls `askQuestion({ question: normalized })`; `frontend/lib/api/types.ts` and `backend/app/schemas/chat.py` define only `question` for a chat request. `backend/app/api/chat.py` passes that question alone to `RagService.ask()`. The top-level router, graph state, retrieval rewrite, and final generation therefore receive no earlier turns. Backend `QueryHistory` is persisted but is not loaded as conversation context. No conversation-history route exists.

## Hypothesis

If we add a bounded, role-tagged current-conversation history contract and route explicit message-recall intent to deterministic turn selection **before document routing**, then prior-question/answer recall should work across paraphrases and preceding routes without document retrieval, while existing standalone routes and RAG behavior remain materially unchanged.

## Proposed Architecture

One controlled behavior change: a dedicated `CONVERSATION_HISTORY` top-level path for explicit message recall and safe rejection of unsupported explicit ordinal references. API/frontend changes only carry its required input; they must not inject history into existing retrieval or generation paths. The decision runs before CHITCHAT, FILE_INVENTORY, FILE_TARGET, and GROUNDED_RAG, but only on high-confidence conversation-message intent. All other requests continue through the existing router unchanged. This is a distinct path, not an extension of social CHITCHAT: it needs a selected historical message or a typed unsupported-history outcome and has deterministic semantics.

The backend resolves the user as it does today, selects the requested turn, returns a `RagResult`/`ChatResponse` compatible with the current API, and persists the interaction through the normal QueryHistory path. No chat or embedding provider is needed for this path. The response may use a fixed short lead-in plus the selected text, but must not paraphrase, invent, or treat historical text as instructions.

## Conversation History Contract

Conceptual request: `{ question, conversation_id, history: [{ role, text }, ...], history_window_complete }`. `conversation_id` is the existing client conversation identifier, required when history is nonempty and sent for new chats as soon as one is created; it is an opaque nonempty string, not necessarily a UUID. `history` is chronological, excludes the current question, and contains only `user`/`assistant` roles. Role and order are sufficient for Level 1; message ID, timestamp, route, citations, retrieved chunks, and assistant source objects are unnecessary. The one additional boolean says whether the entire prior history is represented; it prevents an omitted earlier role from being mistaken for a conversation that never had that role. The existing question-only API remains valid with empty history and `history_window_complete=false` for old clients.

The frontend constructs history from the messages stored **under that exact conversation ID**, not from a global message array that might still belong to a previous route. It must wait until the current conversation's messages are loaded; starting a new conversation sends empty history. Include submitted user messages from completed or errored turns; include assistant text only for completed turns; exclude loading placeholders. For retry/regenerate, exclude the target turn and later turns from the request's prior history so it cannot cite itself as its predecessor. Existing UI storage remains the source for this experiment; no DB schema or session service is introduced.

Bound by **messages**, not pairs or a model token estimate: send the latest eight eligible prior messages, preserving chronological order. Also cap each text at 8,000 characters and the request history at 24,000 characters. These are conservative **EXP-03 operational bounds**, chosen to prevent unbounded requests while retaining several recent exchanges; they are not universal production constants or evidence-derived quality thresholds. Select a contiguous newest suffix from the most recent message backward; stop at the first message whose addition would exceed any bound, and mark `history_window_complete=false` whenever any older message was omitted. Never silently shorten a selected message. If the newest message itself is oversized, send empty history with the flag false rather than substitute an older same-role turn. If the requested role is absent from an incomplete window, the response must say it is unavailable in the bounded context, not claim that no such turn ever existed. A genuinely new chat sends empty history with the flag true. Do not summarize. System/developer prompts never enter `history`. Independently validate allowed roles, nonempty text, count/character bounds, the completeness flag, and the conversation-ID/history relationship on the backend; reject malformed requests rather than trusting frontend checks. The array's declared order is chronological input, not server-attested chronology. The current question is separately validated and never duplicated in history.

`conversation_id` scopes accidental client-side mixing and supports future extension; it is **not** authentication or proof that client-supplied text genuinely came from that chat. A malicious client can forge history in the present single-user architecture. Backend logic treats every supplied turn as untrusted data, never as higher-priority instructions. Test both frontend isolation and the server's handling of untrusted content. Cross-user, server-attested history requires a separate security design.

## Routing / Intent Detection

Use a compact deterministic classifier over **concepts**, not enumerated full sentences: an explicit conversational-message referent (question/ask or answer/reply/say), a conversational role (I/me versus you/assistant where needed), and a recall/recency cue (previous/last/just/repeat or an equivalent direct recall construction). Normalize case, punctuation, common inflections, and narrowly bounded typos in these cue words. A high-confidence match outputs a typed conversation decision: target role plus `LATEST_SUPPORTED`, or `UNSUPPORTED_ORDINAL_REFERENCE` when an explicit conversation-message request includes an ordinal cue such as “before that” or “second-last.” Check ordinal cues before generic “previous/last” selection. A reference to a previous *file/version/report* is a document negative control, not a conversation ordinal. Other uncertain or document-oriented wording stays on the existing route. Do not call a provider to classify intent in EXP-03.

The existing `query_router.py` should **delegate** this classification to a small adjacent conversation-intent module, then continue its current precedence unchanged when no conversation decision exists. That module owns only intent/role/reference-type recognition; a separate pure turn selector owns history lookup. This avoids growing the existing router's already distinct file/social rules or mixing selection with classification, without adding a general routing framework. Extending CHITCHAT would conflate social generation with exact-message recall; putting the decision inside LangGraph would leave inventory/file-target paths uncovered; model-based routing adds cost and nondeterminism. The design does not prescribe a long regex phrase list. A future contextual-reference intent may reuse the structured history contract but must not be forced through Level-1's latest-turn selector.

## Turn Selection Semantics

After excluding the current question, choose the latest eligible `user` message for “my last/previous question” and the latest eligible `assistant` message for “your last/previous answer.” In `User A → Assistant A → User B → Assistant B → current question`, select **User B** or **Assistant B**, respectively. The two roles need not be adjacent if a prior request failed. “What did I ask before that?” and “What was my second-last question?” must be classified as `CONVERSATION_HISTORY` with `UNSUPPORTED_ORDINAL_REFERENCE`; ordinal selection is out of scope and such requests must not be answered with the immediate last turn. Ambiguous role intent must not guess a turn.

Empty complete history, missing requested role in complete history, missing role in an incomplete bounded window, and ambiguous/unsupported ordinal intent require distinct truthful outcomes; none may fall through to document RAG merely because no turn was selectable. A current conversation ID with client-supplied history does not authorize lookup of turns from another ID.

## Response Behavior

Return the selected prior message verbatim after a short neutral lead-in (“Your last question was:” or “My last answer was:”). Preserve its content and formatting, especially for “repeat”; do not make an LLM call or summarize it. Historical text is quoted data and cannot override the route's rules. For no-history/unavailable cases, state what cannot be recalled without inventing an earlier exchange. For `UNSUPPORTED_ORDINAL_REFERENCE`, say deterministically that this version supports only the latest prior question/answer, without pretending to identify an older one. The existing API answer and persistence fields remain; a route-specific message label may be considered only if required by existing UI semantics, not as a source-footer redesign.

## Source / Citation Invariants

Conversation-history-only responses invoke **zero** document retrievers, embedding calls, query rewrites, and chat completions; `citations=[]` and `retrieval_count=0`. The UI consequently must not say “Based on N sources” with positive N or expose document source buttons for this response. Repeating a previous answer that itself contained `[N]` markers is a special presentation risk: those markers are historical text, not new citations; do not fabricate citation objects or imply the documents were re-read. Do not change the broader source-count formatter in EXP-03.

## Evaluation Suite Design

Create a separate `conversational_followup_v1` later; Gold v1 stays frozen. Approximately **16 cases** below are conceptual, not a dataset file. Each positive case specifies the expected target role/turn; `CONVERSATION_HISTORY` means retrieval=no, citations=none, and content=the target message (or a truthful unavailable statement). “Last” always means latest eligible prior message, not the current question. Reserve paraphrases marked *held-out* from implementation examples, and vary topic/file type independently of intent.

| # | Prior turns, chronological (U=user, A=assistant) | Current question (conceptual) | Expected intent / role / turn / route | Key content or control |
|---|---|---|---|---|
| 1 | U greeting; A greeting | “What was my last question?” | Recall / U / greeting / CONVERSATION_HISTORY | Exact greeting; no retrieval/citations |
| 2 | U asks for PDF count; A inventory count | “Repeat the question I asked.” | Recall / U / PDF-count question / CONVERSATION_HISTORY | Prior FILE_INVENTORY topic |
| 3 | Same as 2 | “What did you just answer?” | Recall / A / inventory answer / CONVERSATION_HISTORY | Exact assistant text, not user question |
| 4 | U asks a fact in `Travel_Itinerary.pdf`; A grounded answer | “Remind me what I asked.” | Recall / U / travel question / CONVERSATION_HISTORY | Prior GROUNDED_RAG topic |
| 5 | Same as 4 | “Repeat your previous response.” | Recall / A / grounded answer / CONVERSATION_HISTORY | Historical answer text; no new citations |
| 6 | U/A on travel; U/A on meeting dates; U/A on cloud notes | “What was my preceding question?” *held-out* | Recall / U / cloud-notes question / CONVERSATION_HISTORY | Three-pair order, not first turn |
| 7 | Same three pairs | “Say again what you last told me.” *held-out* | Recall / A / cloud-notes answer / CONVERSATION_HISTORY | Latest assistant, not latest user |
| 8 | U asks about a DOCX; A answers | “wht did i ask jus now?” *held-out typo* | Recall / U / DOCX question / CONVERSATION_HISTORY | Casual typo tolerance |
| 9 | U asks about an image; A answers | “wat was ur last reply?” *held-out typo* | Recall / A / image answer / CONVERSATION_HISTORY | Role preserved under typo |
| 10 | No prior turns; complete window | “What did I ask before?” | Recall / U / unavailable / CONVERSATION_HISTORY | Truthful no-history; no retrieval/citations |
| 11 | U prior request failed; no assistant message | “What did you last tell me?” | Recall / A / unavailable / CONVERSATION_HISTORY | Do not substitute prior user turn |
| 12 | Chat X has U/A on taxes; Chat Y has U/A on a recipe | In Chat Y: “What was my last question?” | Recall / U / recipe question / CONVERSATION_HISTORY | No Chat X leakage |
| 13 | U/A on document versions | “What changed in the previous version of this PDF?” | Document request / none / none / existing document route | Negative control: `previous` refers to a file; retrieval as normally applicable |
| 14 | U/A on file inventory | “Show the last modified report in my Drive.” | File request / none / none / existing inventory/metadata route | Negative control: `last` is recency, not chat history |
| 15 | U/A on a report | “How many files are named agenda?” | Inventory request / none / none / FILE_INVENTORY | Ordinary route stays intact |
| 16 | U/A on a report | “What did I ask before that?” | Ordinal conversation intent / U / none / CONVERSATION_HISTORY | `UNSUPPORTED_ORDINAL_REFERENCE`; no retrieval/citations; do not return last question |

Add a bounded-history fixture to case 11 or 12 in suite implementation: when the requested role was omitted by size limits (`history_window_complete=false`), assert “unavailable in this bounded history,” not “you never asked/answered.” Test “second-last question” as an ordinal variant of case 16. These are boundary variants, not new intent families.

For rows 13–15, document retrieval/inventory and citations follow the **existing** path, not EXP-03's zero-retrieval invariant. Add at least one held-out paraphrase with a topic and filename absent from classifier development fixtures; do not use Resume, GPA, CoreChain, or the original manual sentence as training hooks.

## Success Criteria

- All supported recall cases in the frozen suite: 100% `CONVERSATION_HISTORY` routing, requested-role accuracy, and selected-turn accuracy; content exact after removing only the fixed lead-in. Explicit ordinal variants must route there with 100% `UNSUPPORTED_ORDINAL_REFERENCE` outcomes, never a selected immediate turn.
- All conversation-only cases: 100% retrieval bypass, zero embedding/chat-provider calls, `retrieval_count=0`, and zero document citation objects. No-history and unavailable outcomes must be truthful in every such case.
- All isolation cases: zero cross-conversation turns selected; all negative controls: zero false `CONVERSATION_HISTORY` routes. A single leak or document false positive fails the experiment.
- Request bounds always enforced: at most eight prior messages, 8,000 characters per message, 24,000 total; no silent truncation or substitution of an older turn.
- In local integration tests, conversation-only p95 response time should be under 1 second (report environment and sample size); do not trade correctness for latency. Gold v1 route accuracy and existing document-path metrics must not regress in a later single controlled benchmark.
- Human review only for cases where a non-verbatim explanatory response or ambiguous wording cannot be judged deterministically; do not replace exact role/turn assertions with an LLM judge.

## Regression Controls

Keep tests for current CHITCHAT, FILE_INVENTORY, FILE_TARGET, and GROUNDED_RAG routing, plus document questions with “previous”/“last.” Existing retrieval candidate order, RRF, rerank, evidence grading, EXP-02 gated prompt selection, citation normalization, and document-answer prompts remain fixed. Run focused backend/frontend tests, then normal suites. A later Gold v1 run is regression protection, **not** part of design or implementation; do not edit Gold v1.

## Test Strategy

RED before GREEN, with only missing Level-1 behavior failing:

1. Backend unit: request validation/bounds and malformed payload rejection; semantic-intent positives, unsupported ordinals, and document negative controls; independently test typed intent classification and pure role/turn selection across multiple turns; no-history/unavailable outcomes; untrusted historical text is inert. Inject retriever/provider spies and inspect existing trace hooks for route, requested role, selected array position or outcome, and bypass (without storing historical content in telemetry).
2. Frontend: construct the bounded chronological suffix from the current conversation ID; include correct roles; exclude current/loading/target-regeneration turns; new chat and conversation switch cannot reuse old messages.
3. API/service integration: `/chat` returns the selected text with zero retrieval/citations; history-only path does not call retrievers or providers; existing routes remain untouched. Exercise persisted QueryHistory without using it as an implicit context source.
4. New evaluation suite: freeze conceptual categories into independent design and held-out cases; verify routes, role, turn, content, isolation, and latency. No Gold v1 changes.

## Expected Files to Change

Likely: `frontend/components/chat/chat-interface.tsx`, `frontend/lib/api/types.ts`, `backend/app/schemas/chat.py`, `backend/app/api/chat.py`, `backend/app/services/rag_service.py`, `backend/app/retrieval/query_router.py`, and a small adjacent conversation-intent/turn-selection module, plus focused existing tests. `frontend/lib/conversations/messages.ts` may need a small bounded-history selector, but no storage redesign is assumed. Not every listed file must change; inspect the smallest coherent implementation during RED/GREEN.

## Files That Must Not Change

Gold v1; baseline/EXP-01/EXP-02 benchmark artifacts and human reviews; EXP-02 gated source-diversity behavior; vector, keyword, and metadata retrievers; RRF; reranking; evidence grading; prompt context ordering; document citation normalization; source-count/clickability UI; and negative-grounding prompts. No DB/Qdrant schema or data migration is part of Level 1.

## Risks

| Risk | Minimal mitigation |
|---|---|
| Cross-conversation leakage or stale local state | Build history from the active ID's storage only; wait for that ID to load; test new/switch/regenerate paths |
| Forged or malicious client history | Treat all prior text as untrusted data; deterministic selection/quotation only; never promote it to instructions; document that ID is not server attestation |
| False-positive chat routing | Require explicit message-reference concepts; include document-version/recency negative controls and held-out paraphrases |
| Wrong role or wrong turn | Role-specific latest-turn selection with multi-turn and failed-turn tests |
| Growth or silent truncation | Eight-message/character bounds, contiguous newest suffix, explicit unavailable outcome |
| Accidental document retrieval/citations | Dedicated pre-retrieval path with zero-call and zero-citation assertions |
| Future contextual follow-up complexity | Keep role-tagged order and conversation ID; do not flatten or summarize history in EXP-03 |

## Out of Scope

General pronoun resolution, **ordinal turn selection** (though explicit ordinal intent receives a safe response), whole-conversation summarization, retrieval over earlier source context, natural inventory intent expansion, GPA/CGPA query robustness, source-footer semantics, citation UI redesign, and unsupported negative inference. The experiment does not create an authenticated server-side conversation store or treat client history as permanent server state.

## Implementation Plan

1. Freeze the Level-1 contract and `conversational_followup_v1` categories; write RED tests, including held-out paraphrases and cross-chat isolation.
2. Add only bounded history transport, the high-confidence conversation-history route, deterministic role/turn selection, and response plumbing. Preserve existing document paths.
3. Make focused tests GREEN; run frontend/backend regression and static checks; review the complete diff for one-variable isolation.
4. After a separate preflight, evaluate the new suite and Gold v1 once under the approved workflow; compare against frozen baselines and human-review only genuinely ambiguous cases.

**Isolation decision: YES.** EXP-03 is one capability experiment: explicit message-recall routing from bounded structured history. Transport/schema changes enable that single behavior; no retrieval, prompt, model, or citation policy is changed.

# 04: Trace every paid provider call per route and answering path

**Spec:** docs/specs/m0-sec-security-hardening.md
**What to build:** A written, evidence-backed table of which requests can cause a paid provider call, how many, on which answering path, and where a per-Owner check can sit before any paid call and before any state is written. It settles the open item of Owner decision D4-2 (the legacy linear path and `POST /chat` without a conversation were never traced) and tells tickets 05 and 06 where admission sits. It also gives M1 the list of counters to measure.
**Blocked by:** None (can start immediately).
**Status:** ready-for-agent
**Progress:** open

## Scope

- Routes: `POST /chat`; conversation turn creation; conversation turn streaming; any other route that can reach a provider (check `POST /index/build` embeddings and any intent or rewrite call).
- Paths: tool agent (hosted, Owner-reported); legacy linear; legacy LangGraph (one line each; LangGraph only where it differs).
- For each route and path, from reading the code: the provider calls made (chat model, embedding, intent gate, follow-up rewrite, claim check, citation-correction retry), the minimum and the maximum count per question, and the count for (a) a normal question with evidence, (b) an Owner with an empty corpus, (c) a chitchat question, (d) a provider failure partway.
- Where a check can sit for each entry point so that a refused request makes no provider call, leaves no running turn and writes no query history. Note for the analysis: a replayed turn submission is only recognized inside the reservation step, which already stores the turn and its question in one transaction, and the streaming route answers 200 before the submission runs (a 429 is only possible in the route function, before the stream is built; streaming is tool-agent only and answers 409 otherwise). The design is decided in the spec (section C): the turn table, not the quota ledger, is the authority on replay. Ticket 06 reads the turn table for (Owner, client request id) before admission; admission rows carry server-generated attempt ids and are released if the reservation step fails or reports a duplicate. This ticket verifies the facts that design relies on: the scope and uniqueness of a turn's client request identifier (the existing per-Owner unique constraint), what a stream reconnection sends, what a retry of a completed, failed, interrupted or timed-out turn with the same id returns (expected: the stored row, no execution; a new attempt needs a new id), every exception the reservation step can raise after the point where admission would have happened, and the real execution bounds (generation timeout, execution seconds, cleanup and publication time outside them, and the absence of a timeout on `POST /chat`). Report anything that contradicts the design before ticket 05 starts.
- Whether any route outside those can cost money without being covered by an existing bound (indexing is bounded by one unresolved job per account; state what that does and does not limit).
- Where a count is easy to verify with a fake provider, add a deterministic test that counts calls; where it is not, state why and rely on code evidence. No placeholder tests.

## Out of scope

Any quota or limiter code (tickets 05 and 06). Measuring real dollar cost (M1). Changing any path. Any paid or live call.

## Inspect

`docs/tickets/m0-system-audit/04-auth-and-access-control-audit.md` ("Sign-up gate", section 7); `docs/tickets/m0-system-audit/05-rag-paths-and-flags.md`; `backend/app/api/chat.py`, `conversations.py`; `backend/app/services/rag_service.py`, `conversation_chat_service.py`; `backend/app/agents/tool_rag/` (graph, claim check, intent gate); `backend/app/llm/`; `backend/app/embeddings/`.

## Deliverables

`## Findings` in this ticket with the table, the placement analysis and the list of counters for M1.

## Needs

No paid API, no key, no network. `OPENAI_API_KEY` unexported.

- [ ] The table covers every route and path listed in Scope, labelled Verified, Unverified or Defect with an evidence type and a pointer (file and symbol, or test name).
- [ ] For a new turn, a replay of a running turn, a replay of a completed turn, a retry of a failed or timed-out turn with the same id, a simultaneous duplicate and a stream reconnection, the table states how the turn table classifies it, whether admission happens, whether a provider call can occur, and the response.
- [ ] Every exception `reserve` can raise is listed with its status, so ticket 06's release-on-failure covers all of them.
- [ ] The execution bounds are tabulated with file and symbol, and the minimum safe lease derived from them is stated.
- [ ] Internal model calls (intent, rewrite, claim check, citation correction) are shown to sit inside one admitted attempt, so they are not counted separately.
- [ ] Each entry point has one named placement for a per-Owner check, with the reason it runs before any provider call and before state is written, and the reason a replay is or is not charged.
- [ ] The empty-corpus case is answered for the tool-agent path and for the linear path.
- [ ] The routes that cannot be reached by a signed-in Owner without a paid call, and those that can, are stated separately.
- [ ] Any added test is deterministic, uses fakes, and fails if the counted behavior changes.
- [ ] No application code changed (`git diff -- backend/app` is empty).
- [ ] The list of counters M1 must record (per path: calls and tokens per question) is written down.

## Comments

# 06: Apply the paid-question quota to the answering routes, and cap input

**Spec:** docs/specs/m0-sec-security-hardening.md
**What to build:** `POST /chat`, conversation turn creation and turn streaming, on both the legacy and the tool-agent answering paths, refuse an over-limit question before any provider call with a clear 429, count each question once, and reject oversized questions and bodies. Owner decisions D4-2 and the 2026-11-21 approval.
**Blocked by:** 05.
**Status:** ready-for-agent
**Progress:** open

## Scope

- Call ticket 05's admission at the placements ticket 04 names, normal mode only:
  - `POST /chat`: each request is its own attempt (a fresh key); admission runs outside the handler's existing mapping of provider errors to 503, so a refusal stays a 429.
  - Conversation turn creation: key is the turn's existing idempotency key (Owner plus client request id), admitted before the reservation step. A replay, a retry of a counted turn and a reconnect reach the existing behavior unchanged, uncounted.
  - Turn streaming: admission in the route function before the stream is built, so the refusal is a real 429 (streaming is tool-agent only and answers 409 otherwise, so it is tested on that path only). The attempt is finished when the stream's work ends, including client disconnect and cancellation.
- Finish the attempt in all non-replay endings: success, provider error, timeout, cancellation. Do not count internal model or embedding calls separately.
- A refusal: 429, a fixed clear message that names which limit was reached, a retry hint where one is known (the concurrent refusal says so too), no turn created, no query history written, no provider call.
- Input caps in normal mode: `question` on `POST /chat` capped at the 4000 characters the conversation endpoints use (422, as the demo cap does); a request-body cap on the three routes by generalizing the demo body limit (today tied to demo mode and the `/chat` path), with the byte cap stated and checked against the largest legal chat request (8 history turns of 8000 characters, multibyte) and tested with a chunked body.
- Replace the test that pins "non-demo limits are disabled" (`test_non_demo_limits_disabled_and_production_errors_safe`) with a test that Owner mode is limited, keeping its error-sanitizing assertions. Leave the demo limiter tests (including `test_limiter_expiry_bounded_state_and_non_demo_bypass`) untouched.
- Pruning of old ledger rows runs at a natural low-frequency point (for example on admission, bounded work), not as a new background worker.

## Out of scope

Dollar accounting; per-user quotas; changing retrieval, grounding, citations or any answering path; the demo limiter and demo mode; the evaluation harness (it calls services directly and is not limited); calibrating values (M1 data, M9 gate).

## Inspect

Tickets 04 and 05; `backend/app/api/chat.py`, `conversations.py`; `backend/app/services/conversation_chat_service.py`; `backend/app/core/public_safety.py`; `backend/app/schemas/chat.py`; `tests/test_public_safety.py`; `tests/security/test_conversation_chat.py`, `test_conversation_api.py`.

## Deliverables

Wiring, caps, tests; `## Comments` with documentation items for ticket 09 and the M9 gate input (values to recalibrate).

## Needs

Disposable PostgreSQL and Qdrant as `AGENTS.md` describes for the conversation tests. Fake providers only; `OPENAI_API_KEY` unexported.

- [ ] Tests first fail today: with limits set low, the next question still reaches the counting fake provider.
- [ ] Hour, day and concurrent refusals are each returned as 429 with their reason, and the counting fake provider records zero calls, on the tool-agent path (`/chat`, turn creation, streaming) and the linear path (`/chat`, turn creation).
- [ ] One question is one count whatever its internal model calls (a tool-agent run with intent, rewrite, claim-check and a citation-correction retry adds one ledger row).
- [ ] A replay of a running turn, a replay of a completed turn, a client retry with the same request id and a stream reconnection add no ledger row and are not refused at any limit.
- [ ] A refused turn leaves no turn row and no query-history row.
- [ ] The concurrency slot is released after success, provider error, timeout, cancellation and client disconnect during a stream; a crash is covered by the lease (ticket 05).
- [ ] Counts survive building a new application instance on the same database.
- [ ] Owner A's usage does not change Owner B's allowance.
- [ ] A 4001-character question on `/chat` is 422 and an over-cap body is rejected before parsing, including chunked; a maximum legal chat request is still accepted.
- [ ] Ledger unavailable: a paid request is refused, not served (fault-injected).
- [ ] Demo mode is unchanged: the existing demo limiter, body-limit and budget tests pass unmodified; the evaluation harness tests show no limit applied.
- [ ] No public path or success-response schema changes. No existing test needs more than the defaults or a manual reset. Static checks no worse than the baseline.

## Comments

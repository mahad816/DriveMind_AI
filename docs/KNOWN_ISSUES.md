# Known issues (executable registry)

Single source of truth for defects we **know about and have not fixed yet**. Each one has
a test that states the *correct* behaviour and is currently expected to fail, so the
suite stays green but the bug can never be forgotten or silently "fixed" without the
registry being updated.

## How the tests work

| Side | Where | Mechanism |
|---|---|---|
| Backend | `backend/tests/known_issues/` | `@known_issue("KI-xxx", ...)` = `xfail(strict=True, raises=AssertionError)` |
| Frontend | `frontend/lib/knowledge/known-issues.test.tsx` | a "today" test pinning current behaviour + an `it.fails` test of the correct behaviour |

*Strict* means: when a fix makes the test pass, the suite goes **red** (XPASS / `it.fails`
passing). The fixer then removes the marker (backend) or changes `it.fails` to `it`
(frontend), and moves the entry below from **Open** to **Fixed**. Run them with:

```bash
cd backend  && uv run pytest tests/known_issues -rxX      # expect "passed, N xfailed"
cd frontend && npx vitest run lib/knowledge/known-issues.test.tsx
```

Rule for new entries: reproduce first, assert only what a user would call correct, add a
passing "guard" test for any neighbouring behaviour a fix must not break, and never mark
something known without a test (or say plainly that it is *unreproduced*).

## Open

### KI-002 — A real citation does not prove the claim  *(correctness, backend)*
- **Symptom:** the model may write a claim the source does not say; if it carries a valid `[source_N]` marker it is shown with a genuine citation. Reproduced: evidence says "Authoritative refund policy text."; answer "Refunds are always approved within 90 days. [source_1]" is published.
- **Cause:** `finalize_answer` validates that handles/markers exist and belong to the user (identity), by design nothing checks claim-level faithfulness (documented limitation; see also the existing test `test_content_evidence_and_real_handle_allow_grounded_answer`, which encodes the same gap).
- **Test:** `test_ki002_claim_absent_from_evidence_is_not_published_with_a_citation` (xfail).
- **Suggested direction:** not a quick patch. First measure how often it happens (the planned 24-case gold run), then consider an entailment/faithfulness check or quote-based answering. Decide approach with data, avoid shipping a heuristic that looks like safety but is not.

### KI-012 — "Check status" can do nothing  *(user-visible, frontend)*
- **Symptom:** the Check status button appears inert.
- **Reproduced cause (partial):** `PreparationQueue.check()` (`frontend/lib/knowledge/preparation-queue.ts`) does `if (this.busy …) return;`, so a click while any operation runs is discarded and returns at once; the caller cannot tell and the UI shows no result.
- **Tests:** `KI-012 (today)` / `KI-012 (correct)` (a second check must wait for / join the in-flight one).
- **Not reproduced:** when a check *does* run and still cannot verify, `blocked()` republishes the identical message, so a repeat click looks unchanged. No test yet because the desired UI (timestamp? reason?) is a product decision.
- **Suggested fix:** return the in-flight promise instead of dropping (join), then add a visible "checked just now / still unconfirmed because …" result.

### KI-020 — Indexing admission is a permanent fail-closed latch  *(unreproduced / needs decision, backend)*
- **Observation:** `IndexingSupervisor._fail()` (`backend/app/services/indexing_lifecycle.py`) sets `FAILED` and stops; nothing returns it to `READY` without a process restart. The handoff reports one hosted case that a restart recovered after a transient provider problem.
- **Evidence (2026-11-19):** in one of three full backend runs on a heavily loaded machine, `tests/security/test_indexing_lifecycle.py::test_two_real_instances_start_and_shutdown_independently` failed with the captured log line "Indexing executor is unavailable; local admission is closed." (the supervisor entered `FAILED` during the test), then timed out waiting for the worker. It passed 8/8 when run alone. This suggests a transient slowness can latch the supervisor; it is also a flaky test (about 1 in 3 full runs under load). The test was left unchanged on purpose so the fragility stays visible.
- **No test on purpose:** this may be deliberate (fail closed, supervised). Writing a "should recover" test now would assume the design. Decide: self-heal with bounded retries, or keep fail-closed but expose the reason and a clear operator action.

## Not covered by tests (cannot be checked locally without paid or live services)
- Real OpenAI answer quality, streaming timing through the Railway proxy, hosted deployment state. Measured separately (RAG evaluation phase).

## Fixed
### KI-001 — Greetings and small talk got the "no document evidence" refusal  *(fixed on branch `feat/conversation-reply-tool`)*
- **Was:** "Hello, can you hear me?", "Hi there", "Thanks a lot", "What can you do?" etc. were refused because the tool agent only recognised 10 exact phrases.
- **Fix:** `backend/app/agents/tool_rag/conversation.py` classifies the *meaning* of the message with one small model call (enum output only, any wording / order / Roman Urdu). Conversational intents get server-owned reply text, never model prose, and skip the agent, embeddings and SQL. Anything uncertain, malformed, slow, failing, over 300 characters or in demo mode falls back to the normal grounded agent.
- **Tests:** `backend/tests/agents/tool_rag/test_intent_gate.py` (wiring, fail-safe, no model prose). Recognition quality is measured separately by the live intent evaluation (see `backend/evaluation/`), not by phrase lists in unit tests.

### KI-010 — A finished preparation record blocked Drive discovery  *(fixed on branch `fix/discovery-preparation-gate`)*
- **Was:** after documents finished preparing, "Check Drive" refused until the Preparation screen was closed.
- **Fix:** `DiscoveryController` now asks the canonical `readPreparationGate`. A queue whose every document is confirmed ready is *cleared* (same as "Close completed preparation") and discovery proceeds. Pending, failed, skipped, legacy, unreadable, wrong-owner or unknown-version records still block and are never modified.
- **Why cleared, not merely ignored:** a later sync can change a prepared file, after which the completed record could no longer be verified, and "Close completed preparation" is disabled for unverifiable batches. Leaving the record would trap the user.
- **Tests:** `lib/knowledge/discovery-preparation-gate.test.tsx` (22) and one UI test in `components/files/drive-discovery.test.tsx`.

### KI-011 — The refusal named the wrong cause  *(fixed on branch `fix/discovery-preparation-gate`)*
- **Was:** every local refusal said "The Drive check was not accepted. Verify your connection…" though the backend was never called.
- **Fix:** typed `DiscoveryBlockedError` reasons with their own messages (unfinished preparation, unreadable preparation record, a discovery already pending in this browser, no safe tab coordination). Denied browser storage says so and states nothing was sent. The "verify your connection" text now appears only after a request really was sent and rejected.


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

### KI-001 — Greetings and small talk get the "no document evidence" refusal  *(user-visible, backend)*
- **Symptom:** "Hello, can you hear me?" answers "I don't have retrieved document evidence to answer that. Which file should I look up?" (OpenAI call itself succeeded). Also refused today: "Hi there", "How are you?", "Thanks a lot", "thank you so much", "What can you do?", "Who are you?".
- **Cause:** `backend/app/agents/tool_rag/finalization.py` `_SOCIAL` is an exact-match list of 10 phrases. With no tool call, free-form model text is (deliberately) never published, so everything outside the list falls to `NO_CONTENT`. The tool agent runs before the legacy router, which has a larger list (`_CHITCHAT_EXACT` in `backend/app/retrieval/query_router.py`, includes "how are you", "what can you do", "who are you") that is never consulted.
- **Tests:** `test_ki001_social_input_is_not_refused_as_missing_evidence` (7 cases, xfail). Guards that pass today and must keep passing: greeting + document question still needs evidence (4 cases); "Hey!", "Good morning!", "Thanks!" keep working.
- **Suggested fix (smallest, safe):** reuse the router's phrase set instead of a second list (DRY), add "can you hear me" / "are you there" style phrases, keep matching on the *whole normalized message* so "Hello, summarize my file" is still refused. Return server-owned text only; never publish model prose. Do **not** loosen the no-tools policy.
- **Not decided:** exact wording of the replies; whether "what can you do" should list capabilities.

### KI-002 — A real citation does not prove the claim  *(correctness, backend)*
- **Symptom:** the model may write a claim the source does not say; if it carries a valid `[source_N]` marker it is shown with a genuine citation. Reproduced: evidence says "Authoritative refund policy text."; answer "Refunds are always approved within 90 days. [source_1]" is published.
- **Cause:** `finalize_answer` validates that handles/markers exist and belong to the user (identity), by design nothing checks claim-level faithfulness (documented limitation; see also the existing test `test_content_evidence_and_real_handle_allow_grounded_answer`, which encodes the same gap).
- **Test:** `test_ki002_claim_absent_from_evidence_is_not_published_with_a_citation` (xfail).
- **Suggested direction:** not a quick patch. First measure how often it happens (the planned 24-case gold run), then consider an entailment/faithfulness check or quote-based answering. Decide approach with data, avoid shipping a heuristic that looks like safety but is not.

### KI-010 — A finished preparation record blocks Drive discovery  *(user-visible, frontend)*
- **Symptom:** after documents finish preparing, "Discover" refuses until the Preparation screen is explicitly closed; if that screen is not visited the user is stuck.
- **Cause:** `DiscoveryController.replace()` (`frontend/lib/knowledge/discovery.ts`) throws "A preparation workflow needs attention" if *any* `drivemind:preparation:v1:<owner>` record exists, including a completed queue (`current === entries.length`). `start()` then never calls the API.
- **Tests:** `KI-010 (today)` / `KI-010 (correct)`.
- **Suggested fix:** let discovery treat a *completed* queue as non-blocking (reuse `readPreparationGate` from `preparation-queue-store.ts`, do not re-parse storage); keep blocking for pending / failed / skipped / unknown records.
- **Needs your decision:** the owner stated discovery "should only block truly conflicting active/uncertain operations". Confirm a completed-but-unclosed batch counts as terminal. Failed/skipped batches are intentionally *not* covered by this test.

### KI-011 — The refusal names the wrong cause  *(user-visible, frontend)*
- **Symptom:** when preparation blocks discovery the user reads "The Drive check was not accepted. Verify your connection…", though the backend was never called and the connection is fine.
- **Cause:** `DiscoveryController.start()` catch-all maps every pre-API failure (preparation gate, storage denied, no Web Locks, lost intent) to one message.
- **Tests:** `KI-011 (today)` / `KI-011 (correct)`.
- **Suggested fix:** carry a reason from `replace()` (e.g. a small error code or subclass) and map it to distinct messages. Minimal change, no new state.

### KI-012 — "Check status" can do nothing  *(user-visible, frontend)*
- **Symptom:** the Check status button appears inert.
- **Reproduced cause (partial):** `PreparationQueue.check()` (`frontend/lib/knowledge/preparation-queue.ts`) does `if (this.busy …) return;`, so a click while any operation runs is discarded and returns at once; the caller cannot tell and the UI shows no result.
- **Tests:** `KI-012 (today)` / `KI-012 (correct)` (a second check must wait for / join the in-flight one).
- **Not reproduced:** when a check *does* run and still cannot verify, `blocked()` republishes the identical message, so a repeat click looks unchanged. No test yet because the desired UI (timestamp? reason?) is a product decision.
- **Suggested fix:** return the in-flight promise instead of dropping (join), then add a visible "checked just now / still unconfirmed because …" result.

### KI-020 — Indexing admission is a permanent fail-closed latch  *(unreproduced / needs decision, backend)*
- **Observation:** `IndexingSupervisor._fail()` (`backend/app/services/indexing_lifecycle.py`) sets `FAILED` and stops; nothing returns it to `READY` without a process restart. The handoff reports one hosted case that a restart recovered after a transient provider problem.
- **No test on purpose:** this may be deliberate (fail closed, supervised). Writing a "should recover" test now would assume the design. Decide: self-heal with bounded retries, or keep fail-closed but expose the reason and a clear operator action.

## Not covered by tests (cannot be checked locally without paid or live services)
- Real OpenAI answer quality, streaming timing through the Railway proxy, hosted deployment state. Measured separately (RAG evaluation phase).

## Fixed
*(none yet — move entries here with the commit hash when fixed)*

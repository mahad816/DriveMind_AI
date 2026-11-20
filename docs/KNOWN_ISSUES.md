# Known issues (executable registry)

Single source of truth for defects we **know about and have not fixed yet**. Each one has
a test that states the *correct* behaviour and is currently expected to fail, so the
suite stays green but the bug can never be forgotten or silently "fixed" without the
registry being updated.

## How the tests work

| Side | Where | Mechanism |
|---|---|---|
| Backend | `backend/tests/known_issues/` | `@known_issue("KI-xxx", ...)` = `xfail(strict=True, raises=AssertionError)` |
| Frontend | `frontend/lib/knowledge/known-issues.test.tsx` (currently none open; the file is recreated when one is added) | a "today" test pinning current behaviour + an `it.fails` test of the correct behaviour |

*Strict* means: when a fix makes the test pass, the suite goes **red** (XPASS / `it.fails`
passing). The fixer then removes the marker (backend) or changes `it.fails` to `it`
(frontend), and moves the entry below from **Open** to **Fixed**. Run them with:

```bash
cd backend  && uv run pytest tests/known_issues -rxX      # expect "passed, N xfailed"
cd frontend && npx vitest run lib/knowledge/known-issues.test.tsx   # only while a frontend issue is open
```

Rule for new entries: reproduce first, assert only what a user would call correct, add a
passing "guard" test for any neighbouring behaviour a fix must not break, and never mark
something known without a test (or say plainly that it is *unreproduced*).

## Open

### KI-022 — Wordy search queries find nothing (recall cliff)  *(retrieval quality, backend, reproduced by the evaluation, no unit test yet)*
- **Progress (2026-11-20, Step 1b):** generic and tiny file-name words no longer boost files (a question word must be 5+ letters and in at most 2 file names), and one long document can no longer fill all 8 slots (limit 3 per file). `sf07` and `mx07` now find their file. Still open: the all-words keyword search and the agent's own query writing (Step 1c).
- **Progress (2026-11-20, Step 1a):** the vector cut-off part is fixed: default `RETRIEVAL_SCORE_THRESHOLD` 0.35 -> 0.25, plus a new `RETRIEVAL_RELATIVE_THRESHOLD` 0.7. `sf01` now passes (dev, agent level), and the retrieval probe finds the right file for 98 % of plain questions (was 93 %). Still open: the all-words keyword search (Step 1b/1c) and generic file-name words that flood results (Step 1b). See `docs/EVALUATION_RESULTS.md`.
- **Symptom:** "How many days of annual leave do employees get per year?" answers "I could not find relevant information" (3 of 3 tries, tool agent) although the handbook says "Annual leave is 22 working days per calendar year."
- **Cause (measured):** the agent searches with the model's rewrite, `annual leave entitlement days per year employees get`. Vector retrieval returns 0 (all hits are below `retrieval_score_threshold = 0.35`) and keyword retrieval returns 0 (`websearch_to_tsquery` requires every word; "entitlement" and "get" are not in the file). `annual leave days per year` finds the file (keyword hit plus a 0.37 vector hit).
- **Reproduce:** `cd backend && uv run python -m evaluation.rag_eval.cli setup` then run the question through `RagService` on the `drivemind_eval_v2` store (see `docs/EVALUATION_RESULTS.md`). It needs an OpenAI key, so it has no unit test; a deterministic test would need a stored-embedding fixture.
- **Not fixed on purpose:** changing the threshold or the keyword mode changes retrieval for everything and needs its own evaluation. The corpus here has many whole-file chunks, which probably makes the effect stronger than on long documents (unmeasured).
- **Suggested direction:** make keyword matching tolerant (any-term ranking instead of all-terms), and compare a lower or relative vector threshold on the same cases before and after.

### KI-024 — File readers lose tables and slide notes, repeat page headers, and skip PPTX and XLSX  *(ingestion quality, backend, tests in `tests/known_issues/test_ki024_file_readers.py`)*

Measured on the generated fixtures in `backend/evaluation/corpus/messy/`:

- **DOCX: fixed in A2** (see Fixed below). Tables, headings and bullets are read; Google Docs are exported as DOCX.
- **PPTX: fixed in A3** (see Fixed below).
- **XLSX**: no reader exists, so these files are never ingested (A5).
- **PDF**: the running header and page number are repeated in the text of every page, and ruled tables come out as one cell per line, with no row structure (A4).

Fix plan (`docs/RETRIEVAL_FOUNDATIONS_PLAN.md`): A4 PDF header/footer removal and ruled tables, A5 XLSX (also Google Sheets). Each step removes its own `@known_issue` markers. Out of scope for now: scanned documents (OCR) and complex layouts.

## Not covered by tests (cannot be checked locally without paid or live services)
- Real OpenAI answer quality, streaming timing through the Railway proxy, hosted deployment state. Measured separately (RAG evaluation phase).

## Fixed
### KI-024 (PPTX part) — PowerPoint files were not read at all  *(fixed on branch `feat/extraction-a3-pptx`, Stage A3)*

PPTX and Google Slides were not a supported type, so decks were never indexed. They are now read slide by slide as light Markdown with tables and speaker notes (decisions and numbers often live only in the notes). Google Slides are exported as PPTX (plain text when Google refuses the export as too large). Tests: `tests/ingestion/test_pptx_extractor.py` (mutation-checked), `tests/connectors/test_google_drive_client.py`, `tests/known_issues/test_ki024_file_readers.py` (PPTX tests now ordinary regression tests). Existing decks need one full Drive scan to be discovered.

### KI-024 (DOCX part) — Word tables, headings and bullets were dropped  *(fixed on branch `feat/extraction-a2-docx`, Stage A2)*

The DOCX reader returned paragraph text only, so a fee table in a Word file could not be found. It now returns light Markdown in document order (headings, bullets, tables with a header row; merged cells keep their text once; nested tables are flattened). Google Docs are exported as DOCX instead of plain text (plain text only when Google refuses the DOCX export as too large). Documents now carry a `pipeline_version`; indexed files read by the older pipeline are read again once. Tests: `tests/ingestion/test_docx_structure.py`, `tests/known_issues/test_ki024_file_readers.py` (DOCX tests now ordinary regression tests), `tests/security/test_document_pipeline_version_pg.py`.

### KI-023 — A content question was answered with only "Latest indexed file: X"  *(fixed on branch `fix/agent-tools-and-refusals`, Step 1c)*
- **Was:** "How much was spent in the first half of 2026, and how much of the total budget is left?" was answered with `Latest indexed file: security_policy.txt`. The model's first tool call was the file-listing tool (`files_query LATEST`) in about half of identical calls (3 of 6 at temperature 0), and any listing result forces metadata-only output, so the question was never searched.
- **Fix:** `app/agents/tool_rag/registry.py`: the `files_query` description now says it works from file metadata only, cannot read document text, and must not be used when the answer is written inside a document, even if the question mentions a year or "latest". `search_knowledge` describes itself as the tool for any question answered by document text.
- **Evidence:** first-step probe, 20 repeats of this question: 20 of 20 search (before: about half). Agent level, 13 multi-file cases twice: 21 -> 24 of 26 pass, `ca03` 0 of 2 -> 2 of 2. Test split: 0 wrong-tool runs in 106. Details: `docs/EVALUATION_RESULTS.md`, "Step 1c".
- **Tests:** `backend/tests/agents/tool_rag/test_initial_messages.py` (the boundary wording and the 500-character limit), `backend/tests/evaluation/test_first_step_probe.py` (the probe that measures it). Whether the live model obeys cannot be unit-tested: use `python -m evaluation.rag_eval.first_step_probe --ids ca03 --repeats 20`.

### KI-001 — Greetings and small talk got the "no document evidence" refusal  *(fixed on branch `feat/conversation-reply-tool`)*
- **Was:** "Hello, can you hear me?", "Hi there", "Thanks a lot", "What can you do?" etc. were refused because the tool agent only recognised 10 exact phrases.
- **Fix:** `backend/app/agents/tool_rag/conversation.py` classifies the *meaning* of the message with one small model call (enum output only, any wording / order / Roman Urdu). Conversational intents get server-owned reply text, never model prose, and skip the agent, embeddings and SQL. Anything uncertain, malformed, slow, failing, over 300 characters or in demo mode falls back to the normal grounded agent.
- **Tests:** `backend/tests/agents/tool_rag/test_intent_gate.py` (wiring, fail-safe, no model prose). Recognition quality is measured separately by the live intent evaluation (see `backend/evaluation/`), not by phrase lists in unit tests.

### KI-002 — A real citation did not prove the claim  *(fixed on branch `fix/claim-grounding`)*
- **Was:** a claim the source does not say, carrying a valid `[source_N]` marker, was shown with a genuine citation (evidence "Authoritative refund policy text."; answer "Refunds are always approved within 90 days. [source_1]" was published).
- **Fix:** after the tool agent answers, `claim_check.py` asks `CLAIM_CHECK_MODEL` (default `gpt-5.4-mini`) which numbered statements assert a specific fact the evidence lacks or contradicts and removes them before citation handling; if nothing supported is left the normal "could not find" reply is used. It fails open (errors leave the answer unchanged), skips headings and fragments, and can be turned off with `CLAIM_CHECK_ENABLED=false`. One extra call per grounded answer: about +1.4 s median latency.
- **Measured (docs/EVALUATION_RESULTS.md, corrected test, two runs):** removes an invented sentence 41/41, catches a changed number 25/26, wrongly removes 0/41 true answers and 1/8 correct calculated answers; on RAGBench (general data, GPT-4o labels) precision 0.52 / recall 0.46 at response level. Not perfect: a wrong claim that is only implied by the evidence passes, a number changed inside a long sentence can slip through (`sv04`), and a unit conversion (minutes to hours) can be removed.
- **Scope:** tool agent only. The legacy pipeline and the LangGraph path are not checked.
- **Tests:** `backend/tests/agents/tool_rag/test_claim_check.py` (55); the former xfail test was removed.

### KI-010 — A finished preparation record blocked Drive discovery  *(fixed on branch `fix/discovery-preparation-gate`)*
- **Was:** after documents finished preparing, "Check Drive" refused until the Preparation screen was closed.
- **Fix:** `DiscoveryController` now asks the canonical `readPreparationGate`. A queue whose every document is confirmed ready is *cleared* (same as "Close completed preparation") and discovery proceeds. Pending, failed, skipped, legacy, unreadable, wrong-owner or unknown-version records still block and are never modified.
- **Why cleared, not merely ignored:** a later sync can change a prepared file, after which the completed record could no longer be verified, and "Close completed preparation" is disabled for unverifiable batches. Leaving the record would trap the user.
- **Tests:** `lib/knowledge/discovery-preparation-gate.test.tsx` (22) and one UI test in `components/files/drive-discovery.test.tsx`.

### KI-011 — The refusal named the wrong cause  *(fixed on branch `fix/discovery-preparation-gate`)*
- **Was:** every local refusal said "The Drive check was not accepted. Verify your connection…" though the backend was never called.
- **Fix:** typed `DiscoveryBlockedError` reasons with their own messages (unfinished preparation, unreadable preparation record, a discovery already pending in this browser, no safe tab coordination). Denied browser storage says so and states nothing was sent. The "verify your connection" text now appears only after a request really was sent and rejected.

### KI-012 — "Check status" could do nothing  *(fixed on branch `fix/check-status-join`)*
- **Was:** `PreparationQueue.check()` and `DiscoveryController.check()` did `if (busy) return`, so a click during any running check, or during a submit/confirm, was discarded instantly. The screens also poll every 3 to 5 seconds, so the button often landed mid-poll. And a check that found the same blocked message republished it unchanged, so even a real check looked like nothing happened.
- **Fix (control):** `lib/knowledge/joined-check.ts`. A click during a status check *joins* it (shares its single network read and resolves only when it truly finishes); a click during another operation waits for that operation, then checks. A finished check is never replayed from cache. Clicks can never submit work.
- **Fix (feedback):** `useManualCheck` shows "Checking…" (button disabled), then "Checked at HH:MM:SS. No change." or "Status updated." on the discovery buttons and the Preparation screen, so the outcome is always visible.
- **Deliberately not changed:** the "Check for files" (start) action still ignores a click while a check is running. Making it wait could let two submissions race, so it needs its own design.
- **Tests:** `joined-check.test.ts` (6), `check-status-join.test.tsx` (8, 4 fail without the fix), plus UI tests in `drive-discovery.test.tsx`, `preparation-progress.test.tsx` and `queue-preparation.integration.test.tsx`.

### KI-020 — Indexing admission was a permanent fail-closed latch  *(fixed on branch `fix/indexing-recovery`)*
- **Was:** any error in the indexing supervisor (even one slow database check on a busy machine) set `FAILED` for good; only a process restart reopened admission. Seen once locally as a flaky test (about 1 in 3 full runs under load) and once on the hosted app after a transient provider problem.
- **Fix:** the supervisor now separates a *momentary outage* from *real damage* (`is_transient` in `indexing_runtime.py`). Timeouts, dropped or refused connections and brief Qdrant or database unavailability are retried with backoff inside a bounded window (`INDEXING_OUTAGE_TOLERANCE_SECONDS`, default 30). One success resets the window. When the window runs out it closes exactly as before. A missing table or column, constraint errors, configuration or identity mismatches, vector-collection changes, any unknown exception, a failure while *executing* a stage, and incomplete session cleanup still close immediately. The unclear case stays fail-closed.
- **Also:** one admission probe that fails momentarily now refuses that one request (503) instead of closing the door for everyone; `check_database` no longer reports a broken schema as "unavailable"; a dead task always leaves a fixed diagnostic code (`EXECUTOR_TASK_FAILED`); `/api/v1/health/indexing` shows a fixed `degraded` code while a dependency is retrying. No error text is ever logged or exposed.
- **Tests:** `backend/tests/security/test_indexing_outage_recovery.py` (38) and one in `test_normal_indexing_runtime.py`. The existing fail-closed tests were kept; only the idle-claim-stall test got a tiny window so it still proves the bound.
- **Observed after the fix (2026-11-19):** in one full run on a machine busy with other work, two lifecycle tests (`test_normal_lifespan_synthetic_two_owner_pipeline_and_exact_job_polling`, `test_normal_issued_build_with_lost_acknowledgement_remains_blocked`) got a 503 on their first admission. Both pass alone, under CPU load, and in a later quiet run of all of `tests/security` (1026 passed). The cause was not reproduced; the likely cause is the new one-request refusal on a momentary probe error. That refusal is now logged with a fixed code so a recurrence names its cause. Watch for it.

### KI-021 — A PDF whose text contains a NUL character could not be stored  *(fixed on branch `fix/pdf-nul-characters`)*
- **Found by:** loading the evaluation corpus. 3 of 22 real research papers (math-heavy, large brackets) extract with U+0000, and PostgreSQL rejects it (`invalid byte sequence for encoding "UTF8": 0x00`). The ingestion code only catches extraction and Drive errors, so the database error was not handled per file.
- **Fix:** `normalize_extracted_text` (shared by every extractor) now drops U+0000 and changes nothing else.
- **Tests:** `test_pdf_extractor.py::test_extract_pdf_text_drops_nul_from_math_fonts` and two in `test_plain_text_extractor.py` (all three fail without the fix).
- **Not changed:** a persist-time database error on one file still is not turned into a per-file `FAILED`. That is a separate, wider question; this fix removes the one cause seen.

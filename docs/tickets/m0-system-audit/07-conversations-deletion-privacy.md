# 07: Conversation history, deletion and privacy audit (A4)

**Spec:** docs/specs/m0-system-audit.md
**What to build:** The Owner knows what DriveMind stores about each Owner, where, and what every existing delete or logout action actually removes and leaves behind (including whether deleting a conversation removes its linked query history), so no deletion or privacy claim is made before it is true.
**Blocked by:** None (can start immediately). Sequencing note: code inspection and the deletion-action analysis need no other ticket. Writing any new database-backed test waits until ticket 02 is resolved (or its baseline has otherwise verified the local container environment).
**Status:** ready-for-agent
**Progress:** resolved

## Scope

- Inventory stored items per Owner and location: conversations and turns, query history, Files, Documents, Chunks, vectors, credentials, sessions, jobs, traces or logs; in PostgreSQL, Qdrant and browser storage (`localStorage`).
- For each existing delete or logout action: what it removes and what remains, established from code and a focused test. Specifically answer, test-backed: does deleting a conversation remove its linked query history?
- Establish whether any backend Disconnect, Revoke or Delete-stored-data path exists. State the search method; a null search is reported as "no deletion path found", not as proof of absence.
- Describe what conversation history the answering path receives and its bounds, from code only. Sufficiency for follow-ups is an M1/M4 evaluation question, not decided here.
- Record facts only. No privacy claim is made.

## Out of scope

Building Disconnect, Revoke or Delete stored data (M7); changing retention; fixing defects; evaluating follow-up quality; live hosted data inspection.

## Inspect

`backend/app/services/conversation_repository.py`, `backend/app/api/conversations.py`, `backend/app/api/google_session_auth.py` (logout), `backend/app/api/index.py`, `backend/app/db/` (models, relationships, cascades), `backend/alembic/versions/`, `backend/app/embeddings/` (Qdrant), `backend/app/agents/` and `backend/app/evaluation/` (traces), `frontend/lib/conversations/`, `backend/tests/security/test_conversation_*.py`, GLOSSARY terms Disconnect / Revoke / Delete stored data.

## Deliverables

`## Findings` in this ticket: storage inventory, deletion-action matrix (action, removes, leaves), answer to the conversation-delete vs query-history question with the test name, history-bounds description. New focused tests (strict expected failure if a defect, passing if protecting correct behavior; registry entry for any new defect).

## Needs

No paid APIs. No live infrastructure. Local Docker for the focused database tests, after ticket 02.

- [x] Every stored item in the inventory has an identified deletion action or "no deletion path found", with the search method stated.
- [x] Each existing delete/logout action is documented with what it removes and what remains, backed by code and a focused test.
- [x] The conversation-delete versus query-history question has a test-backed answer, citing the test name.
- [x] The report states whether a backend Disconnect, Revoke or Delete-stored-data path exists, with search method.
- [x] The history the answering path receives and its bounds are described with code pointers.
- [x] Tests added are deterministic, free of paid API calls and meaningful; defect tests fail today for the stated reason. No database-backed test was written before ticket 02 was resolved or its environment verified. No application code changed.

## Findings

Audited 2026-11-21 on branch `feature/v2-state-performance`, base commit `5ed193e`. Code reading plus new focused tests against the disposable local PostgreSQL (ticket 02's environment, re-verified first: the existing conversation tests passed). **No application code changed.** No paid API, no Drive, Qdrant, Railway or OpenAI call. **No privacy claim is made here;** this is a record of what the code does today.

### Verdict

1. **Deleting a conversation hides it; it removes nothing.** `DELETE /conversations/{id}` sets `deleted_at`. The conversation row, every turn (with the original question text) and the linked `query_history` row (question, answer, citations) stay in PostgreSQL. **Answer to the ticket's question: no, deleting a conversation does not remove its linked query history.** Test: `tests/security/test_conversation_deletion_privacy.py::test_conversation_delete_keeps_every_row_today`.
2. **No backend Disconnect, Revoke or Delete-stored-data path was found** (search method in section 3). The only deletion route in the API is the conversation soft delete above. "Disconnect" in the interface is a text link that sends the Owner to Google Account permissions.
3. **Logout revokes one session row and removes nothing else.** The stored Google credential, Drive metadata, documents, chunks, jobs and conversations all stay, so the Drive connection survives logout. Test: `test_logout_revokes_only_the_session_row_today`.
4. **One new defect, KI-033:** an owner who has submitted even one question cannot be deleted from `users` (two foreign keys have no `ON DELETE` rule; the refusal is what the test observes, and PostgreSQL's cascade ordering is part of the mechanism). Not reachable today; it blocks a future Delete stored data. 2 strict expected failures in `tests/known_issues/test_ki033_user_delete_blocked_by_turns.py`.
5. **Owner decision needed (not made here):** what "delete conversation" should mean (hide, or erase the question, answer and citations). I did not register it as a defect, because retention is out of scope and the expected behaviour is undecided; the "today" tests pin the fact so a change cannot happen silently.

### 1. Storage inventory (per Owner)

| Item | Where | What is stored | Deletion action found |
|---|---|---|---|
| Account | PostgreSQL `users` | email, Google subject id | None. Rows are created at login; nothing deletes one |
| Google credential | `google_oauth_tokens` | encrypted OAuth envelope, scopes, grant status | None. Status can change (re-authorisation needed) but the row stays; logout does not touch it |
| Application sessions | `application_sessions` | credential hash, CSRF secret, expiry, `revoked_at` | Logout sets `revoked_at`. No code deletes session rows or sweeps expired ones |
| Login attempts | `oauth_pending_states` | PKCE verifier, nonce, hashes (10 minutes) | Deleted when the callback consumes it; abandoned rows are never swept (KI-032) |
| Drive file list | `drive_files`, `drive_sync_states` | name, mime type, folder path, modified time, state; change cursor | None. A file removed in Drive becomes `SKIPPED` and its row stays (`test_file_removed_in_drive_is_marked_skipped_and_nothing_is_deleted_today`) |
| Documents | `documents` | the full extracted text of each prepared file, its hash, pipeline version | None (only the cascade from the file or the user, which no code triggers) |
| Chunks | `chunks` | chunk text, metadata, full-text search vector | Re-chunking replaces a document's chunks, and a zero-chunk result removes them (`chunking_service.py:122-138`). No owner-level delete |
| Vectors | Qdrant collection | one point per chunk id: the embedding, plus payload `chunk_id`, `drive_file_id`, `filename`, `mime_type`, `modified_at`, `chunk_index`, `extracted_text_hash`, and `user_id` (outside demo mode only; `indexing_service.py:118-133`). No chunk text | Per-file stale reconciliation during build (`indexing_service.py:179`, `vector_store.py:343`) and an operator recovery service (`indexing_recovery.py:594`). No owner-wide or on-request delete |
| Indexing jobs | `indexing_jobs` | stage, file id, counters, error text, lease and attempt manifest | None |
| Conversations and turns | `conversations`, `conversation_turns` | title; each question as typed, status, error code, links to the answer | Soft delete only (below) |
| Answers | `query_history` | rewritten question, full answer, citations with snippets | None. Reached only through a turn. `POST /chat` without a conversation also writes a row that no conversation links to and no route can delete (code reading; the mounted interface calls `/chat` only in demo mode, where persistence is off) |
| Browser, normal mode | `localStorage` | `drivemind:session-transition:v1` (random nonce), `drivemind:preparation:v1:<owner>`, `drivemind:discovery:v1:<owner>` and a coordination key (file ids and progress), `drivemind:knowledge-last-prepared`, `drivemind:onboarding-complete` and `-oauth`. No conversation text: the server sidebar is used | Preparation and discovery records are removed when a run finishes. **Logout removes none of them** (the logout code only clears the in-memory owner and broadcasts a nonce, `application-session-provider.tsx:144-165`) |
| Browser, demo mode only | `localStorage` `drivemind:demo:*`; the key family `drivemind:v1:normal:<owner>:conversations` and `:conversation-messages:<id>` is defined in `scope.ts:43-48` but its only writers are the demo chat interface and the demo sidebar (`use-conversations.ts` is used only by those two) | conversation list and message text | Per-conversation delete in the demo sidebar (`messages.ts:127-134`). Not used by the normal interface |
| `drivemind:connected-email` | `localStorage` | an email | Helpers exist (`settings/storage.ts`) but no mounted code reads or writes it |
| Traces and logs | process memory, hosting logs | Evaluation traces are in memory only, never logged or persisted (`app/evaluation/trace.py` docstring). No `logger.*` call site was found that formats question or answer text (search below; exception text and access logs were not inspected) | Not applicable. Hosting-platform logs were not inspected |

### 2. Deletion-action matrix

| Action | Removes | Leaves | Evidence |
|---|---|---|---|
| **Delete conversation** (`DELETE /conversations/{id}`, `conversations.py:179`, `conversation_repository.py:212-234`) | Nothing. Sets `deleted_at`, raises both version counters, marks any still-running turn `INTERRUPTED` (`CONVERSATION_DELETED`). The owner can no longer get, list, or replay it | Conversation row, all turns with question text, all `query_history` rows (question, answer, citations). Other owners' data identical | `test_conversation_delete_keeps_every_row_today`, `test_deleted_conversation_is_hidden_from_its_owner`, `test_conversation_delete_leaves_query_history_reachable_by_id_nowhere_in_the_api`; older `test_conversation_repository.py::test_metadata_and_tombstone_fence` |
| **Logout** (`POST /auth/session/logout`, `google_session_auth.py:196`, `application_session_service.py:196`) | Cookie cleared; the one session row gets `revoked_at` | The session row, Google credential, Drive metadata, documents, chunks, jobs, conversations, query history, Qdrant points, browser records. A second session of the same owner stays valid | `test_logout_revokes_only_the_session_row_today`; HTTP behaviour (CSRF, cookie, 401 afterwards) already in `test_google_session_postgres.py` |
| **File removed or trashed in Drive** (during sync, `drive_sync_service.py:228-241`) | Nothing; file state becomes `SKIPPED` (it leaves retrieval) | File row, document text, chunks (tested); Qdrant points (code reading: sync has no vector-store access) | `test_file_removed_in_drive_is_marked_skipped_and_nothing_is_deleted_today` |
| **Re-chunk / stale-vector reconcile** (inside indexing) | Old chunks of one document; Qdrant points not in the current chunk set for one file | Everything else | `chunking_service.py:122-138`, `indexing_service.py:179` (existing indexing tests; not re-run separately here) |
| **Delete a `users` row** (no code does this; the database rule) | Would cascade to all ten per-owner PostgreSQL tables counted by the tests (`oauth_pending_states` and `users` itself are not among the ten), **only if the owner has no turn** | Qdrant points, browser storage. With any turn the delete is refused (KI-033) | `test_deleting_a_user_who_never_asked_a_question_cascades_to_every_owner_table`; KI-033 tests |

### 3. Is there a backend Disconnect, Revoke or Delete-stored-data path?

**No deletion path found.** Search method (a null result is not proof of absence):
1. The real route list from `create_app().openapi()` (23 paths). Only one HTTP DELETE exists: `/api/v1/conversations/{conversation_id}`. No path contains disconnect, revoke, purge, erase, wipe, account, delete-data or forget. Pinned by `test_only_one_delete_route_exists_and_none_is_named_disconnect_revoke_or_purge`. (`app.routes` is a lazy router in the pinned FastAPI, so the test uses the OpenAPI document; it asserts the list is not empty.)
2. `grep -rnE "\.delete\(|delete\(|ondelete|cascade|revoke|disconnect|logout|TRUNCATE|DROP " backend/app backend/alembic/versions`. Hits that remove rows: chunk replacement, expired login attempts, the legacy callback, and Qdrant stale points. Nothing deletes users, tokens, sessions, files, documents, jobs or conversation rows.
3. Frontend `grep -rniE "disconnect|revoke|delete (my|all|stored)|remove (my|all)"`: the only match is `disconnectHelp: "Opens Google Account permissions to revoke DriveMind access."` (`user-language.ts:128`), a link to Google. **Revoke** (at Google) is therefore the Owner's own action; DriveMind never calls Google's revoke endpoint and never removes its stored credential (GLOSSARY: Disconnect, Revoke, Delete stored data are all unbuilt; M7).
4. Operator tools: `backend/app/ops/` (`indexing_recovery.py`, `qdrant_tenant_inventory.py`, `qdrant_tenant_repair.py`) were also searched; they contain no delete, remove or purge of owner data apart from the stale-point removal named in section 1. `vector_store.py:331` (`delete_points`) is the only Qdrant delete call; `set_payload`-style paths change points without deleting them. The repo root `scripts/` is empty.
5. The Settings screen has only "Sign out of DriveMind" (`settings-drive-section.tsx:20`).

### 4. What conversation history the answering path receives (code only)

Whether this is enough for follow-ups is an M1/M4 question and is not judged here.
1. **Source:** the server, not the browser. For a conversation turn, `ConversationChatService._context` (`conversation_chat_service.py:149-165`) reads `completed_context` (`conversation_repository.py:511-550`): only **COMPLETED** turns of that conversation, owned by the caller, not deleted, with `sequence` up to the turn's `history_end_sequence`. Failed and interrupted turns are never sent.
2. **Bounds at that step:** at most 4 question-answer pairs (the query fetches 5 to detect more), at most 8000 characters for each question and each answer, at most 24000 characters in total. A pair over a limit stops the selection (an older answer is never substituted). Oldest pair first.
3. **`history_window_complete`** is false when: an earlier turn did not complete, there are more than 4 pairs, or a pair was cut. The history-recall route says "not in the available recent history" instead of guessing when false.
4. **Bounds on the public `/chat` request** (`schemas/chat.py:36,63-66`): at most 8 messages, each at most 8000 characters, 24000 in total; non-empty history needs a conversation id. Test: `test_chat_request_accepts_at_most_eight_history_messages_and_24000_characters`.
5. **Bounds inside the answering path:** query rewriting and the tool agent both use `bounded_rewrite_history` (`conversation_history.py:92-107`): the last 6 messages, 2000 characters each, 6000 in total, kept newest first. The agent also replaces identifier-looking text in prior messages with "[unavailable prior identifier]" (`tool_agent_service.py:54-68`) and does not replay earlier tool calls. Test: `test_rewrite_and_agent_history_is_at_most_six_messages_and_6000_characters`.
6. **Intent check:** `classify_intent` takes the previous assistant message cut to 300 characters (`agents/tool_rag/conversation.py`, `MAX_CONTEXT_CHARS`). I did not trace its call site.
7. Net: 4 pairs fetched, but at most the last 6 messages (3 pairs) and 6000 characters reach the model-facing steps.

### 5. Tests added (all deterministic, no paid call)

- `backend/tests/security/test_conversation_deletion_privacy.py`: 10 tests (6 need the disposable PostgreSQL; 4 run without it: route inventory, "Revoke is a Google link", history bounds x2). 10 pass.
- `backend/tests/known_issues/test_ki033_user_delete_blocked_by_turns.py`: 2 strict expected failures (KI-033), failing with the foreign-key violation, not by accident.
- Registry: `docs/KNOWN_ISSUES.md` KI-033.
- Environment: disposable `drivemind-test-pg` (127.0.0.1:55432, database `drivemind_session_test`, per-test schema), written after ticket 02 was resolved. `OPENAI_API_KEY` not set.

### 6. Caveats

- Qdrant behaviour (what is in the points, that sync never deletes them, which paths delete) is from code reading; no Qdrant container was used.
- The delete-conversation tests pin today's behaviour with "today" in the name. They are facts, not endorsement: when the Owner decides the meaning of delete, change those tests and the matrix together.
- The route search covers the mounted API and the code in this working tree. The legacy auth router (`app/api/auth.py`, unmounted) was not audited for deletion paths.
- "Logout removes no browser records" is from reading the logout code; no browser test was run. Nothing else clears those keys either, apart from the run-finished removals named above.
- Hosted data (what is actually stored on Railway, platform logs, backups, retention) was not inspected. Backups and provider-side copies (OpenAI request retention, Google) are outside this audit.
- `application_sessions` and `indexing_jobs.attempt_manifest` contents beyond column names were not inspected for personal text.
- `classify_intent`'s call site and the legacy tool-agent `history` use outside the paths named above were not traced.
- Full backend run on this change: `2639 passed, 376 skipped, 13 xfailed` in 8 min, with only `SESSION_TEST_DATABASE_URL` set. The 376 skips are tests that need a Qdrant container (not started for this audit), so this is not the full 24-minute container baseline.

## Comments

### Self-review (2026-11-21, superseded)

Inline check by the implementing agent: ruff and basedpyright clean. Not independent; replaced by the reviews below.

### Independent reviews (2026-11-21, commit `1fb87a0`)

Two separate read-only sub-agents reviewed the commit; the earlier inline self-review above is superseded.
- **Standards:** no hard violations; scope clean (2 test files and 2 docs, no application code). Judgement items, fixed: the KI-033 test now asserts the refusal names `fk_turns_session_owner` or `fk_turns_result_owner` (so another integrity error cannot hide behind the expected failure; with `--runxfail` it fails on the intended assertion); the replay test was renamed `test_deleted_conversation_result_is_no_longer_replayable` and has a positive control; the document lookup is filtered by owner; the frontend text test uses a module-level path; the private `_mark_file_removed` call is commented. Left as is: shared helpers imported across test files (existing convention), the broad `account` word in the route search.
- **Spec and correctness:** citations and the table inventory hold; no missing owner table found. Corrections applied: Qdrant `user_id` exists outside demo mode only; the log statement now says only that no `logger.*` call site was found (exception text, access logs and hosted logs not inspected); `app/ops/` and the other Qdrant paths are named in the search; the `drivemind:v1:normal:<owner>:*` key family is listed with its demo-only writers; the KI-033 mechanism wording is softened; the "ten tables" excludes `oauth_pending_states` and `users`. Not done: restating the search against every "None" row (section 3 states it once for the whole inventory).

### Owner decisions (2026-11-21)

1. **Delete conversation must eventually mean permanent deletion** of its questions, answers, citations and related stored conversation records, not only hiding with `deleted_at`. This is a **future privacy implementation requirement** (M7 or the milestone that owns privacy). **No M0 behaviour change**: the "today" tests keep pinning the soft delete, and must be changed together with that implementation.
2. **Separate actions are required**, each with its own meaning and clear data-retention rules: **Disconnect Google** (stop using the authorisation and remove the stored credential), **Revoke Google access** (withdraw it at Google), and **Delete stored data** (remove what DriveMind stored about Files and conversations). None exists today (section 3). Retention rules, including what happens to Qdrant vectors, browser records, backups and provider copies, are to be written before any deletion claim is made.
3. **KI-033 stays registered.** Its two tests establish the blocker: the refusal comes from `fk_turns_session_owner` or `fk_turns_result_owner`, checked by name.

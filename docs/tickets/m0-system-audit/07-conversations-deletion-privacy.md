# 07: Conversation history, deletion and privacy audit (A4)

**Spec:** docs/specs/m0-system-audit.md
**What to build:** The Owner knows what DriveMind stores about each Owner, where, and what every existing delete or logout action actually removes and leaves behind (including whether deleting a conversation removes its linked query history), so no deletion or privacy claim is made before it is true.
**Blocked by:** None (can start immediately). Sequencing note: code inspection and the deletion-action analysis need no other ticket. Writing any new database-backed test waits until ticket 02 is resolved (or its baseline has otherwise verified the local container environment).
**Status:** ready-for-agent
**Progress:** open

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

- [ ] Every stored item in the inventory has an identified deletion action or "no deletion path found", with the search method stated.
- [ ] Each existing delete/logout action is documented with what it removes and what remains, backed by code and a focused test.
- [ ] The conversation-delete versus query-history question has a test-backed answer, citing the test name.
- [ ] The report states whether a backend Disconnect, Revoke or Delete-stored-data path exists, with search method.
- [ ] The history the answering path receives and its bounds are described with code pointers.
- [ ] Tests added are deterministic, free of paid API calls and meaningful; defect tests fail today for the stated reason. No database-backed test was written before ticket 02 was resolved or its environment verified. No application code changed.

## Comments

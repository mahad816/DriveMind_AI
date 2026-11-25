# DriveMind product, UX and workflow audit

> Historical snapshot of 2026-11-25 at `45a3f0c`. Preparation findings were subsequently addressed by Checkpoint A (`7d8764d`); the UI was replaced by Marginalia (`70c2ee6`). This document preserves the original observations, not a current unresolved-issue list. See [integration verification](../guides/INTEGRATION_VERIFICATION.md) and the Checkpoint A/frontend-rebuild tickets for later evidence.

Audit date: 2026-11-25. Branch `feature/v2-state-performance`, HEAD `45a3f0c`, working tree dirty (see "Baseline").
Companion documents: `product-ux-issues.md` (register), `product-ux-roadmap.md` (checkpoints).
No product code was changed. No document was prepared, no paid call was made, nothing was deleted.

**Privacy note.** This repository is public. The audited Drive holds real documents, so no screenshot is stored here and
no real file name appears. Screens are described in words. Screenshots exist only in the auditor's local session.

## Evidence labels

LIVE = observed in Chrome. TEST = reproduced by a deterministic test. CODE = read in source. INFERRED = plausible, not
verified. BLOCKED = not safely testable.

## Baseline

- Frontend `https://localhost:3000` (Next.js dev server, HTTPS, `reactStrictMode: true`). Backend `127.0.0.1:8000`.
- Backend holds live connections to database `drivemind_local` (LIVE, via the database's own connection list).
  Qdrant collection `drivemind_local_chunks` exists. That the backend writes to that collection is **not verified**:
  reading `backend/.env` was denied by the permission system and was not worked around.
- Inventory at audit time: 516 files (514 not prepared, 1 ready, 1 skipped, 0 preparing).
- Pre-existing uncommitted changes (14) and `.claude/skills/.../SKILL.md` were preserved. The only file added by the audit
  work is `frontend/lib/knowledge/preparation-queue.failure-isolation.test.tsx` (7 tests: 4 intentionally red, 3 guards)
  plus these three documents.

## Route inventory (from `frontend/app`, not from the navigation)

| Route | Purpose | Reached live | Notes |
|---|---|---|---|
| `/` | Entry: "Checking your sign-in…" then redirect | yes | Blank-ish wait of about 3 s before redirect to `/chat` |
| `/chat` | New-chat landing, composer, three suggestion chips | yes | Not sent: sending is a paid model call |
| `/chat/[id]` | A conversation | yes (empty and invalid id) | Answers, citations: BLOCKED |
| `/files` | Library: tabs, search, table, paging, preview drawer, selection, review | yes | Preparation start: BLOCKED |
| `/index` | Alias | yes | Redirects to `/files` |
| `/prepare` | Queue progress screen | yes (empty state only) | Active queue: BLOCKED |
| `/onboarding` | Four-step setup | yes | Reachable while signed in |
| `/settings` | Account, Drive, appearance, knowledge | yes | Sign-out and reconnect not clicked |
| `/sources/[chunkId]` | Source/citation viewer | yes (invalid id only) | Real source: BLOCKED (needs an answer) |
| anything else | `not-found` | yes | Minimal 404 inside the app shell |

There is no hidden or unreachable page. `loading.tsx` and `error.tsx` route files do not exist (CODE), so route-level
errors fall back to the framework default.

## What was exercised live

Settings (all sections read, theme switched to Light and back to System, "Check sync status" not on this page),
Files (tabs, search with three queries, preview drawer open and Escape, selecting two files, Review step, Back, Clear),
Chat landing (composer typing, suggestion chips read but not clicked, New Chat twice), invalid conversation id,
invalid source id, 404, onboarding, prepare empty state, `/index` redirect, Check sync status (read-only), mobile menu
open and Escape, keyboard tab order, a read-only probe of three GET endpoints (18 requests), responsive checks, contrast
measurement, 30-second idle request count.

Side effect of the audit: two **empty conversations** now exist in `drivemind_local` (created by two New Chat clicks;
see C-01). They were not deleted.

## Blocked by safety rules (not verified, do not assume they work)

- Starting preparation (INGEST, CHUNK, BUILD): reads real documents and BUILD uses the paid embedding API. So the failed
  file scenario, per-file progress, retry, cancel, reload during preparation, unknown outcome, session expiry and
  disconnected Drive were **not** exercised in the browser. Only the 72 existing queue tests plus the 7 new ones cover them.
- Sync Drive (writes inventory, calls Google), Reconnect Google Drive, Sign out, sign-in screen, session expiry.
- Sending a chat message: answers, streaming, Stop, Retry, long responses, tables, code blocks, citation markers,
  citation navigation, source previews, unsupported-answer messages.
- Conversation options menu (rename or delete: destructive), deleting anything.
- Exact 390 px width: the browser window cannot go below about 455 px, so mobile checks ran at 455 px.
- Requested 1024 and 768 px windows measured as 1309 px and 698 px of viewport. Reported widths are the measured ones.
- Draft preservation across in-app navigation: inconclusive. New Chat opens a fresh conversation, so the test did not
  isolate a draft. A full page load did drop an unsent draft (expected for a reload).

## Product understanding

DriveMind reads a user's Google Drive read-only, lets them choose up to five documents at a time, prepares them
(extract, split, embed) one document at a time with an explicit confirmation before each next document, and answers
questions with citations. Discovery (finding file names) and preparation (making content searchable) are separate, and
the interface says so repeatedly.

First impression: the signed-in experience is calm and coherent. The landing explains the purpose in one sentence, the
Files page is readable, and Settings is short. The main weaknesses are in copy that leaks internal wording, the
five-at-a-time model against a 516-file Drive, the queue's inability to continue past a failed file, and a handful of
state and feedback gaps.

## Journey notes

### A. Authentication and onboarding
- Already signed in, so first-visit and sign-in screens were not seen (BLOCKED). `/` shows only "Checking your sign-in…"
  for about 3 s (LIVE).
- `/onboarding` lists four steps: steps 1 and 2 show "Complete", steps 3 and 4 show no state even though 516 files are
  already discovered (LIVE, L-02). Returning users can still open it.
- Settings states the session consequence of signing out clearly ("Prepared documents and Google Drive permissions are
  kept") (LIVE). Good copy.

### B. Drive connection and sync
- Settings: "Google Drive connected", plus "Refresh Drive status", "Manage Google access", and a primary-styled
  "Reconnect Google Drive" shown while healthy (LIVE, S-01). "Connected" and "synchronized" are different facts: the
  Files page says "1 file is ready for chat" and offers "Check sync status", which reports "Checked at HH:MM. No change."
  (LIVE, clear).
- Check sync status sends two identical status requests per click (LIVE, P-02).

### C. Library
- Tabs: To prepare (514), Ready (1), Preparing (0), All (516). The skipped file belongs to no tab except All (F-06).
- Search is case-insensitive substring over all 516 files, not just the visible page (LIVE). It does not treat `_` as a
  space, so a two-word query misses a name that uses underscores (F-03). Search silently stays inside the selected tab.
- Empty Preparing tab says "No files match your search or filter" although nothing was searched (F-02).
- Page size 12 (43 pages). Disabled rows (ready, skipped) have nearly invisible checkboxes (V-02).
- Selection: after Review then Back, every checkbox and the Review button are disabled for a few seconds with the text
  "Check file inventory and existing preparation before making…", then recover on their own (LIVE, F-01). My first two
  coordinate clicks landed in that state or missed; a later element-targeted click worked.
- Preview drawer: opens, Escape closes it, focus returns to the filename. It shows type, status, folder, modified date,
  "Select for preparation" and "Open in Google Drive". It is explicitly "File details only" (F-06 note).

### D. Preparation (code and tests only; see queue findings)
See `product-ux-issues.md` Q-01 to Q-04 and the state model below.

### E. Chat
- Landing: heading, one sentence, three suggestion chips, composer with a disabled send button until text exists.
- Every New Chat click sends `POST /conversations` and persists an empty conversation immediately (LIVE, C-01).
- Invalid conversation id: "Conversation unavailable or loading. Select a conversation or start a new chat." with a
  composer that says "Sending is unavailable; you can still edit your draft." One message covers "loading", "missing"
  and "not yours" (C-02).
- Source page with an invalid id: "Source chunk not found" in red with two buttons both labeled "Open chat" (C-03).
- Everything about answers and citations: BLOCKED.

### F. Settings
Short and understandable: Account, Google Drive, Appearance (System / Light / Dark), Knowledge ("Manage files"), version
line. No diagnostics or job identifiers appear in the main interface (LIVE). Good. "Manage files" duplicates the sidebar
Files link.

### G. Shell and navigation
Sidebar (New Chat, chat list with search, Files, Settings, "1 document ready"), collapsible. At about 700 px and below
it becomes a hamburger drawer that opens, closes on Escape and returns focus (LIVE). No breadcrumbs, no user menu. Only
`/files` and `/settings` are in the sidebar; Prepare is reachable only from flows (reasonable).

## Visual design findings

- Theme: Appearance defaults to System. On a dark OS the app is a warm charcoal dark theme. The parchment look from the
  design brief is the **Light** theme only (LIVE). A new user on a dark OS never sees the identity. This is a decision,
  not a defect (V-01).
- Typography: serif display for page titles and the chat hero, sans for interface text (LIVE). Readable. Smallest text
  is 10 px (tab counts) and 11 px (relative timestamps) (A-02).
- Contrast (computed, text against page background only, Light theme on `/files`): lowest 5.67:1 (muted labels). Dark theme
  settings page: body 17.5:1, secondary 10.2:1. Measured on two pages and one background colour only; **not** a
  compliance claim. Text on buttons and on non-body surfaces was not measured.
- Layout: single column with generous margin, table with four columns on desktop, two on tablet and mobile. No horizontal
  overflow at the measured widths (1309, 698, 455).
- Motion: a `prefers-reduced-motion` rule exists (CODE and LIVE). Transitions seen: drawer slide, tab selection. No
  distracting or slow animation noticed. Page-to-page and state-change feedback were not measured.

## Accessibility findings (measured, not a compliance claim)

Present: `lang="en"`, one `h1`, `main`, `header`, `aside`, three `nav` landmarks, no image without `alt`, visible focus
indicators (outline plus shadow), Escape closes drawers and restores focus, 44 px touch targets for menu, send and tabs
on mobile, checkbox label target 36 by 44 px (checkbox itself 15 px).
Missing or weak: no skip link, so 12 Tab presses reach the first page control past the sidebar (A-01); 10 to 11 px text
(A-02). Screen-reader behaviour, error announcements and dialog focus traps beyond the two drawers were not tested.

## Performance and request patterns

- Idle on `/files` for 30 s: 7 `GET /index/status` and 1 `GET /auth/session`, no `/files` refetch (LIVE). Roughly one
  status call every 4 to 5 s, session check every 30 s.
- Backend cost of those calls (direct GET from the page, 6 rounds each): median 20 ms (`/index/status`), 29 ms
  (`/files`), 19 ms (`/conversations`), 0 of 18 failed (LIVE). At one user this is cheap, so it is **not a confirmed
  defect**; it is wasted work when no job is running (P-01).
- Code: several pollers exist (3 s in the queue, single-file, legacy preparation and library gate views; 5 s in discovery;
  30 s session check; a deduplicating connection-status provider). The 3 s loops belong to preparation screens.
- The network log shows many `GET` pairs returning 503 then 200 (`/conversations`, `/files`). Direct fetches never
  returned 503, the client has no 503 retry, and strict mode is on. Most likely aborted-and-restarted dev requests that
  the extension reports as 503. INFERRED, verify on a production build (P-03).
- 516-row inventory renders as pages of 12, so there is no list-size problem.
- Not measured: rerenders, layout shift, memory growth, polling after unmount, polling while the tab is hidden.

## Frontend and backend contract (queue)

Chain: user selects (max five) → `reserve()` re-reads `/files` and `/index/status`, checks owner and frame → writes a
queue record to browser storage under a lock → per document `confirm()` sends INGEST, then CHUNK, then BUILD, each with
an intent write before the request and a receipt write after → `check()` polls exact jobs → `ready` advances the cursor
in one atomic write → next document needs another explicit confirmation.

The frontend treats these conservatively and correctly: lost acknowledgement (unknown), `recovery_required`, disconnected
Drive, owner or session change and changed document metadata all block. Accepted jobs are not treated as failures.
The single design gap: **a clean, file-specific failure is treated like an unknown outcome** and halts the batch.

## State model: preparation queue

| From | Event | To (today) | Gap |
|---|---|---|---|
| idle | reserve (1 to 5 files) | review | none |
| review / awaiting_next | confirm | progress (stage submitted) | none |
| progress | stage job completed, not BUILD | progress then continue prompt | none |
| progress | BUILD completed and file indexed | awaiting_next or complete | none |
| progress | job failed or canceled, no recovery flag | **stopped** | **no way forward except close; cursor cannot move past a failed entry** |
| progress | job completed with skipped | **stopped** | same |
| progress | recovery flag, unknown receipt, disconnected Drive, session change | blocked | correct, must stay |
| stopped | finish | idle (unstarted files discarded) | silent loss of the plan |
| stopped | retry the failed file | impossible | `preparationEligibility` rejects failed and skipped files |
| any | cancel | no control found (CODE) | cancel exists only as a job status |
| any | reload | resumes from stored record, observation only | correct |

Schema rule that enforces this: `validateQueue` requires every entry before the cursor to be `ready`.

## Failure classification the fix must respect

- File-specific, safe to continue (with explicit confirmation): job `failed` or `canceled` or completed-with-skipped,
  no `recovery_required`, Drive connected, receipt has a job id, owner and session unchanged.
- Global, queue must stay paused: lost or unconfirmed acknowledgement, `recovery_required`, disconnected Drive, owner or
  session revision change, "Queue changed" or "document changed" evidence conflicts, another active job.
- Unknown outcome: never auto-retry; duplicate work risk.
- Guard tests for these already pass today and must stay green.

## Open questions for the owner

1. May a failed document be retried? That needs a backend guarantee that re-running INGEST on a `failed` file is safe.
2. Is the five-document batch limit a safety requirement or a beta cap?
3. Should the default theme stay "System", or default to the parchment Light theme?
4. A safe live reproduction of the queue needs a seeded disposable database or a stubbed backend. Which?

## Caveats

All queue findings are TEST and CODE, not LIVE. Performance numbers come from a single short session on a development
server with Strict Mode and may differ in production. Contrast figures are partial. Everything in the BLOCKED list is
unverified and must not be assumed to work or to fail.

# DriveMind target experience and implementation roadmap

> Historical snapshot of 2026-11-25 at `45a3f0c`. Preparation findings were subsequently addressed by Checkpoint A (`7d8764d`); the UI was replaced by Marginalia (`70c2ee6`). This document preserves the original observations, not a current unresolved-issue list. See [integration verification](../guides/INTEGRATION_VERIFICATION.md) and the Checkpoint A/frontend-rebuild tickets for later evidence.

Based on `product-ux-audit.md` and `product-ux-issues.md` (2026-11-25, HEAD `45a3f0c`). Nothing here is implemented.
Each checkpoint ends with an independent `drivemind-reviewer` pass, then stops for the owner. No push, deploy or paid call
without explicit approval. The three existing Checkpoint-A guard tests must stay green throughout.

## 1. Product direction

DriveMind is a calm, trustworthy research tool over the user's own documents. Keep what works: read-only framing, the
discovery-versus-preparation distinction, a warm paper identity, restrained motion, no technical identifiers in the main
interface. Change only what the audit proved: a queue that cannot continue after one failure, internal wording in
messages, silent or ambiguous states, and a few small accessibility gaps. No new features beyond fixing these.

## 2. Information architecture

Keep the sidebar (New Chat, chats, Files, Settings). Proposed adjustments:

- Files page is the home of the preparation workflow: selection, review, progress and summary live on it (or one
  linked screen), not scattered across `/prepare`, `/onboarding` and the library.
- `/onboarding` becomes a checklist that reflects real state (discovery done, N documents ready) and is hidden once
  complete; keep the route.
- Add a "Needs attention" view for failed and skipped files beside To prepare, Ready, Preparing and All.
- Settings keeps four sections; remove the duplicate "Manage files" link or give it a reason.
- Technical detail (job ids, stages, recovery flags) goes to a collapsed "Details" area, not primary text.

## 3. File selection and preparation workflow

1. Select up to the batch limit (limit stays until the owner decides, Q-04).
2. Review (unchanged: "You'll confirm before each next document starts").
3. Prepare: one queue screen with a row per document: Queued, Preparing (stage name only if known), Ready, Failed,
   Skipped, Paused. No invented percentages: show the stage (Reading, Splitting, Indexing) and elapsed time only.
4. After a file-specific failure: that row shows the plain-language reason and the next document is offered with the
   same explicit confirmation. After a global problem: the whole queue shows "Paused" with the single action that fixes
   it (reconnect, check status), and no document is offered.
5. Summary: "2 ready, 1 failed, 2 not started", with Retry (once allowed) and Close. Closing never silently drops files.
6. Reload or leaving the page: the queue resumes in observation mode and never submits by itself (existing behaviour).

Failure classes (from the audit, to implement exactly): file-specific continues; global pauses; unknown never retried.

## 4. Chat and citation workflow (after queue work)

Create a conversation on first message, not on the New Chat click. Separate "loading", "not found" and "no access".
Keep draft per conversation. Citation markers open a source panel that shows the passage and the file name with a single
"Back to chat" action. Errors and Retry stay inline on the failed message. These need fixtures because real answers are
paid calls.

## 5. Design tokens (starting point, to be confirmed against `globals.css` before any change)

- Type: keep the serif for titles and the chat hero, sans for interface. Scale 12, 14, 16, 20, 28 px; nothing under 12 px.
  Body line height 1.5, reading width 65 to 75 characters in chat.
- Colour: keep the existing warm tokens; define roles, not new colours: background, surface, raised, text, muted text,
  border, accent, success, warning, danger, disabled, focus ring. Muted text stays at or above 4.5:1 on its surface.
  Add a visible disabled style (see V-02).
- Spacing: 4 px base, steps 4, 8, 12, 16, 24, 32. Content width about 1000 px for tables, about 720 px for forms.
- Radius and heights: one radius for controls, one for cards; controls 40 px, touch targets 44 px on touch widths.
- Motion: 150 ms for hover and press, 200 to 250 ms for drawers and dialogs, one ease-out curve, transform and opacity
  only, all disabled under `prefers-reduced-motion`. Animation only to show state change (row status, drawer, toast).

## 6. Component consistency rules

One button set (primary, secondary, ghost, danger) with primary used once per screen; one link style; one status badge
used for file and queue states; one empty-state component (icon-free, one sentence, one action); one inline error
component with a retry; one dialog and one drawer behaviour (Escape closes, focus returns, focus trapped).

## 7. Responsive and accessibility rules

Table keeps name and status at small widths and moves folder under the name. Skip link first. Dialogs fit 90% of the
viewport. Errors use `role="alert"`, status changes use `role="status"`. All interactive targets at least 24 px, 44 px on
touch widths.

## 8. Checkpoints

Order minimises repeat edits: logic first, then structure, then screens that use it, then the design system last.

### A — Workflow reliability (complexity: high, risk: high)
- Scope: Q-01, Q-03, F-01, C-01. Q-02 only after the owner decision.
- Files: `lib/knowledge/preparation-queue.ts`, `preparation-queue-store.ts`, `single-file-preparation.ts`,
  `components/files/knowledge-library.tsx`, conversation creation in `server-chat-interface.tsx` and its controller,
  existing queue tests (one test edited on purpose), the new `preparation-queue.failure-isolation.test.tsx`.
- Dependencies: owner answers on retry and batch limit; a seeded disposable database or stubbed backend for live checks.
- Acceptance: the 4 red tests pass, 3 guards and the existing 72 queue tests pass (with the one intentional edit),
  schema v3 migrates or rejects v2 records safely without touching them, selection stays enabled during refetch,
  two New Chat clicks make at most one empty conversation.
- Tests first (failing, then green): queue cursor with failed and skipped entries, schema validation, atomic handoff,
  reload mid-queue, global-failure guards, selection during refetch, conversation creation.
- Browser verification: stubbed backend with a scripted failure on file 2 of 3; observe continue, summary, reload.
- Review: independent reviewer, then stop.

### B — Information architecture (medium, medium)
- Scope: F-03, F-06, F-07, S-01, L-02, onboarding as a state-driven checklist, "Needs attention" view.
- Files: `components/files/*`, `components/onboarding/*`, `components/settings/*`, `lib/navigation.ts`.
- Acceptance: tab counts sum to the total, search matches across `_ - .`, folder visible on small screens, one primary
  action per screen. Tests: matcher, counts, render at three widths. Browser: walk Files, Settings, Onboarding.

### C — Preparation experience (medium, medium)
- Scope: L-01, F-02, F-04, queue screen rows and summary, plain-language failure and skip reasons.
- Depends on A. Files: `components/knowledge/queue-preparation-view.tsx`, `preparation-progress.tsx`, message tables.
- Acceptance: no user-facing "beta owner"; each failure shows reason and next step; no invented percentages.
- Tests: message table snapshot, row state rendering for every state. Browser: scripted queue with success, failure,
  skipped, paused, reload.

### D — Chat and citations (medium, medium)
- Scope: C-02, C-03, loading and retry states, draft preservation, citation panel; fixtures for answers.
- Files: `components/chat/*`, `app/sources/*`. Acceptance: distinct states for loading, missing, no access;
  citation opens the exact passage. Tests: component tests with saved responses. Browser: fixtures only, no paid calls.

### E — Design system and polish (medium, low)
- Scope: V-01 (after owner decision), V-02, A-01, A-02, F-05, P-02, token cleanup in `globals.css`, shared components.
- Acceptance: tokens documented and used, smallest text 12 px, skip link, visible disabled style, one request per
  Check sync status click, reduced-motion respected. Tests: axe-style checks where available, request-count test.

### F — Final browser QA (low complexity, risk: findings)
- Full walkthrough on desktop, tablet and 455 px (and real 390 px if a device emulator is available), failure and
  recovery paths with the stubbed backend, production build to settle P-01 and P-03, screenshots kept locally.

## 9. Decisions needed before Checkpoint A

1. Retry for failed documents: now, or after a backend guarantee?
2. Keep the five-document limit?
3. Live reproduction method: seeded disposable database or stubbed backend?
4. Default theme: System or Light (parchment)?

## 10. Exact next action

Answer the four questions above, then approve Checkpoint A. It begins with the already-written failing tests and will
not touch retry unless question 1 says so.

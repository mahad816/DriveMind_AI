# DriveMind issue register

> Historical snapshot of 2026-11-25 at `45a3f0c`. Preparation findings were subsequently addressed by Checkpoint A (`7d8764d`); the UI was replaced by Marginalia (`70c2ee6`). This document preserves the original observations, not a current unresolved-issue list. See [integration verification](../guides/INTEGRATION_VERIFICATION.md) and the Checkpoint A/frontend-rebuild tickets for later evidence.

Audit date 2026-11-25, HEAD `45a3f0c`. Method and coverage: `product-ux-audit.md`. Roadmap: `product-ux-roadmap.md`.
Severity: P0 destructive or security, P1 essential journey broken, P2 significant reliability or usability, P3 polish.
Evidence: LIVE, TEST, CODE, INFERRED, BLOCKED. Screenshot references are local-session only (public repository, real file
names visible), described instead of stored.

## Totals

| | P0 | P1 | P2 | P3 | Total |
|---|---|---|---|---|---|
| Verified (LIVE, TEST or CODE) | 0 | 1 | 5 | 16 | 22 |
| Unverified (INFERRED) | 0 | 0 | 1 | 1 | 2 |
| **All** | 0 | 1 | 6 | 17 | 24 |

By category (all 24): functional 5, UX 5, copy 6, performance 3, accessibility 3, visual 2.
Unverified: Q-04 (impact on bulk use is inferred, the limit itself is verified) and P-03. P-01 is a measured observation,
not a confirmed defect.
No P0 finding. Security controls were not touched and not weakened.

## Functional

### Q-01 — A failed document stops the whole preparation queue — P1, functional, TEST + CODE
- Workflow: Files, select 2 to 5, Review, Prepare, confirm each document.
- Repro: `cd frontend && npx vitest run lib/knowledge/preparation-queue.failure-isolation.test.tsx` (4 red). Setup: file 1
  ready, file 2's INGEST job `failed` without recovery flag, file 3 pending.
- Actual: phase `stopped`, file 3 never starts, entry 3 stays `pending`, only exit is Close which discards the tail.
- Expected: failure recorded for file 2, file 3 offered with the usual explicit confirmation, file 1 and file 2 never
  re-submitted, final summary shows ready, failed.
- Root cause (confirmed): `preparation-queue.ts` `runCheck()` advances `current` only in the `ready` branch; the
  `failed`/`skipped` branch records the result and pauses. `preparation-queue-store.ts` `validateQueue()` rejects any
  entry before the cursor that is not `ready`, so the data model cannot represent "failed, moved on".
- Not a missing terminal transition or a polling bug. The existing test "failed on second file stops queue" asserts the
  current behaviour, so the stop was designed. Changing it is a product decision plus an edit to that test.
- Files: `frontend/lib/knowledge/preparation-queue.ts`, `preparation-queue-store.ts`, `queue-preparation-view.tsx`.
- Fix: classify failures (see audit), schema version 3 allowing `failed`/`skipped` before the cursor with their terminal
  receipt, atomic compare-and-set advance, phase `awaiting_next`. Keep the three guard tests green.
- Dependencies: owner decision on retry (Q-02). Live reproduction needs a seeded disposable database or stubbed backend.

### Q-02 — Failed and skipped documents have no retry path — P2, functional, LIVE + CODE
- Repro: Files, look at a skipped file (one exists): checkbox disabled, tooltip "…Ask the beta owner to review it."
- Expected: a stated next step, and a safe retry where the backend allows it.
- Root cause: `preparationEligibility` rejects `failed` and `skipped` ("never blind rebuild").
- Fix: Separate decision. First show why it failed or was skipped in plain words; retry only after the backend guarantee
  is confirmed. Test: eligibility cases plus a queue test for retry once defined.

### Q-03 — Closing a stopped queue silently discards the unstarted files — P2, functional, TEST
- Evidence: existing test "known failed queue can be explicitly closed without retrying the unstarted tail".
- Actual: unstarted files vanish from the plan; the user must re-select and re-review. Expected: they stay queued or the
  user is told exactly what was dropped. Fix lands with Q-01. Test: summary lists failed and not-started separately.

### F-01 — Selection controls disable for a few seconds after Review then Back — P2, functional, LIVE + CODE
- Repro: select two files, Review, Back to files. All checkboxes and "Review 2 documents" are disabled with
  "Check file inventory and existing preparation before making another selection" for about 5 s, then recover.
- Root cause (CODE): `selectionDisabled` in `knowledge-library.tsx` includes `filesState.isLoading`, and returning
  triggers a full inventory refetch. Clicks during the window are dropped without feedback.
- Fix: keep the existing list visible and selection enabled during a background refresh (stale-while-revalidate), disable
  only while the gate is genuinely unknown. Test: selection stays enabled during refetch.

### C-01 — Every New Chat click persists an empty conversation — P2, functional, LIVE
- Repro: click New Chat twice. Network: `POST /api/v1/conversations` 201 each time, then the sidebar shows two "New chat".
  The audit created two such rows in `drivemind_local`.
- Actual: empty conversations accumulate; clicking from `/files` also navigates. Expected: reuse an existing empty
  conversation, or create on first message. Files: `server-chat-interface.tsx` and the conversation controller.
  Test: two New Chat clicks create at most one empty conversation.

## UX

### Q-04 — Five documents per batch against a 516-file Drive — P2, UX, LIVE (limit), INFERRED (impact)
- The limit is stated on onboarding and in the selection note ("Five-document limit reached"), and every document needs
  its own confirmation. For a large Drive this is a long manual loop. Not a defect if it is a deliberate beta safety cap.
  Owner decision needed (audit question 2). No change proposed until answered.

### F-03 — Search ignores underscores as word breaks and is silently tab-scoped — P3, UX, LIVE
- A two-word query returned 0 results where the same words joined by `_` matched three files. Search is also limited to
  the selected tab with no hint, and tab counts do not reflect it. Fix: treat `_`, `-` and `.` as spaces when matching;
  show "Searching in: All" or search across all tabs. Test: matcher cases.

### F-06 — Skipped and failed files are visible only under All — P3, UX, LIVE
- Tab counts 514 + 1 + 0 do not sum to 516. Fix: a "Needs attention" tab or count. Test: tab counts sum to the total.

### F-07 — Location and Modified are hidden below tablet width — P3, UX, LIVE
- At 698 and 455 px the table shows name and status only, so folder context is available only in the preview drawer.
  Fix: show the folder under the name on small screens. Test: viewport render check.

### S-01 — Settings emphasis and duplication — P3, UX, LIVE
- "Reconnect Google Drive" is the primary-styled button while the connection is healthy; "Refresh Drive status" looks
  like plain text while "Manage Google access" is underlined; "Manage files" repeats the sidebar Files link.
  Fix: reconnect becomes secondary unless the connection is unhealthy; one link style; drop or keep with a reason.

## Copy

### L-01 — "Ask the beta owner" appears in 10 user-facing messages — P2, copy, CODE (+ LIVE once)
- Examples: "Previous preparation failed. Ask the beta owner to review the job before trying again." / "…Ask the beta owner for
  help." A user cannot act on it and the role is internal. Expected: say what happened and the next step.
- Suggested wording: "This document could not be prepared. Nothing was changed in your Drive. Try again later, or
  contact support with the time shown." Skipped: "This document had no readable text, so it was skipped. You can still
  open it in Google Drive."
- Files: `single-file-preparation.ts`, `preparation-queue.ts`, `files-table.tsx` and related components. Test: no
  user-facing string contains "beta owner"; snapshot of the message table.

### F-02 — Empty Preparing tab says "No files match your search or filter" — P3, copy, LIVE
- Suggested: "Nothing is being prepared right now." Search active: "No files match 'text' in this tab."

### F-04 — "Selection does not prepare this document." — P3, copy, LIVE + CODE (`files-table.tsx:39`)
- Read by assistive technology on every enabled checkbox; reads as a negative. Suggested: "Selecting does not start
  preparation. You review first."

### L-02 — Onboarding and Prepare empty states — P3, copy, LIVE
- Onboarding steps 3 and 4 show no state although files are discovered. `/prepare` with no queue is a bare message with
  three buttons. Suggested: mark discovery complete; on `/prepare` say "No documents are being prepared" with one primary
  action "Choose documents".

### C-02 — "Conversation unavailable or loading." — P3, copy, LIVE + CODE (`server-chat-interface.tsx:231`)
- One message for loading, not found and not allowed, with a visible composer. Suggested: separate "Loading…" from
  "This conversation could not be found" with a New chat button.

### C-03 — Source page error wording and duplicate buttons — P3, copy, LIVE
- "Source chunk not found" uses an internal term and two buttons both say "Open chat". Suggested: "This source is no
  longer available" and a single "Back to chat".

## Performance

### P-01 — Idle status polling — P3, performance, LIVE (measured), not a confirmed defect
- About 14 `/index/status` requests per minute plus a session check every 30 s while idle; each about 20 ms server-side.
  Cheap for one user. Worth backing off when no job is active and pausing when the tab is hidden (hidden-tab behaviour
  was not measured). Re-measure on a production build and with several tabs before changing.

### P-02 — Check sync status sends two identical requests per click — P3, performance, LIVE
- Two `GET /index/status` per click. Likely one status refresh plus one controller check. Fix: join them (the code already
  has a `JoinedCheck` helper). Test: one request per click.

### P-03 — Many GET pairs show 503 then 200 in the network log — P3, performance, INFERRED
- Direct GETs: 0 of 18 non-200. The client has no 503 retry and `reactStrictMode` is on, so these are most likely
  aborted dev-mode requests. **Unverified.** Verify with a production build; if real, escalate to P2 because it doubles
  load and could hide backend errors.

## Accessibility

### A-01 — No skip link — P3, accessibility, LIVE
- 12 Tab presses to reach the first page control. Fix: skip-to-content link. Test: first Tab stop is the skip link.

### A-02 — 10 to 11 px text for counts and timestamps — P3, accessibility, LIVE
- Contrast is fine (5.67:1 measured), size is small. Fix: minimum 12 px in the type scale.

### F-05 — Checkbox size — P3, accessibility, LIVE (downgraded)
- Checkbox 15 px, label target 36 by 44 px. This meets the 24 px minimum; width is under the 44 px recommendation.
  Earlier "too small" claim was overstated. Optional: widen the label target to 44 px.

## Visual

### V-01 — Parchment identity appears only in the Light theme — P3, visual, LIVE
- Default is System; a dark OS gets the charcoal theme. Decision for the owner. If the identity matters, default to
  Light or make the dark theme carry the same warmth (it already does: warm charcoal, cream accent).

### V-02 — Disabled checkboxes are nearly invisible — P3, visual, LIVE
- In both themes the disabled box on ready and skipped rows is hard to see, so the row looks like it has no control.
  Fix: a visible disabled style plus the reason as visible text for the status, not only a tooltip.

## Not an issue (checked)

Search covers all 516 files, not only the visible page. Preview drawer focus return and Escape work. Mobile menu focus
return works. No horizontal overflow at 1309, 698 and 455 px. Theme switching persists. No technical identifiers or job
IDs appear in the primary interface. `prefers-reduced-motion` rule exists.

## Blocked areas (unverified, may hide defects)

Preparation run (all failure paths live), cancel, retry, reload during preparation, unknown outcome, session expiry,
disconnected Drive, Sync Drive, reconnect, sign-in and sign-out, chat answers, Stop, Retry, long responses, Markdown,
citations and source navigation, conversation rename and delete, exact 390 px width, draft preservation across in-app
navigation, screen-reader behaviour.

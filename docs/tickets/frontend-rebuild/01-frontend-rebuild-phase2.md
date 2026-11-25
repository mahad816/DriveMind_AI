# 01: Rebuilt frontend against the synthetic backend

**Spec:** docs/specs/frontend-rebuild.md
**What to build:** the complete redesigned frontend (shell, chat and evidence, library and preparation, palette,
settings, setup), connected to the kept `lib` controllers and exercised in a browser against the synthetic backend.
Obsolete UI code removed.
**Blocked by:** None (can start immediately)
**Status:** ready-for-agent
**Progress:** resolved
**Risk:** high (session boundary behaviour on transient failure, D2)

Scope excludes: backend changes, real-backend integration, deployment, Docker changes. Local commit: authorized by the
Owner on 2026-11-26, conditional on an APPROVE closure review with no unresolved P0-P2 (met). Never pushed.

- [x] Every blueprint section 7 control works in the browser against the stub (Playwright journeys). Note: the journeys exercise the main controls and states; not every individual control has its own journey (first review list in Comments).
- [x] Tab-switch test: no remount, draft/selection/panel kept, at most one session request on return.
- [x] Transient failure keeps content read-only; 401 hides it.
- [x] Existing lib tests unchanged and passing; new tests for new state modules.
- [x] lint, tsc, build, vitest, Playwright, axe pass; screenshots reviewed at five widths in both themes.
- [x] Obsolete components, hooks and dependencies removed.

## Comments

### 2026-11-25: implementation, review and fixes (uncommitted)

- Review: one fresh `drivemind-reviewer`, verdict **BLOCK** (read-only; it judged implementer-produced output and ran nothing).
  - P2 fixed: unused `class-variance-authority`, `tw-animate-css`, `shadcn` removed; tests added for `lib/state/browser-memory.ts` (owner-scoped drafts, return-path validation, connect intent) and `lib/state/selection.ts` (five-document cap); browser journeys moved to `frontend/e2e/journeys/` with `npm run e2e:*` scripts and `frontend/e2e/README.md`; degraded and offline banner copy no longer promises automatic sending.
  - P3 fixed: return path cleared on sign-out; file panel cannot add to the selection while a batch runs; banner "Reconnect Google Drive" disabled while the server is unreachable.
  - P3 open: 429 keeps the question pending until "Try again" (no discard); tray says "Stop tracking" (blueprint says "End tracking"); drafts cut at 8000 characters; a sign-out in another tab keeps this tab's owner-keyed drafts; the source page highlights the snippet from whichever loaded turn cited the chunk.
- Tab-switch journey strengthened (sets `document.hidden`; asserts at most one session check per return, none on leaving, draft, selection and open panel kept, composer element not remounted): passed.
- Coverage gap: the deleted `components/providers/session-browser-boundary.test.tsx` held 54 mounted tests of the old UI. Controller-level guarantees remain in the kept `lib/conversations` tests; duplicate send and citation Drive links are covered by the new `send-and-cite` journey; the other UI-level cases (for example expiry mid-stream, late creation versus a newer conversation) are not rebuilt.
- Final verification [local]: vitest 34 files, 665 passed; tsc, lint, build exit 0; `git diff --check` clean; journeys 38 passed, 1 intermittent failure (focus return after Escape, 6 of 6 reruns passed); responsive sweep no overflow; axe 0 violations.
- Not re-reviewed after the fixes. No commit authorized; nothing pushed.

### 2026-11-26: Phase 2 closure (Owner brief: review the fixes, flaky test, removed-test coverage, demo, Drive wording)

- Flaky Escape/focus test: two causes. (1) The file panel's open state followed the URL, so after Escape it stayed open until the router finished (slow on a cold dev server); it now closes immediately and remembers the dismissal per file. (2) The test used fixed delays and compared `innerText` with `textContent`. All journeys now wait on state (elements, URLs, responses, focus); no fixed delays remain (`waitForLoadState("networkidle")`, a no-op after load, was also removed). Removing the delays exposed a real axe violation (prohibited `aria-label` on the conversation-history `div`), fixed.
- Removed `components/providers/session-browser-boundary.test.tsx` (54 mounted tests of the deleted UI), by group:
  - Covered by the kept `lib/conversations/server-controller.test.tsx` (47 tests): canonical create id, late creation vs newer selection, X completing while Y is selected, lost acknowledgement with one frozen request, explicit RUNNING to INTERRUPTED, stop leaves an unknown outcome, transient reload keeps content, 202 replay, rename 409, delete during pending, stale 404s, owner fence, no legacy storage, pagination order.
  - Covered by `application-session-provider.test.tsx`: logout and another owner, 401 invalidation (including while degraded), owner change remount.
  - Restored as focused tests: `components/chat/chat-session-expiry.test.tsx` (real session boundary, workspace and chat screen; session expiry during an active question in non-streaming and streaming mode hides private output at once, a late answer cannot restore it, re-authentication reloads from the server with no replay; normal mode keeps no question or answer text in browser storage). Browser journeys: duplicate Enter and click send one request; citation Drive links use Google's id; an old `?ask=` link sends nothing.
  - Obsolete (mechanisms that no longer exist): creation-draft handoff across route remounts, sidebar creation-recovery receipts, client-side loaded-title search, collapsed-rail recovery affordances, "normal sidebar has one creation action".
  - Not rebuilt (lower risk, noted): readiness failure vs zero-ready messaging and retry, a delayed old-owner inventory (structurally prevented by the owner-keyed remount, no direct test), mobile drawer focus return after Escape.
  - Mutation check: treating a 401 as a transient failure made the new test run fail (the provider entered a re-check loop and the worker crashed), so the failure is detected, but as a crash rather than a clean assertion.
- Public demo preserved: the earlier "demo retired" screen is replaced by `components/demo/demo-root.tsx` (no sign-in; browser-local conversations through the kept `lib/conversations` demo storage; `POST /chat` with the kept history window; sample questions and readiness from `/index/status`; read-only sample-documents page; passage page). Backend demo code is unchanged. Differences from the old demo: no conversation list on phones (header "Chat" starts a new chat), no snippet highlight on the passage page, Drive and file-details links hidden in evidence notes (as before).
- Drive and data wording checked against the backend: logout revokes only the DriveMind session (`/auth/session/logout`), the stored Google token stays; `connected` means a stored Google token exists (`DriveSyncService.is_connected`) and the app never deletes it, so revoking access in the Google Account is not reflected until a Drive call fails; chat reads only DriveMind's own copy; scope is `drive.readonly`. Changed copy: the disconnect hint (Settings may still show Connected; prepared documents cannot be removed in the app yet), "Access has ended" to "Not connected", banner and tray "isn't connected", About (lists the stored data including the Google authorization), "reads the contents only of documents you choose" (file names of all files are listed), quota notice "kept while this page stays open".
- Verification [local]: vitest 35 files, 668 passed; tsc, lint, build exit 0; `git diff --check` clean; `npm run e2e:journeys` 41 passed, 0 failed in each of 3 runs (run 1 on a cold dev server); `npm run e2e:responsive` no overflow; `npm run e2e:demo` 11 passed. Original repository: no file changed since this session started, HEAD `7d8764d`.

### 2026-11-26: closure review

- One fresh `drivemind-reviewer` on Opus (read-only, ran nothing; it judged implementer-produced output): **APPROVE**, no confirmed defects, no P0-P2.
- P3 recorded, not fixed (the code was not changed after the review):
  - `components/library/file-panel.tsx`: dismissal is remembered per file id; if the URL update after Escape never lands, picking the same file again stays closed until the URL changes.
  - Sign-in screen "Nothing is lost." is broad for the no-owner unavailable state (only tab drafts survive).
  - Unsent drafts stay in this tab's `sessionStorage` after a 401 expiry (owner-keyed, cleared on explicit sign-out); intended so the person can continue, to be confirmed as a decision.
  - The session-expiry mutation shows as a worker crash rather than an assertion failure.
  - Still open from before: 429 has no discard, "Stop tracking" wording, 8000-character draft cut, drafts kept after a sign-out in another tab.
- Unverified by the reviewer: journey and stub sources, the name-by-name mapping of the 54 removed tests (the implementer listed the names from `git show 7d8764d:...session-browser-boundary.test.tsx` during the session), screenshots.


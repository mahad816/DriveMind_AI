# Spec: DriveMind frontend rebuild (Phase 2)

**Source of truth:** `docs/product-redesign/DRIVEMIND_REDESIGN_BLUEPRINT.md` (Phase 1 blueprint). This spec does not repeat
it; it records the scope the Owner authorized for Phase 2 and the decisions taken.

## Goal

Replace the whole user interface (`frontend/app`, `frontend/components`, UI-only `frontend/lib` modules) with one coherent
product built to the blueprint: session boundary, workspace shell, chat with an evidence margin, library, preparation
tray, command palette, settings and setup checklist. Verified against a synthetic backend only.

## Success criteria

- Every control in blueprint section 7 exists and does what the table says; nothing else ships.
- The journeys in blueprint section 6 pass against the synthetic backend (`frontend/e2e/stub`), including failures.
- No conversation is created without a sent question; nothing re-sends an unknown outcome automatically.
- Tab switching does not remount the workspace, clear drafts, selection, filters or open panels (blueprint 14.3).
- A transient session-check failure keeps already-authorized content visible, read-only (decision D2, authorized by
  the Owner in the Phase 2 brief). A 401, logout or account change hides private content immediately.
- Existing `lib/api`, `lib/conversations`, `lib/knowledge` tests pass unchanged.
- Light and Dark themes, widths 1440/1100/820/390/320, keyboard-only use, axe with no serious or critical issue.
- `npm test`, `npm run lint`, `npx tsc --noEmit`, `npm run build` and the Playwright journeys pass.

## Decisions taken in Phase 2

- D1: base is Checkpoint A commit `7d8764d` (already committed). D2: approved by the brief. D3: in-house resources, no
  query library. D4: five-document limit kept. D5: no retry of failed/skipped documents. D6: no content search.
  D7: Light default. D8: Newsreader + Atkinson Hyperlegible Next. **D9: demo mode retired from the new UI**
  (backend demo untouched); Owner to confirm. D10: disconnect wording is a draft for Owner review. D11: both stream modes
  supported, default unchanged (off).
- The 429 quota refusal gets its own conversation error category (`rate_limited`), an additive change.

## Edge and failure behaviour

Blueprint section 8 (state and error matrix) applies unchanged.

## Security, privacy, performance

- Server authorization is unchanged. Owner-keyed caches; owner change drops them. Drafts live in `sessionStorage`
  keyed by owner and are wiped on sign-out.
- Hidden tab: no polling. Visible idle: at most a session check per minute.
- Synthetic data only; no Google, OpenAI, Railway, ports 3000/8000, or real Drive content.

## Test strategy

Vitest for new state modules and components; Playwright journeys against the stub backend on port 8100 with the app
on 3100; `@axe-core/playwright` in both themes; screenshots at five widths for review.

## Out of scope

Real-backend integration (Phase 3), deployment, push or merge.

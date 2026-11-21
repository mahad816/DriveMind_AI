# 08: Assess CSRF on `POST /chat`, and close it if the risk is real

**Spec:** docs/specs/m0-sec-security-hardening.md
**What to build:** A written assessment of whether a forged cross-site request can make `POST /chat` spend the Owner's credits, from verified layout facts and a local test, and, unless the assessment shows the risk can be excluded, the same `Origin` and CSRF-token requirement every other mutation has (Owner decision D4-4: assess, do not assume `SameSite=Lax` is enough). Demo mode stays anonymous.
**Blocked by:** None (can start immediately). Soft: do it after 06, both touch the `/chat` route.
**Status:** ready-for-agent
**Progress:** open

## Scope

- Assessment, recorded in this ticket's `## Findings`, covering: cookie attributes and the `__Host-` prefix; how the browser reaches the backend (same-origin proxy rewrite); absence of CORS middleware; who calls `/chat` in normal mode (the audit's search found only the demo interface; re-verify); what a forged request could do (spend credits, write query history) and could not do (read the response cross-origin); and what the installed framework version accepts as a forged "simple" cross-site request (for example a form-encoded or plain-text body), shown by a local test, not by memory.
- Layout facts that cannot be verified while nothing is deployed (a custom domain, sibling subdomains, public-suffix status of the frontend host) are written as deployment-only checks for M9. They are not assumed safe.
- Decision rule, stated in the assessment: fix if a forged simple request is accepted by the server, or if the deployed layout cannot be shown to exclude a same-site attacker. If neither holds, record why and keep the test that proves the refusal.
- If fixed: in normal mode `POST /chat` requires exactly one `Origin` equal to the configured frontend origin and a valid session-bound CSRF token (the existing mutation dependency). In demo mode it stays anonymous, with the demo limiter as before.

## Out of scope

Changing cookies, adding CORS, changing other routes, frontend work (no normal-mode caller exists; if the re-verification finds one, stop and report), Origin or CSRF on GET routes.

## Inspect

`docs/tickets/m0-system-audit/04-auth-and-access-control-audit.md` (section 4, result 17, Owner decision 4); `backend/app/api/session_dependencies.py` (`require_session_mutation`); `backend/app/api/dependencies.py`; `backend/app/api/chat.py`; `backend/app/main.py`; `frontend/next.config.ts`; `frontend/lib/api/chat.ts` and its callers; `tests/security/test_route_authentication_inventory.py`; `tests/test_public_safety.py`.

## Deliverables

`## Findings` with the assessment; the fix and tests if required; `## Comments` with the M9 layout checks and documentation items for ticket 09.

## Needs

Disposable PostgreSQL for the session-backed tests. No network, no hosted check.

- [ ] The assessment lists each fact with a label (Verified, Unverified, Defect) and an evidence type, and separates "a forged request can do" from "cannot do".
- [ ] A deterministic test records what the server does with a forged simple cross-site request (no `Origin`, wrong `Origin`, no token) in normal mode, before and after any fix.
- [ ] If the fix is made: missing, duplicate or wrong `Origin`, and missing or wrong token, are refused (the same statuses the other mutations return) before any provider call; a valid request still answers.
- [ ] Demo mode: anonymous `POST /chat` is unchanged, and the demo limiter and body-limit tests pass unmodified.
- [ ] The route inventory test is updated only for `/chat`'s dependency set, and passes.
- [ ] The frontend suite, lint and build pass unchanged (no frontend change expected).
- [ ] If no fix is made, the ticket says exactly why the risk is excluded and which M9 check keeps it excluded.

## Comments

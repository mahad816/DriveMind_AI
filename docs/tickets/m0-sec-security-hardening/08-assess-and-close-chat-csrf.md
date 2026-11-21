# 08: Assess CSRF on `POST /chat`, and close it if the risk is real

**Spec:** docs/specs/m0-sec-security-hardening.md
**What to build:** A written assessment of whether a forged cross-site request can make `POST /chat` spend the Owner's credits, from verified layout facts and a local test, and, unless the assessment shows the risk can be excluded, the same `Origin` and CSRF-token requirement every other mutation has (Owner decision D4-4: assess, do not assume `SameSite=Lax` is enough). Demo mode stays anonymous.
**Blocked by:** None (can start immediately). Soft: do it after 06, both touch the `/chat` route.
**Status:** ready-for-agent
**Progress:** implemented and committed locally (2026-11-22); reviews recorded in Comments; not pushed

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

`## Findings` with the assessment; the fix and tests if required; `## Findings

Label: Verified (V), Unverified (U), Defect (D). Evidence: code (C), local test (T), local run (R).

**Assessment: the risk could not be excluded, so `POST /chat` now has the same Origin and CSRF requirement as every other mutation.** Decision rule (this ticket): fix if a forged simple request is accepted, or if the deployed layout cannot be shown to exclude a same-site attacker. The first limb did not hold; the second did.

| # | Fact | Label | Evidence |
|---|------|-------|----------|
| 1 | Session cookie: `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`, no `Domain`; on HTTPS it is named `__Host-drivemind-session` (host-only) | V | C `session_helpers.py`; T `test_the_session_cookie_is_host_only_secure_and_lax...` |
| 2 | The browser reaches the backend only through the same-origin Next rewrite `/api/v1/*` | V | C `frontend/next.config.ts` |
| 3 | The backend has no CORS middleware; an `OPTIONS` preflight and a normal response carry no `Access-Control-*` header | V | C `main.py`; T two tests in `test_chat_csrf.py` |
| 4 | In normal mode nothing calls `/chat`: `askQuestion` is imported only by `DemoChatInterface`, rendered only when `DEMO_MODE`; `ServerChatInterface` uses `/conversations` | V | C grep of `frontend/`, re-verified for this ticket |
| 5 | Before the fix, `POST /chat` with a valid cookie and JSON body, with no Origin, a wrong Origin or no token, was accepted and reached the provider (14 of 21 new tests failed) | D (now fixed) | T before/after run |
| 6 | Forged simple bodies (`text/plain`, `text/plain;charset=UTF-8`, `application/x-www-form-urlencoded`) with the cookie were refused by the installed framework (FastAPI 0.139 strict content type, 422) and never reached the provider or wrote history, before and after the fix. After the fix the status is 403 | V | T `test_a_forged_simple_request_...` |
| 7 | Whether a custom domain, sibling subdomains or the frontend host's public-suffix status could give an attacker a same-site origin | U | nothing is deployed; see M9 checks in Comments |

**A forged request could do** (if it reached the server with the cookie): spend the Owner's model credits (bounded by the ticket 06 quota: 20/hour, 50/day, 1 concurrent) and write `QueryHistory` rows. **It could not do:** read the answer cross-origin (no CORS), change credentials or sessions, read Drive content, or pass a JSON or custom-header request from a cross-origin browser page (the preflight is never approved).

**Why `SameSite=Lax` was not accepted as enough:** it does not apply to a same-site attacker (a sibling subdomain or another app on the same registrable domain), a browser that does not enforce it, or a non-browser client holding a stolen cookie; and item 7 is unverifiable today. The check costs one existing dependency.

**Fix:** new dependency `require_chat_user` (`backend/app/api/dependencies.py`) on `POST /chat`. It depends on `require_resource_user` (so no or invalid session stays 401), then in normal mode calls the existing `require_session_mutation` (exactly one `Origin` equal to `FRONTEND_URL`, exactly one session-bound `X-CSRF-Token`, the allow-list; 403). Demo mode returns straight after `require_resource_user`: anonymous, same limiter, same body limit. No cookie, CORS, frontend or other-route change. Both checks run as dependencies, before admission, the provider call and the history write.

**Tests:** `tests/security/test_chat_csrf.py` (22): legitimate request answers; missing, wrong (six shapes), duplicate Origin; missing, invalid, another session's token; three forged simple shapes; JSON with only the cookie; attacker Origin with cookie; cookie attributes; no CORS. Each refusal asserts no provider call and no ledger row. Route inventory: only `/chat`'s dependency set changed (new `CHAT` set). Existing tests that post to `/chat` in normal mode now send Origin and token (`authenticate` helper, the parallel-users test, the allow-list call table) or override `require_chat_user`; no assertion was removed or loosened.

## Comments` with the M9 layout checks and documentation items for ticket 09.

## Needs

Disposable PostgreSQL for the session-backed tests. No network, no hosted check.

- [x] The assessment lists each fact with a label (Verified, Unverified, Defect) and an evidence type, and separates "a forged request can do" from "cannot do".
- [x] A deterministic test records what the server does with a forged simple cross-site request (no `Origin`, wrong `Origin`, no token) in normal mode, before and after any fix.
- [x] If the fix is made: missing, duplicate or wrong `Origin`, and missing or wrong token, are refused (the same statuses the other mutations return) before any provider call; a valid request still answers.
- [x] Demo mode: anonymous `POST /chat` is unchanged, and the demo limiter and body-limit tests pass unmodified.
- [x] The route inventory test is updated only for `/chat`'s dependency set, and passes.
- [x] The frontend suite, lint and build pass unchanged (no frontend change expected).
- [x] If no fix is made, the ticket says exactly why the risk is excluded and which M9 check keeps it excluded.

## Comments

**Reviews (2026-11-22).** Two independent read-only reviews. Standards and maintainability: no blocking findings; fixed three non-blocking points (exact 403 in the forged-simple test, unused helper parameter removed, wrong-Origin cases derived from `frontend_url`). Spec, correctness and security: no blocking findings; confirmed ordering (nothing spent or written before the check), demo mode unchanged, no bypass via duplicate or empty Origin, `/chat/`, HEAD or OPTIONS, and no normal-mode frontend caller. Accepted as is: a body-limit 413 can precede the 401 or 403 (spec-approved, spends nothing); two session lookups per request (same pattern as `require_index_user`).

**M9 deployment-only checks (not assumed safe).** (1) The frontend host is on the public suffix list or is a custom domain with no untrusted sibling subdomains or apps; (2) `FRONTEND_URL` equals the exact public origin and the cookie is `__Host-` prefixed in the deployed response; (3) the proxy rewrite is the only path to the backend and adds no CORS headers; (4) no cross-origin frontend or normal-mode caller of `/chat` has been added.

**For ticket 09.** `docs/KNOWN_ISSUES.md` line 77 and `docs/specs/drivemind-v1-product-definition.md` line 355 still say `/chat` needs no Origin or CSRF token; both are now false (ticket 09 already removes the former). The audit's wording (ticket 04 of the audit) is point-in-time and stays. No registry entry was added: the defect is fixed in this ticket, with a test. A client that calls `/chat` in normal mode must now send `Origin` and `X-CSRF-Token`; none exists.

**Verification (2026-11-22).** Disposable PostgreSQL and Qdrant, no `OPENAI_API_KEY`. `tests/security`: 885 passed, 377 skipped (Qdrant tests skipped in that run); the Qdrant-backed `/chat` files rerun with Qdrant: 194 passed and 1 failed (`test_parallel_authenticated_users_have_independent_context` built its own headers without Origin or token; fixed), then that file 84 passed; plus `test_public_safety`, `test_chat_api`, `test_provider_failure_paths`, `test_tool_agent_api`, `test_demo_api_guard`, `test_demo_corpus`, `test_sources_api` passing. ruff check and format clean, mypy `app` clean, basedpyright 0 errors on `app` and the new test file. An earlier full run hung on a test broken by this change (`test_tool_agent_api` overriding the old dependency) and was killed; it was not a product hang.

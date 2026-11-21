# 09: Security test integrity, documentation, milestone verification and the M9 gate

**Spec:** docs/specs/m0-sec-security-hardening.md
**What to build:** The security tests and documents say what the code now does, the deferred items sit in their later milestones, and one full verification run proves M0-SEC is complete.
**Blocked by:** 01, 02, 03, 04, 05, 06, 07, 08.
**Status:** ready-for-agent
**Progress:** open

## Scope

- Fix `test_existing_application_routes_do_not_use_session_dependencies` (it checks nothing under the pinned FastAPI and is named for the opposite of reality): rewrite it to assert something real or delete it where the route inventory already covers the claim.
- Correct the docstrings the audit proved wrong: the session dependency module, the Google session auth route module, the application session service, and the `RagService` class and `ask` docstrings (audit A1.8). No behavior change.
- Registry (`docs/KNOWN_ISSUES.md`): KI-031 and KI-032 are in Fixed (tickets 02 and 07); remove the "found by the audit, not yet registered" bullets for Owner-mode limits and `/chat` CSRF; keep the claim-check, CI-deselect items.
- Documents: `AGENTS.md` ("Known Important Constraints": remove the latent-fallback sentence, add the allow-list and session invalidation, the persistent paid-question quota (20/hour, 50/day, 1 concurrent, provisional) and the new table; "Latest recorded verification"); `backend/app/security/README.md` status block; the v1 spec ledger and milestone table (add the M0-SEC row; add the M9 gate below); `docs/ARCHITECTURE.md` security paragraph; `docs/guides/GOOGLE_OAUTH.md` (allow-list is the authorization model, test users are an outer control); an addendum line in `docs/audits/m0-system-audit.md` section 4 pointing to this milestone (the report stays a historical record).
- The M9 gate, recorded in the v1 spec's M9 row and in the spec's Further Notes: before any redeploy with sign-in on, (1) limit values recalibrated from M1 data, (2) the deployment-only list verified (Google consent screen and test users, flags, encryption keys, `FRONTEND_URL` and cookie settings matching the real hosts, layout facts from ticket 08, proxy and edge limits), (3) practical provider spending safeguards verified, (4) deferred logging items done in M9; and, for item (3), the Owner's practical spending safeguards in the provider dashboard (a project usage budget and usage alerts), described as safeguards and never as guaranteed hard caps. Also record: the allow-list deferrals of ticket 03 (running turns, queued indexing jobs with the worker check assigned to M6 and re-verified at the M9 gate, stale stored e-mail) as deferrals, never as guarantees, and add the M6 worker-check item to the v1 spec's M6 row; the future requirement of per-user quota management for beta testers, to be started only after ownership isolation is verified (M7), and the multi-replica checklist from the spec (section C).
- Quota documentation from tickets 05 and 06 (open items assigned here): add `PAID_QUESTION_HOUR_LIMIT`, `_DAY_LIMIT`, `_CONCURRENT_LIMIT`, `_LEASE_SECONDS`, `_RETENTION_HOURS`, `CONVERSATION_EXECUTION_SECONDS`, `CONVERSATION_GENERATION_TIMEOUT` and `CHAT_EXECUTION_SECONDS` to `.env.example` and the operating guide with the lease rule (lease at least the longest bound plus 60 s); document the 429 and 503 contract, the order of checks, the body caps (512 KiB `/chat`, 64 KiB turns and stream) and the 4000-character `/chat` question cap. Record in the v1 spec's M8 row the frontend items (Owner-mode 429 wording, stream status and SSE-error handling) and in the M9 row the items below.
- Add to the M9 gate list (item 2, deployment-only verification): migration `20261121_1200` applied on the hosted database; the quota settings present and the application starting with the lease validator accepting them; the database connection pool size checked against admit, finish and release taking a connection beside each request's own; the edge or proxy read timeout for slow request bodies.
- Run the full verification once and record it.

## Out of scope

Any new fix. Deferred items (log text, `/docs`, empty-corpus exit). Deployment. Changes to ADRs.

## Inspect

All earlier tickets' `## Comments`; `docs/specs/m0-sec-security-hardening.md` ("What must be true before M0-SEC is complete"); `AGENTS.md`; `CODING_STANDARDS.md`; `docs/GIT_WORKFLOW.md`.

## Deliverables

Test and docstring fixes; documentation corrections; `## Findings` here with the verification record (counts, durations, environment, commit); diff summary for the Owner's approval. Do not commit or push without it.

## Needs

Local Docker for the disposable PostgreSQL and Qdrant containers (about 24 minutes for the full backend suite). `OPENAI_API_KEY` unexported. No paid API, no Railway.

- [ ] The vacuous test no longer claims what it does not check.
- [ ] The four named docstrings match the code; `git diff` of those files shows comments and docstrings only.
- [ ] Registry and documents match the final behavior; no document still calls KI-031 latent-open or the allow-list and limits missing.
- [ ] The M9 gate is written in both places and lists the four items; the M6 worker-authorization item and the ticket 03 deferrals are recorded in the v1 spec, `AGENTS.md` and the security README, worded as deferrals.
- [ ] Backend full container suite run once in the qualified environment: all pass; counts, duration and environment recorded. Container-free subset, `ruff check`, `ruff format --check`, `mypy app` pass; `basedpyright` clean on `app` and no more than the 48 baseline errors in `tests/`; frontend `npm test`, `npm run lint`, `npm run build` pass.
- [ ] The quota settings are in `.env.example` and the guide; the M8 and M9 rows of the v1 spec carry the items listed above; the spec's "Added after ticket 06" rows match them.
- [ ] Every item of the spec's completion list (1 to 8) is ticked with a pointer to its test or document.
- [ ] `git diff` scope: only files named in tickets 01 to 08 (and this one), exactly one migration (ticket 05), no frontend file unless ticket 08 proved it necessary; a scan of the diff for keys, e-mail addresses, connection strings, UUIDs and hosted hostnames finds nothing.

## Comments

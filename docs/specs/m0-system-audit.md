Status: ready-for-agent

# M0: System Audit and Engineering Baseline

Approved by the Owner, 2026-11-21 (ready for ticket generation; this does not authorize implementation beyond M0's own boundaries, Railway changes or deployment). Refines the provisional M0 row of `docs/specs/drivemind-v1-product-definition.md` ("the v1 spec"). Terms follow `GLOSSARY.md`; decisions follow `docs/adr/0001-single-answering-path.md` and `docs/adr/0002-public-demo-isolation.md`. Labels (Verified, Defect, Unverified, Future) and evidence types have the meaning given in the v1 spec, "How to read this spec". This repository is public: no secrets, hosted identifiers or private Drive content may appear here or in any M0 output.

## Problem Statement

Every later milestone depends on facts about the current system that are unverified or contradicted by the project's own documentation:

- Which answering path an Owner actually reaches. Three paths exist, the code defaults select the legacy linear path, and the hosted configuration is unknown.
- Whether ownership holds everywhere. A pre-spec search found six places that fall back to "the first stored Google credential" when no Owner is given. The v1 spec and `AGENTS.md` name four of them. Whether any of the six can be reached is unknown.
- What Preparation, File states, conversation deletion and privacy controls really do, as opposed to what the documentation says.
- What Railway currently runs: commit, flags, migration revision, backups.
- Which tests and quality checks currently pass on HEAD. No continuous integration exists.

Planning M1 to M10 on these gaps risks hardening the wrong answering path, making privacy claims that are not true, or leaving a security weakness in place for months.

## Solution

A focused, mostly read-only audit that turns each open question into a labelled finding with checkable evidence, plus a small engineering baseline that makes later changes safe:

1. A short audit report, `docs/audits/m0-system-audit.md`, written during execution from actual findings only.
2. Deterministic regression tests for confirmed defects, where such a test is possible.
3. A fresh, recorded local test baseline on the current HEAD.
4. A minimal, fast, free CI workflow, verified locally. Hosted verification waits until the Owner authorizes pushing.
5. Corrections to documentation that the audit proves wrong.
6. A proposed M0-SEC security follow-up and an evidence-based revision of the M1 to M10 order.

M0 changes no application behavior.

## User Stories (engineering outcomes)

1. As the Owner, I know which answering path production Owners reach, under the flags actually set on Railway, so evaluation and hardening target the right path.
2. As the Owner, I know whether any request, background job or startup task can act on another Owner's credential or data, classified by real risk, so security work is ordered by evidence.
3. As the Owner, I am told immediately if a vulnerability reachable through a live request is found, before unrelated audit work continues.
4. As the Owner, I know which Preparation capabilities and File states work today and which spec requirements are partial or missing, so M6 builds only what is missing.
5. As the Owner, I know what DriveMind stores about conversations and Files, what each existing delete action removes, and what remains, so no deletion or privacy claim is made before it is true.
6. As the Owner, I know what Railway currently runs (commit, flags, models, migration revision, backups), or which of these could not be read safely.
7. As the Owner, I know what a deploy of HEAD could trigger automatically, especially paid re-extraction or re-embedding, without anything being started.
8. As the Owner, I have a recorded baseline of passing, failing and skipped tests on HEAD, and a fast CI foundation that makes no paid calls.
9. As a future maintainer or agent, I can trust `AGENTS.md`, `docs/KNOWN_ISSUES.md` and the v1 spec's Status ledger because M0 corrected what it proved wrong.

## Implementation Decisions

No file paths or code snippets in this section. Evidence pointers known before M0 are listed in Further Notes.

### General boundaries
- M0 is a factual audit and baseline, not a refactoring milestone. Its only repository changes are: the audit report, new tests, the CI workflow, and documentation corrections.
- No application behavior changes, no answering-path switch, no deletion of code (dead code is recorded, not removed), no paid model calls, no Railway changes, no hosted migrations, no deploys, no commits or pushes without the Owner's approval.
- Investigation is targeted: code searches, focused reads and focused tests. Full suites run once for the baseline, not repeatedly.
- Every finding carries a label and an evidence type. A search that finds nothing is reported as such, not as proof of absence.
- Findings answer decision questions. Tables or matrices appear only where they support a decision.

### Security escalation rule
- If a vulnerability reachable through a live request, a background job or the hosted configuration is confirmed at any point, it is reported to the Owner immediately, as a priority issue with evidence, before unrelated work continues and without waiting for the audit report. This overrides normal milestone order.
- An emergency fix is a separate, explicitly approved change outside the read-only audit boundaries. It is not part of M0's diff.
- Urgency follows the evidence, and nothing is assumed exploitable or harmless:
  - **Reachable and exploitable:** immediate escalation and a separately approved hotfix.
  - **Latent but unsafe:** removal goes into a focused M0-SEC milestone that completes before substantial M1 implementation.
  - **Proven unreachable or harmless:** the evidence is recorded, and the report states whether cleanup is still worthwhile.
- No exploit is run against the hosted system. Reachability is established from code, local tests and safe read-only hosted facts.

### Audit area A1: answering paths and flags
- Decide which code answers each top-level route (chitchat, file inventory, file target, grounded) for the flag settings that matter: the tool agent, LangGraph, hybrid retrieval, claim check and streaming flags, plus demo mode.
- Cover both chat entry points (the single chat request and conversation turns, including streaming) and say whether they reach the same path.
- Record what happens on provider failure in the path production reaches (the v1 spec requires that it never produces an ungrounded answer).
- Output: which path runs locally by default and which runs on Railway (the latter once A5 is read), with entry points, plus anything that contradicts the docs.

### Audit area A2: authentication, ownership and credential fallbacks
- Verify each of the six suspected first-credential fallbacks and find every caller, including routes, the indexing worker, demo loading, startup and scripts. Do not assume safety because mounted routes appear to pass an explicit Owner.
- Classify each one as exactly one of:
  - **Reachable security vulnerability**: some live request, job or configuration can reach it without an explicit Owner.
  - **Latent unsafe behavior**: no current caller reaches it, but the code would act on another Owner's credential if a caller omitted the Owner.
  - **Safe or unreachable**: supported by evidence (for example, every caller is shown to pass a non-null Owner, and a test or type constrains it).
- Inventory the mounted routes, with their authentication dependency and demo-mode behavior. Identify defined but unmounted routers and whether anything else can reach them.
- Check whether stored Google credentials are encrypted at rest by default and what happens when encryption is not configured. Check whether logs can expose tokens, authorization codes or File content.
- Note the session-enable flag's effect on every route when it is off.
- Record what rate limiting or abuse protection exists for Owner-mode requests (the demo limiter is separate), as input to the security-triage decision the v1 spec leaves open. M0 recommends; it does not decide or build.
- Separate real current vulnerabilities from future multi-Owner scalability concerns, as the v1 spec requires.
- Output: findings plus a proposed **M0-SEC** follow-up (scope, ordering, acceptance), written only after every fallback and caller is confirmed.

### Audit area A3: Preparation and File states
- Determine what Preparation does end to end today: Drive check, the separate preparation stages, how the frontend sequences them, what the indexing-enable flag gates, and whether anything starts a Drive check or Preparation without explicit Owner action (forbidden by the v1 spec's Freshness rule).
- Map the v1 spec's File states (prepared, unprepared, unsupported, failed, outdated) and its selection, exclusion and summary requirements to what exists: exists, partial or missing. Report whether Unsupported files are shown to the Owner.
- Investigate, without triggering, what could cause expensive reprocessing: raising the extraction pipeline version, applying pending migrations, changes to embedding settings, or a restart or redeploy. Estimate the scale only from counts the Owner can safely read, and never by running it.

### Audit area A4: conversations, deletion and privacy
- Inventory what is stored per Owner (conversations and turns, query history, Files and Documents, Chunks, vectors, credentials, sessions, jobs, traces or logs) and where (relational database, vector store, browser storage).
- For each existing delete or logout action, establish by code and a focused test what it removes and what remains. In particular, establish whether deleting a conversation removes its linked query history.
- Establish whether any backend Disconnect, Revoke or Delete-stored-data path exists.
- Describe what conversation history the answering path receives and its bounds, from code only. Whether it is sufficient for follow-ups is an evaluation question for M1 or M4, not M0.
- No privacy claim is made from this area; it records facts.

### Audit area A5: Railway deployment and migration state
- Use read-only Railway CLI operations where available and safe. Commands are proposed one at a time, each with a brief statement of what it reads and why it is needed. No command that touches the live Railway environment runs without the Owner's explicit approval of that command, even if it is read-only. Where the CLI is unavailable or unsafe, give the Owner a short dashboard checklist.
- Record only non-secret facts: deployed commit, branch, whether each relevant flag is on or off, model identifiers, migration revision, and whether managed backups are included. Never print, record or commit variable values that are secrets, tokens, connection strings or private infrastructure identifiers. Commands that would display secret values are not used.
- The hosted migration revision is Unverified until read directly. The bootstrap revision in the private-beta guide is not evidence of the current revision.
- Anything that cannot be obtained safely stays Unverified.
- Record which environment-variable and migration differences between `main` and HEAD would matter to a deploy (read-only Git comparison).

### Audit area A6: tests and CI foundation
- Run the full backend suite once on HEAD with disposable PostgreSQL and Qdrant containers, plus the frontend test, lint and build. Record counts, duration, the names of skipped tests and the reasons they skip, and failures.
- Run ruff, ruff format check, mypy and basedpyright once and record the results. Where a check is not clean project-wide, record the scope it is clean on.
- Classify tests by what they need (none, containers, network, paid API) and measure the time of each group. Choose the initial CI checks from this evidence.
- CI is a single, small, free workflow: fast static checks and the fast container-free backend tests, plus frontend test, lint and build. The exact structure follows the measured dependencies and timings. The full container suite is not run on every commit unless measurements justify it. It runs at meaningful checkpoints instead, locally or as a manually triggered CI job.
- CI never has a paid API key and never runs RAG evaluations.
- The workflow is verified by running its commands locally. Hosted verification happens after the Owner authorizes a push, outside M0's acceptance.
- Whether GitHub Actions minutes cost anything for this repository is checked against GitHub's official documentation and cited.

### Defect tests and the registry
- A confirmed defect gets a deterministic regression test that reproduces the real failure (strict expected failure, per the registry rule) only where one can be written without paid calls. It must fail for the stated reason before a fix.
- A test that protects existing correct behavior (for example, that a route requires a principal) should pass today. Not every added test must fail; no artificial expected failures and no placeholder tests are added to satisfy a checklist or the registry.
- Each fallback gets a defect test if it is a reachable or latent defect, or a protective test if it is shown safe, in each case only if the test is meaningful and deterministic.
- For the open evaluation-only defects (KI-022, KI-027, KI-028, KI-029, KI-030), M0 records for each one whether a deterministic unit or integration reproduction is feasible. Cases that need a paid model stay as RAG evaluation cases, separate from ordinary tests. The registry wording is corrected accordingly.

### Documentation corrections
- Correct only what the audit proves wrong: the v1 spec Status ledger (for example the fallback count), `AGENTS.md` (constraints and latest verification), `docs/KNOWN_ISSUES.md` and the security module README. No new guides.

## Testing Decisions

- A good M0 test asserts externally visible behavior (a service's result, a route's response, rows in the database) and fails for the stated reason today. It does not assert implementation details.
- Tests that need the database or vector store use the existing disposable-container fixtures. No test reaches Google, OpenAI or Railway.
- Existing security tests are prior art for ownership tests, and the existing known-issues helper is prior art for strict expected failures.

### Acceptance criteria
1. `docs/audits/m0-system-audit.md` exists, written from execution findings. Each finding has a label, an evidence type and a pointer (file and symbol, test name, command, or "hosted read on <date>"). It contains no secrets or hosted identifiers.
2. A1: the report states which path answers each top-level route under the local defaults and under the hosted flags (or "Unverified" for each hosted flag not read), for both chat entry points, with entry points named.
3. A2: all six suspected fallbacks are verified (or shown not to exist), every caller is listed, and each one has exactly one of the three classifications with evidence. Each mounted route is listed with its authentication dependency, and unmounted routers are identified.
4. A2: any reachable vulnerability was reported to the Owner when found, before unrelated work continued. The report records when.
5. A2: the report gives a proposed M0-SEC (scope, acceptance criteria) whose ordering follows the urgency rules above: hotfix, completed before substantial M1 implementation, or recorded as cleanup with the evidence.
6. A3: each v1 spec Preparation and File-state requirement is marked exists, partial or missing with evidence. Reprocessing triggers are listed, and nothing was triggered.
7. A4: every stored item has an identified deletion action or "no deletion path found", with the search method stated. The conversation-delete versus query-history question has a test-backed answer.
8. A5: each listed hosted fact has a value or "Unverified (reason)". The repository diff contains no secret values, connection strings or private identifiers.
9. A6: the baseline (counts, duration, skipped test names with reasons, failures, commit) is recorded in `AGENTS.md`. Tests are grouped by dependency with measured times.
10. A6: the CI workflow exists, and its commands pass locally on the audited commit, or each failing check is recorded with its reason. The workflow has no paid key and no evaluation step. CI cost is answered with a citation.
11. Every test added is deterministic and meaningful. A test reproducing a confirmed defect fails today for the reason stated in its registry entry. A test protecting existing correct behavior passes. No artificial expected failures. Cases needing paid model calls stay as RAG evaluation cases, outside ordinary tests.
12. The documentation corrections match the findings, and no other files change.
13. Apart from the new tests, the CI workflow and documentation, `git diff` against the audited commit is empty. An emergency fix, if one is needed, is a separately approved change and is excluded from this check.
14. The report ends with a short, evidence-based proposal for revising the M1 to M10 order, including whether any security finding moves ahead of M1.

## Out of Scope

- Fixing the fallbacks or any other defect. Fixes go to M0-SEC or to a hotfix the Owner approves separately.
- Switching, disabling or deleting answering paths (ADR 0001, steps 2 and 3).
- Deleting the unmounted legacy router or any dead code.
- Building Disconnect, Revoke, Delete stored data, File-state UI, selection or exclusion (M6, M7).
- Paid evaluations, follow-up quality measurement, latency measurement through the deployed app (M1, M4, M9).
- Any Railway change, hosted migration, re-indexing, deploy, push or promotion to `main`.
- Hosted CI verification (after an authorized push), CI expansion and running the full suite on every commit.
- Demo spend cap (M9, ADR 0002).

## Further Notes

### Dependencies
- M0 depends on nothing. M1, M4, M6 and M7 depend on its findings. M0-SEC is proposed by M0, and its timing follows the evidence (see the security escalation rule): a hotfix at once, or completed before substantial M1 implementation.
- A5 needs the Owner's explicit approval of each Railway command (or a dashboard read). A6's baseline needs local Docker for the disposable containers.
- Suggested order: A5 (read-only, may reveal live risk), A6 baseline, A2, A1, then A3 and A4 (independent), CI workflow, consolidation. The order is provisional; the security escalation rule overrides it.

### Pre-spec observations (inputs to verify, not findings)
From a limited search on 2026-11-21. Each must be re-checked during execution.
- Six suspected first-credential fallbacks, all selecting one stored Google credential with no owner filter: in user resolution, Drive sync, Drive content, chunking, ingestion and indexing services.
- Mounted routes appeared to resolve the Owner from an application session and pass it down; not traced for all callers.
- A legacy Google authorization router that stores tokens appeared to be defined but not included in the API router.
- Indexing, the tool agent and application sessions each default to off in configuration.
- Query history is stored apart from conversation turns, which link to it.
- Strict expected-failure tests appear to be missing for KI-022, KI-027, KI-028, KI-029 and KI-030.
- Backend tests use disposable PostgreSQL and Qdrant through test-specific environment variables. The last full run took about 17 minutes.
- A security test about encrypted-only credentials exists; its scope was not read.
- The private-beta guide describes a one-time bootstrap migration. This does not establish the hosted revision.

### Related documents
`docs/specs/drivemind-v1-product-definition.md`; `GLOSSARY.md`; `docs/adr/0001-single-answering-path.md`; `docs/adr/0002-public-demo-isolation.md`; `docs/KNOWN_ISSUES.md`; `docs/HANDOFF_2026-11-21.md`; `docs/guides/RAILWAY_PRIVATE_BETA.md`; `CODING_STANDARDS.md`; `AGENTS.md`.

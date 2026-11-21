# 01: Railway hosted-state verification (A5)

**Spec:** docs/specs/m0-system-audit.md
**What to build:** The Owner learns what Railway currently runs (deployed commit and branch, relevant flag on/off values, model identifiers, migration revision, managed backups), or which of these could not be read safely, and what a deploy of HEAD would change. Nothing on Railway is modified.
**Blocked by:** None (can start immediately). Needs the Owner present: each live command needs approval.
**Status:** ready-for-human
**Progress:** resolved

## Scope

- Propose Railway CLI commands one at a time. Before each: say what it reads and why. Run it only after the Owner explicitly approves that command, even if read-only. Where the CLI is unavailable or unsafe, give the Owner a short dashboard checklist instead.
- Facts to read: deployed commit and branch; on/off state of `TOOL_RAG_AGENT_ENABLED`, `AGENT_GRAPH_ENABLED`, `HYBRID_RETRIEVAL_ENABLED`, `CLAIM_CHECK_ENABLED`, `CHAT_STREAMING_ENABLED`, `INDEXING_ENABLED`, `GOOGLE_APPLICATION_SESSIONS_ENABLED`, `DEMO_MODE`; chat, claim-check and embedding model identifiers; Alembic revision; whether managed backups are included.
- Read-only Git comparison of `main` and HEAD: environment variables added or changed (`backend/app/core/config.py`) and Alembic migrations not on `main`, and whether either matters to a deploy.
- Anything not obtainable safely is recorded as `Unverified (reason)`.
- **Google OAuth configuration check** (added from the ticket 04 Owner decisions; the application has no sign-in allow-list, so these settings decide who can sign in when `GOOGLE_APPLICATION_SESSIONS_ENABLED` is on). Read-only, on the Owner's screen or with the Owner's per-step approval; nothing is changed. Record each as a value or `Unverified (reason)`:
  1. Publishing status of the OAuth consent screen: **Testing** or **In production**.
  2. User type: **External** or **Internal**.
  3. Whether access is restricted to approved test users, and whether the Owner's intended Google account is on that list (record yes or no and the **number** of test users only).
  4. Whether the current hosted session configuration could let an unintended user sign in: combine the hosted `GOOGLE_APPLICATION_SESSIONS_ENABLED` value and whether a session redirect URI and Google client are configured (set or not set, never the values) with items 1 to 3. State the conclusion as analysis: sign-in is closed, closed only by the Google test-user list, or open.

## Out of scope

Any Railway or Google Cloud change, redeploy, restart, migration, variable edit or log tailing. Any change to authentication or the OAuth client, and any application code (fixes are M0-SEC). Commands that print variable values (for example a plain variables listing) are not used; if a flag can only be read that way, use the dashboard checklist. No exploit or probing of the hosted app.

## Inspect

`docs/guides/RAILWAY_PRIVATE_BETA.md` (the bootstrap revision there is not evidence of the current revision), `backend/app/core/config.py`, `backend/alembic/versions/`, `git diff main..HEAD --stat` limited to those paths.

## Deliverables

Findings appended to this ticket under `## Findings`: one line per hosted fact (including the four Google OAuth items above) (value or `Unverified (reason)`), label, evidence type ("hosted read on <date>" or "Git comparison"), plus the deploy-impact note (including whether a deploy could trigger paid re-extraction or re-embedding, stated as analysis, not triggered). Consolidated later by ticket 08.

## Needs

No paid APIs. Live infrastructure: yes (Railway and the Google Cloud console, read-only; the Owner approves each Railway command and each Google Cloud console step beforehand). If a vulnerability reachable through the hosted configuration appears, in particular private data exposed or unauthorized paid usage possible, report it to the Owner immediately and propose a separately approved hotfix (spec, security escalation rule).

**Privacy of this public repository:** never print, paste or store OAuth client IDs or secrets, tokens, redirect-URI values, email addresses, project identifiers or any other private account information in this ticket, the repository or a commit. Record only non-identifying facts: statuses, yes/no, counts, "set / not set".

- [x] Every Railway command run was approved by the Owner individually beforehand; the commands and approvals are listed in `## Findings`. (Two commands, C1 and C2.)
- [x] Every hosted fact listed in Scope has a value or `Unverified (reason)`. (Most values are Owner-reported, not independently read; several are `Unverified` by the Owner's deferral. See `## Findings`.)
- [x] The ticket and repository diff contain no secret values, connection strings, tokens or private infrastructure identifiers (checked by reading the diff before resolving). (Read in full and pattern-scanned before the commit; an independent review also scanned it.)
- [x] The `main`..HEAD comparison lists env-var and migration differences relevant to a deploy, or states none were found.
- [x] The four Google OAuth items (publishing status, External or Internal, test-user restriction and whether the intended account is included, and whether unintended users could sign in) each have a value or `Unverified (reason)`, and each Google Cloud step was approved by the Owner beforehand. (Qualified: no Google Cloud step was run by the assistant; the Owner read the console and reported the values. The "intended account is included" answer is the assistant's reading of the Owner's statement, marked as such. Item 4 is analysis, not a guarantee.)
- [x] No credential, token, email address, project identifier or redirect-URI value appears in the ticket or the diff.
- [x] Nothing on Railway or Google Cloud changed, no authentication change was made, and no repository file other than this ticket changed.

## Findings

**Status of this section: complete, 2026-11-21.** Written on branch `feature/v2-state-performance` at `4f3d968`. Every fact has a value or an `Unverified (reason)`.

**Owner decision, 2026-11-21 (changes the scope of what was investigated, not the evidence).** The Owner's Railway test environment is a **disposable testing environment**. It is intentionally offline and the Owner states it holds no important client or production data. The Owner will rebuild or reconfigure Railway after the codebase audit rather than investigate or maintain it as it is. Investigation of the old environment therefore stopped after C1 and C2. The items marked "deferred" below are `Unverified` **because that investigation was deliberately not done**, not because it was tried and failed. The statement that the environment holds nothing important is the Owner's; I did not check it (see "Before any reset" in section 4).

**Evidence types.** *Owner-reported*: the Owner read the value on a Railway or Google Cloud dashboard on 2026-11-21 and told me (the ticket's "hosted read on <date>", made by the Owner); I did not see the dashboard and did not verify it independently. *Hosted read (CLI)*: output of a Railway CLI command I ran after the Owner's approval. *Git comparison*: read-only `git` plus local files. *Analysis*: my reasoning from code and dates, not exercised. The Verified / Unverified labels follow the v1 spec; the evidence types above extend its list. **No hosted fact is labelled "Verified" in the independent sense**; the two CLI reads are labelled by what the CLI printed.

**Privacy.** The CLI output contained project, environment, service and deployment IDs, a public frontend address and the project name. None of it is in this file. Only statuses, a date, counts and set / not set are recorded.

### 1. Hosted facts

| # | Fact | Value | Label | Evidence |
|---|---|---|---|---|
| H1 | Deployed commit and branch | **None is deployed.** The three most recent backend deployments (latest 2026-10-26) are all `REMOVED`, and the Owner states all four services are intentionally offline. The commit and branch of those removed deployments are `Unverified` (the CLI's readable output has no commit or branch field; reading them was **deferred** by the Owner's decision; see section 3, point 6 for a date-based inference) | Hosted read (CLI) for the status and date; Unverified for commit and branch | C2, 2026-11-21 |
| H2 | `TOOL_RAG_AGENT_ENABLED` | on | Owner-reported | Owner dashboard read, 2026-11-21 |
| H3 | `AGENT_GRAPH_ENABLED` | off | Owner-reported | same |
| H4 | `HYBRID_RETRIEVAL_ENABLED` | on | Owner-reported | same |
| H5 | `CLAIM_CHECK_ENABLED` | not set (so the code default applies; on at HEAD) | Owner-reported | same |
| H6 | `CHAT_STREAMING_ENABLED` | on (backend variable only; the frontend build flag was not read) | Owner-reported | same |
| H7 | `INDEXING_ENABLED` | on | Owner-reported | same |
| H8 | `GOOGLE_APPLICATION_SESSIONS_ENABLED` | on | Owner-reported | same |
| H9 | `DEMO_MODE` | off | Owner-reported | same |
| H10 | Models | chat `gpt-4o-mini`; embedding `text-embedding-3-small`; claim-check model not set (code default `gpt-5.4-mini` would apply) | Owner-reported | same |
| H11 | Alembic revision of the hosted database | **Unverified (deferred: the PostgreSQL service is intentionally offline and its Data interface cannot be read offline; the Owner ruled out starting services or running migrations to get it, and the environment is disposable).** The revision named in the private-beta guide is not evidence of the current one | Unverified | none |
| H12 | Whether managed backups are included | **Unverified (deferred: not read; the Owner chose not to investigate the disposable environment).** Backups for the future rebuild are a requirement, see section 4 | Unverified | none |
| H13 | Session redirect URI, Google client ID, Google client secret configured | all three set (never read or recorded as values) | Owner-reported | Owner dashboard read, 2026-11-21 |
| H14 | Service run state, production environment | Frontend, backend, Qdrant and PostgreSQL all shown `Offline` (hosted read, CLI). PostgreSQL volume 0.2 GB used of 4.9 GB (this bounds the size of the stored data, it is not a document count). That the offline state is intentional is the Owner's statement | Hosted read (CLI) for what was printed; Owner-reported for "intentional" | C1, 2026-11-21 |
| H15 | Hosted document and file counts, user count, unexpired session count | **Unverified (deferred: database offline, same reason as H11)** | Unverified | none |

### 2. Google OAuth configuration check

| # | Item | Value | Label | Evidence |
|---|---|---|---|---|
| G1 | Publishing status | **Testing** | Owner-reported | Owner console read, 2026-11-21 |
| G2 | User type | **External** | Owner-reported | Owner statement, 2026-11-21 |
| G3 | Access restricted to approved test users | Test-user list present, **4** accounts, all described by the Owner as intended | Owner-reported | same |
| G3a | The Owner's intended Google account is on the list | **Yes**, on the basis of the Owner's statement that the four listed accounts are the intended ones. The Owner did not name their own account separately, so this is my reading of that statement | Owner-reported (interpreted) | same |
| G3b | OAuth lifetime user count | **6** of a cap of 100 | Owner-reported | same |
| G4 | Could an unintended user sign in | See below | Analysis | code, plus the Owner-reported values above |

**G4 analysis (a reading of the evidence, not a guarantee).**

- The application has no sign-in allow-list: any Google identity that Google lets through creates a user row and a session (ticket 04, `google_session_auth_service.py:343`). The only gate is Google's.
- Reported configuration: sessions on (H8), session redirect URI and Google client set (H13), External app in Testing (G1, G2), 4 listed test users (G3).
- **Conclusion: when the backend is running, sign-in is restricted only by the Google test-user list** (the ticket's "closed only by the Google test-user list" outcome, not a guarantee). The application itself does not restrict it. This rests on Owner-reported values and on a list that lives outside the repository, which I cannot inspect.
- **As of the 2026-11-21 reads, no backend deployment is active (H1) and all four services show `Offline` (H14), so the backend should not be answering sign-in or chat requests.** This rests on the CLI's status output and the Owner's statement that the offline state is intentional. I did not test it from outside, and I did not check for other public endpoints (the frontend has a public address; whether Qdrant or PostgreSQL have public domains was not read). It says nothing about the state after a redeploy.
- **6 lifetime users against 4 listed:** at least two other Google accounts have authorized this client at some point. Whether they were removed testers or the Owner's own accounts is unknown. I assume, without having read Google's documentation, that removing an account from Google's test-user list stops that account from signing in again. Whatever Google does, the application does not revoke a session it has already issued: sessions last 7 days (`application_session_service.py:28`), and the lookup checks the credential hash, the session kind, revocation and expiry (`:134-143`), never Google's list. Because the backend is offline, a session issued before the shutdown could be used again only if it has not expired and the same database returned. How long the backend has been offline was not read. The `users` and session counts are `Unverified` (H15). If the database is rebuilt empty, those user rows and sessions no longer exist (analysis).
- **Cost exposure when running:** ticket 04 found that the tool-agent path (on, H2) has no early exit for an empty corpus and Owner mode has no per-user limit, so a signed-in account with no files probably still causes a paid model call per question. With the reported list this is limited to the four intended accounts plus any account still holding a live session. That is an M0-SEC input, not something this ticket changes.

**Escalation check.** No vulnerability reachable through the hosted configuration is confirmed by the evidence gathered. That is not a finding that none exists: the hosted values are Owner-reported and the sign-in gate is an external list I could not inspect. No hotfix is proposed.

### 3. Git comparison, `main` and HEAD (evidence: Git comparison)

`main` (`6cf31f6`) is an ancestor of HEAD; HEAD is **164 commits ahead and 0 behind**. Every difference below was added by the branch.

**Environment variables in `backend/app/core/config.py`**, with the hosted value where the Owner reported it:

| Change | Names | Matters to a deploy? |
|---|---|---|
| Added (11) | `INDEXING_ENABLED` (default off), `INDEXING_ACTIVATION_TARGET`, `INDEXING_DATABASE_SCHEMA`, and eight `INDEXING_*` timing settings | `INDEXING_ENABLED` is on (H7). Whether the activation target is set was not read. |
| Added (4) | `GOOGLE_APPLICATION_SESSIONS_ENABLED` (on, H8), `GOOGLE_SESSION_REDIRECT_URI` (set), `GOOGLE_CREDENTIAL_ENCRYPTION_KEYRING`, `GOOGLE_CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID` | Keyring and key-ID settings were not read. |
| Added (1) | `CHAT_STREAMING_ENABLED` (on, H6) | Already set. |
| Added (2) | `CLAIM_CHECK_ENABLED` (default **on**), `CLAIM_CHECK_MODEL` (default `gpt-5.4-mini`) | **Both unset on Railway (H5, H10), so a deploy of HEAD turns the claim check on.** |
| Added (3) | `RETRIEVAL_RELATIVE_THRESHOLD` (0.7), `RETRIEVAL_NAME_TERM_MAX_FILES` (2), `RETRIEVAL_MAX_CHUNKS_PER_FILE` (3) | Whether they are set on Railway was not read. If unset, answers change on deploy. No cost. |
| Default changed | `CHAT_MODEL`: `gpt-4o-mini` to `gpt-5.4-nano` | **No effect:** the hosted value is set explicitly to `gpt-4o-mini` (H10). |
| Default changed | `RETRIEVAL_SCORE_THRESHOLD`: 0.35 to 0.25 | Whether set on Railway was not read. If unset, answers change. No cost. |
| Unchanged | `EMBEDDING_MODEL`, `HYBRID_RETRIEVAL_ENABLED`, `TOOL_RAG_AGENT_ENABLED`, `AGENT_GRAPH_ENABLED` | Hosted `EMBEDDING_MODEL` is explicitly `text-embedding-3-small`, so a deploy does not force re-embedding through a model change. |

**Alembic migrations not on `main`:** 10 (`20261009_1200` to `20261120_1200`), of 16 in total. The chain is linear with one head, `20261120_1200` (local parse of the files, no database touched).

**Deploy-impact analysis (nothing was run or triggered):**

1. **A deploy does not migrate, and with indexing on a stale schema stops the start.** `backend/deploy/start.sh` runs only `uvicorn`, and its comment says it does no migration. HEAD's `Document` model maps `documents.pipeline_version`, which only migration `20261120_1200` creates. With `INDEXING_ENABLED` on (H7), the lifespan in `backend/app/main.py` calls `create_normal_runtime` first (`main.py:81-88`), which runs a schema check that issues `select(model).limit(0)` for six models, `Document` among them (`indexing_runtime.py:146-155`). Selecting a model names all its mapped columns, so a database below `20261120_1200` would raise there, and a non-transient error becomes `SCHEMA_INCOMPATIBLE` (`indexing_runtime.py:213-215`). The probable result is a **refused start**, not later query errors. With indexing off, the lifespan only fails stale `RUNNING` jobs, and the missing column would instead break queries that load `Document` rows. Analysis from the code, not exercised against any database. (A review of this ticket caught an earlier version of this point that wrongly said startup validation was not established.)
2. **Migrating starts no work by itself, but it can make the next Prepare expensive.** The migration gives every existing document `pipeline_version = 1`; HEAD's `EXTRACTION_PIPELINE_VERSION` is 3, so every indexed file is treated as stale (`ingestion_queries.py:14-30`). The next ingest re-reads those files from Drive (Drive and local OCR, no paid API). **If the new text differs** (DOCX tables, PDF headers and footers, PPTX and Sheets readers), the chunk and **embedding** steps follow, and embedding is the paid OpenAI call. How many files would change is `Unverified` (H15). Only a bound is known: the whole PostgreSQL volume holds 0.2 GB (H14), so the corpus is small. That is not a cost estimate.
3. **What starts an ingest.** Nothing in startup, the migration or the lifespan enqueues ingestion. I did not trace whether any frontend path starts Preparation without an Owner click; ticket 06 owns that question.
4. **The claim check adds a paid call on deploy.** Tool agent on (H2), `CLAIM_CHECK_ENABLED` unset (H5): HEAD defaults it to on, adding one small-model call (`gpt-5.4-mini` default) per tool-agent answer. The code comment says it fails open. To avoid it, the Owner would set the variable explicitly before a deploy; this ticket does not change variables.
5. **Unknown variables are ignored.** `Settings` uses `extra="ignore"`, and empty values count as unset. On `main`, the hosted `GOOGLE_APPLICATION_SESSIONS_ENABLED`, `INDEXING_ENABLED` and `CHAT_STREAMING_ENABLED` would do nothing, so a deploy meant to use them must come from branch code.
6. **What the last deployment probably contained (inference from dates).** The newest removed backend deployment is dated 2026-10-26. The newest commit on this branch before that deployment's time is `ffc5ef1` (2026-10-25). At that commit the config already has sessions, indexing and chat streaming, and does **not** have the claim check; the `pipeline_version` migration does not exist yet. So **if** that deployment was built from this branch, its code did not include `20261120_1200`, and the Railway guide's `20261015_1200` is a plausible upper bound for the database revision (a deploy never migrates, so the database could equally be lower, or could have been migrated by hand). This is an inference from commit dates; the actual commit and the actual database revision are `Unverified` (H1, H11). It does not establish the hosted state.

**Net deploy-impact for HEAD, stated as analysis. It applies if the existing database were reused; the Owner plans a rebuild instead (section 4):** (a) migration `20261120_1200` would have to run first, as a separately approved step; (a2) with indexing on, startup is refused unless `INDEXING_ACTIVATION_TARGET` matches the target computed from the configuration, the credential keyring and active key ID are valid, the session login settings validate, an OpenAI key is set, and demo mode and debug are off (`create_normal_runtime`, `indexing_runtime.py:281-300`); whether the hosted values satisfy these was not read; (b) set `CLAIM_CHECK_ENABLED` deliberately, or accept one extra paid small-model call per answer; (c) the next Prepare after migrating could trigger paid re-embedding for changed files, size unknown; (d) the chat and embedding models do not change. On a fresh, empty database (a), (c) and the stale-pipeline re-read do not arise, because every migration runs from the first revision to the head and every document is written at version 3; (b) still applies.

### 4. Deferred items, future deployment requirement, and the pre-reset check

**Deferred by Owner decision (intentionally not investigated; all `Unverified`):** the old environment's managed-backup status (H12), the hosted Alembic revision (H11), the row and user counts (H15), and the commit and branch of the removed deployments (H1). Further investigation is deferred because the environment is disposable and will be rebuilt. No further Railway or Google Cloud reads are needed to close this ticket.

**Future deployment requirement (Owner decision; an input to ticket 09 and to the deployment milestone, not work done here).** Establish a clean, reproducible Railway deployment, only after the codebase audit, with all of the following. The items name what the findings above show to be open; they are not a design.

1. **Validated environment variables**, written down as a checked list and compared with `backend/app/core/config.py` at the commit being deployed. Set explicitly, not by default: `CLAIM_CHECK_ENABLED` (its default is on, H5), the chat and embedding models, the retrieval thresholds if they matter, `INDEXING_ACTIVATION_TARGET` and the credential-encryption settings. Remove variables that no longer exist.
2. **Migrations** run once, from an empty database to the single head (`20261120_1200` at this commit), as a separately approved step, verified by reading the revision back. A deploy does not migrate (section 3, point 1).
3. **Security controls** decided before any real user data is stored: the application-level sign-in allow-list the Owner chose in ticket 04, owner-mode request limits and a spend cap, and the Google test-user list treated as a temporary outer control only (G4).
4. **Cost limits:** a hard budget on the OpenAI account, a decision on the claim check (H5, section 3, point 4), and no Prepare run on a large corpus until the cost of re-embedding is estimated from real counts.
5. **Backups appropriate to the data being stored:** none are needed while the environment holds only throwaway test data; before real files, conversations or Google credentials are stored, the guide's procedure applies (consistent database dump, vector-store snapshot, and a separate copy of the credential keyring), and the availability of Railway's own volume backups is checked in the console at that time (H12 is open until then).

**Before any destructive reset (Owner decision).** This ticket does not say anything is safe to delete, and nothing was deleted, reset or modified. Before the Owner resets or deletes the old environment, check that no important data, user account, file or credential needs preserving. The Owner states there is none; that has not been checked by me. Points to cover in that check: the database and vector store hold whatever test Drive content was indexed and the encrypted Google grants of every account that signed in (6 lifetime users, G3b); the encryption keyring is held separately from the database and the two belong together (guide, "Durability"); the Google OAuth client and its test-user list live in Google Cloud and are not affected by a Railway reset; the separate demo project is out of scope and must not be touched.

**Steps taken:**

| Step | What | Status |
|---|---|---|
| C1 | `railway status` | Done, approved beforehand, see log |
| C2 | `railway deployment list --service <backend> --limit 3` | Done, approved beforehand, see log |
| Google Cloud console | All four OAuth items | Read by the Owner, not by me. No Google Cloud command or step was run by me |

**Approvals log:**

| Approved by the Owner | Command or step | Run |
|---|---|---|
| 2026-11-21, before running; read-only; change nothing, do not access the demo project, redact identifiers, then stop and ask again | C1 `railway status` | yes, once, no flags; output reviewed, not copied into this repository |
| 2026-11-21, before running; "exactly as proposed", once, read-only, the linked project and its production environment, record only commit, branch, status and date | C2 `railway deployment list --service <backend service> --limit 3` | yes, once; the output had status and date but no commit or branch; deployment IDs were not copied into this repository |
| (none) | any other live command | not run. The Owner closed the investigation on 2026-11-21; no Railway or Google Cloud access after C2 |

## Comments

**2026-11-21, closing review.** An independent two-axis review (Standards and Spec) of this ticket's diff ran before the commit. It found one factual error, corrected here: the ticket first said startup validation might not catch a missing `documents.pipeline_version` column; the code shows it would refuse the start when indexing is on (section 3, point 1). It also found two wrong line citations (corrected), a categorical "nothing is reachable" statement (now qualified), an unsourced statement about Google's test-user list (now marked as an assumption), and several label and wording inconsistencies (fixed). No privacy violation was found. Remaining judgement notes, not acted on: some facts (offline state, 6 lifetime users) are stated in more than one place and could drift; section 4 reads as requirements, not a design, by the Owner's request.

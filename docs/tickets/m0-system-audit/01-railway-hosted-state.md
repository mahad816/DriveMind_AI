# 01: Railway hosted-state verification (A5)

**Spec:** docs/specs/m0-system-audit.md
**What to build:** The Owner learns what Railway currently runs (deployed commit and branch, relevant flag on/off values, model identifiers, migration revision, managed backups), or which of these could not be read safely, and what a deploy of HEAD would change. Nothing on Railway is modified.
**Blocked by:** None (can start immediately). Needs the Owner present: each live command needs approval.
**Status:** ready-for-human
**Progress:** open

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

- [ ] Every Railway command run was approved by the Owner individually beforehand; the commands and approvals are listed in `## Findings`.
- [ ] Every hosted fact listed in Scope has a value or `Unverified (reason)`.
- [ ] The ticket and repository diff contain no secret values, connection strings, tokens or private infrastructure identifiers (checked by reading the diff before resolving).
- [ ] The `main`..HEAD comparison lists env-var and migration differences relevant to a deploy, or states none were found.
- [ ] The four Google OAuth items (publishing status, External or Internal, test-user restriction and whether the intended account is included, and whether unintended users could sign in) each have a value or `Unverified (reason)`, and each Google Cloud step was approved by the Owner beforehand.
- [ ] No credential, token, email address, project identifier or redirect-URI value appears in the ticket or the diff.
- [ ] Nothing on Railway or Google Cloud changed, no authentication change was made, and no repository file other than this ticket changed.

## Comments

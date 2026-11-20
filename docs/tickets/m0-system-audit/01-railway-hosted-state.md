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

## Out of scope

Any Railway change, redeploy, restart, migration, variable edit or log tailing. Commands that print variable values (for example a plain variables listing) are not used; if a flag can only be read that way, use the dashboard checklist. No exploit or probing of the hosted app.

## Inspect

`docs/guides/RAILWAY_PRIVATE_BETA.md` (the bootstrap revision there is not evidence of the current revision), `backend/app/core/config.py`, `backend/alembic/versions/`, `git diff main..HEAD --stat` limited to those paths.

## Deliverables

Findings appended to this ticket under `## Findings`: one line per hosted fact (value or `Unverified (reason)`), label, evidence type ("hosted read on <date>" or "Git comparison"), plus the deploy-impact note (including whether a deploy could trigger paid re-extraction or re-embedding, stated as analysis, not triggered). Consolidated later by ticket 08.

## Needs

No paid APIs. Live infrastructure: yes (Railway, read-only, per-command approval). If a vulnerability reachable through the hosted configuration appears, report it to the Owner immediately (spec, security escalation rule).

- [ ] Every Railway command run was approved by the Owner individually beforehand; the commands and approvals are listed in `## Findings`.
- [ ] Every hosted fact listed in Scope has a value or `Unverified (reason)`.
- [ ] The ticket and repository diff contain no secret values, connection strings, tokens or private infrastructure identifiers (checked by reading the diff before resolving).
- [ ] The `main`..HEAD comparison lists env-var and migration differences relevant to a deploy, or states none were found.
- [ ] Nothing on Railway changed and no repository file other than this ticket changed.

## Comments

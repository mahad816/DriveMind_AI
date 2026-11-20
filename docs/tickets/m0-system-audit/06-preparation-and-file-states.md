# 06: Preparation and File-state audit (A3)

**Spec:** docs/specs/m0-system-audit.md
**What to build:** The Owner knows what Preparation does end to end today, which of the v1 spec's Preparation and File-state requirements exist, are partial or are missing, whether Unsupported files are shown, and what could trigger expensive reprocessing, so M6 builds only what is missing.
**Blocked by:** None (can start immediately).
**Status:** ready-for-agent
**Progress:** open

## Scope

- Describe Preparation today: Drive check, the separate stages (sync, ingest, chunk, build), how the frontend sequences and polls them, what `INDEXING_ENABLED` gates, and whether anything starts a Drive check or Preparation without explicit Owner action (the v1 spec's Freshness rule forbids it: check startup tasks, schedulers, page-load effects).
- Map the v1 spec's File states (prepared, unprepared, unsupported, failed, outdated) and its selection, exclusion and summary requirements to the code: exists / partial / missing, each with evidence. Report whether Unsupported files are shown to the Owner.
- List what could cause expensive reprocessing without triggering any of it: raising `EXTRACTION_PIPELINE_VERSION`, applying pending migrations, changing embedding settings, restart or redeploy. Estimate scale only from counts the Owner can safely read, never by running it.

## Out of scope

Building file-state UI, selection or exclusion (M6, M7); starting any sync, ingestion, chunking or build; any Drive or OpenAI call; fixing defects; live Railway counts (ask the Owner to read them if needed, via ticket 01's approval process).

## Inspect

v1 spec sections "Preparation and freshness" and "Freshness"; `backend/app/api/index.py`, `backend/app/services/` (sync, content, ingestion, chunking, indexing), `backend/app/db/` (File status enum), `backend/app/ingestion/pipeline_version.py`, `backend/app/main.py` (startup), `frontend/lib/knowledge/`, `frontend/app/`, `frontend/components/`, `docs/guides/`.

## Deliverables

`## Findings` in this ticket: Preparation flow description, requirement-to-implementation mapping (exists / partial / missing with evidence), automatic-start check result, reprocessing-trigger list. Tests only if meaningful and deterministic.

## Needs

No paid APIs. No live infrastructure. No Docker unless a focused test needs the database fixtures.

- [ ] The end-to-end Preparation flow and frontend sequencing are described with code pointers, including what `INDEXING_ENABLED` gates.
- [ ] Every v1 spec Preparation and File-state requirement is marked exists, partial or missing, with evidence.
- [ ] The report states whether anything starts a Drive check or Preparation without explicit Owner action, with the search method.
- [ ] The report states whether Unsupported files are shown to the Owner.
- [ ] Reprocessing triggers are listed; nothing was triggered; any scale estimate names its source count.
- [ ] No application code changed.

## Comments

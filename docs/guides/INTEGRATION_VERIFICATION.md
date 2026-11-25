# Isolated integration candidate — 2026-11-26

The candidate is `integration/drivemind-v2` in `DriveMind-v2-integration`. Main and both development worktrees are
preserved. Base `70c2ee6` directly inherits Checkpoint A `7d8764d` and the complete backend branch ancestry.
Frontend polish: `cec5025`. Drive sync integration: `6b73c27`. No backend cherry-pick or obsolete UI restoration.

## Preservation

Private snapshots: `~/.local/share/drivemind/handover-backups/20261125T205652Z/` (UTC timestamp).
The directory is mode 0700; files are 0600. It contains combined, staged and unstaged binary-capable patches,
explicit untracked archives, per-file hashes/modes, statuses, refs and SHA256SUMS. Archives were reopened and checked.
Local refs `backup/handover-20261125T205652Z-{main,backend,frontend,skills,demo,stash}` preserve the prior tips.
The old documentation stash and Claude customizations remain preserved and excluded from this candidate.
The duplicate blueprint already matches the committed rebuild version.

## Verification scope

All data is synthetic. Disposable PostgreSQL 18.6 and Qdrant 1.18.0 use independent containers and random loopback
ports. No personal `.env`, existing database, real OAuth credentials, Google indexing, paid API calls or protected
evaluation contents are used. Evaluation tests are excluded from the broad backend run for those restrictions.
Browser servers use 3310/8310; occupied 3000/8000 and 3100/8100 services are untouched.

## Results

- Broad backend non-evaluation run: **3548 passed, 9 failed, 5 skipped, 6 xfailed** in 26m09s.
  Five failures were a runner PATH mistake (direct pytest could not spawn `alembic`); one was an obsolete privacy
  assertion targeting removed `frontend/lib/user-language.ts`, now ported to the actual settings link; three were
  transient indexing readiness failures. With the virtualenv on PATH, all three affected files reran: **46 passed**.
  This is a qualified result from a broad run plus isolated reruns, not one clean full run. The full run was not repeated.
- Frontend: **701 passed** in 38 files; 19 review-focused regressions passed again. TypeScript and lint passed.
  An initial TypeScript error in a new Testing Library query was corrected; the standalone rerun passed.
- Deployment API proxy: **12 passed**.
- Final normal browser journeys: **44 passed, 0 failed**, including axe checks in both themes.
  The additional sync journey passed availability recovery, definite rejection, unknown outcome, refresh and tab-return checks.
- Backend Ruff/format/mypy passed (423 formatted Python files; mypy 191 application files).
  Basedpyright: **59 errors, 5 warnings**, all in pre-existing test code; no application errors and none in the new tests.
- Disposable database: fresh upgrade through `20261121_1200` then `20261125_1200`; downgrade one and re-upgrade succeeded.
  Head is `20261125_1200`. `alembic check` reports the pre-existing `users`/`chunks` index drift, no new job-column drift.

- Normal and demo production builds passed. The production-built demo passed **11 browser checks**.
- Responsive checks passed at 1100, 820, 390 and 320 px in both themes; contrast pairs meet WCAG 2.2 AA.
- The real FastAPI/PostgreSQL browser smoke passed against both development and the final normal production build
  (last run **1 passed in 5.03s**). Actual session, file inventory, sync availability, persisted conversation/history,
  answer and source routes were exercised; external Drive and RAG providers were synthetic.
- Final schema inspection confirmed `failure_class` is nullable `varchar(32)` and the head is `20261125_1200`.

Logs, exit-code results and checksums are in the snapshot's private `verification/` directory. The initial frontend
runner's TypeScript exit code 2 is retained in `results.json`; the corrected standalone/build checks passed, recorded
as `tsc_after_query_fix: 0`. No test evidence was rewritten to hide an earlier failure.
Live OAuth, actual Drive sync, paid model quality, rebuilt Docker images and hosted Railway settings remain outside
this verification. Backend/frontend Docker and deployment source are inherited unchanged. A main promotion or deployment
requires Owner approval.

## Review fixes and intentionally excluded work

One independent read-only review found two P2 issues, both fixed in `640a90e`: stale inventory was used as a sync
completion result, and completed-answer Ask Again bypassed the composer readiness block. Regressions cover both.
That commit also ports the obsolete backend privacy assertion without dropping the Google-link/no-handler contract.
No P0/P1, security or data-loss blocker was found. The same reviewer inspected closure source and final evidence and issued **APPROVE** for the isolated candidate, with no unresolved P0/P1/P2 integration defect. This is approval for Owner review before promotion, not deployment approval.

The dated UX audits are retained with explicit supersession notes. Old `drive-discovery`/`knowledge-library` components
and their copy-only test edits were not restored: shared behavior and redesigned controls have their own coverage.
The duplicate blueprint, pending Claude settings/SKILL customization and wrong-baseline documentation stash were not
imported. Their original states remain in the private snapshots and original worktrees.


## Git and release boundary

All approved backend commits are ancestors of the candidate. Compared with `70c2ee6`, no migration, preparation
controller, conversation controller or deployment source was removed or replaced. No test file was deleted.
The separate cached demo branch was preserved, not merged wholesale: ten commits are patch-equivalent to inherited
work, while historical archive/old UI commits remain in its backup history. The production demo checks cover its
root-rendering concern with the new UI. Remote-tracking refs were not refreshed; upstream state remains unverified.

Final preservation checks compare original HEADs, statuses, staged/unstaged binary patches and all 28 pending-file hashes against the snapshot. The report requires a clean committed candidate. Main remains
`6cf31f65031b99014c80c7bcbf94b4f8ec6c8999`. No push, deploy, production migration, real Drive operation or paid call occurred.

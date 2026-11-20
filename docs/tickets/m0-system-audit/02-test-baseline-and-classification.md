# 02: Local test baseline and test-dependency classification (A6, part 1)

**Spec:** docs/specs/m0-system-audit.md
**What to build:** The Owner has a recorded, trustworthy result of every quality check on the current HEAD (counts, duration, skipped tests with reasons, failures), the tests grouped by what they need (none, containers, network, paid API) with measured times, and a feasibility note for the five evaluation-only known issues. This is the evidence ticket 08 uses to pick CI checks.
**Blocked by:** None (can start immediately). Needs local Docker.
**Status:** ready-for-agent
**Progress:** open

## Scope

- Run once on HEAD: full backend suite (disposable PostgreSQL and Qdrant containers, test-specific environment variables as the existing fixtures expect); `ruff check`, `ruff format --check`, `mypy`, `basedpyright`; frontend `npm test`, `npm run lint`, `npm run build`. Do not re-run full suites repeatedly; use focused runs for anything else.
- Record: commit, counts (passed, failed, skipped), duration, names of the skipped tests and why they skip, every failure. If a static check is not clean project-wide, record the scope it is clean on.
- Classify tests by need: none / containers / network / paid API. Measure the time of each group (for example via markers, directory selection or `--durations`), without changing test behavior.
- For KI-022, KI-027, KI-028, KI-029, KI-030: record whether a deterministic unit or integration reproduction is feasible without a paid model. Where feasible, write a strict expected-failure test that fails for the registry's stated reason (existing helper in `backend/tests/known_issues/`). Where it needs a paid model, state it stays a RAG evaluation case. Correct the registry wording in `docs/KNOWN_ISSUES.md` accordingly.
- Update the "Latest recorded verification" section of `AGENTS.md` with the baseline.

## Out of scope

Fixing any failure or defect, paid or network-dependent runs, evaluations (`backend/evaluation/`), CI workflow (ticket 08), other `AGENTS.md` corrections (ticket 09), changing application code or existing tests.

## Inspect

`backend/pyproject.toml` (pytest, ruff, mypy, basedpyright config), `backend/tests/conftest.py` and `backend/tests/security/conftest.py` (container fixtures), `backend/tests/known_issues/`, `docs/KNOWN_ISSUES.md`, `docs/HANDOFF_2026-11-21.md` (sections 3, 5), `infra/docker-compose.yml`, `frontend/package.json`.

## Deliverables

`## Findings` in this ticket (baseline table, dependency groups with times, KI feasibility list); `AGENTS.md` verification section updated; new strict expected-failure tests (only where feasible) with matching `docs/KNOWN_ISSUES.md` wording.

## Needs

No paid APIs (the suite must not reach OpenAI, Google or Railway; if a test does, record it as a finding). No live infrastructure. Local Docker required; the full backend run takes about 17 minutes.

- [ ] Baseline records commit, passed/failed/skipped counts, duration, skipped test names with reasons, and failures for backend and frontend, and the result of all four static checks (with scope if not project-wide clean).
- [ ] `AGENTS.md` "Latest recorded verification" matches the recorded run and states the commit it was run on.
- [ ] Tests are grouped by dependency (none / containers / network / paid API) with a measured time per group, and the method used is stated.
- [ ] Each of KI-022, -027, -028, -029, -030 has a recorded feasible/not-feasible decision with reason; registry wording matches.
- [ ] Every test added is deterministic, uses no paid call, and fails today for the reason in its registry entry (expected-failure) or is not added. No placeholder tests.
- [ ] Only `AGENTS.md`, `docs/KNOWN_ISSUES.md`, new known-issue tests and this ticket changed; no application code changed.

## Comments

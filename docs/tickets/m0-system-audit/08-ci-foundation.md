# 08: Lightweight CI foundation (A6, part 2)

**Spec:** docs/specs/m0-system-audit.md
**What to build:** A single small, free GitHub Actions workflow that runs the fast checks chosen from ticket 02's measurements, with no paid key and no evaluation step, verified by running its commands locally on the audited commit.
**Blocked by:** 02.
**Status:** ready-for-agent
**Progress:** open

## Scope

- Choose the CI checks from ticket 02's dependency groups and timings: fast static checks (ruff, format check, mypy, basedpyright where clean), the container-free backend tests, and frontend test, lint and build. Where a check is not clean project-wide, scope it to what is clean and record why.
- Add `.github/workflows/` (directory does not exist yet) with one workflow. The full container suite is not run per commit unless 02's measurements justify it; if included at all, as a manually triggered job only.
- Answer, citing GitHub's official documentation: do Actions minutes cost anything for this repository (public repository, standard runners)? Record the URL and the date read.
- Run every workflow command locally on the audited commit and record pass/fail; for any failing check, record the reason.

## Out of scope

Hosted verification (needs an authorized push, outside M0 acceptance); evaluations in CI; secrets of any kind; deploy or release automation; branch protection; expanding CI beyond measured fast checks; fixing failing checks.

## Inspect

`docs/specs/m0-system-audit.md` A6; ticket 02 `## Findings`; `backend/pyproject.toml`, `frontend/package.json`, `AGENTS.md` ("Development"), `CODING_STANDARDS.md` ("Checks a change should pass"), `docs/GIT_WORKFLOW.md`.

## Deliverables

`.github/workflows/<name>.yml`; `## Findings` in this ticket with the local run results, the choice rationale tied to ticket 02 numbers, and the cited cost answer.

## Needs

No paid APIs, no live infrastructure, no GitHub access beyond reading public documentation. Local Docker only if the manual full-suite job is included and checked.

- [ ] Exactly one workflow file exists; it references no secrets or API keys and contains no evaluation step.
- [ ] The selection of checks is justified by ticket 02's measured dependency groups and timings.
- [ ] Every command in the workflow was run locally on the audited commit; results recorded; each failing check has a recorded reason.
- [ ] The CI cost question is answered with a citation (URL and date).
- [ ] No hosted verification was attempted and nothing was pushed.
- [ ] The only files changed are the workflow and this ticket.

## Comments

# 08: Lightweight CI foundation (A6, part 2)

**Spec:** docs/specs/m0-system-audit.md
**What to build:** A single small, free GitHub Actions workflow that runs the fast checks chosen from ticket 02's measurements, with no paid key and no evaluation step, verified by running its commands locally on the audited commit.
**Blocked by:** 02.
**Status:** ready-for-agent
**Progress:** resolved

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

- [x] Exactly one workflow file exists; it references no secrets or API keys and contains no evaluation step.
- [x] The selection of checks is justified by ticket 02's measured dependency groups and timings.
- [x] Every command in the workflow was run locally on the audited commit (except the `apt-get` Tesseract install, already present on this Mac, and the key guard, run separately as a shell snippet); results recorded; each failing check has a recorded reason.
- [x] The CI cost question is answered with a citation (URL and date).
- [x] No hosted verification was attempted and nothing was pushed.
- [x] The only files changed are the workflow and this ticket.

## Findings

Executed 2026-11-21 on audited commit `e7b85d8` (branch `feature/v2-state-performance`). The only new file is `.github/workflows/ci.yml`. Nothing was pushed and no hosted run was attempted.

### The workflow

One file, `.github/workflows/ci.yml`, triggers: push to `main`, pull request, manual (`workflow_dispatch`). `permissions: contents: read`, no secrets, no `OPENAI_API_KEY`, no deploy, no RAG evaluation. Two jobs on `ubuntu-latest`:

| Job | Steps |
|---|---|
| `backend` | guard that fails if `OPENAI_API_KEY` is set (ticket 02 F1); install `tesseract-ocr` (same package as `backend/Dockerfile`, so the OCR integration test runs); `uv sync --dev --frozen`; `ruff check app tests`; `ruff format --check app tests`; `mypy app`; `basedpyright app`; `pytest -q -rs` with 4 deselects |
| `frontend` | Node 22 (same major as `frontend/Dockerfile`); `npm ci`; `npm test`; `npm run lint`; `npm run build` |

Action versions are the latest majors read from the GitHub API on 2026-11-21: `actions/checkout@v7`, `astral-sh/setup-uv@v10`, `actions/setup-node@v7`. They are tags, not commit SHAs (a tag can move; pinning by SHA is a hardening step left out as outside "measured fast checks").

### Why these checks (ticket 02 numbers)

- Included: everything ticket 02 measured as container-free and fast: ruff, format, mypy (all clean), the container-free backend tests (53 s locally), frontend test 50 s, lint 3 s (ticket 02, warm cache; 9 s in the clean-export run below), build 19 s. Run in parallel here, the backend steps took about 3 minutes in total (mostly mypy and pytest) and the frontend steps about 2.3 minutes (mostly `npm ci` and `npm test`).
- `basedpyright` is scoped to `app` because `app tests` has the 48-error baseline from ticket 02 (all in `tests/`, not a target).
- **Not included:** the 753 PostgreSQL/Qdrant tests (about 21 min summed, about 24 min whole suite, ticket 02). That is too slow for every commit, and it needs containers with specific variables and ports (including a hard-coded Qdrant port, ticket 02 F2). **No manually triggered full-suite job was added**: it could not be verified locally without recreating the exact fixture environment, and the ticket allows leaving it out. The full suite stays a local checkpoint run.
- **What a green CI run does not prove:** the ownership, session, indexing-job and vector-isolation tests in `tests/security` are skipped (about 785 skips, reason "SESSION_TEST_DATABASE_URL must name ..."). `-rs` prints every skip reason in the job log so this is visible.

### Local run results

Method: `git archive e7b85d8` into an empty directory, so no `backend/.env`, no `node_modules`, no `.venv`, no git-ignored public PDFs and no git history, which is what a fresh runner sees. `OPENAI_API_KEY` and the three container variables unset. Commands run exactly as in the workflow (Tesseract was already installed on this Mac; the apt step itself is unrun).

| Command | Result | Time |
|---|---|---|
| `uv sync --dev --frozen` | pass | 4 s (uv cache warm) |
| `ruff check app tests` | pass | 2 s |
| `ruff format --check app tests` | pass | <1 s |
| `mypy app` | pass | 25 s (cold in the clean directory) |
| `basedpyright app` | pass | 11 s |
| `pytest -q -rs` with 4 deselects | **2237 passed, 785 skipped, 4 deselected, 2 xfailed** | 36 s |
| `npm ci` | pass | 50 s |
| `npm test` | pass | 49 s |
| `npm run lint` | pass | 9 s |
| `npm run build` | pass (needs network for Google Fonts) | 30 s |

The counts differ from ticket 02 (2174 passed, 753 skipped) because tickets 06 and 07 added tests since; the run above is the current number.

### Failures found on the first clean-checkout run, and how the workflow handles them

The first run, without deselects, gave `4 failed, 2237 passed, 785 skipped, 2 xfailed`. Ticket 02's statement that the container-free subset works on a clean checkout was only true for one test; the four below pass on this Mac only because of local state. Not fixed (fixing checks is out of scope); the workflow deselects them and the reasons are:

| Test | Reason it fails on a clean checkout |
|---|---|
| `tests/evaluation/test_agent_smoke.py::test_frozen_sixteen_case_gold_and_identities` | runs `git show 8eb48e32...:backend/app/agents/tool_rag/__init__.py`. That commit is **not an ancestor of HEAD**; it is only on `origin/demo/public-demo` and in this clone's object store. Full-history checkout would not help. |
| `tests/evaluation/test_cli_corpus.py::test_messy_documents_are_not_in_the_default_corpus_and_join_on_request` | needs the git-ignored `public/nist_sp800_145.pdf` (`FileNotFoundError`) |
| `tests/evaluation/test_cli_corpus.py::test_the_messy_question_set_is_only_valid_with_the_messy_documents` | same |
| `tests/evaluation/test_cli_corpus.py::test_files_to_check_skips_public_files_nobody_references` | same |

These are unit tests of the evaluation tooling, not RAG evaluations: no model is called. The other evaluation-folder tests still run. Follow-up for the Owner (not done here): make these four skip when their inputs are absent, as `test_public_cases_validate_when_the_public_documents_are_downloaded` already does, then drop the deselects. The `docs/DECISIONS.md` / `AGENTS.md` wording "skips on a clean checkout" applies to that one test only.

### Do Actions minutes cost anything for this repository?

**No, as long as the repository stays public and uses standard runners.** `gh repo view` on 2026-11-21 reports `mahad816/DriveMind_AI` as PUBLIC. GitHub's billing page states: "The following usage remains free independently and does not reduce the included compute usage: Standard GitHub-hosted runners in public repositories ... Larger runners are billed for public repositories." The workflow uses `ubuntu-latest`, a standard runner.

Source: https://docs.github.com/en/billing/concepts/product-billing/github-actions (read 2026-11-21).

If the repository were made private, usage would count against the plan's included compute (same page, plan table: GitHub Free, "Included compute usage (per month)" $12 USD, expressed as money, not minutes), and cache and artifact storage have separate limits.

### Caveats

- Hosted behaviour is unverified: runner timing, the `apt-get` Tesseract step, `setup-uv` cache and the action major versions have not run on GitHub. The first hosted run (after the Owner authorizes a push) may need small fixes.
- `npm run build` fetches fonts from Google Fonts; a network blip fails the frontend job.
- Tags (not SHAs) for third-party actions.
- Local timings come from a Mac with warm caches; the 15-minute job timeouts are generous guesses.

## Comments

- 2026-11-21: implemented by the agent. Workflow verified locally on a clean export of `e7b85d8`; four tests deselected with recorded reasons (see Findings). Not pushed.

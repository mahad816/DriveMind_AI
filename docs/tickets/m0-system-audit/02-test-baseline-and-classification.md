# 02: Local test baseline and test-dependency classification (A6, part 1)

**Spec:** docs/specs/m0-system-audit.md
**What to build:** The Owner has a recorded, trustworthy result of every quality check on the current HEAD (counts, duration, skipped tests with reasons, failures), the tests grouped by what they need (none, containers, network, paid API) with measured times, and a feasibility note for the five evaluation-only known issues. This is the evidence ticket 08 uses to pick CI checks.
**Blocked by:** None (can start immediately). Needs local Docker.
**Status:** ready-for-agent
**Progress:** resolved

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

- [x] Baseline records commit, passed/failed/skipped counts, duration, skipped test names with reasons, and failures for backend and frontend, and the result of all four static checks (with scope if not project-wide clean).
- [x] `AGENTS.md` "Latest recorded verification" matches the recorded run and states the commit it was run on.
- [x] Tests are grouped by dependency (none / containers / network / paid API) with a measured time per group, and the method used is stated.
- [x] Each of KI-022, -027, -028, -029, -030 has a recorded feasible/not-feasible decision with reason; registry wording matches.
- [x] Every test added is deterministic, uses no paid call, and fails today for the reason in its registry entry (expected-failure) or is not added. No placeholder tests.
- [x] Only `AGENTS.md`, `docs/KNOWN_ISSUES.md`, new known-issue tests and this ticket changed; no application code changed.

## Findings

Run 2026-11-21 on commit `7197af4` (branch `feature/v2-state-performance`, tree clean before the run). Machine: macOS arm64, 8 CPUs, Docker with 4 GB. Tools: Python 3.12.13, uv 0.11.26, Node 26.13.1, ruff 0.15.20, mypy 2.1.0, basedpyright 1.39.9. Containers: a **new, separate** pair (PostgreSQL 18.7 on tmpfs, Qdrant 1.18.2), bound to loopback only and removed afterwards. The existing evaluation containers (`drivemind-test-pg`, `drivemind-test-qdrant`, which hold the `drivemind_eval_v2` store) were not used or touched. `backend/.env` holds a real `OPENAI_API_KEY`, so the first full run exported a dummy key (see finding F1). Label for every item below: **Verified** by the command named, unless stated.

### Baseline

| Check | Result | Time |
|---|---|---|
| Backend full suite (2927 tests) | **2923 passed, 1 failed, 3 skipped** (explained below; all 2927 pass in the right environment) | 24 min 9 s |
| `ruff check app tests` | clean | <1 s (cached) |
| `ruff format --check app tests` | clean, 340 files at the time | <1 s |
| `mypy app` | clean, 183 files | 1 s (incremental cache; not a cold run) |
| `basedpyright app tests` | **48 errors, 0 warnings, all in `tests/`** (9 files); `app/` has none | 29 s |
| Frontend `npm test` | 876 passed, 76 files, nothing skipped | 50 s |
| Frontend `npm run lint` | clean (`next lint` prints a deprecation notice for Next 16) | 3 s |
| Frontend `npm run build` | succeeded, 10 pages | 18.6 s |

basedpyright scope: clean on `app/` only. The 48 errors by file: `tests/streaming_preview.py` 10, `tests/agents/tool_rag/test_evidence_recovery.py` 10, `test_intent_gate.py` 8, `tests/test_chat_streaming.py` 6, `tests/services/test_conversation_failure_diagnostics.py` 5, `tests/test_chat_streaming_api.py` 3, `test_mixed_grounding.py` 3, `test_grounding_policy.py` 2, `tests/security/test_google_session_postgres.py` 1. Rules: argument type 14, attribute access 12, call issue 9, function member access 6, optional member access 5, operator 2. This is the state `docs/HANDOFF_2026-11-21.md` section 5 already described ("not the whole project").

**The failure.** `tests/security/test_two_user_rag_end_to_end.py::test_http_graph_strategy_plans[Show only txt-False]`: a rewrite request reached the mocked model where the test asserts none. Cause: the graph rewrite node calls the model only when `settings.openai_api_key` is non-empty, and my run exported a dummy `OPENAI_API_KEY`. It failed 3 of 3 alone with the dummy key and passed (3 of 3 cases) with the variable unset. No application code differs from the previous recorded run (`git diff b0cc552 HEAD -- backend/app` is empty), so this is a test-environment sensitivity, not a regression (F1).

**The 3 skips** (they explain "which 3 were not recorded" in the handoff): `tests/security/test_conversation_chat.py::test_real_rag_modes_owner_filtered_qdrant_and_citation_publication[linear]`, `[graph]`, `[tool]`. The test body requires `CONVERSATION_TEST_QDRANT_URL == "http://127.0.0.1:61448"` exactly and otherwise skips with "Requires the explicitly disposable S2B Qdrant endpoint". I had set another port. With a disposable Qdrant on that port, `tests/security/test_conversation_chat.py` ran 32 passed, 0 skipped (57 s).

**How the baseline is recorded (Owner decision, 2026-11-21).** Accepted as a *qualified* baseline; the 24-minute suite is not repeated. Two kinds of result are kept apart:
- **Full run, as measured:** `2923 passed, 1 failed, 3 skipped`, 24 min 9 s, commit `7197af4`.
- **Focused re-runs on the same commit:** `test_http_graph_strategy_plans` with `OPENAI_API_KEY` not exported: 3 passed (3 of 3 failed with a dummy key exported); `tests/security/test_conversation_chat.py` with a disposable Qdrant at `http://127.0.0.1:61448`: 32 passed, 0 skipped.

So all 2927 tests pass in the right environment, shown by the full run plus those two re-runs, not by one clean 2927-test run. The run took 7 min longer than the previous recorded 17 min 24 s; I did not investigate why (a different PostgreSQL major version and a fresh Qdrant are possible factors, unmeasured).

### Tests grouped by dependency

Method: (1) a run with no container variables set (`SESSION_TEST_DATABASE_URL`, `QDRANT_TEST_URL`, `CONVERSATION_TEST_QDRANT_URL` unset) shows which tests skip themselves: those need containers; (2) the per-test times come from the JUnit report of the full run; (3) the network and paid-API groups are decided by reading every test file that builds an OpenAI or Google client, and by the runs themselves. No test behaviour was changed.

| Group | Tests | Time | Notes |
|---|---|---|---|
| Needs nothing | 2174 | 203 s summed; 3 min 35 s wall run alone | includes one 155 s test, below |
| – the same without that one test | 2173 | 48 s summed; **53 s wall** | the fast subset for CI |
| Needs PostgreSQL (some also Qdrant) | 753, all under `tests/security` | 1243 s summed (about 21 min) | 14 of the files also use Qdrant (listed below) |
| Needs network | 0 | – | |
| Needs a paid API | 0 | – | |
| Skipped in the full run | 3 | – | the S2B Qdrant tests above |

- **How the counts were obtained, and one wrinkle.** The counts are the skip counts of the no-container run (753 skipped, 2174 passed, total 2927 = the full run). Times come from the full run's per-test JUnit report matched by test name; three tests carry a random UUID in their parametrize id (`test_payload_defects[...]`, `test_malformed_credentials_fail_deterministically[...]`, `test_demo_browsing_never_falls_back[...]`), so their names differ between runs and cannot be matched. One of them is a PostgreSQL test (1.0 s), which is why a name-matched count first gave 752/2175; it is counted in the PostgreSQL group above and its 1.0 s is included in that group's time.
- The 155 s test is `tests/evaluation/test_rag_eval_dataset.py::test_public_cases_validate_when_the_public_documents_are_downloaded`. It reads the git-ignored public PDFs under `evaluation/corpus/public/`, which exist on this Mac, and **skips on a clean checkout** (so it is not part of a CI run, but it is most of the local container-free time).
- Files that use Qdrant as well as PostgreSQL: `test_conversation_chat`, `test_indexing_admission_closure`, `test_indexing_attempts`, `test_indexing_outage_recovery`, `test_normal_indexing_runtime`, `test_indexing_leases`, `test_indexing_recovery`, `test_indexing_lifecycle`, `test_qdrant_tenant_io`, `test_qdrant_tenant_repair`, `test_indexing_worker`, `test_worker_vector_reconciliation`, `test_qdrant_tenant_inventory`, `test_two_user_rag_end_to_end` (static: they reference a Qdrant variable or fixture; the split of time between PostgreSQL-only and PostgreSQL-plus-Qdrant was not measured).
- Eight of those files contain both container-free and container tests, so the grouping is by test, not by file.
- Slowest tests: the 155 s corpus test; `test_qdrant_tenant_repair` (two CLI tests, 25 s and 17 s); `test_normal_indexing_runtime` lifespan test, 19 s. Everything else is under 15 s.
- "No network, no paid API" is **Verified** for: every `AsyncOpenAI` construction in `tests/` uses `httpx.MockTransport` or is patched (`test_chat_streaming.py`, `test_two_user_rag_end_to_end.py`, `test_rag_eval_score.py`); the Google Drive client tests use `MagicMock`. A run with the OpenAI base URL pointed at a closed local port (container-free subset, 2173 passed) produced no connection failure. This does not prove that no test swallows a connection error. The frontend build is the one step that touches the network: `next/font/google` downloads the Geist fonts (public static assets, no credentials).

### Hand-off to ticket 08 (CI), measured, no workflow written here

- Static checks: `ruff check app tests`, `ruff format --check app tests`, `mypy app` (all clean). `basedpyright app` is clean; `basedpyright app tests` is not: **the 48 errors in `tests/` are the preserved baseline** (not fixed here, not a target), so a CI gate must be scoped to `app` or accept exactly that baseline.
- Backend tests without containers: `uv run pytest -q` with no container variables and no `OPENAI_API_KEY`: **53 s** (here with the 155 s corpus test `--deselect`ed; on a clean checkout it skips by itself).
- Frontend: `npm test` 50 s, `npm run lint` 3 s, `npm run build` 19 s (needs network for fonts).
- The full container suite is about 24 min; it needs PostgreSQL, Qdrant on two ports, and no exported `OPENAI_API_KEY`.
- **`OPENAI_API_KEY` (F1 below):** the CI job and any local runner must leave it unset or the full suite reports a false failure. Ticket 08 should state this next to the commands and, if it wants a guard, add a step that fails early when the variable is present.
- **Limits of the fast subset (what it does not prove):**
  - It runs none of the 753 PostgreSQL/Qdrant tests, which include the ownership, session, indexing-job and vector-isolation tests in `tests/security` (judged from file names). A green fast job says nothing about those; they need the container suite at checkpoints.
  - 753 tests skip silently in it (reason "SESSION_TEST_DATABASE_URL must name an isolated local test database"); a CI summary should show the skip count so a green run is not read as "everything passed".
  - The 53 s figure is from a Mac with local dependencies; a GitHub runner's time and cache behaviour are unmeasured. `mypy` was timed on its incremental cache (1 s), not cold.
  - The new KI-022 test is in the skipped group; the KI-030 test and the other known-issue tests run in the subset.
  - `npm run build` needs network for Google Fonts and was run once.

### Known-issue feasibility

| Issue | Deterministic test without a paid model? | Decision |
|---|---|---|
| KI-022 | **Yes, for the keyword half** | Added `tests/known_issues/test_ki022_keyword_all_words.py`: against PostgreSQL, keyword retrieval returns 0 hits for the user's question and for the agent's rewrite although the handbook sentence is indexed; a passing guard shows the short query finds it. The agent's own query writing needs a model and stays an evaluation case. |
| KI-027 | **No** | A throwaway probe (not kept in the repository; method: the 22 files of `backend/evaluation/corpus/synthetic/` chunked with `chunk_text`, loaded into an isolated PostgreSQL schema with `to_tsvector('english', text)`, queried through `KeywordRetriever.retrieve`, public PDFs not loaded) showed keyword retrieval finds `incident_report_2026_q2.txt` for the `id01` question and for `INC-204 root cause`, so the loss is not in keyword search. The remaining layers need real embeddings; invented vectors would assume the unmeasured cause. Stays an evaluation case. |
| KI-028 | **No** | The defect is a model's choice to answer from a similar document. A scripted model would only test a check that does not exist yet. Stays an evaluation case. |
| KI-029 | **No** | Reading the table is already deterministic and tested; the wrong sum is the model's arithmetic. Stays an evaluation case. Unit tests belong to a calculation tool if one is built. |
| KI-030 | **Yes, for the chunking cause (a chunk-level proxy)** | Added `tests/known_issues/test_ki030_small_deck_chunking.py`: the generated 560-character board deck becomes 1 chunk, so the chunk that holds the answer ("Signed 6 new clinics in Q3") also holds the unrelated hiring decision (and the reverse). The test asserts only that every fact stays in some chunk and that a chunk holding one slide's fact does not hold an unrelated slide's fact; no chunk count, size, boundary or heading rule. A passing guard in the same file shows the existing chunker with a 200-character target already meets the expectation, so no particular algorithm is asked for. Assumption stated in the test and the registry: the fix is in chunking (the registry's own direction); a fix that keeps the deck whole and improves ranking would replace this test. Whether the single chunk loses in vector search needs embeddings and stays the `px03` case. |

Each added expected-failure test was run with `--runxfail` against the disposable PostgreSQL and fails with an `AssertionError` for the stated reason: KI-022 `assert 'employee_handbook.txt' in []` (2 cases); KI-030 `1 of 1 chunks holding 'Signed 6 new clinics in Q3' also hold 'approve hiring a second QA engineer'` (and the reverse). Results of the `tests/known_issues` folder after the additions: **19 passed, 4 xfailed** with PostgreSQL; **18 passed, 3 skipped (KI-022, needs PostgreSQL), 2 xfailed** without containers. `docs/KNOWN_ISSUES.md` wording was corrected for all five entries.

### Other findings

- **F1. A test fails when `OPENAI_API_KEY` is exported (for ticket 08).** `test_http_graph_strategy_plans[Show only txt-False]` assumes the variable is absent: the graph rewrite node calls the model when `settings.openai_api_key` is non-empty, and the test asserts that no model request happens. 3 of 3 failures with a dummy key exported, 3 of 3 passes without it, no application change in between. A developer shell or a CI secret with the key set would fail it. Not fixed here (existing tests are out of scope); recorded in the hand-off to ticket 08 above.
- **F2. A hard-coded port.** The 3 `test_conversation_chat` tests only run against `http://127.0.0.1:61448`, so they were silently skipped on every run that used any other port.
- **F3.** `infra/docker-compose.yml` uses `postgres:16-alpine`, the existing test container is PostgreSQL 18; this run used 18.7. What Railway runs is Unverified (ticket 01).
- Working tree check at the end: only `AGENTS.md`, `docs/KNOWN_ISSUES.md`, this ticket and the two new test files changed.

## Comments

- 2026-11-21: executed by the agent. Owner decisions applied: qualified backend baseline accepted without repeating the full suite (full run and focused re-runs recorded separately); KI-030 test kept but reworked to assert discoverability, not a chunking algorithm; the `OPENAI_API_KEY` issue recorded for ticket 08 in the hand-off above (ticket 08's own file was not edited, per the instruction not to change other M0 tickets); the 48 basedpyright errors and the limits of the fast subset kept as documented.
- 2026-11-21: `/code-review` close-out (two fresh sub-agent contexts, Standards against `CODING_STANDARDS.md`, Spec against this ticket and `docs/specs/m0-system-audit.md`). No security risk and no scope change found. Fixed:
  - **Standards, hard:** `ruff format --check` failed on the reworked KI-030 test (two lines over 100 characters); formatted, now clean over 342 files.
  - **Spec, wrong numbers:** the dependency table disagreed with `AGENTS.md` (752/2175 vs 753/2174). Cause: three tests have random UUIDs in their parametrize ids and cannot be matched between runs. Corrected to 753 PostgreSQL / 2174 container-free (2173 without the corpus test); method and wrinkle recorded above.
  - **Spec, KI-030:** the docstring overstated "only what can be observed" and the three-chunker check lived nowhere in the repo. The test now says it is a chunk-level proxy that assumes a chunking fix, and a passing guard in the file shows a plain 200-character split meets the expectation (so no algorithm is prescribed).
  - **Spec, missing record:** the `tests/known_issues` result is now in the Findings (19 passed + 4 xfailed with PostgreSQL; 18 passed + 3 skipped + 2 xfailed without). The KI-022 expected failures were re-run against PostgreSQL and fail with `assert 'employee_handbook.txt' in []`.
  - **Spec, wording:** removed the contradiction between "qualified baseline" and "not covered: a single clean full run"; recorded the KI-027 probe method (the throwaway script is not kept).
  - Not changed, on purpose: the fixture import from `tests.security.conftest` with two suppression comments, the fixture name `sessions` and the seeding code that resembles `test_keyword_name_terms_pg.py` (sharing it would mean editing existing tests, out of scope; the new file sits in `tests/known_issues/` so the registry's run command finds it); import order in `tests/known_issues` (not part of the repo's ruff rules, prior art is the same).
- 2026-11-21: Owner approved the decisions and the commit. Not pushed.

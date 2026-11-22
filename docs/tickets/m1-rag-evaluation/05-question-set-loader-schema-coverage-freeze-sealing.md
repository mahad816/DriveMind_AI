# 05: Question set: loader, schema, coverage, freeze and sealing

**Spec:** docs/specs/m1-rag-evaluation.md
**What to build:** One frozen question set with named roles and the machinery that keeps it honest. The existing 201 cases load unchanged, with the "test" cases relabelled as the regression pool; the case schema gains what the spec requires; a free coverage report shows what is still missing; a freeze mechanism makes silent edits fail a test; and reports show held-out cases as aggregates only. No cases are written here.
**Blocked by:** 04.
**Status:** ready-for-agent
**Progress:** resolved (2026-11-22)

## Scope

- **Loader and pools.** Merge the four existing case files and the new ones; map the existing development split to the development pool and the existing test split to the regression pool at load time (existing files are not edited); support a held-out split. Reports always show the pool.
- **Schema v3**, validated by the existing validator (kept and extended): a Critical-failure tag; format tags; question-type tags; provenance (author session and date, never a person's name); the behaviour "clarify" (the correct reply is one short clarifying question; add its expectation to the refusal judge's table and its pass rule); histories checked against the production bound (at most six prior messages and 6000 characters, the bound stated once and pinned by a test).
- **Coverage report.** A free command printing counts per pool against the spec's minimums (total, unanswerable plus partial plus false-premise, Critical, multi-file, table, calculation, identifier, follow-up, ambiguous, injection with distinct documents and formats, each promised format) and exiting non-zero when a full-set minimum is unmet.
- **Freeze and amendment.** A freeze manifest with the SHA-256 of every frozen case file, the corpus version id and the pool mapping; a free test that fails when a frozen file changes without an entry in an amendment log (date, case id, reason, checksums before and after). The earlier corrections (`vi06` replaced by `vi08`, the `id10` gold) are entered from the results history.
- **Sealing, enforced by files.** The held-out case file is located by an environment variable and lives outside the working tree; the repository holds its checksum, counts per gate group and the amendment log. The freeze test verifies the checksum when the file is present and skips otherwise. The default selection of cases ("all") excludes held-out; it runs only when selected by name, once per checkpoint. Per-case held-out rows are written outside the repository and without reply text. The summariser, logs and committed-baseline writer show the held-out pool as a total plus the gate groups and suppress any cell under ten cases. A free test (on a fabricated held-out file) fails if a committed output contains a held-out case id or a small cell. To diagnose a held-out case, move it to the development pool with an amendment-log entry; it stays in earlier checkpoints' denominators. No reserve and no reveal flag exist. The validator also checks that anchors are unique across near-duplicate and superseded documents and generates sibling-value forbidden claims (other values the same field takes elsewhere in the corpus) so a verbose reply that lists many values does not pass.

## Out of scope

Writing any case (tickets 06 and 07), running the system, scoring changes (ticket 03), changes to the existing case files, the application package.

## Inspect

`backend/evaluation/rag_eval/dataset.py`, `judge.py`, `runner.py`, `score.py`; the four `rag_v2_*` dataset files; `backend/tests/evaluation/test_rag_eval_dataset.py`, `test_dataset.py`; `docs/EVALUATION_RESULTS.md` ("What the first run got wrong", the `vi06` and `id10` corrections); `GLOSSARY.md`.

## Deliverables

Loader, validator extension, coverage command, freeze manifest and amendment log, sealing in the writers, free tests, `## Findings` with the current coverage table.

## Needs

No paid API, no key, no network. The validator reads extracted text from the corpus through the product's extractors (free).

- [x] Loading all pools gives 201 existing cases with the original ids, 120 development, 81 regression, nothing relabelled on disk; ids are unique across files.
- [x] A fabricated new case passes or fails the validator for each rule (anchor, forbidden claim, history bound, required fields, "clarify" behaviour judged by its expectation text).
- [x] The coverage report prints a table and exits non-zero on a shortfall; the shortfalls against the current pools are recorded in Findings.
- [x] The freeze test fails on a changed frozen file and passes after an amendment entry; the first amendment entries exist.
- [x] A fabricated held-out result never reaches a summary, log or committed-baseline output except as aggregates (test).
- [x] `git diff -- backend/app` is empty; touched evaluation files pass `ruff check`, `ruff format --check` and `mypy`; the container-free evaluation tests pass.

## Findings

Written 2026-11-22 on `f2fd647` plus this ticket's changes. Every number below was produced by a command or test run in this session; no provider, key, network, Railway or production data was used. Nothing here measures retrieval or answer quality: it is bookkeeping and validation of the question set.

### What was built

| Piece | Where |
|---|---|
| Loader and pools (`development`, `regression`, `held_out` assigned at load time; held-out file located by `DRIVEMIND_EVAL_HELDOUT_FILE`, refused inside the repository; `select` keeps `all` free of held-out); `pools validate` command | `backend/evaluation/rag_eval/pools.py` |
| Schema v3 rules: provenance, tag vocabulary checked against the case's own fields, format tags, Critical kind (the four glossary kinds), injection document, `clarify` rules, history bound (6 messages, 6000 characters, stated once), anchors unique across near-duplicate and superseded documents, sibling-value forbidden claims | `schema_v3.py`, called from `dataset.validate` (kept, extended) |
| `clarify` behaviour: expectation text in the refusal judge's table; pass rule (`?` required in code, judge for the rest, no citation and no guessed reading as for small talk) | `judge.py`, `runner.py` |
| Coverage command (counts per pool against the spec minimums, exit 1 on a whole-set shortfall) | `coverage.py` |
| Freeze manifest, amendment log, `check`, `amend`, `add`, `seal-held-out` | `freeze.py`, `datasets/m1_freeze.json`, `datasets/m1_amendments.json` |
| Sealing: aggregate-only summary (cells under ten suppressed), row reducer, committed-baseline view, leak and small-cell checks; `score.summarise` applies it to any held-out row; the `run` command takes `--split held_out` by name only and writes reduced rows beside the sealed file | `sealing.py`, `score.py`, `cli.py` |
| 87 free tests | `tests/evaluation/test_question_set.py` (50), `test_question_freeze.py` (18), `test_sealed_reporting.py` (19) |
| Guide section | `docs/guides/EVALUATION.md` |

No existing case file was edited; `git diff -- backend/app` is empty.

### Coverage today (`uv run python -m evaluation.rag_eval.coverage`, exit 1)

| Requirement | Min (all) | Min (held-out) | Dev | Regression | Held-out | All |
|---|---:|---:|---:|---:|---:|---:|
| Cases in total | 300 | 100 | 120 | 81 | 0 | **201** |
| Unanswerable + partial + false premise | 80 | 30 | 28 | 24 | 0 | **52** |
| Tagged Critical failure | 30 | 10 | 0 | 0 | 0 | **0** |
| Multi-file (all listed files must be cited) | 25 | 8 | 5 | 3 | 0 | **8** |
| Table lookup | 25 | | 12 | 9 | 0 | **21** |
| Calculation | 20 | 6 | 4 | 9 | 0 | **13** |
| Identifier | 25 | 6 | 8 | 7 | 0 | **15** |
| Follow-up (history inside the bound) | 15 | 5 | 3 | 2 | 0 | **5** |
| Ambiguous (clarify) | 10 | 4 | 0 | 0 | 0 | **0** |
| Prompt injection (documents / formats) | 10 | 4 | 3 | 1 | 0 | **4** (2 documents, 1 format; need 3 and 2) |
| Evidence in DOCX / XLSX / PPTX / text PDF | 8 each | 3 | | | 0 | **7 / 5 / 8 / 22** |
| Evidence in Markdown / CSV / TXT | 8 each | 3 | | | 0 | **0 / 0 / 120** |

Shortfalls to fill (whole set): 99 cases, 28 non-answer, 30 Critical, 17 multi-file, 4 table, 7 calculation, 10 identifier, 10 follow-up, 10 ambiguous, 6 injection plus 1 more document and 1 more format, 1 DOCX, 3 XLSX, 8 Markdown, 8 CSV. Only PPTX, text PDF and TXT meet their minimum. The held-out pool does not exist yet (ticket 07). All 201 existing cases validate against the frozen corpus (`pools validate --with-public`, 0 problems, about 90 s including the public PDFs).

### How it was verified

- **Loading:** 201 cases, original ids in file order, unique, 120 development and 81 regression; a test shows no file has a `pool` key and only `dev`/`test` splits (nothing relabelled on disk).
- **Each validator rule has a failing and a passing case** on small fabricated corpora (provenance, tags, formats, Critical kind, injection document, held-out needs schema 3, anchor uniqueness, sibling values, history bound at 6/6000 and 7/6001, nine malformed `clarify` variants), and the same rules run on the real frozen corpus (a superseded-policy case needs the old value forbidden; a quote shared by both policy versions is rejected; the 2026 tariff case needs the 2025 and other routes' rates forbidden; a CSV column gives the other depots).
- **History bound pinned to production:** a test drives the agent's own check with 7 messages and 6001 characters (refused) and 6 messages and 6000 characters (not refused), so the evaluation constants cannot drift from the application.
- **Freeze:** a silent edit fails; editing the manifest to match still fails; `amend` makes it pass; a second silent edit fails again; deleting a log entry fails; a broken history chain, a malformed entry, a wrong corpus version or pool mapping, an unlisted case file and a missing file each fail. The first amendment entries (five, from git and `docs/EVALUATION_RESULTS.md`): `ag05`/`pb05`/`td01` sources, the 31 trap-set additions, the three shortened anchors, `vi06` replaced by `vi08`, and the `id10` gold.
- **Sealing:** fabricated 30-case held-out file, outside the repository. The summariser, the committed view, the printed output of `cli.run`, the written result file and the freeze manifest contain no held-out id, no reply, question, query or snippet text, and no cell under ten; a group of nine is suppressed, a group of ten is shown, a strict rate resting on five decided rows is suppressed. The leak and small-cell checks are shown to detect a deliberately unsafe output.
- **Checks can fail:** 15 deliberate breakages of the safeguards (reply kept in reduced rows, cell suppression removed, held-out branch in the summariser removed, `all` including held-out, repository-path refusal removed, each of four validator rules, the history constant, freeze checksum and chain checks, the CLI probe refusal, the `clarify` pass rule, sibling requirement) were each caught by the new tests; every file was restored afterwards.
- **Static and regression:** `ruff check` and `ruff format --check` clean on the 13 touched files; `mypy` clean on the 10 evaluation modules; `basedpyright` 0 errors on the three new test files; `env -u OPENAI_API_KEY uv run pytest tests/evaluation -q`: 548 passed, 4 skipped (the 463 earlier tests plus 85 new; the 4 skips are 2 earlier ones plus the two sealed-file tests, which skip on a machine without the sealed file).

### Findings that change the plan

1. **True multi-file count is 8, not 16.** The spec's audit (A13) counted every case listing two or more files. Eight of them accept either file (`citation_mode: any`), such as `id10`, so one file answers them. Coverage now counts only cases that must cite all their files; the shortfall is 17, not 9.
2. **Two older cases rest on anchors that occur in two documents:** `sv05` and `tr15` (near-duplicate synthetic documents). They are frozen and exempt from the v3 rule. A chunk-level citation check on them cannot tell the two documents apart; read their citation result with that in mind.
3. **The `id10` correction cannot be given a full "before" checksum.** The identifier file was first committed already corrected (commit `fefb0a9`); the pre-correction checksum exists only as the prefix `1d9f4f05` in `docs/EVALUATION_RESULTS.md`, recorded as such, not completed.

### Caveats, limits and what was not tested

- **No cases were written.** The ticket says so; tickets 06 and 07 write them. The session's title and prompt said "Evaluation Cases Implementation"; this ticket was followed, so coverage is SHORT everywhere it is short (exit code 1 is the correct state).
- **Dataset correctness is not retrieval or answer quality.** Nothing here ran the system. The `clarify` judge expectation and pass rule were exercised with a stub judge only; whether the real judge applies it correctly is for ticket 10, with the human labels.
- **Held-out run not exercised end to end.** The `--split held_out` path was driven with a stubbed pipeline (no store, no provider). `cli.corpus_files()` does not yet include the v1 and Google files, so a real held-out run (or any run on v1 cases) fails validation until ticket 08 wires the new corpus into setup and run; this ticket did not change corpus selection.
- **The sealed file does not exist yet.** The checksum test and the committed-files id scan skip without it, and were shown to work only on fabricated files.
- **The freeze guards against accidents, not against someone who rewrites file, manifest and log together;** git history shows that. `history` entries are reconstructed from git diffs and commit messages, not from contemporaneous records.
- **The sibling generator is limited:** it reads markdown table columns (including the same-named column in other tables) and numbers, dates or identifiers that follow the same four words; it does not find sibling names in running prose and does not apply to computed cases. A table with a title row above the header yields no header-based cross-table siblings. An author reviews its output and may list values in `sibling_exempt`. It is a validation requirement, so the frozen case file shows the full forbidden list; nothing is merged silently at run time.
- **Suppression is per cell.** Groups overlap and a total is shown, so a reader holding several rates could infer something about a small cell by subtraction. The log names case ids by design (a moved case becomes a development case); the id scan therefore excludes it.
- **Provenance cannot detect a person's name,** only that the session id has the form `m<N>-<ticket>-...` in lower case.
- **Format and type counts are derived** from file suffixes, categories, `computed`, `history` and `tags`; a v3 case's tags are checked against its fields, an older case's types are inferred and may differ from how its author would label it.

## Comments

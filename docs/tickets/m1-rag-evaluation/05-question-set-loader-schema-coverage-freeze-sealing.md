# 05: Question set: loader, schema, coverage, freeze and sealing

**Spec:** docs/specs/m1-rag-evaluation.md
**What to build:** One frozen question set with named roles and the machinery that keeps it honest. The existing 201 cases load unchanged, with the "test" cases relabelled as the regression pool; the case schema gains what the spec requires; a free coverage report shows what is still missing; a freeze mechanism makes silent edits fail a test; and reports show held-out cases as aggregates only. No cases are written here.
**Blocked by:** 04.
**Status:** ready-for-agent
**Progress:** open

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

- [ ] Loading all pools gives 201 existing cases with the original ids, 120 development, 81 regression, nothing relabelled on disk; ids are unique across files.
- [ ] A fabricated new case passes or fails the validator for each rule (anchor, forbidden claim, history bound, required fields, "clarify" behaviour judged by its expectation text).
- [ ] The coverage report prints a table and exits non-zero on a shortfall; the shortfalls against the current pools are recorded in Findings.
- [ ] The freeze test fails on a changed frozen file and passes after an amendment entry; the first amendment entries exist.
- [ ] A fabricated held-out result never reaches a summary, log or committed-baseline output except as aggregates (test).
- [ ] `git diff -- backend/app` is empty; touched evaluation files pass `ruff check`, `ruff format --check` and `mypy`; the container-free evaluation tests pass.

## Comments

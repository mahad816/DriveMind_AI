# 04: Realistic corpus v1

**Spec:** docs/specs/m1-rag-evaluation.md
**What to build:** A frozen evaluation corpus that covers every promised format, includes longer multi-chunk documents with invented content, near-duplicate versions and several documents that carry embedded instructions, so later question sets can test the situations the product will meet. Nothing is embedded or sent to a provider here.
**Blocked by:** None (can start immediately; independent of tickets 01 to 03).
**Status:** ready-for-agent
**Progress:** resolved (2026-11-22)

## Scope

- Extend the deterministic fixture builder (fixed seeds, no timestamps, byte-identical output on every run) with an invented second company so facts cannot be known from a model's training data. Add at least:
  - DOCX (3 more: headings, bullet lists, a table, a long multi-section document);
  - XLSX (3: several sheets, a header row that is not row one, numeric columns, values a question can add up; cached values must be written so a reader sees numbers, not empty formula cells);
  - PPTX (3: bullets, text boxes, speaker notes, a short deck that becomes one chunk and a longer one);
  - text PDF (3: multi-page, a ruled table, two columns);
  - Markdown (3), CSV (3), TXT beyond the existing 22 where a format gap remains;
  - six longer invented documents, each at least four chunks long, so retrieval has real work to do;
  - two near-duplicate or superseded pairs and two same-name-entity cases across files;
  - at least three documents with embedded instructions in at least two formats (for example a table cell, slide notes, a PDF footer), each a different kind of instruction (reveal something, ignore the rules, cite a fake source).
- A corpus manifest with a version id, a digest of each file's extracted text (so a later reader change in M6 shows up as a visible change), a path, kind, source (generated, public, Google export), generator version, SHA-256 and, per file, at least three "canary" strings that must appear in its extracted text. The existing verify step covers the new kinds.
- **Extraction smoke test (free).** Every file extracts to non-empty text through the product's own extractors and contains its canary strings and, for the injection documents, the embedded instruction verbatim (so an attack is real). The test records chunk counts per file (the longer documents must produce several chunks). A reader regression then fails here, not in a paid run.
- **Google-exported fixtures: Owner action, not an agent action.** Write the steps (create three small synthetic files from provided text in a throwaway Google account, export through the normal menus, place them in a named folder) in `docs/guides/EVALUATION.md` and in this ticket's comments. The exports are checksum-pinned and added to the manifest as source "Google export". No Google API call by any agent. The Owner's export, or an explicit decision to decline it, is recorded **before this ticket resolves**, so the corpus version does not change after cases are written. Declining means "Google-exported files not covered" is recorded and ticket 11 proceeds on that basis.
- Document the licence of the public documents already used and confirm nothing new is fetched.

## Out of scope

Embedding or indexing the corpus (ticket 08), questions (tickets 05 to 07), extraction fidelity and capacity testing (M6), image OCR, scanned PDFs, Urdu-script documents, any change to the application's readers. A reader defect found here is registered with a reproducing test and handed to M6, not fixed.

## Inspect

`backend/evaluation/rag_eval/messy_fixtures.py`, `corpus.py`, `fetch_public.py`; `backend/evaluation/corpus/` manifests; `backend/tests/evaluation/test_messy_fixtures.py`, `test_cli_corpus.py`; `backend/app/ingestion/extractors/`; `docs/KNOWN_ISSUES.md` (KI-024, KI-029, KI-030); `docs/guides/EVALUATION.md`.

## Deliverables

Generator, fixtures (small, committed; the public PDFs stay uncommitted), manifest, smoke test, the guide section, `## Findings` with the format and chunk-count table and any reader defects found.

## Needs

No paid API, no key, no network beyond what the existing public-document fetch already does (and that is not run here). A free test per file kind.

- [x] The corpus contains every format listed with at least the stated counts, and building it twice gives byte-identical files and the same checksums as the manifest.
- [x] The manifest carries a version id; verify fails on any changed file; the smoke test passes for every file and reports chunk counts; the six long documents each produce at least four chunks.
- [x] At least three injection documents in at least two formats exist and their instructions are present in the extracted text.
- [x] Any reader problem found (a table row lost, a sheet skipped, notes ignored) is registered in `docs/KNOWN_ISSUES.md` with a strict expected-failure test, and the affected fixture keeps its canary on text that is read correctly so the corpus stays usable.
- [x] The Google-export steps are written; the Owner action is recorded as done, or as declined with "not covered" noted here and in the spec.
- [x] No private data, real names or secrets in any fixture (a pattern scan is run and recorded); `git diff -- backend/app` is empty; touched evaluation files pass `ruff check`, `ruff format --check` and `mypy`; the container-free evaluation tests pass.

## Findings

Written 2026-11-22. Evidence is from this session's own runs; the numbers below are what was measured, not estimates.

### What was built

| Piece | Where |
|---|---|
| Invented second company (Marrowdale Freight Cooperative): content descriptions, canaries, injection texts, Google source text | `backend/evaluation/rag_eval/corpus_v1_content.py` |
| Deterministic builders (DOCX, PPTX, XLSX with cached formula values, PDF with ruled tables and two columns), manifest, validators, CLI | `backend/evaluation/rag_eval/corpus_v1.py` |
| 19 committed fixtures (352 KB) and the manifest | `backend/evaluation/corpus/v1/`, `backend/evaluation/corpus/v1_manifest.json` |
| `v1_files()`, `.md`/`.csv` MIME entries and a `verify` that covers `v1`/`google` and says "is missing" | `backend/evaluation/rag_eval/corpus.py` (the only existing file changed) |
| 94 free tests | `tests/evaluation/test_corpus_v1.py` (18), `test_corpus_v1_manifest.py` (19), `test_corpus_v1_extraction.py` (57) |
| Guide section, Google steps, licences | `docs/guides/EVALUATION.md` |

The older generator `messy_fixtures.py` and its five files are unchanged (byte for byte). `git diff -- backend/app` is empty.

### Format and chunk-count table (product readers, default chunk size 3,500 with 500 overlap)

Corpus version `m1-corpus-v1-a605f90dc57b`; 49 committed files (22 synthetic, 5 messy, 19 v1, 3 Google exports) plus the 33 public PDFs referenced by checksum. (Before the exports were pinned: `m1-corpus-v1-652433e4d475`, 46 files.)

| File | Format | Characters | Chunks | What it exercises |
|---|---|---:|---:|---|
| `driver_handbook.docx` | docx | 13,264 | 5 | long; headings, bullets, a table; same-name entity (Sam Kerrigan) |
| `customs_and_border_guide.docx` | docx | 12,815 | 5 | long; table |
| `depot_safety_procedures.docx` | docx | 958 | 1 | bullets, table; **injection (reveal)** in a table cell |
| `fleet_register.xlsx` | xlsx | 1,993 | 1 | 3 sheets, header on row 3, numeric columns; same-name (Pioneer model) |
| `tariff_2026.xlsx` | xlsx | 876 | 1 | 3 sheets; **cached formula values**; supersedes `tariff_2025.csv` |
| `fuel_and_toll_costs_q3.xlsx` | xlsx | 1,410 | 1 | 3 sheets, sums; **injection (fake source)** in a cell |
| `depot_induction.pptx` | pptx | 369 | 1 | short deck (one chunk), notes, text box |
| `quarterly_ops_review.pptx` | pptx | 4,113 | 2 | longer deck, table, notes, text boxes; **injection (ignore rules)** in slide notes |
| `network_expansion_plan.pptx` | pptx | 715 | 1 | table, text box, notes |
| `cold_chain_operations_manual.pdf` | pdf | 11,353 | 5 | long; multi-page; five ruled tables |
| `marrowdale_annual_report_2025.pdf` | pdf | 11,540 | 5 | long; multi-page; borderless and ruled tables; two-column page |
| `member_newsletter_autumn_2026.pdf` | pdf | 970 | 1 | two columns; **injection (redirect the user)** in a paragraph |
| `fleet_maintenance_policy_v1.md` / `_v2.md` | md | 608 / 722 | 1 / 1 | superseded pair |
| `depot_systems_runbook.md` | md | 13,089 | 5 | long; code blocks |
| `tariff_2025.csv` | csv | 591 | 1 | superseded by `tariff_2026.xlsx`; same-name (Pioneer route) |
| `incident_log_2026.csv` | csv | 982 | 1 | numeric columns |
| `customer_accounts.csv` | csv | 687 | 1 | same-name (Sam Kerrigan the customer contact; Northgate Cold Stores versus the Northgate depot) |
| `cooperative_bylaws.txt` | txt | 10,904 | 5 | long |

Counts: DOCX 3, XLSX 3, PPTX 3, PDF 3, Markdown 3, CSV 3, TXT 1 (the 22 existing text files cover the rest of the TXT gap). Six long documents, each 5 chunks. Two superseded pairs (policy v1/v2; tariff CSV/XLSX). Two same-name cases (Sam Kerrigan; Pioneer), plus Northgate. Four injection documents, four formats, four kinds. All of it is invented and every depot, person, route and number is made up.

### Reader problems found: none that lose content

A test for each of the ticket's three examples passes on the current readers: **no table row is lost** (every row of every table in DOCX, PPTX, PDF, CSV and XLSX appears), **no sheet is skipped** (all nine sheets appear, and formula cells show their stored value), **speaker notes and text boxes are read** (every one of them). Nothing was added to `docs/KNOWN_ISSUES.md` and no expected-failure test was needed.

Observations, not defects (nothing is lost, so no registry entry):
1. `fleet_register.xlsx` has a title in row 1 and the header in row 3. The reader takes the first non-empty row as the header, so the title becomes the table header and the real header row reads as the first data row. Every value is present; only the header label is misplaced. Questions about this file should not depend on the header position being detected.
2. `depot_induction.pptx` (369 characters, four slides' worth of facts) is one chunk, the situation KI-030 already registers (`tests/known_issues/test_ki030_small_deck_chunking.py`). It is the intended "short deck" and a second place where KI-030 can show up in measurements.

### Mistakes made and caught while building (each now has a permanent check)

| Mistake | How it was caught | Permanent check |
|---|---|---|
| The seeded text generator drew random numbers in Python **set** order, which depends on the process hash seed, so three files had different bytes from one run to the next. | `corpus_v1 --check` reported "rebuilding gives different bytes". | `test_output_does_not_depend_on_the_process_hash_seed` (two subprocesses, seeds 1 and 2). Mutation-tested: restoring the old line makes it and the fresh-build test fail. |
| First draft's six "long" documents were 4,000 to 7,600 characters (2 or 3 chunks). | The `long` rule in the manifest check. | Rule `long` needs at least four chunks, in the manifest check and the extraction test. |
| The "longer" deck was one chunk, like the short one. | Chunk report. | Rules `short_deck` is one chunk and `long_deck` is more than one. |
| Invented facts contradicted each other (the quarterly table did not add to the 4,820,000 revenue; "Tollbridge is the only depot that grew every quarter" was false; per-depot staff, incidents and vehicles did not add to 214, 41 and 63; the ops review's per-depot tonnes disagreed with its own table; a fleet-register, cold-room-zone, alarm-delay, border-delay and incident-ID clash). | Reading the extracted text against the descriptions. | Arithmetic tests re-derive every total from the descriptions (`test_the_annual_report_adds_up`, `test_the_ops_review_tables_bullets_and_log_agree`, `test_other_cross_file_numbers_agree`). |
| `extract_all(root)` read from the real corpus whatever the root, which would have made every broken-copy test meaningless. | Review before writing the tests. | The broken-copy tests now read from the temporary root and the Google-pinning test passes only if that works. |
| The Google rota sample reused three customer contact names, creating unplanned same-name cases. | Review. | Names changed; none of the unplanned names remain. |

### Verification actually run (2026-11-22, `feature/v2-state-performance`, base `98799ce`)

| Check | Result |
|---|---|
| `tests/evaluation` before the change | 366 passed, 2 skipped |
| `tests/evaluation` plus the two reader-related known-issue files (`test_ki024_file_readers.py`, `test_ki030_small_deck_chunking.py`), final run | 481 passed, 2 skipped, 2 xfailed in 115 s. The 2 xfailed are the registered strict KI-030 markers, unchanged. |
| `messy_fixtures --check` (older generator) | "all fixtures reproduce byte for byte" |
| New tests | 94, all pass; they need no key, container, network or public PDF |
| `corpus_v1 --check` | `m1-corpus-v1-a605f90dc57b: 49 files, all checks pass` |
| `ruff check`, `ruff format --check` on the six touched Python files | clean |
| `mypy` on the three touched evaluation source files | clean (`messy_fixtures.py`, untouched, has 22 mypy errors before and after; the evaluation package is not in the CI mypy gate) |
| `basedpyright` on the three new test files | 0 errors (the preserved `tests/` baseline of 48 is not increased) |
| `git diff -- backend/app` | empty |
| Pattern scan (nine patterns: e-mail outside `.example`, phone, web address, API key or token, credential assignment, private key, bank account, card number, other company or personal names) on every fixture's description text, on the files read back by plain libraries, on document properties and on the Google source text | no match; the scanner itself is tested on one planted example of each pattern |
| Real names | A pattern scan cannot know a real name. All names are invented combinations; a coincidental match with a real person cannot be excluded, and none was looked up. |
| Network or Google | none; the new modules contain no network code, `fetch_public` was not run, no paid call was made |

### Limits, stated plainly

- This is corpus validation, not RAG quality. Nothing here shows that retrieval or answers are good.
- No question was written (tickets 05 to 07). The canaries and descriptions are the grounding those tickets use; expected answers are not yet derived.
- The generated files are cleaner than files saved by Word, Excel or PowerPoint. The three Google exports reduce that gap but are tiny (204 to 260 characters each) and cover only a short document, one small sheet and a three-slide deck; they do not show that large or complex Google files read well.
- Long documents come from seeded templates, so their sentences are regular. They do give retrieval real work (near-identical passages that differ in depot and number), but they are less varied than real prose.
- Compressed ZIP bytes depend on the zlib build. The manifest records zlib 1.2.12; on another zlib the two byte-exact tests skip with a reason. CI has not run this on GitHub.
- The CLI `corpus_files(with_messy=...)` in `cli.py` does not yet include `v1`/`google` files. Wiring them into an evaluation run belongs to ticket 08 (indexing). Until then `v1_files()` and the manifest are the only entry points.

## Comments

**2026-11-22, Owner decision: real Google exports with synthetic content (done).** The Owner first offered personal and third-party files; they were not used (one held a person's name and e-mail address in its properties, one was a personal job-search record, one export was missing). The Owner then created the three files in Google from the guide's synthetic text and they were pinned the same day: `google/google_open_day_notice.docx`, `google_open_day_rota.xlsx`, `google_open_day_briefing.pptx`, source `Google export`, `google_exports.status = pinned`, corpus version `m1-corpus-v1-a605f90dc57b`. Checks before pinning: valid zip files, no `docProps` entries (so no author or e-mail), no media or macros, scanner clean, text equal to the specification. The product's readers keep all nine canaries, the sheet values and the speaker notes on slide 3 (`test_the_real_google_exports_keep_their_sheet_values_and_speaker_notes`).
Deviation: the sheet tab is named `Sheet1`, not `Rota` as the guide said (the guide now says so). No canary depends on it. The slide 2 bullet ends with a full stop ("The fire marshal wears orange."). Neither affects any check.
The question tickets (05 to 07) can now be written against this corpus version.

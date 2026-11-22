# 06: New development cases

**Spec:** docs/specs/m1-rag-evaluation.md
**What to build:** New questions, written from the corpus documents and never from system output, that fill every gap in the coverage minimums that does not belong in the held-out pool.
**Blocked by:** 05.
**Status:** ready-for-agent
**Progress:** resolved (2026-11-22)

## Scope

- Write development cases (about 60 to 80; the exact number is what the coverage report needs after leaving the held-out share to ticket 07) with a verbatim anchor quote per fact, a reference answer and a forbidden-claim list each, **without running the system or reading any run result**. Cover what the existing set lacks: Critical-failure cases (a named document that does not exist next to a similar one that does; same-name entities; injection across the new documents and formats; content attributable to the wrong file); ambiguous questions; follow-ups with histories inside the production bound; calculations and table lookups on the new XLSX, DOCX and CSV files; multi-file questions; identifier questions on the new documents; at least eight questions per promised format across development and regression together.
- Prefer the invented second company and the long invented documents. Keep Roman Urdu cases as they are; add none.
- Record provenance (session and date). Freeze the new file in the freeze manifest.

## Out of scope

Held-out cases (ticket 07), running the system, changing any existing case, scoring, the application package.

## Inspect

Ticket 05's coverage report and `## Findings`; the corpus manifest and documents (ticket 04); `docs/KNOWN_ISSUES.md` (KI-022 to KI-030, for the shapes to cover); `GLOSSARY.md` (Critical failure); the v1 spec's required question types.

## Deliverables

New development case file(s), updated freeze manifest, `## Findings` with the coverage table after this ticket and the authoring rules used.

## Needs

No paid API, no key, no network.

- [x] Every new case passes the validator (anchors verbatim in extracted text, forbidden claims absent from the corpus, histories inside the bound).
- [x] After this ticket, every full-set minimum that does not depend on the held-out pool is met by development plus regression together; any shortfall is listed with its size in Findings.
- [x] No new case was derived from a system output and no result file was opened (stated in provenance and Findings).
- [x] The freeze manifest includes the new file; the freeze test passes.
- [x] `git diff -- backend/app` is empty; touched evaluation files pass `ruff check`, `ruff format --check` and `mypy`; the container-free evaluation tests pass.

## Findings

Written 2026-11-22 on `fb6516b` plus this ticket's changes. Every number below was produced by a command or test run in this session. No provider, key (`OPENAI_API_KEY` was unset for every command), network, Railway, Google or production data was used. Nothing here measures retrieval or answer quality: it is authoring and validation of the question set.

### What was written

`backend/evaluation/datasets/rag_v3_dev_cases.json`: **81 schema-v3 cases, all in the development pool** (`split: dev`), every one about the second invented company (Marrowdale, `corpus/v1/`) or the three Google exports. Corpus `m1-corpus-v1-a605f90dc57b`. Provenance on every case: session `m1-06-dev-a`, date 2026-11-22.

| By behaviour | Cases | | By shape | Cases |
|---|---:|---|---|---:|
| answer | 60 | | Critical failure | 23 |
| clarify (one clarifying question is correct) | 8 | | injection (4 documents, 4 formats) | 7 |
| not found | 10 | | multi-file (every file anchored) | 11 |
| partial | 2 | | follow-up (histories of 2, 4 and 6 messages) | 8 |
| false premise | 1 | | calculation (14 computed, each re-derived) | 14 |

Critical failure kinds: obeyed injection 7 (the fuel workbook x4, the safety procedures DOCX, the Q3 review PPTX, the newsletter PDF), wrong file as requested 7 (a policy version 3, a 2027 tariff, a 2024 report and an edition 6 that do not exist; version 1, the 2025 tariff and the 2026 tariff asked for by name), misattributed content 5 (Sam Kerrigan as customer contact against depot manager, assembly point C at the open day against the depot procedure, two questions that name the wrong document for a fact that lives in another), fabricated detail or citation 4 (a Zone E, a Zone D at a depot without one, a 2023 surplus, a berth depth that the plan says a survey must confirm).

### Coverage after this ticket (`uv run python -m evaluation.rag_eval.coverage`, exit 1)

| Requirement | Min (all) | Min (held-out) | Dev | Regression | Dev + regression | Target for this ticket | Met |
|---|---:|---:|---:|---:|---:|---:|---|
| Cases in total | 300 | 100 | 201 | 81 | 282 | 200 | yes |
| Unanswerable + partial + false premise | 80 | 30 | 41 | 24 | 65 | 50 | yes |
| Tagged Critical failure | 30 | 10 | 23 | 0 | 23 | 20 | yes |
| Multi-file | 25 | 8 | 16 | 3 | 19 | 17 | yes |
| Table lookup | 25 | | 35 | 9 | 44 | 25 | yes |
| Calculation | 20 | 6 | 18 | 9 | 27 | 14 | yes |
| Identifier | 25 | 6 | 19 | 7 | 26 | 19 | yes |
| Follow-up | 15 | 5 | 11 | 2 | 13 | 10 | yes |
| Ambiguous (clarify) | 10 | 4 | 8 | 0 | 8 | 6 | yes |
| Prompt injection | 10 | 4 | 10 | 1 | 11 | 6 | yes |
| Injection documents / formats | 3 / 2 | | | | 6 / 5 | 3 / 2 | yes |
| Evidence in DOCX / XLSX / PPTX / PDF | 8 each | 3 | 19 / 19 / 17 / 34 | 3 / 2 / 4 / 9 | 22 / 21 / 21 / 43 | 8 each | yes |
| Evidence in Markdown / CSV / TXT | 8 each | 3 | 12 / 10 / 75 | 0 / 0 / 48 | 12 / 10 / 123 | 8 each | yes |

**Target** is the full-set minimum less its held-out share (which ticket 07 supplies), except table lookup (no held-out share) and the eight cases per promised format (the ticket's own number), which are held to the full figure. `test_development_and_regression_meet_every_minimum_that_does_not_depend_on_the_held_out_pool` pins it. Format counts above include non-answer cases whose anchors lie in a format; counted from answer and partial cases alone the new file still gives 15 XLSX, 9 DOCX, 11 PPTX, 14 PDF, 10 CSV, 10 Markdown.

**Shortfalls that remain (all whole-set, all inside the held-out share, so ticket 07):** cases in total 18 (282 of 300; held-out minimum 100), unanswerable + partial + false premise 15 (65 of 80), Critical 7 (23 of 30), multi-file 6 (19 of 25), follow-up 2 (13 of 15), ambiguous 2 (8 of 10). The held-out pool must therefore bring at least 15 non-answer, 7 Critical, 6 multi-file, 2 follow-up and 2 ambiguous cases on top of its own minimums (30, 10, 8, 5 and 4), and 18 more cases in total (its own minimum of 100 already covers that).

### Authoring rules used

1. **Corpus text only.** Every question, reference answer, anchor and forbidden value was written from the extracted text of the frozen corpus (through the product's own readers). The ticket's `Inspect` list was followed; the `KNOWN_ISSUES` lines read were the defect shapes (the shape of KI-022 to KI-030), and one evidence line of KI-025 showed result counts by accident, which no case uses. **No result file was opened and no system output was read.** The file's `corpus` line and the provenance say so.
2. **Every fact is verbatim.** Each answer or anchor quote is checked verbatim in the extracted text by the validator; the numbers in every reference answer were additionally checked against the anchored sources by a one-off script, and the 13 arithmetic answers among the 14 computed cases were recomputed from the extracted tables (all agree; the fourteenth, `fm03`, is a date rule, checked by reading the policy's transition sentence).
3. **Multi-file means anchored in every file** (the review rule of ticket 05), and an answer that two files can give is `citation_mode: any`, not multi-file.
4. **Clarify cases anchor each reading with the name that separates it** (the depot, crossing or service) and forbid each reading's value, so a valid clarifying question is recognisable by the words it uses. `deep.clarifying` accepts each reference question, rejects a reply that states a reading, and leaves a vague "How can I help you?" undecided (checked for all 8).
5. **Non-answer cases forbid only what the corpus lacks.** A forbidden claim that the corpus contains would fail a correct refusal that mentions the similar document, so the wrong-file traps rely on the judge note and the citation check instead of a value (see the first finding).
6. **Sibling values come from the validator's generator** and were reviewed per case. Six cases exempt a value a correct reply may mention: the other version's value (`wf01`, `wf02`, `fm01`), two Notes-sheet sentences that carry the injection (`ix03`, `mg06`), a column header (`fr01`).
7. **Roman Urdu: none added; no existing case changed.**

### How it was verified

- **Validator, all cases, public PDFs included:** `pools validate --with-public`: 282 cases, 0 problems (about 160 s). The ordinary run without the public PDFs also gives 0.
- **The validator bites on this file:** nine broken variants of real cases (a changed anchor, a dropped sibling, a history of 8 messages, a critical case without a kind, an injection case without a document, a multi-file case missing an anchor, a clarify reference that answers, a clarify forbidden value outside the anchors, an anchor present in two files) each produced exactly the expected problem. A tenth, a forbidden claim of a missing thing that a Marrowdale file really contains, passed silently: that is finding 1.
- **Independent checks, all clean:** each reference satisfies its own `must_include` and avoids its own forbidden values; computed answers recomputed from the tables; no new question duplicates an existing one; ids unique; every history inside 6 messages and 6000 characters (largest: 6 messages, 310 characters).
- **Freeze:** `freeze check` 0 problems. The file was registered as an addition (79 cases), then amended twice, as the protocol requires (see below); the four older files' checksums are unchanged and `git diff` shows only the manifest and log gaining entries.
- **Static:** `ruff check` and `ruff format --check` clean on the touched files; `mypy` clean on `dataset.py`, `pools.py`, `schema_v3.py`, `coverage.py`, `freeze.py`; `basedpyright` 0 errors on the two touched test files; `git diff -- backend/app` is empty.
- **Tests:** `env -u OPENAI_API_KEY uv run pytest tests/evaluation -q`: **567 passed, 4 skipped** (ticket 05's 560 plus 7 new: the forbidden-claim scope, the acceptance minimums, contradictory references (two tests), sibling stability against unrelated documents (two tests) and the unlisted `rag_v3_*` file; the 4 skips are as before: 2 earlier ones plus the two sealed-file tests). `pools validate --with-public`: 282 cases, 0 problems. `freeze check`: 0 problems.

### Findings that change the plan

1. **The not-found forbidden-claim check ignored the new corpus (fixed).** `dataset.validate` scanned only `synthetic/` and `messy/` text, so a not-found case on a Marrowdale document could forbid a value the corpus really contains and the validator said nothing (reproduced: forbidding "24,000 km" on a missing policy v3 gave 0 problems). Such a claim fails a correct refusal that names the similar document. The scan now includes `v1/` and `google/`. Red then green: `test_a_forbidden_claim_of_a_missing_thing_must_be_absent_from_every_corpus_family`. No older case was affected (0 problems on all 201).
2. **Validation could depend on whether the public PDFs were present (found, one case fixed, check added).** `sk02` passed the ordinary run but failed `--with-public` with 15 problems: its handbook anchor began with "The", a one-word context, so digits after "The" anywhere in the public PDFs counted as siblings. The quote now starts at the value (amendment 2 of the log). `test_a_cases_sibling_values_do_not_depend_on_unrelated_documents` now fails for any v3 case whose siblings change when unrelated text is added, and a second test shows it detects the old `sk02`. **The generator itself still treats a one-word context as a context** (`schema_v3._context_siblings`); it was not changed here because older and future cases may rely on short contexts. Ticket 07 authors should start a quote at the value when it begins with a generic word.
3. **The unlisted-file guard missed this file's name (fixed).** `freeze.CASE_FILE_PATTERNS` matched `rag_v2_*` and `m1_*cases*` only, so an unregistered `rag_v3_*.json` would not have failed `freeze check`. The pattern now includes `rag_v3_*.json` (`test_an_unregistered_rag_v3_case_file_fails_like_any_other`, shown to fail without the change).
4. **Two corpus statements contradict their own details (no case depends on them).** The runbook says it covers "the seven systems" but documents eight; the customs guide says the Ostrow Pass booking window "is the longest of the five" but gives 12 hours, the shortest (the others are 36 or 48). No case asks how many systems the runbook covers or which crossing has the longest window; the cases that touch those documents use the detailed entries. Ticket 08 and M6 should know that a reader or model that trusts the introduction will be wrong.
5. **Several existing tests encoded "the repository holds only the four older files" and were updated, not loosened:** the freeze manifest's file list, the load test (the 201 older cases, their order and pools are still pinned as the first 201), the coverage count and the "201" in the coverage output; the freeze fixture now copies every file the manifest lists; and the check that `sha256` equals `frozen_sha256` now applies to the four older files (an amended file moves `sha256`, by design). One log-phase assertion now expects the first five entries to be `history` and later ones `post_freeze`.
6. **The case file was amended after it was registered, twice, inside this ticket:** `sk02` anchor (finding 2) and two multi-turn follow-ups `fxL1` (4 messages) and `fxL2` (6 messages, at the bound), added after a review showed that all six earlier follow-ups were single-exchange. Both entries are in `m1_amendments.json`; nothing was run between them, so no earlier checkpoint is affected.

### Caveats, limits and what was not tested

- **No run.** Whether the system answers any of these cases correctly is unknown and must stay so until ticket 11. Every acceptance criterion here is about the file and its validators, not about the product. The one criterion that cannot be verified without a paid API or Google is the quality of the cases as a measurement (a case can be valid and still not discriminate); the pilot and the baseline will show which cases never fail or always fail.
- **The wrong-file traps carry no deterministic bite** for the "not found" shape (rule 5): their pass depends on the refusal judge and the citation check, and the judge has never met a human label (ticket 10). The wrong-version answer cases do have bite (`must_include` fails the wrong value).
- **Computed cases are weaker than lookups:** the validator does not check computed answers against the text, and the forbidden-value list is empty for them (the sibling generator skips computed cases). A reply that gets the arithmetic wrong with a number that looks plausible passes only if it also contains the right one; `must_include` is a single number for all of them.
- **Injection cases use payload values as forbidden claims.** `ix04` forbids two strings from other documents that a dump of "every other document" would contain, and `ix01`-`ix03` forbid "REG-9". A reply that quotes the planted instruction ("the note says to cite REG-9") fails the deterministic check although the glossary says quoting is not a Critical failure; the claim-support grader and the Owner's spot check are the safeguard, as for `ij01`.
- **Clarify cases test a behaviour the production agent may not have.** Whether the agent ever asks one clarifying question is exactly what these eight measure; a result of 0 of 8 is information, not a defect in the cases. `deep.clarifying` is deterministic only for questions that name a reading; a question that names none stays undecided.
- **Some long forbidden lists** (`ic01`, `fr02`, `mg04`: about 40 values each) come from the generator reading every `Cost (GBP)` column in the corpus. They are what the rule asks for and none can occur in a correct reply, but they make the file noisy.
- **All new cases are `dev`.** None is regression (that pool is the old `test` split, by design) and none is held-out. They will be tuned against in M2 and M3; ticket 07 and the sealed pool are the overfitting check.
- **Two assumptions about "the corpus text":** the extracted text is what the product reads today (pipeline version 3); a reader change that alters it would turn some anchors into validator failures, which is the intended alarm.

## Comments

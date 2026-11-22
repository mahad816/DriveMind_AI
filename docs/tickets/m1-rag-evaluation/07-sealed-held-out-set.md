# 07: Sealed held-out set

**Spec:** docs/specs/m1-rag-evaluation.md
**What to build:** At least 100 new questions, written before any baseline measurement by an author who has seen no result, covering the same dimensions as the development pool. The sealing machinery already exists (ticket 05); this ticket supplies the cases and the Owner's review of their gold answers.
**Blocked by:** 06.
**Status:** ready-for-agent
**Progress:** resolved (2026-11-22), Owner review of the review sheet complete (36 of 36 correct, 0 gold wrong; see "Owner review finalization M1-07-E"). **Ticket 08 and ticket 11 each still need the Owner's own approval of paid spend; the review does not give it.**

## Scope

- **Authoring in a clean session.** The session reads the corpus documents, the case schema and the coverage report. It does **not** open any result file or run summary, does not run the system, and does not read per-case failure tables in the results log. Provenance states this. Cases follow ticket 06's rules.
- **Size and coverage.** At least 100 held-out cases meeting the held-out column of the spec's minimums (unanswerable, partial and false-premise at least 30; Critical at least 10; multi-file at least 8; calculation at least 6; identifier at least 6; follow-up at least 5; ambiguous at least 4; injection at least 4; each promised format at least 3). Prefer questions about the invented second company and the long invented documents.
- Save the file at the Owner-local path (outside the working tree) and register only its checksum and counts in the freeze manifest; the sealing tests from ticket 05 now run on the real file. Tell the Owner to back the file up, because the repository will not hold it. Reserve a share of the long invented documents for held-out questions only.
- **Owner review.** Export a review sheet of at least 30 sampled held-out cases (stratified; question, reference answer, anchor quote, source file) for the Owner to mark "correct" or "gold wrong". Gold errors are corrected under the amendment log; the share found is reported.

## Out of scope

Running the system on any case, scoring, tuning anything, editing development or regression cases, committing any held-out per-case result.

## Inspect

Tickets 05 and 06 `## Findings` and the coverage report; the corpus manifest and documents; `docs/specs/m1-rag-evaluation.md` ("The frozen question set").

## Deliverables

The held-out case file, the review sheet, `## Findings` with the held-out coverage table, the authoring statement and the review outcome.

## Needs

No paid API, no key, no network. Owner time: about one hour for the review sheet (spec decision 2).

- [x] The held-out file validates, meets every held-out minimum, has at least 100 cases and no id collisions.
- [x] The held-out file is not in the working tree; its checksum and counts are in the freeze manifest; the freeze and sealing tests pass on the real file; no held-out case id appears in any committed output; the Owner has been told to back it up.
- [x] The Owner review sheet exists; the review result (cases checked, errors found, corrections applied) is recorded here. If the Owner has not reviewed it when the session ends, the ticket is resolved with the review recorded as pending and ticket 08 (the first paid step, which already measures held-out cases once) and ticket 11 must not start until it is done. **Sheet exists; review complete (36 of 36 checked, 36 correct, 0 gold wrong), recorded in "Owner review finalization M1-07-E".**
- [x] Findings state that no result or run output was read during authoring.
- [x] `git diff -- backend/app` is empty; touched evaluation files pass `ruff check`, `ruff format --check` and `mypy`; the container-free evaluation tests pass.

## Findings

Written 2026-11-22 on `e6fb7ed` plus this ticket's changes. Every number below was produced by a command or test run in this session. No provider, key (`OPENAI_API_KEY` was unset for every command), network, Railway, Google or production data was used. **This ticket's evidence is aggregate only: no held-out question, reference answer, anchor, id or per-case result appears here, and none may be added.** Nothing here measures retrieval or answer quality: it is authoring, validation and safeguards for the question set.

### Authoring statement

The pool was written in one session (`m1-07-held-a`, 2026-11-22) from the **extracted text of the frozen corpus** `m1-corpus-v1-a605f90dc57b` (the Marrowdale documents and the three Google exports) through the product's own readers. **No result file, run summary, per-case failure table or system output was opened, read or used**; the session read this ticket, ticket 06's findings, the spec, the schema, coverage and freeze code, and the committed development case file (questions and gold only). Every computed answer was recomputed from the extracted tables by a script that does not read the case answers (25 of 25 agree); every number in every non-computed reference answer was traced to its question, history or evidence text (three untraced tokens were a date reformatting and two statements about the annual report, all correct). No question is identical to a development or regression question; 8 are close (similarity above 0.85) because they are the answerable or unanswerable twin of a development shape, with a different answer in each pair.

### What was written and where

180 schema-v3 cases, all `held_out`, **one file outside the working tree** (on the Owner's Mac: `~/.drivemind-eval-sealed/m1_held_out_cases.json`, owner-only permissions). Its checksum, case count, counts per gate group and injection documents are in `datasets/m1_freeze.json`, with one `addition` entry in `m1_amendments.json` that lists no case id. All 180 are about the second invented company or the three Google exports; none is Roman Urdu.

| Held-out cases by behaviour | | Critical by kind | | Other shapes | |
|---|---:|---|---:|---|---:|
| answer | 139 | obeyed injection | 14 | computed (calculation) | 25 |
| not found | 22 | wrong file as requested | 9 | follow-ups: 2, 4 and 6 messages | 6 / 1 / 1 |
| partial | 7 | fabricated detail or citation | 8 | question names a missing file | 2 |
| false premise | 6 | misattributed content | 5 | citation mode "any" | 3 |
| clarify | 6 | all Critical | 36 | | |

### Coverage (`coverage --require-held-out`, exit 0, with and without the sealed file)

| Requirement | Min (all) | Min (held-out) | Held-out | Whole set | Met |
|---|---:|---:|---:|---:|---|
| Cases in total | 300 | 100 | 180 | 462 | yes |
| Unanswerable + partial + false premise | 80 | 30 | 35 | 100 | yes |
| Tagged Critical failure | 30 | 10 | 36 | 59 | yes |
| Multi-file | 25 | 8 | 11 | 30 | yes |
| Table lookup | 25 | | 30 | 74 | yes |
| Calculation | 20 | 6 | 25 | 52 | yes |
| Identifier | 25 | 6 | 16 | 42 | yes |
| Follow-up | 15 | 5 | 8 | 21 | yes |
| Ambiguous (clarify) | 10 | 4 | 6 | 14 | yes |
| Prompt injection | 10 | 4 | 14 | 25 | yes |
| Evidence in DOCX / XLSX / PPTX / PDF | 8 each | 3 each | 40 / 30 / 25 / 42 | 62 / 51 / 46 / 85 | yes |
| Evidence in Markdown / CSV / TXT | 8 each | 3 each | 21 / 20 / 15 | 33 / 30 / 138 | yes |
| Injection documents / formats | 3 / 2 | | 4 / 4 (held-out alone) | 6 / 5 | yes |

These are design counts of the file, not results. Ticket 06 left whole-set shortfalls of 18 cases, 15 non-answer, 7 Critical, 6 multi-file, 2 follow-up and 2 ambiguous; the held-out pool covers those **and** its own held-out minimums at the same time (the second set is the larger requirement: for example 30 non-answer and 10 Critical inside the pool, not 15 and 7).

**Reserved share of the long documents.** Counting text lines of the seven long documents (cold chain manual, bylaws, customs guide, runbook, driver handbook, annual report, Q3 review) that an evidence anchor covers: 130 lines are used by held-out questions only, 50 by development and regression only, 44 by both. 74 of the 116 held-out cases that rest on a long document share no line with a development or regression anchor.

### Permanent safeguards

| Safeguard | Where | Shown to bite |
|---|---|---|
| **A reference answer must pass its own deterministic checks** (the M1-06 review finding). The test-only helper became `schema_v3.reference_problems`, called by `dataset.validate` for every v3 case, held-out included; its messages name the case and the rule, never a value. | `schema_v3.py`, `dataset.py` | red then green; removing the call, or the clarify rule, fails a test |
| **Redacted validation of the sealed pool**: `pools validate --held-out` prints the case count and a count per broken rule; every validator message is reduced to its rule (unmatched = "other rule"); a structurally broken case is reported by exception class only; id collisions and duplicate questions against the committed set are counted. | `pools.py` | a file with one broken copy of a real case per rule (8 rules) and secret markers in id, question, quote and forbidden claim: each rule counted once, no marker in stdout, stderr or the report; the raw validator does quote the marker |
| **Content-leak scan**: `sealing.leaked_cases` counts how many held-out cases a text gives away by id, by a question of 15 or more normalised characters or by a reference answer of 30 or more (text already public in the corpus or in the committed questions and references does not count). The tracked-file scan now uses it, and its failure message is a number. | `sealing.py`, `test_held_out_set.py` | id, question, reference and public-text rules each have a case; removing the reference or id rule fails a test |
| **Held-out minimums cannot be skipped silently**: a hollow held-out pool (100 cases of one shape) passes the whole-set check and fails `--require-held-out`; the command now prints "held-out minimums NOT enforced" without the flag; a free test runs `--require-held-out` on the manifest's recorded counts on every machine, so a registered file that is too small fails. | `coverage.py`, `test_held_out_set.py` | removing either the flag handling or the notice fails a test |
| **Owner review sheet**: `pools review-sheet OUT.md` writes a stratified, deterministic sample (one place per shape, then proportional) with question, reference answer, anchor quote and file, owner-only, **refused inside the repository**; prints counts per shape. | `pools.py` | a skewed pool (two rare shapes among 40) keeps both; the inside-repository refusal and the minimum-of-one rule each fail a test when removed |

Reused unchanged: the loader and the refusal of a held-out file inside the repository, `freeze seal-held-out`, the amendment log, the aggregate-only summaries with cells under ten suppressed, `coverage --require-held-out`, the freeze and pool protections. 10 deliberate breakages of the new safeguards were each caught by a test; every file was restored afterwards.

### Verification

- **Validator on the sealed file** (redacted): 180 cases, 0 problems (anchors verbatim, forbidden claims absent or bounded, sibling values forbidden, histories inside the bound, references consistent, no id collision, no duplicate question).
- **Freeze:** `freeze check` 0 problems with and without the sealed file; the four older files' and the development file's checksums are unchanged; the manifest gained the held-out node and the log one entry.
- **Tests:** `env -u OPENAI_API_KEY uv run pytest tests/evaluation -q`: **590 passed, 8 skipped** without the sealed file (2 earlier unrelated skips, the 2 sealed-file tests of ticket 05 and the 4 of this ticket); **596 passed, 2 skipped** with `DRIVEMIND_EVAL_HELDOUT_FILE` set, which runs ticket 05's checksum and id-scan tests on the real file. Ticket 06 ended at 567 passed, 4 skipped; 27 tests are new (`tests/evaluation/test_held_out_set.py`). Three older fabricated fixtures whose reference answers lacked their own facts were corrected (the new rule found them), the freeze fixture now models the repository before sealing, and the coverage test whose premise was "no held-out pool" now blanks the manifest's counts.
- **Static:** `ruff check`, `ruff format --check` clean; `mypy` clean on the six touched evaluation modules; `basedpyright` 0 errors on the three touched test files; `git diff -- backend/app` is empty.
- **Privacy checks:** a scan of every tracked text file for a held-out id, question or non-public reference answer finds none; `freeze check`, `coverage`, `pools validate --held-out` and `pools review-sheet` print counts only (tested with secret markers on fabricated files).

### Owner review (superseded: see "Owner review finalization M1-07-E" below)

`m1_review_sheet_for_owner.md`, next to the sealed file in the same owner-only folder, holds **36 of the 180 cases**, stratified (shapes: ambiguous 1, calculation 5, follow-up 2, identifier 2, injection 3, lookup 11, multi-file 2, non-answer 6, table 4), each with two boxes, "correct" and "gold wrong". **Result: cases checked 0 of 36, errors found 0, corrections applied 0, all pending.** Corrections go through `freeze seal-held-out --reason ...` (a held-out amendment, no ids in the log); report only the share found here. **Tickets 08 and 11 must not start until the review is done** (a gold error would otherwise be measured; ticket 08's plain-question probe covers held-out cases once). The review is not a spend approval: each paid ticket also needs the Owner's own approval of its estimate and cap (spec decision 1), given when that ticket starts. Nothing in the repository records that the review is done (see "Review fix M1-07-C" below), so the check is a human one.

### Review fix M1-07-C (2026-11-22, two issues from the independent review)

Evidence is aggregate and fabricated only: no held-out question, answer, review sheet or transcript was opened, and `DRIVEMIND_EVAL_HELDOUT_FILE` was unset for every command.

**1. Owner-review prerequisite (documentation).** *Root cause:* the review gate was written down for ticket 11 only (this ticket, spec decision 2) while ticket 08 and the spec's ticket table already said ticket 08 needs it, and ticket 08 measures held-out cases once. The review and the spend approval were never separated in words. *Fix:* this ticket, ticket 08 (scope and checklist), the spec (decisions preface, decision 2, ticket table, ordering sentence) and `docs/guides/EVALUATION.md` now say: **ticket 08 and ticket 11 need the completed Owner review, and each paid ticket also needs the Owner's own approval of its estimate and cap; one does not imply the other.** Ticket 11's existing precondition ("the held-out review (ticket 07) is done") was already correct and is unchanged.

**Blocker B-1 (not fixed, needs a design decision): nothing enforces the review before a paid held-out run.** Checked: the freeze manifest holds the sealed file's checksum and counts only; the amendment log records corrections, not review state; `cli run --split held_out` and the probes check a cap and a plan, not a review; the review sheet and its marks live on the Owner's Mac outside the repository, and the result is recorded in this ticket as prose. No existing boundary can read a "review done" state, so any enforcement would need a new completion flag (where it lives, who may set it, how it is tied to the sealed file's checksum so a later amendment invalidates it). That is a broader decision than this fix and was not invented. Until it is made, the gate is the Owner's and the assistant's check of this ticket before ticket 08 starts. **The Owner review is still pending (0 of 36 checked) and was not marked complete.**

**2. Required schema fields (code).** *Root cause:* `dataset.validate` read thirteen fields as `case["..."]` and trusted the type of every other field, and `v3_field_problems` did the same; the contract (all 282 committed cases carry the thirteen; v3 cases carry `tags`) was never stated or checked. A missing `id`, `expected_behavior`, `expected_files`, `must_include`, `must_not_include`, `evidence_anchors` or `computed` raised `KeyError`; a non-string question or a list of strings as anchors raised `TypeError`; a missing or invalid `question`, `category`, `language`, `citation_mode`, `tags` (or `computed` given as text) passed with no problem at all. On the sealed pool one such case collapsed the whole report into a single "KeyError" line, hiding every other count. *Fix:* `schema_v3.required_field_problems` (a field table with a type check each, `LANGUAGES = en, roman_urdu`) runs first in `dataset.validate`; a case that fails gets one `<id>: required field <name> is missing or invalid` line per field (never the value) and no other rule is run on it, and the other cases are still validated. `pools.validate_question_set` keeps malformed cases in so they are reported. In the redacted sealed report the lines are one rule: "a required case field is missing or invalid". Optional fields (`history`, `critical`, `critical_kind`, `injection_document`, `sibling_exempt`, `judge_note`, `formats`) are type-checked when present. Vocabulary checks (behaviour, split, citation mode, tags) are unchanged.

| | Before (fabricated cases, same tests) | After |
|---|---|---|
| Missing or invalid required field, one fabricated v3 case each | 72 of 152 tests in the two touched test files fail (7 fields raise `KeyError`, bad types raise `TypeError`, 5 fields pass silently) | 152 passed, 4 skipped (the sealed-file tests) |
| Evaluation suite | 590 passed, 8 skipped (ticket 07) | 661 passed, 8 skipped |
| Committed cases (282) | valid | valid (`test_every_committed_case_carries_the_required_fields`); `freeze check` 0 problems; no dataset file changed |

*Permanent safeguards:* the field table is the single statement of the contract; new tests in `test_question_set.py` (a missing field on a v3 case, on an older case, invalid values per field, a malformed case does not hide the others, id-less cases reported one by one, no value quoted in a message, all committed cases comply, the committed-set validator does not raise) and two in `test_held_out_set.py` (own redacted rule; every field maps to it); 72 of these failed before the fix. One older test asserted the defect ("structurally malformed (KeyError)") and now asserts the new rule. `git diff -- backend/app` is empty; `ruff check`, `ruff format --check`, `mypy` (three touched modules) and `basedpyright` (two touched test files) are clean.

### Caveats, limits and what was not tested

- **The authoring transcript holds the pool.** The cases were written through tool calls in this session, so this session's transcript (and the builder scripts in a temporary folder) contain them. Treat the transcript as confidential, do not resume or search it from a later session that will diagnose or tune, and delete the temporary builder files (done at the end of this ticket).
- **Not yet checked by a human.** The gold answers were verified mechanically (verbatim anchors, recomputed arithmetic, traced numbers) and by the author, not by the Owner; the share of gold errors is unknown until the sheet is reviewed. The sheet samples 36 of 180, so errors outside it stay undetected.
- **Not run.** Whether the system answers any held-out case correctly is unknown and must stay so until ticket 11 (once per checkpoint). A valid case can still fail to discriminate; the baseline will show which never fail.
- **Shape twins.** Several held-out shapes repeat development shapes with different entities (not-found beside an answerable lookup, clarifying templates, date-rule cases), so tuning to the development shapes can help held-out cases; the leak is of shape, not of content, and the limit is stated in the spec.
- **Forbidden-claim noise.** Sibling values come from the validator's generator and include some noise (other columns' numbers); a few values a correct reply may mention (the other tariff year, a file name, two Notes sentences) are exempted per case. A very verbose correct reply can still trip a forbidden value; the claim-support grader and the Owner's spot check are the safeguard.
- **Counts per gate group are committed.** The manifest records design counts per group (some under ten, such as ambiguous 6); they say how the pool is built, not how anything performed, and ticket 05 chose to commit them. Results remain suppressed under ten.
- **Two corpus statements still contradict their details** (ticket 06, finding 4); no held-out case depends on either.
- **Backup.** The sealed file and the review sheet exist only on this Mac. Back both up (the repository will not).

### Owner review finalization M1-07-E (2026-11-22, on `b6d3f32`)

Aggregate counts only: no held-out question, answer, anchor, id or per-case result appears here. No paid API, key, network, Railway, push or deployment was used; the sealed file was not modified.

**Authorization.** The Owner reviewed the 36 sampled cases visually and authorized recording "correct" for every case that the existing tools verify, and "gold wrong" with a note for any that fail. None failed.

**Re-verification before marking** (a scratch script outside the repository, printing counts and sheet positions only):
- The sealed file's SHA-256 equals the checksum in `datasets/m1_freeze.json`; the sheet (36 cases, no duplicate id) matches the sealed file on behaviour, question, reference answer, history, judge note and every anchor (file and quote) for all 36 cases, including the case whose missing anchor was corrected in M1-07-D.
- `pools validate --held-out`: 180 cases, 0 problems (anchors verbatim, one file each, reference answers pass their own checks). Every answer or partial case in the pool, and so every sampled one, has an anchor in each expected file.

**Result.** Decisions recorded 36 of 36; **correct 36; gold wrong 0; unresolved 0.** Each case has exactly one box selected. Corrections applied: 0 (no amendment needed). The sheet stays in the owner-only folder (mode 600), outside the repository. The sealed file's checksum is identical before and after, and equals the manifest's.

**Limits.** The sheet samples 36 of 180 cases; errors in the other 144 are not excluded. "Correct" means the reference answer and anchors were verified against the corpus text, not that the system answers the case. The review is **not** an approval of paid spend: ticket 08 and ticket 11 each need the Owner's explicit approval of their estimate and cap.

**Free checks run:** `freeze check` 0 problems; `coverage --require-held-out` exit 0; `pytest tests/evaluation` 667 passed, 2 skipped (sealed file present); `ruff check` clean.

**Blocker B-1 remains open (safeguard recommendation for a separate ticket).** Nothing in the repository still stops a paid held-out run on an unreviewed or later-modified sealed file; the review state lives only in this prose. Smallest deterministic mechanism:
1. A review attestation file beside the sealed file (outside the repository), holding `sealed_sha256`, the number of cases reviewed, the number marked correct and the number marked gold wrong. A command (for example `pools attest-review`) writes it by parsing the Owner's sheet: it refuses unless every sheet case has exactly one box, every id is in the sealed file, there are at least 30 cases and none is "gold wrong"; it records the sealed file's current hash and the sheet's hash.
2. One check in `pools.load_held_out`, the only entry point the paid `run --split held_out` path uses: the file must have an attestation whose `sealed_sha256` equals the file's current hash and the manifest's `held_out` checksum; otherwise stop with a message that names no case. Any later amendment changes the hash, so it invalidates the attestation without extra bookkeeping.
3. Free-only commands (`validate`, `coverage`, `freeze check`, `review-sheet`) must bypass the check, so they use a separate loader flag, not the default.
4. Tests: no attestation, a stale hash, a sheet with an unticked or doubly ticked case, a "gold wrong" case and fewer than 30 cases each refuse; a matching attestation passes; the review-sheet output stays outside the repository.
The attestation records review only; the spend approval and cap stay the Owner's separate act at the start of each paid ticket.

## Comments

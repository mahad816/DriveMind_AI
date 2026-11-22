# 07: Sealed held-out set

**Spec:** docs/specs/m1-rag-evaluation.md
**What to build:** At least 100 new questions, written before any baseline measurement by an author who has seen no result, covering the same dimensions as the development pool. The sealing machinery already exists (ticket 05); this ticket supplies the cases and the Owner's review of their gold answers.
**Blocked by:** 06.
**Status:** ready-for-agent
**Progress:** open

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

- [ ] The held-out file validates, meets every held-out minimum, has at least 100 cases and no id collisions.
- [ ] The held-out file is not in the working tree; its checksum and counts are in the freeze manifest; the freeze and sealing tests pass on the real file; no held-out case id appears in any committed output; the Owner has been told to back it up.
- [ ] The Owner review sheet exists; the review result (cases checked, errors found, corrections applied) is recorded here. If the Owner has not reviewed it when the session ends, the ticket is resolved with the review recorded as pending and ticket 11 must not start until it is done.
- [ ] Findings state that no result or run output was read during authoring.
- [ ] `git diff -- backend/app` is empty; touched evaluation files pass `ruff check`, `ruff format --check` and `mypy`; the container-free evaluation tests pass.

## Comments

# 03: Deterministic scoring extensions and failure attribution

**Spec:** docs/specs/m1-rag-evaluation.md
**What to build:** Everything about an answer that code can decide is decided by code, from stored rows, with no model: which passage was cited, how many required facts were present, whether the answer asserts numbers nobody supplied, whether retrieval found the supporting passage, and what the most likely cause of a failure is. The same module gives paired and repeat statistics for comparing runs honestly.
**Blocked by:** 02.
**Status:** ready-for-agent
**Progress:** open

## Scope

- **Anchor-to-passage mapping.** A pure function that decides whether a case's verbatim evidence quote lies in a given chunk's text (using the existing normalisation), and a small resolver that loads chunk texts by identifier from the evaluation database. A quote cut by a chunk boundary is classified "split" and handled by a stated rule; the validator fails when more than 2 percent of anchors are split.
- **New per-case scores, all recomputable from a stored row plus resolved chunk texts:**
  - fact recall (required fact groups present over required) next to the existing all-or-nothing correctness;
  - chunk-level citation (a cited chunk contains the anchor), citation precision (share of cited files that are expected, already counted as noise) and citation integrity (every cited chunk exists, belongs to the evaluation owner and carries the file name the corpus maps to; zero tolerance);
  - retrieval from the recorded real queries: anchor chunk among the retrieved chunks, its best rank, whether the right file was retrieved, number of distinct files per search;
  - an independent unseen-value screen: numbers, dates, identifiers and capitalised names in the reply that appear nowhere in the cited chunk texts, the question or the history, and are not allowed by a computed case. It is deliberately over-inclusive (a screen, not a verdict) and must not reuse the claim checker's own extraction; it allows cited file names, reformatted dates, unit conversions, number words and list numbers;
  - the **legacy pass**, the **deterministic strict pass** (every anchor chunk cited, cited files outside the expected set within a stated bound, integrity, clean screen) and the slot for the graded strict pass, as defined in the spec, the answerable and non-answer outcome matrices (correct, wrong, false abstention, correct abstention, fabrication), and the Critical-failure candidates the code can see (a citation that fails integrity, a named missing file answered from another file, a forbidden injected instruction present).
- **Failure-cause assignment.** An ordered, documented rule list that gives each failed case exactly one primary cause and keeps secondary flags: extraction (anchor absent from extracted text; the validator should prevent it), agent did not search, retrieval miss (anchor chunk not retrieved by any search), retrieved but not used (anchor chunk retrieved, fact missing), intent-gate short circuit (the answer path ended at the gate with no retrieval), answer built from a whole-file read rather than a search, a claim-check removal of a correct statement, the no-evidence envelope or cycle limit or truncation notice, generation error (wrong value stated), grounding (unseen value or, later, grader verdict), citation (right facts, wrong or missing passage), false abstention, fabrication, provider or timeout error. The rule order and the cases it cannot decide ("unknown") are tested.
- **Statistics.** Wilson intervals (existing), bootstrap intervals for percentiles, a paired exact test on cases that differ between two runs, per-case pass rate and flip rate across repeats, and the share of flaky cases. Roll-ups by category, format, split, language, behaviour and the Critical tag.
- A summary schema version 2 written by the existing summariser, with the old fields kept so earlier documents stay readable; `rescore` recomputes the new fields from stored rows.

## Out of scope

Any LLM grading (ticket 09), new datasets or corpus, paid runs, changes to application code or to the claim checker.

## Inspect

`backend/evaluation/rag_eval/score.py`, `text.py`, `runner.py` (`score_row`, `overall`), `dataset.py`; `backend/tests/evaluation/test_rag_eval_score.py`, `test_rag_eval_text.py`; ticket 02's `## Findings`; `docs/EVALUATION_RESULTS.md` (the invention-trap findings `tr01`, `tr04`, `tr11`, `tr13`, the planted-claims section).

## Deliverables

Code and free tests; a `## Findings` section with the failure-cause rule table and a worked example for each cause; the old results history is not rewritten.

## Needs

No paid API, no key, no network. The resolver test uses the existing disposable PostgreSQL fixtures; everything else is pure and needs nothing.

- [ ] Hand-built rows pin each new score, including: right file cited with the wrong passage fails the strict pass but passes the legacy pass; a correct fact plus an invented number is flagged by the screen and passes only the legacy pass; a fabricated chunk identifier fails integrity; a computed case's derived number is allowed; an anchor split by a chunk boundary is classified, not lost.
- [ ] Each failure cause has a pinned example row, the rule order is tested, and an undecidable row is reported as "unknown", never forced into a cause.
- [ ] The paired test, the bootstrap interval and the flip statistics are tested against hand-computed values; an A-versus-B comparison with differing case sets refuses to run.
- [ ] `rescore` on a pre-ticket-01 fixture and on a ticket-01 fixture both produce a version 2 summary with the old fields unchanged.
- [ ] The screen is documented as a screen: Findings name its blind spots. Its false-flag rate is **not** measured on reference answers (they come from the files, so that rate is trivially low) but is recorded in ticket 09 on real pilot replies against the Owner's labels; this ticket only builds it and tests it on constructed rows.
- [ ] `git diff -- backend/app` is empty; touched evaluation files pass `ruff check`, `ruff format --check` and `mypy`; the container-free evaluation tests pass and the resolver's container test passes.

## Comments

# 03: Deterministic scoring extensions and failure attribution

**Spec:** docs/specs/m1-rag-evaluation.md
**What to build:** Everything about an answer that code can decide is decided by code, from stored rows, with no model: which passage was cited, how many required facts were present, whether the answer asserts numbers nobody supplied, whether retrieval found the supporting passage, and what the most likely cause of a failure is. The same module gives paired and repeat statistics for comparing runs honestly.
**Blocked by:** 02.
**Status:** done
**Progress:** complete (2026-11-22)

## Scope

- **Anchor-to-passage mapping.** A pure function that decides whether a case's verbatim evidence quote lies in a given chunk's text (using the existing normalisation), and a small resolver that loads chunk texts by identifier from the evaluation database. A quote cut by a chunk boundary is classified "split" and handled by a stated rule; the validator fails when more than 2 percent of anchors are split.
- **New per-case scores, all recomputable from a stored row plus resolved chunk texts:**
  - fact recall (required fact groups present over required) next to the existing all-or-nothing correctness;
  - chunk-level citation (a cited chunk contains the anchor), citation precision (share of cited files that are expected, already counted as noise) and citation integrity (every cited chunk exists, belongs to the evaluation owner and carries the file name the corpus maps to; zero tolerance);
  - retrieval from the recorded real queries: anchor chunk among the retrieved chunks, its best rank, whether the right file was retrieved, number of distinct files per search;
  - an independent unseen-value screen: numbers, dates, identifiers and capitalised names in the reply that appear nowhere in the cited chunk texts, the question or the history, and are not allowed by a computed case. It is deliberately over-inclusive (a screen, not a verdict) and must not reuse the claim checker's own extraction; it allows cited file names, reformatted dates, unit conversions, number words and list numbers;
  - the **legacy pass**, the **deterministic strict pass** (every anchor chunk cited, no unnecessary extra cited file, judged against the case's declared supporting evidence, integrity, clean screen) and the slot for the graded strict pass, as defined in the spec, the answerable and non-answer outcome matrices (correct, wrong, false abstention, correct abstention, fabrication), and the Critical-failure candidates the code can see (a citation that fails integrity, a named missing file answered from another file, a forbidden injected instruction present).
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

- [x] Hand-built rows pin each new score, including: right file cited with the wrong passage fails the strict pass but passes the legacy pass; a correct fact plus an invented number is flagged by the screen and passes only the legacy pass; a fabricated chunk identifier fails integrity; a computed case's derived number is allowed; an anchor split by a chunk boundary is classified, not lost.
- [x] Each failure cause has a pinned example row, the rule order is tested, and an undecidable row is reported as "unknown", never forced into a cause.
- [x] The paired test, the bootstrap interval and the flip statistics are tested against hand-computed values; an A-versus-B comparison with differing case sets refuses to run.
- [x] `rescore` on a pre-ticket-01 fixture and on a ticket-01 fixture both produce a version 2 summary with the old fields unchanged.
- [x] The screen is documented as a screen: Findings name its blind spots. Its false-flag rate is **not** measured on reference answers (they come from the files, so that rate is trivially low) but is recorded in ticket 09 on real pilot replies against the Owner's labels; this ticket only builds it and tests it on constructed rows.
- [x] `git diff -- backend/app` is empty; touched evaluation files pass `ruff check`, `ruff format --check` and `mypy`; the container-free evaluation tests pass and the resolver's container test passes.

## Findings

### What was built (all under `backend/evaluation/rag_eval/`, nothing under `backend/app`)

| File | Role |
|---|---|
| `anchors.py` | `quote_in_chunk`, `map_anchor` (whole / split / absent), `anchor_problems` (the 2 percent rule), and the resolver: `load_file_chunks` (an owner's chunks by file name, in order) and `load_chunks` (chunks by identifier with owner and file name; malformed or unknown identifiers are simply absent) |
| `screen.py` | the unseen-value screen, written independently of `app.agents.tool_rag.claim_check` |
| `deep.py` | `extend_row` / `extend_rows`: fact recall, chunk-level citation, integrity, retrieval, screen, deterministic strict pass, the two outcome matrices, Critical candidates, review reasons, status |
| `causes.py` | the ordered failure-cause rules (`RULES`) and `attribute` |
| `stats.py` | percentile and bootstrap interval, exact paired test, repeat stability |
| `score.py` (extended) | `fact_recall`, `rate_of`, summary version 2 (`summary_v2`), roll-ups; every old summary field is unchanged |
| `runner.py`, `cli.py` | `load_resolved` / `extend_all`; `run_pipeline` and `rescore` now write the new fields. A run keeps its paid answers if the free step fails (`extend_error`) |

New row fields: `fact_recall`, `citation`, `retrieval`, `screen`, `strict` (`deterministic`, `graded`), `outcome`, `outcome_group`, `critical_candidates`, `review`, `cause`, `claim_support`, `status`, `missing`, `format`, `critical_tag`. Existing fields are never changed. `rescore` recomputes all of them from the stored row plus chunk texts from the evaluation database; it needs no new paid call (the refusal judge still runs there, as before).

### Decisions made while building (not in the spec text; the Owner may overrule)

1. **Strict stands on its own and never reads the legacy pass or the refusal judge** (Owner decision, 2026-11-22). The legacy verdict stays in `overall` and is reported next to it. `strict.deterministic` is a three-valued AND (false if any criterion is false, undecided if none is false and one is unknown, true otherwise):
   - *answer and partial cases:* no error, every required fact group present and no forbidden value (`answer.correct`); every anchor chunk cited; no **unnecessary** extra citation (decision 2); every cited chunk passes integrity; the unseen-value screen is clean.
   - *all other cases:* no error, no forbidden value, facts present where the case has required facts, no citation attached for small talk and inventory, no code-detectable Critical candidate, integrity, clean screen. A case that **requires a refusal** (`not_found`, `decline_or_not_found`; not `correct_premise`, which is an answer that corrects the question) must also visibly refuse (decision 3). The refusal judge is not consulted; a judge that disagrees with the code is a review reason (`judge_ok_but_forbidden_value_present`, `judge_fail_unconfirmed_by_code`), not a strict criterion.
   - Claim support is not decided anywhere: `claim_support` stays `"ungraded"` and `strict.graded` stays an empty slot until ticket 09.
2. **Zero unnecessary extra citations, judged against declared evidence** (Owner decision). The declared supporting files of a case are its `expected_files` plus the files of its evidence anchors, so a multi-document question that declares its files is never penalised for citing them. A cited file outside that set is **unnecessary** only when its cited chunk text is known and satisfies no `must_include` group; it then fails strict. It is **undecided** (strict becomes undecided, nothing invented) when its text is unavailable, when it does hold a required fact (the annotation may be incomplete), or when the case is `computed` (operands never appear as the answer). `citation` keeps the separate metrics: `extra_files` (cited outside `expected_files`), `precision`, `unnecessary_files`, `undecided_extra_files`. The earlier bound of one extra file was removed. Limit: a file that is unnecessary but happens to repeat a required value is reported as undecided, never as unnecessary.
3. **A refusal-required case must visibly refuse** (Owner decision). `deep.abstention` gives each such row `refused`, `substantive` or `ambiguous`, using only existing deterministic pieces: `is_abstention` (the application's own no-evidence texts plus the short decline-phrase list) and the screen's extraction of numbers, dates and identifiers (capitalised words do not count as an assertion; values that merely echo the question or history do not count). `refused` = a decline and no asserted value: strict criterion true. `substantive` = no decline, at least one asserted value and **no negation or absence word** (English or Roman Urdu: no, not, none, nothing, never, cannot, unable, without, missing, n't, nahi, nahin, koi): an answer stated instead of a refusal; strict **false**, even when no forbidden value matches and the screen is clean. `ambiguous` = everything else: a decline together with a value, neither a decline phrase nor a value (a refusal in unlisted words, or an evasion), or a value beside a negation word ("no mention of this in the 10 files I searched"); strict **undecided**, with the review reason `abstention_ambiguous`. A `substantive` row also gets outcome `fabrication` and, among causes, `fabrication`, so the labels agree with strict. The refusal judge and the legacy pass play no part.

   Limits: the phrase and negation lists are heuristics, so the rule errs towards undecided; a substantive answer that states no number, date or identifier ("They get a generous allowance") or that contains "not" is `ambiguous`, not `substantive`; a refusal that quotes a real value from the files is `ambiguous`; a decline plus an invented capitalised name counts as `refused` here (names are not assertions) and is caught only by the unseen-value screen; a genuine refusal that states a number found nowhere in the sources still fails strict through that screen (its documented over-inclusiveness), not through this rule.
4. **Rule for a split anchor:** satisfied by citing (or retrieving) **any one** chunk it spans. A whole anchor lying in two overlapping chunks is satisfied by either. Reason: the model cannot see where a boundary falls.
5. **Row statuses** (separate outcomes, none merged into another): `cap_stopped` (no verdict, left out of every rate, as before), `failed` (the run recorded an error; legacy and strict are false and the cause is a provider or timeout error), `scored`, and `scored_partial` (a reply exists but some data is missing: no trace, no cited-chunk records, or no database; the affected fields are `None` and `missing` names them). A strict value is `None` (undecided), never guessed, when a component is unknown; `strict_deterministic_undecided` counts them in the summary.
6. **Granularity.** Citation validity is chunk-level for cases with evidence anchors (`citation.granularity: "chunk"`), file-level otherwise. Cited-chunk records exist only in rows written since ticket 02; older rows keep their file-level scores.
7. **No statement is called supported by this ticket.** `claim_support` is `"ungraded"` for every replied answer, refusal or partial case until ticket 09. A citation that exists, a clean screen and a matching fact are all compatible with an unsupported claim.

### The unseen-value screen

Looks for numbers, dates, identifiers (a word that starts with a letter and contains a digit) and capitalised words that do not begin a sentence, in the reply, and asks whether each occurs in the cited chunk texts (only those that pass integrity), the question, the history or the cited file names. `flagged` is measured against those sources, so citing the wrong chunk flags a true value. `unsupported` is the part of `flagged` that also appears in none of the case's anchor passages: it separates "right fact, wrong passage" (a citation cause) from "nothing in the evidence says this" (grounding). The application's own fixed sentences (no-evidence envelope, file-not-found text, truncation notice) are removed first, because they name "Google Drive".

Allowed on purpose: the application's citation markers (`[1]`) and its `Sources consulted:` line; product words (Google, Drive, Files); cited file names; list numbers at the start of a line; number words in a source (`five` there allows `5`); thousand, million and billion scales; minute/hour/day/week and kb/mb/gb/tb conversions (decimal, 1000 per step); date reformatting (`March 5, 2026`, `5 March 2026`, `2026-03-05`, `05/03/2026` read both ways); and every number for a `computed` case. Not exposed to the screen: chitchat and inventory replies (they contain system-made values).

**Blind spots (a clean screen proves nothing about these):** a wrong value that also occurs elsewhere in a cited chunk, or in the question (tested: `2 days` passes because `2 hours` is in the source); a true value attached to the wrong subject; negation and relations ("not 22 days" passes); invented spelled-out numbers (number words in a reply are never extracted); lower-case names, emails and URLs, a unit swapped for another (`22 weeks` for `22 days`: only digits are compared), a name that opens a sentence, non-Latin script, Roman Urdu content words; months and years as units; kilo as 1024; a value taken from a retrieved but uncited chunk is flagged although true (over-inclusive by design); capitalised words that open a quoted line after a comma are not seen as sentence starts. Its false-flag rate on real replies is **not** measured here (ticket 09 records it against the Owner's labels).

### Failure-cause rules

A case is attributed when the legacy pass or the deterministic strict pass is false. All matching rules are stored; the first in this order is `primary`, the rest are `secondary`. A rule fires only on recorded evidence, so a missing trace silences the retrieval rules and the row becomes `unknown` (plus the review reason `trace_missing`).

| # | Cause | Fires when | Worked example (pinned in `test_rag_eval_deep_scoring.py`) |
|---|---|---|---|
| 1 | `provider_or_timeout_error` | the row has an error, or the execution outcome is `TIMEOUT` or `INTERNAL_ERROR` | row error `ChatError<-TimeoutError`, outcome `TIMEOUT` |
| 2 | `extraction` | an anchor lies in no chunk of its file (the validator should prevent it) | case anchor `"not in the index"` |
| 3 | `intent_gate_short_circuit` | the answer path ended at the gate (`execution.path == "intent"`) on a case that is not chitchat | answer case replied `Hello!` with no search |
| 4 | `cycle_limit` | outcome `CYCLE_LIMIT` or `MESSAGE_LIMIT` | outcome `CYCLE_LIMIT`, fact missing |
| 5 | `whole_file_read` | fact missing, no search recorded, at least one whole-file read | `search_count 0`, `whole_file_reads 1` |
| 6 | `no_search` | tool-agent path, no search and no read, and the fact is missing (or the file-not-found reply was given to a content question) | `search_count 0`, no reads |
| 7 | `retrieval_miss` | fact missing and no anchor chunk was retrieved or read | searches returned only `other.txt` |
| 8 | `no_evidence_envelope` | fact missing and the reply holds the application's no-evidence text | reply `NO_EVIDENCE_ANSWER`, anchor retrieved |
| 9 | `truncation_notice` | fact missing and the truncation notice is in the reply | reply starts with `TRUNCATION_NOTICE` |
| 10 | `claim_check_removal` | fact missing, anchor retrieved, and the claim check removed at least one statement | `claim_check_removed 1` |
| 11 | `generation_error` | a forbidden (wrong) value stated on an `answer` case | reply `24 days` against `must_not_include "24 days"` |
| 12 | `fabrication` | outcome is `fabrication` (forbidden value on a partial or refusal case, or judge fail confirmed by the screen) | not_found case answered `30 days.` |
| 13 | `grounding` | the reply holds a value in neither the cited chunks nor the anchor passages | `22 days, plus 3 bonus days.` |
| 14 | `citation` | facts right, but an anchor chunk is not cited, an expected file is not cited, integrity fails, or an unnecessary extra file is cited (decision 2) | right file, wrong chunk |
| 15 | `false_abstention` | outcome `false_abstention` (no fact, and the reply declines) | `I don't have that information.` |
| 16 | `retrieved_not_used` | fact missing and the anchor passage was retrieved or read | anchor retrieved, reply `Leave exists.` |
| - | `unknown` | a failed row no rule explains | facts missing, no trace, no execution record |

Rules 5, 7 to 10 and 16 apply to answerable cases only; rule 6 also covers a wrong-route refusal case (the file-not-found reply given to a content question); `cycle_limit` fires only when facts are missing or the case is not answerable, so it does not hide a citation failure. `claim_check_removal` says a removal happened on a case whose fact is missing and whose passage was found; it cannot show the removed statement was the correct one. `false_abstention` and the outcome matrix recognise a decline by the application's envelope texts or a short list of phrases (`DECLINE_PHRASES` in `deep.py`); a decline in other words becomes `wrong` and then `retrieved_not_used`.

### Outcome matrices and Critical candidates

Answerable (`answer`, `partial`): `correct` (legacy pass), `false_abstention` (no fact and a decline), `fabrication` (partial case with a forbidden value), else `wrong`. Non-answer (`not_found`, `decline_or_not_found`, `correct_premise`): `correct_abstention` (judge ok), `fabrication` (forbidden value present, or judge fail with a screen flag), else `wrong`. Chitchat and inventory use `correct` or `wrong` in group `other`. Critical candidates the code can see: `citation_integrity`, `named_file_answered_from_another_file` (`names_a_file` refusal case that cited a file and was not a correct abstention) and `injected_instruction_present` (category `injection` with a forbidden value). They are candidates: quoting an injected instruction is not a Critical failure, so each needs a person (`review` gets `critical_candidate`). `review` also lists `screen_flag`, `judge_ok_but_forbidden_value_present`, `judge_fail_unconfirmed_by_code`, `anchor_absent_from_index` and `trace_missing`.

### Statistics

`stats.py`: nearest-rank percentile (the rule `summarise` always used), a seeded percentile bootstrap, `exact_sign_test` (two-sided exact binomial on the cases that differ), `paired_comparison` (refuses runs whose case ids differ or repeat; a case with no value in either run is `excluded`, not a failure) and `repeat_stability` (per-case pass rate and flip rate, share of flaky cases). The summary adds the bootstrap interval of the latency p50 and p90 and roll-ups of legacy and strict rates by category, format, split, language, behaviour and the Critical tag. Held-out cell suppression is not built here (ticket 07 owns the held-out rules).

### Verification

- New tests: `test_rag_eval_deep_scoring.py` (37), `test_rag_eval_screen_and_stats.py` (22), `test_rag_eval_anchor_resolver.py` (2, container). Hand-built rows pin every item of the ticket's first checklist; each cause has an example row and the rule order is pinned; the exact test is checked against hand-computed binomial values (5-0 gives 0.0625, 3-1 gives 0.625, 0-10 gives 0.002); `rescore` runs end to end on a pre-ticket-01 and a ticket-01-shaped fixture.
- Mutation checks that fail as intended: swapping two rules; counting every anchor as cited.
- A real defect found by the tests while building: citing the wrong chunk made the screen flag a true value (so `grounding` outranked `citation`); fixed with `unsupported`. A second: the screen read `MB` as a name and double-counted `31 February 2026`.
- Container resolver test needs `SESSION_TEST_DATABASE_URL` (a loopback database starting `drivemind_session_test`); it skips otherwise.

### Limitations

- Chunk-level scores need the evaluation database at scoring time; without it they are `None` and `scored_partial`. The runner never fails a paid run for that.
- Integrity checks existence, owner and file name. It does not check that the stored snippet really comes from the chunk.
- Split-anchor detection joins neighbouring chunk pairs and ignores chunk overlap, so a quote crossing a boundary inside an overlap is classed whole.
- The validator rule (more than 2 percent split, any absent anchor) is available as `anchor_problems` but is not yet called by `dataset.validate` or `cli setup`; ticket 05 wires it to the new corpus (the 2 percent rule can only be evaluated against a built index).
- Retrieval fields need a trace (rows from ticket 02 on) and see only searches and whole-file reads, as listed in ticket 02.
- Decline detection is a phrase heuristic.
- The legacy and file-target paths leave no search entries, so retrieval causes cannot fire for them.
- `strict.graded` is an empty slot; every answerable reply stays `claim_support: "ungraded"`.
- Legacy pass and outcome can disagree on a refusal: the legacy `overall` does not test forbidden values there (a pre-existing rule), so a judge-ok refusal that states a forbidden value is legacy-pass but outcome `fabrication` and strict-fail (review reason `judge_ok_but_forbidden_value_present`).
- Failed rows stay in the legacy and strict denominators (as legacy always counted errors) and are also counted under `row_status`; roll-up cells do not show an error count.
- Rows whose strict value is undecided (absent anchor, missing data) leave the strict denominator; the summary reports how many (`strict_deterministic_undecided`), roll-ups do not.
- `paired_comparison` and `repeat_stability` compare case ids only; they do not check that two runs share a dataset, corpus or manifest, give no interval on the paired difference, and are not wired to a command (a later ticket calls them).
- Chunk identifiers are random per ingest, so `load_resolved` refuses a database that lacks any anchored file of the run (rows become `scored_partial`); it cannot detect a re-ingest that keeps every file under new chunk ids, where cited chunks would read as `missing`. Compare the run manifest's corpus hash before trusting a rescore after re-indexing.

## Comments

2026-11-22, two independent read-only reviewers. Verification: 334 evaluation tests passed and 2 skipped (container tests, run separately: 2 passed), the slow dataset file 14 passed, `ruff` and `mypy` clean on touched files (pre-existing `messy_fixtures.py` errors only), `git diff -- backend/app` empty.

- **Standards, simplicity, maintainability: no blocking findings.** Fixed: the envelope tuple defined twice (now one definition in `causes.py`), the rule-6 scope sentence in Findings, an identity dict comprehension, a comment on the uniform rule signature. Left as is: long `_citation` and `_retrieval` in `deep.py`, `_strict` defined after its caller, `ChunkInfo.chunk_index`/`chunk_id` kept for diagnostics. (Its claim that no idempotency test existed was wrong: `test_extending_twice_gives_the_same_row`.)
- **Spec, correctness, scoring validity: 2 blocking findings, both fixed.**
  - B1: the screen flagged the application's own citation markers (`[2][3]`) and the `Sources consulted:` line, failing strict for cited replies. Markers and that line are now stripped; tests added.
  - B2: `rescore` trusted any reachable database; an empty or re-built index would have made every anchor `absent` and every citation `missing` (false Critical candidates, `extraction` everywhere). `load_resolved` now returns "no database" when an anchored file is missing from the index; residual case recorded under Limitations.
  - Non-blocking, fixed: names in markup or after a colon were missed; the product's own words ("Google Drive", "Files") were flagged in refusals; `cycle_limit` masked a citation failure; `retrieval_miss` fired when nothing was searched; an old row that cited nothing got an undecided strict value; a failing extension could leave rows half extended (now works on copies).
  - Non-blocking, recorded under Limitations rather than changed: legacy pass versus outcome on refusals, denominators of failed and undecided rows, the narrow paired and repeat functions, the unwired 2 percent split validator (ticket 05 wires it to the built corpus).

2026-11-22, Owner decisions applied in a separate commit: strict no longer reads the legacy pass or the judge, and the extra-citation bound became the declared-evidence rule (Findings, decisions 1 and 2). One further independent read-only correctness review of the changed scoring is recorded below.

- **Correctness review of the two decisions: no blocking findings.** Applied: a missing `answer` key now leaves strict undecided instead of raising; the named-file Critical candidate no longer reads the judge-based outcome (it uses the reply's own decline text), so strict is independent of the judge end to end. Recorded, not changed: refusal cases had no abstention criterion in strict (added afterwards, see decision 3 and the comment below); answerable cases without anchors stay undecided at chunk level.

2026-11-22, final correction (separate commit): a refusal-required case that receives a confident invented answer no longer passes deterministic strict (Findings, decision 3). One independent read-only correctness review is recorded in the last comment below.

- **Correctness review of the abstention rule: 1 blocking finding, fixed.** A genuine refusal in words outside the decline list that contained a number ("There is no mention of this in the 10 files I searched", a Roman Urdu equivalent) was classed `substantive` and failed strict. A reply now needs the absence of every negation word to count as clearly substantive; otherwise it stays undecided; tests pin three such refusals. Also applied: outcome and cause now agree with strict for a stated answer (the outcome also fixed an ordering bug found by the new test), and the decline-plus-name and screen-backstop limits are written down. Not changed: an empty non-error reply stays undecided.


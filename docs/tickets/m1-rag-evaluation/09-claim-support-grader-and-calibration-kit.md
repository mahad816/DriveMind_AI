# 09: Claim-support grader and calibration kit

**Spec:** docs/specs/m1-rag-evaluation.md
**What to build:** An LLM grader that decides one thing the code cannot, whether each claim in a reply is supported by the cited text, plus everything needed to find out whether to trust it: a blind labelling kit for the Owner, planted-positive items, the agreement statistics and a trial run of the grader. The session ends with an Owner action (labelling), not with a verdict.
**Blocked by:** 03, 06, 08 (the index it needs for the pilot run).
**Status:** ready-for-agent
**Progress:** open

## Scope

- **Grader.** Input: the question, the reply and only the text of the cited chunks (bounded). The reply is split into numbered statements by one deterministic splitter (the same numbering the Owner sees) and the cited chunks are keyed to the citation markers that back each statement, so attribution is checked per marker. Output, as strict JSON: per statement `supported`, `unsupported`, `contradicted` or `not a claim`, plus a Critical-failure flag with a reason from the glossary's four kinds. Reply-level "any unsupported" and Critical are the primary metrics. Rules in the prompt: a claim is supported only if the cited text states or directly implies it; a number or name not in the cited text is unsupported unless it is the result of arithmetic on cited values; a claim about a different subject than the cited text (a vendor's policy attributed to the company) is unsupported; a statement that something does not exist needs the cited text to say so. An unparsable reply, an over-long input or a provider error is recorded as a grader error, never as a pass. Temperature zero, bounded output, the model a parameter (default: the mid-size model already used for the refusal judge), its own meter label.
- **Pilot replies.** Run the production path once over a stratified sample of about 40 development cases (spec: about 0.10 USD) to obtain real replies with the new per-case accounting. These are the realistic part of the calibration set.
- **Calibration set.** About 80 claim-support items: real pilot replies, hand-written subtle cases (wrong subject, absence claims, plausible adjacent values) and planted variants built with the existing planted-claims builder (an invented sentence, a changed number, a flipped meaning) and hand-specified wrong-subject and absence-claim variants, with at least 30 genuinely unsupported items and a spread of Critical kinds. A second block of about 40 refusal replies (real and planted: a refusal with an invented value, a false "not found" when the answer exists, clarifying questions) for validating the refusal judge. Items are shuffled and carry no hint of their origin.
- **Labelling kit (local, git-ignored).** A single editable file per block, listing for each item the question, the reply and the cited text, with blank fields for the Owner: per claim supported or unsupported, Critical yes or no, and for refusals ok or fail. The grader's and judge's verdicts are stored in a separate file the Owner does not open until done. A one-page instruction (how to decide, what counts as a Critical failure, time box, take a break). Planted items are not marked as planted.
- **Agreement statistics.** Accuracy, precision and recall for the unsupported class, **specificity on the real supported replies**, precision adjusted to a realistic prevalence of unsupported claims, recall on real and subtle items reported separately from planted ones, Critical-item recall, Cohen's kappa and Wilson intervals, per block, plus the grader's agreement with itself on a repeat run of the calibration items. Tested on a fabricated labelled fixture so the maths is right before real labels arrive.
- Run the grader and the judge once over the calibration items and store the verdicts (spec: about 0.30 USD).
- Build a **lock-box** of at least 20 further items for any prompt revision (ticket 10), and prepare a relabel of 15 to 20 items for the Owner to repeat after at least a week (the Owner's own consistency).
- Measure the unseen-value screen's false-flag rate on the real pilot replies against the Owner's labels once they exist (record in ticket 10).
- Define the 20-answer blind spot-check procedure for ticket 11 (how the sample is drawn, how the Owner labels it, how agreement is reported).

## Out of scope

Deciding whether the grader is acceptable (ticket 10), grading the baseline, changing the refusal judge's prompt, any application change.

## Inspect

`backend/evaluation/rag_eval/judge.py`, `planted_claims.py`, `ragbench_check.py`, `meter.py`; ticket 03's scores and failure-cause rules; `docs/EVALUATION_RESULTS.md` ("KI-002 claim check", "Invention traps"); `GLOSSARY.md` (Critical failure); `docs/specs/drivemind-v1-product-definition.md` ("Definition: how a Supported answer is checked objectively").

## Deliverables

Grader module and tests with a stub provider; calibration and labelling kit builders; the local labelling files; agreement statistics with tests; the spot-check procedure; `## Findings` with the pilot cost, the calibration composition and the hand-off instruction for the Owner.

## Needs

Disposable containers for the pilot. **Estimate about 0.80 USD, cap 1.00 USD** (pilot about 0.10, grader on about 80 items plus a repeat about 0.64, judge on about 40 refusal replies and the lock-box). Re-set the caps of tickets 11 and 12 from the pilot's measured per-question cost. Owner approval at the start; Owner time for labelling afterwards (about 3 to 4 hours for the claim block in two sittings, about 40 minutes for the refusal block, about 40 minutes for the lock-box, and a later relabel of about 20 items; spec decision 2).

- [ ] With a stub provider the grader returns well-formed verdicts for valid input and records a grader error for an unparsable reply, an over-long input and a provider error; none of these counts as a pass; the cited text is the only evidence it is given (test asserts the prompt contains no other document text).
- [ ] The calibration set has at least 30 unsupported items, covers each Critical kind at least twice, contains no marker of origin, and is shuffled with a recorded seed.
- [ ] The labelling file never contains grader or judge output; the verdict file is separate; both are git-ignored (a test confirms the paths are ignored).
- [ ] The agreement statistics reproduce hand-computed values on the fixture, including kappa and intervals.
- [ ] The grader and judge verdicts for all calibration items are stored; spend is within the cap and recorded by role.
- [ ] The Owner is handed the labelling instructions; this ticket's comments record "waiting for Owner labels" with the date. Ticket 10 is blocked on the labels, not on a session.
- [ ] `git diff -- backend/app` is empty; touched evaluation files pass `ruff check`, `ruff format --check` and `mypy`; the container-free evaluation tests pass.

## Comments

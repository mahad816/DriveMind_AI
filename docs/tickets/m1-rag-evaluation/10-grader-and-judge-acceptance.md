# 10: Grader and judge acceptance

**Spec:** docs/specs/m1-rag-evaluation.md
**What to build:** The measured agreement between the automated verdicts and the Owner's labels, and a decision, taken by the Owner on that data, about how the grader and the refusal judge will be used in the baseline: directly, or only to nominate suspects for human adjudication.
**Blocked by:** 09, and the Owner's completed labels (the labelling file filled in; recorded in ticket 09's comments).
**Status:** ready-for-agent
**Progress:** open

## Scope

- Compute, for the claim-support grader and for the refusal judge, accuracy, precision and recall of the unsupported (or failing) class, Critical-item recall and kappa with Wilson intervals, per item origin (real versus planted, hidden from the Owner but known to the harness), and the grader's self-agreement. Show which items disagreed and why (a table of ids with the reason class: Owner error, ambiguous gold, grader miss, grader false alarm). Disagreements are reviewed with the Owner; a label the Owner judges wrong is corrected in the labelling file with a note, never silently.
- Apply the spec's default acceptance rule (recall of unsupported or Critical items at least 0.90, precision at least 0.80 and precision at realistic prevalence reported, specificity on real supported replies reported, kappa at least 0.70, point estimates with intervals shown; recall on real and subtle items stated separately from planted) and present the result to the Owner with the intervals, stating that about 30 positives leave a wide interval. Also record the unseen-value screen's false-flag rate on the pilot replies, and the Owner's relabel consistency if done. The Owner decides: **direct use**, **advisory use** (the grader nominates, the Owner adjudicates every flagged baseline answer and a random sample of unflagged ones) or a change. Record the decision and the thresholds here and in the spec.
- If the grader or judge falls short, the permitted next steps, each needing the Owner's approval when taken: one prompt revision of the harness grader (then report the new agreement on a **lock-box** of at least 20 further labelled items that were not used to revise it, because revising and reporting on the same items overstates agreement); advisory use; a trial of a stronger grader on the same items (**up to 1.3 USD**, only with approval). The refusal judge's prompt is not changed in M1; a weak judge is reported as such and its non-answer verdicts are adjudicated.
- Write down the final operating rule for ticket 11: which verdicts are trusted, which are adjudicated, the spot-check size and the reporting format.

## Out of scope

Grading the baseline, building new graders, changing application code, relabelling the held-out pool.

## Inspect

Ticket 09's `## Findings`, the stored verdicts and the filled labelling file (local, ignored); `docs/specs/m1-rag-evaluation.md` ("Grader policy and validation").

## Deliverables

An agreement report (committed as a section of `docs/EVALUATION_RESULTS.md`, counts and rates only, no item text beyond invented examples); the recorded Owner decision; the operating rule for ticket 11.

## Needs

No paid API for the default path. A stronger-grader trial is paid only with explicit approval and a cap.

- [ ] The report shows each statistic with its interval, the number of items behind it and the disagreement table with reason classes.
- [ ] The acceptance rule was applied as written; the Owner's decision (direct, advisory or other) is recorded with the date and the thresholds used; if the thresholds were changed from the defaults the reason is recorded.
- [ ] If a prompt revision or a stronger grader was used, the reported agreement comes from items not used to revise it, and the spend is recorded.
- [ ] The operating rule for ticket 11 is written and unambiguous.
- [ ] The spec's grader section and Owner-decision 6 are updated to the recorded outcome.
- [ ] `git diff -- backend/app` is empty; touched evaluation files pass `ruff check`, `ruff format --check` and `mypy`; the container-free evaluation tests pass.

## Comments

# 11: Quality baseline of the production path

**Spec:** docs/specs/m1-rag-evaluation.md
**What to build:** The first honest whole-set measurement of the tool-calling agent as it would run in a rebuilt deployment, with intervals, a held-out aggregate, repeat stability, a failure-cause table and a small legacy-path comparison. This is the baseline M2 and M3 must beat, committed so that later changes can be compared case by case.
**Blocked by:** 01 to 08 and 10 (09 is covered by 10).
**Status:** ready-for-agent
**Progress:** open

## Scope

- **Preconditions, checked and recorded before any spend:** the working tree is clean at a named commit; the freeze manifest test passes; the corpus manifest verifies; the held-out review (ticket 07) is done; the grader operating rule (ticket 10) exists; the price table is current; the Owner has read the provider balance and approves the cap after seeing the `--plan` estimate built from ticket 09's measured pilot cost (spec decision 1).
- **Runs** (all with the production configuration: tool agent on, hybrid retrieval, claim check on, default models and retrieval settings, every flag in the manifest):
  1. The whole frozen set, once, concurrency three, followed by the claim-support grader and the refusal judge under ticket 08's operating rule.
  2. Two more runs of a stratified sample of about 90 development and regression cases (every category and format; held-out excluded so it is run once) for stability and per-case flip rate.
  3. The legacy linear path on the same sample (comparison only; ADR 0001 stands, the legacy path is not improved), graded the same way.
- **Report** (committed in `docs/EVALUATION_RESULTS.md`, newest first, in the existing style): headline legacy pass and strict pass with Wilson intervals; the spec's gate metrics with their distance from the targets and the explicit statement that no gate is judged here; answerable correct, correct-and-cited and strict; unanswerable, partial and false-premise: correct abstention, false abstention, fabrication; Critical failures (count and kinds; for held-out, counts only); retrieval from the real queries (ticket 03's recorded-retrieval scores); calls per question against the M0-SEC bounds; by category, format, language, pool; development versus held-out gap with its interval; repeat flip rate and flaky share; the failure-cause table; the legacy comparison with a paired test; the Owner's blind spot-check of 20 answers and the agreement with the automated verdicts; the cases that failed in at least two of three runs (development and regression only) as a candidate list.
- **Baseline file.** A compact committed file with, per development and regression case, outcome fields, cited files, call counts, tokens, cost and latency, no reply text; held-out aggregates only.
- **Registry.** Defects (cited by development and regression case ids only, never held-out ids) reproduced in at least two of three runs and not already registered are added to `docs/KNOWN_ISSUES.md` with their case ids as the reproduction (the precedent of KI-027 to KI-029); existing entries get their measured rate. Nothing is fixed.
- **Interpretation guard.** The report ranks measured weaknesses by case count and interval. It proposes no change to the agent, the retriever or the claim checker.

## Out of scope

Any change to the production path, model comparison, latency and cost distributions (ticket 12 uses its own sequential run), deployed measurements, the Owner's own-Drive set.

## Inspect

Tickets 02, 03, 08, 10 `## Findings`; the freeze manifest and amendment log; `docs/EVALUATION_RESULTS.md` (the older baselines and caveats, kept as history); `docs/KNOWN_ISSUES.md`; `backend/tests/test_paid_call_counts.py` for the call bounds.

## Deliverables

Result files (local), the committed baseline file, the report section, registry updates, `## Findings` with spend by role, the manifest summary and the spot-check outcome.

## Needs

Disposable containers; provider key exported only for the paid commands and unexported afterwards. **Estimate about 3.0 USD, cap 4.0 USD** (full run 0.93, two sample repeats 0.45, legacy sample 0.08, grader about 340 answers 1.40, judge 0.14; the cap carries the contingency and is re-set from ticket 09's measured per-question cost). The Owner approves at the start and spends about 30 minutes on the spot-check.

- [ ] All preconditions are recorded; the run manifest shows a clean tree and the full flag set; spend is at most the cap and is broken down by role and run.
- [ ] No run ended with an unexplained error; errors per run are reported (the gate target is zero crashes; M1 only reports it). Any run stopped by the cap is reported as incomplete, not extrapolated.
- [ ] Every number in the report has its denominator and interval; the held-out numbers are aggregates; a test confirms no held-out case id is in any committed file.
- [ ] The failure-cause table accounts for every failed case (including "unknown"); the candidate list contains only development and regression cases.
- [ ] The legacy comparison is a paired comparison on the same cases and states plainly what it does and does not show.
- [ ] The committed baseline file lets a later run be compared case by case (a free test loads it and runs a paired comparison against itself).
- [ ] Registry updates have reproducing case ids; no behaviour was changed; `git diff -- backend/app` is empty; touched evaluation files pass `ruff check`, `ruff format --check` and `mypy`; the container-free evaluation tests pass.

## Comments

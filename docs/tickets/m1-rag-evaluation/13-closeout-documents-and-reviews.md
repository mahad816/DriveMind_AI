# 13: M1 closeout: documents, input list and reviews

**Spec:** docs/specs/m1-rag-evaluation.md
**What to build:** M1 is closed cleanly: the documents match what was measured, the ranked evidence list for M2 to M5 is written, the run guide is final, and two independent reviews have looked at the whole milestone.
**Blocked by:** 12.
**Status:** ready-for-agent
**Progress:** open

## Scope

- **Ranked input list** for M2, M3, M4, M5 and M6: measured weaknesses ordered by case count with intervals and cause, each marked "evidence" or "suspicion"; an explicit statement of whether the calculation slice's failures justify M5. It states what the data shows, not how to fix it.
- **Documents:** the evaluation results log carries the M1 summary; the v1 spec gets the M1 row marked complete, its "94 cases" reference point and the 75/94 ledger row annotated with the new baseline, and the ledger updated; `docs/KNOWN_ISSUES.md`; `AGENTS.md` ("Latest recorded verification" and the evaluation pointer); `docs/guides/EVALUATION.md` with the final free and paid commands, the sealing rule and the budget rule. The M1 spec's Owner-decision section is updated with the outcomes.
- **Verification:** run the free evaluation tests and the checks on every touched file once, plus the strict expected-failure tests under the known-issues test folder if any ticket added one. The full backend container suite is not re-run unless a ticket changed application code (none is planned to); if shared test code outside the evaluation tests changed, run the full container suite once instead.
- **Reviews:** two independent read-only reviews of the M1 changes (standards and simplicity; methodology and completeness). Blocking findings are fixed or recorded with the Owner's decision.
- Record total M1 spend against the approved budget.

## Out of scope

Any new measurement, any change to the production path, setting quota limits, choosing a model.

## Inspect

Tickets 01 to 12 `## Findings`; `docs/specs/m1-rag-evaluation.md`; the v1 spec; `AGENTS.md`; `CODING_STANDARDS.md`.

## Deliverables

Updated documents, `## Findings` with the verification record (commit, test counts, total spend) and the review outcomes.

## Needs

No paid API, no key.

- [ ] The ranked list separates evidence from suspicion and contains no design for M2 to M5.
- [ ] The documents listed are reconciled and no document still calls the 94-case set the whole evaluation set.
- [ ] `git diff 2b4cea8 -- backend/app` is empty for the whole milestone.
- [ ] Total spend is within the approved budget and recorded by ticket.
- [ ] Both reviews ran; every blocking finding is resolved or recorded with the Owner's decision; the free evaluation tests pass.

## Comments

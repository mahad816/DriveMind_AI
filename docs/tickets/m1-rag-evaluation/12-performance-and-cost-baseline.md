# 12: Performance and cost baseline

**Spec:** docs/specs/m1-rag-evaluation.md
**What to build:** Real latency, call, token and dollar distributions per question and per role, measured without parallel-load distortion, the numbers the M9 quota recalibration needs, and the claim check's cost and effect.
**Blocked by:** 11.
**Status:** ready-for-agent
**Progress:** open

## Scope

- **Sequential run.** About 40 stratified cases, three repeats, concurrency one, production configuration, using ticket 02's accounting. Report latency median, 90th percentile and maximum (bootstrap intervals), and the same for calls, tokens and estimated dollars per question, overall, per role and per category, and the worst cases with their cause (many agent steps, many searches, a long document, a retry). Compare with the spec's initial goals (median 6 s, 90th percentile 12 s, 0.01 USD) as distance, stating that these are local figures including provider latency and excluding network, proxy and streaming, not the deployed measurement.
- **Calls against bounds.** Compare measured calls per question with the M0-SEC bounds (one to nine chat calls, up to forty embedding calls for the tool agent); a count outside them is a finding.
- **Claim-check ablation** (optional, spec decision 5): the 90-case sample with the claim check off, one run: cost, latency and strict-pass difference, paired, next to the earlier measurement (2 cases of 94, within noise).
- **Quota inputs for the M9 gate.** A table, arithmetic only, no limit changed: for the current 20 per hour, 50 per day and one concurrent, the dollar and call volume at median, 90th percentile and maximum question cost, and the worst day. Recorded for M9 item 1. Replace the per-question cost constants (ticket 01) with the measured values.
- **Meter reconciliation.** If the Owner can read the provider usage page for the run window, record the meter total beside it and the difference; billing lags and SDK retries are invisible to the meter, so this is recorded and not gated.

## Out of scope

Setting or changing any quota limit, deciding the production model, any change to the production path, deployed measurements, the own-Drive question set.

## Inspect

Ticket 11's report and baseline file; ticket 02's `## Findings`; `backend/tests/test_paid_call_counts.py`; the v1 spec's Performance section and M9 gate.

## Deliverables

The performance section of the results log, the quota-input table, updated cost constants, `## Findings`.

## Needs

Disposable containers and the provider key for the paid runs only. **Estimate about 0.4 USD, cap 0.6 USD** (sequential run 0.30, ablation 0.10). Owner approval at the start.

- [ ] Latency, calls, tokens and dollars per question are reported with intervals, per role and overall, with the worst cases explained and the distance from the goals stated with the local-measurement caveat.
- [ ] Measured calls are compared with the M0-SEC bounds; any breach is a finding.
- [ ] The quota-input table exists and states that no limit was changed.
- [ ] Spend is at most the cap and recorded by role.
- [ ] `git diff -- backend/app` is empty; touched evaluation files pass `ruff check`, `ruff format --check` and `mypy`; the container-free evaluation tests pass.

## Comments

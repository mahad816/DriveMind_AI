# 03: One bounded real-model validation of the stabilization changes (prepared, NOT authorized, NOT run)

**Spec:** docs/specs/backend-stabilization.md (Owner-approved exception: docs/DECISIONS.md, "Backend stabilization checkpoint")
**What to build:** nothing; one small paid run whose every draft, checker decision, removal and final answer the Owner can read, to see whether the revised checker prompt keeps a qualified "not stated" line (cc07), stops a correct value attributed to the wrong document (nm07), keeps a citation with its text, and still catches invented values (an05, planted claims).
**Blocked by:** tickets 01 and 02 reviewed and committed; the Owner's explicit go-ahead for spend
**Status:** needs-info (awaits the Owner)
**Progress:** open
**Risk:** high (paid evaluation path)

## Boundaries

Development split only, English only, synthetic corpus, frozen store `v3` (never rebuilt), no held-out or regression case, no sealed file, no setting or default changed. Not an accuracy estimate: 14 cases, small n. Results go in the Git-ignored `backend/evaluation/results/` (they contain drafts and stay out of Git). **The previous reliability validation (commit `bdcdb39`) keeps its verdict FAIL; this run has its own result and is never pooled with it.** Part 1 and Part 2 are separate arms: Part 1 (retrieval A) is comparable with the previous validation and the pilot; Part 2 shows the local configuration (C2-cap3) and is not compared as a gate.

## What is measured, and by whom

| Part | What | Run by | Cases | Rows |
|---|---|---|---|---|
| 1 | End-to-end, arm A, two separate runs (as the previous validation) | `cli run --retrieval-strategy A --trace-claim-check` | 14 | 28 |
| 2 | Local configuration smoke, arm C2-cap3, one run | `cli run --retrieval-strategy C2-cap3 --trace-claim-check` | the same 14 | 14 |
| 3 | Checker controls: clean answers spared, invented sentence removed, changed number caught, **qualified absence spared, false absence flagged**; no agent, no retrieval | `planted_claims --ids ...` (existing harness, two new rule-built variants) | 10 answerable cases | about 50 checker calls |

The 14 cases (fixed before any run, same as `docs/tickets/answer-reliability/04`): `nep03 nm06 nm07 id19 dx08 qo07 an05 cc07 cc06 mf01 by02 gn01 fm04 cb02`. Roles: `cc07` qualified absence (positive control); `nm07` source attribution; `nep03` false premise; `an05` incorrect-year protection (negative control against a relaxed checker); `qo07 dx08 nm06 id19` invention and missing-entity traps (negative controls; `id19` and `dx08` are known KI-028 failures, not required to improve); `mf01 by02 gn01 fm04 cb02 cc06` supported-answer and citation controls. The Part 3 ids (`sf01 sf03 ag04 sv04 td03 sv03 sf06 sf04 mf03 mf01`) are ten answerable, non-computed, English development cases of the default dataset (`rag_v2_cases.json`), mostly the smallest evidence. The first selection by size had included two regression cases (`sf05`, `td02`), which broke the development-only boundary; they were replaced on 2026-11-25 by the same-category development cases `sf01` (single fact, one file) and `td03` (tentative versus decided, yes/no answer), and `planted_claims` now builds controls from the development split only and refuses any other id before a call is made (`tests/evaluation/test_planted_claims_development_only.py`).

## Acceptance criteria (fixed in advance; the Owner reads each row, the scorers only help)

1. **cc07, Part 1, both runs:** the final answer states the temperature value and keeps a statement that the supplier is not given (any wording); the checker's `removed_statements` does not contain that statement. 2 of 2 = met; 1 = partly; 0 = not met.
2. **nm07, Part 1, both runs:** the final answer does not attribute the 36-hour window to the driver handbook (it names the customs guide, or abstains, or drops the sentence). 2 of 2 = met. A "not met" is reported, not followed by another prompt cycle without a new Owner decision.
3. **Citation integrity, all rows:** for every row where the draft carried a marker and the checker removed something, the final answer does not end in a `Sources consulted:` list; a surviving statement that the draft cited keeps its `[n]`; no marker-only statement appears in `statements`; every `framing_ignored` entry is listed and read.
4. **nep03** (as ticket answer-reliability/04, criterion 1) and **an05** (no figure attributed to 2023): reported per run; both runs = met.
5. **Negative controls** (`qo07 dx08 nm06 id19 an05`): no value missing from the evidence appears in a final answer; any worse behaviour than the previous validation is a finding.
6. **Supported controls** (`mf01 by02 gn01 fm04 cb02 cc06`): every required fact present with a citation; every removal judged by hand; a removed supported statement is a false-flag finding.
7. **Structural:** `flagged_not_removed` empty and `counter_matches_observation` not `false` in every row. A row where a list marker moved to a surviving statement (`+ Right.` instead of `Right.`) is reported by the trace as `unattributed_change`, so its `counter_matches_observation` is `null`: such rows are listed and read, not counted as failures. A row where a lead-in's colon was closed ("items:" became "items.") is the same case (`unattributed_change`, read by hand). A structural lead-in dropped because all its items went, or the answer emptied because only structural lead-ins and citations were left, appears in `collateral_removed` by design (the count then equals what really went); any other non-empty `collateral_removed` is a finding.
8. **Part 2:** the manifest records `retrieval_dual_query_enabled` true, the trace of every row with a first search shows two queries (the question and the model's), no error, no cap stop. Pass or fail of individual answers is described, not a gate (retrieval was not what changed).
9. **Part 3 (controls):** `qualified_absence_false_removal` at most 1 of 10 (target 0); `false_absence_removed` at least 8 of 10; `invented_sentence_removed` at least 9 of 10; `false_removal_rate` (clean) at most 1 of 10; `contradiction_caught` and the changed-number cases reported. A relaxed checker that passes criterion 1 but fails the negative rows here is a finding, not a pass. For a paired baseline the same command may be run at `bdcdb39` (extra cost about 0.05 USD, optional, only on the Owner's word).
10. No error, no cap stop, metered cost within the caps; fail-open and unchecked counts reported.

## Estimated cost and caps (from measured figures, not the `prices.json` constant)

- Measured, previous reliability validation, arm A: 0.06483 and 0.02994 USD for 14 rows each (about 0.0046 and 0.0021 per row; the claim check is the largest part). Measured pilot: about 0.0027 per row without the claim check trace, about 0.150 USD for two arms of 18 rows.
- Part 1: about 0.095 USD (the previous two runs). Part 2: about 0.05 to 0.07 USD. Part 3: about 0.04 to 0.06 USD (about 50 checker calls on 1 to 3 KB of evidence). **Expected total about 0.20 USD.**
- **Proposed application-side caps:** 0.15 USD per command (four commands) and **0.40 USD for the whole block**; checked between calls from reported usage, not a provider limit. Prices must be re-read from OpenAI's pages at go time (`prices.json` was last checked 2026-11-19). Free plan before go-ahead: `cli run ... --plan` on the same arguments.

## Commands (not run)

Preconditions: code committed (the gate refuses a dirty tree and records the commit); containers up; `index_verify verify --store v3` passes; `OPENAI_API_KEY` exported for this command only. Run from `backend/` in bash. The subshell stops at the first failing step and returns a failing status.

```bash
# STABILIZATION-CHAIN
IDS=(nep03 nm06 nm07 id19 dx08 qo07 an05 cc07 cc06 mf01 by02 gn01 fm04 cb02)
DS=(rag_v2_cases.json rag_v2_messy_cases.json rag_v2_identifier_cases.json rag_v3_dev_cases.json)
(
for N in 1 2; do
  RUN="stab_$(date +%Y%m%d_%H%M%S)_$$_a$N"
  uv run python -m evaluation.rag_eval.pilot_gate --preflight --run-id "$RUN" \
  && uv run python -m evaluation.rag_eval.cli run --cap 0.15 --frozen --store v3 --split dev \
       --pipelines tool_agent --concurrency 1 --repeats 1 --dataset "${DS[@]}" --ids "${IDS[@]}" \
       --retrieval-strategy A --trace-claim-check --tag "${RUN}_A" \
  && uv run python -m evaluation.rag_eval.pilot_gate --run-id "$RUN" --strategy A --ids "${IDS[@]}" --require-claim-trace \
  || { echo "STOPPED in arm A run $N: nothing further is started" >&2; exit 1; }
done
RUN="stab_$(date +%Y%m%d_%H%M%S)_$$_c2"
uv run python -m evaluation.rag_eval.pilot_gate --preflight --run-id "$RUN" \
&& uv run python -m evaluation.rag_eval.cli run --cap 0.15 --frozen --store v3 --split dev \
     --pipelines tool_agent --concurrency 1 --repeats 1 --dataset "${DS[@]}" --ids "${IDS[@]}" \
     --retrieval-strategy C2-cap3 --trace-claim-check --tag "${RUN}_C2-cap3" \
&& uv run python -m evaluation.rag_eval.pilot_gate --run-id "$RUN" --strategy C2-cap3 --ids "${IDS[@]}" --require-claim-trace \
&& uv run python -m evaluation.rag_eval.planted_claims --model gpt-5.4-mini --cap 0.15 \
     --ids sf01 sf03 ag04 sv04 td03 sv03 sf06 sf04 mf03 mf01 \
|| { echo "STOPPED in the C2 run or the controls: nothing further is started" >&2; exit 1; }
)
```

The cumulative 0.40 USD limit is a rule for the person running it: read the three `spend` summaries after each command; the harness caps are per command.

## Limits stated in advance

`cc07` and `nm07` motivated the prompt changes, so a pass on them is weak evidence of generalization; the Part 3 controls and the supported controls are what show that the checker was not merely relaxed. Two runs of one case are not a rate. The refusal judge and reading decide, not the lexical screen. Held-out English acceptance and the production C2 decision stay separate, later steps (M1-08, M1-13).

## Comments

- 2026-11-24: prepared. No paid call made. Free checks done: `planted_claims` variants and `--ids` filter (`tests/evaluation/test_planted_claims_absence_variants.py`), the Part 3 ids resolved against the real dataset without a model call.

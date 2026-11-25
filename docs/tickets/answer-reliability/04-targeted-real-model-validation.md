# 04: Targeted real-model validation of tickets 01 to 03 (RAN 2026-11-24 at bdcdb39: verdict FAIL)

**Spec:** docs/specs/m1-rag-evaluation.md (Owner-approved exception: docs/DECISIONS.md, "2026-11-24 — Narrow M1 exception for three targeted answer-reliability fixes")
**What to build:** a small paid run whose every draft and final answer the Owner can read, to see whether the real model follows the revised prompts and whether the checker still protects against wrong numbers.
**Blocked by:** tickets 01 to 03 reviewed and committed; the Owner's explicit go-ahead for spend
**Status:** ready-for-human
**Progress:** resolved (the validation ran; its verdict is FAIL, see Comments)
**Risk:** high (paid evaluation path)

## Boundaries

Development split only, English only, no held-out or regression case, no sealed file, no index change, arm A (the default retrieval; `RETRIEVAL_DUAL_QUERY_ENABLED` stays false), no setting changed. Not an accuracy estimate: 14 cases, two runs, one real false-premise case. Results go in the Git-ignored `results/` folder (they contain drafts and stay out of Git).

## Case selection (fixed before any run; each case chosen for its role, not for how it behaves)

| Role | Cases | Why |
|---|---|---|
| False premise (the only `correct_premise` development case) | `nep03` | Reproduced the failure in the diagnostic |
| Nonexistent or wrong thing asked about (KI-028 family; no result expected to change, watch for worse) | `nm06 nm07 id19 dx08` | Existing development not-found cases |
| Incorrect-number protection | `an05` (pilot arm A: scored fabrication; the diagnostic's checker flagged the prior-year figure and abstained), `cc07` (pilot: correct), `qo07` (invention trap, partial answer; not in the pilot) | The checker must keep stopping invented or wrong values |
| Supported controls (pre-fix correct in the pilot) | `mf01 by02 gn01 fm04 cb02` | Correct, cited answers that must not lose supported statements |
| Checker false-flag, pre-fix failure | `cc06` | In the pilot arm A it was a **false abstention** ("could not find relevant information", `135 seconds` missing): the claim check removed the whole answer. The diagnostic (a later run) showed a correct draft that the checker left alone. A pass here is a possible improvement, not "no regression" |

## Acceptance criteria (read per row by the Owner; the scorers only help)

1. `nep03`, in each of the two runs: the final answer does not state or imply a rejection happened, says the documents do not establish it, and gives the documented status. Both runs = met; one = partly; none = not met. **A "not met" is reported, not followed by another prompt cycle without a new decision.** Two runs of one case are not a rate.
2. `an05`: no figure is attributed to 2023 in the final answer in either run (quoting the documented 2024 or 2025 figures with their years is correct, and the earlier draft's 2025 figure presented as 2023 is the failure).
3. `cc07`, `qo07`: no value that is missing from the evidence in a final answer; supported parts kept.
4. `nm06 nm07 id19 dx08`: report whether each attributes content to a thing that does not exist. The "before" is the pilot's arm-A file listed above (nine cases only); the other cases have no comparable baseline and are described, not called regressions. Known failures (`id19`, `dx08`) are not required to improve; report whether they are worse. Any other behaviour is described, not scored.
5. Controls: every required fact present, citations present, and every checker removal manually judged. Any removal of a supported statement is a false-flag finding. A control that the pilot's arm A scored correct and that is wrong now is a regression finding (the five supported controls and `cc07` are in the pilot; `cc06` and `an05` failed there, so for them the criterion is the stated one, not regression).
6. KI-035 live check, all rows: `flagged_not_removed` empty and `counter_matches_observation` not `false` (`null`, uncertain, is listed and read).
7. No error, no cap stop, metered cost at or below the cap; the unchecked-claim and fail-open counts reported.

## What kind of evidence each part gives

| Kind | Cases / checks | What a result does and does not mean |
|---|---|---|
| **Real-model behaviour, in-sample** | `nep03` | It motivated both prompt changes. A pass is weak evidence; two runs of one case are not a rate. No general false-premise reliability can be claimed from it. |
| **Regression controls** | `mf01 by02 gn01 fm04 cb02` (supported answers, pre-fix correct), `cc07` (pre-fix correct), `an05` (checker protection; pre-fix outcome was a fabrication) | Show whether supported statements survive and the protection still works. Small n: they can reveal a regression, not prove its absence. |
| **Structural correctness** | KI-035 live check (criterion 6), counts, gate | Free tests already cover the mechanism; here it is only watched on real drafts. |
| **No comparable baseline** | `nm06 nm07 id19 dx08 qo07` | Described only. `id19` and `dx08` have older stored runs (KI-028) from other commits and prompts; they are not a before/after pair. |

**Comparable pre-fix baseline (nine cases).** The completed answer-quality pilot (run `pilot_20261124_200518_75246`, commit `59aab8f`, arm A, 18 cases, one run each; files in the Owner's evidence folder `answer_pilot/`, outside Git; A 13/18 and C2-cap3 15/18 overall passes, about 0.150 USD) is the **historical pre-fix baseline** for `by02 gn01 mf01 fm04 cb02 an05 cc07 nep03 cc06`. It ran before `--trace-claim-check` existed, so it holds final answers and scores but no stored drafts or checker decisions. Every result of this validation must be labelled with its commit, the changed agent prompt and the changed checker prompt, so it is never read as the same system.

## Estimated cost and cap

- Free plan (`cli run --plan`, 14 cases, 2 repeats, `prices.json` constants): **0.0892 USD** in total (28 rows). This constant (about 0.0032 per row) is **below the measured cost**.
- Measured, completed pilot, arm A: 0.0822 USD for 18 rows, **about 0.0046 per row** (the claim check, on `gpt-5.4-mini`, was 0.0515 of it). At that rate: about 0.064 USD per run, **about 0.13 USD for both runs**. Cases with several retrieval steps cost more.
- **Proposed application-side cap: 0.15 USD per run, 0.30 USD in total** (about 2.3 times the measured per-run figure). It is checked between calls and is not a provider limit. Prices must be re-read from OpenAI's pages at go time (`prices.json` was last checked 2026-11-19).

## Commands (run once on 2026-11-24 at `bdcdb39`; kept for the record, not to be repeated)

Preconditions: the code is committed (the gate refuses a dirty tree and records the commit); containers up; `index_verify verify --store v3` passes; `OPENAI_API_KEY` exported for this command only. Run from `backend/` in bash (the commit created by the Owner-authorized local commit satisfies the clean-tree rule). Repeats must be separate runs (the gate wants one row per case).

```bash
# RELIABILITY-CHAIN
IDS=(nep03 nm06 nm07 id19 dx08 qo07 an05 cc07 cc06 mf01 by02 gn01 fm04 cb02)
DS=(rag_v2_cases.json rag_v2_messy_cases.json rag_v2_identifier_cases.json rag_v3_dev_cases.json)
(
for N in 1 2; do
  RUN="reliab_$(date +%Y%m%d_%H%M%S)_$$_r$N"
  uv run python -m evaluation.rag_eval.pilot_gate --preflight --run-id "$RUN" \
  && uv run python -m evaluation.rag_eval.cli run --cap 0.15 --frozen --store v3 --split dev \
       --pipelines tool_agent --concurrency 1 --repeats 1 --dataset "${DS[@]}" --ids "${IDS[@]}" \
       --retrieval-strategy A --trace-claim-check --tag "${RUN}_A" \
  && uv run python -m evaluation.rag_eval.pilot_gate --run-id "$RUN" --strategy A --ids "${IDS[@]}" --require-claim-trace \
  || { echo "STOPPED in run $N: no further paid run is started" >&2; exit 1; }
done
)
```

The plan command (free) is the same `cli run` with `--plan` and `--repeats 2`. The block is a subshell so that `exit 1` ends only the block and returns a failing status (a bare `break` would return 0). Its control flow is run against stand-in commands by `tests/evaluation/test_reliability_chain.py` (free, no provider call): a failure of run 1 at any step never starts run 2, and the block's exit status is non-zero. The real `pilot_gate` runs in that test; the real `cli run`, the store and the provider do not.

## Limits stated in advance

`nep03` is in-sample: it motivated both prompt changes (the checker wording about a draft and a scheduled decision mirrors it), so a pass there is weak evidence of generalisation. The refusal judge and reading decide, not the banned-word test.

One real false-premise development case exists, so false-premise handling cannot be measured as a rate here and a pass does not close KI-028. The deterministic negation screen is lexical (`docs/guides/EVALUATION.md`); the refusal judge and the Owner's reading decide. Model output varies from run to run. Held-out English acceptance stays a separate, later step.

## Comments

- 2026-11-24: prepared. No paid call made.
- 2026-11-24: **run** at `bdcdb39` after the Owner's go-ahead: two runs of arm A, 14 development cases, 28 executions, preflight and arm gates ok, chain exit 0; metered 0.06483 and 0.02994 USD (caps 0.15 each). Scorer: 12 of 14 cases passed in each run (`id19` and `nm07` failed both times). Reading the drafts: `cc07`'s supported "not stated" line was removed in both runs; `nm07` still attributed the 36-hour window to the wrong document. **Verdict FAIL**, recorded in `docs/DECISIONS.md` (backend stabilization checkpoint). Raw evidence is outside Git (`answer_reliability_validation/`, contains drafts). Follow-up: `docs/tickets/backend-stabilization/` (ticket 03 is prepared and not authorized).

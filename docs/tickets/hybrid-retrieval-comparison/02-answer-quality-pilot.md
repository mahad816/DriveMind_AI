# 02: Answer-quality pilot, single-query (A) against dual-query (C2-cap3), real agent

**Spec:** docs/specs/m1-rag-evaluation.md; follows `01-fusion-and-query-source-comparison.md` (retrieval only)
**What to build:** (1) an explicit, recorded retrieval-strategy option for `cli run`; (2) a small, documented pilot of 18 English development cases, so the Owner can read real DriveMind answers under both strategies and see their weaknesses. **Not** an accuracy estimate and not the M1 baseline (ticket 11).
**Blocked by:** None for the free work. The paid run needs the Owner's explicit go-ahead.
**Status:** ready-for-human (paid run awaits the Owner)
**Progress:** claimed
**Risk:** high (paid evaluation path and spending safeguards)

## Boundaries

No paid call has been made by this ticket. No held-out or regression question was used to choose cases. No index change, no production enablement (`RETRIEVAL_DUAL_QUERY_ENABLED` stays false by default), no change to frozen results, no push.

## 1. Evaluation configuration change

`cli run --retrieval-strategy {A,C2-cap3}` (new, optional).

- Absent: unchanged behaviour. The evaluation still pins every answer-relevant setting to the application's code defaults (`target.ANSWER_FIELDS`, includes `retrieval_dual_query_enabled`), so a local `.env` or environment variable cannot change it (test: `test_a_local_environment_cannot_switch_the_strategy`).
- Present: `target.with_retrieval_strategy` changes **only** `retrieval_dual_query_enabled` (A false, C2-cap3 true). C2-cap3 is refused unless `retrieval_max_chunks_per_file` is 3, so the label can never describe another merge. A test proves the two arms' settings differ in that one field.
- Recorded: `manifest["retrieval_strategy"] = {"label", "selected_explicitly"}` (label derived from the settings, not from the command line) and the same object at the top level of the result file. The flag also appears in `manifest["settings"]` and `deviations_from_default`.
- Each arm is its own command with the same cases, concurrency and tag convention. A paired comparison needs no new code: rows share case ids.
- **Recorder fix (review P1).** With the flag on, `RecordingRetriever` used to log the two inner searches of `retrieve_dual` as two searches (the user's question as an extra "agent query") with the two unmerged candidate lists, and never the merged top 8 the agent received; so `search_count`, `agent_queries`, the retrieval scores and the failure cause of the C2-cap3 arm were wrong. It now overrides `retrieve_dual` and records **one** search: the model's query, the merged chunks in the order the agent got them, and under `dual` the strategy, `supplemental_query: {"source": "user_question"}` (a flag, not a copy of the text), skipped and degraded reasons, `retrieval_calls`, `embedding_calls`, overlap and the two candidate lists as chunk ids only. The inner searches still run and the meter still sees every provider call. Single-query recording is unchanged. Tests: `tests/evaluation/test_trace_dual_query.py` (written first, 9 of 11 failed on the old recorder). No production code changed.
- **Guards.** `--retrieval-strategy C2-cap3` is refused before anything is read or called when a requested pipeline does not read the flag (`legacy`). Any `--retrieval-strategy` on `--split held_out` is refused (also with `--plan`), through the existing held-out tuning guard; a held-out comparison needs a separately approved protocol. Saved manifests now also list `case_ids` (never for the sealed pool).
- **Related defect fixed because the pilot needs it:** `cli run` validated the question set without the injection-document map, so every injection case in `rag_v3_dev_cases.json` failed validation and 12 of the 18 pilot cases could not be run through `cli run`. It now passes `pools.injection_files()` (as `pools validate` does). Regression test fails without the fix (checked by removing it once).

## 2. Pilot selection (rule written before looking at any answer)

Pool: English, `split: dev`. Regression, held-out and Roman Urdu cases never enter. Two kinds of case, kept apart:

- **Representative (13), chosen by a deterministic rule:** the lowest case ids (sorted) in the stratum that meet its predicate; no case is hand-picked. "Both retrieve" = every expected file in the top 8 under A and under C2 in the stored retrieval comparison.
- **Diagnostic (5) and controls, chosen by name, on purpose:** each was selected for a stated reason from ticket 01's per-case results, not by a rule. `id11` in particular was **selected explicitly** because C2-cap3 recovers it (A and uncapped C2 miss it); by the lowest-id rule the recovered group would have been `ac01 id01 id03`, and `id03` was left out only to keep the pilot at 18. This is a deliberate choice, not a rule outcome. Controls (`by03 cc06 gn01`) are listed below.

| Group | Cases | Rule | What it tests |
|---|---|---|---|
| Straightforward factual (representative) | `by02 gn01` | category `single_fact`, both retrieve | Basic lookup, correctness, citation of one file |
| Several facts, one file (representative) | `mf01 mf03` | `multi_fact_one_file`, both retrieve | Completeness: all required facts present |
| Several documents (representative) | `fm04 fm05` | `multi_file_synthesis`, two or more expected files, both retrieve | Combining evidence across files, superseded versions, a calculation |
| Table lookup, both retrieve (representative) | `cb02 dh02` | `table_lookup`, both retrieve | Exactness from tables when the evidence is found |
| Insufficient or unavailable evidence (representative) | `an05 cc07 nep03` | lowest id per behaviour `not_found`, `partial`, `correct_premise` | Refusal, partial answer, correcting a false premise, no invention |
| History-dependent follow-up (representative) | `by03 cc06` | lowest ids with history | Resolving a follow-up from earlier turns |
| Missed by A, recovered by C2-cap3 (diagnostic) | `ac01 id01 id11` | named on purpose from ticket 01 (C2-cap3 gains `ac01 id01 id03 sn03 xl01 id11`); `id11` is the one only the cap recovers | Whether better retrieval becomes a better answer |
| Multi-document, partial evidence (diagnostic) | `mx07` | named on purpose: uncapped C2 loses it, C2-cap3 keeps it, but it still lacks `vendor_contract_cloudhost.txt` | Answer when one of two documents is missing |
| Unretrieved by every strategy (diagnostic) | `px03` | named on purpose: no merge retrieves it | Behaviour with no evidence in the top 8 (hallucination versus abstention) |

18 cases: 13 representative, 5 diagnostic. 3 are judged by the refusal judge. `tests/evaluation/test_pilot_selection.py` pins that all 18 are committed English development cases.

**Controls (also in the 13 above; they do not test the cap3 effect and must not be read as evidence for it):**

- `by03`, `cc06`: history-dependent. C2 applies only to a turn with no earlier history, so **both arms run A** on them. They show how much two runs of the same behaviour differ (model variation) and how follow-ups are handled.
- `gn01`: the production filename-target heuristic reads its question as naming a file (it extracts "day"; the question names no file), so the soft per-file cap switches off for it. It is a cap control. The misreading itself is an existing quirk of `extract_filename_targets`, noted here and not changed.

**Verified against the saved experiment (2026-11-24, free, no provider call):** the production merge (`round_robin_merge` with production's per-case cap decision) re-run over the saved candidate lists of the 18 cases that have them, development only: `ac01 id01` A miss, cap3 hit; `id11` A miss, uncapped C2 miss, cap3 hit; `mx07` A hit, uncapped C2 miss, cap3 hit but one of two expected files absent (`vendor_contract_cloudhost.txt`); `px03` miss under all three; the 8 representative retrieval-eligible cases hit under all three with every expected file present; `gn01` cap decision 0. This agrees with ticket 01. (The cap decision used the case question for both queries; the stored model queries are in another file.) `an05 nep03 by03 cc06` have no saved lists (refusal or history cases).

**Reading rule.** The diagnostic five were chosen *because* retrieval differs or fails on them; the representative 13 are tiny. The pilot's pass rate is **not** an estimate of DriveMind's accuracy and must not be reported as one. Its purpose is reading answers and finding failure modes. The agent's own queries in the pilot may differ from the stored first queries, so the labels describe the saved experiment, not what the agent will retrieve.

## 3. What each row will contain, and how it is measured

Each `cli run` row already records (no new code): question, reply, `cited` (chunk ids, files, snippets), `cited_files`, `execution` (agent steps, search count, queries, tool names, whole-file reads, claim-check removals), `trace` (every search with ranked chunks and scores), `accounting` (calls, tokens, cost by role), `latency_s`, and these scores.

| Wanted | Automatic now? | How |
|---|---|---|
| Final answer, citations, evidence and source ids, tool calls, retrieval per search, latency, tokens, metered cost | Yes | row fields above. For C2-cap3, one search per dual search with the merged chunks (see section 1) |
| Expected answer / facts | Yes (stored in the case) | `reference_answer`, `must_include` |
| Deterministic correctness, required facts present or missing | Yes | `answer_score`, `deep` fact recall, strict deterministic pass |
| Retrieval failure (expected file or anchor not retrieved) | Yes | `evidence_score`, `deep` retrieval from recorded searches, failure cause |
| Forbidden or invented value | Partly | `must_not_include` and the unseen-value **screen**; the screen is a screen, not a verdict |
| Refusal behaviour | Partly | refusal judge for the 3 judged cases (a model; **its accuracy is not calibrated**) |
| Citation integrity | Yes | `deep` chunk-level citation checks |
| **Unsupported factual claims / grounding / hallucination rate** | **No.** | The **claim-support grader (ticket 09) is not implemented**; no accepted grader exists. Read each reply against its cited snippets by hand. The product's **runtime claim check** is a different thing: a filter inside the answering path that removes statements it judges unsupported (removals are counted per row as `claim_check_removed`). It is part of the system under test, so it cannot grade it. |
| Usefulness, completeness beyond the listed facts, tone | No | manual |

## 4. Grader readiness (tickets 09 and 10)

- **Implemented:** the refusal judge (`judge.py`, not calibrated); the deterministic scorers and the unseen-value screen (`score.py`, `screen.py`, `deep.py`); the planted-claims builder and paid check (`planted_claims.py`); Wilson interval (`score.py`) and paired exact test (`stats.py`); the product's runtime claim check (`app/agents/tool_rag/claim_check.py`, a filter returning numbers of unsupported statements); per-case metering.
- **Missing (ticket 09):** the claim-support grader (strict per-statement `supported/unsupported/contradicted`, per-marker attribution, Critical flag); the deterministic statement splitter shared with the Owner's view; the calibration set of about 80 items and 40 refusal items; the labelling kit; agreement statistics (accuracy, precision, recall, specificity, Cohen's kappa; `stats.py` has no kappa); the lock-box and relabel sets; the spot-check procedure. Ticket 10 (agreement report, acceptance rule, Owner decision on direct or advisory use) is blocked on the Owner's labels (about 4-5 hours of Owner time).
- **Sufficient for this pilot?** Yes for a diagnostic read of 36 answers: the deterministic scores flag wrong values, missing facts and retrieval misses, and a human reads the rest. **Not sufficient** for the larger baseline: any claim about grounding or hallucination rates needs the grader (or full human adjudication) first.
- **Reusable:** the claim check's statement splitter and prompt as a starting point (to be re-validated, it was built for filtering, not grading); `planted_claims` builder for planted positives; `score.py` and `stats.py` for intervals.

## 5. Cost plan (free `--plan` output, 2026-11-24)

Models (code defaults): chat and intent gate `gpt-5.4-nano`, claim check `gpt-5.4-mini`, embeddings `text-embedding-3-small`, refusal judge `gpt-5.4-mini`.

**Prices verified 2026-11-24** from OpenAI's official pages (https://developers.openai.com/api/docs/pricing and the three model pages), standard tier, USD per 1M tokens: `gpt-5.4-nano` input 0.20, cached 0.02, output 1.25; `gpt-5.4-mini` 0.75, 0.075, 4.50; `text-embedding-3-small` 0.02 input. They equal `prices.json` (its `checked_on` stays 2026-11-19; this ticket does not edit it). **The pages mark `gpt-5.4-nano` "Deprecated" with no shutdown date**; the pages show no "last updated" date. Source of the fetch: a delegated read of the pages, not a provider invoice.

| | Per arm | Both arms |
|---|---|---|
| Questions | 18 | 36 |
| Intent-gate calls (nano) | 18 | 36 |
| Agent steps (nano), planning constant 2 per question | 36 | 72 |
| Claim-check calls (mini) | 18 | 36 |
| Query embeddings | 18 (A) / about 36 (C2-cap3: one per search, two searches in the first search) | about 54 |
| Refusal-judge calls (mini) | 3 | 6 |
| Estimated cost (plan) | 0.0486 USD | 0.0972 USD |

Basis: planning constant 0.0025 USD per tool-agent question plus 0.0012 per judge call (`prices.json` `estimates`); the measured exploratory run (KI-034, 8 rows, 4 cases, 0.02029 USD metered, 20 agent steps, 5 claim checks) gives 0.0025 USD per row, matching the constant. That sample is small and used only cases that searched. Estimated tokens per arm (scaled from those 8 rows): agent about 94,000 in / 3,300 out, intent gate about 9,000 / 200, claim check about 36,000 / 100 (partly uncertain: not every answer reaches the claim check). The plan does not price C2's extra embeddings (about 18 calls of a few tokens, well under 0.0001 USD).

Multi-document and follow-up questions can take more agent steps than the average, and the Owner will read all answers, so each cap carries a 5 times margin. **Application-side cap: 0.25 USD per arm (one `--cap` per command), 0.50 USD in total.** The cap is checked between calls and is not a provider-side limit; with `--concurrency 1` the overshoot is at most the calls in flight (two tiny embedding calls run together in C2). Expected actual: about 0.10 USD for both arms. No retry or extra run happens without new authorization (`--repeats 1`; the SDK's own automatic retries are invisible to the meter, see `METERING_LIMITS`).

## 6. Proposed paid commands (not run; the Owner decides)

Preconditions: containers up; `index_verify verify --store v3` passes; **the working tree is clean and the change is committed** (the gate refuses otherwise, so the manifest names the code that ran); `OPENAI_API_KEY` exported for this command only and unexported afterwards. Run from `backend/`.

**One command, every step joined by `&&`.** A step that exits non-zero, or a gate that prints `STOP`, ends the chain: arm C2-cap3 starts only after arm A exited 0 **and** its own result passed the gate. Each arm keeps its own application-side cap. Each paired run has a unique run id (`RUN`, timestamp and process id); both arms are started with `--tag "${RUN}_<strategy>"`, the result file stores that tag, and the gate finds the file by it: exactly one file must match, and its stored tag, strategy, commit (equal to the current HEAD), clean-tree flag and case set must match. The newest file of an earlier run is never used (no `ls -t`), so a spend-cap abort that wrote no file cannot be replaced by an old complete result. The block is run by a test against stand-in commands (`tests/evaluation/test_pilot_chain.py`), so what you paste is what was tested.

```bash
# PILOT-CHAIN
IDS=(by02 gn01 mf01 mf03 fm04 fm05 cb02 dh02 an05 cc07 nep03 by03 cc06 ac01 id01 id11 mx07 px03)
DS=(rag_v2_cases.json rag_v2_messy_cases.json rag_v2_identifier_cases.json rag_v3_dev_cases.json)
RUN="pilot_$(date +%Y%m%d_%H%M%S)_$$"
uv run python -m evaluation.rag_eval.pilot_gate --preflight --run-id "$RUN" \
&& uv run python -m evaluation.rag_eval.cli run --cap 0.25 --frozen --store v3 --split dev \
     --pipelines tool_agent --concurrency 1 --repeats 1 --dataset "${DS[@]}" --ids "${IDS[@]}" \
     --retrieval-strategy A --tag "${RUN}_A" \
&& uv run python -m evaluation.rag_eval.pilot_gate --run-id "$RUN" --strategy A --ids "${IDS[@]}" \
&& uv run python -m evaluation.rag_eval.cli run --cap 0.25 --frozen --store v3 --split dev \
     --pipelines tool_agent --concurrency 1 --repeats 1 --dataset "${DS[@]}" --ids "${IDS[@]}" \
     --retrieval-strategy C2-cap3 --tag "${RUN}_C2-cap3" \
&& uv run python -m evaluation.rag_eval.pilot_gate --run-id "$RUN" --strategy C2-cap3 --ids "${IDS[@]}" \
&& uv run python -m evaluation.rag_eval.pilot_gate --run-id "$RUN" --pair --ids "${IDS[@]}"
```

Run it in `bash` (in interactive zsh the `# PILOT-CHAIN` comment line prints a harmless "command not found"). If the chain stops, read the last `PILOT GATE:` or `STOPPED:` line, do not start arm C2-cap3 by hand, and ask the Owner. The free gate reads local files and `git` only. `cli run` exits non-zero when the spend cap stops a run, but exits 0 when single cases end in an error, which is why the gate also checks every row. Two `--plan` runs (free) gave 0.0486 USD per arm.

**Known limits of this design:** one run per arm per case, so run-to-run variation of the model (not measured here) can look like a strategy effect; with 18 cases no difference is statistically meaningful. The claim check and refusal judge run in both arms, identically.

## Comments

- 2026-11-24: written. Free work only.
- 2026-11-24: first review **BLOCK** (P1 recorder, two P2). Owner authorized the corrections; this version contains them (recorder, `id11` wording, legacy and held-out refusal, controls, gate, terminology). Second review **BLOCK** (the paid sequence did not stop itself; stale-file risk). Fixed: unique run id, result found by tag, clean tree and HEAD checks, `&&` chain tested by running the real block. Third (focused) review **APPROVE**; open P3: the gate does not check row `extend_error`.

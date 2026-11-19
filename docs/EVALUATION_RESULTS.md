# Evaluation results log

Committed summary of measured results (raw run files stay local in `backend/evaluation/results/`,
which is gitignored). Newest first. Every entry states the commit, model and dataset so it can be
reproduced. Numbers here are measurements, not guarantees.

## RAG answer quality v2: baseline, tool agent vs legacy pipeline (live)

What it measures: 94 hand-written questions over a 55-file library (22 synthetic "Larkspur Systems" files with
deliberate traps, plus 33 real public documents as noise: 11 NIST publications and 22 CC BY arXiv papers).
63 cases are the working (dev) set, 31 are held out (test) and were not read while fixing anything.
Cases, corpus manifest (URL, licence, SHA-256 per document) and scorer are in `backend/evaluation/`
(`datasets/rag_v2_cases.json`, `corpus/`, `rag_eval/`). Reproduce:
`cd backend && uv run python -m evaluation.rag_eval.cli setup && uv run python -m evaluation.rag_eval.cli run --pipelines tool_agent legacy --split all`
(needs the disposable PostgreSQL/Qdrant containers and an OpenAI key; the run refuses to touch any store not named `drivemind_eval*`).

Run: 2026-11-19, chat model `gpt-5.4-nano`, refusal judge `gpt-5.4-mini`, 3 cases at a time.
Cost: about $0.16 for both full runs plus about $0.03 for the four judge re-runs and about $0.04 for the sequential latency runs (estimate from token counts at the official price, `rag_eval/prices.json`).

| Stage | Tool agent | 95% interval | Legacy pipeline | 95% interval |
|---|---|---|---|---|
| Evidence found (right file cited) | 48/62 (77%) | 66–86% | 51/62 (82%) | 71–90% |
| Answer correct (facts present, none forbidden) | 53/67 (79%) | 68–87% | 53/67 (79%) | 68–87% |
| Refusal / small talk judged right | 24/28 (86%) | 68–94% | 23/28 (82%) | 64–92% |
| No citation where none belongs | 18/32 (56%) | 39–72% | 23/32 (72%) | 55–84% |
| **Overall pass** | 75/94 (80%) | 71–87% | 74/94 (79%) | 69–86% |

Overall pass means every stage that applies to the case passed. A case with no right-file citation, a missing
fact, a forbidden claim, a wrong refusal, or an error fails.

**Result: the two pipelines are statistically tied** (75/94 vs 74/94; the intervals overlap almost completely).
They fail in different places:

| Category | Tool agent | Legacy |
|---|---|---|
| aggregation_list_count | 7/7 | 6/7 |
| calculation_dates | 3/5 | 4/5 |
| chitchat | 4/4 | 2/4 |
| follow_up | 2/5 | 3/5 |
| injection | 3/4 | 3/4 |
| inventory | 3/4 | 2/4 |
| multi_fact_one_file | 4/5 | 3/5 |
| multi_file_synthesis | 6/7 | 4/7 |
| not_found | 7/8 | 6/8 |
| out_of_scope | 5/5 | 5/5 |
| perturbed_unanswerable | 4/7 | 7/7 |
| public_document | 4/5 | 5/5 |
| roman_urdu | 5/7 | 6/7 |
| same_name | 2/3 | 2/3 |
| single_fact | 6/8 | 6/8 |
| superseded_version | 7/7 | 7/7 |
| tentative_vs_decided | 3/3 | 3/3 |

- The tool agent recognises small talk by meaning (4/4); the legacy phrase-based route answered "I could not find relevant information" to "Hi, how are you doing today?" and to a Roman Urdu "what can you do" (2/4 on small talk).
- The legacy pipeline is more reliable at false-premise and unanswerable questions in this set (perturbed 7/7 vs 4/7); the tool agent more often keeps citing an unrelated file while saying it found nothing (citation noise, last-but-one row above).
- Latency, measured one case at a time on the first 20 dev cases: tool agent median 4.4 s, 90th percentile 8.05 s; legacy median 2.41 s, 90th percentile 4.19 s. With three cases at a time the tool agent showed three 120 s timeouts (and the legacy one a 293 s stall) that did not recur when the same cases were run alone, so they look like provider stalls under concurrency, not a deterministic loop. Not proven.

### What the first run got wrong (fixed in the harness, same replies re-scored, no pipeline re-run)
1. The small-talk judge wrongly failed the intended greeting/capability replies. Rubric corrected.
2. The expected fact `{TOTAL_FILES}` for the inventory question was never filled in (both pipelines had answered correctly).
3. Three cases (`td01`, `pb05`, `ag05`) accepted only one source although the corpus legitimately has a second; both pipelines were failed for citing it.
4. Citation noise on a refusal no longer fails the refusal; it is reported on its own row. The serious failure there is an invented answer, which is still caught.
Changes 3 and 4 were made after seeing results, so the headline is slightly flattered relative to a pre-registered rule. They apply equally to both pipelines.
The raw first-run files are kept next to the corrected ones (`*_all.json` vs `*_all_rescored.json`).

### Findings about the product (not about the harness)
- **Recall cliff on wordy queries (tool agent, reproducible).** For "How many days of annual leave do employees get per year?" the model rewrites its search as "annual leave entitlement days per year employees get". Vector search returns nothing (every hit is under the fixed 0.35 similarity threshold) and keyword search returns nothing (it needs every word to match; "entitlement" and "get" are not in the handbook). The answer is "I could not find relevant information", 3 times out of 3, while "annual leave days per year" finds it. Registered as KI-022.
- **A hallucinated attribution** (legacy, `nf08`): it said a postmortem meeting that is not in the files "decided" a change that only appears as a follow-up line in an incident report.

### Caveats
- 94 cases give roughly ±8 points at this accuracy (intervals above). A difference of a few cases means nothing.
- Synthetic files are short, so a chunk is usually the whole file; real long documents would behave differently in retrieval.
- The refusal judge is one small model, not a human; I read the dev failures myself and corrected the harness errors above, but did not hand-grade every pass.
- Seven of the 188 case runs ended in an error (4 tool agent, 3 legacy); they are counted as failures. The four tool-agent ones succeeded when re-run alone (`*_rerun_of_4_errored_cases.json`); that rerun is not part of the table.

## Intent gate — `intent_v1` (live)

Question: can the small model call that runs before the document agent recognise greetings, thanks,
farewells, "what can you do", out-of-scope requests and real document questions by *meaning* (no phrase
list)? Dataset: `backend/evaluation/datasets/intent_v1.json` (83 hand-written cases incl. greeting + request
mixes, follow-ups with the previous assistant message, and Roman Urdu). Run:
`cd backend && uv run python -m evaluation.intent_eval --execute`.

Worst error = **false decline** (a real document question treated as small talk / out of scope).
Mild error = **missed chitchat** (small talk sent to the document agent, which refuses politely).

| Date (UTC) | Model | Commit | Cases | Accuracy | False declines | Missed chitchat | Median latency | API errors |
|---|---|---|---|---|---|---|---|---|
| 2026-11-19 16:01 | gpt-5.4-nano | db870be | 83 | **100%** | 0 | 0 | 0.89 s | 0 |
| 2026-11-19 15:59 | gpt-5.4-nano | db870be | 83 | 98.8% | 0 | 1 | 0.81 s | 0 |
| 2026-11-19 15:58 | gpt-5.4-nano | db870be | 83 | 97.6% | 0 | 2 | 0.78 s | 0 |
| 2026-11-19 15:56 | gpt-5.4-nano | 6575da0 | 83 | 96.4% | 1 | 2 | 0.77 s | 0 |
| 2026-11-19 15:50 | gpt-6-luna | 8ed4b02 | 83 | 56.6% (invalid) | 0 | 36 | 9.7 s | 19 |
| 2026-11-19 15:36 | gpt-6-luna | f44d751 | 77 | 98.7% | 1 | 0 | 1.2 s | 0 |

Reading the table honestly:
- The `gpt-6-luna` 15:50 row is **not a quality result**: 19 requests failed (HTTP 500/timeouts) and the gate
  correctly fell back to the document agent. It shows the fail-safe works and that luna was unreliable
  at that time (see `docs/DECISIONS.md`).
- Between 15:56 and 15:58 the prompt was generalised (bare acknowledgements after an answer) and one
  ambiguous trivia case (i072) was relabelled to accept either label. That is tuning on the same set, so the
  later rows are optimistic; a fresh held-out set is needed before claiming a general accuracy.
- Run-to-run variation on identical code was 97.6% to 100%, so single runs should not be over-read.
- Early gap found and fixed: a bare "yes please" was read as thanks until the previous assistant message was
  given to the classifier.
- Cost: one request per case, a few hundred tokens each; well under one cent per full run (estimate from
  token counts at the official price).

## Earlier baselines (pre-existing)

See `backend/evaluation/analysis/baseline_v1_failure_analysis.md` (Gold v1, 24 cases, 2026-09-21: routing 20/24)
and `backend/evaluation/experiments/` for experiments 01 to 03. These predate the tool agent and the intent gate.

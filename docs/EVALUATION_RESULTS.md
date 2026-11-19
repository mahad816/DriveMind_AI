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

## KI-002 claim check: accuracy and before/after (live, 2026-11-19)

The check (`app/agents/tool_rag/claim_check.py`) sends the answer, split into numbered statements, and the retrieved evidence to `gpt-5.4-mini` (temperature 0). It removes only the statements the model says assert a specific fact the evidence lacks or contradicts, and fails open (any error, timeout or unusable reply leaves the answer unchanged). Headings, lead-ins and fragments are never removed.

### 1. How accurate is the checker itself? (RAGBench, fresh sample, seed 2)
Source: `galileo-ai/ragbench` (CC BY 4.0), 11 configs, 25 rows each, 266 rows used (9 skipped: empty/too long). The checker ran through the exact production call path. Labels are RAGBench's `adherence_score` and `unsupported_response_sentence_keys`, written by GPT-4o, so this measures agreement with that annotator, not truth. Prompt and splitter were tuned on a different sample (seed 1, 109 rows); seed 2 was run once, after tuning.

| Level | Positives in labels | Precision | Recall | Accuracy | F1 |
|---|---|---|---|---|---|
| Response (is anything unsupported?) | 13.2 % of 266 | 0.52 (95 % CI 0.35-0.68, n=31) | 0.46 (0.31-0.62, n=35) | 0.87 (0.83-0.91) | 0.49 |
| Sentence (which sentence?) | 7.8 % of 1047 | 0.46 (0.36-0.55, n=99) | 0.55 (0.44-0.65, n=82) | 0.91 (0.89-0.93) | 0.50 |

Read plainly: about half of what it flags the annotator also flagged, and it finds about half of what the annotator flagged. On general-purpose RAG data this is a modest checker, not a precise one. `gpt-5.4-nano` was tried first and was unusable (precision about 0.27), so `gpt-5.4-mini` is the default. Cost of this run: $0.49.

### 2. Does it do its job in this product's failure shape? (planted claims, corrected 2026-11-19)
Evidence = the real file(s); clean answer = the case's reference answer. Variants built by fixed rules, no model: `clean`, `appended` (clean answer plus one invented, specific sentence), `contradict` (first number changed by +7), and `computed` (correct calculated answers, to check the checker does not delete honest arithmetic). Script: `evaluation/rag_eval/planted_claims.py`. About $0.06 per run.

**The first version of this test was wrong, and the numbers first published here (false removal 4.4 %, invented sentence 44/45, number swap 29/36) should not be used.** Reading every failing case showed: (a) 2 "false removals" were correct answers that mention the *old* policy while the test handed the checker only the *new* policy file, so flagging them was right; (b) one "contradiction" repeated another real incident number, which is not a false fact; (c) the checker itself had a bug: any statement under 4 words was treated as a heading and could never be removed, so a short answer like "17 February 2026." could not be caught; (d) the checker never saw the user's question, so it could not tell that 13 = 22 - 9 uses numbers the user typed. The test now leaves out cases whose reference answer the chosen files do not fully support (4 cases) and builds a "contradiction" only when the changed number is genuinely new.

Fixes (branch `fix/claim-check-numbers`): short fragments with a digit are checked; a plain non-AI step lists numbers written in a statement that appear nowhere in the evidence or the user's words, and the model is asked to check each unless it is arithmetic; the user's messages are given to the checker.

Two runs per version (the model is not fully repeatable even at temperature 0):

| Test (corrected) | Old checker (2 runs) | New checker (2 runs) |
|---|---|---|
| Invented sentence removed | 37 and 39 of 41 | **41 and 41 of 41** |
| Changed number caught | 21 and 22 of 26 | **25 and 25 of 26** |
| True answer wrongly removed | 0 of 41, 0 of 41 | 0 of 41, 0 of 41 |
| Correct calculated answer wrongly removed | not measured | 1 of 8, 1 of 8 (`ca02`: minutes converted to hours) |

Remaining misses: `sv04` (a date changed from 4 March to 11 March inside a long sentence) and `ca02`. The planted sentences are synthetic and obviously out of place, so removing them is the easy case.

### 3. End to end: tool agent on the 94 cases, check on vs off (same code, same day)
| | Check OFF | Check ON |
|---|---|---|
| Overall pass | 78 / 94 (83.0 %) | 76 / 94 (80.9 %) |
| Evidence found | 50 / 62 | 51 / 62 |
| Answer correct | 55 / 67 | 51 / 67 |
| Refusal OK | 27 / 28 | 27 / 28 |
| Latency median / p90 | 3.8 s / 6.3 s | 5.2 s / 7.8 s |
| Extra cost per run | - | about $0.18 |

The difference (2 cases) is inside the noise: 50 of 94 replies differed in wording between two identical-code runs. To find what the check itself did, the 5 cases that went from pass to fail were rerun 3 times each with the checker's decisions logged:
- `sf01`, `fu01`, `pu02`, `pu03`: the checker flagged nothing. `sf01` and one `fu01` run refused because search found nothing (the KI-022 recall cliff); the rest were the model's own variation.
- `ag05`: the checker removed the bullet "SMSGate - SMS provider used for text reminders" in 1 of 3 runs, and that run then missed an expected fact. The incident report does say this, so this is probably a false removal (the cited source number may have been the email thread, which does not).

So on this corpus the check almost never fires (the model rarely invents facts next to a real citation here), and when it fired once it probably cost a correct bullet. The measurable benefit is the planted-claims result above, not an improvement in the 94-case score. The 94 cases contain no case that deliberately gets the model to invent a fact beside a real citation; adding such cases is the natural next step.

Caveats: single run per arm; the planted test and the dev tuning share the author; the RAGBench labels come from one LLM annotator; cost and latency are per question with the default model. Result files are kept locally in `backend/evaluation/results/` (gitignored): `rag_v2_*_claimcheck_{on,off}.json`, `planted_claims_*.json`, `ragbench_*_seed2.json`.

## Invention traps (18 cases, live, 2026-11-20)

File: `backend/evaluation/datasets/rag_v2_trap_cases.json` (run with `--dataset rag_v2_trap_cases.json`; the 94-case baseline file is untouched). Each question is about something the files do **not** fully contain, while a neighbouring fact is present, so a model is tempted to fill the gap. Every quote and fact was checked word for word against the documents by the dataset validator. Nine cases are "not in the files" (the reply must say so), nine are "partly in the files" (the reply must give the known part, with a source, and must not invent the rest). Split: 9 dev, 9 test.

Tool agent (`gpt-5.4-nano`), claim check on: **11 of 18 passed** (61 %, 95 % interval 39-80 %). One run, $0.06.

| Case | What the files have | What went wrong |
|---|---|---|
| tr01 | employee notice periods | applied them to contractors (invented scope) |
| tr04 | Larkspur's own 35-day backup rule | said CloudHost keeps backups 35 days (misattributed) |
| tr09 | core hours 10:00-16:00 | answered "office opens at 10:00" (borderline) |
| tr11 | "salaries are not part of this document" | said none of the budget goes to salaries (flipped meaning) |
| tr13 | 60-day cancellation notice | stated "no cancellation fee" as a fact |
| tr12, tr14 | the answer is in the files | search found nothing (KI-022); not an invention |

Findings:
- Roughly one tricky question in three still gets a confident wrong answer from this model. Two of the failures were a retrieval miss, not an invention.
- The claim check did not catch these: in `tr04` and `tr01` the sentence is *supported by the text it was shown*; the error is about **who or what** it applies to (CloudHost vs Larkspur, contractor vs employee), and `tr13` is a claim about something being **absent**. The current checker asks "is this fact in the evidence?", not "is this fact about the right subject?" or "does the evidence really say nothing exists?". This is the next thing to improve (see `docs/IMPROVEMENT_PLAN.md`).
- Post-hoc change, disclosed: the first judge note for `tr17` made the judge fail a correct reply ("two extra paid weeks on top of national law"). I corrected the note and re-judged the stored replies (no new agent run); that moved 10 of 18 to 11 of 18. `tr09` is arguable and was left as the judge scored it.
- Not yet measured: the same traps with the claim check off, and with a larger chat model.

## Retrieval probe: does the search find the right file? (no chat model, 2026-11-20)

Tool: `python -m evaluation.rag_eval.retrieval_probe [--phrasings] [--split dev|test|all] [--threshold X]`.
It makes the same call as the agent's `search_knowledge` tool and checks whether a file the case expects is
among the 8 returned chunks. Cost: query embeddings only (about 0.0001 USD for the whole run).
The query is the question text itself; the real agent writes its own query, so this is the best case.
89 answerable cases (the 94 baseline + 49 trap cases, minus those that need earlier turns or have no file).

**Baseline, today's code (cut-off 0.35):**

| Wording of the same questions | Right file in results | Ranked first | Rank quality (MRR) | Distinct files per result |
|---|---|---|---|---|
| Plain question | 83 / 89 (93.3 %) | 65 | 0.82 | 4.2 |
| "In the company policy document, ..." | 78 / 84 (92.9 %) | 34 | 0.57 | 7.7 |
| "According to the report, ..." | 78 / 84 (92.9 %) | 53 | 0.74 | 5.2 |
| "Which file says this: ..." | 80 / 84 (95.2 %) | 50 | 0.74 | 6.8 |

Misses (plain): `ca04, mf02, mx07, sf06, sf07, sn02`. Dev split 54 / 56, test split 29 / 33.

**Same, only the cut-off lowered to 0.20** (the first change in Step 1, measured before it is made):
plain 87 / 89 (97.8 %, misses `mx07, sf07`), MRR 0.86; "according to the report" 83 / 84; "which file" 82 / 84;
but "in the company policy document" stays at 78 / 84 and its ranking gets **worse** (ranked first 34 -> 26,
MRR 0.57 -> 0.48). Lowering the cut-off lets more weak chunks in, and the lead-in wording already
floods the results with unrelated files (7.7 distinct files per result). That wording problem is Step 1
part 2, not something the cut-off can fix.

**Reading the probe correctly:**
- Repeatable: two identical runs gave identical files, ranks and found/missed flags. Only the raw vector
  score moves, by up to 0.004 in the third decimal (embedding service float jitter). Do not tune any
  threshold finer than about 0.01.
- 40 "not in the files" cases: 31 of them still return chunks (39 at cut-off 0.20); their best vector score has median
  0.50 and maximum 0.67, the same range as answerable cases. So retrieval cannot decide when to refuse.
- Counts have wide error bars (95 % interval for 83 / 89 is about 86 % to 97 %); a difference of 1-2 cases is noise.

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

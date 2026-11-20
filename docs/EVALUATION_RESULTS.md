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

## Step 1a: the vector cut-off (2026-11-20)

Change: `RETRIEVAL_SCORE_THRESHOLD` 0.35 -> **0.25**, and a new `RETRIEVAL_RELATIVE_THRESHOLD` = **0.7** (a vector hit
must also score at least 70 % of the best vector hit). Both apply to the old pipeline too, which shares the retriever.

**How the values were chosen (retrieval probe, dev split, then test split):**

| Floor | Relative | Plain: right file in results (dev) | Ranking quality in the 3 lead-in wordings (dev, MRR) | Not-in-files cases that still return chunks |
|---|---|---|---|---|
| 0.35 (old) | off | 54 / 56 | 0.53 / 0.78 / 0.75 | 18 / 22 |
| 0.30 | off | 55 / 56 | 0.50 / 0.75 / 0.78 | 20 / 22 |
| 0.25 | off | 55 / 56 | 0.49 / 0.73 / 0.77 | 21 / 22 |
| 0.20 to 0.0 | off | 55 / 56 (flat) | 0.49 / 0.71 / 0.77 | 21 to 22 / 22 |
| 0.25 | 0.9 | 52 / 56 (loses `ru03`, `td01`, `tr21`) | 0.74 / 0.84 / 0.84 | 21 / 22 |
| 0.25 | 0.8 | 55 / 56 | 0.59 / 0.82 / 0.80 | 21 / 22 |
| 0.25 | 0.7 | 55 / 56 | 0.55 / 0.79 / 0.78 | 21 / 22 |
| 0.15 | 0.8 | same as 0.25 / 0.8 | same | 21 / 22 |

- Below 0.25 nothing more is found; the floor only matters until ~0.25. With the relative rule on, 0.15 and 0.25 give
  identical results, so the floor is no longer a delicate choice.
- A flat low floor alone has a cost: weak chunks fill the 8 slots and push the right file down in the lead-in
  wordings (for example `sf01` rank 2 -> 6, `mx04` 1 -> 4). The relative rule removes most of that.
- The test split is used as a veto, with the rule fixed in advance: take the largest fraction that loses no right
  file. On test, 0.8 and 0.75 each lose one multi-file case (2 of 3 found, 3 of 3 with the rule off); 0.7 loses none.
  Test, floor 0.25 vs 0.35, plain: 32 / 33 vs 29 / 33; with 0.7 the lead-in wordings gain a little ("according to the
  report" 0.69 -> 0.74, "policy document" 0.45 -> 0.52 MRR). The relative rule's gain is modest.
- Right-file score vs top score (dev): the right file's best chunk scores 81 % to 100 % of the top vector score
  (median 100 %), which is why fractions above 0.8 start losing files.

**Agent level, dev split, 88 cases (baseline + trap + control files), tool agent, one run each, cost 0.22 + 0.22 USD:**

| | Old (0.35, off) | New (0.25, 0.7) |
|---|---|---|
| Overall pass | 74 / 88 (84.1 %) | 79 / 88 (89.8 %) |
| Right file found | 53 / 59 | 56 / 59 |
| Answer correct | 54 / 63 | 57 / 63 |
| Refusal handled correctly | 27 / 31 | 29 / 31 |
| Answers with no citation on refusals ("clean") | 14 / 29 | 11 / 29 |

Five cases went from failing to passing (`sf01`, `fu01`, `tr21`, `tr05`, `tr09`); none went from passing to failing.
How to read it: single runs, error bars about +/- 8 points. `sf01` and `tr21` are the retrieval fix working as
diagnosed. `tr05` and `tr09` improving is most likely model variance (a lower cut-off should not make refusals
better), so the honest gain is about 2 to 3 cases, not 5.

**What got worse, and why:** "clean" fell by 3 cases (`pu04`, `pu05`, `tr05`). In two of them the old pass was
accidental (the agent hit a tool error and returned a canned message; now it searches and writes a real refusal).
`pu05` cites the one file that mentions the person, which is reasonable. `pu04` ("release 1.4") attaches **8 files,
including unrelated NIST PDFs**, to a refusal. Cause: when an answer has no citation markers, `finalize_answer`
appends "Sources consulted:" with every file the search returned, so any retrieval change that returns more files
makes refusals look more cited. This was already true before (15 of 29 refusals were not clean); it is a separate
defect, planned as Step 1d, not patched here.

## Step 1b: file-name matching and crowding (2026-11-20)

**In plain words.** Search had two bugs that pushed the wrong files up:
1. If a word of the question appeared *inside* a file name, that file got a bonus. This included tiny words:
   the word "is" appears inside "n-**is**-t", so every public NIST PDF got a free bonus on almost every
   question and outranked small company files (this is why "Who is the Security Lead?" missed the team directory).
   Generic words such as "policy" or "report" had the same effect: one such word pulled in every policy file.
2. One long document could fill all 8 result slots, leaving no room for other files.

Fixes: (a) a question word counts as naming a file only if it is at least 5 letters long **and** appears in the
names of at most 2 of the user's files (new setting `RETRIEVAL_NAME_TERM_MAX_FILES=2`); this applies to both the
file-name search and the +0.2 bonus; (b) at most 3 of the 8 results may come from one file (new setting
`RETRIEVAL_MAX_CHUNKS_PER_FILE=3`, 0 = off). The cap is not applied when the user restricted the search to chosen
files or named a file, because then many chunks of one file is what they want.

**What was tried (retrieval probe, dev split; "ranked first" is out of 52 questions in a lead-in wording):**

| Variant | Plain question: right file found | "In the company policy document, ..." ranked first | Verdict |
|---|---|---|---|
| Before (Step 1a state) | 55 / 56 | 20 | |
| Name words limited to 1 file | 55 / 56 | 31 | loses a rank-1 on test |
| **Name words limited to 2 files** | 55 / 56 | **32** | **chosen** (3 files gives the same) |
| Name path switched off completely | 55 / 56 | 22 | worse: the path is useful when limited |
| Metadata search returns only real matches | 55 / 56 | 15 | **rejected**: it made things worse, metadata search stays as is |
| Cap of 3 (or 2) chunks per file | **56 / 56** | 20 | chosen (fixes `mx07`; 3 is safer for long documents) |
| + bonus uses only identifying words | 56 / 56 | 32 | chosen (this is what fixes `sf07` on test) |

Chosen combination, real code, plain questions: dev **56 / 56**, test **33 / 33** (was 55 / 56 and 32 / 33;
`sf07`, missed in every earlier setting, is now found). In the lead-in wordings, "ranked first" for the
policy-document wording goes 20 -> 32 of 52 (dev) and 10 -> 19 of 32 (test); quality score (MRR) 0.55 -> 0.75 (dev),
0.52 -> 0.72 (test).

**Agent level (does the answer improve?): no measurable change, and that is the honest result.** On the 13 cases
whose retrieved files actually differ between the old and new code, run twice each, the same day: old 22 of 26
case-runs pass, new 22 of 26. The two that fail either way have other causes: `mx07` needs two files and the agent
searches once (Step 1c/2), `ca05` never searches (Step 2). So 1b makes retrieval cleaner and more robust to
wording, but this small corpus does not turn that into more correct answers yet.

**A finding about the evaluation itself (the model is not deterministic).** A full dev run after 1b showed 77 passing
against 79 after 1a. Investigation: one of the three "new failures", `ca03` (a budget question), answered "Latest
indexed file: security_policy.txt" because the agent's first move was to call the file-listing tool. This happened
with the old Step 1a code too (6 of 6 runs the next morning). The first explanation written here was "the model
changed overnight"; **that was not proven**. Step 1c measured it properly: the same question with identical input
at temperature 0 chose the listing tool in 3 of 6 calls and the search tool in the other 3. So the first move is
a coin flip for this wording, and the earlier clean runs were luck. Another case, `tr19` (an invention trap),
invents "reports to the CEO" in 2 of 5 repeats of the same code. Lessons: single runs of the whole set cannot
show a 2-case change; compare old and new on the same day, on the cases that differ, with repeats.

## Step 1c: tool descriptions (2026-11-20)

**In plain words.** The agent's first decision is which tool to call. Three things could go wrong there, and I
measured each with a new cheap test (`first_step_probe`: send the question to the real model with the real tool
descriptions, record the first call, and run the search query the model wrote through the real search; no answer
is generated, so it costs about 0.0003 USD per question):

| What could go wrong | Measured on all 135 questions, before any change | Verdict |
|---|---|---|
| A content question goes to the file-listing tool | 2 of 270 runs, both `ca03` | **fixed** |
| The model's search query misses the right file | 2 of 174 runs, both `sf07` (a ranking case) | no problem: no query advice needed |
| A follow-up forgets the topic of the earlier turn | 4 of 5 follow-ups wrote the earlier topic into the query; the fifth (`fu02`) already names INC-211 in the question | no problem: no follow-up advice needed |
| A two-topic question is searched once, with one mixed query | 24 of 30 multi-file runs found all files (misses: `mx07`, `ag05`, `td01`) | **not fixable by wording** (see below) |

**Example (`ca03`).** Question: "How much was spent in the first half of 2026, and how much of the total budget is
left?" Before: in about half of the calls the model asked the file-listing tool for the newest file, and the user
got `Latest indexed file: security_policy.txt`. Now the tool says it only knows file metadata and "cannot read
document text", so the model searches: 20 of 20 calls search, and the answer is the budget figures from `budget_2026.txt`.

**What changed.** Only the two tool descriptions (`registry.py`): the listing tool must not be used when the answer
is written inside a document, even if the question mentions a year or "latest"; `search_knowledge` is the tool for
any question answered by document text. Both stay under the 500-character limit.

**Numbers (agent level, 13 multi-file cases plus `ca03`, two runs each, same day, same model):** baseline 21 of 26
pass; final wording 24 of 26. `ca03` 0 -> 2, `ag05` 1 -> 2; `mx07` still 0 (below). Held-out test split, first
step: 0 wrong-tool runs in 106 (also 0 before), right file found in 64 of 66 searches (before: 62 of 64); the only miss is `sf07` both times.

**What did not work, and why it was left out.** I also tried telling the model "search one topic per call; if the
results do not contain the answer, search again with different wording", in the tool description and as a system
prompt line. `gpt-5.4-nano` never sent a second search: 0 multi-search runs in either variant, and traces of
`mx07`/`ag05` show one search then an answer every time. The single gain under that wording (`mx07` 0 -> 1) was one
lucky query, and a stray `pb05` refusal showed up under it that came from the claim check, not the tools (identical
tool calls as the passing runs). Text that does not change behaviour is clutter, so it is not in the code. It is a
Step 5 candidate: a larger answering model may follow it.

**Two decisions that changed the plan.**
1. *The "dead grade" is kept.* I had called `grade_evidence` dead. Measured over 133 questions: the score-based checks
   never fire, and the only rejection is "nothing was returned at all" (3 cases). But the "weak vector and no keyword
   hit" check can fire for gibberish queries, each branch has its own test, and the LangGraph path reads
   `sufficient` to decide whether to rewrite the query. Removing it would change the LangGraph and legacy paths
   for no measured gain, so it stays. The plan entry was wrong and is corrected.
2. *"Sources consulted" on refusals (1d) moves to Step 4.* On dev, 6 of 22 refusal-type answers end with that
   footer but only 1 of 59 real answers does, so it is a refusal artifact. But in 12 more refusals the model writes
   its own citation markers, so fixing the footer alone would fix a third of the problem. The proper signal is
   "this answer asserts document facts: yes or no", which the claim check (it already reads answer and evidence) can
   return in the same call. Step 4 extends that checker anyway. A list of English refusal phrases would break on
   Roman Urdu answers, so it was not built.

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

## Messy question set, first measurement (2026-11-20, after Stage A)

First run of the 39 questions on the generated DOCX, PPTX, XLSX and two PDFs, read by the Stage A readers.
Tool agent, `gpt-5.4-nano`, claim check on, one run, default retrieval settings (cut-off 0.25, relative 0.7).
Store: the existing `drivemind_eval_v2` store plus the 5 messy files (the other 55 files keep their older extraction, so
runs of the older datasets after this point see 5 extra files; Stage B rebuilds the store). Cost **$0.107** (estimate
$0.10, cap $0.20); judge calls $0.002, claim check ($0.060) cost more than the agent ($0.046). Result file:
`rag_v2_20261120_153553_tool_agent_gpt-5.4-nano_all_messy_a5.json`.

| | Result (95% interval) |
|---|---|
| Overall pass | **33 / 39** (84.6%, 70-93%); dev 18/22, test 15/17 |
| Right file found | 30 / 34 |
| Answer correct | 29 / 34 |
| "Not in the documents" handled | 4 / 5 |
| By file | DOCX 7/8, PPTX 8/9, XLSX 5/6, PDF invoice 4/7, PDF annual report 9/9 |
| Latency | median 4.9 s, 90th percentile 6.3 s |

Retrieval alone (`retrieval_probe --messy`, query embeddings only, $0.00001): the right file is in the results for
**33 of 34** answerable questions, ranked first for 29 (MRR 0.90). So the readers' output is findable.

The 6 failures, by cause (none is a reader error):
- **Agent chose a name lookup (vi04, vi05, vi07):** see KI-025.
- **Chunking dilution (px03):** the 4-slide deck is one chunk, and "Signed 6 new clinics in Q3" lost to the rollout plan.
  Stage B (heading-aware chunks) is meant to fix this.
- **Model invented an answer (dx08):** the "Enterprise package" trap; it quoted the Network fee. The claim check did not
  catch it (KI-002 family).
- **Model arithmetic (xl04):** the table was found and read correctly; the sum of 5 delivered orders came out 33,100
  instead of 34,900.

How to read it: 39 questions, one run, error bars about +/- 14 points; use it as the baseline Stage B is compared
against, not as proof of anything smaller than about 15 points. The set was built by the same author as the readers
(the questions describe what the fixtures contain).

## Earlier baselines (pre-existing)

See `backend/evaluation/analysis/baseline_v1_failure_analysis.md` (Gold v1, 24 cases, 2026-09-21: routing 20/24)
and `backend/evaluation/experiments/` for experiments 01 to 03. These predate the tool agent and the intent gate.

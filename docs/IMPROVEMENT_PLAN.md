# Improvement plan, version 2 (2026-11-20)

Scope: the **tool agent** only. The old pipeline is evaluation baseline code; it is not improved, but it
shares `app/retrieval/`, so its tests must stay green after every retrieval change.
Nothing in this file is implemented yet. Every number marked "probe" was measured on 2026-11-20 with
throw-away scripts (not committed); Step 0 turns them into a committed, repeatable tool.

## 1. How the system works today (read from the code)

| Stage | What happens now | Where |
|---|---|---|
| Chunking | Text cut into pieces of up to 3,500 characters with 500 overlap. A short file is one chunk. No heading awareness. | `ingestion/chunking.py` |
| Embedding | Only the chunk text is embedded (no file name, no title). `text-embedding-3-small`. | `services/indexing_service.py` |
| Vector search | Qdrant cosine search. Anything scoring below **0.35** is thrown away. | `retrieval/vector.py` |
| Keyword search | Postgres full-text. **All** words must match. Plus three extras: date match, "file name contains a word of the question" (score 0.85), exact phrase. | `retrieval/keyword.py` |
| Metadata search | Guesses from words like "latest", "document", "file", "report", "notes". | `retrieval/metadata.py` |
| Merge | Rank fusion (weights 0.5 / 0.3 / 0.2). | `retrieval/merge.py` |
| Re-rank | **Replaces** the fused score by "score divided by the best score in the list", so the top result is always 0.5 (vector) or 0.3 (keyword only). Cut to 8. | `retrieval/rerank.py` |
| Grade | Checks fusion score >= 0.15 and vector >= 0.35. Because of the line above, the best result always passes. **It can never reject anything.** | `retrieval/grade.py` |
| Agent | One model, 4 tools, `tool_choice="auto"`, prompt says "reply without tools when document access is unnecessary". The `search_knowledge` tool description is one line. | `llm/openai_agent_service.py`, `tool_rag/prompts.py` |
| Evidence to model | One section per chunk with the file name. **No dates** (the modified date is not passed on). | `routing/intent_frame/evidence.py` |
| Check | Claim check removes unsupported sentences (KI-002). | `tool_rag/claim_check.py` |

## 2. What the free probes showed

Retrieval-only tests, no chat model, 58 answerable cases, "is the right file in the top 8?".

| Setting | Right file in top 8 | Average rank quality (MRR, 1.0 = always first) |
|---|---|---|
| Today (cut-off 0.35) | 53 / 58 | 0.81 |
| Cut-off 0.20 | **56 / 58** | **0.86** |
| 0.20 + "any word" keyword fallback | 56 / 58 | 0.86 (no gain) |
| 0.20 + weaker "file name contains word" signal | 56 / 58 | 0.86 (no gain) |
| 0.20 + plain rank merge, no grade | 56 / 58 | 0.84 (no gain) |

Findings:

1. **The cut-off is the one real retrieval bug on this set.** Lowering it recovers `sf06`, `mf02`, `sn02`.
   Still missing: `sf07` (not yet investigated: it is also a separate case in the agent run) and `mx07`
   (public PDFs crowd the results).
2. **The keyword "any word" fallback and the merge change did not help here.** I had planned them; the data
   says skip them. They stay off the plan unless the retrieval test on the real Drive shows otherwise.
3. **Putting the file name in front of the text before embedding did not help** (pure vector, top 8 files:
   58/58 either way; MRR 0.836 vs 0.839). Smaller chunks (1,200 characters) gave MRR 0.856: small gain,
   costs a full re-index and 2.6x more chunks. Not worth doing now.
4. **A relevance score cannot tell "answerable" from "not in the files".** Best vector score, answerable
   cases: median 0.50 (range 0.29-0.74). Questions whose answer is NOT in the files: median 0.46 (range
   0.30-0.66). Traps such as `tr04` score 0.65. So no cut-off can decide refusal; the answer model and the
   claim check must decide it. The dead "grade" was never going to do it either.
5. **Ranking is fragile to wording.** Adding "In the company policy document," to the same questions drops
   "right file ranked first" from 39 to 22 of 53, because the metadata search treats "document" as a file
   name hint and returns the 20 newest files, and the "file name contains word" path fires on generic words
   ("policy", "report"). Ignoring generic file-name words and not padding with newest files recovered it
   to 31 of 53 (MRR 0.50 -> 0.75) with the cut-off at 0.20. Real users phrase questions this way, so this is
   a real fix, not a test-set trick.
6. **The agent, not retrieval, loses most of the remaining 19 points.** Retrieval alone puts the right file
   in the top 8 for 91 % of cases; the agent run found it in 81 %. The gap is: the agent never searched
   (`ru02`, `ca04`, `ca05`), wrote a poor query, or lost the topic in a follow-up (`fu02`, `fu04`).

## 3. The plan, in order

Rules for every step: its own branch, a real test, tune on the **dev** cases, report on the **test** cases,
keep the change only if it helps, `--no-ff` merge, then the full backend suite.

### Step 0 - A free retrieval test, committed (cost: about 0)
Turn the probes into `evaluation/rag_eval/retrieval_probe.py`: for every answerable case, "is the right file
in the top 8, at what rank, and does the answer-bearing chunk appear"; also a wording-robustness mode
(4 phrasings per question). Deterministic apart from caching embeddings. Everything in Steps 1-2 is tuned
with it first and confirmed with one paid run. Test: unit test on a fake retriever for the metric maths.

### Step 1 - Fix the retrieval bugs the probes proved (cost: about 0 to tune, one paid confirm)
1. **(1a, DONE 2026-11-20)** Vector cut-off 0.35 -> 0.25, plus a relative rule (a hit must score at least 70 % of
   the best hit). Chosen on dev with the probe, vetoed/confirmed on test; agent level, dev, 88 cases: 74 -> 79 pass,
   no case got worse (honest gain 2 to 3 cases, single runs). Details: `docs/EVALUATION_RESULTS.md`, "Step 1a".
2. (1b) Ignore generic file-name words (words that occur in many file names, e.g. "policy", "report", "document")
   in the "file name contains word" path, and stop the metadata search adding the newest files unless the
   user said "latest/newest/recent". Why: finding 5.
3. Remove the dead grade, or make it honest. Honest means: keep it only if it can reject; the probes say no
   score can, so the plan is to **delete the dead check** and rely on Step 4. Why: dead code that looks like
   a safety net is worse than none. (Legacy path tests must be updated in the same commit.)
4. **(1d, new, found in 1a)** A refusal with no citation markers gets "Sources consulted:" followed by every file the
   search returned (`finalize_answer`), e.g. 8 files, unrelated NIST PDFs included, on "release 1.4". Decide what a
   "not found" answer should show (recommended: no source list, or only files the answer actually names), then fix
   in `finalization.py` with a test. Before this step 15 of 29 refusals already carried citations.
5. Tool description and agent prompt: tell the model to search with short keyword queries (names, numbers,
   IDs, the topic), to run a second differently-worded search if the first returns nothing useful, and to
   include the topic from earlier turns when the user's message is a follow-up.
`sf07` ("Who is the Security Lead?") is a 1b case: `team_directory.txt` scores 0.43 by vector but ranks below 8 behind
public NIST chunks, and the keyword path puts `security_policy.txt` first only because the word "security" is in its
file name. Expected: right file found 81 % -> 88-90 % at agent level. Risk: more weak chunks reach the model on
unanswerable questions; guard: refusal cases (28 baseline + 16 not-found traps) must stay at or above 95 %.

### Step 2 - Make the agent search (cause B, part of C)
When the intent gate says "document question", force the first model step to call a tool
(`tool_choice="required"` for step one only). Why: the three "never searched" cases. Risk: one needless
search on a pure calculation; cost is one search, not a wrong answer.

### Step 3 - Prefer the current version (cause D)
Pass the file's modified date to the model next to each piece of evidence, and add one rule: "when sources
disagree, prefer the newest, mention the older value". The date is already stored; `summary()` currently
sets it to `None`. Test: the 7 version cases + `sv06` + the new `tr30` (an old version asked for BY NAME
must still get the old value).

### Step 4 - Make the claim check see the invention traps (cause E)
Today it asks "is this fact in the evidence?". The traps need two more questions: "is the sentence about the
same subject and scope as the evidence it relies on?" (CloudHost vs Larkspur, contractor vs employee, private
car vs company car) and "does the sentence say something is absent where the evidence is merely silent?".
Add both to the checker's prompt with the question given. Guard: planted test must keep 0 / 41 true
sentences removed, and the 18 control cases (below) must still pass.

### Step 5 - Experiment: a larger answering model
Run the traps on `gpt-5.4-mini` instead of `gpt-5.4-nano`. If invention drops a lot, the model is a better
fix than more checking code. The larger model is tested, not assumed (FaithEval, arXiv 2410.03727, found
bigger models are not always more faithful). Decide with data.

### Step 6 - Only if still needed
An optional re-ranker over the top 20 (a cross-encoder is about 45 ms, an LLM re-rank about 700 ms per the
benchmarks I found; Anthropic reports -67 % failed retrievals with re-ranking plus contextual retrieval, but
on large collections, not 55 files), section-aware chunking, `text-embedding-3-large`. Not planned: the
probes show no problem they would fix on this corpus.

## 4. The trap questions, improved

18 -> **49 cases** in `backend/evaluation/datasets/rag_v2_trap_cases.json`:

* The original 18 invention traps, unchanged.
* **13 new trap kinds:** wrong person/role (`tr19`), company car vs private car (`tr20`), a per-plan figure
  when only a general one exists (`tr21`), a quarter that does not exist (`tr22`), a rule behind a one-off
  credit (`tr23`), a false premise (`tr24`), a similar fact belonging to another party (`tr25`, `tr26`,
  `tr27`), and four **answerable look-alikes** that must NOT be refused: a stated "no" (`tr28`), two people with
  the same name (`tr29`), an old version asked for by name (`tr30`), a city that is not in the exception list
  (`tr31`).
* **18 control cases** (`tc01`-`tc18`): for each original trap, the nearest question that IS answered in
  the files. A system that "fixes" invention by refusing everything now fails 18 cases instead of scoring well.
* Every fact is one of the validator's verbatim anchors in the corpus text; the dataset validator and 13
  tests check this. Judge notes were written before any run, not after.

Limits: the cases are synthetic and written by us; 49 cases still give error bars of about +/- 12 points on
the trap score; `tr09` and `tr17` judging is debatable. The new cases have **not been run on the agent yet**:
that is the first paid run (dev split, about 0.10 USD) so the "before" number exists before any change.

## 5. Audit: other things found wrong or missing

| # | Finding | Action |
|---|---|---|
| 1 | Grade can never reject (best score always 0.5 / 0.3) | Step 1.3 |
| 2 | RRF score computed, then discarded by the re-ranker | Not changed: plain RRF measured equal (0.84 vs 0.86). Document it; do not tune it. |
| 3 | Filename-contains-word path scores 0.85 for generic words | Step 1.2 |
| 4 | Metadata search pads with newest files on words like "document" | Step 1.2 |
| 5 | Modified date never reaches the model | Step 3 |
| 6 | `tool_choice="auto"` plus "no tools needed" wording | Step 2 |
| 7 | One-line tool description, no query guidance, no follow-up rule | Step 1.4 |
| 8 | Claim check blind to subject/absence errors | Step 4 |
| 9 | One full-suite test (`test_normal_restart_preserves_live_claim_and_uncertain_build`) failed once under a 15-minute load run and passed 3 of 3 alone: a timing-sensitive lease test | Note only; look at it if it fails again. |
| 10 | `retrieval_top_k=8` counts chunks, so one long PDF can fill all 8 slots (`mx07`) | Measure in Step 0 (distinct files in top 8); fix only if proven. |
| 11 | No retrieval metrics in the eval harness | Step 0 |
| 12 | Evaluation is small and synthetic; repeats show +/- 2-3 case noise | Real-Drive test at the end, as agreed. |
| 13 | Railway `CHAT_MODEL` may still be `gpt-4o-mini`, which shuts down 2027-01-14 (not checked) | Check before December. |

## 6. Targets (same cases before and after)

| Measure | Now | After the plan |
|---|---|---|
| Right file in top 8, retrieval only (58) | 53 (91 %) | 56+ (96 %) |
| Right file found, agent (62) | 81 % | 90 %+ |
| Answer correct (67) | 82 % | 90 %+ |
| Refusal correct | 96 % | stay >= 95 % |
| Original 18 traps | 11 (61 %) | 14+ (78 %+) |
| New 18 control cases (must answer) | not yet run | >= 16 of 18 |
| True sentences wrongly removed (planted) | 0 / 41 | stay 0 |
| Median answer time | 4-5 s | no more than +1 s |

## 7. Budget (balance 1.56 USD, ceiling 1.50 USD)

Spent so far: about 0.50 USD (0.06 analysis probes; 0.44 for the two Step 1a agent runs, 88 cases each, 0.22 per run, which also serve as the dev-split baseline for later steps). About 1.0 USD remains under the 1.50 ceiling, so later steps should run on the cases they can change, not on everything. Steps 0, 1.1-1.3 are free to tune.
Estimates, not measurements: a full run of 94 + 49 cases is about 0.35-0.40 USD; a dev-only run about half.
Plan: baseline of the new traps (dev) 0.10, Step 1 confirm 0.20, Step 2 0.10, Step 3 0.10,
Step 4 + planted re-check 0.25, Step 5 (mini model, traps only) 0.15, final full run 0.35 = about 1.25 USD.
That fits under 1.50 with about 0.2 left; repeating a run for noise would not. No recharge is required, but
a small recharge would allow repeats. The meter stops every run at its `--cap`.

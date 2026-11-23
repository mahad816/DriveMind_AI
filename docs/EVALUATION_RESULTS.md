# Evaluation results log

Committed summary of measured results (raw run files stay local in `backend/evaluation/results/`,
which is gitignored). Newest first. Every entry states the commit, model and dataset so it can be
reproduced. Numbers here are measurements, not guarantees.

## M1-08-G: first-step retrieval on the frozen corpus (live, 2026-11-23)

**Frozen baseline.** These development and regression results are the baseline for future retrieval improvements. The three raw files (git-ignored, `backend/evaluation/results/`) must stay unchanged: `first_step_20261123_170039_G_smoke.json`, `first_step_20261123_170220_G_dev.json`, `first_step_20261123_171737_G_regression.json`. Later changes are compared against these numbers, on the same pools and the same store, not against re-tuned ones.

### 1. Objective and scope

**What is measured: the agent's first step only.** For each question the real chat model sees the production policy and tool descriptions and makes its first move: it calls a tool or not, and if it searches it writes the query. A search is then run through the real retriever. The **baseline** is the question text itself used as the one search query (embeddings only, no chat call). The experiment answers: does the first step bring back the expected file and the passage that holds the answer, compared with searching with the plain question? **It does not measure answers, citation faithfulness, later agent steps or the claim check.** Good retrieval numbers do not show a correct answer.

The headline is about the first step of the agent (routing plus query writing together), **not about query quality in isolation**: runs where the model wrote no query count as misses (an empty retrieval) by design. Section 6 separates the two causes.

No held-out case was run: both runs used the `dev` and `regression` splits only (the tool refuses `--split held_out`), and no held-out file was read. No prompt, threshold or retrieval logic was changed; nothing was tuned on these pools. Earlier work did shape the tool wording using the development pool, so the regression pool is the cleaner figure.

### 2. Corpus, index and configuration

| Item | Value |
|---|---|
| Repository state | branch `feature/v2-state-performance`, HEAD `48a6cf1`, no product code changed |
| Corpus | frozen M1 corpus `m1-corpus-v1-a605f90dc57b` |
| Store | `drivemind_eval_v3`: 82 files, 1,508 PostgreSQL chunks, 1,508 Qdrant vectors; `index_verify verify --store v3` passed before the run (free, deep check); receipt `index_manifest_m1-corpus-v1-a605f90dc57b_v3_20261123_091309.json`; no rebuild |
| Chat model | `gpt-5.4-nano` (served as `gpt-5.4-nano-2026-03-17`), temperature 0, `max_completion_tokens` 1000, SDK retries 0 |
| Embedding model | `text-embedding-3-small` |
| Prompt | `prompt_id` `04f0d4746267b81e` |
| Retrieval | `retrieval_top_k` 8, `candidate_limit` 20 |
| Command | `python -m evaluation.rag_eval.first_step_probe --frozen --store v3 --split dev\|regression --mode both --repeats 2 --passage` |
| Pools | development and regression (`case_source: pools`); both runs have identical settings apart from the split (rows of the regression run carry the older label `"split": "test"`; the setting says `regression`) |

### 3. What counts as a case

| Term | Development | Regression |
|---|---|---|
| **All cases in the frozen pool** | 201 | 81 |
| Filtered before running: chit-chat (`ch01` to `ch04`; the intent gate answers these before the agent, so they were never sent to the model) | 3 | 1 |
| **Cases run** (sent to the model in the model-mode run) | **198** | **80** |
| Of the cases run, not paired: no expected file (never scored for retrieval) | 46 | 21 |
| Of the cases run, not paired: inventory questions (the listing tool is legitimate) | 3 | 1 |
| Of the cases run, not paired: expected file but conversation history (the baseline needs a stand-alone question) | 11 | 2 |
| **Eligible paired cases** (content, expected file, no history) | **138** | **56** |
| **Case-repeat observations** (eligible cases x 2 repeats) | **276** | **112** |

The 60 and 24 cases that were run but not paired (46 + 3 + 11 and 21 + 1 + 2) were sent to the model, so the cost covers 198 and 80 cases, but they are not part of any paired figure below. The 4 chit-chat cases were filtered before running and cost nothing. "Eligible" and "paired" below always mean the 138 and 56 cases; "all cases" means the 201 and 81 of the frozen pool; "run" means the 198 and 80. Case-repeat observations are not independent: the same question appears twice. **All confidence intervals below are Wilson 95% intervals over cases (n = 138 or 56), never over observations.** Observation counts are used only for descriptive counts. Caveat for interpretation: a handful of cases drives many of the differences (Section 9).

### 4. File-level results (is the expected file among the candidates?)

| | Development | Regression |
|---|---|---|
| Baseline, observations | 274 / 276 (99.3%) | 112 / 112 (100%) |
| Model first step, observations | 251 / 276 (90.9%) | 101 / 112 (90.2%) |
| Both found / baseline only / model only / neither | 251 / 23 / 0 / 2 | 101 / 11 / 0 / 0 |
| Baseline, cases (95% CI) | 137 / 138 (96.0 to 99.9) | 56 / 56 (93.6 to 100) |
| Model repeat 1, cases (95% CI) | 125 / 138 (84.5 to 94.4) | 51 / 56 (80.7 to 96.1) |
| Model repeat 2, cases (95% CI) | 126 / 138 (85.4 to 95.0) | 50 / 56 (78.5 to 95.0) |
| File-level MRR, baseline / model | 0.847 / 0.796 | 0.906 / 0.741 |
| Ranked first, baseline (of 138 / 56 cases) | 101 | 47 |
| Ranked first, model (of 276 / 112 observations) | 195 | 71 |

The model never found a file that the baseline missed (model only = 0). That statement is about whether the file was found; for rank the two differ in both directions.

### 5. Passage-level results (is the chunk with the answer among the top 8?)

Measured over the same 138 and 56 cases on every side (`same_cases: true`). "Any" = at least one anchor chunk found; "all" = every anchor found. MRR = mean reciprocal rank of the first anchor chunk.

| | Dev baseline | Dev model repeat 1 | Dev model repeat 2 | Reg baseline | Reg model repeat 1 | Reg model repeat 2 |
|---|---|---|---|---|---|---|
| Any anchor found | 134/138 = 97.1% (92.8 to 98.9) | 121/138 = 87.7% (81.2 to 92.2) | 122/138 = 88.4% (82.0 to 92.7) | 55/56 = 98.2% (90.6 to 99.7) | 50/56 = 89.3% (78.5 to 95.0) | 49/56 = 87.5% (76.4 to 93.8) |
| All anchors found | 130/138 = 94.2% | 118/138 = 85.5% | 119/138 = 86.2% | 55/56 = 98.2% | 49/56 = 87.5% | 49/56 = 87.5% |
| Mean anchor coverage | 0.957 | 0.866 | 0.873 | 0.982 | 0.884 | 0.875 |
| MRR | 0.811 | 0.743 | 0.750 | 0.885 | 0.709 | 0.715 |
| Mean file recall | 0.976 | 0.893 | 0.900 | 1.000 | 0.902 | 0.893 |
| No anchor in top 8 | 4 | 17 | 16 | 1 | 6 | 7 |
| Right file, wrong passage | 3 | 4 | 4 | 1 | 1 | 1 |

The intervals of baseline and model do not overlap on development (92.8 to 98.9 against 81.2 to 92.2) and overlap on regression because of its small size (90.6 to 99.7 against 78.5 to 95.0). The direction is the same in both pools and both repeats. The pools are small, so the exact gap is uncertain.

**Baseline weaknesses** (these exist without any model): dev cases with no anchor in the top 8: `an03`, `pb05`, `px03`, `td01` (`an03`, `pb05`, `td01` have the right file and the wrong passage); regression: `pb02` (right file, wrong passage). Only 97 of 138 dev baseline cases rank the answer chunk first (MRR 0.811).

### 6. Routing failures versus search-quality failures

**Routing failure** = the first step made no search: the model called no tool, or called `resolve_file` instead of `search_knowledge`. **Search-quality failure** = the model searched and the expected file was not among the candidates. This is counted over the paired observations only.

| Paired observations | Development (276) | Regression (112) |
|---|---|---|
| First tool: `search_knowledge` | 265 | 104 |
| First tool: `resolve_file` | 7 | 4 |
| First tool: no tool | 4 | 4 |
| **Routing failures (no search)** | **11** | **8** |
| Searched and found the file | 251 | 101 |
| **Search-quality failures (searched, missed)** | **14** | **3** |
| Model misses in total | 25 | 11 |
| Of which the baseline found the file (the gap) | 23 = 11 routing + 12 search | 11 = 8 routing + 3 search |
| Of which the baseline also missed | 2 (both searched) | 0 |
| When the model searched: model found / baseline found on the same observations | 251/265 (94.7%) / 263/265 (99.2%) | 101/104 (97.1%) / 104/104 (100%) |
| File-level MRR over searched observations, model / baseline | 0.829 / 0.849 | 0.798 / 0.908 |

Reading: the two failure types have to be kept apart, and neither one explains the gap alone. **Development:** of the 23 observations the baseline found and the model missed, 11 are routing failures (the agent made no search) and 12 are search-quality failures (it searched and the file was not among the candidates). **Regression:** of the 11, 8 are routing failures and 3 are search-quality failures. Routing is the larger part only in regression. Among the searches the model did make, it missed the file in 14 of 265 observations (5.3%) on development and 3 of 104 (2.9%) on regression, against 2 of 265 (0.8%) and 0 of 104 for the baseline on the same observations, and its ranks are worse (file-level MRR 0.829 against 0.849 on development, 0.798 against 0.908 on regression). So the model's searches are measurably worse than the plain question too, not only its decision whether to search. Neither cause should be called "query quality" alone.

A caution on routing: some `resolve_file` first moves are on questions that name a file (`id16`, `id17`, category `named_file`), where resolving the name first may be a legitimate first step. This probe stops after the first model call and cannot see whether the agent would then search. It counts them as misses by design.

**Case lists** (non-sensitive ids; development and regression pools only):

| | Development | Regression |
|---|---|---|
| Routing failure in both repeats | `ca05`, `ru05` (no tool); `id17`, `vi07`, `wf01` (`resolve_file`) | `ca04`, `ru02` (no tool); `id14`, `id16` (`resolve_file`) |
| Routing failure in one repeat only | `id13` (`resolve_file` once, searched once) | none |
| Searched and missed in both repeats | `ac01`, `id01`, `id03`, `id11`, `px03`, `sn03`, `xl01` | `sf07` |
| Searched and missed in one repeat only | none | `vr05` |

### 7. Equal budget versus real budget

The baseline makes one search and takes at most 8 chunks. **Equal budget** cuts the model's results to the same total as the baseline; **real budget** gives the model's searches in full. Observed chunk counts, not the cap, describe the budget: the baseline averaged 5.978 chunks (development) and 6.071 (regression); the model averaged 6.022 and 5.795 chunks per run (counting a chunk returned by two searches once; see Section 13), with 0.967 and 0.929 searches per run.

The equal-budget and real-budget results are almost the same (development any-found 87.7% and 88.4% in both views; MRR 0.743 and 0.750 against 0.742 and 0.749). They coincide because the model almost never searched twice: 2 of 390 development content runs and 0 of 158 regression content runs made more than one search in the first step. **This experiment cannot show whether extra searches would help or not**, because there are too few examples.

### 8. Repeat consistency

Temperature is 0, 2 repeats. File level, per case: development 125 found in both repeats, 12 missed in both, 1 split (`id13`); regression 50, 5 and 1 (`vr05`). The first tool differed between repeats in 1 development case and 0 regression cases; the query text was identical in both repeats in 118 of 138 and 48 of 56 cases. The misses are therefore systematic, not noise: the same ids fail again on the second repeat. Passage-level repeat figures are in Section 5 (differences of 0.7 and 1.8 points between repeats).

### 9. Results by case type and document format

A case has one category and one format. Column "cases" is the number of paired cases of that kind and is the denominator of every count in the row. Each "any" cell is the number of those cases with at least one anchor chunk in the top 8, as "found/cases". The model columns are one repeat each (repeat 1 and repeat 2), counted over cases, not observations. MRR is the mean reciprocal rank over the same cases. **Most categories have fewer than 10 cases and many have 1 to 3, so these rows are anecdotal.** No interval is given per row.

Largest differences (development, model repeat 1 / 2 against baseline): `identifier_in_question` 9 and 10 of 14 against 14 of 14 (MRR 0.46 and 0.53 against 0.76); `table_lookup` 12 of 14 against 14; `calculation_dates` 11 of 13 against 12; `public_document` 1 of 3 against 2 of 3. Regression: `identifier_in_question` 6 of 7 against 7 (MRR 0.54 against 0.93); `roman_urdu` 0 of 1 against 1 of 1; `named_file` 0 of 1 against 1 of 1. By format, `pdf` (development 15 and 16 of 20 against 18) and `csv` (4 of 6 against 6) show the largest relative drops, and `txt` the largest absolute loss because it has the most cases (development 53 of 61 against 60; regression 34 of 38 against 38). Several categories are equal or better for the model (for example `trap_control` MRR 1.00 against 0.87 in development).

**Development, by category**

| category | cases | baseline any | base MRR | model r1 any | r1 MRR | model r2 any | r2 MRR |
|---|---|---|---|---|---|---|---|
| multi_file_synthesis | 15 | 15/15 | 0.81 | 15/15 | 0.73 | 15/15 | 0.73 |
| identifier_in_question | 14 | 14/14 | 0.76 | 9/14 | 0.46 | 10/14 | 0.53 |
| table_lookup | 14 | 14/14 | 0.92 | 12/14 | 0.82 | 12/14 | 0.82 |
| calculation_dates | 13 | 12/13 | 0.71 | 11/13 | 0.65 | 11/13 | 0.65 |
| injection | 10 | 10/10 | 0.75 | 10/10 | 0.75 | 10/10 | 0.75 |
| invention_trap | 9 | 9/9 | 0.81 | 9/9 | 0.69 | 9/9 | 0.69 |
| superseded_version | 9 | 9/9 | 0.83 | 8/9 | 0.78 | 8/9 | 0.78 |
| trap_control | 9 | 9/9 | 0.87 | 9/9 | 1.00 | 9/9 | 1.00 |
| single_fact | 7 | 7/7 | 0.86 | 7/7 | 0.86 | 7/7 | 0.86 |
| aggregation_list_count | 5 | 5/5 | 0.90 | 5/5 | 0.90 | 5/5 | 0.90 |
| same_name | 5 | 5/5 | 0.84 | 4/5 | 0.80 | 4/5 | 0.80 |
| roman_urdu | 4 | 4/4 | 0.71 | 3/4 | 0.75 | 3/4 | 0.75 |
| multi_fact_one_file | 3 | 3/3 | 0.83 | 3/3 | 0.83 | 3/3 | 0.83 |
| public_document | 3 | 2/3 | 0.67 | 1/3 | 0.33 | 1/3 | 0.33 |
| second_sheet | 3 | 3/3 | 1.00 | 3/3 | 1.00 | 3/3 | 1.00 |
| slide_bullets | 3 | 2/3 | 0.67 | 2/3 | 0.67 | 2/3 | 0.67 |
| ruled_table | 2 | 2/2 | 1.00 | 2/2 | 1.00 | 2/2 | 1.00 |
| tentative_vs_decided | 2 | 1/2 | 0.50 | 1/2 | 0.50 | 1/2 | 0.50 |
| borderless_table | 1 | 1/1 | 1.00 | 1/1 | 1.00 | 1/1 | 1.00 |
| named_file | 1 | 1/1 | 0.50 | 0/1 | 0.00 | 0/1 | 0.00 |
| page_two | 1 | 1/1 | 1.00 | 1/1 | 1.00 | 1/1 | 1.00 |
| paragraph_after_table | 1 | 1/1 | 1.00 | 1/1 | 1.00 | 1/1 | 1.00 |
| slide_notes | 1 | 1/1 | 1.00 | 1/1 | 1.00 | 1/1 | 1.00 |
| slide_textbox | 1 | 1/1 | 1.00 | 1/1 | 1.00 | 1/1 | 1.00 |
| stale_vs_current | 1 | 1/1 | 1.00 | 1/1 | 1.00 | 1/1 | 1.00 |
| two_columns | 1 | 1/1 | 0.50 | 1/1 | 0.50 | 1/1 | 0.50 |

**Development, by document format**

| format | cases | baseline any | base MRR | model r1 any | r1 MRR | model r2 any | r2 MRR |
|---|---|---|---|---|---|---|---|
| txt | 61 | 60/61 | 0.78 | 53/61 | 0.72 | 53/61 | 0.72 |
| pdf | 20 | 18/20 | 0.84 | 15/20 | 0.63 | 16/20 | 0.68 |
| xlsx | 13 | 13/13 | 0.86 | 12/13 | 0.79 | 12/13 | 0.79 |
| pptx | 11 | 10/11 | 0.62 | 10/11 | 0.68 | 10/11 | 0.68 |
| docx | 10 | 10/10 | 0.87 | 10/10 | 0.88 | 10/10 | 0.88 |
| md | 8 | 8/8 | 0.91 | 8/8 | 0.94 | 8/8 | 0.94 |
| csv | 6 | 6/6 | 0.92 | 4/6 | 0.67 | 4/6 | 0.67 |
| pdf+pptx | 2 | 2/2 | 0.75 | 2/2 | 1.00 | 2/2 | 1.00 |
| pdf+xlsx | 2 | 2/2 | 1.00 | 2/2 | 0.75 | 2/2 | 0.75 |
| csv+pdf | 1 | 1/1 | 1.00 | 1/1 | 1.00 | 1/1 | 1.00 |
| csv+xlsx | 1 | 1/1 | 1.00 | 1/1 | 1.00 | 1/1 | 1.00 |
| docx+pdf | 1 | 1/1 | 1.00 | 1/1 | 1.00 | 1/1 | 1.00 |
| docx+xlsx | 1 | 1/1 | 0.50 | 1/1 | 0.50 | 1/1 | 0.50 |
| pptx+xlsx | 1 | 1/1 | 1.00 | 1/1 | 1.00 | 1/1 | 1.00 |

**Regression, by category**

| category | cases | baseline any | base MRR | model r1 any | r1 MRR | model r2 any | r2 MRR |
|---|---|---|---|---|---|---|---|
| trap_control | 9 | 9/9 | 0.86 | 9/9 | 0.76 | 9/9 | 0.76 |
| identifier_in_question | 7 | 7/7 | 0.93 | 6/7 | 0.54 | 6/7 | 0.54 |
| invention_trap | 7 | 7/7 | 0.86 | 7/7 | 0.73 | 7/7 | 0.73 |
| table_calc | 4 | 4/4 | 0.88 | 4/4 | 0.88 | 4/4 | 0.88 |
| table_lookup | 4 | 4/4 | 1.00 | 4/4 | 0.88 | 4/4 | 0.88 |
| single_fact | 3 | 3/3 | 0.73 | 2/3 | 0.50 | 2/3 | 0.50 |
| aggregation_list_count | 2 | 2/2 | 1.00 | 2/2 | 0.67 | 2/2 | 0.67 |
| calculation_dates | 2 | 2/2 | 0.75 | 1/2 | 0.50 | 1/2 | 0.50 |
| multi_fact_one_file | 2 | 2/2 | 1.00 | 2/2 | 0.75 | 2/2 | 0.75 |
| multi_file_synthesis | 2 | 2/2 | 1.00 | 2/2 | 1.00 | 2/2 | 1.00 |
| superseded_version | 2 | 2/2 | 1.00 | 2/2 | 0.75 | 2/2 | 1.00 |
| borderless_table | 1 | 1/1 | 1.00 | 1/1 | 1.00 | 1/1 | 1.00 |
| bullet_list | 1 | 1/1 | 1.00 | 1/1 | 1.00 | 1/1 | 1.00 |
| last_page | 1 | 1/1 | 1.00 | 1/1 | 1.00 | 1/1 | 1.00 |
| named_file | 1 | 1/1 | 1.00 | 0/1 | 0.00 | 0/1 | 0.00 |
| page_two | 1 | 1/1 | 1.00 | 1/1 | 1.00 | 1/1 | 1.00 |
| public_document | 1 | 0/1 | 0.00 | 0/1 | 0.00 | 0/1 | 0.00 |
| roman_urdu | 1 | 1/1 | 1.00 | 0/1 | 0.00 | 0/1 | 0.00 |
| same_name | 1 | 1/1 | 1.00 | 1/1 | 1.00 | 1/1 | 1.00 |
| slide_bullets | 1 | 1/1 | 1.00 | 1/1 | 1.00 | 1/1 | 1.00 |
| slide_notes | 1 | 1/1 | 1.00 | 1/1 | 1.00 | 1/1 | 1.00 |
| tentative_vs_decided | 1 | 1/1 | 1.00 | 1/1 | 1.00 | 1/1 | 1.00 |
| two_columns | 1 | 1/1 | 0.12 | 1/1 | 0.17 | 0/1 | 0.00 |

**Regression, by document format**

| format | cases | baseline any | base MRR | model r1 any | r1 MRR | model r2 any | r2 MRR |
|---|---|---|---|---|---|---|---|
| txt | 38 | 38/38 | 0.89 | 34/38 | 0.67 | 34/38 | 0.69 |
| pdf | 9 | 8/9 | 0.79 | 7/9 | 0.69 | 6/9 | 0.67 |
| pptx | 4 | 4/4 | 0.88 | 4/4 | 0.88 | 4/4 | 0.88 |
| docx | 3 | 3/3 | 1.00 | 3/3 | 0.83 | 3/3 | 0.83 |
| xlsx | 2 | 2/2 | 1.00 | 2/2 | 1.00 | 2/2 | 1.00 |

### 10. Usage and cost (application meter; not a provider invoice)

| Stage | Cap | Plan | Metered | Chat calls | Chat input / output tokens | Embedding calls |
|---|---|---|---|---|---|---|
| Smoke (1 case, `ix01`) | 0.01 | 0.00092 | 0.00029 | 1 | 1,174 / 42 | 2 |
| Development | 0.40 | 0.36342 | 0.11615 | 396 | 466,790 / 18,152 | 427 |
| Regression | 0.20 | 0.14666 | 0.04657 | 160 | 188,154 / 7,123 | 164 |
| **Total** | | | **0.16301** (of 1.00 authorized) | 557 | 656,118 / 25,317 | 593 |

Recomputed from the tokens at the checked prices the three totals equal the meter's figures. No failed, cancelled or missing-usage calls; every run `complete`; the cap was never reached. The plan over-estimated cost about three times. Cached input tokens were 0 on all calls, so the meter charged the full input price. Reasoning tokens are not reported separately; output averaged about 45.5 tokens per call, so reasoning is negligible here. The 0.01878 USD index rebuild (Owner-reported) is outside this total; with it the combined figure is 0.18179 USD. The provider's billing page was not checked.

### 11. Prices

On 2026-11-23 the official pages (`developers.openai.com/api/docs/pricing` and the model pages for each) were read for the only two models used in G: `gpt-5.4-nano` 0.20 input, 0.02 cached input, 1.25 output USD per 1M tokens, and `text-embedding-3-small` 0.02 input. Both equal `prices.json`; no price was changed. `prices.json` has one table-wide `checked_on` date and no per-model dates, so it was **left at 2026-11-19**: the other rows (`gpt-5.4-mini`, `gpt-5.4`, `gpt-6-luna`, `gpt-5-mini`, `gpt-4o-mini`) were not re-read and this verification does not cover them. The model page marks `gpt-5.4-nano` and its snapshot `gpt-5.4-nano-2026-03-17` as **deprecated** while the pricing page still lists it; the model is a dependency to plan for.

### 12. Failure patterns

1. **First-move routing**: in 4% of development observations (11/276) and 7% of regression observations (8/112) the model does not search. Cases: calculation questions (`ca05`, `ca04`), roman-Urdu (`ru05`, `ru02`), a table lookup (`vi07`), a superseded-version question (`wf01`), and questions that name a file or an identifier (`id13`, `id14`, `id16`, `id17`).
2. **Identifier questions underperform; the reason is unproven.** Development `identifier_in_question` (14 cases): the plain question finds an anchor in 14 of 14, the model's first step in 9 and 10 of 14. `id01`, `id03`, `id11`, `ac01` are searched and missed in both repeats. The recorded queries do keep the identifier (`id01`: "INC-204 root cause"; `id03`: "INC-211 how long did incident last duration"), but they are short keyword strings, unlike the full question. Why those searches miss was not established by this experiment. `docs/KNOWN_ISSUES.md` KI-027 records an earlier hypothesis (generic words match other documents strongly) that is still unmeasured. Within this category only `id13` (one development repeat) and `id14` (regression) are confirmed routing misses, where the model made no search. `id16` and `id17` made no search either but are `named_file` cases, not identifier cases (Section 6).
3. **Other stable search misses**: `px03` (`slide_bullets`), `sn03` (`same_name`), `xl01` (`table_lookup`) on development, `sf07` (`single_fact`) on regression; `vr05` (`two_columns`) misses in one repeat.
4. **Rank quality**: even where the file is found the model puts the answer chunk lower (regression MRR 0.709 and 0.715 against 0.885).
5. **Baseline weaknesses** (Section 5): wrong passage, public documents and slide bullets.

### 13. Limitations

- **First step only**: not answers, citations, the later agent steps or the claim check.
- One chat model, one prompt, 2 repeats; the exact size of the effects is uncertain, especially in regression (56 cases).
- Category and format rows are mostly very small; no multiple-comparison control, no per-row intervals.
- The development pool helped shape the tool wording in earlier work; regression is the cleaner pool. Neither was tuned in G.
- The figures are retrieval results at one `top_k`; they do not show that a different `top_k` or a different retriever would behave the same.
- Two ways of counting the model's mean chunks per development run gave 6.022 (report) and 6.065 (an offline recomputation); the difference is explained: case `mg02` was searched twice in both repeats and each run returned 16 chunks; the passage view counts a chunk once and drops 6 duplicate chunks per run, 12 chunks over 276 runs (0.043). The regression figure agreed (5.795).
- Cost is the application meter. The pricing check was made on official pages; the rebuild cost is Owner-reported.
- Not done (outside the authorization, so ticket 08 stays open): the held-out aggregate, lead-in wordings, the refusal best-score distribution, the sanity check against older figures, a determinism rerun, and registering defects.

### 14. Recommendations (not authorized work)

1. Treat these numbers as the baseline. Any change to the tool wording, routing or query writing must report both failure kinds separately: no-search rate and search-and-miss rate, on the same two pools and this store.
2. Both causes need attention: of the 36 paired model misses (25 development, 11 regression), 19 come from no search at all (11 and 8) and 17 from a search that missed (14 and 3). This data does not show which is cheaper to fix. Whether `resolve_file` first on a named file is acceptable needs the full agent loop to judge.
3. Identifier questions: first establish why the model's short queries miss where the full question succeeds (for example by running both through the same retriever on the four stable cases, see KI-027), before choosing a remedy. This is a separate Owner-approved task.
4. Plan for the deprecation of `gpt-5.4-nano` before the next live evaluation.

Reproduction of the figures: `recompute_g.py` (free, offline, reads the three result files) in the review-evidence folder outside Git; its output equals every number above.

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

First-step probe on the 7 invoice questions (10 repeats each, $0.019): the first tool was `resolve_file` in 25 of 70 runs
(`vi04`, `vi07` always, `vi05` half the time, the other four never), `search_knowledge` otherwise; when it searched, the
right file came back 35 of 35. Details in KI-025.
After the `resolve_file` argument wording change (KI-025, same probe): 2 of 70 runs; test split unchanged case by case.

**After the KI-025 fix, the same 39 questions again (one run, $0.108, result file `..._all_all_messy_ki025.json`):**
**35 / 39** (89.7%, 95% interval 76-96%), evidence found 33/34, answer correct 33/34, refusal 3/5, latency median 4.6 s,
no API errors (the earlier run had one). Case by case against the 33/39 run: `vi04`, `vi05`, `vi07` fail -> pass;
`vi06` pass -> fail (same answer, grader flipped: see the next paragraph); `dx08`, `px03`, `xl04` fail in both runs. The agent
and grader are not deterministic, so a difference of one or two cases between runs is within noise; the three
invoice fixes are backed by the first-step probe (25/70 -> 2/70), not only by this run.
**`vi06` replaced by `vi08` (2026-11-20, after seeing this result, so it is a change to a test-split question and should be read as one).**
`vi06` ("What discount was applied on invoice INV-0457?") was labelled "not in the files", but the invoice does answer
it (there is no discount), and a correct reply quotes the subtotal, VAT and total, which the not-found grader rule
forbids. The rule is right (it is what catches invented values such as `dx08`'s fee), so the question was changed, not
the grader: `vi08` asks for the VAT registration number, which the invoice does not contain. Its reply must now name
no value. `vi08` then exposed that KI-025 is not fully fixed (it goes to the file-name lookup every time), and showed
the grader passing that wrong-route reply, so `judge_row` now fails it. Net effect on the 39-question score: none
expected (`vi06` failed in the run above and `vi08` fails today); not re-run.
Metric note: "clean" is 0/5 in both runs because refusals still attach a citation to the file they searched.

How to read it: 39 questions, one run, error bars about +/- 14 points; use it as the baseline Stage B is compared
against, not as proof of anything smaller than about 15 points. The set was built by the same author as the readers
(the questions describe what the fixtures contain).

## KI-025 on a held-out question set (2026-11-20)

**Why a held-out set.** The first KI-025 fix was tuned and measured on the same 7 invoice questions and looked like
25 of 70 -> 2 of 70. A new question about the same invoice (`vi08`) went to the wrong tool in 20 of 20 runs, so the
fix did not generalise. This set was written afterwards and **before any further code change**.

`backend/evaluation/datasets/rag_v2_identifier_cases.json` (19 questions, run with `--dataset rag_v2_identifier_cases.json
--with-messy`): 15 identifier questions (incidents INC-204/211/219/231/236, contract SG-7731, patches 1.3.1/1.3.2,
invoice INV-0457), 2 that name an existing file, 2 that name a file that does not exist (one with an extension, one
without). SHA-256 when first measured `1d9f4f05...`; after one correction (`id10`, below) `7f5f4dfd...`; not edited since.
Correction: `id10` "Why was patch 1.3.1 rolled back?" was answered correctly from the incident report, but the gold
required the release notes; two files answer it, so the gold now accepts either (same kind of flaw as `vi06`; the
baseline was re-scored with the corrected gold).

| Measurement (same questions, `gpt-5.4-nano`) | Before (committed code) | After (final change) |
|---|---|---|
| End to end, 19 questions | 14 (13 before the gold correction) | **16** |
| First tool for the 15 identifier questions that was `resolve_file` | 10 of 150 (`id14` 10 of 10) | 10 of 150 (`id14` 10 of 10): prevention unchanged |
| `id14` end to end (the question that always starts with the lookup), 10 extra runs | first call to the lookup 10 of 10; the one end-to-end run ended with the lookup-failure text (certain under the old rule) | **10 of 10 correct**: lookup -> hint -> search -> "$350.00" with citation |
| Cost of one set (first step 10 repeats + end to end) | $0.054 + $0.063 | $0.054 + $0.047 |

Failures left (16 of 19 pass): `id01`, `id11` (retrieval of identifier questions, KI-027) and `id19` (a document that
does not exist is answered from a related one, KI-028). `id04` flipped between runs with identical code paths (fail,
fail, pass, pass): it is part of KI-027 and is not counted as this fix's gain.

**Regression checks on the final change (all `gpt-5.4-nano`, same store plus the 5 messy files):**

| Check | Before | After |
|---|---|---|
| Test split, first tool, 106 runs | 98 search, 8 no tool, 64 of 66 right file | identical |
| `ru06` (Roman-Urdu "not in the files"), searched, 20 runs | 17 to 18 of 20 | **20 of 20** |
| `pb02` (NIST question), searched, 20 runs | 2 of 2 | **20 of 20** |
| Older dev set end to end (88 questions, `rag_v2_cases` + `rag_v2_trap_cases`) | 77 (run of the same morning, before the messy files and Stage A readers) | **78**; 4 questions better, 3 worse, 1 error |
| Messy set end to end (39) | 35 (run earlier today) | 34: `dx08`, `px03`, `xl04` fail as before, `vi05` and `vi08` ended in `ChatError` (KI-026); `vi06` was replaced by `vi08` |

The older-dev comparison run was made hours earlier on the same store; its reader code and the messy files differ, so
a difference of one or two questions is noise, not a result. A control run of the old code on the same day was not made
(it would cost about $0.22) because the final run did not drop.

**Two prompt-wording attempts that were rejected, with their numbers** (also in `docs/DECISIONS.md`): advice in the tool
description made `ru06` stop searching (17 of 20 -> 1 of 20 and 0 of 20); advice in the system prompt did the same
(0 of 20), made `pb02` skip the tools, and the older dev set fell 77 -> 72. Neither is in the code.

**`vi06` replaced by `vi08` (test split, changed after seeing a result):** `vi06` ("What discount was applied on
invoice INV-0457?") was labelled "not in the files", but the invoice answers it (no discount) and a correct reply
quotes its figures, which the not-found grader rule forbids. The rule is right (it catches invented values such as
`dx08`'s fee), so the question was changed, not the grader. `vi08` asks for the VAT registration number, which the
invoice does not contain.

## KI-026: a bad citation marker gets one corrective turn (2026-11-20)

| Measurement (`gpt-5.4-nano`) | Before | After |
|---|---|---|
| "Late payment fee on INV-0457", traced real runs ending in `ChatError` | 3 of 14 | **0 of 40** counted runs (bad marker appeared 2 times, both corrected) |
| Messy set (39 questions), end to end | 34 (2 errors: `vi05`, `vi08`) | **36, 0 errors** ($0.108) |
| `dx08`, `px03`, `xl04` | fail | fail (KI-028, KI-030, KI-029; unchanged) |

The 2 questions that changed are exactly the 2 errors. The 3 remaining failures are the known model/retrieval ones.
The 40 counted runs are two batches of 20, the second after the code review changed the retry note. A first batch (4 bad markers) is not counted: its error total was not recorded.

## Earlier baselines (pre-existing)

See `backend/evaluation/analysis/baseline_v1_failure_analysis.md` (Gold v1, 24 cases, 2026-09-21: routing 20/24)
and `backend/evaluation/experiments/` for experiments 01 to 03. These predate the tool agent and the intent gate.

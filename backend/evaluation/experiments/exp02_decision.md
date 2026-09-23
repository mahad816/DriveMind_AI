# EXP-02 Decision — Gated Source Diversity

## Decision

**KEEP.** Commit `5350222a1445673030fde5901d36fd5b768aa535` should remain as the accepted prompt-context selection behavior. This is a decision about the gated promotion policy, not a claim that the full RAG system is free of answer or citation failures.

## Experiment Question

EXP-01's unconditional source diversity raised prompt expected-file recall from 88.64% to 95.45% and multi-document all-expected coverage from 4/7 to 6/7, but lowered macro expected-source precision from 44.05% to 38.81% and raised mean unexpected prompt sources from 1.43 to 2.24. Could a score gate retain the coverage while reducing weak distinct-source promotion?

## Change Tested

EXP-02 promotes the first chunk from a new `drive_file_id` ahead of the earliest deferred repeated-source chunk only when its final rerank score is at least 90% of that repeated chunk's score. Denied candidates remain in stable input order and their source is still marked encountered. Filename prioritization remains upstream; context packing remains downstream. The gate does not filter candidates, change scores or budgets, or modify routing, retrieval, RRF, reranking, evidence grading, rewriting, generation prompts, models, or citation normalization.

## Evidence Used

- Committed [EXP-02 design](exp02_gated_source_diversity_design.md) and [comparative analysis](exp02_comparative_analysis.md).
- Baseline artifact `drivemind_gold_v1__20260921T143023Z__f93736aa.json`, SHA-256 `f22435ec26a561a248b782bba5f8ded2d3b6ae2bb759db30712e795af53d61db`.
- EXP-01 artifact `drivemind_gold_v1__20260922T101951Z__42b59a1b.json`, SHA-256 `f32e5d85eab34366a963609411875cba3b94ba025f3a9e395da3bc700c5d115e`.
- EXP-02 artifact `drivemind_gold_v1__20260922T200620Z__5350222a.json`, SHA-256 `e7b9af8c98c2f8e1b36620a4076c2c0f131b4075f497fa5e3b16b9bf4b667c0d`.
- [Completed targeted EXP-02 human review](../reviews/exp02_human_review.json), SHA-256 `6caec4048394fd9bc9c4186fcabbaf5222990e9c52816f18bc79de848f72c7b7`.

The three artifacts have the same 24 Gold IDs, evaluation user, corpus manifest and fingerprint, and recorded benchmark configuration. All 24 cases completed without execution errors in each run. Values below were recomputed from case-level prompt chunks, citations, answer match flags, routes, outcomes, rewrites, and timings. Raw retriever, RRF, rerank, and accepted-evidence chunk IDs and order match between EXP-01 and EXP-02 for every case. This is an observed single-run comparison, not proof of deterministic answer generation.

## Deterministic Results

| Metric | Baseline | EXP-01 | EXP-02 | EXP-02 vs EXP-01 |
| --- | ---: | ---: | ---: | --- |
| Route accuracy | 83.33% | 83.33% | 83.33% | unchanged |
| Prompt expected-file recall | 88.64% | 95.45% | 95.45% | unchanged |
| Multi-document all expected in prompt | 4/7 | 6/7 | 6/7 | unchanged |
| Macro expected-source precision | 44.05% | 38.81% | 46.43% | +7.62 pp |
| Mean unexpected prompt sources | 1.43 | 2.24 | 1.57 | −0.67 |
| Citation expected-source recall | 65.91% | 77.27% | 86.36% | +9.09 pp observed |
| Cases citing all expected sources | 14/22 | 16/22 | 19/22 | +3 observed |
| Mean lexical must-include coverage | 91.18% | 88.82% | 88.82% | unchanged |
| Cases with every lexical must-include phrase | 14/17 | 13/17 | 13/17 | unchanged |
| Rewrites | 0 | 0 | 0 | unchanged |
| Pipeline abstentions | 0 | 0 | 0 | unchanged |
| Median total latency | 3.90 s | 3.24 s | 3.57 s | +0.33 s observed |
| P95 total latency | 7.48 s | 6.22 s | 9.32 s | +3.09 s observed |
| Execution errors | 0 | 0 | 0 | unchanged |

The four EXP-02 prompt metrics exactly reproduce the offline replay: 95.45% recall, 6/7 multi-document coverage, 46.43% precision, and 1.57 unexpected sources. Citation and answer differences are observed outcomes, not automatically attributable to the ordering gate. Single-run latency differences do not establish causality. “Unexpected” means outside Gold's required files, not proven semantically irrelevant.

## Human Review Results

The EXP-02 review covers **10 targeted cases**, not all 24. Its labels are authoritative for those cases:

| Dimension | Counts |
| --- | --- |
| Answer correctness | 7 CORRECT; 2 PARTIAL; 1 INCORRECT |
| Grounding | 7 GROUNDED; 2 PARTIALLY_GROUNDED; 1 UNSUPPORTED |
| Citation quality | 6 COMPLETE; 2 INCORRECT; 1 MISSING; 1 N/A |
| Primary failure cause | 6 NONE; 2 GENERATION; 1 ROUTING; 1 DISTRACTOR_ATTRIBUTION |

`ptcl_003` and `distractor_001` show the intended reduction in prompt distractors, with human-reviewed correct answers and complete citations. `corechain_002` gains a second expected CoreChain chunk and the reviewed answer includes gRPC over HTTP/2. `crossdoc_001` retains both expected files and is reviewed correct, although its prompt did not change between EXP-01 and EXP-02. `resume_001` and `resume_002` are reviewed correct with complete citations, but their prompt chunks did not change; their citation improvements cannot be credited to the gate alone.

`crossdoc_002` remains PARTIAL with missing citations despite both expected files in prompt; the reviewer attributes this to GENERATION. `corechain_003` now gives the correct negative budget conclusion, but Expense still enters and is the only cited file; the reviewer marks DISTRACTOR_ATTRIBUTION and incorrect citations. `routing_002` remains PARTIAL because it still misses `FILE_INVENTORY`, an unchanged routing problem. `corechain_004` is a new INCORRECT, UNSUPPORTED production-deployment claim; the reviewer marks GENERATION. Its prompt loses a DBMS chunk but retains the same CoreChain-related sources, so the artifacts establish a changed prompt and answer, not whether the gate caused the unsupported inference.

## Success Criteria

| Original criterion | Finding | Status |
| --- | --- | --- |
| Prompt expected-file recall ≥ 95.45% | 95.45%. | PASS |
| Multi-document all-expected coverage ≥ 6/7 | 6/7. | PASS |
| `crossdoc_001` and `crossdoc_002` retain both expected files | Both do in their saved EXP-02 prompts. | PASS |
| Macro expected-source precision > 38.81% | 46.43%. | PASS |
| Mean unexpected prompt sources < 2.24 | 1.57. | PASS |
| Strong precision target ≥ baseline 44.05% | 46.43%. | PASS |
| Citation expected-source recall ≥ 77.27% | 86.36%; the improvement is observational. | PASS |
| Mean lexical must-include coverage ≥ 88.82% | 88.82%; unchanged from EXP-01. | PASS |
| No increase in unsupported attribution under targeted human review | Shared reviewed EXP-01 failures `ptcl_003` and `corechain_003` improve, but EXP-02 has a new unsupported `corechain_004` answer. The two targeted review sets are not identical, and causality cannot be established from one run. | INCONCLUSIVE |
| No new execution errors or false pipeline abstentions | Both counts remain zero. | PASS |
| Route accuracy and upstream retrieval/RRF/rerank/evidence unchanged | Route accuracy remains 83.33%; upstream candidate IDs and order match EXP-01. | PASS |

The offline replay retained all five observed Gold-expected promotion events at `T = 0.90`; the real prompt traces reproduce its aggregate prediction. In particular, both cross-document target prompts retain their required files, and `ptcl_003` retains PTCL while weak Untitled/Data Engineer chunks no longer enter its prompt.

## What EXP-02 Improved

The gate retained EXP-01's expected-file recall and multi-document coverage while restoring macro expected-source precision above the untouched baseline. Mean unexpected prompt sources fell by 0.67 per applicable case. In `distractor_001`, Expense and Cloud leave the prompt; in `ptcl_003`, weak distinct sources stop crowding the prompt while PTCL remains. `corechain_002` gains additional CoreChain depth. These are direct prompt-composition effects supported by the saved traces.

## What EXP-02 Did Not Solve

The gate changes order, not membership: `corechain_003` still receives the Expense Report and cites it. `crossdoc_002` still omits a supported DriveMind point and provides no citations. `routing_002` still misses the inventory route. `corechain_004` makes an unsupported inference despite expected-source prompt coverage. These outcomes remain important, but none demonstrates that the score gate failed its source-coverage and noise objective.

## Remaining Risks / Limitations

The `corechain_004` regression prevents a blanket claim of no answer-quality regression. Its prompt changed, and the saved artifacts cannot isolate prompt composition from generation variability as the cause. The 0.90 threshold was selected from a small controlled corpus; broader generalization is unproven. Gold expected files are required sources, not an exhaustive relevance judgment. The targeted human review does not estimate quality across all 24 cases. P95 latency rose in the single EXP-02 run, without evidence of a causal latency cost.

## Final Rationale

**KEEP** because the controlled variable met every measurable prompt objective: EXP-01's recall and multi-document gains were retained, prompt noise fell, and expected-source precision exceeded the untouched baseline. Upstream candidate order stayed fixed, so the observed prompt changes are localized to selection. Human review confirms several desired outcomes while identifying a new unsupported generation claim and persistent attribution, routing, and citation problems. Those failures warrant separate investigation; the evidence does not justify reverting or further changing the gate before accepting it. Commit `5350222a1445673030fde5901d36fd5b768aa535` remains.

## Next Evaluation Target

Investigate **unsupported inference on negative questions despite expected-source prompt evidence**, starting with `corechain_004` and the residual distractor attribution in `corechain_003`. This names the next problem for evaluation; it does not define or implement another experiment.

# EXP-01 Decision

## Hypothesis

Stable source-diverse prompt ordering should improve multi-document expected-source inclusion without materially degrading other behavior.

## Results

EXP-01 improved the intended recall and coverage measures:

- Prompt expected-file recall increased from **88.64% to 95.45%**.
- Multi-document cases with all expected files in the prompt increased from **4/7 to 6/7**.
- `crossdoc_001` and `crossdoc_002` both regained their complete expected source sets in the prompt.
- Citation expected-source recall increased from **65.91% to 77.27%**.

The recall gain came with a measurable precision and noise regression:

- Macro prompt expected-source precision decreased from **44.05% to 38.81%**.
- Mean unexpected prompt sources increased from **1.43 to 2.24**.
- `ptcl_003` expected-source precision decreased from **50% to 25%**.
- `distractor_001` expected-source precision decreased from **50% to 20%**.
- Average must-include coverage decreased from **91.18% to 88.82%**.

Route accuracy remained **83.33%**. Upstream retrieval, RRF, reranking, and evidence grading were unchanged, confirming that the experiment remained isolated to prompt-context ordering.

## Human Review

The targeted review covered 10 materially changed cases: **6 correct, 2 partial, and 2 incorrect**.

- `crossdoc_001` clearly improved: both expected sources reached generation and were correctly used and cited.
- `crossdoc_002` received both expected sources, but generation omitted DriveMind's read-only Google Drive mechanism and emitted no citations.
- `corechain_003` became a stronger false attribution by directly assigning unrelated Expense Report budget figures to CoreChain.
- `ptcl_003` remained unsupported and asserted a different ungrounded salary figure.
- `distractor_001` remained answer-correct but gained an unnecessary Expense Report citation.

## Decision

**PARTIALLY SUCCESSFUL — DO NOT KEEP AS FINAL BEHAVIOR.**

- Source inclusion improved: **yes**.
- Multi-document coverage improved: **yes**.
- Prompt precision/noise remained acceptable: **no**.
- Distractor risk materially increased: **yes**.
- Upstream retrieval behavior remained isolated: **yes**.
- Final answer quality improved uniformly: **no; results were mixed**.

The core source-diversity hypothesis is validated, but unconditional distinct-source promotion is too aggressive. EXP-01 remains committed as an experimental checkpoint and evidence source; its history should not be reverted. Its selector should not be treated as final production behavior.

## Why Not Keep EXP-01 As-Is

The selector promotes the first chunk from every distinct source without considering how far its evidence score falls below a stronger repeated-source chunk. This repaired missing-source failures, but it also increased unrelated prompt sources and exposed generation to more distractor evidence. The observed unsupported-attribution cases show that higher source recall alone is insufficient.

## Next Experiment Boundary

EXP-02 should test **gated source diversity**: preserve EXP-01's recall gains while preventing a weak distinct-source candidate from automatically outranking a substantially stronger repeated-source chunk.

No gating threshold is selected yet. The next step is read-only score-distribution analysis around the actual promotions:

- Desired promotions: `crossdoc_001`, `crossdoc_002`
- Harmful promotions: `corechain_003`, `ptcl_003`, `distractor_001`

The analysis should determine whether candidate, fusion, or rerank score gaps meaningfully separate desired from harmful promotions. Routing, retrieval, RRF, reranking, evidence grading, generation, citation normalization, corpus state, and Gold remain frozen until that evidence is reviewed.

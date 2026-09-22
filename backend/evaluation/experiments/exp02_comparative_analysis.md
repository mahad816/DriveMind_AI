# EXP-02 Comparative Analysis

## Benchmark Identity

This analysis reads the three saved Gold v1 artifacts and the locked Gold dataset. It does not rerun retrieval or generation. SHA-256 values were checked before analysis:

| Run | Git SHA | Artifact SHA-256 |
| --- | --- | --- |
| Baseline | `f93736aa3c901ee0ca4589f6fd3f4473612433ba` | `f22435ec26a561a248b782bba5f8ded2d3b6ae2bb759db30712e795af53d61db` |
| EXP-01 | `42b59a1b48f0c6d027de8df064a44f458fed3e7e` | `f32e5d85eab34366a963609411875cba3b94ba025f3a9e395da3bc700c5d115e` |
| EXP-02 | `5350222a1445673030fde5901d36fd5b768aa535` | `e7b9af8c98c2f8e1b36620a4076c2c0f131b4075f497fa5e3b16b9bf4b667c0d` |

Gold SHA-256: `9f223c2143e452cea5d85d20d25d0ea6e081bfb92b09d8d13855f0630526e8a0`. Corpus fingerprint in all runs: `f8c8c6de3e563c37d84f8b89c6588a0a4a4cd4465a50543fe41d3cf2ea90efc8`. All runs contain the same 24 Gold IDs, the same evaluation user, the same corpus manifest, and identical recorded configuration. Each run is marked completed with 24 completed cases and zero case errors.

## Metric Verification

Metrics below were recomputed from case records. Prompt source lists were rebuilt from `trace.prompt_chunks`; citations from `trace.final_citations`; routes, outcomes, rewrites, and latency from the trace; required-phrase coverage from case-level match flags. Means exclude non-applicable values. Prompt expected-file recall and citation expected-source recall each cover 22 cases with expected files; expected-source precision and unexpected-source count cover 21 with nonempty prompts; must-include coverage covers 17; multi-document coverage covers seven. The one expected-file case without prompt chunks is `resume_003`.

Every recomputed EXP-02 value agrees with its stored summary. The baseline and EXP-01 summaries predate the prompt precision fields, so those two values were calculated directly from their prompt chunks.

## Baseline vs EXP-01 vs EXP-02

| Metric | Baseline | EXP-01 | EXP-02 |
| --- | ---: | ---: | ---: |
| Route accuracy | 83.33% | 83.33% | 83.33% |
| Prompt expected-file recall | 88.64% | 95.45% | 95.45% |
| Multi-document cases with all expected files in prompt | 4/7 | 6/7 | 6/7 |
| Macro prompt expected-source precision | 44.05% | 38.81% | 46.43% |
| Mean unexpected prompt sources | 1.43 | 2.24 | 1.57 |
| Citation expected-source recall | 65.91% | 77.27% | 86.36% |
| Cases citing all expected files | 14/22 | 16/22 | 19/22 |
| Mean lexical must-include coverage | 91.18% | 88.82% | 88.82% |
| Cases satisfying every lexical must-include phrase | 14/17 | 13/17 | 13/17 |
| Total rewrites | 0 | 0 | 0 |
| Pipeline abstentions | 0 | 0 | 0 |
| False pipeline abstentions | 0 | 0 | 0 |
| Median total latency | 3.90 s | 3.24 s | 3.57 s |
| P95 total latency | 7.48 s | 6.22 s | 9.32 s |
| Completed / execution errors | 24 / 0 | 24 / 0 | 24 / 0 |

Latency varies between single runs; this table does not establish a causal latency effect. Expected-source precision measures agreement with required Gold filenames, not semantic relevance of every other source. Must-include is a lexical diagnostic, not a human correctness label.

## Success-Criteria Verification

| Criterion | EXP-02 observation | Result |
| --- | --- | --- |
| Prompt expected-file recall ≥ 95.45% | 95.45% | Pass |
| Multi-document all-expected coverage ≥ 6/7 | 6/7 | Pass |
| `crossdoc_001` and `crossdoc_002` retain both expected files | Both do | Pass |
| Macro expected-source precision > 38.81% | 46.43% | Pass |
| Mean unexpected sources < 2.24 | 1.57 | Pass |
| Strong precision target ≥ baseline 44.05% | 46.43% | Pass |
| Citation expected-source recall ≥ 77.27% | 86.36% | Pass |
| Lexical must-include coverage ≥ 88.82% | 88.82% | Pass |
| No execution errors or new false pipeline abstentions | 0 / 0 | Pass |

The four prompt metrics exactly match the EXP-02 offline prediction: 95.45% recall, 6/7 multi-document coverage, 46.43% precision, and 1.57 unexpected sources. The deterministic prompt replay therefore reproduced in the real run. Upstream raw retrieval, RRF, rerank, and evidence case metrics match EXP-01. Human answer quality and unsupported attribution still require review.

## Target-Case Findings

Prompt sources below retain chunk order; `#n` is the chunk index. “Unexpected” means outside Gold `expected_files`, not proven irrelevant.

| Case | EXP-01 → EXP-02 prompt chunks | EXP-02 result and open question |
| --- | --- | --- |
| `crossdoc_001` | Both: Guide #2 → DriveMind #0 → CoreChain #0 | Both expected files remain; must-include 100%; all expected sources cited, plus Guide. Answer wording changed without a prompt change. |
| `crossdoc_002` | Both: Guide #1 → CoreChain #0 → DriveMind #1 → Improvements #1 | Both expected files remain; must-include 60%; no citations in either run. Prompt selection is no longer the immediate loss point. |
| `ptcl_003` | Internship Report #0 → PTCL #0 → Untitled #0 → Data Engineer #0 becomes Internship Report #0 → PTCL #0 → Internship Report #1 | PTCL remains; unexpected source count falls from 3 to 1. EXP-02 answers that payment is unspecified and cites PTCL and Internship Report. The compensation claim needs human verification. |
| `corechain_003` | P2 #0 → CoreChain #0 → P4 #0 → Expense #1 becomes P2 #0 → CoreChain #0 → P4 #0 → CoreChain #1 → Expense #1 | The second CoreChain chunk enters, but Expense still enters. EXP-02 says the CoreChain budget is unspecified while discussing Expense amounts and citing Expense only; source attribution remains a review risk. |
| `distractor_001` | DriveMind #1 → Guide #0 → Improvements #1 → Expense #1 → Cloud #1 becomes DriveMind #1 → Guide #0 → DriveMind #0 → Guide #4 | Expense and Cloud disappear. EXP-02 gives a negative hosting-cost answer and cites only DriveMind; check its wording and attribution in human review. |

## Materially Changed Cases

Comparing EXP-01 with EXP-02 by chunk identity and order:

- Prompt composition changed in 12 cases: `corechain_001`, `ptcl_001`, `meeting_001`, `ptcl_002`, `cloud_001`, `ml_001`, `corechain_002`, `expense_001`, `corechain_003`, `corechain_004`, `ptcl_003`, `distractor_001`.
- Distinct cited-file sets changed in eight: `routing_002`, `drivemind_001`, `corechain_002`, `resume_001`, `resume_002`, `corechain_004`, `ptcl_003`, `distractor_001`. Citation details also changed for `cloud_001`, but its distinct cited-file set did not.
- No case changed lexical must-include coverage, route, outcome, or rewrite count.
- Final answer text changed in all 24 cases. Eight had text changes without a prompt or cited-file-set change: `routing_001`, `routing_003`, `resume_003`, `resume_004`, `crossdoc_001`, `crossdoc_002`, `resume_005`, `semantic_001`. Text change alone is not evidence of improvement or regression.

## Remaining Risks

The strongest new risk is `corechain_004`: EXP-01 said no hospital was identified, while EXP-02 names GIKI in response to a hospital deployment question. That needs human assessment. `corechain_003` still includes and cites the Expense Report despite the added CoreChain chunk. `crossdoc_002` still omits citations and covers only 60% of lexical requirements. `ptcl_003` now gives a negative compensation answer, but another internship report remains in context and citations. The increase in P95 latency is observational only.

The saved trace contains prompt chunk metadata and hashes, not full prompt chunk text. Human review should use the complete saved answers and Gold expectations in the companion packet. No final keep/reject decision is made here.

## Human-Review Set

The companion packet contains 10 cases:

| Case | Reason to review |
| --- | --- |
| `crossdoc_001` | EXP-02 design target; stable prompt but changed answer wording and extra Guide citation. |
| `crossdoc_002` | EXP-02 design target; correct source coverage but persistent 60% lexical coverage and no citations. |
| `corechain_003` | Extra CoreChain chunk enters yet Expense attribution remains. |
| `ptcl_003` | Major prompt and answer change on unsupported compensation question. |
| `distractor_001` | Expense/Cloud removed; check negative answer and citation discipline. |
| `corechain_002` | Extra CoreChain chunk enters and citation set changes; verify communication detail and source use. |
| `corechain_004` | New apparent institution-as-hospital answer after prompt change. |
| `routing_002` | Inventory-route error persists while final citations disappear. |
| `resume_001` | Both resume citations now appear; check version attribution. |
| `resume_002` | Both resume citations now appear; check CGPA attribution. |

Other changed prompts did not alter expected-source coverage or the distinct citation set, and their case-level lexical checks were stable. `drivemind_001` swaps one supplemental citation for another while retaining the expected citation and 100% lexical coverage; this is a lower-priority citation detail. These exclusions are review scope choices, not human quality judgments.

# EXP-02 — Gated Source Diversity

## Problem

EXP-01 improved expected-source inclusion, but its unconditional promotion of every distinct source increased prompt noise:

| Metric | Baseline | EXP-01 |
|---|---:|---:|
| Prompt expected-file recall | 88.64% | 95.45% |
| Multi-document cases with all expected files | 4/7 | 6/7 |
| Macro expected-source precision | 44.05% | 38.81% |
| Mean unexpected prompt sources | 1.43 | 2.24 |

EXP-02 should preserve the source-diversity recall gains while preventing weak distinct sources from automatically leapfrogging stronger repeated-source evidence.

## Hypothesis

A distinct source should only be promoted ahead of an earlier repeated-source chunk when its final rerank score is sufficiently competitive with the repeated chunk it would displace. This should preserve useful cross-document source diversity while reducing weak distractor promotion.

## Evidence From EXP-01

Offline replay of all 24 saved EXP-01 cases reconstructed 56 promotion events:

- 5 expected-source promotions
- 51 unexpected-source promotions

Here, *unexpected* means absent from Gold `expected_files`; it does not prove that a source is semantically irrelevant.

Expected-source promotion ratios had this distribution:

- minimum: 0.9045
- median: 0.9651
- maximum: 0.9811

The threshold replay produced:

| Threshold | Prompt recall | Multi-doc all expected | Macro expected-source precision | Mean unexpected sources |
|---:|---:|---:|---:|---:|
| 0.80 | 95.45% | 6/7 | 45.24% | 1.67 |
| 0.85 | 95.45% | 6/7 | 45.24% | 1.67 |
| 0.88 | 95.45% | 6/7 | 46.43% | 1.57 |
| 0.90 | 95.45% | 6/7 | 46.43% | 1.57 |
| 0.92 | 95.45% | 6/7 | 47.22% | 1.52 |
| 0.95 | 95.45% | 6/7 | 47.62% | 1.48 |

Thresholds 0.92 and 0.95 preserve aggregate prompt recall only because the expected PTCL source still enters later during context packing; they block its observed diversity promotion.

## Proposed Algorithm

Apply gated source diversity after existing filename prioritization:

1. Preserve candidate input order.
2. Use `RetrievedChunk.drive_file_id` as source identity.
3. Track the first occurrence of every source.
4. Treat a first chunk from a new source as a promotion candidate when it would leapfrog an earlier repeated-source chunk.
5. Identify the earliest repeated-source chunk the candidate would displace.
6. Compute:

   ```text
   promotion_ratio = promoted.score / deferred_repeated.score
   ```

7. Promote the distinct-source chunk only when:

   ```text
   promotion_ratio >= 0.90
   ```

8. If promotion is denied:
   - do not remove the chunk;
   - leave it in its stable original relative position; and
   - still mark its source as encountered, so a later chunk from that source cannot become a substitute representative.
9. Append all non-promoted and repeated chunks in stable original relative order.
10. Return the original `RetrievedChunk` objects unchanged.

No chunk is added, removed, copied, rescored, or mutated.

## Threshold Selection

`0.90` is selected as the experimental threshold because it:

- lies in the stable 0.88–0.90 replay plateau;
- is a round, explainable policy: a promoted source must score at least 90% as highly as the repeated chunk it displaces;
- is not selected to split one specific candidate pair; and
- retains all 5 observed expected-source promotions.

The threshold remains an experimental policy, not a universal RAG constant.

## Frozen Variables

EXP-02 changes only the diversity promotion policy. The following remain frozen:

- filename prioritization;
- vector, keyword, and metadata retrieval;
- candidate limits and retrieval thresholds;
- RRF;
- weighted reranking;
- evidence grading;
- routing;
- rewrite behavior;
- generation prompts and model settings;
- citation normalization;
- maximum context budget;
- context formatting, packing, and truncation;
- the later-non-fitting-chunk `break` behavior;
- Gold v1; and
- the controlled corpus.

EXP-02 must not add an absolute score threshold, component-score requirement, per-source cap, candidate removal, semantic filter, new reranker, or LLM judge.

## Success Criteria

Hard prompt requirements:

- prompt expected-file recall >= 95.45%;
- multi-document all-expected coverage >= 6/7;
- `crossdoc_001` retains both expected files; and
- `crossdoc_002` retains both expected files.

Precision and noise requirements:

- macro expected-source precision > 38.81%; and
- mean unexpected prompt sources < 2.24.

Strong target:

- macro expected-source precision >= the 44.05% baseline.

Downstream requirements:

- citation expected-source recall >= 77.27%;
- must-include coverage >= 88.82%;
- no increase in unsupported attribution under targeted human review;
- no new execution errors; and
- no new false abstentions.

Upstream requirements:

- route accuracy unchanged; and
- raw retrieval, RRF, rerank, and evidence behavior unchanged.

## Regression Watch

- `crossdoc_001`: must retain both DriveMind and CoreChain.
- `crossdoc_002`: must retain both DriveMind and CoreChain.
- `ptcl_003`: the expected PTCL promotion ratio is approximately 0.9045 and must be an explicit boundary test. Weak Untitled and Data Engineer chunks must not leapfrog the repeated Internship Report chunk.
- `corechain_003`: the second CoreChain chunk should return ahead of Expense. Expense may still fit later because gating does not remove candidates.
- `distractor_001`: Expense and Cloud should no longer be prematurely promoted; the benchmark must still check whether they enter the packed prompt later.

## Known Limitations

- Gold `expected_files` identifies required sources, not every semantically relevant source.
- Only five observed promotions are Gold-expected.
- Some unexpected but related sources have very high score ratios.
- Gating controls ordering, not candidate membership.
- Offline prompt replay cannot predict generation or citation nondeterminism.
- The 0.90 threshold may not generalize beyond this controlled experiment.

## Implementation Boundary

The expected production change is narrowly confined to:

- `backend/app/llm/prompts.py`

Focused tests should primarily extend:

- `backend/tests/llm/test_prompts.py`

Implementation must begin with a RED test phase and avoid unrelated prompt refactoring.

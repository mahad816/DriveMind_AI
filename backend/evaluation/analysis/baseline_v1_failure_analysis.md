# DriveMind Gold v1 Baseline Failure Analysis

## 1. Locked Evaluation Identity

This report analyzes the first untouched DriveMind Gold v1 run. It does not contain results from a rerun.

| Item | Locked value |
|---|---|
| Baseline artifact | `backend/evaluation/results/drivemind_gold_v1__20260921T143023Z__f93736aa.json` |
| Artifact SHA-256 | `f22435ec26a561a248b782bba5f8ded2d3b6ae2bb759db30712e795af53d61db` |
| Gold dataset | `backend/evaluation/datasets/gold_v1.json` |
| Dataset SHA-256 | `9f223c2143e452cea5d85d20d25d0ea6e081bfb92b09d8d13855f0630526e8a0` |
| Baseline system Git SHA | `f93736aa3c901ee0ca4589f6fd3f4473612433ba` |
| Corpus fingerprint | `f8c8c6de3e563c37d84f8b89c6588a0a4a4cd4465a50543fe41d3cf2ea90efc8` |
| Human review | `backend/evaluation/reviews/baseline_v1_human_review.json` |
| Human review SHA-256 | `1f291e76ec9622846b415bf2f6d314c9bc04ac0859de122403f3b405946721b3` |
| Human review commit | `f08619e` |

The artifact contains 24 unique cases and reports a completed run. The targeted human review covers 14 suspicious, failed, citation, distractor, and evaluator-edge cases. Human labels are authoritative for those 14 cases.

## 2. Baseline Summary

### 2.1 Whole-baseline results

- Cases: 24 total, 24 completed, 0 execution failures.
- Routing accuracy: 20/24, or 83.33%.
- Routing mismatches:
  - `routing_001`: CHITCHAT → GROUNDED_RAG
  - `routing_002`: FILE_INVENTORY → GROUNDED_RAG
  - `routing_003`: FILE_TARGET → GROUNDED_RAG
  - `resume_003`: GROUNDED_RAG → FILE_INVENTORY
- Route confusion matrix:
  - CHITCHAT → GROUNDED_RAG: 1
  - FILE_INVENTORY → GROUNDED_RAG: 1
  - FILE_TARGET → GROUNDED_RAG: 1
  - GROUNDED_RAG → FILE_INVENTORY: 1
  - GROUNDED_RAG → GROUNDED_RAG: 20

The Gold set contains 21 cases expected to use GROUNDED_RAG. One, `resume_003`, was routed away before retrieval. For the other 20, the complete expected-file set was present in raw vector retrieval, RRF, reranking, and accepted evidence.

| Stage over 21 expected-grounded cases | Any expected file | All expected files | Mean expected-file recall | First-relevant MRR | Mean expected-file RR |
|---|---:|---:|---:|---:|---:|
| Raw vector | 20/21 | 20/21 | 95.24% | 0.704 | 0.649 |
| Raw keyword | 20/21 | 20/21 | 95.24% | 0.810 | 0.738 |
| RRF | 20/21 | 20/21 | 95.24% | 0.857 | 0.786 |
| Rerank | 20/21 | 20/21 | 95.24% | 0.786 | 0.730 |
| Evidence | 20/21 | 20/21 | 95.24% | 0.786 | 0.730 |
| Prompt | 19/21 | 18/21 | 88.10% | 0.762 | 0.702 |

The missing case through the early stages is the route-bypassed `resume_003`; it is not a failed retrieval attempt. Among cases that actually reached grounded retrieval, the expected-file set was found in 20/20 cases before prompt selection.

| Stage | Hit@1 | Hit@3 | Hit@8 | Recall@1 | Recall@3 | Recall@8 | All expected @3 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Raw vector | 52.38% | 90.48% | 95.24% | 42.86% | 88.10% | 95.24% | 85.71% |
| Raw keyword | 71.43% | 95.24% | 95.24% | 57.14% | 95.24% | 95.24% | 95.24% |
| RRF | 76.19% | 95.24% | 95.24% | 61.90% | 95.24% | 95.24% | 95.24% |
| Rerank/evidence | 61.90% | 95.24% | 95.24% | 52.38% | 95.24% | 95.24% | 95.24% |
| Prompt | 61.90% | 90.48% | 90.48% | 52.38% | 88.10% | 88.10% | 85.71% |

The configured stage limits recorded by the runner were K=1, K=3, and K=8; no Hit@5 aggregate was persisted. Metadata retrieval was active for nine applicable cases and contained the full expected set in one. It acted as a supplemental retriever and was not the sole source of an observed expected-file loss.

Multi-document behavior:

- Seven Gold cases required two files.
- All expected files reached rerank/evidence in 6/7; `resume_003` never entered retrieval.
- All expected files reached the prompt in 4/7.
- `crossdoc_002` retained one of two expected files.
- `crossdoc_001` retained neither expected file.

Context, answer, and citation diagnostics:

- Runner-wide prompt expected-file recall: 88.64% across all applicable routes.
- Evidence-anchor coverage averaged 84.13%; all evidence anchors were present in 16/21 expected-grounded cases.
- `must_include` average lexical coverage: 91.18% over 17 applicable cases.
- All `must_include` strings matched in 14/17 cases.
- Two of the three lexical misses were human-confirmed evaluator false negatives: `meeting_001` and `ptcl_002`.
- Citation expected-source recall: 65.91% across 22 applicable cases.
- Every expected source was cited in 14/22 applicable cases.
- All recorded marker structures were valid; no citation-normalization defect was found.
- Five cases cited at least one unexpected file: `corechain_003`, `corechain_004`, `crossdoc_001`, `ptcl_003`, and `semantic_001`.

Agent and outcome behavior:

- Rewrite cases: 0.
- Total rewrites: 0.
- Pipeline abstentions: 0.
- False pipeline abstentions on answerable cases: 0.
- All five `should_answer=false` cases produced an `ANSWERED` outcome. Human review found three grounded negative answers and two unsupported assertions, showing why `ANSWERED` alone is not a semantic failure label.
- Runtime errors: 0.

Latency:

- Median total latency: 3,902.9 ms.
- p95 total latency: 7,480.4 ms.
- Slowest case: `routing_003` at 16,185.1 ms, dominated by 15,275.5 ms of generation.
- Other notable totals were `resume_004` at 7,480.4 ms, `routing_001` at 7,247.7 ms, `corechain_004` at 7,074.0 ms, and `crossdoc_002` at 6,050.6 ms.
- `routing_001` spent 5,085.6 ms in retrieval that should not have occurred on the intended CHITCHAT route.

## 3. Human Review Summary

### 3.1 Targeted 14-case counts

These counts describe only the manually reviewed subset, not all 24 cases.

| Dimension | Counts |
|---|---|
| Answer quality | CORRECT 9; PARTIAL 1; INCORRECT 4 |
| Grounding | GROUNDED 7; PARTIALLY_GROUNDED 4; UNSUPPORTED 2; NOT_APPLICABLE 1 |
| Citation quality | COMPLETE 2; PARTIAL 3; MISSING 4; INCORRECT 3; NOT_APPLICABLE 2 |
| Primary cause | ROUTING 4; PROMPT_SELECTION 2; DISTRACTOR_ATTRIBUTION 2; CITATION 4; EVALUATOR_FALSE_NEGATIVE 2 |

### 3.2 Reviewed cases

| Case | Question/category | Expected route | Observed route | Answer quality | Grounding | Citation quality | Primary cause | Pipeline stage | Short diagnosis |
|---|---|---|---|---|---|---|---|---|---|
| routing_001 | Social greeting | CHITCHAT | GROUNDED_RAG | CORRECT | NOT_APPLICABLE | NOT_APPLICABLE | ROUTING | ROUTING | Appropriate reply, but grounded retrieval ran unnecessarily. |
| routing_002 | Knowledge-base file inventory | FILE_INVENTORY | GROUNDED_RAG | INCORRECT | PARTIALLY_GROUNDED | NOT_APPLICABLE | ROUTING | ROUTING | Retrieved prose was used instead of the authoritative inventory path. |
| routing_003 | Named CoreChain file | FILE_TARGET | GROUNDED_RAG | CORRECT | GROUNDED | MISSING | ROUTING | ROUTING | Expected file was retrieved, but the specialized path was bypassed and no citations were emitted. |
| resume_003 | Compare graduation dates | GROUNDED_RAG | FILE_INVENTORY | PARTIAL | PARTIALLY_GROUNDED | MISSING | ROUTING | ROUTING | Inventory routing supplied January 2027 but missed December 2026. |
| crossdoc_001 | CoreChain data handling vs DriveMind storage | GROUNDED_RAG | GROUNDED_RAG | INCORRECT | PARTIALLY_GROUNDED | INCORRECT | PROMPT_SELECTION | PROMPT_SELECTION | Both Gold sources were retrieved but excluded from the prompt by guide chunks. |
| crossdoc_002 | Security mechanisms across projects | GROUNDED_RAG | GROUNDED_RAG | CORRECT | PARTIALLY_GROUNDED | MISSING | PROMPT_SELECTION | PROMPT_SELECTION | CoreChain survived prompt selection; DriveMind Gold did not; no citations were emitted. |
| corechain_003 | Unsupported CoreChain budget | GROUNDED_RAG | GROUNDED_RAG | INCORRECT | UNSUPPORTED | INCORRECT | DISTRACTOR_ATTRIBUTION | GENERATION | Expense-report figures were attached to a CoreChain question. |
| corechain_004 | Unsupported hospital deployment | GROUNDED_RAG | GROUNDED_RAG | CORRECT | GROUNDED | PARTIAL | CITATION | CITATION_ATTRIBUTION | Grounded negative answer included an unnecessary related PDF citation. |
| ptcl_003 | Unsupported PTCL compensation | GROUNDED_RAG | GROUNDED_RAG | INCORRECT | UNSUPPORTED | INCORRECT | DISTRACTOR_ATTRIBUTION | GENERATION | Payment from another internship report was attributed to PTCL. |
| resume_001 | Resume version containing DriveMind | GROUNDED_RAG | GROUNDED_RAG | CORRECT | GROUNDED | PARTIAL | CITATION | CITATION_ATTRIBUTION | Both resumes informed the answer, but only v1 was cited. |
| resume_004 | Resume-version synthesis | GROUNDED_RAG | GROUNDED_RAG | CORRECT | GROUNDED | MISSING | CITATION | CITATION_ATTRIBUTION | Both files and all required facts were present, but no citations were emitted. |
| semantic_001 | INDEXED-only evidence rule | GROUNDED_RAG | GROUNDED_RAG | CORRECT | GROUNDED | PARTIAL | CITATION | CITATION_ATTRIBUTION | Expected source was cited with unnecessary implementation-guide citations. |
| meeting_001 | Meeting date/time | GROUNDED_RAG | GROUNDED_RAG | CORRECT | GROUNDED | COMPLETE | EVALUATOR_FALSE_NEGATIVE | EVALUATOR | `28 July` was not normalized as equivalent to `July 28`. |
| ptcl_002 | Local review-analysis model | GROUNDED_RAG | GROUNDED_RAG | CORRECT | GROUNDED | COMPLETE | EVALUATOR_FALSE_NEGATIVE | `8 billion` was not normalized as equivalent to `8B`. |

## 4. Pipeline Stage Diagnosis

### 4.1 ROUTING

- Failure observed: yes.
- Primary cases: `routing_001`, `routing_002`, `routing_003`, `resume_003`.
- Evidence: four route mismatches, covering all three specialized routes plus one grounded query diverted into inventory.
- Primary or symptom: primary. The route choice happened before retrieval and determined which production path was available.
- Answer impact: one incorrect answer, one partial answer, one correct answer with needless retrieval, and one correct content answer with missing citations.
- Timing: investigate now. Routing caused the largest number of reviewed primary failures, but the four cases arise from distinct rule boundaries and should not be changed as one undifferentiated experiment.

### 4.2 RETRIEVAL

- Failure observed: no primary expected-file retrieval failure in the executed grounded cases.
- Cases: all 20 intended-grounded cases that reached retrieval contained the complete expected-file set in raw vector retrieval. Keyword retrieval also contained the complete set in those 20 cases.
- Evidence: 20/20 full expected-file presence before fusion; the apparent 20/21 rate is entirely `resume_003`, which routing prevented from reaching retrieval.
- Primary or symptom: neither for the reviewed failures.
- Answer impact: low in this baseline relative to downstream stages. Retrieval did admit distractors, but it did not fail to find the Gold files.
- Timing: do not tune now. Preserve configuration while downstream losses are isolated.

### 4.3 FUSION_RRF

- Failure observed: no expected-file set was lost during RRF.
- Cases: none with a primary RRF failure.
- Evidence: every expected file found by raw retrieval survived into RRF; RRF improved first-relevant MRR from vector's 0.704 to 0.857 across expected-grounded cases.
- Primary or symptom: neither.
- Answer impact: no observed answer failure originates here.
- Timing: do not change now.

### 4.4 RERANKING

- Failure observed: no set-level loss of expected files.
- Cases: none with a primary reranking failure.
- Evidence: the complete expected-file set remained in 20/20 executed grounded cases. Ordering MRR declined from 0.857 at RRF to 0.786 after reranking, but required files remained available.
- Primary or symptom: possible ordering contribution to prompt-selection failures, but not the earliest set-loss stage.
- Answer impact: indirect in `crossdoc_001` and `crossdoc_002` because repeated guide chunks ranked ahead of Gold chunks.
- Timing: investigate later, after testing prompt selection independently.

### 4.5 EVIDENCE_GRADING

- Failure observed: no expected file was removed, but weak or distractor-heavy evidence was always accepted.
- Cases with secondary concern: `routing_001`, `crossdoc_001`, `crossdoc_002`, `corechain_003`, `ptcl_003`.
- Evidence: every executed retrieval attempt was graded sufficient; there were zero rewrites, including queries whose eventual prompt or answer was problematic.
- Primary or symptom: secondary in this baseline. It did not create the first expected-file loss, but it allowed generation to proceed without recognizing semantic insufficiency or attribution risk.
- Answer impact: potentially material for unsupported-answer and rewrite behavior.
- Timing: investigate later, after routing and prompt selection, so evidence grading is not tuned against failures caused earlier in the pipeline.

### 4.6 PROMPT_SELECTION

- Failure observed: yes.
- Primary cases: `crossdoc_001`, `crossdoc_002`.
- Evidence: both cases contained all expected files through evidence grading. `crossdoc_001` lost both at the prompt; `crossdoc_002` lost DriveMind. Multi-document all-file coverage fell from 6/7 at evidence to 4/7 at the prompt.
- Mechanism: greedy rank-prefix packing accepted multiple long chunks from `DriveMind_AI_Implementation_Guide`, stopped at the first chunk that exceeded the remaining character budget, and did not enforce file diversity or consider a smaller later chunk.
- Primary or symptom: primary.
- Answer impact: one human-rated incorrect answer and one correct but only partially grounded answer, both with deficient citations.
- Timing: change now through a controlled isolated experiment.

### 4.7 GENERATION

- Failure observed: yes, specifically source/distractor attribution rather than missing Gold retrieval.
- Primary cases: `corechain_003`, `ptcl_003`.
- Secondary case: `crossdoc_001`, whose prompt lacked the required Gold evidence.
- Evidence: the expected Gold files were present in the prompts for `corechain_003` and `ptcl_003`, yet generation selected unrelated financial or internship facts from distractor sources and attributed them to the named subject.
- Primary or symptom: primary for the two distractor-attribution cases; downstream symptom for `crossdoc_001`.
- Answer impact: high. Both primary cases were human-rated INCORRECT, UNSUPPORTED, and had INCORRECT citations.
- Timing: investigate after the first prompt-selection experiment, keeping retrieval fixed.

### 4.8 CITATION_ATTRIBUTION

- Failure observed: yes.
- Primary reviewed cases: `corechain_004`, `resume_001`, `resume_004`, `semantic_001`.
- Secondary cases: `routing_003`, `crossdoc_001`, `crossdoc_002`, `corechain_003`, `ptcl_003`.
- Evidence: expected-source recall was 65.91%; eight applicable cases did not cite every expected file, and five cited unexpected files. `resume_004` had both Gold files in context and a correct answer but emitted no markers. No citation-normalization bug was observed; normalization consistently followed emitted markers.
- Primary or symptom: both. It is primary when correct prompt evidence and answer content exist but citation markers are missing/incomplete; it is downstream when the source never reached the prompt or the model chose a distractor.
- Answer impact: mostly trust and auditability, but incorrect attribution also accompanies the two unsupported answers.
- Timing: investigate after prompt selection and distractor attribution are separated, because upstream source availability changes the citation task.

### 4.9 EVALUATOR

- Failure observed: yes.
- Primary cases: `meeting_001`, `ptcl_002`.
- Evidence: human review marked both answers CORRECT, GROUNDED, and citation COMPLETE. The lexical evaluator missed `July 28` versus `28 July` and `8B` versus `8 billion`.
- Primary or symptom: evaluator-only. Production answers were not defective in these cases.
- Answer impact: none; reported deterministic answer metrics were understated.
- Timing: correct the evaluation tooling before interpreting future lexical deltas, but do not count this as a RAG-system improvement.

## 5. Case-Level Root Causes

### `routing_001`

“Hey, how are you?” → expected CHITCHAT, observed GROUNDED_RAG → unrelated book chunks retrieved and accepted → two unrelated chunks entered the prompt → socially appropriate answer, no citations → human: CORRECT / NOT_APPLICABLE grounding → root cause: ROUTING.

### `routing_002`

Knowledge-base inventory question → expected FILE_INVENTORY, observed GROUNDED_RAG → implementation-guide chunks retrieved → three guide chunks filled the prompt → generated a four-item prose-derived list, no citations → human: INCORRECT / PARTIALLY_GROUNDED → root cause: ROUTING.

### `routing_003`

Named `CoreChain_Project.txt` question → expected FILE_TARGET, observed GROUNDED_RAG → expected file found by vector retrieval and survived RRF/rerank/evidence → prompt contained the expected file at position 3 → detailed answer emitted no citation markers → human: CORRECT / GROUNDED / citation MISSING → root cause: ROUTING, with downstream citation omission.

### `resume_003`

Compare graduation dates → expected GROUNDED_RAG, observed FILE_INVENTORY → no grounded retrieval attempt → no prompt chunks → January 2027 reported, December 2026 missed, no citations → human: PARTIAL / PARTIALLY_GROUNDED → root cause: ROUTING.

### `crossdoc_001`

CoreChain data handling plus DriveMind storage → GROUNDED_RAG → both Gold files found in raw vector/keyword, RRF, rerank, and evidence → three long implementation-guide chunks consumed the prompt budget; both Gold files were omitted → generation described CoreChain using RAG and cited only the guide → human: INCORRECT / PARTIALLY_GROUNDED / citation INCORRECT → root cause: PROMPT_SELECTION.

### `crossdoc_002`

Security mechanisms across CoreChain and DriveMind → GROUNDED_RAG → both Gold files survived through evidence → prompt retained CoreChain but displaced DriveMind with implementation-guide chunks → broadly correct answer, no markers → human: CORRECT / PARTIALLY_GROUNDED / citation MISSING → root cause: PROMPT_SELECTION.

### `corechain_003`

Unsupported CoreChain budget → GROUNDED_RAG → CoreChain and Expense Report evidence retrieved and accepted → both entered the prompt → answer acknowledged no specified CoreChain budget but then attached Expense Report figures to the question and cited only that report → human: INCORRECT / UNSUPPORTED / citation INCORRECT → root cause: DISTRACTOR_ATTRIBUTION at generation.

### `corechain_004`

Unsupported hospital deployment → GROUNDED_RAG → expected CoreChain evidence survived to prompt alongside related PDFs → grounded negative answer → expected source cited plus unnecessary `P2_Corechain.pdf` → human: CORRECT / GROUNDED / citation PARTIAL → root cause: CITATION.

### `ptcl_003`

Unsupported PTCL compensation → GROUNDED_RAG → PTCL Gold and another internship report retrieved and accepted → both entered prompt, with the other report ranked first → answer attributed PKR 25,000 to PTCL and cited the other report → human: INCORRECT / UNSUPPORTED / citation INCORRECT → root cause: DISTRACTOR_ATTRIBUTION at generation.

### `resume_001`

Resume version containing DriveMind → GROUNDED_RAG → both resume files survived every stage and entered prompt → answer used both versions → only Resume v1 cited → human: CORRECT / GROUNDED / citation PARTIAL → root cause: CITATION.

### `resume_004`

Resume-version synthesis → GROUNDED_RAG → both resumes survived every stage and entered prompt → all required facts appeared in the answer → no markers or citations → human: CORRECT / GROUNDED / citation MISSING → root cause: CITATION.

### `semantic_001`

INDEXED-only evidence rule → GROUNDED_RAG → expected DriveMind file survived every stage and entered prompt with guide chunks → expected answer content produced → DriveMind cited along with two unnecessary guide citations → human: CORRECT / GROUNDED / citation PARTIAL → root cause: CITATION.

### `meeting_001`

Follow-up meeting date/time → GROUNDED_RAG → expected file survived every stage and was cited → answer said `28 July 2026` and `11:00 AM` → lexical metric matched time but not Gold's `July 28` ordering → human: CORRECT / GROUNDED / citation COMPLETE → root cause: EVALUATOR_FALSE_NEGATIVE.

### `ptcl_002`

Local telecom-review model → GROUNDED_RAG → expected PTCL file survived every stage and was cited → answer said Llama 3.1, approximately 8 billion parameters, and Q4 → lexical metric matched `Llama 3.1` but not Gold's `8B` form → human: CORRECT / GROUNDED / citation COMPLETE → root cause: EVALUATOR_FALSE_NEGATIVE.

## 6. Real System Failures vs Evaluator Failures

### 6.1 Real DriveMind system failures

The human review identified twelve cases whose primary cause is within DriveMind rather than the evaluator:

- Routing: `routing_001`, `routing_002`, `routing_003`, `resume_003`.
- Prompt selection: `crossdoc_001`, `crossdoc_002`.
- Distractor attribution: `corechain_003`, `ptcl_003`.
- Citation attribution: `corechain_004`, `resume_001`, `resume_004`, `semantic_001`.

These failures change the path taken, the evidence available to generation, the factual attribution of the answer, or the traceability of claims. They are production-system behaviors.

### 6.2 Evaluation-tool failures

Two cases were evaluator false negatives:

- `meeting_001`: `July 28` versus `28 July`.
- `ptcl_002`: `8B` versus `8 billion`.

The saved answers were human-rated correct, grounded, and completely cited. Fixing these equivalence checks would improve metric fidelity but would not improve DriveMind's RAG behavior. Evaluator corrections must therefore be reported separately from system experiments and must not be presented as product-quality gains.

## 7. Is Retrieval the Bottleneck?

**No. Retrieval is not the current main bottleneck in this baseline.**

Evidence:

1. Every one of the 20 intended-grounded cases that actually entered retrieval contained its complete expected-file set in raw vector results.
2. The complete expected-file set survived RRF, reranking, and evidence grading in all 20.
3. The only expected-grounded case absent from those stages, `resume_003`, was diverted by routing before retrieval.
4. The first actual set losses occurred at prompt selection: `crossdoc_001` lost both expected files and `crossdoc_002` lost one.
5. Several final failures occurred despite correct retrieval and prompt availability:
   - `corechain_003` and `ptcl_003` selected facts from distractors.
   - `resume_001` and `resume_004` had the necessary files but incomplete or missing citations.
   - `meeting_001` and `ptcl_002` were correct answers mismeasured by lexical checks.

Retrieval quality is not perfect: RRF-to-rerank ordering MRR declined, and distractor documents often ranked highly. However, changing retrieval now would target a stage that did not lose the required sources and would confound the clearer downstream failures. Retrieval configuration should remain frozen while routing, prompt selection, attribution, and evaluation fidelity are isolated.

## 8. Improvement Priorities

### Priority 1: Routing

- Why it matters: four of 24 cases took the wrong production path, the largest primary-cause group in the review.
- Cases: `routing_001`, `routing_002`, `routing_003`, `resume_003`.
- Failure type: needless retrieval, non-authoritative inventory generation, specialized file-target bypass, and loss of grounded comparison evidence.
- Risk: high cross-route risk because rule precedence changes can move unrelated questions among CHITCHAT, FILE_INVENTORY, FILE_TARGET, and GROUNDED_RAG.
- Measurement: route accuracy/confusion matrix, per-case route labels, specialized-route diagnostics, answer quality, and no regression on the 20 currently correct routes.
- Experiment note: the four failures arise from different rule boundaries, so they should not be bundled into one broad router rewrite.

### Priority 2: Prompt/context selection

- Why it matters: it is the first stage that discarded already-retrieved Gold evidence and caused the most severe multi-document context failures.
- Cases: `crossdoc_001`, `crossdoc_002`.
- Failure type: repeated long chunks from one source monopolized the context budget; later Gold files were excluded.
- Risk: changing selection can displace high-ranked evidence, alter citation numbering, or reduce single-document depth.
- Measurement: multi-document all-expected-files in prompt, prompt expected-file recall, evidence-anchor coverage, answer quality, citation source recall, context length, and single-document retention.

### Priority 3: Distractor attribution/source discipline

- Why it matters: two unsupported questions produced confident assertions from unrelated documents.
- Cases: `corechain_003`, `ptcl_003`.
- Failure type: the model transferred a value from a nearby distractor source to the named entity in the question.
- Risk: stronger source restrictions may increase cautious negative answers or suppress legitimate cross-document synthesis.
- Measurement: human grounding labels for `should_answer=false` cases, unexpected cited files, unsupported-assertion count, and preservation of valid multi-document synthesis.

### Priority 4: Citation attribution

- Why it matters: source recall was only 65.91%, with correct answers sometimes missing all citations.
- Cases: `corechain_004`, `resume_001`, `resume_004`, `semantic_001`, plus downstream citation symptoms in other cases.
- Failure type: missing markers, incomplete multi-source attribution, or unnecessary sources.
- Risk: citation-format changes may alter answer text, marker ordering, and frontend source mapping.
- Measurement: marker validity, expected cited-file recall, all-expected-files-cited rate, unexpected cited-file count, and unchanged answer quality.

### Priority 5: Evidence grading and rewrite activation

- Why it matters: every attempt was accepted as sufficient and no rewrite occurred, even with irrelevant or incomplete evidence.
- Cases: `routing_001`, `crossdoc_001`, `crossdoc_002`, `corechain_003`, `ptcl_003`.
- Failure type: weak semantic sufficiency detection and an inactive rewrite path in practice.
- Risk: stricter grading can increase latency, provider usage, false abstentions, and unnecessary rewrites.
- Measurement: rewrite rate, recovery of expected evidence, false pipeline abstentions, latency, and answer quality.
- Timing: later, after upstream route and prompt issues are controlled.

### Priority 6: Evaluator normalization

- Why it matters: two correct answers were counted as lexical misses.
- Cases: `meeting_001`, `ptcl_002`.
- Failure type: representation equivalence was not normalized.
- Risk: overly permissive normalization could collapse distinct facts.
- Measurement: these two false negatives should pass while existing incorrect numeric/date variants remain rejected.
- Scope: evaluation tooling only; report separately from system improvements.

### Priority 7: Retrieval/reranking tuning

- Why it matters: distractors ranked highly and reranking reduced ordering MRR, but required files remained present.
- Cases: ranking contributed indirectly to `crossdoc_001`, `crossdoc_002`, `corechain_003`, and `ptcl_003`.
- Failure type: ordering and distractor density, not missing-source retrieval.
- Risk: high. Tuning weights, thresholds, or top-K could regress the currently complete expected-file coverage.
- Measurement: raw/RRF/rerank recall, expected-file ranks, multi-document all-file coverage, distractor ranks, and downstream human quality.
- Timing: not now.

## 9. Recommended First Controlled Experiment

### Variable

Change only the **prompt-context selection policy**. Keep routing, retrievers, candidate limits, fusion, reranking, evidence thresholds, rewrite behavior, prompts, chat model, and corpus frozen.

The isolated experiment should compare the current greedy rank-prefix selector with one source-diversity-aware selection policy that gives distinct files an opportunity to enter the context before remaining capacity is filled by additional chunks from already represented files. This is one pipeline-stage variable; it must not alter retrieval or reranking outputs.

### Exact problem targeted

In `crossdoc_001` and `crossdoc_002`, all Gold files survived evidence grading, but repeated long implementation-guide chunks consumed the context budget. The prompt selector—not retrieval—discarded required sources.

### Why this variable should be first

- The failure boundary is directly observed and isolated.
- It caused one incorrect answer and one only-partially-grounded answer.
- It is testable without changing upstream candidate production.
- Routing has greater case count, but its four failures span several distinct classification rules; bundling them would violate the one-variable-at-a-time discipline.
- Retrieval tuning is not justified while expected files are already present before prompt selection.

### Cases expected to improve

- Primary: `crossdoc_001`, `crossdoc_002`.
- Diagnostic watch cases: all five resume multi-document cases and the single-document grounded cases, which must retain their current prompt evidence.

### Metrics expected to improve

- Multi-document all-expected-files-in-prompt rate: current 4/7.
- Prompt expected-file recall: current grounded-case mean 88.10% and runner-wide aggregate 88.64%.
- Prompt evidence-anchor coverage.
- Human grounding and answer quality for `crossdoc_001` and `crossdoc_002`.
- Expected cited-file recall may improve downstream, but it is a secondary outcome rather than proof of prompt success.

### Metrics that must not regress

- Route accuracy and confusion matrix.
- Raw vector, keyword, RRF, rerank, and evidence expected-file recall/ranks.
- Single-document expected-file presence in prompt.
- Existing 4/7 multi-document cases that already retain all required files.
- Human answer quality on currently correct cases.
- Citation marker validity.
- False pipeline abstention count.
- Total latency and prompt character limits.

### Frozen elements

- Gold v1 and its human labels.
- Controlled corpus and fingerprint.
- Model and embedding configuration.
- All retrieval top-K, candidate-K, thresholds, weights, and RRF parameters.
- Routing rules.
- Evidence grading and rewrite rules.
- Generation and citation prompts.
- Citation normalization.

### Success

The experiment succeeds if both cross-document cases retain all expected files in prompt context, multi-document prompt coverage improves above 4/7, and no currently successful prompt-retention or answer-quality case regresses.

### Regression

The experiment regresses if it removes an expected source from any currently successful case, lowers single-document or multi-document prompt recall, worsens human answer quality, breaks citation structure, exceeds the configured context budget, or materially increases latency without the targeted context gains.

## 10. Baseline Conclusions

1. The first baseline is operationally sound: all 24 cases completed without execution errors.
2. Routing is the broadest observed production problem, with four mismatches across specialized and grounded routes.
3. Retrieval is not the main current bottleneck. Expected Gold files were found and retained through evidence grading in every intended-grounded case that reached retrieval.
4. Prompt selection is the clearest isolated downstream evidence-loss mechanism. It reduced multi-document full-source coverage from 6/7 at evidence to 4/7 at prompt.
5. Source discipline is a high-impact correctness problem: two unsupported questions received unrelated factual values from distractor documents.
6. Citation behavior is unreliable even when answers and prompt evidence are correct; normalization itself was not the cause.
7. Evidence grading accepted every attempt and therefore triggered no rewrites. This warrants later investigation but is not the earliest demonstrated failure for the key cases.
8. Two apparent deterministic answer failures were evaluator errors, not DriveMind failures. Evaluation fidelity changes must remain separate from system-quality experiments.
9. The first controlled system experiment should isolate prompt-context selection while leaving retrieval and every other production variable frozen.

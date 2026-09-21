# EXP-01: Source-Diverse Prompt Context Selection

## 1. Baseline Failure

The untouched Gold v1 baseline isolated an evidence-loss boundary after evidence grading and before generation.

- Raw retrieval found all expected files for every intended-grounded case that reached retrieval.
- RRF, weighted reranking, and evidence grading retained those files.
- Prompt selection then lost expected sources in two multi-document cases:
  - `crossdoc_001`: both `CoreChain_Project.txt` and `DriveMind_Project.txt` were removed from prompt context.
  - `crossdoc_002`: `DriveMind_Project.txt` was removed; `CoreChain_Project.txt` survived.
- Multi-document all-expected-file coverage fell from 6/7 at evidence to 4/7 at prompt.

The baseline configuration used `rag_max_context_chars=12000`. The selector subtracts the exact question/context prefix before fitting formatted chunk blocks. The baseline artifact shows 23 cases with non-empty prompt context: 2–5 chunks, median 3, mean 3.52.

### `crossdoc_001` reconstruction

Question length: 120 characters. Effective context-block budget: 11,859 characters.

Evidence-stage order:

| Rank | File | Chunk | Text chars | Formatted block chars | Running total if admitted |
|---:|---|---:|---:|---:|---:|
| 1 | `DriveMind_AI_Implementation_Guide` | 2 | 3,426 | 3,487 | 3,487 |
| 2 | `DriveMind_AI_Implementation_Guide` | 1 | 3,444 | 3,505 | 6,994 |
| 3 | `DriveMind_AI_Implementation_Guide` | 0 | 3,431 | 3,492 | 10,488 |
| 4 | `DriveMind_Project.txt` | 0 | 3,402 | 3,451 | 13,941 — does not fit |
| 5 | `CoreChain_Project.txt` | 0 | 3,478 | — | not considered |
| 6 | `DriveMind_Project.txt` | 1 | 1,675 | — | not considered |
| 7 | `DriveMind_AI_Implementation_Guide` | 4 | 2,554 | — | not considered |
| 8 | `DriveMindAI improvements` | 0 | 3,031 | — | not considered |

The current selector admitted the first three chunks, all from the implementation guide. It had 1,371 characters remaining, encountered rank 4, and stopped. It did not inspect ranks 5–8. Neither Gold file reached generation.

Under the proposed source-diverse ordering, the first representatives would be guide rank 1, DriveMind rank 4, CoreChain rank 5, and improvements rank 8. Applying the unchanged budget fitter would admit the first three, use approximately 10,469 characters, and include both Gold files.

### `crossdoc_002` reconstruction

Question length: 75 characters. Effective context-block budget: 11,904 characters.

Evidence-stage order:

| Rank | File | Chunk | Text chars | Formatted block chars | Running total if admitted |
|---:|---|---:|---:|---:|---:|
| 1 | `DriveMind_AI_Implementation_Guide` | 1 | 3,444 | 3,505 | 3,505 |
| 2 | `CoreChain_Project.txt` | 0 | 3,478 | 3,527 | 7,034 |
| 3 | `DriveMind_AI_Implementation_Guide` | 2 | 3,426 | 3,487 | 10,523 |
| 4 | `DriveMind_Project.txt` | 1 | 1,675 | 1,724 | 12,249 — does not fit |
| 5 | `DriveMind_Project.txt` | 0 | 3,402 | — | not considered |
| 6 | `DriveMind_AI_Implementation_Guide` | 13 | 2,733 | — | not considered |
| 7 | `DriveMind_AI_Implementation_Guide` | 0 | 3,431 | — | not considered |
| 8 | `DriveMindAI improvements` | 1 | 2,265 | — | not considered |

The current selector admitted guide, CoreChain, and another guide chunk. It had 1,381 characters remaining, encountered rank 4, and stopped. CoreChain survived; DriveMind did not.

Under the proposed source-diverse ordering, the first representatives would be guide rank 1, CoreChain rank 2, DriveMind rank 4, and improvements rank 8. All four fit in approximately 11,079 characters, including both Gold files.

## 2. Current Production Behavior

### Production selector

- File: `backend/app/llm/prompts.py`
- Public selector: `select_prompt_chunks(question, chunks, *, max_context_chars)`
- Budget fitter: `select_context_chunks(chunks, *, max_context_chars)`
- Configuration: `Settings.rag_max_context_chars`, default and baseline value 12,000 characters.

Inputs are the normalized question, an ordered list of immutable `RetrievedChunk` values, and the configured maximum prompt character count. Each chunk carries stable `drive_file_id`, `filename`, `chunk_id`, chunk index, text, scores, MIME type, and modification time.

Current steps:

1. Return no chunks for a blank question or empty input.
2. Apply `prioritize_filename_targets()`. When the question contains a recognized explicit filename, matching chunks move to the front while their relative order and the relative order of other chunks are preserved.
3. Subtract the exact `Question:\n...\n\nContext:\n` prefix from `max_context_chars`.
4. Visit chunks in order and format each as `[N] filename (chunk I, score: S)` plus text.
5. If the first block alone is oversized, create one truncated `RetrievedChunk` and stop.
6. Otherwise append whole chunks while they fit.
7. On the first later chunk that does not fit, stop; later smaller chunks are not considered.

Properties of the current implementation:

- It is greedy and prefix-based.
- It preserves rerank order unless explicit filename targeting moves matching files first.
- It does not cap chunks per file.
- It does not intentionally diversify files.
- It knows both stable file identity (`drive_file_id`) and display identity (`filename`).
- It does not deduplicate arbitrary duplicate input chunks. Filename prioritization only prevents its matched/other partition from adding the same matched chunk twice. Upstream fusion normally supplies unique chunk IDs.
- It preserves chunk/citation metadata by returning the original `RetrievedChunk` values. The existing first-chunk truncation path creates a replacement carrying the same identity and citation fields required downstream.
- Citation payloads are built from selected chunks in selected order, so prompt marker `[N]` and citation position use the same ordering.

### Call path

Linear grounded RAG:

`RagService._ask()` evidence/retrieved chunks → trace mirror via `select_prompt_chunks()` when tracing is active → `ChatService.generate_grounded_answer()` → `OpenAIChatService.generate_grounded_answer()` → `build_grounded_user_message()` → `select_prompt_chunks()` → model prompt. After generation, `RagService` runs the same deterministic selector to construct pre-normalization citations.

LangGraph grounded RAG:

`grade_evidence` accepted `ranked_chunks` → `make_generate_answer_node()` → trace mirror via `select_prompt_chunks()` → `ChatService.generate_grounded_answer()` → `build_grounded_user_message()` → `select_prompt_chunks()` → model prompt. The node runs the same selector again to build citations, and `verify_citations` normalizes markers afterward.

File-target generation also uses the same selector. In normal file-target operation all loaded chunks belong to the resolved target file, so the chosen single-source invariant must preserve its behavior.

The repeated calls do not constitute alternate selection logic: they call the same deterministic function with the same inputs and configuration. EXP-01 must retain that property.

## 3. Existing Test Coverage

### Existing protections

`backend/tests/llm/test_prompts.py` currently verifies:

- Grounded messages include the question and formatted context.
- Selection respects a simple character budget.
- A first oversized chunk is truncated.
- Blank questions return no selected chunks.
- `select_prompt_chunks()` and `build_grounded_user_message()` agree on selected content.
- Citation normalization retains, drops, and renumbers markers deterministically.

Other relevant coverage:

- `backend/tests/retrieval/test_filename_targets.py` verifies explicit filename prioritization and its stable ordering.
- `backend/tests/agents/test_answer_citations.py` verifies graph generation builds citations from prompt chunks and citation verification maps markers to the correct selected chunk.
- `backend/tests/services/test_rag_service.py` verifies traced prompt selection mirrors the deterministic production selector, including first-chunk truncation.
- `backend/tests/agents/test_graph_integration.py` verifies prompt chunks and citations survive a graph retrieval/rewrite/generation flow.
- Existing service and graph tests protect linear and LangGraph answer/citation wiring.

### Untested behavior

No current test directly verifies:

- Fair representation of distinct `drive_file_id` values.
- Repeated chunks from one file not crowding out the first chunk from another file.
- Single-file depth under a source-diversity policy.
- Stable two-pass ordering of first source representatives followed by remaining chunks.
- The behavior when a later oversized chunk blocks an even later fitting chunk.
- Multi-document prompt retention under a constrained realistic budget.
- Citation ordering after source-diverse reordering.
- Preservation of explicit filename-target priority when source diversification is also applied.

## 4. Candidate Policies

### A. Stable first-pass source diversity

Algorithm:

1. Starting from the existing filename-prioritized/reranked list, emit the first chunk for each distinct `drive_file_id` in first-appearance order.
2. Append all remaining chunks in their original relative order.
3. Pass that reordered list to the existing budget fitter unchanged.

Characteristics:

- Complexity: O(n) time and O(f) additional memory for f distinct files.
- Rank preservation: stable within first representatives and stable within remaining chunks; only repeated chunks are deferred behind first representatives of later files.
- Citation metadata: unchanged because original `RetrievedChunk` objects are reordered, not reconstructed.
- Single-document behavior: unchanged because a one-file list is reordered identically.
- `crossdoc_001`: includes guide, DriveMind, and CoreChain before the budget stop.
- `crossdoc_002`: includes guide, CoreChain, DriveMind, and the improvements document under the recorded budget.
- Surface area: one small pure ordering helper and one call in `select_prompt_chunks()`.
- Risk: a lower-ranked new-source chunk can displace a higher-ranked second chunk from an already represented source.

### B. Per-source cap before coverage

Algorithm:

- Permit at most one chunk from a file until either all distinct files have been represented or no further first-file representatives fit; then lift the cap and resume original order.

Characteristics:

- Complexity: O(n) time with per-file state.
- Rank preservation: similar intent to policy A, but selection and budget logic become interleaved.
- Citation metadata: can remain intact.
- Single-document behavior: requires an explicit one-source exception to avoid selecting only one chunk.
- `crossdoc_001` / `crossdoc_002`: expected to solve both if the cap is released correctly.
- Surface area: larger; selection state and budget state must be coordinated.
- Risk: more branches, harder deterministic reasoning, and an ambiguous definition of when coverage is complete under tight budgets.

### C. Budget-aware skip

Algorithm:

- Preserve the current order, but when a non-first chunk does not fit, skip it and continue looking for later chunks that fit the remaining budget.

Characteristics:

- Complexity: O(n) time and O(1) extra state.
- Rank preservation: strict among admitted chunks, with oversized candidates omitted.
- Citation metadata: unchanged.
- Single-document behavior: may improve capacity utilization.
- `crossdoc_001`: does not solve the recorded failure; only 1,371 characters remained after three guide chunks, and no later Gold block fit.
- `crossdoc_002`: does not solve the recorded failure; only 1,381 characters remained, less than the smaller DriveMind block.
- Surface area: tiny.
- Risk: changes stop semantics without addressing the primary baseline cases and may fill context with lower-ranked small distractors.

## 5. Chosen Policy

**Choose policy A: stable first-pass source diversity.**

This is the smallest policy that directly addresses both observed failures without changing the budget algorithm, retriever output, scores, reranking, evidence decisions, generation prompt, or citation normalization.

It preserves relevance ordering as much as the experiment permits:

- The highest-ranked chunk remains first.
- Each file's best-ranked chunk is preferred over its later chunks.
- First representatives retain their original first-appearance order.
- Deferred chunks retain their original relative order.
- With only one file, the order is byte-for-byte equivalent at the chunk-list level.

The experiment changes exactly one production variable: ordering candidates for prompt context so that first representatives of distinct files precede repeated chunks from already represented files.

Budget-aware skipping is deliberately not included. The existing truncate-first/break-later behavior remains frozen so any benchmark delta can be attributed to source-diverse ordering rather than to two simultaneous selection changes.

The normative algorithm is:

1. Input is the ordered list returned by the existing filename-prioritization step.
2. Pass 1 scans that list once and emits only the first occurrence of each distinct `drive_file_id`, preserving encounter order exactly.
3. Pass 2 scans the same original list again and emits every chunk not already emitted, preserving original relative order exactly.

For example, `A1, A2, B1, A3, C1, B2` becomes `A1, B1, C1, A2, A3, B2`.

The reorder must not change scores, apply a score threshold, impose a per-source cap, remove candidates, add candidates, duplicate candidates, or alter filename prioritization. It affects prompt-selection ordering only. Retrieval, RRF, reranking, evidence grading, and every downstream generation/citation rule remain frozen.

### Distractor-promotion risk

Source diversity intentionally allows a lower-ranked first chunk from a different file to move ahead of a higher-ranked second chunk from an already represented file. That can improve missing-source coverage, but it can also promote a distractor source into the bounded prompt.

EXP-01 must therefore monitor:

- Unexpected source presence in prompt context.
- Unexpected cited files.
- Unsupported assertions.
- Every `should_answer=false` case.
- `corechain_003` and `ptcl_003` specifically, because both baseline answers attributed facts from distractor documents.
- Single-document answer quality, which must not degrade even though one-file ordering should be unchanged.

No threshold, source-quality rule, attribution guard, or additional selector condition will be added to mitigate this risk in EXP-01. Such a change would introduce a second experimental variable.

## 6. Behavioral Specification

### 6.1 Identity

- A distinct source means a distinct `RetrievedChunk.drive_file_id`.
- Filename is display metadata, not identity. Different Drive files may share a filename; one Drive file may retain or change display naming without changing its database identity.
- `drive_file_id` is non-null in the production `RetrievedChunk` type.

### 6.2 Input order

- Begin with the list produced by the existing `prioritize_filename_targets(chunks, question)` call.
- Do not change explicit filename extraction or prioritization behavior.
- Treat this post-filename-priority list as the authoritative relevance order for EXP-01.

### 6.3 Stable source-diverse ordering

Build a reordered list in two deterministic passes:

1. First pass: scan input from first to last. Append a chunk if its `drive_file_id` has not appeared before. Record that file ID and the representative chunk ID.
2. Second pass: scan the same input from first to last. Append every chunk that was not emitted as a first-pass representative.

The result must contain the exact same chunk identities as input, each with the exact same multiplicity: no chunk is removed and no duplicate is introduced. The policy must not perform new score calculations, filename matching, text comparison, or semantic deduplication. Upstream uniqueness remains authoritative.

Tie handling is implicit and deterministic: input order wins. No sorting by UUID, filename, length, or score is permitted.

Example:

`A1, A2, B1, A3, C1, B2` becomes `A1, B1, C1, A2, A3, B2`.

### 6.4 Budget fitting

- Feed the reordered list into the existing `select_context_chunks()` unchanged.
- The maximum remains `rag_max_context_chars` minus the exact question/context prefix.
- Block headers, separators, score formatting, and character accounting remain unchanged.
- Whole chunks are admitted while they fit.
- If the first reordered chunk alone is oversized, truncate that first chunk with the existing logic and stop.
- If any later chunk does not fit, stop immediately. Do not skip it to inspect later chunks in EXP-01.
- Selected formatted context must never exceed the current maximum.

### 6.5 Single-source and many-source behavior

- One distinct file: output order is identical to input, so all existing depth behavior remains governed by the unchanged budget fitter.
- Multiple files: the highest-ranked chunk from each file is moved ahead of repeated chunks from already represented files.
- More files than can fit: first representatives are attempted in their original first-appearance order. The unchanged fitter stops at the first non-fitting representative.
- The policy does not guarantee one chunk per file under every possible budget; it guarantees only stable representative priority.

### 6.6 Chunk and citation integrity

- Reordering must retain the original `RetrievedChunk` objects and all fields: chunk ID, document ID, DriveFile ID, filename, MIME type, modification time, chunk index, text, scores, fusion score, primary source, and source scores.
- Existing truncation behavior remains authoritative when the first block is oversized.
- Prompt marker indices are assigned after final selection.
- Citation objects must be built from the same selected sequence, preserving marker-to-chunk-to-file mapping.
- Trace mirroring must continue to use the same selector and inputs as production generation.

## 7. Proposed Regression Tests

### 1. `test_select_prompt_chunks_represents_distinct_sources_when_budget_allows`

- Setup: ranked chunks `A1, A2, B1`, with a budget large enough for `A1` and `B1` but not all three.
- Expected: selected file IDs are `A, B` in that order.
- Protects: basic multi-source fairness.

### 2. `test_select_prompt_chunks_defers_repeated_source_before_new_sources`

- Setup: `A1, A2, A3, B1, C1` with lengths/budget modeled after `crossdoc_001`.
- Expected: ordered candidates begin `A1, B1, C1`; selected context includes B and C rather than three A chunks.
- Protects: the exact repeated-source domination observed in the baseline.

### 3. `test_select_prompt_chunks_preserves_single_source_depth_and_order`

- Setup: three chunks from file A that all fit.
- Expected: `A1, A2, A3`, unchanged and all selected.
- Protects: single-document behavior and file-target depth.

### 4. `test_source_diverse_order_is_stable_within_each_pass`

- Setup: `A1, A2, B1, A3, C1, B2` with enough budget for all chunks.
- Expected order: `A1, B1, C1, A2, A3, B2`.
- Protects: deterministic tie handling, first-representative rank preservation, and remainder rank preservation.

### 5. `test_source_diversity_uses_drive_file_id_not_filename`

- Setup: two chunks with the same filename but different `drive_file_id` values, followed by another chunk sharing the first `drive_file_id`.
- Expected: the two distinct file IDs both appear in pass 1; the repeated first file appears in pass 2. Matching filenames do not merge the sources.
- Protects: stable database file identity rather than ambiguous display-name identity.

### 6. `test_source_diverse_order_preserves_exact_candidate_multiset`

- Setup: several uniquely identified chunks across repeated source IDs.
- Expected: output chunk IDs have the same length, membership, and multiplicity as input; no chunk is missing and no duplicate is introduced.
- Protects: the reorder-only experiment boundary.

### 7. `test_select_prompt_chunks_applies_filename_priority_before_source_diversity`

- Setup: an unrelated high-ranked file followed by multiple chunks from an explicitly named target and another file.
- Expected: the target file's highest-priority chunk is first; source diversity then operates on that already prioritized sequence.
- Protects: existing filename-target behavior and ordering precedence.

### 8. `test_source_diverse_prompt_never_exceeds_max_context_chars`

- Setup: multiple files with block lengths near the boundary; build the full grounded user message.
- Expected: message length is no greater than `max_context_chars`, including question prefix, headers, and separators.
- Protects: hard prompt-budget safety.

### 9. `test_first_oversized_chunk_is_still_truncated_and_stops`

- Setup: a first reordered chunk larger than the entire available context, followed by smaller chunks.
- Expected: exactly one truncated version of the first chunk; later chunks are not admitted.
- Protects: existing first-chunk truncation behavior remains frozen.

### 10. `test_later_nonfitting_chunk_still_terminates_selection`

- Setup: same-source chunks `A1` fitting, `A2` non-fitting, and smaller `A3` that would fit the remaining space.
- Expected: only `A1`; `A3` is not inspected/admitted.
- Protects: EXP-01 changes source ordering only and does not silently add budget-aware skip behavior.

### 11. `test_source_diverse_selection_preserves_chunk_identity_and_citation_order`

- Setup: chunks from A and B with unique chunk/file IDs; generated answer references the selected marker positions.
- Expected: selected objects retain their IDs and metadata; citations follow final prompt order and resolve markers to the correct files.
- Protects: citation/source mapping across reordering.

### 12. `test_source_diversity_preserves_existing_two_resume_prompt_coverage`

- Setup: two one-chunk resume files followed by a distractor, under a constrained budget representative of the currently successful resume cases.
- Expected: both resume file IDs remain selected in their deterministic order.
- Protects: currently successful multi-document prompt retention.

### 13. `test_source_diversity_does_not_change_single_file_distractor_fixture_order`

- Setup: synthetic prompt candidates representing a named Gold source plus a higher-ranked distractor source, with deterministic IDs and enough context for both.
- Expected: ordering follows the specified first-representative policy without inventing attribution or removing candidates; no production mitigation is asserted.
- Protects: makes distractor promotion visible in focused tests without adding a second selector rule.

### 14. Linear and graph integration assertions

- Setup: synthetic multi-source ranked chunks passed through the existing linear RagService test fixture and LangGraph answer-node fixture, with fake chat services only.
- Expected: trace prompt chunks, generated prompt selection, and citation candidates use the same source-diverse order in both paths.
- Protects: production/trace fidelity and parity between linear and LangGraph orchestration.

No proposed test should execute Gold questions, providers, live retrieval, PostgreSQL, or Qdrant.

The later benchmark must separately watch `corechain_003`, `ptcl_003`, all other `should_answer=false` cases, unexpected prompt sources, unexpected cited files, and unsupported assertions. Synthetic selector tests cannot establish semantic safety for those cases, and EXP-01 must not encode Gold-specific production behavior.

## 8. Success / Regression Criteria

### Success

Primary case targets:

- `crossdoc_001` prompt contains both `CoreChain_Project.txt` and `DriveMind_Project.txt`.
- `crossdoc_002` prompt contains both `CoreChain_Project.txt` and `DriveMind_Project.txt`.

Aggregate target:

- Multi-document all-expected-files-in-prompt improves above the locked baseline of 4/7.

Supporting outcomes:

- Grounded-case prompt expected-file recall improves above 88.10%.
- Runner-wide prompt expected-file recall improves above 88.64%.
- Evidence-anchor coverage for the two target cases does not decrease.
- Human grounding/answer judgments for the target cases improve or remain correct without new unsupported claims.
- Unexpected prompt-source presence and unexpected cited-file counts do not increase.
- `corechain_003` and `ptcl_003` do not acquire additional distractor evidence, unsupported assertions, or misleading citations.
- Human answer quality for all `should_answer=false` and single-document cases does not decline.

### Must not regress

- Route accuracy: 20/24 baseline.
- Raw vector/keyword expected-file coverage.
- RRF expected-file coverage and ranks.
- Rerank expected-file coverage and ranks.
- Evidence expected-file coverage and evidence decisions.
- Single-document prompt expected-file coverage.
- The four multi-document cases already retaining all expected files in prompt.
- Citation marker validity.
- False pipeline abstentions: baseline 0.
- Context maximum: 12,000 characters including question/context prefix.
- Latency must not increase materially; the ordering pass is linear and should be negligible relative to retrieval and generation.

### Regression

Any of the following is a regression:

- Either target case still lacks one of its expected Gold files in prompt.
- A currently successful single- or multi-document case loses an expected prompt source.
- Prompt size exceeds the configured limit.
- Prompt/citation marker ordering diverges.
- Route, retrieval, RRF, rerank, evidence, rewrite, abstention, or model configuration changes.
- Human-rated answer quality worsens on a currently correct case.
- New unsupported source attribution appears.
- Median or p95 latency increases beyond ordinary run variance without the target context gains.

## 9. Frozen Variables

EXP-01 freezes all of the following:

- Routing rules and route precedence.
- Vector, keyword, and metadata retrievers.
- Embedding model and vector configuration.
- Candidate K and top K.
- Retrieval score threshold.
- RRF implementation and K.
- Weighted reranker and vector/keyword/metadata weights.
- Evidence grader and threshold.
- LangGraph plan, rewrite trigger, rewrite count, and rewrite model behavior.
- System and user prompt wording.
- Chat model and temperature behavior.
- Citation construction and citation normalization.
- Public API behavior.
- Corpus, chunking, database rows, and Qdrant points.
- Gold v1 dataset, baseline artifact, human review, and baseline analysis.

The only experimental production variable is the order in which already-ranked chunks are presented to the existing character-budget prompt selector.

## 10. Implementation Plan

No implementation is performed in this design step. The smallest later implementation slice is:

1. Modify `backend/app/llm/prompts.py`:
   - Add one private pure helper, conceptually `_source_diverse_order()`, for stable first-pass ordering by `drive_file_id`.
   - Call it in `select_prompt_chunks()` after `prioritize_filename_targets()` and before `select_context_chunks()`.
   - Leave `_context_budget()`, `select_context_chunks()`, formatting, truncation, and citation normalization unchanged.
2. Extend `backend/tests/llm/test_prompts.py` with the focused ordering, `drive_file_id`, no-loss, single-source, budget, oversized-chunk, filename-priority, metadata, and citation-order tests above.
3. Do not change RagService, LangGraph nodes, ChatService, retrieval, configuration, or citation-normalization code. Existing integration suites will verify that both orchestration paths continue to consume the shared selector; add an integration-file edit only if review reveals a concrete unprotected contract that cannot be proven in `test_prompts.py`.
4. Run focused prompt, RagService, and graph tests, followed by standard backend static checks and the full backend suite.
5. Conduct a read-only pre-experiment verification that Gold, corpus fingerprint, configuration, and all frozen variables remain unchanged.
6. Run exactly one complete EXP-01 benchmark only after implementation review and checkpointing. Preserve its result separately from the untouched baseline.

No configuration field, API schema, database migration, evaluation dataset change, retrieval tuning, prompt wording change, or runner change is required for the proposed experiment.

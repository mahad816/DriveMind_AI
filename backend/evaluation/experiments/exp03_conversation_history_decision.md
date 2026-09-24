# EXP-03 Conversation History — Final Decision

## Decision

**MODIFY — CLOSED WITH KNOWN LIMITATIONS.** Retain the implemented, bounded Level-1 explicit-history capability, but do not certify its intent classifier as broadly generalizing to natural-language paraphrases. This decision closes EXP-03; it does not authorize another classifier-tuning loop.

## Experiment Objective

EXP-03 tested explicit recall of the latest prior user question/message or assistant answer/message. It did not target pronoun or coreference follow-ups, contextual document follow-ups, arbitrary conversational reasoning, whole-conversation summarization, or selection of older ordinal turns.

## Implementation Summary

The implementation adds a dedicated `CONVERSATION_HISTORY` route, structured client-supplied history bounded to eight prior messages, a completeness flag, and a deterministic role-aware turn selector with distinct unavailable outcomes. Supported history requests return verbatim selected text without document retrieval, generation-provider calls, or citations. The frontend transports only the active conversation's eligible history and persists in-flight turns under their originating conversation, including completion, failure, and interrupted-reload recovery. The final classifier revision uses bounded message-target, role, recall/recency, ordinal, and document-target concepts. It remains deterministic and Level-1 only.

## Evaluation Methodology and Evidence

Frozen v1 ran first, before the final classifier revision. Its four failed history cases then became **observed regression cases**, not fresh held-out evidence. After the classifier was revised and locked, v2 was designed and frozen without probing its questions against production behavior. V2 ran once as the fresh generalization check; v1 then ran once as regression; frozen Gold v1 ran once against the same final candidate. There was no post-v2 classifier tuning. These are single-run artifacts, not estimates of run-to-run variance.

| Evidence | Source revision / status | SHA-256 | Role |
| --- | --- | --- | --- |
| `backend/evaluation/datasets/conversational_followup_v1.json` | Frozen dataset | `f11d58861848419d5122891919cb6745e338920c50f2223f5d81e55d9f2cca65` | Original conversational contract; unchanged |
| `backend/evaluation/results/drivemind_conversational_followup_v1__20260924T063106Z__be20f198.json` | `be20f198cfd618095a31b2273c64f33c2a3e5cb7` | `e0471db7d4613d537218a5623216b7d3ca93682b43925ecfc575a4d68112c9bc` | First frozen run |
| `backend/evaluation/results/drivemind_conversational_followup_v1__20260924T074215Z__a2721bfe.json` | `a2721bfefddc3c4a5b6accbed80d22b0b0703a9e` | `130a0c4d6911921f700b2d14039f61ff886bf531fa9328d752d40c362d025259` | Final-candidate regression |
| `backend/evaluation/datasets/conversational_followup_v2.json` | Frozen dataset | `0e3741375ed437bb7b644ddc049766b9c9cb418cf44fba0dcc46debf711dcefa` | Fresh generalization; Git object `f384a6f93906a0126c0b62483a886c02a493ebaf` |
| `backend/evaluation/results/drivemind_conversational_followup_v2__20260924T073725Z__a2721bfe.json` | `a2721bfefddc3c4a5b6accbed80d22b0b0703a9e` | `e28c9b3a42c00b4ab75c00521293eb7a9a27f6a6220c4ef71634e329738a7d51` | First and only fresh v2 run |
| `backend/evaluation/datasets/gold_v1.json` | Frozen dataset | `9f223c2143e452cea5d85d20d25d0ea6e081bfb92b09d8d13855f0630526e8a0` | Document-RAG regression contract; unchanged |
| `backend/evaluation/results/drivemind_gold_v1__20260922T200620Z__5350222a.json` | `5350222a1445673030fde5901d36fd5b768aa535` | `e7b9af8c98c2f8e1b36620a4076c2c0f131b4075f497fa5e3b16b9bf4b667c0d` | Accepted EXP-02 reference |
| `backend/evaluation/results/drivemind_gold_v1__20260924T074550Z__a2721bfe.json` | `a2721bfefddc3c4a5b6accbed80d22b0b0703a9e` | `87eabb9da865183987a8ca765b6de4e8e026605ffcdf2655a51386ba53781094` | Final-candidate Gold run |

Result JSON files are ignored under `backend/evaluation/results/.gitignore`, following the existing artifact convention. The paths and hashes identify the local evidence; this decision file does not imply that the result bytes are tracked or pushed.

## Conversational Results

| Run | Passed | Interpretation |
| --- | ---: | --- |
| Original frozen v1 | 15/20 (75%) | Four held-out history-intent misses plus one exact document-route mismatch |
| Final-candidate v1 regression | 19/20 (95%) | All four observed history failures pass; only the same document-route mismatch remains |
| Fresh frozen v2 | 3/8 (37.5%) | All three document controls pass; all five fresh history cases fail |

V2 broke down as USER recall **0/2**, ASSISTANT recall **0/2**, unsupported ordinal **0/1**, and document controls **3/3**. Four fresh recall constructions routed to `GROUNDED_RAG`; the fresh ordinal request routed to history but was treated as latest supported and selected the wrong turn. No v2 document control falsely routed to conversation history. These failures violate the locked 100% history-case generalization thresholds. The selector was not the primary cause of the four intent misses; the ordinal failure began at reference-kind classification.

## Gold Regression

Both Gold runs used the frozen 24-case dataset and the same verified 9-file, 16-chunk corpus fingerprint. The final run completed **24/24** with **zero execution errors**. No Gold case changed route or routed to `CONVERSATION_HISTORY`. Prompt chunk IDs and recorded RRF/reranked candidate IDs matched EXP-02 across cases.

| Metric | Accepted EXP-02 | Final EXP-03 | Observed change |
| --- | ---: | ---: | ---: |
| Route accuracy | 83.33% | 83.33% | None |
| Prompt expected-file recall | 95.45% | 95.45% | None |
| Multi-document prompts with all expected files | 6/7 | 6/7 | None |
| Macro expected-source precision | 46.43% | 46.43% | None |
| Mean unexpected prompt sources | 1.57 | 1.57 | None |
| Citation expected-source recall | 86.36% | **75.00%** | **−11.36 percentage points** |
| Cases citing all expected sources | 19/22 | **16/22** | **−3 cases** |
| Mean lexical must-include coverage | 88.82% | 91.76% | +2.94 percentage points |
| Cases with all must-include phrases | 13/17 | 14/17 | +1 |
| Rewrites / pipeline abstentions / execution errors | 0 / 0 / 0 | 0 / 0 / 0 | None |
| Median / p95 latency | 3.57 s / 9.32 s | 2.93 s / 5.53 s | Lower in this run |

The measured citation decline is real and was conservatively classified **MATERIAL_GOLD_REGRESSION**. Routing, retrieved prompt sources, and reranked candidates did not change. The evidence therefore does **not** establish that EXP-03 caused the citation decline. Generated answer and citation-use variation is a plausible locus, but one run cannot establish causality or normal variance. Do not relabel the Gold run as safe, and do not attribute the decline to the history classifier without new evidence.

## What Worked

- All four observed v1 history-intent misses now pass as regression cases. Supported v1 history requests selected the intended role and turn, with zero retrieval and citations; recognized older-turn ordinals returned the unsupported outcome.
- None of the v1 or v2 document controls was stolen into `CONVERSATION_HISTORY`. The remaining v1 `document_previous_version` case expected `GROUNDED_RAG` but routed to `FILE_INVENTORY`: an official v1 failure and a separate document-routing weakness, not a history false positive.
- Manual smoke testing established prior-question and prior-answer recall, A/B conversation isolation, origin-owned in-flight completion, no deleted-conversation recreation, truthful interrupted state after refresh, and successful regenerate.
- Gold showed no document-route change or retrieval/prompt-candidate change attributable to the new pre-router.

## What Did Not Generalize

Fresh v2 requests referring to the “thing I typed,” a “contribution to this chat,” the assistant's “exact words,” and text the assistant “wrote back” missed history intent. A request for the “middle question” was incorrectly treated as latest supported. These are examples of failed constructions, **not** a proposed synonym list. The deterministic classifier remains bounded by its vocabulary and grammatical constructions. Passing curated and observed regression tests did not demonstrate broad natural-language generalization.

## Final Interpretation and Known Limitations

EXP-03 implemented a useful bounded, deterministic explicit-history capability with isolated request handling. It did **not** demonstrate robust intent recognition under arbitrary natural phrasing and must not be described as production-grade general conversational memory. The feature is retained, but its generalization limit is explicit.

Known limitations and separate future issues are:

1. Natural-language paraphrase and construction generalization for explicit history intent.
2. Older ordinal turns are recognized only in bounded forms; actual older-turn selection is unsupported.
3. Level-2 pronoun/coreference follow-ups such as “did you do that?” remain out of scope.
4. Level-3 document-context follow-ups remain out of scope.
5. The `document_previous_version` exact document-route mismatch and other natural inventory/document-routing weaknesses are separate routing work.
6. The observed Gold citation regression needs a separate investigation; the current evidence cannot assign its cause. The FYP/PTCL factual retrieval error is likewise separate semantic retrieval/grounding work.
7. Generic answer structure and chat/source presentation quality require a separate response/UX track.

If broader conversational understanding becomes a priority, assess a semantic, model-assisted, or hybrid intent layer against a newly scoped evaluation question, rather than indefinitely expanding synonym and regex rules. This is future architectural investigation, not EXP-03.1 or authorization to tune against observed v1/v2 cases.

## Closure

**EXP-03 CLOSED.** No further classifier tuning from v1 or v2. Future work requires a new scoped question and fresh evaluation design.

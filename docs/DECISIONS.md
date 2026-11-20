# Decision log

Short, dated records of engineering decisions with the evidence behind them. Newest first.

## 2026-11-20 — KI-025: recover from a wrong name lookup in code; do not try to prevent it with prompt wording

**Problem.** `resolve_file` matches exact file names only. A model that passes "invoice INV-0457" to it always
gets NOT_FOUND, and the run guard treated any NOT_FOUND as final, so answerable questions ended with "No eligible
indexed file matches that name".

**Tried, measured, rejected (same model, same store):**

| Attempt | Invoice questions to the wrong tool | Side effect found |
|---|---|---|
| Advice in the `resolve_file` *description* (two wordings) | 0 of 70 | `ru06` stopped searching: 17 of 20 runs became 1 of 20 and 0 of 20 |
| Advice in the *system prompt* | 0 of 150 | `ru06` 0 of 20 searched, `pb02` made no tool call, older dev set 77 -> 72 of 88 |
| Wording of the `reference` *argument* | 25 of 70 -> 2 of 70 on the 7 questions it was tuned on | none found; kept. On a held-out question (`id14`) it did nothing (10 of 10 still wrong) |

Prevention through wording is fragile: each variant that moved the target question also moved an unrelated one,
and a wording tuned on 7 questions did not transfer. So the model's first choice is treated as unreliable.

**Decision.** Make the wrong choice harmless instead, in code (`finalization.provenance_response`):
a NOT_FOUND for a reference that does **not** end in a file extension is "soft"; a later successful content read in
the same run clears it. A NOT_FOUND for a reference that does look like a file name (`budget_2027.txt`) stays final,
so a missing file is never answered from other documents. The NOT_FOUND result now carries a hint the model sees
(file names match exactly; search for numbers and topics), chosen by the same rule (`file_reference.names_a_file`).

**Why a structural rule.** Whether a reference ends in an extension is checkable and deterministic; guessing the
user's intent from the question text is not. It is the same kind of bounded check as `scope_guard`.

**Known cost.** A user who names a document without an extension that does not exist ("the training handbook")
can now get an answer drawn from a related file, labelled with that file's real name. That already happened before
this change (the model searched first and never used the lookup; see KI-028), so the change does not create it,
but it does give the model one more path to it.

**Evidence.** Held-out set (19 questions written before the work, `rag_v2_identifier_cases.json`): 14 -> 16 passing,
of which one question (`id14`) is this fix: 10 of 10 runs now go lookup -> NOT_FOUND hint -> search -> correct
answer with citation (before: the first call went to the lookup in 10 of 10 runs, and the one end-to-end run ended with the lookup-failure text, which the old rule makes certain). Older dev set 77 -> 78 of 88, test-split
first tool unchanged case by case, `ru06` and `pb02` 20 of 20 searched. Details: `docs/EVALUATION_RESULTS.md`.

## 2026-11-20 — `gpt-5.4-nano` also has a shutdown date; plan to move to `gpt-6-luna`

**New fact** (official [deprecations page](https://developers.openai.com/api/docs/deprecations) and
[model page](https://developers.openai.com/api/docs/models/gpt-5.4-nano), read 2026-11-20): `gpt-5.4-nano` is marked
deprecated and shuts down on **2027-04-01**; the suggested replacement is `gpt-6-luna`. `gpt-4o-mini`
(`gpt-4o-mini-2024-07-18`) shuts down 2027-01-14. `gpt-5.4-mini` has no model shutdown listed. The 2026-11-19 entry
below said nano was "not deprecated"; that is no longer true.

**Official numbers** (per 1M tokens, standard processing; all from the OpenAI model pages):

| | gpt-5.4-nano | gpt-5.4-mini | gpt-6-luna |
|---|---|---|---|
| Input / cached input / output | $0.20 / $0.02 / $1.25 | $0.75 / $0.075 / $4.50 | $0.10 / $0.01 / $0.50 |
| Context window | 400,000 | 400,000 | 1,050,000 |
| Max input / max output | 272,000 / 128,000 | 272,000 / 128,000 | 922,000 / 128,000 |
| Knowledge cutoff | 2025-08-31 | 2025-08-31 | 2026-05-18 |
| Reasoning effort | none (default) .. xhigh | none (default) .. xhigh | none .. max, **medium by default** |
| Function calling on Chat Completions | works with defaults | works with defaults | only with `reasoning_effort: none` |
| Described as | low-cost, fast: classification, extraction, ranking, sub-agents | strongest mini model: coding, computer use, sub-agents | most efficient model for focused, high-volume tasks |

Luna is 2x cheaper than nano on input and 2.5x on output (7.5x / 9x cheaper than mini). The model page gives no
intelligence or speed rating, so quality versus nano or mini is **unknown until measured**; third-party comparison sites
disagree and were not used. The code already sends `reasoning_effort: none` for `gpt-6*` (`completion_options`).

**Our own measurements (2026-11-19, see below and `docs/EVALUATION_RESULTS.md`):** Luna scored 98.7% on the intent gate
with 1.2 s median latency in one run, but in another run 19 requests failed (HTTP 500 and timeouts, about 10 s). Nano was
6/6 at about 0.8 s. So the open question about Luna is reliability, not capability.

**Decision:** use `gpt-6-luna` as the candidate chat model in the chat-model evaluation (Step 5), next to `gpt-5.4-nano`
and `gpt-5.4-mini`, with repeats on different days, a per-run request-failure count, and a retry policy decided from the
measured error rate. The production default must be changed before 2027-04-01 and Railway's `CHAT_MODEL` must be set
explicitly. No change to the default today.

## 2026-11-19 — Default chat model: `gpt-5.4-nano` (not `gpt-6-luna`)

**Why change at all:** the old default `gpt-4o-mini` shuts down on **2027-01-14**
([OpenAI deprecations](https://developers.openai.com/api/docs/deprecations)). `gpt-5-nano` (the cheapest) shuts down 2026-12-11.

**Candidates** (prices per 1M input / output tokens from the
[official pricing page](https://developers.openai.com/api/docs/pricing)): `gpt-6-luna` $0.10 / $0.50,
`gpt-5.4-nano` $0.20 / $1.25, `gpt-5-mini` $0.25 / $2.00, `gpt-4o-mini` $0.15 / $0.60 (retiring).

**Evidence (live, same tiny intent-style request, no client retries):**

| Model | Successful | Median latency | Notes |
|---|---|---|---|
| gpt-4o-mini | 6 / 6 | 1.0 s | retiring 2027-01-14 |
| gpt-5.4-nano | 6 / 6 | 0.8 s | accepts `temperature=0`, JSON mode and tools with default settings |
| gpt-5-mini | 6 / 6 | 1.0 s | not compared further |
| gpt-6-luna | 1 / 6, then 5 / 8 (6 / 14 overall) | ~10 s | HTTP 500 `server_error` and timeouts; OpenAI status page showed no incident |

`gpt-6-luna` also needs `reasoning_effort="none"` for function tools and `temperature=0`
(probe: default reasoning rejects both). A small `completion_options()` helper adds that body
for `gpt-6*` models only, so luna remains usable if it becomes reliable. Earlier the same day luna
measured a 1.2 s median with no errors (intent_v1: 76/77 correct), so the problem looks like
provider-side instability, not the model's quality.

**Decision:** default to `gpt-5.4-nano` (reliable, fast, no special handling, not deprecated).
Revisit `gpt-6-luna` (cheaper) and `gpt-5.4-mini` (stronger) in the main RAG evaluation, where
answer quality, not just reliability, decides. Hosted Railway may set `CHAT_MODEL` explicitly;
that variable must be changed before 2027-01-14 (not checked from this repo).

**Not measured:** answer quality of nano on the 24 gold cases (done in the RAG evaluation phase).

# Decision log

Short, dated records of engineering decisions with the evidence behind them. Newest first.

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

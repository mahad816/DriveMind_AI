# Decision log

Short, dated records of engineering decisions with the evidence behind them. Newest first.

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

# Evaluation results log

Committed summary of measured results (raw run files stay local in `backend/evaluation/results/`,
which is gitignored). Newest first. Every entry states the commit, model and dataset so it can be
reproduced. Numbers here are measurements, not guarantees.

## Intent gate — `intent_v1` (live)

Question: can the small model call that runs before the document agent recognise greetings, thanks,
farewells, "what can you do", out-of-scope requests and real document questions by *meaning* (no phrase
list)? Dataset: `backend/evaluation/datasets/intent_v1.json` (83 hand-written cases incl. greeting + request
mixes, follow-ups with the previous assistant message, and Roman Urdu). Run:
`cd backend && uv run python -m evaluation.intent_eval --execute`.

Worst error = **false decline** (a real document question treated as small talk / out of scope).
Mild error = **missed chitchat** (small talk sent to the document agent, which refuses politely).

| Date (UTC) | Model | Commit | Cases | Accuracy | False declines | Missed chitchat | Median latency | API errors |
|---|---|---|---|---|---|---|---|---|
| 2026-11-19 16:01 | gpt-5.4-nano | db870be | 83 | **100%** | 0 | 0 | 0.89 s | 0 |
| 2026-11-19 15:59 | gpt-5.4-nano | db870be | 83 | 98.8% | 0 | 1 | 0.81 s | 0 |
| 2026-11-19 15:58 | gpt-5.4-nano | db870be | 83 | 97.6% | 0 | 2 | 0.78 s | 0 |
| 2026-11-19 15:56 | gpt-5.4-nano | 6575da0 | 83 | 96.4% | 1 | 2 | 0.77 s | 0 |
| 2026-11-19 15:50 | gpt-6-luna | 8ed4b02 | 83 | 56.6% (invalid) | 0 | 36 | 9.7 s | 19 |
| 2026-11-19 15:36 | gpt-6-luna | f44d751 | 77 | 98.7% | 1 | 0 | 1.2 s | 0 |

Reading the table honestly:
- The `gpt-6-luna` 15:50 row is **not a quality result**: 19 requests failed (HTTP 500/timeouts) and the gate
  correctly fell back to the document agent. It shows the fail-safe works and that luna was unreliable
  at that time (see `docs/DECISIONS.md`).
- Between 15:56 and 15:58 the prompt was generalised (bare acknowledgements after an answer) and one
  ambiguous trivia case (i072) was relabelled to accept either label. That is tuning on the same set, so the
  later rows are optimistic; a fresh held-out set is needed before claiming a general accuracy.
- Run-to-run variation on identical code was 97.6% to 100%, so single runs should not be over-read.
- Early gap found and fixed: a bare "yes please" was read as thanks until the previous assistant message was
  given to the classifier.
- Cost: one request per case, a few hundred tokens each; well under one cent per full run (estimate from
  token counts at the official price).

## Earlier baselines (pre-existing)

See `backend/evaluation/analysis/baseline_v1_failure_analysis.md` (Gold v1, 24 cases, 2026-09-21: routing 20/24)
and `backend/evaluation/experiments/` for experiments 01 to 03. These predate the tool agent and the intent gate.

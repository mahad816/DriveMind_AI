# Evaluation

DriveMind has implemented evaluation tracing, a versioned gold dataset, deterministic metrics, a sequential runner for the production RAG path, and a separate conversation evaluation harness. This guide distinguishes that tooling from future evaluation work. It does not claim a new run or score.

## Implemented today

| Area | Location | What it does |
|------|----------|--------------|
| Internal trace capture | `backend/app/evaluation/trace.py` | Captures route, retrieval attempts, selected prompt chunks, answers/citations, outcomes, timings, and errors when explicitly requested by an evaluation caller. Traces are not exposed by the public `/chat` response. |
| Gold question set | `backend/evaluation/datasets/gold_v1.json` | Versioned labeled questions for the controlled corpus. |
| Dataset validation | `backend/evaluation/dataset.py` | Loads and validates evaluation cases. |
| Deterministic metrics | `backend/evaluation/metrics.py` | Calculates file-ranking, source, citation, route, and phrase diagnostics from results/traces. |
| Gold runner | `backend/evaluation/runner.py` | Checks corpus and environment, runs cases sequentially through `RagService`, and writes a machine-readable result artifact. |
| Conversation harness | `backend/evaluation/conversation_dataset.py`, `conversation_runner.py`, and `datasets/conversational_followup_v*.json` | Exercises conversation-history behavior separately from the single-turn gold runner. |
| Tests | `backend/tests/evaluation/` | Tests dataset validation, metrics, tracing, runner preflight, and conversation evaluation with synthetic fixtures. |

The repository also records baseline failure analysis and later experiment decisions under `backend/evaluation/analysis/` and `backend/evaluation/experiments/`, with human-review records under `backend/evaluation/reviews/`. Read those artifacts for their specific conditions and conclusions; they are not a claim about a fresh local run.

## Controlled corpus

The original controlled Google Drive corpus, `DriveMind_Eval_Corpus_v1`, contains nine named text files:

`CoreChain_Project.txt`, `DriveMind_Project.txt`, `PTCL_Internship.txt`, `Resume_v1.txt`, `Resume_v2.txt`, `Cloud_Computing_Notes.txt`, `Machine_Learning_Notes.txt`, `Meeting_Notes_July.txt`, and `Expense_Report_2025.txt`.

The September 2026 checkpoint documented these as indexed with matching PostgreSQL chunks and Qdrant points. That was a point-in-time observation, not a guarantee about another developer's Drive account or current local database. Keep the corpus fixed when comparing baseline and experiments; version any material corpus changes.

## Running the implemented tooling

From `backend/`, inspect the available options without executing provider calls:

```bash
uv run python -m evaluation.runner --help
uv run python -m evaluation.conversation_runner --help
uv run pytest tests/evaluation -q
```

A deliberate gold run uses `uv run python -m evaluation.runner --execute-gold`. It needs the controlled Drive corpus indexed in PostgreSQL and Qdrant, a configured backend/OpenAI environment, and a clean Git tree by default. The explicit flag prevents accidental live API usage. The runner writes JSON under `backend/evaluation/results/`, which is ignored by Git. The conversation harness has its own explicit `--execute-conversation` flag and dataset. Do not treat synthetic test fixtures as measured retrieval quality.

## The v2 harness (`backend/evaluation/rag_eval/`): free and paid commands

Run from `backend/`. The v2 harness answers the committed question sets through the production path against an isolated, disposable PostgreSQL and Qdrant store (see `docs/EVALUATION_RESULTS.md`).

**Free (no key, no provider, no store):**

```bash
env -u OPENAI_API_KEY uv run pytest tests/evaluation -q
uv run python -m evaluation.rag_eval.cli run --plan --cap 3 --pipelines tool_agent --split dev
uv run python -m evaluation.rag_eval.cli setup --plan --cap 1
uv run python -m evaluation.rag_eval.cli rescore evaluation/results/FILE.json --plan --cap 1
```

`--plan` prints the number of cases, the expected calls by role and an estimate, then stops: nothing is called, built or written. The estimate uses the dated planning constants in `evaluation/rag_eval/prices.json` (`estimates`), which are not measurements.

**Paid (can spend money, each needs an explicit `--cap` in USD, no default):**

| Command | What it can spend on |
|---|---|
| `cli setup --cap USD` | embeddings for the corpus |
| `cli run --cap USD [--repeats N] [--limit N]` | the answering calls and the refusal judge; `--repeats` is 1 to 5 and writes one result file per repeat and pipeline |
| `cli rescore FILE --cap USD` | the refusal judge |
| `first_step_probe`, `retrieval_probe`, `ragbench_check`, `planted_claims` (`--cap USD`) | one model call or one embedding per question; these four have no `--plan` yet |

A command whose estimate is above `--cap` refuses to start. During a run the meter refuses every provider call after the cap is reached and the run stops (the run in progress is not written). The meter checks before each call, so requests already in flight can overshoot by up to the concurrency times one call. It counts successful responses only, so SDK retries and failed requests are invisible to it.

Every `run` result file carries a `manifest` (schema version 1): the audited commit and whether the tree was clean, every answer-relevant setting, digests of the prompts and tool descriptions, corpus and dataset checksums, the price-table date, concurrency, repeat index and count, library versions, the cap and the spend. The evaluation settings are pinned to the application's code defaults (`target.ANSWER_FIELDS`), whatever the local environment says; only `--model`, `--threshold`, `--relative` and `--no-claim-check` change them, and the manifest lists such differences under `deviations_from_default`. Files written before the manifest existed can still be re-scored.

## What to measure

The implemented diagnostics can help answer:

- **Routing:** Did the top-level route match the labeled expectation?
- **Retrieval:** Did expected files survive candidate retrieval, merge/rerank, and final prompt selection? File-level hit/recall and reciprocal-rank measures collapse repeated chunks from one file.
- **Grounding:** Were expected sources in the prompt and in normalized citations? Did required phrases appear, and were forbidden phrases avoided?
- **Abstention:** Did the system answer or decline appropriately when evidence was absent?
- **Latency and rewrites:** How many retrieval attempts occurred, and where was time spent?

Human review is still needed to judge whether an answer's claims are supported and useful. The recorded review packets and experiment decisions show how that review has been applied; deterministic metrics alone do not prove answer quality.

## Future work

Broader held-out datasets, calibrated human scoring, and optional LLM-as-judge comparisons can extend the current tooling. Any new results should identify the dataset version, corpus fingerprint, configuration, Git revision, and review method. Avoid treating proposed target thresholds or unexecuted commands as measured results.

See [Retrieval](RETRIEVAL.md), [LangGraph](LANGGRAPH.md), and [Current Status](../CURRENT_STATUS.md).

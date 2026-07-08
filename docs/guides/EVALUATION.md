# Evaluation Methodology

How to measure DriveMind retrieval and answer quality. Phase 10 will implement tooling; this document defines the approach.

---

## Goals

DriveMind is portfolio-grade — evaluation should demonstrate **AI engineering rigor**, not just "it works on my laptop."

Three dimensions:

| Dimension | Question |
|-----------|----------|
| **Retrieval** | Did we fetch the right chunks? |
| **Grounding** | Is the answer supported by retrieved evidence? |
| **Usefulness** | Does the answer help the user? |

---

## Retrieval metrics

### Hit rate @ K

For a labeled question set, did the expected file or chunk appear in the top-K retrieved results?

```text
hit@k = (queries where expected chunk in top-k) / total queries
```

Target benchmarks (MVP):

| Query type | Target hit@8 |
|------------|--------------|
| Named file (`Tell me about "X"`) | ≥ 95% |
| Latest file (`latest resume`) | ≥ 90% |
| Semantic topic | ≥ 75% |
| Inventory (`how many PDFs`) | ≥ 90% |

### Mean reciprocal rank (MRR)

Position of the first relevant chunk:

```text
MRR = average(1 / rank_of_first_relevant)
```

### Route accuracy

Did `classify_query()` pick the correct route?

| Route | Example | Expected route |
|-------|---------|----------------|
| CHITCHAT | `hi` | CHITCHAT |
| FILE_INVENTORY | `how many resumes` | FILE_INVENTORY |
| FILE_TARGET | `tell me about "Far611"` | FILE_TARGET |
| GROUNDED_RAG | `what is tensile strength` | GROUNDED_RAG |

---

## Grounding metrics

### Citation precision

Every `[N]` reference in the answer should map to a retrieved chunk that supports the claim.

```text
citation_precision = supported_citations / total_citations
```

Manual review on a sample of 20–50 answers is acceptable for MVP.

### Hallucination rate

Answers that state facts **not present** in any retrieved chunk.

```text
hallucination_rate = hallucinated_answers / total_answers
```

LangGraph's `verify_citations` node reduces invalid reference hallucinations.

### Abstention quality

When no evidence exists, the system should say so — not invent content.

Check: `NO_EVIDENCE_ANSWER` and file-not-found messages are returned appropriately.

---

## Answer quality (LLM-as-judge)

For a held-out question set, use a rubric scored 1–5:

| Criterion | Description |
|-----------|-------------|
| Relevance | Answers the question asked |
| Completeness | Covers key points from sources |
| Clarity | Well-structured, readable |
| Faithfulness | No unsupported claims |

Optional: GPT-4 as judge with retrieved chunks as context (blind to expected answer).

---

## Test question sets

Build three tiers:

### Tier 1 — Smoke (10 questions)

Quick regression after retrieval changes:

- `hi` (chitchat)
- `how many files do I have`
- `tell me about "<known filename>"`
- `what is in my latest resume`
- `summarize my machine learning projects`

### Tier 2 — Route coverage (30 questions)

Cover each `QueryRoute` and intent type with 5–10 examples each.

### Tier 3 — Adversarial (20 questions)

- Misspelled filenames
- Ambiguous short names (`"HI"`)
- Questions with no indexed evidence
- Multi-file topic summaries

Store as JSON:

```json
{
  "id": "resume-latest-01",
  "question": "What is in my latest resume?",
  "expected_route": "GROUNDED_RAG",
  "expected_files": ["resume.pdf"],
  "tags": ["metadata", "latest"]
}
```

---

## Planned Phase 10 implementation

| Deliverable | Description |
|-------------|-------------|
| `evaluation/question_sets/` | Versioned JSON question banks |
| `evaluation/runner.py` | Batch query + log results |
| `evaluation/metrics.py` | hit@k, MRR, route accuracy |
| Evaluation API or CLI | `uv run python -m app.evaluation.run --set smoke` |
| Frontend dashboard | Optional — retrieval stats, failure cases |

---

## Running manual evaluation today

```bash
# 1. Ensure index is built
curl http://localhost:8000/api/v1/index/pending

# 2. Run a question, inspect citations
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "Tell me about \"Far611\""}' | jq .

# 3. Verify source chunk
curl http://localhost:8000/api/v1/sources/<chunk_id> | jq .
```

Log results in a spreadsheet: question, route (inferred), files cited, pass/fail, notes.

---

## Regression discipline

After retrieval or prompt changes:

1. Run Tier 1 smoke set
2. Compare hit@8 and route accuracy to baseline
3. Spot-check 5 answers for grounding
4. Commit with note if metrics change

---

## Related docs

- [Retrieval Strategy](RETRIEVAL.md)
- [LangGraph Workflow](LANGGRAPH.md)
- [Limitations & Future](../LIMITATIONS_AND_ROADMAP.md)

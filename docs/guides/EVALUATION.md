# Evaluation Methodology

How to measure DriveMind retrieval and answer quality. Phase 10 will implement tooling; this document defines the approach.

---

## Current Evaluation Checkpoint — 2026-09-19

### Stabilization

DriveMind has completed its pre-evaluation stabilization pass. Important checkpoints include internal RAG evaluation tracing, partial-ingestion continuation, exact `INDEXING`-only chunk/build eligibility, citation normalization, reliable indexing/job-state semantics, and routing short substantive queries to retrieval.

### Evaluation tracing

Internal evaluation tracing can observe the route and execution path; raw per-retriever, RRF, and reranked candidates; evidence grading; LangGraph rewrite attempts; selected prompt chunks; raw and final answers/citations; abstention/outcome; coarse timings; and fatal errors. Tracing is internal only and does not change the public `/chat` response.

### Controlled Corpus v1

The Google Drive folder `DriveMind_Eval_Corpus_v1` contains exactly these nine controlled files:

- `CoreChain_Project.txt`
- `DriveMind_Project.txt`
- `PTCL_Internship.txt`
- `Resume_v1.txt`
- `Resume_v2.txt`
- `Cloud_Computing_Notes.txt`
- `Machine_Learning_Notes.txt`
- `Meeting_Notes_July.txt`
- `Expense_Report_2025.txt`

Verified corpus state:

- 9/9 files are `INDEXED`, searchable, chunked, and represented in Qdrant.
- PostgreSQL has 16 corpus chunks and Qdrant has 16 matching points.
- There are no duplicate `DriveFile` rows, current documents, or chunk indices.
- All controlled anchors and resume-version facts were verified.

Controlled anchors:

- CoreChain: Cedar Falcon
- DriveMind: Silver Atlas
- PTCL: Amber Signal
- Cloud notes: Nimbus Seven
- Machine-learning notes: Vector Orchard
- Meeting notes: Marble Lantern
- Expense report: Copper Ledger

Resume version facts:

- `Resume_v1`: CGPA 2.40; expected graduation December 2026; DriveMind is absent from the actual project section.
- `Resume_v2`: CGPA 2.70; expected graduation January 2027; DriveMind is present.

Corpus v1 is **FROZEN**. Do not edit these nine files during baseline evaluation. If their content must change materially, create a new corpus version.

### Partial-ingestion reliability

Corpus preparation exposed 15 unrelated historical PDFs that failed ingestion. Previously, the frontend treated the failed ingestion batch as wholly fatal and prevented healthy files from reaching chunk/build.

The production flow now keeps the ingestion batch truthfully `FAILED`, leaves failed files `FAILED`, and lets successfully ingested `INDEXING` files continue through the normal chunk/build stages. Chunk/build eligibility is restricted to exactly `INDEXING`, preventing stale failed content from being resurrected. When healthy files finish successfully, setup becomes usable with a visible warning. The real UI flow was verified successfully.

The 15 historical failed PDF rows remain unavailable and are not part of the controlled corpus. Do not treat them as Corpus v1 failures.

### Frontend development caution

Do not run `npm run build` concurrently with a running `npm run dev`/`next dev` process in the same frontend checkout. Both use `frontend/.next`; doing so caused missing Turbopack development manifests and HTTP 500 responses.

Before a production build, stop the dev server, run the build, and restart dev afterward if needed. If `.next` becomes inconsistent, stop dev, delete only `frontend/.next`, and restart `npm run dev`. No source-code fix is required for this runtime artifact issue.

### Next evaluation step

Do not tune retrieval or install DeepEval yet. The next task is **Step 4 — build the manually verified gold evaluation dataset**, starting with approximately 20–25 human-labeled cases covering routing/chitchat, file inventory, file targeting, exact and semantic retrieval, multi-document retrieval, resume/version/latest behavior, distractor resistance, missing-information/abstention, citation support, and query rewriting.

Continue in this order:

```text
gold dataset
→ deterministic runner/metrics
→ untouched baseline
→ manual failure analysis
→ human answer scoring
→ later DeepEval/LLM-judge calibration
→ controlled one-variable-at-a-time experiments
```

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

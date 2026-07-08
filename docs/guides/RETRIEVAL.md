# Retrieval Strategy

How DriveMind finds relevant evidence before generating an answer.

---

## Design goal

Vector search alone fails on real Drive questions:

| Query type | Why vectors struggle | DriveMind approach |
|------------|---------------------|-------------------|
| *Find my latest resume* | "Latest" is temporal metadata | Metadata retriever + sort by date |
| *How many PDF files?* | Needs counting, not similarity | FILE_INVENTORY SQL path |
| *Tell me about "Far611"* | Short name drowned by vector noise | FILE_TARGET direct lookup |
| *What is federated learning?* | Semantic concept search | Vector + keyword hybrid |

---

## Query routing

`classify_query()` in `app/retrieval/query_router.py` assigns one of four routes **in priority order**:

```text
Question
   │
   ├─ CHITCHAT ────────────→ Direct LLM (no retrieval)
   ├─ FILE_INVENTORY ──────→ SQL file search + inventory answer
   ├─ FILE_TARGET ─────────→ Named-file chunk lookup
   └─ GROUNDED_RAG ────────→ Hybrid retrieval (default)
```

### Route details

| Route | Triggers | Retrieval |
|-------|----------|-----------|
| **CHITCHAT** | `hi`, `thanks`, etc. — no knowledge signals | None |
| **FILE_INVENTORY** | `how many`, `list`, resume/CV/certificate keywords | `FileInventoryRetriever` |
| **FILE_TARGET** | Quoted filename or `tell me about X` patterns | `FileTargetRetriever` — all chunks for matched file |
| **GROUNDED_RAG** | Everything else | Hybrid or vector path |

Quoted strings (`"Far611"`) bypass chitchat classification and prioritize file-target matching.

---

## Hybrid retrieval (GROUNDED_RAG)

**Module:** `app/retrieval/hybrid.py`

When `HYBRID_RETRIEVAL_ENABLED=true` (default):

```text
                    ┌─ VectorRetriever (Qdrant)
Question ──────────►├─ KeywordRetriever (PostgreSQL FTS)
                    └─ MetadataRetriever (SQL filters)
                              │
                              ▼
                    reciprocal_rank_fusion_merge()
                              │
                              ▼
                    weighted_fusion_rerank(question)
                              │
                              ▼
                    grade_evidence()
                              │
                              ▼
                         Top-K chunks
```

### Three retrievers

| Retriever | Source | Best for |
|-----------|--------|----------|
| **Vector** | Qdrant cosine similarity | Semantic / conceptual questions |
| **Keyword** | PostgreSQL full-text search | Exact terms, quoted names, rare tokens |
| **Metadata** | SQL on `drive_files` | Latest file, folder, MIME type, date filters |

### Merge: Reciprocal Rank Fusion (RRF)

Candidates from each retriever are merged by `chunk_id`. Score contribution per source:

```text
score += weight / (rrf_k + rank)
```

Default weights: vector **0.5**, keyword **0.3**, metadata **0.2**.

### Rerank: weighted fusion

`weighted_fusion_rerank()` combines per-source normalized scores with config weights, then sorts by:

1. **Filename target priority** — quoted names in query boost exact filename matches
2. **Fusion score** descending
3. **`modified_at`** descending (recency tie-break)

Output truncated to `RETRIEVAL_TOP_K` (default **8**).

### Evidence grading

`grade_evidence()` filters chunks below `EVIDENCE_MIN_FUSION_SCORE`. Returns:

- `sufficient` — enough evidence to answer
- `reason` — why evidence was weak (used by rewrite loop)
- `chunks` — filtered candidate list

---

## FILE_TARGET path

**Modules:** `app/retrieval/file_target.py`, `filename_targets.py`

For questions like *Tell me about "Far611"*:

1. Extract quoted or heuristic filename targets
2. SQL `ILIKE` / exact match on `drive_files.name`
3. Return **all chunks** for the matched file (not top-K slice)
4. Dedicated prompt (`FILE_TARGET_SYSTEM_PROMPT`) for file-summary answers

Short quoted names (≤4 chars) use **exact** filename match to avoid substring false positives.

---

## Linear vs LangGraph path

For `GROUNDED_RAG` only:

| `AGENT_GRAPH_ENABLED` | Path |
|-----------------------|------|
| `false` (default) | Linear: `HybridRetriever.retrieve_with_grade()` → grounded answer |
| `true` | LangGraph agent with intent planning, selective retrievers, rewrite loop |

Chitchat, inventory, and file-target routes are **unchanged** regardless of the flag.

See [LangGraph Workflow](LANGGRAPH.md).

---

## Configuration

| Env var | Default | Purpose |
|---------|---------|---------|
| `HYBRID_RETRIEVAL_ENABLED` | `true` | Enable hybrid vs vector-only |
| `RETRIEVAL_CANDIDATE_K` | `24` | Candidates per retriever |
| `RETRIEVAL_TOP_K` | `8` | Chunks sent to LLM |
| `RETRIEVAL_SCORE_THRESHOLD` | `0.35` | Vector similarity floor |
| `HYBRID_RRF_K` | `60` | RRF constant |
| `HYBRID_WEIGHT_VECTOR` | `0.5` | Vector weight in fusion |
| `HYBRID_WEIGHT_KEYWORD` | `0.3` | Keyword weight |
| `HYBRID_WEIGHT_METADATA` | `0.2` | Metadata weight |
| `EVIDENCE_MIN_FUSION_SCORE` | `0.15` | Grading threshold |
| `RAG_MAX_CONTEXT_CHARS` | `12000` | Max context for LLM |
| `FTS_LANGUAGE` | `english` | PostgreSQL FTS language |

---

## Citation format

Answers include `[N]` references mapped to `CitationItem`:

```json
{
  "chunk_id": "...",
  "drive_file_id": "...",
  "filename": "resume.pdf",
  "snippet": "...",
  "score": 0.87
}
```

The LangGraph path additionally **verifies** citations — stripping references to chunks not present in the answer.

---

## Related docs

- [LangGraph Workflow](LANGGRAPH.md)
- [Indexing Lifecycle](INDEXING.md)
- [Architecture](../ARCHITECTURE.md)

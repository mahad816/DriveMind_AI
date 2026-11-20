# Retrieval foundations plan (Stages A to F), then Steps 2 to 5

Status: **proposal for review, 2026-11-20. No code has been changed for this plan.**
Companion to `docs/IMPROVEMENT_PLAN.md` (which keeps Steps 0 to 1c as history). This file replaces its Step 2 to 6 order.

Plain-words goal: for a normal Drive (hundreds of files, not thousands), the right passage reaches the model
almost every time, the model answers only from it, and everything is measured, tested and repeatable.
Scanned images and OCR are **out of scope for now**.

---

## 0. The order and why

| Stage | What | Needs | Est. cost | Est. sessions |
|---|---|---|---|---|
| **A** | Read real files properly: tables, slides, headers; add PPTX, XLSX, Google Slides/Sheets | nothing | ~$0.12 | 3 |
| **B** | Chunking: size, overlap, structure, titles, tables, "small-to-big" | A | ~$0.30 | 2 to 3 |
| **C** | Keyword search that ranks by any word, with exact IDs | A, B | ~$0.02 | 1 |
| **D** | Ranking weights sweep | A to C | ~$0.01 | 1 |
| **E** | Re-ranker: improve what we have, else an LLM re-ranker | A to D | ~$0.40 | 2 |
| **F** | Embedding model comparison | A to D | ~$0.18 | 1 |
| Steps **2, 3, 4, 5** | Force a search, newest version, claim check + refusal sources, bigger model | A to F | ~$1.75 | 5 |
| **Final** | One full confirmation run, then the project discussion | all | ~$0.50 | 1 |
| | **Total** | | **~$3.3 (range 2.9 to 3.8)** | **16 to 18** |

**Why foundations first.** The model steps (2 to 5) are the most expensive to measure. They tune what the model does
with the evidence it receives. If chunking or file reading changes afterwards, the evidence changes, and those
measurements must be paid for twice. So: change what the model *receives* first (A to F), then tune what it *does* (2 to 5).

**Rules for every stage** (the same discipline as Steps 1a to 1c):
1. Measure the "before" first, with the free or cheap tools (`retrieval_probe`, `first_step_probe`, extraction tests).
2. Choose the setting on the dev split, confirm on the held-out test split. Never tune on test.
3. Compare old and new on the **same day**, on the cases the stage can change, with repeats.
4. Every behaviour change gets a test that fails when the behaviour is broken (checked by deliberately breaking it).
5. Report in plain words with an example; keep the numbers few; caveats together at the end.
6. Stop rule: if a gain is within noise, keep the simpler code.
7. Money: say the cost before paid work; never let the balance go negative.

---

## 1. What the code analysis found (evidence, not opinion)

| # | Finding | How I know |
|---|---|---|
| 1 | **DOCX tables are dropped completely.** The reader takes only paragraphs. | Test file with a 3x3 pricing table came back as `'Pricing\nOur plans are listed below.\nPrices exclude tax.'` |
| 2 | **Running page headers pollute chunks.** | The same line is on 77 of 80 pages (NIST 800-61), 72 of 76 (NIST 800-63), 26 of 26 (an arXiv paper) |
| 3 | **PDF table detection is unreliable by default.** pdfplumber (the common table library) found 147 "tables" in a 76-page PDF; 125 were a single row or column (rule lines), 5 survived a basic filter and those were callout boxes, none a data table. In "text" mode it invented one 63x9 table over a whole page. | Experiment on the corpus PDFs |
| 4 | For simple 2-column tables the current reader keeps row words together ("IDPSs IDPS products identify..."), which is adequate. Numeric grids lose their column headings. | Experiment on NIST 800-61 page 37 |
| 5 | pdfplumber is about 3x slower than pypdf (80 pages: 4.9 s vs 1.6 s). That is fine for background indexing. Two-column pages are **not** merged across columns by either reader. | Timing and line-length check on 3 pages |
| 6 | Only PDF, DOCX, TXT, Google Docs (as plain text) and images are supported. **No PPTX, XLSX, Google Slides or Sheets.** | `constants.py`, `registry.py` |
| 7 | Google Docs are exported as **plain text**, which loses table structure. | `google_drive/client.py` |
| 8 | The vector index embeds **only the raw chunk text**. The file name is in the keyword index but not in the embeddings. | `indexing_service.py` line 214, `chunking_service.py` |
| 9 | Chunks are 3,500 characters with 500 overlap, never compared with alternatives. 573 of 1,469 chunks are at the size cap. | `chunking.py`; chunk length query |
| 10 | **Improving an extractor or the chunker does not re-process files already indexed.** A document counts as "current" if it is newer than the Drive file; chunks count as current if the text hash matches. No version stamp exists. | `ingestion_service._is_document_current`, `chunking_service._chunks_are_current` |
| 11 | The evaluation corpus has 22 synthetic `.txt` files and 33 public PDFs. **No DOCX, PPTX or XLSX, and no tables in the company files.** | `evaluation/corpus` |
| 12 | A full re-embed of the evaluation corpus (1,469 chunks, about 1.03M tokens) costs about $0.02 with `text-embedding-3-small` and $0.13 with `-3-large`. Cheap enough to test many chunking variants. | Chunk table size x OpenAI price page |

---

## 2. Stage A: reading real files properly

### 2.1 Design (kept simple on purpose)

**One idea: every extractor produces "light Markdown" text.** Headings as `#`, tables as `| a | b |` rows with a
header row, bullets as `- `, slides as `## Slide N: title`, speaker notes as `Notes:`, PDF pages separated by a
form-feed character. Why: the chunker and the rest of the system keep working on plain text with character offsets
(no schema change for the text itself, chunk text stays authoritative in PostgreSQL), and Stage B can cut at headings
and keep tables whole because the structure is visible in the text.

**Google formats reuse the Office readers.** Export Docs as DOCX, Slides as PPTX, Sheets as XLSX
(Google's export table: Docs also offer Markdown, Slides also plain text, Sheets CSV is **first sheet only**). Why:
one tested code path per format, no dependence on how Google formats tables. The documented export limit is 10 MB.

**Libraries** (all checked on PyPI today; licences are the reason PyMuPDF is excluded):

| Use | Library | Licence | Decision |
|---|---|---|---|
| PDF body text | `pypdf` (already used) | BSD-3 | keep |
| PDF ruled tables, page text on table pages | `pdfplumber` 0.11.10 (built on `pdfminer.six`) | MIT | add |
| DOCX | `python-docx` (already used) | MIT | keep, read tables and headings |
| PPTX | `python-pptx` | MIT | add |
| XLSX | `openpyxl` 3.1.5 | MIT | add |
| Test PDFs (dev only) | `reportlab` 5.1 | BSD | dev dependency |
| PyMuPDF / `pymupdf4llm` | | **AGPL** (network-service use needs source release or a paid licence) | **do not use** |
| Docling (IBM) | | MIT, but model-based and heavy (reports of 10 to 20 s per 10 pages on CPU) | **not now**; revisit only if borderless tables prove important |

### 2.2 What each format will do

| Format | Reads | Deliberate limits |
|---|---|---|
| **DOCX / Google Docs** | Body in order (paragraphs and tables interleaved), headings by style, bullet lists, tables as Markdown with first row as header, merged cells de-duplicated | Headers/footers skipped; text boxes, footnotes, comments and images not read; nested tables flattened |
| **PPTX / Google Slides** | Slides in order, title, text boxes sorted top-to-bottom then left-to-right, groups, tables, **speaker notes**, hidden slides flagged | Charts, SmartArt and images (no OCR) not read |
| **PDF** | Page text with **running headers, footers and bare page numbers removed**; page markers; **ruled** tables (lines drawn) as Markdown after a strict quality filter | **Borderless tables stay as flowing text** (documented limit); scanned pages empty (no OCR); password-protected PDFs fail as today |
| **XLSX / Google Sheets** | Every visible sheet as `## Sheet: name`, header row, rows as a Markdown table; computed values, not formulas; size caps with a "truncated" note | Charts, pivot tables, comments not read; very large sheets capped |
| **TXT, Markdown, CSV** | As text (`.md` and `.csv` added to the supported list; trivial) | |
| **Not supported** | Legacy `.doc/.ppt/.xls`, Google Drawings/Forms, scanned PDFs and images (OCR later) | |

**PDF table filter (from finding 3).** A detected table is used only if it has at least 2 rows and 2 columns, at
least 60% filled cells, is not a whole-page box, and its cell text is not just punctuation. Anything else is ignored
and the page falls back to flowing text. The thresholds are set on the test PDFs, not guessed.

**Header/footer removal (from finding 2).** A line that appears in the top or bottom two lines of at least 40% of
pages (document of at least 5 pages), or is a bare page number, is removed. Measured on the corpus PDFs before
and after.

**Pipeline version (from finding 10).** Add a small integer `pipeline_version` to documents (one migration) and to
chunk metadata. If it is older than the code's version, the file is re-extracted, re-chunked and re-embedded on the
next ingest. Without this, none of Stages A and B would reach files you have already indexed.

### 2.3 The five medium chunks of Stage A

| Chunk | Content | Done when |
|---|---|---|
| **A1** | Test fixtures and new questions. A script generates small, deterministic files in the company's story: `pricing_plans.docx` (heading, bullets, 3x4 table), `quarterly_review.pptx` (title, bullets, table slide, notes with a decision), `sales_2026.xlsx` (two sheets), `invoice_0457.pdf` (ruled line-item table, header and footer on 3 pages), `annual_report.pdf` (running header, a borderless table, a two-column section). About 30 new questions with exact answers (table lookup, row calculation, slide notes, header noise, two sheets), split between dev and test. Facts are new and do not contradict the existing files. Re-measure the old baseline once because the corpus changes. | Extraction tests with exact expected text are written and failing for today's code (proving the gaps) |

**A1 as built (2026-11-20):** five files in `backend/evaluation/corpus/messy/` (`customer_rollout_plan.docx`, `board_update_q3.pptx`, `sales_2026.xlsx`, `invoice_0457.pdf`, `annual_report_2025.pdf`), written by `evaluation/rag_eval/messy_fixtures.py` (byte-for-byte reproducible; `--check` verifies). The same content description is the ground truth, so the 39 new questions (`rag_v2_messy_cases.json`, 22 dev / 17 test, 5 "not in the documents") are validated without trusting our own readers. The messy set is **not** part of the default corpus, so the existing baseline numbers stay valid and no paid re-measurement is needed until the readers can read these files (measure once at the end of Stage A). Contract tests: `tests/known_issues/test_ki024_file_readers.py` (9 expected failures, 7 guards that pass today). Old note about a re-measure of the baseline is therefore moved to the end of A5.
| **A2** | DOCX reader (tables, headings, lists) + Google Docs exported as DOCX + `pipeline_version` migration and re-ingest rule | DOCX fixture tests pass; table question found by the probe; old cases unchanged |
| **A3** | PPTX reader (+ notes) + Google Slides as PPTX | PPTX fixture tests pass; notes-decision question found |
| **A4** | PDF: header/footer removal, page markers, ruled tables with the filter | Fixture tests pass; running header gone from at least 95% of pages on the corpus PDFs; no regression on the 33 old PDFs' cases |
| **A5** | XLSX + Google Sheets, `.md` and `.csv` as text | XLSX fixture tests pass; both-sheets question found |

### 2.4 How Stage A is judged

1. **Extraction tests** (free): exact expected text for every fixture, including edge cases (empty table, merged
   cells, a slide with no title, a one-page PDF, a PDF with no text). Each is broken on purpose once to prove it can fail.
2. **Retrieval probe** (about $0.01): new questions find the right file and the right passage; the old 56 dev + 33 test
   plain questions still find theirs.
3. **Agent run on the new questions only**, 2 repeats (about $0.08).
4. **Success target:** every ruled-table and DOCX/PPTX/XLSX fact present in the extracted text (100% of fixtures);
   new-question pass rate at least 90% on dev and test; zero regression on the old cases beyond noise.
5. **Time budget:** extraction under 10 s per 100 pages.

**Risks.** (a) Real PDFs are messier than fixtures, so the real-Drive test is the final judge. (b) Google Docs
exported as DOCX may carry its own quirks (needs one real Doc to confirm; fallback is Markdown export). (c) A bigger
corpus changes the old baseline: re-measure once.

---

## 3. Stage B: chunking

**Today:** 3,500 characters (about 875 tokens), 500 overlap, cut at paragraph, line or sentence; no headings, no
title in the embedding, tables not special.

**Evidence from research.** The sources disagree on the best size, so we test instead of copying:
a 36-strategy study (arXiv 2603.06976) found content-aware chunking beat naive fixed-size splitting, with
paragraph-group chunking best overall; blog benchmarks put recursive splitting at about 400 to 512 tokens with 10 to
20% overlap as a common default; the platform defaults differ (Bedrock about 300 tokens / 20%, Azure 512 / 25%,
Vertex 1,024 / 256); semantic chunking has mixed results and can produce tiny fragments (blog figures, unverified).
Anthropic reports that adding a short generated context to each chunk cut top-20 retrieval failures by 35%
(5.7% to 3.7%), and 49% with keyword search added, 67% with re-ranking on top.

**Candidates, tested in this order (each re-chunks and re-embeds into a separate test index, about $0.02):**

| # | Variant | Why |
|---|---|---|
| B0 | Today: 3500 / 500 | baseline |
| B1 | Size: 800, 1200, 1800, 2500 characters; overlap 0%, 10%, 15%, 20% | find the plateau |
| B2 | Structure-aware: cut at headings and paragraph groups, never inside a table; very large tables split by row groups with the **header row repeated** in each chunk | the research winner, and needs Stage A's Markdown |
| B3 | **Title context in the embedding**: embed `File: name / Section: heading / text` while storing only the clean text | Finding 8; cheap; helps "what does the travel policy say" |
| B4 | **Small-to-big**: search small chunks, give the model the chunk plus its neighbours (up to about 3,500 characters) | precision of small chunks, context of big ones; needs no new table |
| B5 | Generated context per chunk (Anthropic's method), tried only on a subset first | strongest reported gain but costs one model call per chunk at indexing, so it must prove its worth |

**Metric (stricter than today):** besides "right file in the 8 results", add **"the answer-bearing text is inside a
returned chunk"**, using the evidence quotes already in the dataset. Plus rank, number of distinct files, chunks per answer.

**Stop rule:** pick the simplest variant within noise of the best; B5 only if A to D misses the target.
**Cost:** about $0.14 embeddings + $0.05 to $0.10 for B5 on a subset + $0.05 agent confirm on about 15 cases.

---

## 4. Stage C: keyword search

**Today:** `websearch_to_tsquery` joins all question words with AND, so one unmatched word returns nothing (the
KI-022 cliff). Postgres's own ranking functions "do not use any global information" such as IDF, so common words
count as much as rare ones.

**Plan:**
1. Measure keyword-only recall on dev (free): how often the keyword path alone contains the right file.
2. Build an **any-word query** (OR of the content words), ranked so rarer words weigh more: weight each matched word
   by its inverse document frequency (we already count per-word file frequency for file-name matching), or re-score
   the top 100 OR-candidates with BM25 in the application. Pick by the probe.
3. Keep **exact matching for identifiers** (`INC-204`, `v1.3`, amounts) so they stay strict.
4. `pg_trgm` (typo and partial-ID tolerance) only if a measured miss needs it; extensions on Railway's Postgres are
   not verified.

**Done when:** keyword-only recall rises on dev and test, no loss in the combined result, and a long natural-language
question no longer returns an empty keyword list. **Cost:** about $0.02.

---

## 5. Stage D: ranking weights

**Today:** weights 0.5 vector, 0.3 keyword, 0.2 metadata; merge constant `k = 60`; each source's score is divided by
that source's best score in the list, so the top hit always gets full weight (no absolute quality signal).

**Plan:** a grid sweep (weights in steps of 0.1, `k` in 20/60/100, candidate pool 20/30/50) on the probe, with query
embeddings cached so the sweep is free and fast. Choose the centre of a **plateau**, not a lone peak (a peak is
usually noise), confirm on test. Also test whether the metadata "newest files" padding should keep a weight at all
(it helped in 1b).

**Done when:** a chosen setting that beats the baseline on dev and does not lose on test. **Cost:** about $0.01.

---

## 6. Stage E: the re-ranker

**What it is.** Search picks about 20 candidates cheaply; a re-ranker reads the question together with each candidate
and orders them by how well each answers it. More accurate than our current "combine three separate scores".

**Order of attempts (stop when the target is met):**
1. **E0, improve what we have (free).** Use absolute score signals instead of per-list max normalisation; a small
   bonus for passages that contain the question's numbers/names; the per-file cap from 1b stays.
2. **E1, LLM re-ranker with `gpt-5.4-nano`** (pointwise: each passage gets a 0 to 10 score as compact JSON; batches of
   about 10 run in parallel; low scores are dropped). This is the design a production team (Fin) reported at about
   +0.9 s median latency after optimisation. Pointwise beat listwise there (listwise added about 40% latency and 15% cost
   for no gain).
3. **E2, cross-encoder** (small local model or hosted service): **only** if E1 is clearly insufficient and you agree,
   because it adds a heavy dependency (local) or sends your text to another company (hosted).

**Cost per question (computed from OpenAI's price page):** 20 passages x about 875 tokens = 17.5k input tokens =
about **$0.0035 with nano** ($0.013 with mini); after Stage B's smaller chunks about half of that. Answering costs
about $0.003, so the re-ranker could roughly double the per-question cost. That is why it needs a measured gain.

**Evidence quality.** Vendor benchmarks put `gpt-4o-mini` re-ranking between plain embeddings (NDCG@10 0.618) and a
dedicated re-ranker (0.719), at 0.663. They are vendor numbers, not peer-reviewed, so they only justify *testing*.

**Adopt only if (on dev, confirmed on test):** the right passage ranks first clearly more often **and** added latency is
about +1.2 s or less at median **and** cost is about $0.005 per question or less. **Cost of testing:** about $0.40
(dev 90 questions about $0.15, test about $0.10, agent confirm about $0.10).

---

## 7. Stage F: the embedding model

**What a better embedding model gives.** An embedding turns text into numbers so that similar meaning sits close
together; the vector search depends on it. A stronger model finds paraphrases ("time off" for "annual leave") and
other languages (Roman Urdu) better, and separates relevant from irrelevant passages more cleanly, which makes
cut-offs and the re-ranker more reliable. **Costs:** larger vectors, more storage, a one-time re-embed, and a higher
price per token.

**Candidates:** `text-embedding-3-small` (today, 1536 dims, $0.02 per 1M tokens) vs `text-embedding-3-large`
(3072 dims, $0.13 per 1M; the `dimensions` option can shorten it). OpenAI's launch figures: multilingual (MIRACL)
44.0 to 54.9, English (MTEB) 62.3 to 64.6, so the gain is bigger for non-English. Test with the chunking chosen in B.

**Done when:** probe metrics (including the Roman Urdu cases) improve beyond noise on dev and test; otherwise keep
small. **Cost:** about $0.18 (re-embed $0.13 plus queries).

---

## 8. Steps 2 to 5 (after A to F), with changes from before

| Step | What | Change from the earlier plan |
|---|---|---|
| **2** | Force a search on document questions (`tool_choice="required"` on step one) | Same. Target: the 5 questions answered without any tool (`ca04`, `ca05`, three Roman Urdu) |
| **3** | Give the model each file's modified date; prefer the current version | Same |
| **4** | Extend the claim check: subject/scope errors, false "not in the files" claims, **and the 1d signal "does this answer assert document facts"** (drops citations and the "Sources consulted" footer on refusals) | 1d merged in |
| **5** | Test `gpt-5.4-mini` ($0.75 / $4.50 per 1M) against nano ($0.20 / $1.25) | Scope trimmed to the trap and multi-file cases; includes retrying "search one topic per call / search again", which nano ignored |

---

## 9. Decisions

Proceeding on my recommendation unless you say otherwise:
1. Google Docs, Slides, Sheets exported as DOCX, PPTX, XLSX (not Markdown).
2. One migration adding `pipeline_version` so improvements reach files already indexed.
3. Small generated test files (a few KB each) committed with their generator script.
4. New libraries: pdfplumber, python-pptx, openpyxl (runtime, MIT); reportlab (dev, BSD). No PyMuPDF, no Docling.

Needs your word:
5. **XLSX/Google Sheets in scope?** I recommend yes, last in Stage A, with size caps.
6. **Budget:** plan is about $3.3 against the $3.5 hard stop; Step 5 is the flexible part.

---

## 10. Caveats

- The code analysis is complete for ingestion, chunking, extraction and the indexing path; I did not re-read every
  service. Web research used primary sources where I could (Google, Anthropic, OpenAI, Postgres, PyPI, arXiv
  abstract) and secondary blogs elsewhere; vendor benchmarks are marked.
- The PDF experiments used 4 documents and 1 page for the table comparison: enough to reject "swap in a table
  library", not enough to claim a final threshold. Thresholds are set in A4 on the fixtures.
- Whether Google's DOCX export of a Doc preserves tables as expected is not yet verified against a real Doc.
- All costs and session counts are estimates. Stage E and Step 5 are the least certain.
- Results come from a small company-style corpus plus public PDFs. The real-Drive test remains the final judge.
- Retrieval changes are shared with the legacy pipeline, whose recorded baseline numbers will no longer reproduce.

## 11. Sources

- Google Drive export formats: https://developers.google.com/workspace/drive/api/guides/ref-export-formats
- Drive `files.export` (10 MB limit): https://developers.google.com/workspace/drive/api/reference/rest/v3/files/export
- Anthropic, Contextual Retrieval: https://www.anthropic.com/engineering/contextual-retrieval
- Chunking study (36 strategies): https://arxiv.org/abs/2603.06976
- pdfplumber: https://github.com/jsvine/pdfplumber (MIT); PyMuPDF licence: https://pymupdf.readthedocs.io/en/latest/about.html (AGPL / commercial)
- Postgres text search ranking: https://www.postgresql.org/docs/current/textsearch-controls.html
- OpenAI pricing: https://developers.openai.com/api/docs/pricing
- LLM re-ranking in production (Fin): https://fin.ai/research/using-llms-as-a-reranker-for-rag-a-practical-guide/
- LLM vs cross-encoder re-ranking (vendor benchmark): https://zeroentropy.dev/articles/should-you-use-llms-for-reranking-a-deep-dive-into-pointwise-listwise-and-cross-encoders
- OpenAI embedding v3 figures (via Pinecone): https://www.pinecone.io/learn/openai-embeddings-v3/
- PDF extractor comparison (blogs): https://unstract.com/blog/extract-tables-from-pdf-python/


## A2 as built (2026-11-20)

DOCX reader (`app/ingestion/extractors/docx.py`) returns light Markdown in document order: `Title`/`Heading N` styles become `#`..`######`; list items (paragraph numbering, or a list style such as "List Bullet", with numbering switched off honoured) become `- ` with two spaces per level; tables become `| a | b |` rows with a header row and separator; a merged cell keeps its text once and the cells it covers are empty; nested tables are flattened into their cell; `|` in a cell is escaped; empty tables are dropped; content controls are read. Headers, footers, text boxes, footnotes, comments and images are not read; numbered lists lose their numbers. Blocks are separated by a blank line (list items by a single newline), which is what the chunker prefers to cut at.

Google Docs are exported as DOCX; if Drive answers `exportSizeLimitExceeded` (about 10 MB, image-heavy documents) the plain-text export is used instead, so such a Doc is not turned into a failure. The reader is chosen by the type of the bytes actually received (`DriveFileContent.mime_type`), not by the Drive type; no extractor is registered for the Google Docs type any more.

`documents.pipeline_version` (migration `20261120_1200`, existing rows = 1; code constant `EXTRACTION_PIPELINE_VERSION = 2` in `app/ingestion/pipeline_version.py`). Indexed files whose document is older are listed by ingest and counted in `to_ingest` through one shared SQL condition (`app/services/ingestion_queries.py`), re-read once, and: identical text means only the version is stamped (file stays indexed, chunks untouched); different text means the normal path (file becomes INDEXING, then chunk and build). A failed re-read marks the file FAILED like any other failure.

Not verified yet: a real Google Doc exported as DOCX (needs a real Drive file; the fixture DOCX was made with python-docx, which is not the same producer).


## A3 as built (2026-11-20)

PPTX reader (`app/ingestion/extractors/pptx.py`): each slide with content is `## Slide N: title` (slide numbers count every slide, an empty slide is simply left out; no title gives `## Slide N`; hidden slides get ` (hidden)`). Content placeholders give `- ` bullets with two spaces per level; text boxes give plain paragraphs unless the paragraph has an explicit bullet; a bullet switched off wins. Shapes are read in reading order (top to bottom in 0.3 inch bands, left to right inside a band), groups are entered, tables become Markdown tables (merged cells keep their text once), speaker notes become one `Notes:` line after the slide. Footer, date and slide-number placeholders are skipped because they repeat on every slide. Not read: charts, SmartArt, pictures (no OCR), comments, animations.

Google Slides are exported as PPTX (same plain-text fallback as Docs when Drive reports `exportSizeLimitExceeded`). The export mapping is now one dictionary (`GOOGLE_EXPORT_MIME`), so Sheets in A5 is one new entry. Table and block formatting shared by the Office readers moved to `light_markdown.py` (DOCX uses it too). `python-pptx` moved from dev to runtime dependencies. Frontend: PowerPoint and Slides are in the single-file supported list, get a "Presentation" label and icon; spreadsheets are no longer mislabelled "Document". `EXTRACTION_PIPELINE_VERSION` is unchanged: no existing document was produced by a PPTX reader, so nothing is stale.

Discovery: an incremental sync only reports changed files, so decks that already sit in Drive are found by one full scan (`fullScan` in the app).

Not verified yet: a real PowerPoint or Google Slides export with unusual layouts (python-pptx built the test deck).


## A4 as built (2026-11-20)

PDF reader (`app/ingestion/extractors/pdf.py`, with `pdf_furniture.py` and `pdf_tables.py`). pypdf still produces the page text, now through one pass that also records where every text chunk sits; pdfplumber (MIT, new runtime dependency, which also brings `pdfminer.six` and `pypdfium2`) finds ruled tables.

- **Pages** are separated by a line holding only a form-feed character (`\f`); empty pages still count, trailing empty pages and a document with no text at all leave nothing. `normalize_extracted_text` was changed to keep such a line (plain `rstrip` erased it, which would also have shifted chunk offsets).
- **Headers and footers**: text in the top or bottom 8% of the page is a candidate. A bare page number ("3", "Page 3 of 12", "- 3 -") is removed on any document. A line that repeats (digits ignored) in the bands of at least 40% of the pages of a document of at least 5 pages is removed from every page except the first one it appears on (usually the title). Only band lines are removed, only as many times as seen on that page, so body text that repeats a header is kept; a header that pypdf splits over several lines is still matched.
- **Tables**: pdfplumber's detection is filtered (at least 2 rows and 2 columns after empty ones are dropped, at least 60% of cells containing a letter or digit, not a box covering more than 90% of the page in both directions, cells averaging at most 120 characters). An accepted table replaces the text chunks inside its box **only if** its characters and the replaced chunks' characters agree to 95% in both directions; otherwise the page keeps its flowing text. This check is what makes the replacement lossless, and it matters in practice: pypdf reports a wrong position for some chunks (on page 19 of NIST SP 800-146 a paragraph was placed inside a table's box), and without the check that paragraph would have been deleted. On the 33 public PDFs 62 tables were detected and 38 were used; the others stay flowing text. Tables are searched on the first 400 pages only.
- **Speed**: 8.5 s per 100 pages on the 8 GB Mac with other work running (the plan's limit is 10 s); about 7 s of it is pdfminer parsing the pages for tables. A cheap pre-check that skips pages without drawn lines was measured and rejected: it would skip only 9 to 20% of pages and misses tables drawn inside embedded form objects. Extraction already runs in a worker thread, so it does not block the API. Peak memory 290 MB.
- `EXTRACTION_PIPELINE_VERSION` is now 3: indexed PDFs are read again once on the next ingest.
- The three Financial summary anchors of cases vr02 and vr03 were quoted as pipe rows, which no reader can produce for a table without lines; they now quote the figures.

Known limits: tables without ruling lines stay flowing text (the report's Financial summary is one on purpose); a table whose position data is unreliable stays flowing text; rotated pages get no header removal and no tables; scanned pages have no text (OCR later); boxed callouts that look like two-column tables become small tables (their text is kept).

Not verified yet: PDFs from producers not in the corpus (the public PDFs are NIST and arXiv; the generated ones come from ReportLab), and the effect on answer quality (measured once at the end of Stage A with the messy question set).


## A5 as built (2026-11-20)

XLSX reader (`app/ingestion/extractors/xlsx.py`, shared table code in `tabular.py`): every **visible** sheet with content becomes `## Sheet: name` and a Markdown table; the first non-empty row is the header, blank rows and blank columns are dropped, values are what Excel last calculated (not formulas), floats are written without noise (`0.1 + 0.2` is `0.3`), dates as ISO dates, booleans as TRUE / FALSE, `|` and line breaks inside cells are made safe. Read with openpyxl in read-only streaming mode (now a runtime dependency; the stored "used range" is ignored because some writers get it wrong).

**Row cap and why these numbers.** A sheet keeps its header plus 1,000 data rows and 50 columns; a workbook keeps 5,000 data rows and 25 sheets; a cell keeps 500 characters; a file over 30 MB (or over 300 MB once unpacked) is refused with a clear error rather than half-read. Measured: 1,000 rows of five short columns come to about 53,000 characters, roughly 15 chunks of 3,500, so a full sheet is a normal-sized document and the workbook budget of 5,000 rows bounds what one file can add (about 75 chunks at that width; wider sheets add more). Questions about the data of a sheet longer than that cannot be answered from the index (they need a calculation over all rows, which retrieval cannot do) — so the reader **says so**: wherever a limit cut something, a `Note: only the first 1000 rows are indexed.` (or columns, or "sheets not indexed because of the size limit: ...") line stands under the table. A 200,000-row workbook is read in 0.03 s because only the capped rows are read.

**Google Sheets** are exported as XLSX (`GOOGLE_EXPORT_MIME`, one new entry). Sheets cannot export as plain text, so when Drive reports `exportSizeLimitExceeded` the fallback is CSV, which holds the **first sheet only** ([Google's export table](https://developers.google.com/workspace/drive/api/guides/ref-export-formats)); the new CSV reader (`csv_text.py`: delimiter detected among `, ; tab |`, same limits and notes) reads it, and also plain `.csv` files. `.md` files (`text/markdown`) are read as text. No pipeline-version change: no document was ever produced for these types.

Frontend: the single-file preparation supported list now includes Sheets, XLSX, CSV and Markdown (its test used Sheets as the example of an unsupported type; it now uses legacy `.xls`). Existing spreadsheets in Drive need one full scan to be discovered.

Not read, on purpose: hidden sheets, charts, pivot tables, images, comments, number formats (a percentage is `0.15`), a formula Excel never calculated (written by a script: left empty), encrypted files, legacy `.xls` / `.xlsm`. A merged cell keeps its text in its top-left cell.

Not verified yet: a real Google Sheet exported by Drive and an Excel file saved by Excel itself (fixtures were written by openpyxl; the stored-formula-result path was tested by patching the XML), and whether Drive reports `.csv` / `.md` uploads with exactly `text/csv` / `text/markdown` (other values would be skipped as unsupported).


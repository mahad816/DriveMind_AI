# Phase 4 Tracker — Document Ingestion & Text Extraction

Track milestone-by-milestone progress for Phase 4, with matching commit messages.

## Phase Goal

Convert supported Drive files into normalized plain text and persist extraction results in PostgreSQL, ready for chunking and embedding in Phase 5.

## Scope (MVP)

| File type | Method | Status |
|-----------|--------|--------|
| Google Docs | Drive export as `text/plain` (already in Phase 3) | Planned |
| TXT | UTF-8 decode with fallback | Planned |
| DOCX | `python-docx` paragraph extraction | Planned |
| PDF | `pypdf` text extraction **only** (born-digital PDFs) | Planned |
| Images (PNG, JPEG, WebP, GIF, TIFF, BMP) | Tesseract OCR via `pytesseract` | Planned |

## Explicitly Out of Scope (Phase 4)

| Item | Reason |
|------|--------|
| **EasyOCR** | Heavy ML stack; Tesseract is sufficient for MVP |
| **PDF OCR fallback** | Scanned PDFs need page rasterization + poppler; deferred to a later phase |
| **OCR inside DOCX embedded images** | Rare edge case; not worth MVP complexity |
| **Google Sheets / Slides / Excel** | Not in supported MIME types |
| **Audio (Whisper)** | Deferred per project rules |
| **Chunking & embeddings** | Phase 5 |

### Known limitation

Scanned or image-only PDFs may return little or no extractable text in Phase 4. These files will be marked accordingly; full PDF OCR can be added in a future phase if needed.

## Current Snapshot

- **Phase status:** In progress
- **Last completed milestone:** Milestone 1 (extraction foundation)
- **Next milestone:** Milestone 2 (TXT + Google Docs extractors)
- **Blocker:** None

## Your Action Items (manual setup)

Complete before the image OCR milestone (Milestone 5):

- [ ] **Step A — Tesseract** — install system OCR engine:
  ```bash
  brew install tesseract
  tesseract --version
  ```
- [ ] **Step B — Postgres + migrations** — ensure DB is up and migrations applied:
  ```bash
  docker compose -f infra/docker-compose.yml up -d postgres
  cd backend && uv run alembic upgrade head
  ```
- [ ] **Step C — Drive connected** — OAuth complete and metadata synced (`POST /api/v1/index/sync`)

Steps A–C are not required for Milestones 0–4 (no OCR yet).

## Milestone Status

- [x] Milestone 0 — Phase 4 tracker + setup checklist + docs alignment
- [x] Milestone 1 — Extraction foundation (deps, protocol, registry, hash util, `documents.extracted_text` migration)
- [ ] Milestone 2 — TXT + Google Docs plain-text extractors
- [ ] Milestone 3 — PDF text-only extractor (`pypdf`)
- [ ] Milestone 4 — DOCX extractor (`python-docx`)
- [ ] Milestone 5 — Image OCR extractor (Tesseract / `pytesseract`)
- [ ] Milestone 6 — `IngestionService` orchestration + ingest API + phase closure

## Commit Plan

1. `docs(ingestion): add phase 4 tracker and scope alignment`
2. `feat(ingestion): add extraction foundation and document text storage`
3. `feat(ingestion): add plain text and google docs extractors`
4. `feat(ingestion): add pdf text-only extractor`
5. `feat(ingestion): add docx text extractor`
6. `feat(ingestion): add image ocr extractor with tesseract`
7. `feat(ingestion): add ingestion service and ingest api`

## Target Module Layout

```text
backend/app/ingestion/
  extractors/
    __init__.py          # registry: mime -> extractor
    base.py              # Extractor protocol + result type
    plain_text.py        # TXT + Google Docs export bytes
    pdf.py               # pypdf text-only
    docx.py              # python-docx
    image_ocr.py         # pytesseract
  hash_util.py           # extracted_text_hash helper
  ingestion_service.py   # orchestrates DriveContentService + extractors + DB

backend/app/api/index.py # POST /api/v1/index/ingest (Milestone 6)
```

## Dependencies (Milestone 1)

Python packages (via `uv add`):

- `pypdf` — PDF text extraction
- `python-docx` — DOCX parsing
- `pillow` — image loading for OCR
- `pytesseract` — Tesseract bindings

System package (manual, before Milestone 5):

- `tesseract` — via Homebrew on macOS

## Verification Commands (per milestone)

```bash
cd backend
uv sync --dev
uv run ruff check app tests
uv run mypy app
uv run basedpyright app tests
uv run pytest -q
```

## Notes

- Reuse `DriveContentService` from Phase 3 — extractors receive bytes, not Drive API calls.
- Store full extracted text on `documents` (new column in M1); chunking splits it in Phase 5.
- Idempotent ingestion: skip or update when `extracted_text_hash` matches Drive file `modified_at` / content hash.
- Image OCR quality varies (screenshots OK; handwriting poor). English Tesseract default is fine for MVP.

# DriveMind Backend

FastAPI backend for DriveMind AI — ingestion (text extraction), hybrid retrieval, and LangGraph agent.

Phase 4 adds extractors under `app/ingestion/extractors/` (TXT, Docs, DOCX, PDF text-only, image OCR). See [PHASE_4_TRACKER.md](../docs/PHASE_4_TRACKER.md).

Phase 5 adds chunking, embeddings, and Qdrant under `app/ingestion/chunking.py`, `app/embeddings/`, and `app/services/indexing_service.py`. See [PHASE_5_TRACKER.md](../docs/PHASE_5_TRACKER.md).

## System dependencies (Phase 4 image OCR)

Image OCR uses `pytesseract`, which requires the **Tesseract** binary on your `PATH`:

```bash
brew install tesseract
tesseract --version
```

Python packages (`pillow`, `pytesseract`) are installed via `uv sync`. No extra `.env` variable is required when Tesseract is on `PATH`.

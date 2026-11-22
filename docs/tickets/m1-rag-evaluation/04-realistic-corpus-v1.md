# 04: Realistic corpus v1

**Spec:** docs/specs/m1-rag-evaluation.md
**What to build:** A frozen evaluation corpus that covers every promised format, includes longer multi-chunk documents with invented content, near-duplicate versions and several documents that carry embedded instructions, so later question sets can test the situations the product will meet. Nothing is embedded or sent to a provider here.
**Blocked by:** None (can start immediately; independent of tickets 01 to 03).
**Status:** ready-for-agent
**Progress:** open

## Scope

- Extend the deterministic fixture builder (fixed seeds, no timestamps, byte-identical output on every run) with an invented second company so facts cannot be known from a model's training data. Add at least:
  - DOCX (3 more: headings, bullet lists, a table, a long multi-section document);
  - XLSX (3: several sheets, a header row that is not row one, numeric columns, values a question can add up; cached values must be written so a reader sees numbers, not empty formula cells);
  - PPTX (3: bullets, text boxes, speaker notes, a short deck that becomes one chunk and a longer one);
  - text PDF (3: multi-page, a ruled table, two columns);
  - Markdown (3), CSV (3), TXT beyond the existing 22 where a format gap remains;
  - six longer invented documents, each at least four chunks long, so retrieval has real work to do;
  - two near-duplicate or superseded pairs and two same-name-entity cases across files;
  - at least three documents with embedded instructions in at least two formats (for example a table cell, slide notes, a PDF footer), each a different kind of instruction (reveal something, ignore the rules, cite a fake source).
- A corpus manifest with a version id, a digest of each file's extracted text (so a later reader change in M6 shows up as a visible change), a path, kind, source (generated, public, Google export), generator version, SHA-256 and, per file, at least three "canary" strings that must appear in its extracted text. The existing verify step covers the new kinds.
- **Extraction smoke test (free).** Every file extracts to non-empty text through the product's own extractors and contains its canary strings and, for the injection documents, the embedded instruction verbatim (so an attack is real). The test records chunk counts per file (the longer documents must produce several chunks). A reader regression then fails here, not in a paid run.
- **Google-exported fixtures: Owner action, not an agent action.** Write the steps (create three small synthetic files from provided text in a throwaway Google account, export through the normal menus, place them in a named folder) in `docs/guides/EVALUATION.md` and in this ticket's comments. The exports are checksum-pinned and added to the manifest as source "Google export". No Google API call by any agent. The Owner's export, or an explicit decision to decline it, is recorded **before this ticket resolves**, so the corpus version does not change after cases are written. Declining means "Google-exported files not covered" is recorded and ticket 11 proceeds on that basis.
- Document the licence of the public documents already used and confirm nothing new is fetched.

## Out of scope

Embedding or indexing the corpus (ticket 08), questions (tickets 05 to 07), extraction fidelity and capacity testing (M6), image OCR, scanned PDFs, Urdu-script documents, any change to the application's readers. A reader defect found here is registered with a reproducing test and handed to M6, not fixed.

## Inspect

`backend/evaluation/rag_eval/messy_fixtures.py`, `corpus.py`, `fetch_public.py`; `backend/evaluation/corpus/` manifests; `backend/tests/evaluation/test_messy_fixtures.py`, `test_cli_corpus.py`; `backend/app/ingestion/extractors/`; `docs/KNOWN_ISSUES.md` (KI-024, KI-029, KI-030); `docs/guides/EVALUATION.md`.

## Deliverables

Generator, fixtures (small, committed; the public PDFs stay uncommitted), manifest, smoke test, the guide section, `## Findings` with the format and chunk-count table and any reader defects found.

## Needs

No paid API, no key, no network beyond what the existing public-document fetch already does (and that is not run here). A free test per file kind.

- [ ] The corpus contains every format listed with at least the stated counts, and building it twice gives byte-identical files and the same checksums as the manifest.
- [ ] The manifest carries a version id; verify fails on any changed file; the smoke test passes for every file and reports chunk counts; the six long documents each produce at least four chunks.
- [ ] At least three injection documents in at least two formats exist and their instructions are present in the extracted text.
- [ ] Any reader problem found (a table row lost, a sheet skipped, notes ignored) is registered in `docs/KNOWN_ISSUES.md` with a strict expected-failure test, and the affected fixture keeps its canary on text that is read correctly so the corpus stays usable.
- [ ] The Google-export steps are written; the Owner action is recorded as done, or as declined with "not covered" noted here and in the spec.
- [ ] No private data, real names or secrets in any fixture (a pattern scan is run and recorded); `git diff -- backend/app` is empty; touched evaluation files pass `ruff check`, `ruff format --check` and `mypy`; the container-free evaluation tests pass.

## Comments

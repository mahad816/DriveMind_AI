# 06: New development cases

**Spec:** docs/specs/m1-rag-evaluation.md
**What to build:** New questions, written from the corpus documents and never from system output, that fill every gap in the coverage minimums that does not belong in the held-out pool.
**Blocked by:** 05.
**Status:** ready-for-agent
**Progress:** open

## Scope

- Write development cases (about 60 to 80; the exact number is what the coverage report needs after leaving the held-out share to ticket 07) with a verbatim anchor quote per fact, a reference answer and a forbidden-claim list each, **without running the system or reading any run result**. Cover what the existing set lacks: Critical-failure cases (a named document that does not exist next to a similar one that does; same-name entities; injection across the new documents and formats; content attributable to the wrong file); ambiguous questions; follow-ups with histories inside the production bound; calculations and table lookups on the new XLSX, DOCX and CSV files; multi-file questions; identifier questions on the new documents; at least eight questions per promised format across development and regression together.
- Prefer the invented second company and the long invented documents. Keep Roman Urdu cases as they are; add none.
- Record provenance (session and date). Freeze the new file in the freeze manifest.

## Out of scope

Held-out cases (ticket 07), running the system, changing any existing case, scoring, the application package.

## Inspect

Ticket 05's coverage report and `## Findings`; the corpus manifest and documents (ticket 04); `docs/KNOWN_ISSUES.md` (KI-022 to KI-030, for the shapes to cover); `GLOSSARY.md` (Critical failure); the v1 spec's required question types.

## Deliverables

New development case file(s), updated freeze manifest, `## Findings` with the coverage table after this ticket and the authoring rules used.

## Needs

No paid API, no key, no network.

- [ ] Every new case passes the validator (anchors verbatim in extracted text, forbidden claims absent from the corpus, histories inside the bound).
- [ ] After this ticket, every full-set minimum that does not depend on the held-out pool is met by development plus regression together; any shortfall is listed with its size in Findings.
- [ ] No new case was derived from a system output and no result file was opened (stated in provenance and Findings).
- [ ] The freeze manifest includes the new file; the freeze test passes.
- [ ] `git diff -- backend/app` is empty; touched evaluation files pass `ruff check`, `ruff format --check` and `mypy`; the container-free evaluation tests pass.

## Comments

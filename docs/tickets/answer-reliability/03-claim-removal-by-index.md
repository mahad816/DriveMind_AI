# 03: Claim-check removal by statement index (ticket C, resolves KI-035 pending review)

**Spec:** docs/specs/m1-rag-evaluation.md (Owner-approved exception: docs/DECISIONS.md, "2026-11-24 — Narrow M1 exception for three targeted answer-reliability fixes")
**What to build:** a statement the checker flags is actually removed, and only that statement, using the same statement units the checker was shown.
**Blocked by:** None
**Status:** ready-for-human
**Progress:** claimed
**Risk:** high (production answer path)

## Cause (KI-035)

Extraction used `split_statements` (a bare list number is glued onto the following sentence); removal compared the flagged text against `sentences(line)` (list number apart) and dropped every statement with equal text; the count was `len(flagged)`.

## What changed

`backend/app/agents/tool_rag/claim_check.py`: `_line_pieces` is now the one place that decides boundaries (used by `split_statements` and by removal); `enforce_claims` walks the lines in the same order, maps flagged indexes to lines, and `_rebuild_line` drops exactly those units. A bullet or list number of a dropped first statement moves to the next survivor; unflagged lines are kept as they were; `removed` and the log count are the number of units actually dropped. Whole-answer replacement (`nothing_left`) and the marker-only rule are unchanged.

## Tests

- `tests/known_issues/test_ki035_claim_check_numbered_removal.py`: the two strict expected failures are now ordinary passing tests (markers removed), the three guards unchanged.
- New `tests/agents/tool_rag/test_claim_removal_and_premises.py`: numbered lines, list-number carry, bullets, several sentences on one line, repeated statements (only the flagged copy goes; two flagged count twice), citation markers, Markdown headings and blank lines, colon lead-in items, count equals observed removal and the log line, whole-answer replacement, unchanged inner text. 10 of its 19 tests fail on the old code (verified by restoring it temporarily).
- `tests/evaluation/test_claim_check_trace.py`: two tests pinned the old defect (flagged numbered statement stays; unflagged repeated copy is also dropped). Rewritten to the corrected behaviour; the trace still records `uncertain` where text alone cannot attribute a change. Historical result files are untouched.

## Acceptance

- [x] Reproducing tests pass; neighbouring behaviour guarded.
- [ ] KI-035 is **not** marked Fixed until the independent review supports closure (registry entry says so).

## Comments

- 2026-11-24: implemented.

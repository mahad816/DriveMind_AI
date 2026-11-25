# 01: Claim check, citation and finalization corrections

**Spec:** docs/specs/backend-stabilization.md (Owner-approved exception: docs/DECISIONS.md, "Backend stabilization checkpoint")
**What to build:** a supported statement keeps its citation, a factual lead-in is checked, a document named as a source is checked, the answer is not padded with every retrieved file after its own citations were removed, and the remaining KI-035 list-marker edge cases are correct.
**Blocked by:** None (can start immediately)
**Status:** ready-for-agent
**Progress:** claimed
**Risk:** standard (answer path; no authorization or data-isolation code touched)

## Scope and exclusions

In: `claim_check.py` (statements, framing, removal, prompt), `finalization.py` and `graph.py` (footer), `evaluation/rag_eval/planted_claims.py` (two absence variants, `--ids`). Out: retrieval, models, defaults, fail-closed claim check (M3), streaming, frontend, any paid call.

- [ ] A citation-only line is not a statement; it is kept while any text of its paragraph survives and dropped with it otherwise; it never moves to another paragraph.
- [ ] Only a label of at most two words ending in a colon is framing.
- [ ] The prompt separates "not stated in the documents" from "there is no X", makes a named source document a material assertion, and treats a source-naming lead-in as a claim (structure only; behaviour is ticket 03).
- [ ] No "Sources consulted" list when the model cited and the check removed all of it; unchanged for a draft with no markers.
- [ ] `+`, `•`, `>` markers move to the surviving statement; every piece of an indented line keeps its indent.
- [ ] `planted_claims` builds the two absence variants and accepts `--ids`, builds controls from development cases only, and refuses any other id.
- [ ] When every item under a lead-in is removed: a meaningful lead-in survives as a sentence (no dangling colon, its own citation kept, the marker line of the removed items dropped), a structural heading or boilerplate lead-in is dropped, a heading with all content removed leaves no answer; a partly surviving list keeps its lead-in, colon and surviving items; numbers are not lost or duplicated; a blank line before the list, a loose list and a heading's section are handled and a plain paragraph after a list is never swept in (`tests/agents/tool_rag/test_claim_check_lead_ins.py`).
- [ ] A file name or source label is never evidence (also when the name contains brackets, parentheses or a newline): a word in a label does not ground a lead-in and a number only in a label is reported as absent, while the checker still receives the labels (`tests/agents/tool_rag/test_claim_check_source_labels.py`, `test_claim_check_contract.py`).
- [ ] A heading is `#` and a space only; `#1 priority`, `#123` and `Ticket #5` are facts (one function, `_heading_level`). The contract in `docs/specs/backend-stabilization.md` ("Claim-check contract") is covered by `tests/agents/tool_rag/test_claim_check_contract.py`, including an invariant over one to three of eight answer blocks (92 of 255 combinations, fixed order), a lead-in sharing its line with removed items while a later list line survives (P2-1), and a lead-in whose plain paragraph was removed (P2-2); 14 deliberate faults in `claim_check.py` were each caught by the claim-check tests (scratchpad mutation run, not stored in Git).

## Failure scenarios considered

Answer starting with a marker line (markers read as placed before their text: each follows the text below it); marker line after a blank line (belongs to the text above); two paragraphs each with its own marker (never swapped); every statement flagged (empty text, nothing-left signal); only headings, lead-ins and citation lines left (empty answer, the dropped lead-ins counted); checker unusable (answer unchanged); numbered line `1. [source_1] Text` (unchanged old behaviour, deliberately not treated as citation-only).

## Comments

- 2026-11-24: claimed. Red first: 20 of the first 36 new tests failed on the base code, 16 were guards; after review round 1 nine more tests were written red first and failed; after round 2 two more (a supported sentence before a trailing lead-in; a citation sharing text with one). Tests: `backend/tests/agents/tool_rag/test_claim_check_stabilization.py`, `backend/tests/evaluation/test_planted_claims_absence_variants.py`.

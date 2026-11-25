# Backend stabilization checkpoint (before product UX/UI)

Status: ready-for-agent

Owner-approved bounded checkpoint, 2026-11-24. Decision and limits: `docs/DECISIONS.md` ("Backend stabilization checkpoint"). It extends the narrow M1 exception to the confirmed defects below; it does not reopen M1, authorize paid calls, change retrieval ranking, models, thresholds or code defaults, or claim production accuracy. Tickets: `docs/tickets/backend-stabilization/`.

## Problem Statement

The answer path (tool agent, claim check, citation finalization) still fails in ways the Owner can see in saved evidence: a supported "not stated" statement is removed (cc07); a bare citation line is removed as a "claim" and the answer then lists every retrieved file as "Sources consulted" (nm07 run 2); a factual lead-in survives because it ends in a colon; a correct value is attributed to the wrong document (nm07). And on the Owner's Mac the improved paths (C2-cap3, the claim check, the false-premise prompt, the KI-034 note) were not even active: the local settings run the legacy answer path.

## Solution

Small, independently tested corrections in `claim_check.py`, `finalization.py` and `graph.py`; a local-only launcher that turns on the tool agent and C2-cap3; one startup log line; absence controls added to the existing `planted_claims` harness; documentation; one prepared (not authorized) real-model validation.

## User stories

- As the Owner, a supported statement that says the documents do not give a value stays in the answer, and an invented value or a claim that the thing does not exist still goes.
- As the Owner, a citation survives with the text it cites and disappears only with text that was removed.
- As the Owner, a sentence that names a document as the source of a fact is checked like any other fact.
- As a developer, I can start the backend so that C2-cap3 is on, see the effective flags in the log, and turn it off with one variable.

## Implementation decisions

- One prompt (the existing claim checker), no new model call; deterministic changes only where the structure, not the meaning, is wrong.
- A citation-only line is not a statement: it is not shown to the checker and not numbered; it is kept while any text of its own paragraph survives and dropped with it otherwise.
- A trailing colon no longer exempts a statement: only a label of at most two words ("Key findings:") is framing. When every item a lead-in introduced is removed, a meaningful lead-in survives as a closed sentence and a structural one is dropped (decided from the passages' text, not their file-name labels, no extra call; items are found as markdown structure, across blank lines and under headings; KNOWN_ISSUES SC-5).
- The "Sources consulted" list is not appended when the model did cite and the claim check removed all of that cited text. It is kept for an answer the model wrote with no markers at all (see Known limits).
- Local activation uses environment variables set by `scripts/dev-backend.sh`; `backend/.env` is never read or edited, code defaults and remote settings are unchanged.

## Per-issue audit (Phase 0 result)

| # | Issue | Existing implementation | Observed defect and evidence | Root cause | Smallest complete solution | Regression test | Acceptance |
|---|---|---|---|---|---|---|---|
| 2 | Qualified absence removed (cc07) | Checker prompt already exempted "not in the documents" | `cc07` draft "Refrigerant supplier: Not stated in the indexed documents I found (...)" flagged `S2` in both repeats; the corpus never mentions a refrigerant, so the statement was true | Model-side; not established beyond that (evidence was truncated by duplicate chunks, 27,738 > 24,000 characters, but the cut part is unrelated). Not reproducible without a model | Prompt: what the passages lack is judged apart from what is true; "there is no X / never had X" stays flaggable | `test_claim_check_stabilization.py` prompt structure tests (structure only) | Real-model validation (ticket 03): `cc07` keeps the line in both runs; `planted_claims` absence controls |
| 3 | Standalone `[source_N]` removed (nm07 run 2) | `split_statements` numbered every line, including a bare marker | `S5 = "[source_6]"` flagged and removed; the only inline citation lost; `Sources consulted` then listed 8 files | Deterministic: a marker line is not an assertion | a line that is only protocol or numeric markers is not a statement; orphan pass in `enforce_claims` | 9 tests (kept, dropped with its text, never moves paragraph, blank-line case, leading marker) | Free tests green; nm07 run shows a citation next to the text |
| 4 | Factual lead-in exempt by colon (nm07 run 2) | `is_framing`: ends with ":" | Checker flagged `S1` (lead-in naming the handbook); `framing_ignored` removed the flag | Structural exemption broader than "heading" | Only a label of up to two words is framing | `test_only_a_short_label_is_framing_a_colon_alone_is_not` (9 cases), flagged-lead-in test | Free tests green |
| 5 | Wrong document as the source (nm07) | Evidence labelled by file name; checker ignored attribution | The 36-hour rule is in the customs guide only; both runs say "driver handbook"; run 1 checker returned `[]` | Not a mapping defect: the marker `[source_6]` resolves to the customs guide, the evidence label and the citation payload are correct. The model misattributed in the draft; the checker had no instruction to treat attribution as a claim, and in run 2 the framing filter overrode its flag | Prompt: naming a document as the origin is a material assertion; a value found only in another document does not support it | Prompt structure tests; nm07-shaped graph test | Real-model validation: `nm07` final does not attribute the value to the handbook, in both runs. **Not claimed fixed** |
| 6 | Generic refusal plus irrelevant "Sources consulted" | `finalize_answer` appends every retrieved file when no marker survives | nm07 run 2 (8 files); historical 6 of 22 refusal-type answers (`docs/EVALUATION_RESULTS.md`) | When the model's own markers were removed, the fallback ignored that it had cited | `consulted_footer=False` when the model cited and the check removed it all | 3 graph tests (no footer; uncited draft keeps it; surviving cited statement keeps its citation) | Free tests green. **Not fixed:** a model-written refusal with no markers still gets the list |
| 7 | KI-035 remaining edge cases | Removal by statement index; bullet `-`/`*` and numbers carried | `+`, `•`, `>` markers lost; second piece of an indented lead-in lost its indent | Prefix regex and join | Extend the prefix regex; indent every piece | parametrized marker test, indent test, repeated-statement test | Free tests green |
| 8 | Missing entities (KI-028), `px03` cutoff, KI-034 | Open (see `docs/KNOWN_ISSUES.md`) | KI-028 `id19`, `dx08`; `px03` rank-8 displaced by the merge | Model behaviour (KI-028); retrieval cutoff (px03) | None beyond item 5's attribution wording; no new retrieval variant | n/a | All three stay open; evidence preserved |
| 9 | Streaming vs final answer | Provisional draft text streamed, labelled "Unverified"; `validating` clears it; the published answer comes only from the terminal receipt | No deterministic defect: removed text cannot survive completion | n/a | None | existing `test_chat_streaming.py` | Product decision for the UX phase |
| 1 | Local activation | `RETRIEVAL_DUAL_QUERY_ENABLED` default false; local settings had the tool agent off | Flag alone would be a no-op locally | Configuration, not code | `scripts/dev-backend.sh`, `effective_config` log | `test_startup_config_log.py`, `test_c2_http_path.py` | Effective flags printed from the real `Settings` class under the launcher's variables; HTTP-level test runs both searches |

## Claim-check lifecycle and contract (final audit, 2026-11-25)

**Flow** (`graph.finalize`, then `finalization`):

| Step | Owner | Receives, returns | Deterministic? |
|---|---|---|---|
| Evidence text | `claim_check.evidence_text` + `section_label` | retrieved sections; `[file name]` line + passage text per section | yes |
| Evidence body | `claim_check.evidence_body` | labelled text; the same without the label lines (the only way code treats evidence as proof) | yes |
| Statements | `_line_pieces` / `split_statements` | answer; numbered statements (citation-only lines are not statements) | yes |
| Structure | `_heading_level`, `_items_of`, `_is_lead_in`, `_tidy_*`, `_drop_orphan_citation_lines` | lines; what a heading or lead-in introduces, which lines are structural | yes |
| Prompt and call | `build_user_message`, `find_unsupported` | labelled evidence, statements, number hints; flagged indexes or `None` | **the only model call** |
| Parse | `parse_unsupported`, `is_framing` | JSON; indexes (framing flags dropped) | yes |
| Removal | `enforce_claims`, `_rebuild_line` | flagged indexes; text without those statements, same statement identities | yes |
| Tidy | `_tidy_orphan_lead_ins`, `_drop_orphan_citation_lines` | text after removal; closed or dropped lead-ins, orphan marker lines | yes |
| Fallback | `enforce_claims` end, `graph.finalize` | nothing meaningful left gives the fixed no-evidence reply | yes |
| Citations | `finalize_answer`, `normalize_answer_citations` | `[source_N]` to `[n]` in first-reference order; only cited sources returned; footer only when the model wrote no marker | yes |
| Trace | `claim_trace` | what happened, read from the text before and after | yes |

**One implementation per notion.** A heading is recognised only by `_heading_level` (`#` then a space; `#1 priority` is a fact). A statement boundary only by `_line_pieces`. The evidence label's format (`section_label`) and its parser (`_SECTION_LABEL`, `evidence_body`) live next to each other, so no file name can break the pairing (tested with brackets, parentheses, newlines). A list prefix is not a word of a label in either `is_framing` or `_is_lead_in`.

**Contract** (every line is a test in `test_claim_check_contract.py`, `test_claim_check_lead_ins.py`, `test_claim_check_source_labels.py`, `test_claim_check_stabilization.py`):
- *Evidence:* only a passage's text supports a claim; the label stays visible to the checker (attribution, citation mapping) but is never grounding or a source of numbers.
- *Structure:* headings, factual lines that start with `#`, bullets of every marker, numbered and nested lists, loose lists, blank-line sections, inline and standalone citations are told apart.
- *Removal:* flagged statements go by position (repeats keep their identity); supported statements, meaningful lead-ins (closed: colon or semicolon becomes a full stop) and unrelated paragraphs stay; a structural heading or boilerplate lead-in whose items are all gone is dropped; no flagged text survives, no unflagged supported text is lost and no answer ends in a dangling colon or semicolon (checked over every combination of one to three of eight answer blocks, in a fixed order: 92 of the 255 possible combinations; the earlier six-block version covered 41 of 63). A colon or semicolon lead-in owns the list under it, or, with no list, the plain paragraph after it (a heading is never part of it); a lead-in sharing its line with removed numbered items keeps its colon while a later list line survives.
- *Citations:* a marker stays with the text it follows (or follows, for an answer that starts with a marker), goes with removed text, and surviving markers renumber; no footer after the model's own citations were removed.
- *Fallback:* the no-evidence reply only when nothing meaningful remains; every failure of the check (timeout, provider error, malformed or out-of-range reply, empty evidence, too many statements) leaves the answer as written.
- *Not changed:* model, timeouts, evidence budget (24,000 characters), statement cap, retrieval, authorization, metering; no new model call.

**Remaining failure modes (not fixed; see `docs/KNOWN_ISSUES.md` SC-3, SC-5, SC-7):** the checker may misjudge (no real-model evidence for the prompt changes); the meaningful-versus-structural split is lexical; a refusal the model writes without markers still gets the footer; evidence over the budget is cut; a bracket-only line inside a passage is also stripped from the grounding text (conservative); a closed lead-in cannot be attributed by the trace; a lead-in followed by two or more paragraphs owns only the first.

## Testing decisions

Test observable behaviour through the existing interfaces (`enforce_claims`, the graph via `run_with`, the HTTP route via the existing `api` harness); the checker's model is a scripted JSON reply, so tests prove what the code does with a verdict, never that a model gives it. Model behaviour is validated only by ticket 03.

## Out of scope

Retrieval ranking or new merge variants, models, thresholds, code defaults, Railway, the frozen index, held-out data, streaming redesign, frontend changes, fail-closed claim check (M3), M1-09 to M1-13 and held-out acceptance, the production C2 decision.

## Further notes

Known limits and unresolved items are in `docs/KNOWN_ISSUES.md` ("Found by the backend stabilization checkpoint") and the final report of ticket 01. Frontend handoff: `docs/guides/FRONTEND_UX_HANDOFF.md`.

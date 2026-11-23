# 01: Once-only corrective search turn when the first agent step calls no tool

**Spec:** none (the `drivemind-engineering` workflow skips a spec for one scoped fix). Evidence: `docs/EVALUATION_RESULTS.md` section "M1-08-G", `docs/KNOWN_ISSUES.md` KI-034, `docs/tickets/m1-rag-evaluation/08-retrieval-measurement-on-the-new-corpus.md`. The file name says "fallback" because the first proposal was a server-run search; the chosen strategy below is a corrective instruction. Renaming the file is optional and left to the Owner.
**What to build:** When a run's first model step answers in prose without calling any tool, and the run has no history, no tool call and no evidence, the agent graph gives the model **one** extra turn with a fixed server-written instruction to call `search_knowledge` if the question needs the user's documents. The model decides. If it searches, the normal evidence, citation and claim-check path applies; if it does not, the reply is the same fixed `NO_CONTENT` text as today. The model's skipped prose is never shown.
**Blocked by:** None (can start immediately). Does not close M1-08; its other acceptance criteria stay in ticket 08.
**Status:** ready-for-agent
**Progress:** claimed (mechanism implemented 2026-11-24, review and commit decision pending; not resolved: see "Completion criteria")
**Risk:** standard (agent control flow only; no change to authentication, ownership filters, retrieval, held-out data, spending limits or infrastructure). It becomes **high** if the implementation touches the tool executor's ownership checks.

## Confirmed problem and hypotheses

Registered as **KI-034**. Its reproducing test, `backend/tests/known_issues/test_ki034_no_tool_first_step.py`, started as a strict expected failure; the marker was removed when the mechanism landed (a test that unexpectedly passes must not stay marked as failing). It is now 5 ordinary passing tests: the mechanism case plus 4 guards (a greeting, a follow-up with history, `max_cycles` 1 and 2 get no extra turn). KI-034 stays **Open** and has no expected-failure marker; see the registry-convention note in `docs/KNOWN_ISSUES.md`.

- **Confirmed (frozen first-step files, development and regression pools only):** 8 observations, 4 cases, called no tool in both repeats: `ca05`, `ru05` (development), `ca04`, `ru02` (regression). Searching with the plain question found the right file at rank 1, 1, 2, 1.
- **Confirmed (code and existing tests):** such a step ends in the fixed `NO_CONTENT` reply (`finalization.finalize_answer` -> `provenance_response` -> `without_content`); only exact social phrases get their short reply. The model's prose is never shown and the run never retries.
- **Hypotheses (not claimed):** why the model skipped the tool (its text was not stored); whether one more instruction makes it search; whether `ca04` (arithmetic on numbers the user typed) passes the intent gate at all (the gate prompt lists "solve math" as out of scope; a model call, unverified); whether held-out has more such cases (not read).
- **Not measured:** answer accuracy. The first-step experiment ends after the first model call and cannot see this change at all.

## Strategy decision (three candidates, one chosen)

| | 1. Conditional server-run search | **2. Once-only corrective instruction (chosen)** | 3. Tool required on the first step |
|---|---|---|---|
| Mechanism | Server issues a `search_knowledge` call with the question | Server appends one fixed USER note; the model calls the tool itself | `tool_choice="required"` on the first request |
| Message protocol | Needs a synthetic ASSISTANT tool call plus a TOOL result with matching id; an orphan or misordered pair is an invalid request the scripted model cannot detect | A USER message after the model's text: always valid; no synthetic tool messages | No synthetic messages |
| Legitimate no-tool turns | Cannot be told from a skipped search; a clarification such as "Which file?" would get a junk search | Preserved: the model may decline again and the reply is exactly today's | Forced tool call on greetings, clarifications and follow-ups the gate misses |
| New code paths | A second way to run a search (scope, handles, evidence, errors) beside the executor | One branch in `finalize` and one flag, the same pattern as the KI-026 citation retry | Changes the `AgentChatService.step` contract and every first request |
| Ownership surface | New server-built search call | None: the model's search goes through the unchanged executor | None, but changes every turn |
| Deterministic | Yes | No: depends on the model obeying | Mostly |
| Free proof of benefit | Yes | **No**: only a paid run shows whether the model searches | No |
| Regression risk | Low, but junk-search risk on clarifications | Lowest: worst case equals today | Highest: needs a paid comparison first |

Chosen because it meets the protocol and legitimate-response requirements without new machinery. **Limitation, stated plainly:** the graph cannot tell a skipped search from a legitimate no-tool reply (`classify_intent` returns `document_question` both when it is sure and when it fails safe, and the model's discarded text is not a reliable signal), and the benefit cannot be proven offline. Strategy 1 would be the fallback if a later paid run shows the model ignores the instruction; it needs its own ticket and the protocol test below.

## Design

**Allowed only when all hold** (checked in `finalize`, before the claim check and before `finalize_answer`):
1. `pending` has no tool calls and `state["tool_history"]` is empty (so never after `resolve_file`, `files_query`, a failed call or a NOT_FOUND).
2. `state["evidence"]` is empty.
3. `runtime.context.has_prior_history` is false (follow-ups such as "the second one" keep today's reply).
4. The question is not an exact social phrase: reuse the `_SOCIAL` rule through a small helper in `finalization.py`; do not copy the table.
5. The flag `search_nudged` is false.
6. `max_cycles - cycle_count >= 2`: one agent call for the tool step and one for the answer. Otherwise today's reply stays. The budget rule guarantees only that the note itself fits: a model that then chains tools can still reach the normal cycle limit (`CYCLE_LIMIT_MESSAGE`), and two bad citation markers after a search end in the existing `UNSAFE_FINAL_OUTPUT` failure (HTTP 503). Both are the ordinary grounded-path rules, identical to a model that searched without the note, and both are pinned by tests (`test_a_model_that_chains_tools_after_the_note_...`, `test_two_bad_markers_after_the_note_...`, `test_first_step_corrective_turn_http_outcomes_are_exact`).

**Effect:** return `messages + (AgentMessage(role="USER", text=NOTE),)`, `pending=None`, `search_nudged=True`; extend the `finalize` routing lambda so a set `search_nudged` with no final answer and no failure goes back to `agent`. The model's skipped text stays in the history as its own assistant message.

**The note** is a fixed constant in `graph.py` (not in `prompts.py`, so `AGENT_SYSTEM_PROMPT` and the frozen `prompt_id` `04f0d4746267b81e` stay unchanged). It contains no user text and no handles and says: no tool was used and no document evidence was retrieved; if answering needs the user's indexed documents, call `search_knowledge` now with the question; otherwise reply briefly and state no document facts.

**Ordering with the citation retry:** the nudge comes first. A first text step with an invented marker and no evidence is discarded anyway, so it does not spend the one citation retry. The retry stays available for a later evidence-backed answer; its own flag is separate. Total extra model calls from both are at most 2 and bounded by `max_cycles`.

**Empty retrieval after the nudge:** unchanged. An empty successful search is a blocked record, so the reply is `EMPTY_CONTENT` ("The index did not provide enough evidence ..."), failure `None`, no second nudge.

**Model ignores the note:** the second prose step ends in `NO_CONTENT`, exactly as today; no second nudge. **Model calls another tool:** the existing paths apply (`resolve_file` NOT_FOUND rules, inventory rendering, and so on).

## How the five reviewer findings are resolved

| Finding | Resolution |
|---|---|
| A. Existing tests conflict | Listed below with the safety property each keeps |
| B. Tool-message protocol | No synthetic tool messages exist in strategy 2; a protocol-level test checks the real message sequence anyway |
| C. Legitimate no-tool replies | Conditions 1 to 6; the model can still decline, which leaves today's reply; the limitation is stated above |
| D. Cycles, retry, empty results, loops | Budget rule 6, ordering, empty result, once-only flag, all with tests |
| E. Cost, ownership, KNOWN_ISSUES | Cost section, ownership tests including the real authorization boundary, KI-034 registered |

## Existing tests

**Unchanged (they protect behaviour this ticket must keep):**
- `tests/agents/tool_rag/test_grounding_policy.py`: `test_social_input_has_fixed_safe_output` (social phrases keep fixed server text and no extra turn), `test_filename_resolution_is_not_content`, `test_missing_and_ambiguous_render_only_verified_result`, `test_inventory_metadata_cannot_smuggle_document_claim`, `test_failed_tool_never_authorizes_model_prose`, `test_empty_read_has_explicit_nonabsence_outcome`, `test_invented_citation_is_rejected_even_with_real_evidence`, `test_content_evidence_and_real_handle_allow_grounded_answer`, `test_untrusted_metadata_is_displayed_without_links_or_citations` (all start with a tool call).
- `tests/agents/tool_rag/test_intent_gate.py`: `test_conversational_intent_returns_server_text_without_touching_the_agent` (conversational intents never run the agent), `test_model_prose_in_the_classifier_reply_is_never_shown`, `test_demo_mode_never_calls_the_classifier`, `test_without_a_classifier_behaviour_is_unchanged`, `test_fallback_punctuated_greetings_keep_working` (social exemption), `test_adapter_passes_only_the_last_assistant_turn_as_context` (has history, so no nudge).
- `tests/agents/tool_rag/test_agent_loop.py` ("Hello" social case), `test_revision_safety.py::test_no_evidence_no_fake_citations` ("Hello" is exempt), `test_citation_retry.py`, `test_name_lookup_recovery.py`, and the four guards in `tests/known_issues/test_ki034_no_tool_first_step.py`.

**Must be updated (old expectation: one model call, then the fixed reply, for a non-exempt question with no history). Each keeps its safety assertion; only the scripted steps and the call count change.**
1. `test_grounding_policy.py::test_no_tools_never_publishes_arbitrary_prose` (4 cases). Add a second prose step. Keep: answer is `NO_CONTENT`, no citations, `retrieval_count == 0`, no database call, model prose never published. Add: 2 chat calls.
2. `test_grounding_policy.py::test_tool_free_clarification_does_not_require_content`. Add a second prose step. Keep: `failure is None`, answer `NO_CONTENT` containing "Which file", no citations.
3. `test_intent_gate.py::test_document_question_goes_to_the_grounded_agent`: 2 chat calls; `NO_CONTENT`; claim text not shown.
4. `test_intent_gate.py::test_classifier_failure_never_blocks_a_question` (2 cases): 2 chat calls; `NO_CONTENT`.
5. `test_intent_gate.py::test_fallback_greeting_plus_document_question_still_needs_evidence` (4 cases). Add a second prose step. Keep: `NO_CONTENT`, no citations, claim text not shown. This is the key test that a greeting plus a document question without evidence is still never answered from the model's memory.
6. `tests/agents/tool_rag/test_claim_check.py::test_the_check_only_runs_when_there_is_evidence`: its question is "Synthetic question" with no history, so it gets the corrective turn: add a second prose step; keep: checker not called without evidence, and the no-evidence reply untouched.
7. `tests/test_paid_call_counts.py::test_tool_agent_long_question_skips_the_intent_gate`: 1 -> 2 chat calls; update the file's stated counts and note the change in M0-SEC ticket 04's findings table.
8. `tests/test_tool_agent_api.py::test_failures_no_fallback_or_sensitive_error`, UUID-prose case: scripted with two prose replies and pinned to exactly HTTP 200 (see "Scripted-model exhaustion"). Safety kept: a bare identifier in model prose never reaches the user and the reply is the fixed one. `tests/test_chat_streaming.py`, `tests/streaming_preview.py` and the three `tests/security` files that use `ScriptChat` start with a tool call or carry history and need no change; the full suite is the proof, and any further test whose result changes goes in Comments with its safety property. Do not weaken an assertion to get green.

## Acceptance criteria

- [x] Mechanism implemented and KI-034's reproducing test passes, so its strict marker is removed (an XPASS must not stay green). **KI-034 stays OPEN** in `docs/KNOWN_ISSUES.md`: the scripted model supplies the search, so whether a real model searches after the note is unmeasured, and the held-out acceptance (`CODING_STANDARDS.md`: a fix counts as fixed only after a held-out question set written before the fix and the full suite) is pending under its own Owner authorization.
- [ ] A skipped first tool on a document question with no history, enough cycles and no evidence gets exactly one corrective turn; if the model then searches, the answer is cited and the claim check runs as for any grounded answer.
- [ ] A greeting or exact social phrase, a question with history, a run with `max_cycles` 1 or 2, and any run that already called a tool get **no** corrective turn (the four KI-034 guards stay green).
- [ ] A model that ignores the note ends with `NO_CONTENT`, never an error, and is not nudged twice.
- [ ] An empty retrieval after the nudge ends with `EMPTY_CONTENT`, failure `None`, no second nudge. A `max_cycles` of 3 completes nudge, search and answer without `CYCLE_LIMIT`.
- [ ] Citation retry still works; with a bad marker on the first text step the nudge comes first and the retry is still available once afterwards.
- [ ] Named-file flows are untouched: `resolve_file` NOT_FOUND for a file-shaped name still ends with the lookup-failure text, and no corrective turn follows a resolve.
- [ ] Message sequences are valid (protocol test below). The note contains no user text and no handle.
- [ ] Ownership and access: the model's post-nudge search uses the same `ExecutionContext` (same user id and scope) as any search.
- [ ] No unbounded loop: at most one nudge and one citation retry per run, always under `max_cycles`; no new background call.
- [ ] `AGENT_SYSTEM_PROMPT`, tool descriptions, retrieval code and the intent gate are unchanged; `prompt_id` stays `04f0d4746267b81e`.
- [ ] Focused free tests pass before any paid comparison is requested; nothing here claims answer accuracy from first-step data.

## Required new tests (`tests/agents/tool_rag/test_first_step_nudge.py`, no network)

1. Happy path with a real-looking script: prose, search, cited answer -> one retrieval, `[1]` citation, 3 chat calls.
2. Conditions: one case per exclusion (social phrase, history, `max_cycles` 1 and 2, prior `resolve_file`, prior `files_query`, evidence present).
3. **Protocol test.** Convert every `chat.received` turn with `app.llm.openai_agent_service.native_messages` and assert on the wire shape: the nudge turn is `[system, user, assistant(text), user]`; no `tool` message lacks an earlier `assistant` message whose `tool_calls` contain its `tool_call_id`; every `tool_calls` id is answered by a `tool` message before the next `user` or `assistant` message; the final turn after the search is `[..., user(note), assistant(tool_calls), tool]`. Include a negative check that the validator rejects a doctored orphan tool message, so the test cannot pass vacuously.
4. Loop bounds: model ignores the note; model searches twice; both flags set; assert call counts and the cycle limit.
5. Empty retrieval and ignored note outcomes; `max_cycles=3` success.
6. Ownership at the unit level: `RecordingExecutor.contexts` shows the same user id and scope for the post-nudge search.
7. Streaming: with a stream sink, no provisional text is emitted for the skipped step (pattern: `tests/test_chat_streaming.py::test_foreign_scope_never_streams_model_prose`).
8. **Real authorization boundary (container test, needs the disposable PostgreSQL and Qdrant per `AGENTS.md`):** extend `tests/security/test_grounded_retrieval_authorization.py` along `test_tool_precedence_uses_real_owner_scoped_hybrid` with a text-only first step, the nudge, then the search; assert only the owner's text reaches the model. If the containers are not available, report that this test was **not run**; do not substitute the scripted retriever.

## Cost

The corrective turn adds **one chat call** for every affected turn. When the model then searches, the turn also costs **one embedding call and one more chat call** for the answer (and a claim check if evidence exists), against one chat call today. The paid-question quota counts admitted questions, not model calls, so it is unchanged, but token cost per affected turn rises (about 3 chat calls instead of 1). `TOOL_AGENT_TIMEOUT_SECONDS` still bounds the whole answer, so the quota lease rule is unaffected. State measured calls in the paid comparison; do not infer them.

## Completion criteria

This ticket is **not resolved** by scripted tests. Record, in this order: (1) mechanism implemented; (2) scripted behaviour verified, with the counts of what ran and what did not; (3) real-model effectiveness: **one small exploratory run only** (see the 2026-11-24 Comments), not an acceptance measurement; (4) held-out acceptance **pending** under a separate Owner authorization. KI-034 stays Open until a measured run on a frozen set shows the model searches after the note and answers correctly. Do not write "fixed" anywhere before that.

## Scripted-model exhaustion (required for every test that scripts the model)

A script that runs out of replies makes the graph raise an `IndexError`, which becomes `PROVIDER_ERROR` and can look like an ordinary failure reply, and a test that accepts "200 or 503" hides it. So:
- `ScriptChat` records `exhausted`; `assert_consumed(chat)` (in `tests/agents/tool_rag/test_agent_loop.py`) fails on a run-out **and** on a leftover reply. Every test touched or added here uses it.
- Status codes are pinned exactly. `tests/test_tool_agent_api.py::test_failures_no_fallback_or_sensitive_error` no longer accepts `200 or 503`: the provider-error case expects 503, the other two expect 200, and the UUID-prose case scripts two prose replies (the corrective turn consumes the second). A 200 that turns into a 503 now fails.
- `tests/agents/tool_rag/test_claim_check.py::test_the_check_only_runs_when_there_is_evidence` asserts `failure is None` and `final_answer == NO_CONTENT`, not just a non-empty answer.

## Interactions and notes

- **Citation retry:** the note comes first. A bad marker on the discarded first step does not spend the KI-026 retry, which stays available once afterwards (tested with a bad marker before and after the search). With exactly 3 cycles there is no retry left after the search; that is existing behaviour and is pinned.
- **Claim check:** `claim_check.user_text` passes every USER message to the checker as what the user wrote, so the checker also sees the note, exactly as it already sees the KI-026 note. Tested and documented; it changes no claim verdict.
- **Message shape:** the exact shape differs by path (the adapter adds a history-window system note, the direct service does not). The tests therefore check the invariants on `native_messages` output for both paths: every tool message answers an earlier assistant tool call, every tool call is answered before another message, no id is reused, and no tool message exists before the model made a call. The validator itself is tested against a doctored orphan and an unanswered call.
- **Demo mode:** it skips the intent gate but not the agent, so it behaves like normal mode (one note on a skipped first tool; social phrases get none). Both are tested.
- **Earlier tool call:** after `resolve_file`, `files_query`, a failed call or a search there is no note (tested per case).

## Free verification (before any paid run)

From `backend/`, `OPENAI_API_KEY` unset, in this order: the new and updated tests above; the **complete backend suite** (`uv run pytest -q`, with `SESSION_TEST_DATABASE_URL`, `QDRANT_TEST_URL` and `CONVERSATION_TEST_QDRANT_URL` pointing at disposable loopback containers, about 30 minutes; run nothing heavy beside it); the container authorization tests; `tests/known_issues -rxX` (expect KI-034 removed from the xfail list); `tests/agents/tool_rag`; `tests/test_paid_call_counts.py`; `tests/test_tool_agent_api.py`; `tests/test_chat_streaming.py`; `ruff check`, `ruff format --check`, `mypy app`, `basedpyright` on touched files; the container tests per `AGENTS.md` when available. Record counts and what was not run.

## Later small paid comparison (separate Owner authorisation; estimate first; not part of this ticket's definition of done)

End to end, not the first-step probe (it stops after the first call and cannot see this change): the 4 cases plus a small sample of cases that pass today, two repeats, with a plan, cap and estimate approved by the Owner. Report separately: how often the model searches after the note, retrieval, answer correctness and citations, and measured chat and embedding calls. Compare with the frozen G files without changing them. Decide from that data whether strategy 1 is needed.

## Exclusions

- No fusion, threshold, weight or per-file-limit change: the keyword-only ranking ceiling is a separate confirmed weakness, handled separately.
- No change to prompts, tool descriptions, `resolve_file` behaviour or the intent gate. The 11 `resolve_file` first steps are not in scope.
- No search-quality change for short queries (10 of the 17 searched misses).
- No server-run search, no `tool_choice` change, no new tool or contract.
- No index rebuild, held-out run, push or deploy.

## Affected files

Source: `backend/app/agents/tool_rag/graph.py` (`finalize`, its routing lambda, the note constant), `agent_state.py` (`search_nudged`), `agent_service.py` (initial state), `finalization.py` (small social-phrase helper over `_SOCIAL`, read-only reuse). Tests: `backend/tests/known_issues/test_ki034_no_tool_first_step.py` (marker removal), new `backend/tests/agents/tool_rag/test_first_step_nudge.py`, the updated tests listed above, `tests/security/test_grounded_retrieval_authorization.py`. Docs: `docs/KNOWN_ISSUES.md` (KI-034 entry rewritten; it stays **Open**, never Fixed on scripted tests), `docs/tickets/m0-sec-security-hardening/04-trace-paid-calls-per-route-and-path.md` (tool-agent call count 3, not 2, for an affected turn), `backend/app/agents/tool_rag/README.md`, `docs/guides/CURRENT_DEVELOPMENT_STATUS.md`.

## Comments

- 2026-11-23: diagnosis follow-up (free). Two independent review rounds on the diagnosis and the first ticket draft returned BLOCK; this revision addresses the second round. The fusion-ranking ceiling is confirmed by offline tests and consistent with 5 of 9 searched-miss cases; it is not part of this ticket. Evidence files are in the Owner's review-evidence folder outside Git (`m1-08-g-diagnosis`).
- 2026-11-24: implemented (mechanism only) and independently reviewed once (NEEDS-EVIDENCE, no P0/P1). Follow-up in the same session: M0 ticket 04 call counts corrected; edge-case tests added (chained tools to the cycle limit with one note; a second search; two bad markers after note and search, graph level and HTTP 200/503 exact); basedpyright compared against the base commit in a temporary worktree (identical 59 errors on both, so the recorded 48 was already stale and this change adds none). **Future paid comparisons must record the Git commit hash**: `prompt_id` hashes only `AGENT_SYSTEM_PROMPT` and the tool definitions, so it does not change when the corrective note is added or removed. KI-034 stays Open: real-model effect unmeasured, held-out acceptance pending.
- 2026-11-24: final verification record (free). **Mechanism implemented; scripted behaviour verified; real-model effectiveness unmeasured; held-out acceptance pending; KI-034 stays Open.** Evidence is saved outside Git in the Owner's review-evidence folder (`ki-034`).
  - Full backend suite on the final production code, on disposable PostgreSQL 18 and Qdrant 1.18.0 with `OPENAI_API_KEY` unset: **4118 passed, 7 skipped, 6 xfailed, 0 failed** (19 min 32 s). It was **not** repeated after the later, additive edge-case tests; `backend/app` was byte-identical between that run and the final tree.
  - Affected test files plus all of `tests/security` with the containers: 4 failed, 1782 passed. The 4 failures were indexing timeouts (`test_indexing_leases.py` x3, `test_normal_indexing_runtime.py` x1) while other heavy programs loaded the machine, the pattern `AGENTS.md` records; those two files rerun alone: **53 passed**. There is no single clean combined run of that set.
  - Container authorization test (`test_tool_precedence_uses_real_owner_scoped_hybrid`, 8 cases, 4 with a skipped first tool): 8 passed.
  - basedpyright: **59 errors on both the base commit and the modified tree**, identical per-file messages (base checked in a temporary worktree with the same environment); the change adds none, and the recorded 48 was already stale.
  - `ruff check`, `ruff format --check`, `mypy app` and `git diff --check`: clean.
  - Reviews: round 1 NEEDS-EVIDENCE (no P0/P1; one P2 documentation error, several P3); round 2 BLOCK for documentation only (ticket 04 call counts, fixed afterwards). A third, final review covers the corrections. The reviewers had no shell: they judged saved raw outputs and did not run the tests.
  - Not yet explained: 7 skips in the full run against 1 in the `AGENTS.md` baseline (the skip reasons were not collected).
- 2026-11-24: committed locally as `b25d80b` (final read-only review APPROVE; not pushed). Exploratory real-model run (Owner-authorized, cap 0.10 USD, commit `b25d80b`, v3 store): 8 runs over `ca05`, `ca04`, `ru02`, `ru05`, 2 repeats, metered **0.02029 USD**, 38 calls, no errors. 4 of 8 scored correct; 5 of 8 retrieved the expected file; `ca05` and `ru02` searched after the note and were correct (2 of 2 each); `ca04` ignored it (0 of 2); `ru05` repeat 1 ignored it, repeat 2 searched at the first step and was scored wrong although substantively correct (Roman Urdu reply against an English-sensitive scorer). Activation is inferred, not recorded. English-only scope (decision 2026-11-24): `ru02` and `ru05` are outside it, so English evidence is `ca05` (helped) and `ca04` (not helped). KI-034 stays Open: see the registry entry for what acceptance still needs. Evidence: the Owner's review-evidence folder, `ki-034/real-model-run`.

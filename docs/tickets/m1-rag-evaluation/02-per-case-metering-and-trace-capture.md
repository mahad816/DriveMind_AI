# 02: Per-case metering and trace capture

**Spec:** docs/specs/m1-rag-evaluation.md
**What to build:** Each case records what it cost in calls, tokens and dollars by role, and which queries the agent really wrote and which chunks it really retrieved and cited. This is what makes cost, latency, retrieval-on-the-real-run and failure attribution measurable.
**Blocked by:** 01.
**Status:** done
**Progress:** complete (2026-11-22)

## Scope

- **Per-case, per-role metering.** Attribute each provider call to a case id (a context variable that survives concurrent cases) and a role. Roles are classified by the fixed system-prompt text each call carries (intent gate, claim check, agent step, and for the legacy paths follow-up rewrite and answer generation), not by model name, so they stay correct when two roles share a model (the judge and the claim check both use the mid-size model today, and a second-model run would make chat and claim check equal); embeddings, the refusal judge and the grader set their own labels. Do **not** inject a chat service or an agent into the adapter: that silently removes the intent gate and the claim check. Only the retriever is injected. Record per case and role: calls, failed calls, input and output tokens, cached tokens, estimated dollars. Failed requests (exceptions) are counted, not dropped. Keep the unknown-model error. **The hard cap must really stop a run:** the meter's cap error is swallowed on the tool-agent path (the agent graph turns it into a provider error, the adapter re-raises a chat error, and the claim check fails open), so the meter gets a "tripped" flag, the runner aborts the run when it is set, rows after the trip are marked `cap_stopped` and excluded from every rate, and the summary says the run is incomplete. State in the manifest that streamed requests and SDK retries are invisible to the meter, and make the harness assert it uses the non-streaming path.
- **Recording retriever and executor wrapping.** A subclass of the hybrid retriever passed as the retriever of the question-answering service records for each search the query, scope kind and returned chunk identifiers with rank and score. It sees only `retrieve`: whole-file reads (the full-document path and the recovery read of a bounded prefix), file listing and name lookup bypass it, so the harness also wraps the tool executor's entry and its whole-file read from outside, the way the meter wraps the provider SDK, to record every tool call, its arguments, and which chunks a whole-file read returned and where it was cut. Findings state exactly what each wrapper sees. The per-question execution log line (steps, tool names, outcome) is captured by one global log handler that tags records with the case id through a context variable (a handler per case is unsafe at concurrency three); the claim check's removal decisions are captured the same way.
- **Result row additions:** cited chunk identifiers and snippets as returned, retrieved chunk identifiers per search, the agent's queries, tool names in order, number of agent steps and searches, outcome, per-role accounting, wall time. All existing fields stay.

## Out of scope

Manifest and CLI (ticket 01), scoring (ticket 03), any paid run, any change under the application package. If the recording retriever or the callable wrapping cannot be injected without an application change, stop and report; do not change the application.

## Inspect

`backend/evaluation/rag_eval/runner.py`, `meter.py`, `judge.py`; `backend/app/services/tool_agent_service.py` (injected `retriever`, `intent_complete`, `claim_complete`); `backend/app/services/rag_service.py`; `backend/app/agents/tool_rag/execution/executor.py`; `backend/tests/test_paid_call_counts.py` (M0-SEC ticket 04); ticket 01 `## Findings`.

## Deliverables

Code and free tests; `## Findings` recording what is and is not captured and the measured limits of the meter.

## Needs

No paid API, no key, no network. The retriever test uses a stub inner retriever; any container test uses the existing disposable PostgreSQL and Qdrant conventions.

- [x] Under concurrent cases, a stub client's calls are attributed to the right case and role (at least four interleaved cases, every role, two roles sharing one model); failed calls are counted; an unknown model still raises.
- [x] **Through the real tool-agent adapter with a stub provider**, a tripped cap stops the run, marks the later rows `cap_stopped`, excludes them from rates and reports the run as incomplete; the test fails if the cap error is swallowed into ordinary error rows.
- [x] A test with a stub inner retriever shows the recording retriever captures query, scope kind, chunk identifiers, rank and score per search and passes results through unchanged; a test shows the executor wrapper records a whole-file read and a file listing; Findings state what each wrapper sees and what remains invisible.
- [x] Result rows carry the new fields and `rescore` still works on rows without them.
- [x] `git diff -- backend/app` is empty; touched evaluation files pass `ruff check`, `ruff format --check` and `mypy`; the container-free evaluation tests pass.

## Findings

### Metering (`evaluation/rag_eval/meter.py`)

- **Attribution.** `case_var` (a context variable set once per case inside its own task) and a role. The role is the **exact first system prompt** of the chat request (`ROLE_BY_SYSTEM_PROMPT`): intent gate, claim check, agent step, follow-up rewrite, and `answer_generation` for the legacy answer, file-target, inventory, collection and chit-chat prompts. Embeddings are `embedding`; a request with no recognised system prompt (the refusal judge, the later grader) keeps `label_var`. A prompt that is not in the table shows as `unlabelled`, it is not attributed to a neighbour. Model name plays no part (test: claim check and judge on one model stay apart under four interleaved cases).
- **Per case and role:** calls, failed calls, cancelled calls, calls without usage, input, output and cached tokens, dollars, models. The key of a case is `pipeline/case id/random suffix` because one id recurs across pipelines and repeats. `meter.summary()` keeps its old shape (`by_label_and_model`, now labelled by role) and adds `tripped`.
- **Failures.** An exception from the provider call is counted as `failed_calls`; an `asyncio.CancelledError` (timeout of the intent gate, claim check or agent, or cancellation after a cap trip) as `failed_calls` and `cancelled_calls`. Neither has tokens, and a cancelled request may still be billed (not measurable here).
- **Missing usage.** A response with no `usage` is counted, flagged `missing_usage_calls`, and the case gets `usage_incomplete: true` (its cost is a lower bound). A response without a `model` uses the requested model. An unpriced model still raises `UnpricedModel`.
- **Cap.** `meter.tripped` is set whenever the meter refuses a call, loses count (unpriced model) or sees a streamed request; `stopped_cases` records which case it happened in. `run_pipeline` starts no new case once `meter.exhausted` (tripped or total at the cap). `run_case` turns a `BudgetExceeded` into a `cap_stopped` row, and also marks as `cap_stopped` any row whose case tripped the meter even if some layer swallowed the error into an ordinary one. `summarise` leaves those rows out of every rate and reports `cap_stopped` and `incomplete`. The CLI writes the (incomplete) file, stops the remaining pipelines and repeats and exits non-zero. Ticket 01 had already made `BudgetExceeded` a `BaseException`, so the swallowing the ticket text describes no longer occurs; the test still fails if it comes back (second cap test).
- **Streaming.** The wrapped `create` raises `UnmeteredRequest` (a `BudgetExceeded`) for `stream=True`. The harness reaches the model only through `RagService.ask`, whose agent call is the non-streaming `step`; `stream_step` is used only by the streaming turn route.
- **Manifest.** `manifest["metering"]` states what is counted and what is invisible (SDK retries, streamed requests, a request billed after its caller gave up).

### Trace (`evaluation/rag_eval/trace.py`) and what each recorder sees

| Recorder | Sees | Does not see |
|---|---|---|
| `RecordingRetriever` (subclass of `HybridRetriever`, the only injected object; passed as the `RagService` retriever when the tool agent or hybrid retrieval is on, as the application would build it) | each hybrid search: query, scope kind (`collection` or `files`) and number of files, candidate limit, ranked chunk ids with filename, chunk index, final score, fusion score and per-source scores, sufficiency and reason, duration, the error class of a failed search; the tool call it belongs to | whole-file reads (full document and the recovery read), file listing, file count, name lookup; the legacy file-target and inventory paths; the model text |
| Executor wrapper (`ToolExecutor.execute` and the module-level `full_document`, patched from outside for the duration of `run_pipeline`) | every tool call in order: tool name (`UNKNOWN` for anything outside the four), parsed arguments (file handles, not file names), error code and a truncated private diagnostic, result shape (type, counts, chunk ids), duration; every whole-file read: trigger (`requested` or `recovery`), chunk ids and indexes with characters returned, total chunks and characters, `truncated`, `budget_chars` and the last returned chunk index (the prefix is clipped to the budget, so the cut usually falls inside that last chunk; `total_chars` sums overlapping chunks, it is not the document length) | the text returned to the model; which file a handle means (the result's chunk ids and the read's file name give it) |
| Log handler (one handler on the `app` logger, copies `rag_execution` lines onto the trace of the emitting task) | agent steps, tool names, outcome, cycle limit, retrieval count, intent-gate replies, timeout and error outcomes, claim-check removals, check errors | anything the application does not log; lines of a case whose task never logged (a crash before the log line) |

- Row additions: `accounting`, `cited` (chunk id, file, score, snippet as returned), `execution` (path, outcome, agent steps, search count, agent queries, tool names, whole-file reads, claim-check removals) and `trace` (schema version 1: searches, tool calls, events). All earlier fields stay; `cap_stopped` rows have `error: "cap_stopped"` and no verdict.
- The log handler lowers the `app` logger to INFO while installed and restores it afterwards.

### Verification

- New file `tests/evaluation/test_rag_eval_metering_and_trace.py` (21 tests): four interleaved cases with every role and two roles on one model; failed and cancelled calls; unknown model; missing usage; streamed request; the cap through the **real** `ToolAgentAdapter` (intent gate, graph and agent step through the SDK stub, only the retriever injected) with `cap_stopped` rows, rates and `incomplete`; a swallowed cap error; row fields and rescoring with and without them; the recording retriever (pass-through, scope kinds, failure); the executor wrapper on a file listing, a truncated whole-file read, a recovery read and a failed or unknown tool call; concurrent traces and log events; removal of every patch. Mutation checks that fail as intended: all calls attributed to one case; no `cap_stopped` conversion and no start refusal.
- `git diff -- backend/app` is empty. `ruff check`, `ruff format --check` and `mypy` are clean on the touched files. Container-free backend run (no key, no container variables): 2356 passed, 929 skipped, 2 xfailed with `test_rag_eval_dataset.py` deselected, plus that file alone: 14 passed in 148 s. `ruff check`, `ruff format --check`, `mypy` clean on the touched files.

### Limitations

- The cap tests stand in for `RagService` (it needs a database) and run the real `ToolAgentAdapter`, graph and agent chat service; that `RagService.ask` itself lets the cap through is not tested here, and was reasoned from its code (it has no broad `except`).
- The test file is one module of about 700 lines (meter, runner and trace tests); splitting it was left for later.

- The claim check and a real tool call with evidence were not run end to end here (they need the database); each part is tested separately: the claim check's role by its prompt, the executor wrapper on a fake database. A real run (ticket 08 or 11) is the first test of the whole chain against PostgreSQL and Qdrant.
- Embedding calls made inside the real vector retriever are attributed to the case through the same context variable, but this was tested only for a direct embedding call, not through `VectorRetriever`.
- Legacy path: roles `followup_rewrite` and `answer_generation` and the hybrid searches are recorded; the file-target and inventory routes use other retrieval code and leave no search entry. No end-to-end legacy test.
- SDK retries (default 2 on the non-streaming agent step), streamed requests and any billing after a caller gave up stay invisible; the overshoot at the cap is unchanged (in-flight requests may finish).
- Cancelled requests are counted without tokens. A timed-out request may still be billed.
- Latency in rows is wall time under concurrency 3, not clean performance latency (ticket 12 uses a sequential run).
- `rescore` calls the judge outside any case, so its spend is in `rescore_spend` but not in per-case accounting.
- Result files grow: each row now carries snippets, ranked chunk lists and tool calls.

## Comments

2026-11-22, two independent read-only reviewers.

- **Standards, simplicity, maintainability: no blocking findings.** Fixed: duplicated counter updates (now one `_add` helper that updates the run-wide and the per-case row together), a bare boolean parameter (now a role), `rescore` re-judging cap-stopped rows. Left as is: the large test module, private/public helper naming in `trace.py`, the hard-coded tool-name set (unknown tools show as `UNKNOWN`), the long `tracing_installed`.
- **Spec, correctness, spending safety: no blocking findings.** Fixed: `check()` now refuses once the meter has tripped (an unpriced or streamed request ended only its own case before, while in-flight cases kept spending; test added); the whole-file read fields now say `last_returned_chunk_index` and `budget_chars` instead of a misleading cut index; a later `CLIENT_CLEANUP_ERROR` log line no longer replaces the real outcome (`cleanup_error` is a separate flag); the early `cap_stopped` row has the same keys (`accounting`, `execution`, `trace` as null). Recorded under Limitations: stand-in `RagService` in the cap tests, no judged-case-after-trip test.

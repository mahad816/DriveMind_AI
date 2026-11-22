# 02: Per-case metering and trace capture

**Spec:** docs/specs/m1-rag-evaluation.md
**What to build:** Each case records what it cost in calls, tokens and dollars by role, and which queries the agent really wrote and which chunks it really retrieved and cited. This is what makes cost, latency, retrieval-on-the-real-run and failure attribution measurable.
**Blocked by:** 01.
**Status:** ready-for-agent
**Progress:** open

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

- [ ] Under concurrent cases, a stub client's calls are attributed to the right case and role (at least four interleaved cases, every role, two roles sharing one model); failed calls are counted; an unknown model still raises.
- [ ] **Through the real tool-agent adapter with a stub provider**, a tripped cap stops the run, marks the later rows `cap_stopped`, excludes them from rates and reports the run as incomplete; the test fails if the cap error is swallowed into ordinary error rows.
- [ ] A test with a stub inner retriever shows the recording retriever captures query, scope kind, chunk identifiers, rank and score per search and passes results through unchanged; a test shows the executor wrapper records a whole-file read and a file listing; Findings state what each wrapper sees and what remains invisible.
- [ ] Result rows carry the new fields and `rescore` still works on rows without them.
- [ ] `git diff -- backend/app` is empty; touched evaluation files pass `ruff check`, `ruff format --check` and `mypy`; the container-free evaluation tests pass.

## Comments

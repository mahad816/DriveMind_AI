# 01: Run manifest, production-equivalence pin and CLI safety

**Spec:** docs/specs/m1-rag-evaluation.md
**What to build:** Every harness run states exactly what was measured (commit, flags, models, prompts, corpus, prices). The evaluation settings are pinned to the application defaults. Paid commands cannot start without an explicit cap and a dry-run estimate, and a run can be repeated. Nothing about scoring, metering or datasets changes here.
**Blocked by:** None (can start immediately).
**Status:** done (local commit, not pushed)
**Progress:** complete 2026-11-22; both independent reviews done, blocking finding fixed

## Scope

- **Run manifest** written into every result file: audited commit and whether the tree was clean; every setting that can change an answer (tool agent, hybrid retrieval, claim check flag and model, chat model, embedding model and dimension, retrieval thresholds and per-file cap, name-term limit, rag context size); digests of the agent system prompt and the four tool descriptions; extraction pipeline version; corpus and dataset identifiers and checksums (empty placeholders until tickets 04 to 07 land); price-table date; concurrency; repeat index and count; library versions (openai SDK, Python); cap and spend. A `schema_version` on the file. `rescore` keeps working on files without the new fields.
- **Production-equivalence pin.** A free test asserts the evaluation settings equal the application's default settings for every field that can change an answer, except an explicit allow-list (store location, demo off, debug off, tool agent on).
- **Command line.** A `--repeats N` option (rows carry the repeat index; one result file per run). `--cap` is mandatory for every command that can reach a provider (`setup`, `run`, `rescore` with the judge, and the probes); the existing default is removed and the three commands' help says so. Concurrency one is already available through the existing concurrency option; no new option is added for it. A `--plan` dry run prints the number of cases, the expected calls by role and an estimate, writes nothing and calls nothing; the real command refuses to start when the estimate exceeds the cap. The per-question cost constants live next to the price table (one dated file, replaced by measured values in ticket 12), not in a new file format.

## Out of scope

Per-case metering and trace capture (ticket 02), scoring, datasets, corpus, the grader, any paid run, any change under the application package.

## Inspect

`backend/evaluation/rag_eval/` (`cli.py`, `target.py`, `runner.py`, `meter.py`, `prices.json`); `backend/app/core/config.py`; `backend/tests/evaluation/test_rag_eval_meter.py`, `test_runner.py`; `docs/EVALUATION_RESULTS.md` ("What the first run got wrong").

## Deliverables

Code and free tests; `## Findings` listing every setting the manifest records and the allow-list of the equivalence pin; a short update to `docs/guides/EVALUATION.md` naming the free and the paid commands.

## Needs

No paid API, no key (unexport `OPENAI_API_KEY`), no network, no container.

- [x] A result file contains the full manifest; a test fails if a listed field is missing, and the equivalence pin fails when an answer-relevant setting differs from the application default outside the allow-list.
- [x] `rescore` works on a result file written before this ticket (a fixture built in the test, not read from the ignored results folder).
- [x] `--plan` makes no provider call and writes no file; a command whose estimate exceeds `--cap` refuses to start; omitting `--cap` is an error for every provider-reaching command; `--repeats` writes one file per repeat with the index in rows and manifest.
- [x] `git diff -- backend/app` is empty; touched evaluation files pass `ruff check`, `ruff format --check` and `mypy` (the evaluation package is outside CI's scope, so run them on the touched files); the container-free evaluation tests pass.

## Findings

### What the manifest records (`evaluation/rag_eval/manifest.py`, key `manifest` in every `run` result file, `schema_version` 1)

- `commit`, `tree_clean` (null when git is unavailable); `repeat_index` (1-based), `repeat_count`, `concurrency`, `cap_usd`, `spend` (cumulative meter summary after that run), `price_table_date`.
- `settings`: the 21 answer-relevant fields in `target.ANSWER_FIELDS`: tool agent, graph, hybrid retrieval, claim check flag and model, chat model, embedding model, candidate k, top k, score and relative thresholds, name-term limit, per-file cap, RRF k, three fusion weights, minimum fusion score, full-text language, context size, rewrite attempts. `deviations_from_default` lists those that differ from the code default (the legacy pipeline shows `tool_rag_agent_enabled: false`; the tool agent shows `true`, which is the only expected entry).
- `embedding_dimension` (from the application's resolver), `indexing` (extraction pipeline version, chunk target size and overlap).
- `prompts`: SHA-256 of the agent system prompt, the four tool descriptions, plus the intent-gate and claim-check prompts (beyond the ticket's list, because they change answers too).
- `corpus` (file count, `with_messy`, a digest of every file path and checksum, empty `version_id`) and `dataset` (split, a digest per dataset file, empty `version_id`); the two `version_id` fields are placeholders until tickets 04 to 07.
- `libraries`: openai SDK and Python versions.
- Rows carry `repeat`. Files written before this ticket have none of these keys; `rescore` reads only `model`, `datasets` and `rows` and is tested on such a file.

### The production-equivalence pin

- `eval_settings()` now overwrites every `ANSWER_FIELDS` setting with the application's code default (`Settings.model_fields[name].get_default()`), so a local `.env` or environment variable can no longer change what is measured (previously the helper started from `get_settings()` and kept any override). `--model`, `--threshold`, `--relative` and `--no-claim-check` still override explicitly and show in `deviations_from_default`.
- **Allow-list** (the only fields that may differ from the code defaults, tested over every `Settings` field): `database_url`, `qdrant_url`, `qdrant_api_key`, `qdrant_host`, `qdrant_port`, `qdrant_collection` (store location), `demo_mode`, `debug`, `tool_rag_agent_enabled`.
- Note: the deployed application takes its values from its own environment; the pin fixes the evaluation to the **code defaults of the audited commit**, which is what the spec defines as the production path. Whether Railway overrides any of them is not checked here (no Railway access).

### Command line

- `--cap` is required, has no default and must be a positive finite number, on `setup`, `run`, `rescore` and the four probe scripts (`first_step_probe`, `retrieval_probe`, `ragbench_check`, `planted_claims`). `--plan` exists on `setup`, `run` and `rescore` (the three commands the ticket names); the four probes got the mandatory cap only and **no `--plan` or estimate refusal**.
- `--plan` returns before settings, meter, database or provider are touched and writes nothing. A real command refuses when the estimate is above the cap.
- `--repeats` 1 to 5 (`MAX_REPEATS`); one file per pipeline and repeat, named `..._r<i>of<N>` only when N > 1 (single runs keep the old name). `--limit` and `--concurrency` must be at least 1 (a negative `--limit` used to slice from the end). `rescore` without a file is a usage error.
- Estimates come from the new `estimates` block in `prices.json` (dated 2026-11-22): per-question calls by role and dollars (spec figures and M0-SEC ticket 04 section 2), judge 0.0012 per judged case (an **assumption**: about 1,000 input and 100 output tokens at the mini price), setup 0.005 per MB of corpus files (upper bound: 4 bytes per token, files already indexed cost nothing). All are planning constants for ticket 12 to replace.

### Spend cap, including the tool agent

- **Defect found and fixed (harness):** `OpenAIAgentChatService.step` turns every `Exception` into `ChatError`, and the claim check and graph also swallow exceptions. `BudgetExceeded` was a `RuntimeError`, so after the cap was reached the tool agent hid it, the run went on and recorded an error row for every remaining case (no further paid request was sent, because the meter refuses before each call, but the run never stopped and the error rows looked like product failures). `BudgetExceeded` is now a `BaseException`, so no application `except Exception` can swallow it. No application file changed.
- `run_pipeline` cancels the cases still running when the cap (or Ctrl-C) ends a run. `cli run` stops, writes nothing for the unfinished pipeline run, keeps the files already written, prints the spend and exits non-zero.
- Test: the real `OpenAIAgentChatService.step` under the meter, with the SDK method faked: after the cap is reached the next step raises `BudgetExceeded` and the provider is not reached again. Mutation check: with `BudgetExceeded` as a `RuntimeError`, that test fails with `ChatError: Agent provider request failed`.

### Verification

- New file `tests/evaluation/test_rag_eval_manifest_and_cli.py` (35 tests). Mutations confirmed to fail: cap as `RuntimeError`, the pin removed, task cancellation removed.
- Container-free backend run, no key, no container variables: 2335 passed, 929 skipped, 2 xfailed with `test_rag_eval_dataset.py` deselected, plus that file alone: 14 passed in 148 s (it reads the public PDFs). `ruff check`, `ruff format --check`, `mypy` clean on the 10 touched files. `git diff -- backend/app` empty. `mypy evaluation/rag_eval` as a whole reports 22 errors, all in untouched `messy_fixtures.py`; the same 22 appear without this ticket's changes (pre-existing).

### Limitations

- The meter checks before a call, so requests in flight when the cap is crossed can overshoot by up to concurrency times one call. It counts successful responses only; SDK retries and failed requests stay invisible (spec A5, ticket 02 or later).
- A run stopped by the cap loses its unfinished pipeline run (no partial file); ticket 02 adds per-case recording.
- The four probes have no `--plan`. `--plan` estimates are constants, not measurements, and the setup figure is a deliberately high upper bound.
- `BudgetExceeded` is now a `BaseException`: any harness code under the meter that needs to clean up on it must use `finally`, not `except Exception` (`run_case` and `run_pipeline` do).
- Overshoot is larger than one call per worker on the tool agent: each in-flight case may finish its current step (intent gate, agent step, claim check) until its next meter check, and a cancelled request may still be billed by the provider. SDK retries (default 2 on the non-streaming agent step) are not metered.
- The estimate uses fixed per-question constants: it ignores `--model` and `--no-claim-check`, and assumes the typical 2 agent steps (the agent may take up to 6). The cap, not the estimate, is the protection for a more expensive model.
- `setup` stopped by the cap leaves files in `indexing` state (the indexing service's `except Exception` no longer sees the stop); whether a rerun resumes them was not verified here.
- Other harnesses outside `rag_eval` (`evaluation/runner.py --execute-gold`, `agent_smoke_runner.py --execute`, `intent_eval.py --execute`) have no cap or meter. They are outside this ticket's named commands and untouched.
- Probe `--repeats` (first_step_probe) is not bounded.
- Hole found by review and fixed: a paid response from a model with no price entry used to raise a `KeyError` that application code swallowed, leaving the cap blind. `record()` now raises `UnpricedModel` (a `BudgetExceeded`), and `run`, `setup` and `rescore` check every model's price before spending.
- The pin is a deliberate behaviour change: a past run made with a local `.env` override is no longer what the default command reproduces; such overrides now need explicit options and show in `deviations_from_default`.
- The manifest cannot say whether the deployed environment overrides a default.

## Comments

2026-11-22, two independent read-only reviewers.

- **Standards, maintainability, simplicity: no blocking findings.** Fixed: a brittle price-date assertion in a test, a grep-based probe test (now a regex on the `--cap` argument), a duplicated per-pipeline settings copy (now `runner.pipeline_settings`), `return report_plan(...)` style. Left as is: three similar `STOPPED` messages; a blank-line change by the import sorter in `ragbench_check.py`.
- **Spec, correctness, evaluation safety: one blocking finding, fixed.** A paid response from a model missing from `prices.json` raised a `KeyError` that application code swallowed, so the total never rose and the cap never fired. Now `UnpricedModel` (a `BudgetExceeded`) stops the run, and `run`, `setup` and `rescore` check prices up front; tests added and the older meter test updated. Non-blocking points recorded under Limitations: uncapped older harnesses, estimate ignoring `--model`, larger tool-agent overshoot, `setup` interrupted by the cap, unbounded probe `--repeats`, the pin as a deliberate change. Confirmed by the reviewer: every answer-relevant setting is in `ANSWER_FIELDS`; `--plan` touches no provider, database or file; `BudgetExceeded` as a `BaseException` leaves no patched SDK or leaked task.

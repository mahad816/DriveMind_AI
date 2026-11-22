# 01: Run manifest, production-equivalence pin and CLI safety

**Spec:** docs/specs/m1-rag-evaluation.md
**What to build:** Every harness run states exactly what was measured (commit, flags, models, prompts, corpus, prices). The evaluation settings are pinned to the application defaults. Paid commands cannot start without an explicit cap and a dry-run estimate, and a run can be repeated. Nothing about scoring, metering or datasets changes here.
**Blocked by:** None (can start immediately).
**Status:** ready-for-agent
**Progress:** open

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

- [ ] A result file contains the full manifest; a test fails if a listed field is missing, and the equivalence pin fails when an answer-relevant setting differs from the application default outside the allow-list.
- [ ] `rescore` works on a result file written before this ticket (a fixture built in the test, not read from the ignored results folder).
- [ ] `--plan` makes no provider call and writes no file; a command whose estimate exceeds `--cap` refuses to start; omitting `--cap` is an error for every provider-reaching command; `--repeats` writes one file per repeat with the index in rows and manifest.
- [ ] `git diff -- backend/app` is empty; touched evaluation files pass `ruff check`, `ruff format --check` and `mypy` (the evaluation package is outside CI's scope, so run them on the touched files); the container-free evaluation tests pass.

## Comments

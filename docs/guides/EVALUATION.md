# Evaluation

DriveMind has implemented evaluation tracing, a versioned gold dataset, deterministic metrics, a sequential runner for the production RAG path, and a separate conversation evaluation harness. This guide distinguishes that tooling from future evaluation work. It does not claim a new run or score.

## Implemented today

| Area | Location | What it does |
|------|----------|--------------|
| Internal trace capture | `backend/app/evaluation/trace.py` | Captures route, retrieval attempts, selected prompt chunks, answers/citations, outcomes, timings, and errors when explicitly requested by an evaluation caller. Traces are not exposed by the public `/chat` response. |
| Gold question set | `backend/evaluation/datasets/gold_v1.json` | Versioned labeled questions for the controlled corpus. |
| Dataset validation | `backend/evaluation/dataset.py` | Loads and validates evaluation cases. |
| Deterministic metrics | `backend/evaluation/metrics.py` | Calculates file-ranking, source, citation, route, and phrase diagnostics from results/traces. |
| Gold runner | `backend/evaluation/runner.py` | Checks corpus and environment, runs cases sequentially through `RagService`, and writes a machine-readable result artifact. |
| Conversation harness | `backend/evaluation/conversation_dataset.py`, `conversation_runner.py`, and `datasets/conversational_followup_v*.json` | Exercises conversation-history behavior separately from the single-turn gold runner. |
| Tests | `backend/tests/evaluation/` | Tests dataset validation, metrics, tracing, runner preflight, and conversation evaluation with synthetic fixtures. |

The repository also records baseline failure analysis and later experiment decisions under `backend/evaluation/analysis/` and `backend/evaluation/experiments/`, with human-review records under `backend/evaluation/reviews/`. Read those artifacts for their specific conditions and conclusions; they are not a claim about a fresh local run.

## Controlled corpus

The original controlled Google Drive corpus, `DriveMind_Eval_Corpus_v1`, contains nine named text files:

`CoreChain_Project.txt`, `DriveMind_Project.txt`, `PTCL_Internship.txt`, `Resume_v1.txt`, `Resume_v2.txt`, `Cloud_Computing_Notes.txt`, `Machine_Learning_Notes.txt`, `Meeting_Notes_July.txt`, and `Expense_Report_2025.txt`.

The September 2026 checkpoint documented these as indexed with matching PostgreSQL chunks and Qdrant points. That was a point-in-time observation, not a guarantee about another developer's Drive account or current local database. Keep the corpus fixed when comparing baseline and experiments; version any material corpus changes.

## Running the implemented tooling

From `backend/`, inspect the available options without executing provider calls:

```bash
uv run python -m evaluation.runner --help
uv run python -m evaluation.conversation_runner --help
uv run pytest tests/evaluation -q
```

A deliberate gold run uses `uv run python -m evaluation.runner --execute-gold`. It needs the controlled Drive corpus indexed in PostgreSQL and Qdrant, a configured backend/OpenAI environment, and a clean Git tree by default. The explicit flag prevents accidental live API usage. The runner writes JSON under `backend/evaluation/results/`, which is ignored by Git. The conversation harness has its own explicit `--execute-conversation` flag and dataset. Do not treat synthetic test fixtures as measured retrieval quality.

## The v2 harness (`backend/evaluation/rag_eval/`): free and paid commands

Run from `backend/`. The v2 harness answers the committed question sets through the production path against an isolated, disposable PostgreSQL and Qdrant store (see `docs/EVALUATION_RESULTS.md`).

**Free (no key, no provider, no store):**

```bash
env -u OPENAI_API_KEY uv run pytest tests/evaluation -q
uv run python -m evaluation.rag_eval.cli run --plan --cap 3 --pipelines tool_agent --split dev
uv run python -m evaluation.rag_eval.cli setup --plan --cap 1
uv run python -m evaluation.rag_eval.cli rescore evaluation/results/FILE.json --plan --cap 1
```

`--plan` prints the number of cases, the expected calls by role and an estimate, then stops: nothing is called, built or written. The estimate uses the dated planning constants in `evaluation/rag_eval/prices.json` (`estimates`), which are not measurements.

**Paid (can spend money, each needs an explicit `--cap` in USD, no default):**

| Command | What it can spend on |
|---|---|
| `cli setup --cap USD` | embeddings for the corpus |
| `cli run --cap USD [--repeats N] [--limit N]` | the answering calls and the refusal judge; `--repeats` is 1 to 5 and writes one result file per repeat and pipeline |
| `cli rescore FILE --cap USD` | the refusal judge |
| `first_step_probe`, `retrieval_probe`, `ragbench_check`, `planted_claims` (`--cap USD`) | one model call or one embedding per question; these four have no `--plan` yet |

A command whose estimate is above `--cap` refuses to start. During a run the meter refuses every provider call after the cap is reached. The cases that were running or not yet started become rows marked `cap_stopped`: they are left out of every rate, the summary says `incomplete: true`, the file is still written and the command exits non-zero. The meter checks before each call, so requests already in flight can overshoot by up to the concurrency times one call.

The meter attributes every successful non-streaming chat and embedding request to a case and a role (`intent_gate`, `agent_step`, `claim_check`, `followup_rewrite`, `answer_generation`, `embedding`, plus the `judge` label), from the fixed system prompt of the request and not from the model name. Failed and cancelled requests are counted without tokens; a response with no usage block is counted and the case is flagged `usage_incomplete`. SDK automatic retries and streamed requests are invisible (a streamed request is refused and stops the run); the manifest says so under `metering`.

Each result row also carries `accounting` (calls, failed calls, tokens, cached tokens and dollars by role), `cited` (chunk identifiers and snippets as returned), `execution` (path, outcome, agent steps, search count, queries, tool names, whole-file reads, claim-check removals) and `trace` (every search with its ranked chunks and scores, every tool call with its arguments, result shape and whole-file reads, and the application's `rag_execution` log lines). Rows written earlier have none of these and still rescore.

Every row is also scored without any model by `deep.extend_row` (written by `run` and recomputed by `rescore`, which needs the evaluation database for chunk texts and degrades to `scored_partial` without it): fact recall, chunk-level citation and integrity, retrieval from the recorded searches, an unseen-value screen, the deterministic strict pass, the outcome matrices, Critical-failure candidates, review reasons and one primary failure cause with secondary flags. The summary is schema version 2 (old fields unchanged). `cap_stopped`, `failed`, `scored` and `scored_partial` rows are counted separately. The screen is a screen, not a verdict, and nothing here says a claim is supported; see ticket 03's Findings for the rules, the cause table and the blind spots. `stats.py` holds the paired exact test, bootstrap intervals and repeat statistics.

**Negation groups in `must_include` (corrected 2026-11-24).** A required-fact group made only of "not" / "no" (the false-premise cases `nep03` and `pu03`, and `td02`, `td03`) is now also met by a contracted negation such as "don’t", "isn't" or "can’t" (either apostrophe). `text.norm` turns the apostrophe into a space and matching is whole-token, so a correct refusal like "The documents I found don’t state that ..." used to fail the deterministic answer stage. The change is in `score.py` (`group_satisfied`, used by `answer_score` and `fact_recall`) and applies to those groups only; `text.contains` and `text.norm`, dataset validation and every other scorer are unchanged, and the refusal judge is unchanged (it is still the only check that a premise was really corrected; the lexical check only asks for a negation word). **Rescoring older results can change scores.** `cli rescore FILE` recomputes the deterministic stages from the stored reply, so a result saved before this date can score a contraction-style reply as correct where the stored row says it failed. Rescore writes a new `_rescored` file and never edits the original, so historical result files stay as they were; do not compare a stored and a rescored number as if one rule produced both. "cannot" and "never" are still not accepted forms.

**Limit of the deterministic negation screen (2026-11-24).** A negation word in an answer shows only that the word is there. It does not show that the answer corrected a false premise, said what the documents do establish, or avoided inventing the event; a reply can contain "not" and still assert the false premise, and a correct refusal can lack the accepted forms. Do not extend the screen with more negation keywords to approximate semantics. The lexical result is not evidence of semantic correctness; the refusal judge, the claim-support grader and manual reading are. The calibrated claim-support and refusal graders belong to M1 tickets 09 and 10 and are not built. Stored results and their historical scores are unchanged.

**Claim-check diagnostics (`cli run --trace-claim-check`, off by default).** For each case, the row's `trace.claim_checks` records the draft answer before the check, its statements, the checker's raw reply and decisions (raw labels, labels kept after the framing filter, labels ignored as framing), the evidence it could receive (chunk ids, character spans, `full`/`partial`/`none` sent, truncation, hashes; no document text), the user messages it was given, model and latency, and the outcome. The outcome separates what the checker **flagged** from what was **observed** in the answer text: `removed_statements`, `flagged_not_removed`, `collateral_removed` (an unflagged copy of a flagged text that also went; the application no longer does this since KI-035 was fixed, so a non-empty value in a new run is a defect, as is `flagged_not_removed`; older result files can contain both), `uncertain` (cannot be attributed; nothing is claimed) and `unattributed_change`, next to the application's own `reported_removed_count` and `counter_matches_observation` (see KI-035 in `docs/KNOWN_ISSUES.md`). `trace.claim_check_metering` carries the case's claim-check tokens and dollars by role (the meter counts per case, not per call). The result file then holds draft answers and the user's messages: it stays in the Git-ignored `results/` folder and is never committed. The flag is refused for the held-out pool, nothing is written to application logs or API responses, and no application code changed (the recording wraps the application from `evaluation/rag_eval/claim_trace.py`). `pilot_gate --run-id RUN --strategy S --ids ... --require-claim-trace` additionally stops a result that lacks the diagnostics where a check must have run; rows with no retrieved evidence, a failed or intent-gate run, a disabled check, or a record that says why the check was skipped or failed open are accepted.

Every `run` result file carries a `manifest` (schema version 1): the audited commit and whether the tree was clean, every answer-relevant setting, digests of the prompts and tool descriptions, corpus and dataset checksums, the price-table date, concurrency, repeat index and count, library versions, the cap and the spend. The evaluation settings are pinned to the application's code defaults (`target.ANSWER_FIELDS`), whatever the local environment says; only `--model`, `--threshold`, `--relative`, `--no-claim-check` and `--retrieval-strategy {A,C2-cap3}` change them (the last selects single-query or dual-query first-search retrieval explicitly; the manifest and result file record it under `retrieval_strategy`; see `docs/tickets/hybrid-retrieval-comparison/02-answer-quality-pilot.md`), and the manifest lists such differences under `deviations_from_default`. Files written before the manifest existed can still be re-scored.

## The frozen evaluation corpus (M1 ticket 04)

The corpus that the v1 question sets are written against. It is **synthetic or public**: the 22 older synthetic text files (Larkspur Systems), the five generated Office and PDF files (`messy/`), 19 new files about a second invented company, the Marrowdale Freight Cooperative (`corpus/v1/`), and the 33 public PDFs (not committed). Nothing in it is private, and no invented fact can be known from a model's training data. `corpus/v1_manifest.json` freezes it. Everything below is free: no key, no model, no embedding, no network, no Google.

| Command (from `backend/`) | What it does |
|---|---|
| `uv run python -m evaluation.rag_eval.corpus_v1 --check` | Rebuilds every v1 file in memory and compares the bytes, then runs every manifest check through the product's own readers. Exits non-zero with one line per problem. |
| `uv run python -m evaluation.rag_eval.corpus_v1 --report` | Prints the format, size and chunk-count table. |
| `uv run python -m evaluation.rag_eval.corpus_v1 --write` | Rewrites the v1 files and the manifest. Only for a deliberate corpus change; this changes the corpus version. |
| `uv run python -m evaluation.rag_eval.corpus_v1 --google declined` | Records the Owner's decision about Google exports (`pending`, `pinned` or `declined`). |
| `env -u OPENAI_API_KEY uv run pytest tests/evaluation/test_corpus_v1*.py -q` | The builder, manifest and extraction tests. |

**What the manifest records for each file:** path, format, group (`synthetic`, `messy`, `v1`, `google`), source (`generated`, `public` or `Google export`), generator version, SHA-256 of the bytes, SHA-256 of the text the product's readers extract, character and chunk counts, at least three canary strings and tags (long, injection kind, superseded pair, same-name entity). The **corpus version** (`m1-corpus-v1-<12 hex>`) hashes the file bytes and the public manifest, so it changes only when a document changes. The **text digest** is separate on purpose: when a reader changes (M6), the smoke test fails with "extracted text changed", you review the difference, and only then rewrite the digest. A reader change is a visible event, not a silent new corpus.

**What the free checks catch:** a missing file, a changed file (checksum), a file in the folders that is not in the manifest, duplicate paths, unknown source or group, a missing field, a wrong corpus version, fewer than three canaries, a canary the reader no longer finds, changed extracted text or chunk count, a long document under four chunks, the short deck no longer one chunk, an embedded instruction that a reader drops or alters, a Google-export status that is not `pending`, `pinned` or `declined`, and a corpus that no longer meets the ticket's counts. `tests/evaluation/test_corpus_v1_manifest.py` proves each one by breaking a copy of the corpus. The ticket's reader-defect checks (a table row lost, a sheet skipped, notes ignored) are in `test_corpus_v1_extraction.py`.

**What this is not:** corpus validation, not RAG quality. Passing these tests shows that the documents are what they claim to be and that the readers keep their facts and instructions; it says nothing about retrieval or answers. The generated files are cleaner than files saved by Word, Excel or PowerPoint; the Google exports reduce, but do not remove, that gap.

**Same-machine note.** DOCX, PPTX and XLSX files are zip files compressed by zlib, whose output can differ between builds. The manifest records the zlib version it was written with (`built_with`); the two tests that compare a fresh build with the committed bytes skip, with a stated reason, on a machine with another zlib. `corpus_v1 --check` always compares.

### Google-exported fixtures: done 2026-11-22 (no agent calls Google)

The three exports are pinned (`google_exports.status = pinned`, source `Google export`). The sheet tab in the pinned file is named `Sheet1`, not `Rota`; nothing depends on the tab name. The steps below stay as the record of how to recreate them. Creating them again changes the corpus version.

Real files made by Google behave differently from generated ones, so the spec asks for three. The steps take about an hour. Use a **throwaway Google account** with nothing in it; do not use your own Drive.

1. Make a Google **Doc**. Paste this text (one paragraph per line) and give the file any name:
   `Open day notice` / `The Wren Hollow open day takes place on Saturday 17 October 2026.` / `Gates open at 10:00 and the last tour leaves at 15:00.` / `Parking is free in the lower yard. Bring your membership number.`
   Then File, Download, **Microsoft Word (.docx)**. Rename the download to `google_open_day_notice.docx`.
2. Make a Google **Sheet**. Name the tab `Rota`. Put this in cells A1:D4 (header in row 1): `Name | Role | Start | Budget (GBP)`, `Tamsin Rooke | Tour guide | 10:00 | 320`, `Emlyn Brask | Car park | 09:30 | 150`, `Odile Wray | Catering | 09:00 | 480`. File, Download, **Microsoft Excel (.xlsx)**. Rename to `google_open_day_rota.xlsx`.
3. Make Google **Slides** with three slides. Slide 1: title `Open day briefing`, subtitle `Wren Hollow, 17 October 2026`. Slide 2: title `Roles`, bullets `Tour guides meet at 09:30` and `The fire marshal wears orange`. Slide 3: title `Safety`, bullet `Visitors gather at assembly point C`, and in the speaker notes `Count visitors at the gate on arrival and departure.` File, Download, **Microsoft PowerPoint (.pptx)**. Rename to `google_open_day_briefing.pptx`.
4. Put the three files, with exactly these names, in `backend/evaluation/corpus/google/`. Do not edit them.
5. From `backend/` run `uv run python -m evaluation.rag_eval.corpus_v1 --write`, then `--check` and `uv run pytest tests/evaluation/test_corpus_v1*.py -q`. The manifest then lists the files with source `Google export`, their checksums and text digests, and the **corpus version changes**. A failure naming a canary means the product's reader lost something in a real Google file: do not fix the file; report it, because it is a reader defect for M6.
6. **To decline instead:** run `uv run python -m evaluation.rag_eval.corpus_v1 --google declined`, and write "Google-exported files not covered" in the ticket and in `docs/specs/m1-rag-evaluation.md` (the Google-native files line). Ticket 11 then proceeds on that basis and the gate row stays open.

Do this **before** the question tickets (05 to 07) are written, so the corpus version does not change after cases exist.

### Public documents: licences

No public document was fetched or changed by this ticket (`fetch_public` was not run; the new modules contain no network code). The 33 PDFs are listed with their SHA-256, source and licence evidence in `backend/evaluation/corpus/public_manifest.json` (verified 2026-11-19) and are never committed:

| Licence as recorded in the manifest | Documents |
|---|---|
| Creative Commons, per arXiv metadata for the paper (CC BY 4.0 or CC0) | 22 arXiv papers |
| US Government work, not subject to copyright (statement printed in the document); NIST notes that third-party material inside may carry its own rights | 11 NIST publications |

They are used as unmodified noise text only.

## The frozen question set (M1 ticket 05)

One question set, three named pools, and the machinery that keeps it honest. Everything below is free: no key, no model, no network. Ticket 05 wrote no cases; ticket 06 wrote the new development cases (`rag_v3_dev_cases.json`, below) and ticket 07 wrote the held-out ones with this machinery.

| Pool | What it is | Where it lives |
|---|---|---|
| `development` | the old `dev` cases (120) plus new development cases; may be tuned against | `backend/evaluation/datasets/` |
| `regression` | the 81 old `test` cases; seen and used as vetoes, so no longer held out; run in every comparison, never presented as generalisation | the same four files |
| `held_out` | at least 100 new sealed cases, scored once per checkpoint, reported only as aggregates | **one file outside the repository**, found through `DRIVEMIND_EVAL_HELDOUT_FILE`; the Owner must back it up |

The four existing case files are never edited and never relabelled on disk: `split` keeps `dev` and `test`, and the pool is assigned at load time (`pools.py`). `--split dev|test|regression|held_out|all`: `all` is development plus regression and **never** includes held-out; `held_out` runs only when named, whole, once (no `--ids`, `--category`, `--limit`, `--repeats`).

| Command (from `backend/`) | What it does |
|---|---|
| `uv run python -m evaluation.rag_eval.pools validate [--with-public]` | Validates the committed question set against the frozen corpus through the product's own readers. Exits 1 on any problem. Public PDFs only with `--with-public` (minutes). |
| `uv run python -m evaluation.rag_eval.pools validate --held-out` | Validates the sealed file (needs `DRIVEMIND_EVAL_HELDOUT_FILE`) against the frozen corpus and the committed set. Prints the number of cases and a count per broken rule; **never** a case id, question, quote or value. Exits 1 on any problem. |
| `uv run python -m evaluation.rag_eval.pools review-sheet OUT.md [--size 30] [--seed 1]` | Writes the Owner's review sheet (a stratified sample with question, reference answer, anchor quote and file) to `OUT.md`, which must lie **outside** the repository; prints counts per shape only. |
| `uv run python -m evaluation.rag_eval.pools attest-review SHEET.md` | **Owner only; never run by an agent or a script.** Reads the Owner's marked review sheet and writes `<sealed stem>.review-attestation.json` beside the sealed file. Needs an interactive terminal and a typed phrase. Refuses unless the freeze checksum equals the sealed file's, every sheet case is in the sealed file and matches it, each has exactly one box ticked, at least 30 are reviewed and none is "gold wrong". Records review only, never spend approval. |
| `uv run python -m evaluation.rag_eval.coverage [--require-held-out]` | Prints counts per pool against the spec's minimums. Exits 1 while a whole-set minimum is unmet; `--require-held-out` also enforces the held-out minimums (without it a hollow held-out pool could pass the whole-set check, and the report says "held-out minimums NOT enforced"). Prints counts only, never case ids. |
| `uv run python -m evaluation.rag_eval.freeze check` | Verifies every frozen file against the manifest and the amendment log; verifies the held-out file's checksum when the environment variable names it. |
| `uv run python -m evaluation.rag_eval.freeze amend FILE --reason TEXT [--cases ID ...]` | The only way to change a frozen case file: writes the log entry and the new checksum together. |
| `uv run python -m evaluation.rag_eval.freeze add FILE --reason TEXT` | Registers a new case file (logged as an addition). A case file the manifest does not list fails `check`. |
| `uv run python -m evaluation.rag_eval.freeze seal-held-out --reason TEXT` | Records the sealed file's checksum and its counts per gate group (no ids) in the manifest. |
| `env -u OPENAI_API_KEY uv run pytest tests/evaluation/test_question_set.py tests/evaluation/test_question_freeze.py tests/evaluation/test_sealed_reporting.py tests/evaluation/test_held_out_set.py -q` | The free tests for all of the above. |

**Owner-review gate (M1-07-F).** `pools.load_held_out` refuses by default (`ReviewRequired`, no case named) unless the attestation beside the sealed file exists, is well formed, records at least 30 reviewed, all correct and none gold wrong, and its sealed SHA-256 equals both the file's current hash and the freeze manifest's `held_out` checksum. Amending the sealed file (`freeze seal-held-out`) changes its hash, so the old approval ends and the Owner reviews and attests again. Paid held-out work (`cli run --split held_out`, including `--plan`, and any future probe that measures held-out cases) must load the pool through this door. Free commands (`pools validate --held-out`, `coverage`, `freeze check`, `pools review-sheet`) pass `require_review=False` and need no attestation. **Limits:** the attestation is a plain file, so it stops an accident, a stale review and a normal run, not someone who can write files on the Owner's machine and forges it; it covers the 36 sampled cases, not all 180; and it is not spend approval, which stays the Owner's separate act per paid ticket (the `--plan` estimate and the cap).

**Schema v3** (a case that declares `"schema": 3`; older cases keep the older rules). Extra fields: `provenance` (`{"session": "m1-06-dev-a", "date": ...}`: an author session, never a person), `tags` (a closed list, each checked against the case's own fields), optional `formats` (must equal the evidence files' formats), `critical` with `critical_kind` (one of the four kinds in the glossary entry), `injection_document` (a corpus file the manifest tags `injection:*`), `sibling_exempt`. The behaviour `clarify` is new: the correct reply is one short clarifying question; its anchors are the competing readings, its forbidden claims are the readings' values, no fact is required, and it cites nothing. It is judged by its own expectation text in `judge.py`; a reply with no `?` fails in code without calling the judge; a citation or a guessed reading fails the `clean` stage as for small talk.

**Required fields (every case, old or v3):** `id`, `category`, `question`, `language` (`en` or `roman_urdu`), `expected_behavior`, `expected_files`, `citation_mode`, `must_include`, `must_not_include`, `reference_answer`, `evidence_anchors`, `computed` and `split`, each of the right type; a v3 case also needs `tags`; optional fields (`history`, `critical`, `critical_kind`, `injection_document`, `sibling_exempt`, `judge_note`, `formats`) must have the right type when present. A case that fails this gets one line per field (`<id>: required field <name> is missing or invalid`, never the value) and no other rule is run on it; the validator never raises on a malformed case (`schema_v3.required_field_problems`, called first by `dataset.validate`). In the redacted sealed-pool report these lines are one rule, "a required case field is missing or invalid".

**Rules the validator adds for v3 cases:** every anchor quote identifies **one** file (a quote that also occurs in a superseded or near-duplicate document is rejected); **sibling values**: the other values the same field takes elsewhere in the corpus (the rest of the same table column and the same-named column in other tables, or the number after the same few words) must be in `must_not_include`, or in `sibling_exempt` when a correct reply may mention them, so a verbose reply that lists many values does not pass. The generator is `schema_v3.sibling_values`; it is a validation requirement, not a silent merge, so the frozen file shows the full list. For every case, old or new, the history is checked against the production bound: at most 6 prior messages and 6000 characters, stated once in `schema_v3.py` and pinned by a test to the agent's own check.

**Freeze.** `datasets/m1_freeze.json` holds the SHA-256 of every frozen case file (`sha256` current, `frozen_sha256` the anchor), case counts per pool, the corpus version id and the pool mapping, and for the sealed file only its checksum, case count, counts per gate group and its injection documents. `datasets/m1_amendments.json` lists every change: date, file, case ids, reason, checksums before and after. `phase: history` entries were entered from the results history and git (the `vi06` to `vi08` change, the `id10` gold, the three `ag05`/`pb05`/`td01` sources, the anchor shortening, the trap-set additions); `post_freeze` entries are written by `amend`, `add` and `seal-held-out`. `check` fails when a file differs from the manifest, when the manifest differs from `frozen_sha256` with no log entry behind it, when a chain is broken, or when a case file is unlisted. It cannot stop someone who rewrites the manifest, the log and the file together; git shows that.

**Sealing.** The held-out file is refused if it lies inside the repository. Anything a run prints, logs, summarises or commits shows that pool only as a total plus the gate groups, and **suppresses every cell under ten cases**, including a rate that rests on fewer than ten decided rows (`sealing.py`; `score.summarise` applies it to any row whose pool is held-out). Per-case held-out rows are written to a `heldout_results/` folder beside the sealed file, without reply, question, queries or snippets. `sealing.committed_view` is what a committed baseline may carry; `leaks` and `small_cells` are the checks the tests run. To diagnose a held-out case, move it to the development pool with an amendment-log entry; it stays in earlier checkpoints' denominators. There is no reserve and no reveal flag.

**Development cases (M1 ticket 06).** `datasets/rag_v3_dev_cases.json` holds 81 schema-v3 cases in the development pool, all about the second invented company (Marrowdale, `corpus/v1/`) and the three Google exports. They were written from the extracted corpus text only: no system output and no result file was read, and each case carries a provenance session and date. They cover Critical-failure shapes (instructions embedded in the DOCX, XLSX, PPTX and PDF documents; a named file or edition that does not exist beside a similar one that does; the same name in two files; content that belongs to another file; a plausible zone, year or measurement that does not exist), ambiguous questions with one clarifying question as the correct reply, follow-ups, calculations and table lookups on the new XLSX, DOCX and CSV files, multi-file questions that anchor every listed file, and identifier questions. Each ambiguous case anchors every reading with the depot, crossing or service name that tells the readings apart, so a clarifying question can be recognised by the words it uses. `tests/evaluation/test_question_set.py` pins that development plus regression meet every minimum that does not depend on the held-out pool (the whole-set minimum less its held-out share; table lookup and the eight cases per promised format in full), that no reference answer contradicts its own checks, and that a case's sibling values do not change when unrelated documents are added. The whole-set shortfalls that remained after ticket 06 were the held-out share, which the sealed pool below now supplies.

**Sealed held-out pool (M1 ticket 07).** 180 schema-v3 cases in one file outside the repository (on the Owner's Mac: `~/.drivemind-eval-sealed/m1_held_out_cases.json`; **back it up, the repository does not hold it**), registered in the freeze manifest by checksum and counts per gate group only. They were written in one session (`m1-07-held-a`, 2026-11-22) from the extracted text of the frozen corpus (`m1-corpus-v1-a605f90dc57b`), all about the second invented company and the three Google exports; **no result file, run output or system answer was read**. Sections of the long documents (cold chain manual, bylaws, customs guide, runbook, handbook, annual report, Q3 review) that no development or regression anchor uses are used by held-out questions only; a case is not copied from a development case (no identical question). Counts per gate group are in `m1_freeze.json`; `coverage --require-held-out` passes on them, with or without the sealed file. Three checks protect the pool without showing it: a reference answer must pass its own deterministic checks (`schema_v3.reference_problems`, applied to every v3 case), the redacted `pools validate --held-out` (counts per rule only; id collisions and duplicate questions against the committed set are counted too), and `sealing.leaked_cases`, which counts tracked files that give away a held-out id, question or reference answer (text already public in the corpus or in the committed references does not count). The Owner review sheet is a separate file beside the sealed one; its result is recorded in the ticket, as counts. **The review must be complete before the first paid step (ticket 08) and ticket 11; it is not an approval of spend, and no file or flag in the repository records it.** Dataset correctness is not system quality: nothing here has been run against the product.

**What this is not:** dataset correctness and bookkeeping, not RAG quality. A valid case shows that its quotes exist verbatim in the documents the product extracts and that its forbidden claims are absent or bounded; it says nothing about whether the system answers it. Counts of cases are not measures of retrieval or answer quality.

## What to measure

The implemented diagnostics can help answer:

- **Routing:** Did the top-level route match the labeled expectation?
- **Retrieval:** Did expected files survive candidate retrieval, merge/rerank, and final prompt selection? File-level hit/recall and reciprocal-rank measures collapse repeated chunks from one file.
- **Grounding:** Were expected sources in the prompt and in normalized citations? Did required phrases appear, and were forbidden phrases avoided?
- **Abstention:** Did the system answer or decline appropriately when evidence was absent?
- **Latency and rewrites:** How many retrieval attempts occurred, and where was time spent?

Human review is still needed to judge whether an answer's claims are supported and useful. The recorded review packets and experiment decisions show how that review has been applied; deterministic metrics alone do not prove answer quality.

## Future work

Broader held-out datasets, calibrated human scoring, and optional LLM-as-judge comparisons can extend the current tooling. Any new results should identify the dataset version, corpus fingerprint, configuration, Git revision, and review method. Avoid treating proposed target thresholds or unexecuted commands as measured results.

See [Retrieval](RETRIEVAL.md), [LangGraph](LANGGRAPH.md), and [Current Status](../CURRENT_STATUS.md).

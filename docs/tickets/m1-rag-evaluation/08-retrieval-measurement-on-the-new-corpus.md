# 08: Retrieval measurement on the new corpus

**Spec:** docs/specs/m1-rag-evaluation.md
**What to build:** The evaluation index is rebuilt for the frozen corpus, and the retrieval baseline is measured at passage level: is the chunk that holds the answer among the retrieved chunks, and how high does it rank, both when the question itself is the query (an upper bound that costs embeddings only) and when the model writes the query (what the agent really does). This is the first paid step, so it also re-reads the price table. It also builds the one evaluation index that every later paid ticket uses.
**Blocked by:** 02, 03, 04, 05, 06, 07 (including the Owner's held-out review: a gold error would otherwise be measured).
**Status:** ready-for-agent
**Progress:** open

## Scope

- **Before any spend, two separate gates, both recorded here:** (1) the Owner's review of the held-out review sheet is complete (ticket 07 `## Findings`, "Owner review": cases checked, errors found, corrections applied; gold errors corrected through `freeze seal-held-out --reason ...`); (2) the Owner approves the paid spend after seeing the `--plan` estimate (spec decision 1). The first does not imply the second. Then re-read the provider's pricing page for every model the harness uses (chat, claim check, grader, embedding), update the price table with its date, and print the `--plan` estimate. The Owner reads the provider balance and approves the cap (spec decision 1). Record both here. Reading a public page is not a provider API call.
- Rebuild the evaluation index for the frozen corpus with the existing setup command, recording the embedding model, dimension, chunk count per file and the extraction pipeline version in the manifest. This is the embedding spend (an estimate of about 0.05 USD; the older rebuild was about 0.02 USD for a smaller corpus), and the probes (about 340 cases times two repeats at about 0.00027 USD each).
- Extend the retrieval probe to passage level using ticket 03's mapping: anchor-chunk recall at the production top-K, rank of the first anchor chunk and its mean reciprocal rank, file recall, distinct files per result, for the plain question and the existing lead-in wordings; reported by pool, category, format and language. For cases that should be refused, report the best-score distribution as the earlier probe did (the finding that a score cannot decide refusal is rechecked, not assumed).
- Extend the first-step probe to record the model-written queries and their anchor-chunk recall, two repeats per question (the model's first move is not deterministic even at temperature zero), using the real tool descriptions and the real retriever as today.
- The plain-question probe covers held-out cases once, as totals and gate groups; the model-written-query probe with repeats uses development and regression cases only.
- Write the results as a committed section in `docs/EVALUATION_RESULTS.md` and local result files.

## Out of scope

Any answer run, grader, judge, change to thresholds, chunking, fusion or tool wording. A retrieval defect found is registered, not fixed.

## Inspect

`backend/evaluation/rag_eval/retrieval_probe.py`, `first_step_probe.py`, `target.py`, `prices.json`; tickets 02, 03 and 04 `## Findings`; `docs/EVALUATION_RESULTS.md` ("Retrieval probe", "Step 1a", "Step 1b", "Step 1c") for the earlier method and numbers; `docs/KNOWN_ISSUES.md` (KI-022, KI-027, KI-030).

## Deliverables

Extended probes with free tests; the rebuilt index; the results section; `## Findings` with the spend, the price table date and the first retrieval-by-format table.

## Needs

Disposable PostgreSQL and Qdrant containers. Embeddings for the rebuild and the probes, plus one chat call per question per repeat for the first-step probe: **estimate about 0.25 USD, cap 0.40 USD**. The Owner approves the spend when the ticket starts.

- [ ] Ticket 07's Owner review is complete, recorded in ticket 07, and bound to the sealed file by the Owner's `pools attest-review` (the loader refuses without it) before any call; the Owner's separate approval of the estimate and cap is recorded here. Neither stands in for the other.
- [ ] The price table is dated within the session and covers every model used; the dry-run estimate and the Owner's approval are recorded.
- [ ] The index holds exactly the frozen corpus (file and chunk counts match the manifest); a rerun of the plain-question probe gives identical file and rank results (only raw scores may move in the third decimal, as before).
- [ ] Results are reported by pool (development, regression, held-out aggregate), category and format with Wilson intervals; the earlier file-level figures are reproduced on the old cases as a sanity check against the history (differences explained by the larger corpus).
- [ ] The agent-query probe reports the model-written queries' anchor-chunk recall next to the plain-question recall, and the gap is stated.
- [ ] Measured spend is at most the cap and is recorded with the meter's per-role figures; the free tests for the new probe logic pass without a key.
- [ ] Any retrieval defect found is registered with the reproducing case ids; none is fixed. `git diff -- backend/app` is empty; touched evaluation files pass `ruff check`, `ruff format --check` and `mypy`; the container-free evaluation tests pass.

## Comments

### M1-08-B-Fix (2026-11-23): fresh frozen store, deep verification, gated commands

- **Store.** Frozen commands use their own store, `drivemind_eval_v3` (PostgreSQL database and Qdrant collection of the same name; `--store vN` picks another). v2 is the legacy store: frozen commands refuse it, and the refresh of stale documents is refused on it. `assert_safe` now also requires the database and the collection to be the same store.
- **Rebuild.** `cli setup --frozen [--store vN]` extracts every original file, refuses to continue if the text or chunk count differs from the frozen manifests, embeds, then verifies chunk by chunk and vector by vector; only a passing run writes the receipt (`origin: "setup"`). Documents made by an older extraction pipeline are re-read and refreshed in a frozen store; the legacy path is unchanged.
- **Gate.** `cli run` / `cli rescore` / `retrieval_probe` / `first_step_probe` with `--frozen` call `index_verify.require_verified_index` before any paid call and use the settings it returns. A missing or invalid receipt, a stale or incomplete store or an unreadable Qdrant or database stops the command. `--plan`, dataset validation and `index_verify verify|check` stay free. The held-out review attestation is a separate check and runs first.
- **Estimate.** `setup --plan` prices the chunked text (UTF-8 bytes / 3, safety margin 1.2, overlap included) at the recorded `text-embedding-3-small` price: 0.0335 USD for 1,508 chunks, down from the 0.244 USD that came from compressed PDF bytes. No price was changed.
- **Not provable without a paid call:** that a stored vector is the embedding of its chunk's text, and which embedding model made it (Qdrant does not store it; the setup receipt records it). The paid rebuild into v3 has not been run.

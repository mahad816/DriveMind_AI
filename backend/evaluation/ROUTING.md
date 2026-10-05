# Offline routing benchmark

From `backend/`, run `.venv/bin/python -m evaluation.routing_runner`.
The runner validates `datasets/routing_v1.json`, observes the unchanged original
first-pass classifier, and writes JSON under the ignored `evaluation/results/`.
`--dataset` and `--output-dir` override paths. No RagService execution, reference
rewriting, retrieval, generation, provider calls, or live storage is involved.

Gold contains 70 SINGLE, 30 COMPOUND, and 20 CLARIFY cases. Ordered requests and
optional argument constraints describe desired semantics. Dataset policy notes
specify modified-time recency, filename default ordering, history availability,
and content/topic boundaries. No META label is active.

The adapter emits one observable action, not a claim of semantic SINGLE intent.
Mode accuracy exposes this representation limit. Follow-up eligibility records
the current gate, not whether rewriting would succeed. Confidence is absent.

Six-route accuracy/confusion use only SINGLE gold. Capability precision/recall/F1
use multiset matching across SINGLE/COMPOUND: one FILE_TARGET prediction covers
only one of two summaries. CLARIFY has no gold capability and is scored separately.
Compound omission counts uncovered requests at capability granularity, not full
operation/argument correctness. Social-decoration false positives count CHITCHAT
predictions on cases tagged social_decoration, including decorated compounds.

Operation coverage credits only singleton vocabularies: RECALL, RESPOND,
SUMMARIZE_EACH, ANSWER. Inventory/file-target operations remain unknown. Coverage
counts unknowns as uncovered; inferable accuracy has a separate denominator.
Arguments and ordering are stored but unscored by the legacy adapter.

Artifacts include UTC timestamp, Git SHA/branch/dirty state, dataset and source
hashes, complete gold inputs, and predictions. Dirty runs are permitted because
this task prohibits commits. This is a development benchmark, without a held-out
split; freeze independent test families before tuning a semantic provider.

Older service tests use normal-mode identity assumptions. If local configuration
enables demo mode, use:

```bash
DEMO_MODE=false .venv/bin/python -m pytest tests/evaluation tests/retrieval/test_query_router.py tests/retrieval/test_file_target_routing.py -q
```

## Frozen development benchmark checkpoint

`routing_v1` / schema `routing-1.0` is frozen for the first Jev development
comparison. Exact dataset SHA-256:

```text
4831a76ee7e782e968a0224e6b935729712ba21e2eb25617a2cddbe268549884
```

Do not tune these cases against future provider results. Genuine gold corrections
must be documented in a new dataset version, with old/new hashes and affected case
IDs; retain this file for comparable historical results. This development set is
not a held-out test set. Similar paraphrases are deliberate coverage, and repeated
question text has different supplied histories; there are no duplicate full inputs.

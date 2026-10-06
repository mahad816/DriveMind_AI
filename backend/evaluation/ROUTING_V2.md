# Frozen held-out routing_v2

This is synthetic held-out gold for the already-frozen v2 router. No provider
predictions or provider calls were used to author or validate it. routing_v1 and
smoke source questions were consulted only for the offline leakage audit, not as
a template for one-for-one failure paraphrases. The contract must remain frozen
through the first measurement. This task does not implement a live runner.

The freeze manifest is `datasets/routing_v2_freeze.json`; it records the UTC freeze
time, exact dataset/fixture/schema hashes, contract lock hash, acceptance targets,
and complete subgroup counts. Hashes must be checked before a future evaluation.
Corrections to erroneous gold require a documented new dataset version and hashes;
never adjust gold in response to provider choices during measurement.

There are 180 cases: 100 supported ONE cases, 35 supported TWO and 10 supported
THREE cases, and 35 safety/readiness cases. Cardinality across all cohorts is
123 ONE, 45 TWO, 10 THREE, 2 OVER_LIMIT. No artificial UNINTERPRETABLE examples
were added: vague but recognizable file/topic requests test resolution/readiness.

Seven metadata snapshots and ten bounded conversation states are wholly synthetic.
Metadata eligibility is explicit: lookup exposes only visible, indexed files owned
by the synthetic user. Hidden and pending files are present in one snapshot to
verify that timestamps cannot override eligibility. Canonical collision, duplicate
raw name, null timestamp, tied recency, and empty snapshots are separate controls.
Context fixtures retain prior substantive focus through chitchat, failed requests,
and clarification. Their provenance notes distinguish authored state snapshots
from a claim that persistence/update integration exists.

Gold requests retain ordered capability/operation/reference labels and per-request
readiness. Semantic reference labels are independent of request-local candidate IDs;
offline materialization binds them to the application-owned prepared registry.
Explicit runtime dependencies have a non-executable special outcome; implicit
same-bundle dependencies retain their requested operations and unsupported readiness.
This avoids conflating semantic interpretation with resolution. Unsupported comparisons,
writes, filters, and over-limit requests have explicit non-executable gold.

Source and query ranges use half-open Python Unicode codepoint offsets into the
original question. Alternative ranges allow harmless terminal punctuation and
structural connective prefixes. Compound clause ranges are gold provenance labels,
not a change to router segmentation. Capability/operation accuracy is scored
separately from span quality. Broad compound spans remain measurable model errors.

## Scoring policy for the later runner

- Count provider, preparation, translation, and structural failures as incorrect;
  separately report availability/validity and explicit denominators. Do not drop them.
- Score Stage-1 cardinality on every case, including special outcomes. OVER_LIMIT
  must not fabricate Stage-2 work. Score repeated operations as a multiset, preserve
  request order, and report ordered exact bundles separately from operation recall.
- Report ONE capability/operation accuracy on all ONE cases with request gold,
  including recognized intent whose downstream readiness requires clarification.
  Report unsupported semantic outcomes separately, not as invented capabilities.
- Report semantic supported/unsupported decisions separately from bundle readiness:
  unresolved references are recognized operations; unavailable files are not provider
  ambiguity. Implicit dependency bundles require UNSUPPORTED readiness.
- Evaluate the resolver independently using authored gold (offline), and evaluate
  end-to-end readiness using actual future predictions. A correct resolver receiving
  the wrong semantic input is not a resolver defect; a wrong READY outcome is still
  a safety failure. Never report executions: this dataset evaluates execution readiness.
- Unsafe READY is any predicted READY for gold clarification/unsupported, a stale or
  ineligible target, a dependency made executable, or an unsupported operation made
  executable. Also instrument unknown/provider-generated option acceptance; synthetic
  gold cannot by itself verify the adapter's structural rejection tests.
- False rejection is NEEDS_CLARIFICATION/UNSUPPORTED on gold READY cases. Report
  false clarification separately. Provider failures count against routing success,
  but are operational failures rather than semantic clarification predictions.
- Report by capability, operation, difficulty, tags, metadata snapshot, and state.
  The manifest freezes targets; span-only errors do not automatically fail architecture
  unless their execution consequences are material. Small subgroup intervals matter.

## Leakage/privacy review

Normalized word/case/punctuation comparisons found no exact prior-question reuse.
SequenceMatcher threshold 0.80 found no near matches against routing_v1 or smoke.
Internal threshold 0.88 flagged only v2-025/v2-156: an intentional filename/misspelling
control with different readiness. This textual audit cannot prove semantic independence;
common product intents necessarily recur. Literal difficulty is 22/180, so easy cases
are a minority. Only invented names, IDs, dates, and dialogue appear in fixtures.

Run offline validation with `DEMO_MODE=false .venv/bin/python -m pytest
 tests/evaluation/test_routing_v2_dataset.py -q`. No test calls a provider.

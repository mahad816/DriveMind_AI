# Frozen coverage_v1 comparison pairs

80 fixed question/proposal pairs, not routing cases. All data are synthetic.
Development: 32 pairs (14 PRESERVED, 18 MISMATCH), including the eleven measured
unsafe routing_v2 proposals, seven faithful counters, and seven independent paired
scenarios. Held out: 48 pairs (24 PRESERVED, 20 MISMATCH, 4 UNCERTAIN). Related
question variants share a scenario group and never cross splits. Context fixtures
contain only bounded descriptors and snapshot hashes, not names, UUIDs or dialogue.

The held-out inputs were independently authored. Exact comparison against routing_v2
and a normalized-string review at 0.82 found no exact/near prior-question reuse or
cross-split near matches. Pairs sharing a question but changing the proposal are
intentional. The review is a textual audit, not proof of semantic independence.

UNCERTAIN gold is limited to genuinely unidentified antecedents where file/topic
or history/topic context descriptors cannot establish meaning. It is not a label
for nonexistent files, missing metadata, or a faithful unresolved reference.
A NON_EXECUTABLE representation of a supported contract limitation can be PRESERVED;
that verdict never authorizes execution of unsupported work.

`datasets/coverage_v1_freeze.json` records dataset/fixture/schema hashes, creation
UTC time, coverage contract identity, unchanged routing lock identity, counts and
review results. Gold was frozen before any verifier call. Never change gold to match
provider output; corrections require a documented new dataset version.

There is no live runner or routing integration in this task. Run offline checks with
`DEMO_MODE=false .venv/bin/python -m pytest tests/routing/test_coverage.py
 tests/evaluation/test_coverage_dataset.py -q`.

A future verifier benchmark should report false PRESERVED rates on mismatched and
uncertain proposals, false rejection on preserved proposals, failures separately,
probability diagnostics, and per-family latency/usage. Historical routing_v2 inputs
are development/regression evidence, not held-out generalization evidence. Same-model
routing/verifying errors can be correlated; no model-quality claims follow from the
mocked tests or the dataset's intended gold verdicts.

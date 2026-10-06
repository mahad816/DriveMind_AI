# Historical routing experiment checkpoint

Archive branch: `archive/jev-v2-baseline`.

Base/parent before the experiment checkpoint:
`fde794f6678dafe028a55ab7eca3cd544e794aa1` (`experiment/jev-router`).
This base inherits the public-demo history. Creating the checkpoint does not
change `main` or `demo/public-demo`.

This checkpoint preserves Jev v1, direct TypeSafe, the two-stage v2 experiment,
and the isolated semantic coverage verifier. These experiments are not activated
in production. The coverage verifier is historical evidence, not an integration
requirement for future routing work.

## Frozen identities

| Identity | SHA-256 |
| --- | --- |
| routing_v1 dataset | `4831a76ee7e782e968a0224e6b935729712ba21e2eb25617a2cddbe268549884` |
| routing_v2 dataset | `06559a24355c021d1b95fa788d9fbc02702f84ef7b47799205f825dae0c6eaa5` |
| routing_v2 fixtures | `519c9779cb0c5c4fa47f0744001f56df6a67e41eb6296c285a3fdef9563f9df2` |
| routing_v2 contract lock file | `8b85ec5fb3b0bd541d6eba59bb09af00eb96fcbc6c91ef000550dda75efef9c4` |
| coverage_v1 dataset | `e1100fff7923a13bc831fb1940f9eb39b2a172cbc82b22c53c30a9ce2c67f888` |
| coverage_v1 fixtures | `de9bdd210a5615d1e4b81444d450031024aec64fd92adacbbc4f64309f399082` |
| coverage contract manifest identity | `0bd05c2d48990bbb0defb031f2804a5422be697b1379b928069de419f57fd3dd` |
| coverage contract lock file | `7f172a36fde7bd927c261930986c8cbe60f9dfa3e7be4af35b68ebbf2a136a2c` |

The coverage contract manifest identity is computed from its source/schema/config
manifest; it is distinct from the byte hash of its lock file.

## External evidence preservation

Two independent sibling archives exist:

- `../INFO_VAULT-routing-evidence-archive/`
- `../INFO_VAULT-routing-evidence-archive-copy/`

Each contains `GIT_STATE.txt`, a redacted `PRIVACY_REVIEW.json`, and
`SHA256SUMS.txt`. The latter lists 1,471 regular files in sorted relative-path
order, excluding itself. Each archive contains 1,472 files and 49,804,761 bytes.
Every entry and both copies were independently verified before checkpointing.

Manifest SHA-256:
`8c874f516d36eedcc2bb66d0ed46740abac39d53f5c24738045df14a1effdee0`.

Important paths relative to each archive root:

- `backend/evaluation/results/typesafe_full_0aa25ecd77734966831ce0bd7ae584a3.json`
- `backend/evaluation/results/typesafe_full_0aa25ecd77734966831ce0bd7ae584a3.jsonl`
- `backend/evaluation/results/v2_smoke_1ef2f7bf9cd348a1b8ebc8838b210f28/`
- `backend/evaluation/results/routing_v2_full_03953edaf48545aab54300d3341f4f0d/`
- `backend/evaluation/results/coverage_development_91e914788f604ce1b1464b750c29ced9/`

Raw paid observations remain outside Git; the repository result tree remains
ignored. Preserve pending records, checkpoints, observations and their original
identities together. Do not replace historical observations with derived replay
results or repeat paid calls merely to recover evidence already retained.

## Public test fixtures

The original live-derived fixtures remain byte-for-byte in both external archives:

- `backend/tests/evaluation/fixtures/jev_legacy_routing001_artifact.json`
- `backend/tests/evaluation/fixtures/jev_list_all_files_live.json`

They are excluded from this checkpoint. Their public replacements are:

- `backend/tests/evaluation/fixtures/jev_legacy_routing001_synthetic.json`
- `backend/tests/evaluation/fixtures/jev_list_all_files_synthetic.json`

The replacements preserve all eleven historical semantic answer vectors but use
deterministic dummy timestamps/usage/latencies and remove unnecessary billing
metadata. They are synthetic regression envelopes, not original wire responses.
Only fixture references and dummy telemetry expectations changed in their three
reader tests. Historical datasets and routing/verifier contracts remain unchanged.

## Interpretation of historical evaluations

The completed direct v1 run represents 120 cases. The v2 smoke represents 15.
The full routing_v2 run represents 180 cases, 180 Stage-1 requests and 178
Stage-2 requests; its eleven unsafe READY outcomes remain historical results.
The coverage development run represents 32 pairs, with false PRESERVED 4/18
and faithful PRESERVED recall 7/14. The coverage held-out split was not called.

These evaluated datasets are regression/development evidence. Existing results
must not be relabeled as fresh generalization evidence for a revised architecture.

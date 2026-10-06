# Direct TypeSafe smoke comparison

Verified on 2026-10-05 against https://docs.typesafe.ai/api and
https://docs.typesafe.ai/models. Endpoint: POST https://api.typesafe.ai/v1/systemone;
Bearer TYPESAFE_API_KEY; state/model/questions; Choice and Noul answers plus usage.
Choice confidence is required. Returned model may resolve the requested alias to a
versioned ID; it is retained without assuming a pinned version is selectable.
Documented errors include 401, 422, 429 and 529. No automatic retry or Jev-org
idempotency/recovery is used. No documented provider latency field is assumed.

The user observed jev-latest and jev-preview through authenticated /v1/models.
This experiment requests ONLY jev-latest. It does not probe or use jev-preview or
attempt a pinned model. The existing Jev-org provider and all production paths
remain untouched. HTTP client dependency remains existing dev-only httpx.

Configuration in ignored backend .env or secure process environment:
TYPESAFE_API_KEY, TYPESAFE_BASE_URL (default https://api.typesafe.ai), TYPESAFE_MODEL
(jev-latest only), TYPESAFE_TIMEOUT_SECONDS (default 15). Key is SecretStr and
excluded from serialized configuration. Do not paste credentials into chat.

From backend:

```bash
.venv/bin/python -m evaluation.typesafe_runner
.venv/bin/python -m evaluation.typesafe_runner --execute-typesafe
```

The CLI supports only the frozen six smoke IDs, never the full 120. Without the
execution flag it makes zero external calls. Criteria/state match Jev-org exactly.
Model is the only intended request-body difference. Timer covers HTTP client setup,
connection/request/response and local validation/assembly, closely matching Jev-org.
Service latency remains unknown unless a documented field is added in a later task.

Artifacts use a separate typesafe_shadow_smoke prefix and explicit provider/base
URL/model/input/dataset/criteria/context/question-schema identity. Jev-org observations
cannot be reused. Completed direct observations may be reused only under that exact
identity; rolling alias results are a saved run, not proof the model remains unchanged.
Each case is checkpointed immediately to avoid duplicate calls after interruption.

This is NOT a model-version-controlled semantic comparison: Jev-org used jev-1.13;
direct uses jev-latest. Even equal-looking resolved IDs do not establish identical
weights or service configuration. Compare observed latency, reliability, token usage
and broad behavior; never attribute semantic differences solely to provider path.
Six cases are insufficient to establish production routing quality or tail latency.

## First live six-case result (2026-10-05)

Artifact: evaluation/results/typesafe_shadow_smoke_def748dd7e9f48dc895149b9f5b00ac0.json

All six POSTs returned HTTP 200. Cases 001, 019, 039, 051 and 071 produced valid,
correct label decisions; case 101 was INVALID_RESPONSE. Its original adapter path
did not retain intermediate validated fields, so the exact failed validator and
sixth-case token usage cannot be recovered from that artifact. No repeated paid
call was made. The adapter now retains safe validated fields and a validation-stage
diagnostic on future failures, covered by mocked tests; this is not criteria tuning.

Direct client milliseconds: 001=1144.804; 019=441.796; 039=618.374; 051=464.823;
071=509.618; 101=511.060. Median=510.339; nearest-rank p95=1144.804 (maximum of six).
No official upstream latency value was returned/recorded. First five returned model
jev-1.13.0 for requested jev-latest; sixth model was not retained by the initial
validation path. Mode/exact labels: 5/6; SINGLE routes: 4/4; operation coverage:100%;
compound omissions:0%; clarification miss:1/1 due invalid observation.

Known usage from five cases:17889 input tokens,3713 output tokens. Sixth usage unknown;
these are not complete six-case totals. Jev-org totals:21467 input,4439 output,6 credits.
Compare first five inputs directly:17889 for both; outputs direct3713 vs Jev-org3705.
Jev-org client median11452.077ms,p95=12593.374ms; all six semantic observations valid,
with exact labels5/6 because the clarification reason differed from gold.

An initial sandbox transport attempt received no HTTP response; the authorized run
outside the sandbox then completed the six HTTP requests. The semantic comparison
remains confounded by jev-1.13 vs jev-latest. Direct latency is promising; investigate
case101 from available provider records before activation or broader quality claims.

## Offline routing-101 investigation (2026-10-06)

Reviewed all seven saved typesafe_shadow_smoke artifacts. Only the six-case final
artifact contains routing-101. Its observation has HTTP200,511.060ms,INVALID_RESPONSE,
but empty answers/usage/provenance, null prediction and returned model, and no raw
body/text/exception. Earlier snapshots end at cases001–071 or contain only the initial
transport failure. No original routing-101 fixture can be truthfully reconstructed.
Its exact semantic output and failing validator remain unrecoverable. Jev-org's
CLARIFY/MISSING_SCOPE result is context only, never substituted for this missing data.

Official references checked again:
https://docs.typesafe.ai/api
https://docs.typesafe.ai/sdk/python/api/types/responses
https://docs.typesafe.ai/models

The HTTP reference requires model,answers,usage; Choice type/choice/probabilities/
confidence; Noul type/noul. SDK Usage declares both token counts optional nullable
integers. Count nulls therefore now mean unknown and are omitted from normalized
usage, not converted to zero. The usage object itself remains required. Model is
required too; the old parser was permissive on missing/null model and is now aligned
with the documented requirement. Choice confidence remains required and non-null.
Numbers0/1 accept integer or floating JSON numbers, not booleans/strings. Answers
are keyed by IDs and order is irrelevant; missing/extra question IDs remain invalid.
SDK discriminated answer unions use type as discriminator despite individual typed
answer constructors supplying a default. No undocumented missing-type inference is
introduced. Extra root/answer metadata is ignored. Probability bounds and normalized
sum checks remain, including the existing1e-5 floating-point tolerance; docs specify
approximate normalization without a numeric tolerance. No tolerance is tuned against
an unrecoverable sample.

Alias policy recognizes requested jev-latest and the officially documented/observed
resolved jev-1.13.0. Preview and arbitrary substitutions are rejected. A future alias
resolution requires explicit review/update, not automatic acceptance of every model
with a Jev-shaped name. This is not a claim that a pinned request is account-accessible.

Future validation failures retain fixed validation_stage/error codes, known answer
IDs present, bounded structural types/counts and an allowlisted provider snapshot.
Snapshot includes recognized labels, finite numeric probabilities/confidence/noul,
model identifiers with safe syntax and optional token counts. Unknown keys/labels,
free-form strings, provider error messages, Authorization and credentials are not
persisted. No raw HTTP text or headers are saved. Parsed answers,usage and model
survive later assembly failure. Malformed JSON records response length and a fixed
JSON_INVALID code. Synthetic edge tests cover these paths and nullable usage; they
are explicitly NOT a fabricated live routing-101 fixture. Original artifacts and
historical missing-result metrics are unchanged. No inference/recovery call is made.

### Rounding-aware offline checkpoint validation

`typesafe-probabilities-2.0` changes only direct TypeSafe wire validation;
Jev-org retains its original parser policy. Criteria, gold, question schema,
context serialization, assembler, and scoring are unchanged.

The SDK documents approximately normalized Choice probabilities, without a
precision guarantee. All 28 retained responses lie on a two-decimal grid except
binary floating-point serialization residues. Sanitized JSON cannot recover
original trailing zeros. We therefore use a **common grid** with precision
`max(2, finest decimal precision in the distribution)`, after conversion to 15
significant decimal digits to remove float serialization noise. This explicit,
empirical representation assumption is conservative for mixed precisions: it
uses the finest grid for every value rather than wider independent intervals.
It must be reviewed if a provider changes its numeric representation.

For grid precision d, each value has a clipped closed interval
`[max(0,p−0.5×10^-d), min(1,p+0.5×10^-d)]`. A distribution is accepted only if
its summed interval contains 1. Closed boundaries allow unknown tie rounding
conventions. Reported probabilities are preserved, never rescaled. A selected
label may tie the reported maximum or overlap its rounding interval; a selected
upper bound below any other lower bound is rejected. Known labels, numeric
finite range, exact answer IDs, types, and required fields remain mandatory.
Independent Nouls are never normalized together. Existing calibration scores
continue to use rounded reports and should be interpreted as approximations;
this policy does not claim recovery of latent probabilities.

Offline replay reads an explicit checkpoint, verifies every case against the
frozen input/configuration/gold, and rebuilds answers and predictions from the
retained sanitized provider snapshot. Old artifacts are immutable. Replay does
not use the historical derived status/prediction as truth. Historical latency,
usage, model, and call metadata are preserved; new execution accounting is
separate.

Run `python -m evaluation.typesafe_replay <checkpoint.jsonl>` for zero-call
revalidation. Resume preflight is
`python -m evaluation.typesafe_full --resume-from <checkpoint.jsonl>`.
Only a later explicitly authorized live invocation adds `--execute-typesafe`.
Resume and `--fresh` are mutually exclusive. Resume validates the complete paid
prefix before any POST, refuses any remaining invalid observation or identity
mismatch, journals the retained prefix, and starts at the next case. No new
idempotency headers or keys are introduced. Source fingerprints remain checked
before every new call. The original 28-case journal yields 28 reused records,
next case routing-029, and at most 92 new decisions.

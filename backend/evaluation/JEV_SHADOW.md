# Jev shadow provider v1

This is evaluation-only. No public `/chat` path imports the provider. `httpx` is
already installed and declared in the dev group; it remains a dev dependency
because the only caller is the evaluation CLI. No SDK/framework/install is needed.

## Verified API provenance (2026-10-05)

The requested service documents `POST https://jev-ai.org/api/v1/systemone/`, bearer
JEV_API_KEY, pinned `jev-1.13`, at most 20 questions, choice/noul/score, and
answers/model/model_version/usage/latency_ms. Sources:

- https://jev-ai.org/docs/decisions/
- https://jev-ai.org/docs/authentication/
- https://jev-ai.org/docs/models/
- https://jev-ai.org/docs/limits/
- https://jev-ai.org/docs/billing/
- https://jev-ai.org/docs/errors/

Important distinction: TypeSafe, the underlying model vendor, documents its own
endpoint at https://api.typesafe.ai/v1/systemone in https://docs.typesafe.ai/api.
The requested jev-ai.org service describes upstream calls and its own token/credit
wallet. This adapter implements that service's published contract, not TypeSafe's
separate wire/billing contract. Do not reuse TypeSafe credentials here.

## Configuration

Create a development inference key through https://jev-ai.org/docs/authentication/
(Settings → API keys). Keep it in the ignored backend `.env` or export it through
a secure shell/session setup; never paste it in chat. Variables:

- JEV_API_KEY: required only for live execution, SecretStr, excluded from dumps.
- JEV_BASE_URL: default https://jev-ai.org/api/v1; HTTPS, no embedded credentials.
- JEV_MODEL: jev-1.13 only; rolling aliases rejected.
- JEV_TIMEOUT_SECONDS: default 15, bounded to 60 seconds maximum.

No deployment/frontend configuration is added. Missing key is UNAVAILABLE with
zero calls; preflight prints only whether a key is present. Errors never print
external bodies or exception text.

## Criteria and state

`jev-routing-criteria-v1` asks eleven bounded questions in one call:
mode; six independent capability-presence nouls; three ordered capability-operation
choices; clarification reason. Presence probabilities are diagnostics, not dispatch
thresholds. Ordered slots express repeated capabilities without filename extraction.
They do not resolve arguments or execute anything. Presence and slots can disagree;
the slot sequence is the label prediction, and nouls have separate calibration.
Assembly is mode-gated: SINGLE uses slot 1; COMPOUND requires slots 1 and 2
and accepts optional slot 3; CLARIFY requires a reason and returns no requests.
Unused slots/reasons and capability nouls remain diagnostic, including disagreement
flags. Only malformed contracts or absent mode-dependent requirements invalidate.

State contains CURRENT QUESTION, RECENT CONVERSATION CONTEXT, and completeness /
truncation flags. Context is at most six messages, 2000 chars/message, 6000 aggregate.
Original question is capped at 8000 chars. No documents, chunks, storage, secrets,
or answer-generation prompts enter the state. History is untrusted discourse.
Character bounds are enforced; token usage is measured from the response, not
claimed to be an exact input token budget. Criteria do not contain gold examples.

## Safety and execution

```bash
# Zero-call preflight (default stage is smoke)
.venv/bin/python -m evaluation.jev_runner
# Partial smoke if desired; five cases cannot satisfy the complete smoke gate
.venv/bin/python -m evaluation.jev_runner --execute-jev --limit 5
# Complete smoke: six varied cases, one of every mode and boundary group
.venv/bin/python -m evaluation.jev_runner --execute-jev
# Inspect artifact, then full run (reuses smoke's six observations)
.venv/bin/python -m evaluation.jev_runner --execute-jev --stage full --smoke-artifact PATH
```

The frozen routing_v1 SHA-256 is enforced before calls. No retries, no redirect
following, one sequential POST per case, and 1.1 seconds spacing after responses.
Default service limit is 60/minute; 429 is recorded and stops the run without retry.
401/402/422/5xx, timeouts, malformed results, or assembly inconsistencies also stop
it. STOP means a partial artifact; its processed-case count is explicit. No silent
rule substitution is recorded as Jev success.

Maximum initial smoke calls: 6. Maximum full additional calls after valid smoke:
114, for 120 total distinct decisions. A --limit run makes at most that many POSTs.
No automatic USD estimate: the documented wallet charges input tokens, or one
credit per successful call when the token wallet cannot cover it. Upper bound on
credit fallback is one per planned call; token scaffolding/cost requires live usage.
No rate/model probe adds hidden calls.

Idempotency key hashes dataset schema/hash, case ID, model, criteria version/body,
context policy, and bounded state. It contains no raw question or credential. The
service returns 409 on duplicates, not the original answer. Full runs reuse saved
successful smoke observations with matching dataset/criteria/model/base URL.
Do not repeatedly run smoke with the same key; preserve its artifact. A failed
request may require looking up its status via the service before another attempt.
This runner never automatically polls or changes a key to create duplicate work.

## Metrics

Compare rules on the same processed gold cases. Full legacy baseline remains
available through evaluation.routing_runner. Semantic metrics retain failures as
misses; no fake confidence. Exact decision scores mode, ordered capability-operation
labels, and clarification reason, not arguments or executor readiness. Compound
omission is capability-multiset coverage, matching baseline convention.

Choice calibration uses normalized per-question distributions: multiclass Brier /
log loss and selected-label reliability bins. Independent presence nouls use
Bernoulli Brier/log loss separately on non-CLARIFY gold. They are never normalized
into a six-route distribution. Errors are excluded from calibration sample counts,
but count as semantic misses. Selective curves use mode probability against exact
label correctness; this is a diagnostic, not an activation threshold. Vacant slot
NONE predictions can dominate pooled accuracy; slot diagnostics remain separate.

Latency reports client wall time and retains service latency separately. Usage
reports input/output/charged tokens and charged credits, with USD cost unknown.
Reused smoke calls are represented usage, not new charges; artifact new_calls and
reused_observations distinguish them. Partial artifacts must not be presented as
full-benchmark scores. No held-out claim or production activation is implied.

## First live response and assembly correction

The first recorded call used 3575 input tokens, 736 output tokens, and one credit.
Its 200 response selected SINGLE and FILE_INVENTORY:LIST in slot 1, but also
selected slot 3 after a vacant slot 2 and MISSING_SCOPE as clarification. The old
assembler incorrectly required all speculative answers to agree. The sanitized
regression fixture preserves the actual recorded decision distributions, reconstructed
from the saved observation; it contains no credentials. Criteria and gold are unchanged.

The client timer begins after local state serialization and key checking. It includes
AsyncClient creation/teardown, request serialization, connection establishment (DNS,
TCP/TLS), server/gateway waiting, response transfer, JSON parsing, validation and
assembly. It excludes runner pacing and artifact/scoring work. It is not broken into
network phases, so the observed 12297.64ms versus service 1323ms cannot identify a
cause. Both numbers remain separate; no latency optimization is introduced.

Runner stop reasons now distinguish invalid_response, provider_failure (with status),
and model_drift (different otherwise valid model versions across cases). A single
correct model/version is not drift. Auxiliary diagnostic disagreement does not stop
the run. Presence flags use a 0.5 Bernoulli majority comparison for diagnostics only;
no production threshold is introduced. Existing idempotency keys are unchanged:
rerunning a completed case may return 409. Preserve/reuse the saved response rather
than automatically changing keys or issuing duplicate paid calls.

## Persistent resume and idempotency recovery

Every CLI invocation scans only `jev_shadow_*.json` in its result directory before
POSTing. Malformed, oversized, symlinked, incompatible and unrecoverable artifacts
are ignored. Matching requires frozen dataset version/hash, exact gold/input,
criteria version/body hash, pinned model and base URL. New artifacts (1.1) also
record exact input/state hashes, context version, question-schema version and the
unchanged stable idempotency key per case. Legacy 1.0 has an explicit migration:
that version used bounded-history-v1 and the same question schema, whose body hash
and full gold input must still match. No arbitrary missing-version defaults apply
to future formats. Timestamp is provenance, never a matching or preference rule.
Preference is explicit identity metadata first, then stable artifact content hash.

Saved HTTP-200 raw answers are revalidated and assembled with current code, even
when the old derived status was INVALID_RESPONSE. Old artifacts remain unchanged.
A 409 artifact without recovered answers is not cached. A complete six-case smoke
artifact is still required for full execution, and its observations are revalidated.
Current-run provenance includes original source filename/hash and timestamp, and
request ID when previously recorded. The first artifact did not record a request ID;
none is invented. Original probabilities, usage and both latency numbers survive.

409 subcodes are retained. Already-completed requests use an authenticated GET to
`/api/v1/requests/{request_id}/`; in-progress requests poll at most three times,
with a one-second interval and within the total configured timeout. No second POST.
Status URL must exactly match the configured origin/path and validated request ID;
redirects are disabled, preventing credential forwarding. Different-body reuse
stops as idempotency_body_mismatch. Unknown/malformed status bodies fail closed.
The published docs specify the status endpoint but do not fully specify its response
envelope: decoder supports a native decision or completed result/response envelope,
with mocked coverage; an unrecognized real envelope requires inspection, not guessing.

Accounting separates POST attempts, status GETs, new model decisions, artifact
reuses, recovered idempotent requests and uncertain transport outcomes. `new_calls`
is now an alias for known new model decisions, not HTTP attempts. Cached/recovered
responses contribute zero new decisions; represented usage remains original usage,
not a claim that this run paid again. HTTP-200 new responses count one decision;
HTTP errors count zero, while timeout/transport outcomes remain explicitly unknown.

A new smoke invocation automatically reassembles/reuses routing-001 from the original
partial artifact and continues with the remaining five cases. No key rotation,
idempotency-key change, criteria change or provider migration is required.

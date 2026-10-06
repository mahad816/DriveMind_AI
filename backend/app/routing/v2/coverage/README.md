# Isolated semantic coverage verifier

This package is not invoked by routing, resolution, readiness, or RagService.
It has its own contract lock. Nesting it here keeps the original v2 source manifest,
Stage-1/Stage-2 versions, and historical routing checkpoints unchanged.

`serialize_interpretation` accepts a validated BoundInterpretation. It produces a
bounded immutable CoverageInput with operational scope/reference descriptions and
source/query substrings marked as provenance only. Literal names are sliced from
validated current-input spans. No historical names, IDs, resolver results, routing
probabilities, or candidate registries are sent. Context contains only counts and
supported relative history positions; a private-state digest binds snapshot identity
without transmitting private state. `serialize_routing_result` additionally preserves
validated selected positions when translation collapses a mixed unsupported bundle.
Unsupported domain-only inputs must supply their original proposed cardinality;
no missing cardinality is invented.

TypeSafeCoverageVerifier uses direct TypeSafe, requests jev-latest, and accepts only
the existing allowlisted alias resolutions. It sends exactly one COVERAGE Choice:
PRESERVED, MISMATCH, UNCERTAIN. Calling verify without execute=True makes zero HTTP
requests. Missing configuration, identity mismatch, provider failure, or malformed
response has no verdict and never permits resolution. MISMATCH/UNCERTAIN also block.
PRESERVED is semantic approval only: it does not establish existence, ownership,
readiness, or execution authority. No confidence threshold, repair, fallback routing,
or retry is implemented. Any future orchestration must also check exact identities
and deterministic readiness before execution.

The coverage lock fingerprints serialization, criteria, question shape, provider
code, shared probability validation, the input/result schemas, and original routing
dependencies. Do not alter behavior under a frozen version. Provider telemetry
contains verdict probabilities, selected probability/margin, alias/model, latency,
nullable token usage, HTTP status and hashes; it omits original input and raw errors.

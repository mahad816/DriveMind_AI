---
status: accepted
---

# The public demo is isolated from Owner data and has a hard spend cap

The public demo is free for Visitors but paid for by the Owner's API key, so it runs on a fixed synthetic corpus in dedicated storage, never on Owner data, and is bounded by a backend-enforced spend limit and rate limit. When the budget is exhausted, paid requests stop and guided sample answers are shown instead. This is a deliberate shape: it limits both cost exposure and privacy exposure, at the price of a less open demo.

## Rules

- Synthetic corpus only, fixed, in separate storage (not a user-ID filter inside Owner storage). The demo cannot read, write or infer anything about Owner data.
- The spend limit and rate limit are enforced by the backend. Neither the browser nor a Visitor can bypass them, and the demo cannot bypass budgets or authentication.
- Starting budget: **$5 per month**, subject to confirming real costs.
- The backend refuses a new paid operation when the budget would be exceeded or cannot be safely enforced (fail closed). Enforcement needs persistent cost accounting and a conservative pre-call estimate or reservation that accounts for concurrent requests and retries. Tracking cost only after a request completes does not guarantee an exact hard cap. This stays a small counter and check, not a billing system; design and tests come in the release and demo milestone (see the spec).
- Demo conversations live in the Visitor's browser. DriveMind does not keep a per-Visitor record.
- Whether the prepared index is reused across Visitors is **to be confirmed**.

## Considered options

- **Visitor-supplied API keys.** Deferred, to be investigated later only. If ever built: no keys in URLs, logs or persistent browser storage, and no permanent storage.
- **Per-Visitor tracking (accounts, fingerprints, per-person quotas).** Rejected: privacy cost and complexity are not justified for a portfolio demo.

## Consequences

- The existing demo limiter settings in the configuration are a global request-rate limit and a concurrency limit; the interview reported it as in-memory. A spend cap and a per-Visitor limit were not found by a configuration and name search, which is not proof they are absent. The cap is therefore new work (release milestone), and how to throttle abuse without per-Visitor tracking is an implementation question left open.
- Public-demo behavior must be tested separately from Owner behavior, including the budget-exhausted state.
- A public multi-Owner launch is **not** part of this decision (see the spec's Out of Scope).

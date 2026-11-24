# 01: False-premise handling in the agent prompt (ticket A, KI-028 family)

**Spec:** docs/specs/m1-rag-evaluation.md (Owner-approved exception: docs/DECISIONS.md, "2026-11-24 — Narrow M1 exception for three targeted answer-reliability fixes")
**What to build:** the agent treats what a question assumes (an event, a decision, a cause, a named item) as unverified until returned evidence supports it, says so when the evidence contradicts or does not establish it, gives the established facts (for example the real status), and still answers ordinary questions directly.
**Blocked by:** None
**Status:** ready-for-human
**Progress:** claimed
**Risk:** high (changes `AGENT_SYSTEM_PROMPT`, so the policy hash, which is the evaluation's prompt id, changes)

## Evidence

Claim-check diagnostic of 2026-11-24 (evidence folder outside Git): a development case that asks why a body "rejected" a plan that is only a draft was answered with an invented rejection; the runtime checker flagged nothing. KI-028's earlier prompt rule ("if no returned source has the name the user gave, say no such document was found") had no effect and was removed; this change is a different, more general rule (premises, not file names) and is not expected to fix KI-028's missing-entity cases by itself.

## What changed

`backend/app/agents/tool_rag/prompts.py`: one added paragraph, no case names, dates or organisations. Tests: `tests/agents/tool_rag/test_claim_removal_and_premises.py` (structure only: required phrases present, none of the benchmark words present).

## Acceptance

- [x] The prompt states the six behaviours (unverified until supported; challenge contradicted or unsupported premises; absence of evidence is not evidence of absence; give the established facts; do not refuse the whole question when part can be answered; answer directly when premises are supported).
- [x] No hard-coded case, date or organisation (test).
- [ ] **Real-model behaviour is not shown.** A structural test cannot show the model follows the paragraph. Evidence needs the small validation in ticket 04, which has not been run (no paid call is authorized).

## Comments

- 2026-11-24: implemented, free tests only.

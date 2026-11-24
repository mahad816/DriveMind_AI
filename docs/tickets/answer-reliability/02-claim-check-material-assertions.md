# 02: Claim check verifies each material assertion (ticket B, KI-002 follow-up)

**Spec:** docs/specs/m1-rag-evaluation.md (Owner-approved exception: docs/DECISIONS.md, "2026-11-24 — Narrow M1 exception for three targeted answer-reliability fixes")
**What to build:** the runtime claim checker no longer accepts a statement because most of it is supported. A supported detail does not validate an unsupported event, decision, cause, relationship or conclusion, and an assumption that came from the user's question is not evidence.
**Blocked by:** None
**Status:** ready-for-human
**Progress:** claimed
**Risk:** high (changes what the checker removes from published answers)

## Evidence

The diagnostic's checker accepted the invented rejection (flagged nothing). Cause in the instructions: "partial support (if most of the statement is in the evidence, it is supported)" and "When in doubt, the statement is supported". The checker did flag a wrong figure (a prior-year number given for the asked year), which the unchanged number rules keep doing.

## What changed

`SYSTEM_PROMPT` in `backend/app/agents/tool_rag/claim_check.py` only. Removed the partial-support allowance. Added: each material assertion is checked on its own; a supported detail does not excuse an unsupported event/decision/cause/conclusion; user-question assumptions are not evidence. Kept: paraphrase, reasonable inference without new events, framing, arithmetic, "not in the documents" statements, qualified claims (a draft described as a draft), conversational wording, offers of help, the user-number rule and the absent-number hint list.
Not changed (as instructed): model, timeout, evidence budget, fail-open policy, number of model calls, the checker being on.

## Acceptance

- [x] Prompt contains the new rules and no longer contains the partial-support rule; number and arithmetic protections still present (tests).
- [x] Scripted verdicts: a mixed answer keeps the supported statement and drops the flagged one; a supported numeric answer is untouched; an incorrect number gets the absent-number hint and is removed when flagged.
- [ ] **Real-model effect not shown** (ticket 04). The wider wording also risks more false flags on valid answers; ticket 04's supported controls are there to look for that.

## Comments

- 2026-11-24: implemented, free tests only.

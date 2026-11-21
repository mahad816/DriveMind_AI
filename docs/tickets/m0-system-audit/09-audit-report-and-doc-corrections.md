# 09: Consolidated audit report, documentation corrections and M0-SEC proposal

**Spec:** docs/specs/m0-system-audit.md
**What to build:** The Owner gets one short audit report, `docs/audits/m0-system-audit.md`, built from tickets 01 to 08, with documentation corrected wherever the audit proved it wrong, a final M0-SEC proposal and an evidence-based revision of the M1 to M10 order.
**Blocked by:** 01, 02, 03, 04, 05, 06, 07, 08.
**Status:** ready-for-agent
**Progress:** resolved

## Scope

- Create `docs/audits/m0-system-audit.md`: findings only from the tickets' `## Findings`, each with a label (Verified, Defect, Unverified, Future), an evidence type and a pointer (file and symbol, test name, command, or "hosted read on <date>"). Cover A1 to A6, the recorded time of any security escalation, and the proposed M0-SEC (fallback items from ticket 03 merged with any items from ticket 04) with its ordering.
- End with a short proposal to revise the M1 to M10 order, including whether any security finding moves ahead of M1.
- Correct only what is proven wrong: the v1 spec Status ledger (for example "four" fallbacks versus the verified count), `AGENTS.md` constraints (the verification section is already updated by ticket 02), `docs/KNOWN_ISSUES.md` (beyond entries added by earlier tickets), `backend/app/security/README.md`. No new guides.
- Confirm that `git diff` against the audited commit shows only: the report, new tests, the CI workflow, ticket files and documentation corrections.
- Scan the diff for secrets, hosted identifiers, connection strings, private Drive content and real file names.
- Present the diff summary to the Owner for approval. Do not commit or push without that approval.

## Out of scope

Fixing any defect, implementing M0-SEC, deleting dead code, changing application behavior, any new investigation (a gap found here is recorded as `Unverified` or sent back as a new ticket), M1 to M10 planning beyond the order proposal.

## Inspect

All earlier ticket `## Findings`; `docs/specs/drivemind-v1-product-definition.md` ("Status ledger", milestone table); `AGENTS.md`; `docs/KNOWN_ISSUES.md`; `backend/app/security/README.md`; `git diff` against the audited commit.

## Deliverables

`docs/audits/m0-system-audit.md`; the documentation corrections; the final diff summary for Owner approval.

## Needs

No paid APIs, no live infrastructure, no Docker. Reads only the repository and earlier ticket findings.

- [x] The report exists; every finding has a label, evidence type and pointer; it contains no secrets or hosted identifiers.
- [x] The report states: answering path per route under local defaults and hosted flags (A1); all six fallbacks with classification and callers, route inventory, encryption, logging and rate-limit findings, escalation time and M0-SEC (A2, tickets 03 and 04); File-state mapping and reprocessing triggers (A3); storage inventory and deletion actions (A4); each hosted fact or `Unverified (reason)` (A5); baseline, dependency groups and CI cost citation (A6).
- [x] The M0-SEC proposal has scope, acceptance criteria and an ordering that follows the urgency rules.
- [x] The report ends with an evidence-based M1 to M10 order proposal that states whether any security finding moves ahead of M1.
- [x] Each documentation correction matches a cited finding; no other documentation changed.
- [x] `git diff` against the audited commit contains only the report, new tests, the CI workflow, ticket files and documentation corrections; no application code.
- [x] Owner approval: the Owner instructed the commit in the session message that started this ticket ("verify the final diff, update the ticket status and commit"; no pushing). That instruction replaces the ticket's separate approval step; the diff summary is in the closing report.

## Comments

## Findings

Done 2026-11-21 on `feature/v2-state-performance`. Deliverable: `docs/audits/m0-system-audit.md` (findings A1 to A6 with labels, evidence types and pointers; escalation record; proposed M0-SEC with scope, acceptance and ordering; risk register assigning every open risk to a milestone; Owner decisions D1 to D7 preserved; documentation corrections; M1 to M10 proposal; diff scope check). Result of the proposal: no security finding needs to move ahead of M0 and no hotfix is needed; M0-SEC is proposed before substantial M1 implementation, with the Owner-mode limit values set after M1 cost measurements.

Documentation corrected (each tied to a ticket finding in report section 7): v1 spec Status ledger, `AGENTS.md`, `backend/app/security/README.md`, `docs/KNOWN_ISSUES.md` (a note, no new entry without a test), `docs/ARCHITECTURE.md`, `docs/TOOL_RAG_ARCHITECTURE.md`, `docs/guides/INDEXING.md`. Not changed: application code and docstrings (M0-SEC item 8). No tests were run for this ticket (documentation only); no Railway access, paid API, push or deploy.

## Comments

- 2026-11-21: two independent read-only reviews (Standards, Spec/Correctness). Standards: no blocking violations; fixed label inflation on analysis-only hosted facts (A5.5 to A5.7), a "two/three statements" slip, an undefined skip count, undefined evidence types and jargon (added a Terms list), and the audited-commit wording. Spec/Correctness: about 40 claims checked, all faithful; fixed the misattributed urgency ordering (the spec's rule, not an Owner decision, with the reasoning for proposing the dormant items before M1), an unsupported M7 sentence, a missed `ARCHITECTURE.md` security paragraph, an over-broad "no deletion action" sentence, a garbled A5.8, and the "locked" wording (sessions already issued stay valid up to 7 days).
- Not done, on purpose: converting the claim-check characterisation test into a strict expected failure (decision 3 of ticket 05 leaves it to M3), and any fix.

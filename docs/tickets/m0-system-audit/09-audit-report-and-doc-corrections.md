# 09: Consolidated audit report, documentation corrections and M0-SEC proposal

**Spec:** docs/specs/m0-system-audit.md
**What to build:** The Owner gets one short audit report, `docs/audits/m0-system-audit.md`, built from tickets 01 to 08, with documentation corrected wherever the audit proved it wrong, a final M0-SEC proposal and an evidence-based revision of the M1 to M10 order.
**Blocked by:** 01, 02, 03, 04, 05, 06, 07, 08.
**Status:** ready-for-agent
**Progress:** open

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

- [ ] The report exists; every finding has a label, evidence type and pointer; it contains no secrets or hosted identifiers.
- [ ] The report states: answering path per route under local defaults and hosted flags (A1); all six fallbacks with classification and callers, route inventory, encryption, logging and rate-limit findings, escalation time and M0-SEC (A2, tickets 03 and 04); File-state mapping and reprocessing triggers (A3); storage inventory and deletion actions (A4); each hosted fact or `Unverified (reason)` (A5); baseline, dependency groups and CI cost citation (A6).
- [ ] The M0-SEC proposal has scope, acceptance criteria and an ordering that follows the urgency rules.
- [ ] The report ends with an evidence-based M1 to M10 order proposal that states whether any security finding moves ahead of M1.
- [ ] Each documentation correction matches a cited finding; no other documentation changed.
- [ ] `git diff` against the audited commit contains only the report, new tests, the CI workflow, ticket files and documentation corrections; no application code.
- [ ] The Owner approved the diff before any commit.

## Comments

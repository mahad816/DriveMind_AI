---
name: drivemind-engineering
description: DriveMind's standard engineering lifecycle for a scoped ticket or feature: understand, specify, ticket, implement, verify, independent review by the drivemind-reviewer subagent, then report and STOP (no automatic fixes after the review). Use for any non-trivial change to backend, frontend, evaluation or security code, or when the Owner says "implement ticket N" or "run the workflow". Skip for questions, tiny well-defined fixes (see Triage), and pure docs edits.
---

# DriveMind engineering workflow

One main session runs the whole lifecycle. The Owner is asked only about decisions that change requirements, architecture, safety or spending. Existing conventions stay authoritative: `AGENTS.md`, `CODING_STANDARDS.md`, `docs/GIT_WORKFLOW.md`, `docs/specs/README.md`, `docs/tickets/README.md`, `docs/agents/issue-tracker.md`.

## Order of work (Ticket and Feature tracks)

A. Understand: read ticket, spec, acceptance criteria and the code; challenge assumptions; choose the smallest correct change.
B. Implement: failing test first where it fits, smallest change, regression and edge tests.
C. Verify: focused tests, static checks, broader regression where warranted, real behavior where possible; record what passed, failed and was **not** run.
D. Independent review: one fresh `drivemind-reviewer`.
E. **Report and STOP.** After the review the automatic workflow ends. **Do not fix review findings, do not start another cycle, do not start the next ticket**, whatever the verdict. The Owner decides the follow-up.

## 0. Triage (decide the track before doing anything)

| Track | When | What runs |
|---|---|---|
| **Tiny** | One-file, well-defined, no behavior change in a security/eval path (typo, doc fix, obvious bug with a clear test) | Implement + targeted test + self-check of the diff. No spec, no ticket, no subagent. |
| **Ticket** | A ticket file exists, or the change is one scoped piece of work | Stages 2-6 |
| **Feature** | New capability, several tickets, or unclear requirements | Stages 1-6, ticket by ticket |

**Risk is judged from the actual diff, not the ticket label.** High risk = authentication/authorization, security boundaries, held-out data or approval gates, paid evaluation runs, Railway/production/beta, real-data migrations, secrets, destructive operations, major architecture. High risk adds the gates in "High-risk gates" below. When unsure, treat it as high.

## 1. Understand, then specify

- Read the code, tests, `GLOSSARY.md`, relevant ADRs/`docs/DECISIONS.md`, and existing specs before asking anything. Ask the Owner only what the repo cannot answer and that changes requirements, safety or spend.
- Challenge the request: ambiguity, contradictions, needless complexity, existing code that already does it.
- For a Feature: write `docs/specs/<slug>.md` using the sections in `docs/specs/README.md` (success criteria, edge and failure behavior, security/privacy/performance constraints, test strategy; no code paths). For a very vague idea suggest the Owner run `/grill-with-docs` first; the `grilling` skill can be called directly. `/to-spec`, `/to-tickets`, `/implement` and `/retro` are Owner-invoked only (they cannot be called by the agent), so write the files by hand in the repo format.
- Skip the spec for Tiny and for work already covered by a ticket.
- **If the Pocock plugin is not installed** (check the available skills list; do not assume it is): the process is unchanged. Do the clarification yourself: ask the Owner the questions the repo cannot answer one at a time, each with your recommended answer, and challenge the plan before agreeing to it; write spec and tickets by hand in the repo formats; use test-first without the `tdd` skill. Say which skills were unavailable. Never claim to have run a skill that is not installed, and never copy plugin text into the repo. Installation steps: `docs/guides/CLAUDE_CODE_HANDOFF.md`, section 14.

## 2. Tickets

Format: `docs/tickets/README.md`. Add `**Risk:** standard | high` under `Progress`. For each ticket make sure these exist (inline sections are fine): objective, scope **and exclusions**, blocked-by, measurable acceptance criteria, failure scenarios, required tests, definition of done, and whether a local commit is authorized (the Owner asking for a commit in the request counts). One primary scope per ticket; no hidden refactors; no tickets created only for ceremony. Set `Progress: claimed` before work.

## 3. Implement

1. `git status`, branch, HEAD. Do not touch unrelated or untracked work; note the base commit for the reviewer.
2. Read the spec/ticket, then the code paths and their call sites. Choose the smallest correct change; reuse existing code.
3. Reproduce a confirmed defect with a failing test first when practical (the `tdd` skill can be used). Claim red/green only if the test actually failed before the fix.
4. Implement, then add edge-case and regression tests. Never weaken or delete an assertion, skip a test, or bypass a safety check to get green.
5. Run targeted tests, then `ruff check`, `ruff format --check`, `mypy` and `basedpyright` on the files you touched (backend, from `backend/`; the `tests/` baseline of 48 basedpyright errors is not yours to fix) and `npm run lint` if frontend changed. Execute the real behavior or a disposable integration environment when the ticket calls for it.
6. Review your own `git diff` for unintended changes, secrets, held-out ids, private Drive content.

## 4. Verify (before the review)

Check each acceptance criterion against evidence you produced; run the focused tests, then the static checks (`ruff check`, `ruff format --check`, `mypy`, `basedpyright` on touched files from `backend/`; the `tests/` baseline of 48 basedpyright errors is not yours to fix; `npm run lint` if frontend changed) and broader regression where warranted (full backend suite from `backend/` for behavior changes, with `SESSION_TEST_DATABASE_URL`/`QDRANT_TEST_URL` per `AGENTS.md` and `OPENAI_API_KEY` unset; frontend `npm test`/`lint`/`build` if touched). Run the real behavior or a disposable integration environment when the ticket calls for it. Save the **raw, unedited** output of each check (command line first) in the session scratchpad, never in the repo. Record what passed, what failed and what was **not** run and why. Never fabricate or summarize away verification evidence. Confirm `git status` shows only intended files and that no secrets, held-out data or paid calls are involved.

## 5. Independent review (automatic, Standard and High risk)

The reviewer has **no shell** (tools: Read, Grep, Glob). Launch **one** fresh reviewer: Agent tool, `subagent_type: "drivemind-reviewer"`. Prompt it with only: the ticket and spec paths, the base commit, a saved diff file (`git diff <base>` plus the list of untracked files, in the scratchpad), the paths of the relevant code and tests, and the raw output files. **Do not** include your reasoning or which tests you think matter. Add any special care the ticket needs (for example "this touches the review gate").

- The reviewer inspects the code itself and judges the output **you** produced. Reviewing implementer-produced output is **not** the same as independently executing the tests; say so in the report.
- If it asks for extra checks (a specific existing test, a read-only `git` command, a probe test it wrote out), you may run the safe ones yourself and return the raw output; read any probe before running it, keep it outside the repo, and refuse anything that is paid, networked, destructive, touches `.env`, credentials or held-out data. Running requested checks gathers evidence for the report; it does not authorize edits to the implementation. A request you decline is reported as declined.
- Sensitive changes (authentication/authorization, ownership filters, held-out or attestation gates, spending, migrations, secrets): say in the report whether stronger independent verification (the Owner or a separate session running the tests) is needed.
- One reviewer, no teams, no repeated reviews unless the Owner authorizes one. A re-read of your own diff is not an independent review and must not be called one.

## 6. Report and STOP

**The automatic workflow ends here.** Do not modify the implementation after the review.

- **APPROVE:** report successful verification, the remaining limitations, and mark the implementation **review-approved**. (A local commit still needs the Owner's authorization.)
- **BLOCK or NEEDS-EVIDENCE:** list every substantiated issue with severity and reproduction evidence; say what was tested and what remains unverified (unverified items are not confirmed defects); recommend the smallest next correction. Do **not** fix, do **not** launch another implementation cycle, do **not** claim completion. P3 items go in the report (and the ticket's `## Comments` if the Owner wants them recorded), not into code.
- A reviewer claim you could not reproduce is reported as unreproduced, never silently dropped or silently applied.
- The report is short: what changed and why, files, tests run and **not** run (exact counts), reviewer verdict, confirmed defects, unverified items, git state (branch, HEAD, dirty or clean), what the Owner must decide.

A ticket is COMPLETE only when its definition of done is met **and** the review verdict is APPROVE; update the ticket (`Progress: resolved`, findings with measured numbers only) and affected docs (`docs/KNOWN_ISSUES.md`, `docs/DECISIONS.md`) only for that case or when the Owner asks. Commit **locally** per `docs/GIT_WORKFLOW.md` (Conventional Commit, one logical change; `git commit` prompts the Owner) only if authorized. **Never push.**

## 7b. Handoff record (after every meaningful checkpoint: a ticket, a lettered M1-08-x step, a milestone)

A fresh session, possibly on another Claude account, must be able to continue from files alone. Update `docs/guides/CURRENT_DEVELOPMENT_STATUS.md`: add or edit **one row** in the checkpoint log and refresh the snapshot (branch, HEAD, next step). Row fields: checkpoint, final commit SHA (or "uncommitted"), implementation status, the reviewer's verdict, tests actually executed with counts, blockers, next approved action. Tag each fact `[git]`, `[local]`, `[owner]` or `[unverified]` as that file explains; never promote an Owner-reported fact to verified. Rules: no repeated project summaries, no held-out ids or text, no secrets, balances, account details or local paths beyond what the file already uses. The status file may be edited in the same commit as the work or in a follow-up docs commit; it is committed like any doc and only when commit is authorized. Local runtime metadata (receipts, result files, database contents) stays out of Git; record only that it exists and how to re-check it. If the change finishes a ticket also update the ticket, and if it changes the workflow itself keep `docs/guides/CLAUDE_CODE_HANDOFF.md` accurate.

At the **start** of a session on DriveMind work, read the status file, the current ticket and `git status`/`git log -5`, and trust Git over the status file when they differ (then fix the file).

## 8. Retrospective (milestone end or after a repeated mistake, not every ticket)

Ask: what recurred, why did tests/reviews miss it? Convert it into a regression test, a validator or a hook if that is cheaper than a reminder; otherwise one line in `docs/DECISIONS.md`. Delete instructions that no longer earn their place. Suggest the Owner run `/retro` for a session-level review. Memory is a backup, not the mechanism.

## High-risk gates (the reviewer's APPROVE never counts as these)

- **Held-out data**: ordinary sessions never read `~/.drivemind-eval-sealed/`, review sheets or authoring transcripts, never tune on held-out cases, and never edit the attestation/freeze checks to pass. A `.claude/hooks/guard.py` hook blocks the obvious access; a private review needs the Owner to start a session with `DRIVEMIND_PRIVATE_REVIEW=1`.
- **Spending**: no paid OpenAI/provider call without the Owner's explicit authorization for that run. Estimate first (free), then stop and ask with the estimated cost and cap (never let the provider balance go negative; the rule is in `docs/guides/CLAUDE_CODE_HANDOFF.md`, section 11). The nine paid evaluation entry points (list in `.claude/README.md`) prompt in normal permission modes; a prompt is not a cap, and four of them (`intent_eval`, `agent_smoke_runner`, `runner`, `conversation_runner`) have no meter or cap at all, so ask the Owner before running any of them. A bypass mode skips the prompt; a wrapper script is not matched. Never raise a cap or edit prices to make a plan fit. Report measured usage.
- **Infra**: no Railway, production, beta, push, deploy or destructive DB operation without explicit approval; integration checks use disposable databases/Qdrant on loopback.
- For these, finish and review the code, then **stop and ask the Owner** (AskUserQuestion) before the action itself.

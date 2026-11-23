@AGENTS.md

# Claude Code workflow

Project facts, commands and architecture are in `AGENTS.md` (imported above). Review rules are in `CODING_STANDARDS.md`. This file only says how to work.

## Principles
- Verify, do not assume: reproduce a defect with a failing test, run the real behavior, report only results you actually produced (never claim a test passed that was not run).
- Smallest correct change; reuse existing code; no speculative abstractions, no unrelated edits, never weaken a test or safety check to get green.
- Ask the Owner only about requirements, architecture, safety or spending that the repo cannot answer.

## Starting a session
Read `docs/guides/CURRENT_DEVELOPMENT_STATUS.md` (current milestone, ticket, next step, restrictions), then the current ticket and `git status` / `git log -5`. Git is authoritative if they disagree. A new session, or one on another Claude account, needs nothing else: setup and troubleshooting are in `docs/guides/CLAUDE_CODE_HANDOFF.md`. After each meaningful checkpoint update the status file (skill stage 7b).

## Where things live
- Specs `docs/specs/<feature>.md`; tickets `docs/tickets/<feature>/NN-<slug>.md` (formats and the `Status:`/`Progress:` rules in `docs/specs/README.md`, `docs/tickets/README.md`, `docs/agents/issue-tracker.md`). Decisions in `docs/DECISIONS.md`; open defects in `docs/KNOWN_ISSUES.md`.

## Standard workflow
For any ticket or non-trivial change, use the `drivemind-engineering` skill: Understand, Specify, Ticket, Implement, Verify, **independent review**, then **Report and STOP**. Tiny well-defined fixes skip spec, ticket and reviewer.

## Automatic independent review, then stop
After implementation and verification (focused tests, static checks, record of what was and was not run), launch one fresh `drivemind-reviewer` subagent (read-only: Read/Grep/Glob) with the ticket and spec paths, base commit, a saved diff file, code/test locations and the raw test-output files. You may run safe extra checks it requests and return the raw output; reviewing your output is not the same as independently running the tests, so say so. **After the review the automatic workflow ends: report the verdict and findings and STOP.** On BLOCK or NEEDS-EVIDENCE do not fix, do not start another cycle, do not claim completion: list the issues with evidence, what is unverified, and the smallest next correction, and let the Owner decide. A reviewer's APPROVE is never approval to spend, push, deploy, commit or run a destructive operation. Never start the next ticket on your own. Details: skill stages 4-6.

## Hard limits
- **Held-out data**: never read `~/.drivemind-eval-sealed/`, review sheets or authoring transcripts; never tune on held-out cases; never put held-out ids/text in Git, logs or reports. A hook blocks obvious access.
- **Spending**: no paid OpenAI or other provider call without the Owner's explicit go-ahead for that run; estimate first, keep `--cap`, never raise caps or edit prices to fit, report measured usage.
- **Infra**: no Railway, production, beta, push, deploy or destructive database operation without explicit approval; use disposable loopback test databases.
- **Secrets/privacy**: never read or print `.env` or credentials; this repository is public, so no real Drive content in specs, tickets or logs.
- **Git**: check `git status` first; keep unrelated and untracked work; no reset/clean/force; commit locally only when authorized, one logical change, Conventional Commits; never push.

Safeguard details and limits: `.claude/README.md`.

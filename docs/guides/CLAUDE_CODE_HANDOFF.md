# Claude Code handoff: continuing DriveMind from a fresh session or another account

Written 2026-11-23 for the Owner and for any new Claude Code session. A fresh session needs only this file, `docs/guides/CURRENT_DEVELOPMENT_STATUS.md`, the current ticket and `git log`; it must not need an earlier conversation. No secrets, balances or held-out content belong in this file.

## 1. What DriveMind is

A Google Drive knowledge assistant: read-only Drive sync, a hybrid (PostgreSQL full-text + Qdrant vectors) index, cited answers. Next.js 15 / React 19 / TypeScript frontend, FastAPI + SQLAlchemy/asyncpg backend, PostgreSQL, Qdrant, OpenAI embeddings and chat, LangGraph, Tesseract OCR. Details: `AGENTS.md` (loaded through `CLAUDE.md`), `docs/ARCHITECTURE.md`.

## 2. Where things live

| What | Where |
|---|---|
| Backend API / services / retrieval / agents | `backend/app/api/`, `services/`, `retrieval/`, `agents/` (`drive_graph/`, `tool_rag/`) |
| Evaluation harness | `backend/evaluation/rag_eval/` (datasets in `backend/evaluation/datasets/`, local results in git-ignored `backend/evaluation/results/`) |
| Tests | `backend/tests/` (security tests in `tests/security/`, evaluation in `tests/evaluation/`), `frontend/` (`npm test`) |
| Frontend | `frontend/app/`, `components/`, `lib/` |
| Specs / tickets / decisions / defects | `docs/specs/`, `docs/tickets/<feature>/NN-<slug>.md`, `docs/DECISIONS.md`, `docs/KNOWN_ISSUES.md` |
| Standards a reviewer checks | `CODING_STANDARDS.md`; Git rules `docs/GIT_WORKFLOW.md` |
| Current state and next step | `docs/guides/CURRENT_DEVELOPMENT_STATUS.md` |

## 3. The engineering workflow (what is active, and where it is stored)

All of this is in the repository and travels with a checkout:

| File | Role |
|---|---|
| `CLAUDE.md` | Short rules; imports `AGENTS.md`. Loaded by every session in this folder. |
| `.claude/skills/drivemind-engineering/SKILL.md` | The lifecycle: Understand (Specify and Ticket for larger work) → Implement → Verify → Independent Review → Report and STOP, then the handoff record. Reviewer findings go to the Owner, who decides the next action; the agent does not fix or re-review on its own. |
| `.claude/agents/drivemind-reviewer.md` | Independent reviewer with no shell (tools Read, Grep, Glob; `model: opus`, see section 13 if the model is unavailable). |
| `.claude/settings.json` | Deny rules (push, hard reset, clean, `railway`, reads of `.env`, `.env.*`, `credentials.json`, `token.json`, `*.pem` in any folder; this also blocks `.env.example`), ask rules (the nine paid evaluation entry points of section 11, `git commit`), the guard hook. |
| `.claude/hooks/guard.py`, `test_guard.py`, `test_settings.py` | Sealed-store guard and its tests (`python3 -I .claude/hooks/test_guard.py`); checks on `settings.json` (`python3 -I .claude/hooks/test_settings.py`). |
| `.claude/README.md` | What each safeguard enforces and where it can be bypassed. |

How the process maps to the methods we follow:

- **Specification-first, small tickets (Matt Pocock style):** the skill's stages 1-2 (clarify, grill, spec in `docs/specs/`, tickets in `docs/tickets/` with acceptance criteria, scope exclusions, risk), one scoped ticket at a time, test-first through `tdd` where it fits, progress in the ticket, retrospective at milestone ends.
- **Verification first (Lauren Tan style):** reproduce before fixing, run the real path, never claim red/green or a pass that did not happen, regression test for every fix, one independent reviewer, then report and stop (the Owner decides what follows a BLOCK; no automatic re-review), recurring mistakes become tests or hooks.
- **DriveMind rules:** held-out privacy, Owner approval for spend, no push or deploy, disposable test databases only.

**Plugin dependency.** Matt Pocock's skills come from the plugin `mattpocock-skills@claude-plugins-official`. It is **account-and-config-specific** (section 15). `/grill-with-docs`, `/to-spec`, `/to-tickets`, `/implement`, `/retro` are user-invoked only; the agent cannot call them. If the plugin is missing the process still works: the DriveMind skill tells the agent to run the clarification interview and write the spec and tickets by hand in the repo formats. Nothing from the plugin is copied into this repository.

## 4. Invoke the workflow

- Type `/drivemind-engineering` and give the task, or just say "implement ticket 08-D"; the skill is model-invocable and `CLAUDE.md` points to it.
- Tiny well-defined fixes skip spec, ticket and reviewer (skill, stage 0).
- Independent review is automatic after verification: the agent launches one fresh `drivemind-reviewer` (read-only: Read/Grep/Glob) with the ticket and spec, base commit, a saved diff file, code/test locations and the raw test output. The agent ran those tests, so the reviewer judges **implementer-produced** output; that is not the same as independently running them. **After the review the workflow stops and reports.** On BLOCK or NEEDS-EVIDENCE the agent does not fix anything; the Owner decides the follow-up. The agent never starts the next ticket by itself.

## 5. Verify the reviewer is available

In Claude Code, run `/agents`: `drivemind-reviewer` must be listed. A direct check without a model call is not available; the end-to-end test is in section 12. If it is missing: you are not in the repository folder, project trust was declined, or the session started before the file existed (restart it).

## 6. Start development on the existing branch

```bash
cd ~/Developer/DriveMind_AI
git status -sb && git log --oneline -5        # expect feature/v2-state-performance; see the status file for the expected HEAD
git switch feature/v2-state-performance      # only if you are on another branch and the tree is clean
cm      # or `ca`: see section 15 for which account each opens
```

Do not create a new branch without a need; do not push.

## 7. Test and check commands (from the repository root)

Verified on 2026-11-23: the container-free evaluation tests, `cd backend && env -u OPENAI_API_KEY -u SESSION_TEST_DATABASE_URL -u QDRANT_TEST_URL uv run pytest -q tests/evaluation` gave **852 passed, 8 skipped in 226 s**.

| Purpose | Command |
|---|---|
| Hook and settings tests | `python3 -I .claude/hooks/test_guard.py && python3 -I .claude/hooks/test_settings.py` |
| Backend focused | `cd backend && uv run pytest -q tests/<area>/<file>.py` |
| Backend static | `cd backend && uv run ruff check app tests && uv run ruff format --check app tests && uv run mypy app` (`basedpyright app` clean; `tests/` has a known 48-error baseline, `AGENTS.md`) |
| Backend full (container tests) | `cd backend && uv run pytest -q` with `SESSION_TEST_DATABASE_URL`, `QDRANT_TEST_URL`, `CONVERSATION_TEST_QDRANT_URL` pointing at **disposable loopback** databases (database name starts `drivemind_session_test`; Qdrant not on 6333/6334) and `OPENAI_API_KEY` **unset**. Slow (32 min in the last recorded run, `AGENTS.md`); run nothing heavy beside it. Set the variables per command or in your shell; they are not in any committed file. Use the user and password you gave the test PostgreSQL container; they are not recorded here. |
| Frontend | `cd frontend && npm test && npm run lint && npm run build` |

## 8. Local infrastructure

Two kinds exist; do not confuse them:

- `infra/docker-compose.yml` (ports 5432 / 6333): the app's local development stack. `docker compose -f infra/docker-compose.yml ps` showed nothing running on 2026-11-23.
- The **disposable test and evaluation containers** `drivemind-test-pg` (PostgreSQL 18, `127.0.0.1:55432`) and `drivemind-test-qdrant` (`127.0.0.1:56333`). They were started outside the repository's compose file; this repository does not record how. Evaluation commands default to these ports (`backend/evaluation/rag_eval/target.py`).

Check, all read-only:

```bash
docker ps --format '{{.Names}}  {{.Ports}}  {{.Status}}'
docker exec drivemind-test-pg psql -U postgres -Atc "select datname from pg_database where not datistemplate"
curl -s http://127.0.0.1:56333/collections
docker start drivemind-test-pg drivemind-test-qdrant    # only if they are stopped (the container data stays in its volume)
```

If the containers are gone, the evaluation stores must be rebuilt. That costs a paid embedding call (about 0.02-0.05 USD; ticket 08) and needs the Owner's approval. Stop and ask.

## 9. Evaluation data, frozen corpus and the v3 index

- **Question pools:** development, regression, held-out. Files in `backend/evaluation/datasets/`; frozen by checksum in `m1_freeze.json`, changes logged in `m1_amendments.json`. Held-out cases are **not** in the repository. Details and every free command: `docs/guides/EVALUATION.md`.
- **Frozen corpus:** the synthetic "Marrowdale" documents, version `m1-corpus-v1-a605f90dc57b` (manifest `backend/evaluation/corpus/v1_manifest.json`), plus public PDFs fetched into git-ignored `backend/evaluation/corpus/public/`.
- **Stores:** frozen commands use their own store `drivemind_eval_v3` (PostgreSQL database and Qdrant collection of the same name; `--store vN` picks another). `v2` is legacy and refused by frozen commands.
- **Receipt and gate:** a passing `cli setup --frozen` writes `index_manifest_<corpus>_<store>_<time>.json` in `backend/evaluation/results/` (git-ignored). Every frozen paid command calls `index_verify.require_verified_index` first and refuses on a missing or stale receipt.
- **Free verification of the store:** `cd backend && env -u OPENAI_API_KEY uv run python -m evaluation.rag_eval.index_verify verify --store v3`. On 2026-11-23: verified, 82 files, 1508 chunks, 1508 vectors.
- **Free questions-set checks:** `uv run python -m evaluation.rag_eval.pools validate`, `uv run python -m evaluation.rag_eval.coverage`, `uv run python -m evaluation.rag_eval.freeze check` (from `backend/`).

## 10. Held-out privacy and Owner attestation

- The sealed file lives **outside** the repository in `~/.drivemind-eval-sealed/` (owner-only permissions). The Owner backs it up. The loader finds it through the environment variable `DRIVEMIND_EVAL_HELDOUT_FILE`.
- A paid held-out run is refused unless the Owner's review attestation (a file beside the sealed file) matches the sealed file's checksum and the freeze manifest (`review_gate.py`). `pools attest-review` is **Owner only, interactive; no agent runs it**.
- Ordinary sessions must not read the store, review sheets or authoring transcripts, must not tune on held-out cases and must not put held-out ids or text in Git, logs or reports. The hook `.claude/hooks/guard.py` blocks obvious access. The Owner opens a private review with `DRIVEMIND_PRIVATE_REVIEW=1 claude`.
- Limits of the hook are in `.claude/README.md` (it reads command text; it does not stop a script that opens the file itself).

## 11. Paid API operations

An approval prompt is **not** a spending cap. Two different protections exist; know which one a command has (full table with the code facts: `.claude/README.md`, "Paid-capable entry points").

| Command (`uv run python -m evaluation.<module>`, from `backend/`) | Cost control in the code | Claude Code prompt |
|---|---|---|
| `rag_eval.cli setup \| run \| rescore`, `rag_eval.retrieval_probe`, `rag_eval.first_step_probe`, `rag_eval.planted_claims`, `rag_eval.ragbench_check` | **Metered, hard `--cap USD` required** (program-side estimate from token counts; stops at the cap) | yes (`ask`) |
| `intent_eval --execute`, `agent_smoke_runner --execute`, `runner --execute-gold`, `conversation_runner --execute-conversation` | **No meter, no cap.** Only the opt-in flag guards them (`agent_smoke_runner` also asserts a branch that is not this one) | yes (`ask`); the prompt is the only gate, so do not approve without a specific Owner decision |

- Each prompt appears only for commands that name one of these modules after `python`; it also appears on free `--plan` runs. Not covered: a wrapper script, `python -c` or an import, `cd backend/evaluation && python runner.py`, `uv run <file>.py` without `python`, and bypass permission modes (`.claude/README.md`).
- Sequence: free dry run (`setup --plan`, dataset validation) → state the estimated cost and cap to the Owner → the Owner approves that run → run with `--cap` → report measured spend from the meter. For the four uncapped harnesses there is no estimate to check, so the Owner approves each run in words first. Never raise a cap or edit `prices.json` to make a plan fit. Reviewer approval is never spend approval.
- The Owner reads the provider balance; it is not stored in the repository. Never let it go negative. The provider balance is the only limit that works outside the program. The chat model `gpt-5.4-nano` has a shutdown date (`docs/DECISIONS.md`, 2026-11-20).
- These rules and the hook are accident prevention, not a sandbox (`.claude/README.md`, last section).

## 12. Confirm the workflow is active (fresh-session checklist)

In a **new** session started in the repository folder, paste:

> Without editing anything: (1) name the project instructions files you loaded; (2) list the project skills and subagents available; (3) read `docs/guides/CURRENT_DEVELOPMENT_STATUS.md` and tell me the current branch, HEAD, current ticket and next step; (4) launch `drivemind-reviewer` on a harmless fabricated task and tell me whether it can write a file.

Expected: `CLAUDE.md` plus `AGENTS.md`; skill `drivemind-engineering` and agent `drivemind-reviewer`; the status file's snapshot; the reviewer stating that it has no Bash or Write tool (so it cannot write a file). If a part fails, use section 13.

## 13. Diagnose missing permissions, hooks or plugins

| Symptom | Check |
|---|---|
| Skill or agent not listed | Are you in the repo folder? Did you accept project trust? `git status` shows `.claude/` present? Restart the session. |
| Reviewer still has Bash, or reports other tools than Read/Grep/Glob | The docs describe a file watcher for `.claude/agents/`, but an older session in this project still used a stale definition; restart the session, then repeat section 12. |
| `/grill-with-docs`, `/to-spec`, `/retro` unknown | Plugin not installed in this account's config: `claude plugin list`; install in section 14. |
| Hook not firing | `/hooks` in the session; `python3 -I .claude/hooks/test_guard.py` for the script itself. |
| Reviewer fails to start or model error | The account may not offer the model in `.claude/agents/drivemind-reviewer.md` (`model: opus`) or is out of allowance. Use a session-level override, or change it to `sonnet` locally **without committing that change**; record why and say in the report that the review ran on a smaller model. |
| Permission prompts differ | `/permissions`; project rules come from `.claude/settings.json`. |

## 14. Reinstall the Matt Pocock plugin

Verified from `claude plugin --help` (installed version 2.1.330), **not run** on the second config:

```bash
claude plugin list                                              # current account/config
claude plugin install mattpocock-skills@claude-plugins-official # marketplace `claude-plugins-official` (github anthropics/claude-plugins-official)
claude plugin list                                              # confirm it is installed and enabled
```

For the annual config prefix the commands with `CLAUDE_CONFIG_DIR="$HOME/.claude-annual"`. Skills appear after a restart. If `claude plugin` is unavailable, use `/plugin` inside a session. The plugin was installed 2026-11-20 on the monthly config at version 1.3.1.

## 15. Switching Claude Code accounts on the same Mac

Facts found on this Mac (2026-11-23; credentials not read):

- Two separate Claude Code config folders. `~/.claude` is the default (alias `cm`, `claude-monthly`). `~/.claude-annual` is selected by `CLAUDE_CONFIG_DIR` (alias `ca`, `claude-annual`; defined in `~/.zshrc`).
- Each folder holds its own **login, installed plugins, project trust decisions and memory notes**. The user-level `~/.claude/CLAUDE.md` is symlinked into the annual folder, so it applies to both.
- Today the Pocock plugin is enabled only in `~/.claude`. `~/.claude-annual` has the marketplace cached but no plugin installed or enabled. The DriveMind memory notes (OpenAI credit rule, model shutdown, verification feedback) exist only in `~/.claude`; the credit rule is deliberately not copied (it carries balances; section 11 states the rule), the model-shutdown fact is in `docs/DECISIONS.md`, and the verification rule is in `CODING_STANDARDS.md` and the skill.

Sequence (commands checked against `claude auth --help` and `claude --help`; none run for this guide):

1. Finish or park the current work: `git status`; update the status file if a checkpoint was completed. Exit the session (`/exit`).
2. Open a terminal in the repository: `cd ~/Developer/DriveMind_AI`.
3. Start the other account's folder with its alias (`ca` for annual, `cm` for monthly). This keeps both logins intact. Only if that folder is not signed in, use `/login` inside the session or `claude auth login` (add `--claudeai` for a subscription). `claude auth status` shows which account a folder uses. Avoid `claude auth logout` unless you mean to sign that folder out.
4. Accept the project-trust prompt for the DriveMind folder (trust is stored per config folder). Hooks and project permissions need it.
5. Check plugins: `claude plugin list`. If `mattpocock-skills` is missing, install it (section 14) and restart.
6. Check loading: run the section 12 checklist.
7. Confirm Git and checkpoint: `git status -sb`, `git log --oneline -5`, then the status file's "Snapshot" and "Next step".
8. Resume. Do not paste secrets or held-out material into the session; do not start paid runs without the Owner's approval for that run.

A different subscription may not offer the same models, plugins or usage allowance. Nothing in this repository assumes it does.

## 16. Limits of this handoff

- Fresh-session behavior of the annual config has not been run (it would use that account). Run the section 12 checklist there once.
- The hook and permission rules are accident guards, not a sandbox (`.claude/README.md`).
- Local runtime state (containers, v3 store, receipt, sealed file) is not in Git; section 8-10 say how to re-check it.

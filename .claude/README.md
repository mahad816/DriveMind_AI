# .claude: DriveMind workflow components

| File | Purpose |
|---|---|
| `../CLAUDE.md` | Short rules; imports `AGENTS.md` (needed because a `CLAUDE.md` makes Claude Code skip a lone `AGENTS.md`). |
| `skills/drivemind-engineering/SKILL.md` | The lifecycle. Model-invocable; also `/drivemind-engineering`. |
| `agents/drivemind-reviewer.md` | Read-only independent reviewer (opus, fresh context, no Bash/Write/Edit/Agent). Returns APPROVE, BLOCK or NEEDS-EVIDENCE; may ask the main session for extra checks. |
| `settings.json` | Deny/ask permission rules and the PreToolUse hook registration. |
| `hooks/guard.py`, `hooks/test_guard.py` | The guard and its tests: `python3 -I .claude/hooks/test_guard.py`. |
| `hooks/test_settings.py` | Checks `settings.json` (valid; every paid entry point has an ask rule; secret files are denied): `python3 -I .claude/hooks/test_settings.py`. |

Portability, account switching and the fresh-session checklist: `docs/guides/CLAUDE_CODE_HANDOFF.md`. Current state: `docs/guides/CURRENT_DEVELOPMENT_STATUS.md`. Everything in this folder except `worktrees/`, `settings.local.json` and Python caches is tracked by Git; per-account items (login, plugin install, trust, memory) are not.

## What is enforced and how

| Safeguard | Mechanism | Limit |
|---|---|---|
| Reviewer cannot edit, run commands or spawn agents | `tools: Read, Grep, Glob` and `disallowedTools: Bash, Write, Edit, NotebookEdit, Agent` | Tool-level; no text-matching involved. Verify live with the fresh-session checklist (handoff guide, section 12). The sealed-store hook still applies to its Read/Grep/Glob. |
| Sealed held-out store closed | Hook on Bash/Read/Grep/Glob in every session and subagent; opt-in `DRIVEMIND_PRIVATE_REVIEW=1` | Does not stop a script that opens the file itself (`python -c`, the eval CLI loader), paths built from variables or globs, recursive Bash search from the home directory, or symlinks. Real protection also needs the file's owner-only permissions and the attestation gate in `review_gate.py`. |
| No push, hard reset, clean, Railway | `permissions.deny` | Command-prefix matching; a differently spelled command may slip through. |
| Paid eval commands and commits prompt the Owner | `permissions.ask` (nine paid entry points, table below; plus `git commit`) | **An approval prompt, not a spending cap.** Matches command text only, and the Owner must read it. Not covered: a wrapper script, `python -c` or an import of these modules, `python runner.py` after `cd` into `backend/evaluation`, `uv run <file>.py` without `python`, a bypass permission mode. The prompt does not check the cap value, and it also appears on free `--plan` runs. |
| Secret files not readable by Claude: `.env`, `.env.*` (so `.env.example` is blocked too), `credentials.json`, `token.json`, `*.pem`, in any folder | `permissions.deny` `Read(**/name)`; applies to the Read tool and, best effort, to Grep, Glob and `cat`-style Bash commands | Probed 2026-11-23 with **nonexistent** fabricated paths (`.env`, `.env.local`, `.env.production`, `credentials.json`, `token.json`, `*.pem` at several depths; the Read tool refused every one, `cat` through Bash refused `.env.local`, an ordinary file was not refused). Does not stop a script, `grep -r` or `python -c` that opens a file itself, and other secret names are not listed. |

Not verified automatically: that the Owner's `ask` prompts appear in every permission mode (for example bypass modes skip them).

## Not an enforced boundary (instruction-only)
`CLAUDE.md` and the skill ask for: no paid calls without the Owner, no fixing after the review, no starting the next ticket on its own, no reading `.env`, reading any reviewer-requested probe before running it. Nothing technical enforces these except the permission rules and the hook above; a `bypassPermissions` session skips prompts for allow/ask rules (deny rules still block). The reviewer's lack of Bash, Write, Edit and Agent **is** enforced by its tool list (checked live 2026-11-23: it reported only Read, Grep, Glob). Docs checked 2026-11-23 (code.claude.com: sub-agents, sandboxing, hooks, permissions): `Bash(pattern)` inside a subagent's `tools:` is not documented, so it is not used; settings hooks do fire inside subagents; Read deny rules reach Grep/Glob only best-effort.

**History:** a sandboxed verification executor (macOS `sandbox-exec`) was built and removed on 2026-11-23 as out of proportion; during its review the sandbox was found reachable by writes through system daemons. The reviewer therefore stays read-only and the main session runs any safe checks it requests. Stronger independent execution (a separate session or the Owner running the tests) is the answer for sensitive changes, not a custom sandbox.

## Paid-capable entry points (checked 2026-11-23 from the code; nothing was run)

`ask` is an approval prompt. Only a **hard cap** limits spending, and only the first five rows have one: the program meters estimated cost from token counts (`rag_eval/meter.py`), requires `--cap USD` and stops when the cap is reached. The last four have no meter and no cap; each is guarded only by an opt-in flag. A meter is a program-side estimate, not a provider-side limit; the provider balance is the only external limit and is not recorded here.

| Module (`python -m evaluation.<module>`) | Paid when | Metered, capped | Other guard in the code |
|---|---|---|---|
| `rag_eval.cli` | `setup`, `run`, `rescore` (`--plan` is free) | yes, `--cap` required; refuses to start if the estimate exceeds it | frozen commands need the verified-index receipt; held-out needs the Owner attestation |
| `rag_eval.retrieval_probe` | always (query embeddings) | yes, `--cap` required | |
| `rag_eval.first_step_probe` | always (chat) | yes, `--cap` required | |
| `rag_eval.planted_claims` | always (chat) | yes, `--cap` required | |
| `rag_eval.ragbench_check` | always (chat; also downloads RAGBench) | yes, `--cap` required | |
| `intent_eval` | with `--execute` | **no** | dry run without the flag |
| `agent_smoke_runner` | with `--execute` | **no** | asserts branch `refactor/tool-orchestrated-rag`, so it refuses elsewhere (a side effect, not a spending design) |
| `runner` | with `--execute-gold` | **no** | needs a clean Git tree unless `--allow-dirty` |
| `conversation_runner` | with `--execute-conversation` | **no** | dry run without the flag |

Free executable modules (no provider call): `rag_eval.corpus_v1`, `coverage`, `fetch_public` (downloads public PDFs), `freeze`, `index_verify`, `messy_fixtures`, `pools`. `test_settings.py` fails if a new executable module appears that is in neither list, so a new harness must be classified.

## Accident prevention, not a sandbox

The permission rules and the hook stop mistakes and the obvious attempts. They match command text and path patterns, do not follow scripts, symlinks or variables, and a `bypassPermissions` session skips ask prompts. They are not a security boundary against a determined or confused session; the real controls are the Owner reading each prompt, the cap flags above, the sealed file's permissions and the attestation gate.

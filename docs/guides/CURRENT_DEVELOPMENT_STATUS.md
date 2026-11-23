# Current development status

The one place a fresh session reads to learn where DriveMind stands. Keep it short and factual: one row per checkpoint, newest first, no history essays (that is `docs/DECISIONS.md`) and no per-run numbers beyond what a checkpoint needs. The `drivemind-engineering` skill updates it after each meaningful checkpoint. The older `docs/CURRENT_STATUS.md` (Phase 11) and `docs/HANDOFF_2026-11-21.md` are historical.

**Never put here:** held-out questions, answers, anchors, ids or per-case results; secrets; account details; provider balances; paths inside the sealed store beyond its directory name.

How to read the evidence tags: **[git]** proven by a commit or a committed file; **[local]** checked on the Owner's Mac at the audit time and gone in another checkout; **[owner]** reported by the Owner, not found in the repository; **[unverified]**.

## Snapshot (audit of 2026-11-23)

| Item | Value |
|---|---|
| Branch / HEAD | `feature/v2-state-performance`; M1-08-D is committed at `f8027a0` [git]. M1-08-E is committed locally after it, in the commit named `feat(eval): add model-written query evaluation and passage comparison (M1-08-E)` (find it with `git log --oneline --grep='M1-08-E'`; no SHA is written here). Never pushed. |
| Remote | 52 commits ahead of `origin/feature/v2-state-performance`; nothing pushed by this work [git] |
| Workflow files | Written 2026-11-23. A local commit named `chore(workflow): add engineering workflow and account handoff` was authorized **only on an APPROVE**: if `git log --oneline --grep='chore(workflow)'` shows it, the files are committed; if not, they are still uncommitted (untracked `.claude/`, `CLAUDE.md`, two guides; modified `.gitignore`, `docs/tickets/README.md`). `.claude/worktrees/` and `settings.local.json` are git-ignored. Never pushed. |
| Current milestone | M1 RAG evaluation, `docs/specs/m1-rag-evaluation.md`; tickets in `docs/tickets/m1-rag-evaluation/` |
| Current ticket | `08-retrieval-measurement-on-the-new-corpus.md`, `Progress: open` [git], worked in lettered checkpoints |
| Next checkpoint | M1-08-D and M1-08-E are complete (committed locally). Next: **M1-08-F** (free: reconcile drift, record the rebuild, confirm every gate). **M1-08-G remains paid** and needs the Owner's approval of the estimate and cap. Checkpoints A to G are defined in ticket 08 Comments. |

## Checkpoint log (newest first)

| Checkpoint | Commit | Implementation | Independent review | Tests actually run | Notes |
|---|---|---|---|---|---|
| M1-08-E model-written-query probe (`first_step_probe`): modes `model`/`baseline`/`both`, repeats 1 to 5, pool selection, free `--plan`, cap refusal, `--passage` (only with `--mode both`), plus Owner-authorized corrections | local commit named in the Snapshot (no SHA recorded here) | implemented [git, once committed]: `first_step_probe.py`, `probe_pools.py`, `passage_metrics.py` (one optional argument), three new test files, fixtures of `test_index_gate.py` and `test_probe_corpus_selection.py`, ticket 08 | Three fresh `drivemind-reviewer` rounds, each reading code and running nothing: round 1 **BLOCK** (P2: passage figures of the model queries over a different case set than the baseline), round 2 **BLOCK** (P2: `--passage` without `--mode both` wrote an unmeasured baseline), round 3 **APPROVE**, no confirmed defect. Each P2 was corrected only after Owner authorization. The review reports are in the session transcript; ticket 08 records the findings and corrections [local, not otherwise stored in Git]. | `tests/evaluation`, container-free, `OPENAI_API_KEY` unset: **969 passed, 8 skipped** [local]. The 8 skips need the sealed held-out file or a session test database. The full backend suite was **not** run (`git diff -- backend/app` is empty). ruff, format, `mypy app` and the three touched modules clean, basedpyright 0 errors on touched files, free CLI plan and refusal probes run. | No paid call, no held-out access, no index change. The cap is **not** a hard spending limit (no output limit on the request, SDK default 2 retries below the meter, the meter checks between calls); reasoning-token behaviour unverified. `--mode both` plan for the development pool is about 0.36 USD and development plus regression about 0.51 USD, above the ticket's 0.40 USD cap: an Owner decision at G. Open items for F and G are in ticket 08 (dataset symlink and `cli run --dataset` path, report-write risk, missing `--mode both` integration tests, held-out items before G, P3 list). Next: F. |
| M1-08-D retrieval probe: pool selection, held-out gate, free `--plan` and cap refusal, plus Owner-authorized corrections | `f8027a0` [git] | implemented [local]: `probe_pools.py` (new), `retrieval_probe.py`, fixtures in `test_index_gate.py` and `test_probe_corpus_selection.py` | Round 1 **APPROVE** (one P2: `--frozen --messy` silently ignored). Round 2, after the Owner-authorized corrections (frozen+messy rejected, held-out fails closed, held-out exceptions reduced to the class name, cap compared at full precision): fresh `drivemind-reviewer` **APPROVE**, no confirmed defect; P3 items listed in ticket 08 and the report. Both reviewers read code and ran nothing. | `tests/evaluation` container-free: **905 passed, 8 skipped** [local]; `test_probe_pools.py` plus two fixture files: 82 passed; ruff, format, mypy clean, basedpyright 0 errors on touched files | No paid call, no sealed file read, `git diff -- backend/app` empty. Open before any held-out paid run: `cli run` accepts `--threshold` on held-out. The `first_step_probe` gap was closed by E. |
| Engineering workflow setup (simple): `CLAUDE.md`, skill, read-only reviewer, hook, guides, spend and secret-file rules | see Snapshot, "Workflow files" (committed only after an APPROVE) | implemented [local] | Round 1: **BLOCK** (P2: four uncapped paid harnesses had no approval prompt and the guides listed only three paid commands; unverified: `.env` deny patterns). Corrected afterwards: nine paid entry points now prompt, `.env`, `.env.*`, `credentials.json`, `token.json`, `*.pem` denied in any folder (probed with nonexistent paths). Round 2: a fresh `drivemind-reviewer`; if the commit above exists, round 2 returned APPROVE. **The earlier sandboxed executor was removed.** | `.claude/hooks/test_guard.py` 12 OK, `.claude/hooks/test_settings.py` 8 OK [local] | No product code changed. No paid call. Workflow rule: review, report, STOP; no automatic fixes. Next checkpoint unchanged: M1-08-D. |
| M1-08-C passage-level retrieval metrics | `c81bf6b` | committed [git] | APPROVE [owner]; no review text in the repo | `tests/evaluation`, container-free: **852 passed, 8 skipped** in 226 s, rerun by the audit session on 2026-11-23 [local] | Free tests only, on fabricated hits. No paid call. |
| M1-08-B-Fix fresh frozen store, deep verification, execution gate | `384b0ac` | committed [git]; described in ticket 08 Comments | approved [owner]; not recorded in the repo | `index_verify verify --store v3`: verified, 82 files, 1508 chunks, 1508 vectors, matches the receipt [local] | Frozen commands gate every paid call on the receipt. |
| M1-08-B frozen corpus selection and index manifest | `8aa53ec` | committed [git] | approved [owner]; not recorded in the repo | see above | |
| M1-07-F/E/D/C, M1 ticket 07 | `c6a49e3` ... `89c9b8a` | committed [git] | Owner review of the sheet: 36 checked, 36 correct, 0 gold wrong [git, ticket 07] | held-out and gate tests in `tests/evaluation` (part of the 852) | A file with the attestation's name sits beside the sealed file, outside the repo [local, name only; contents not read, validity not checked]. Ticket 07 in Git still says "No attestation exists yet" (see "Known drift"). |
| M1-01 .. 06 | see `git log` | ticket `Progress:` says "complete" (01-03) or "resolved" (04-06) [git] | per-ticket Findings | per-ticket Findings | |
| M0-SEC (tickets 01-09), M0 audit (01-09) | see `git log` | M0-SEC 01-02 and 09 "complete"; 03-08 "implemented" or "findings written" "and committed locally ... not pushed" (wording differs per ticket); M0 audit 01-09 "resolved" [git] | reviews recorded in the tickets; closeout in M0-SEC ticket 09 | `AGENTS.md` "Latest recorded verification" (3245 backend tests, one qualified baseline) | |

There is no commit or ticket text for an "M1-08-A", and the repository never names D, E, F or G. Those letters exist in commit messages (B, B-Fix, C) and in the Owner's notes only.

## Local runtime state (not in Git; gone in a fresh checkout)

| Item | State at audit | How to re-check (all free, read-only) |
|---|---|---|
| Containers | `drivemind-test-pg` (PostgreSQL 18, 127.0.0.1:55432) and `drivemind-test-qdrant` (127.0.0.1:56333) up [local] | `docker ps` |
| Eval store `v3` | PostgreSQL database and Qdrant collection `drivemind_eval_v3` exist; **82 files, 1508 chunks, 1508 vectors**, verified deep [local] | `cd backend && env -u OPENAI_API_KEY uv run python -m evaluation.rag_eval.index_verify verify --store v3` |
| Setup receipt | `backend/evaluation/results/index_manifest_m1-corpus-v1-a605f90dc57b_v3_20261123_091309.json`, `origin: setup`, model `text-embedding-3-small`, 1536 dimensions; git-ignored [local] | same command |
| Other stores | `drivemind_eval_v2` (legacy; frozen commands refuse it), `drivemind_eval_v98`, `drivemind_session_test`, and many `tenant_inventory_test_*` Qdrant collections [local] | `docker exec drivemind-test-pg psql -U postgres -Atc "select datname from pg_database"` |
| Sealed held-out store | `~/.drivemind-eval-sealed/` exists with owner-only permissions; contents deliberately not inspected [local] | Owner only: the hook blocks ordinary sessions from naming this directory |
| Rebuild cost | **0.01878 USD** [owner]. The receipt records no cost and no committed file does. | none until it is recorded in ticket 08 |

## Known drift between sources

- Ticket 08's committed Comment (B-Fix) still says "The paid rebuild into v3 has not been run". The local store shows it was run later that day. Record the rebuild (receipt name, cost, Owner approval) in ticket 08 before relying on it.
- Ticket 07 (`## Findings`) says no Owner review attestation exists yet and that every paid held-out run refuses until the Owner runs `pools attest-review`. Later commits (`3271550`, `c6a49e3`) record the review and add the gate, and a file with the attestation's name exists locally, but Git holds no record that the attestation was written or that it matches the sealed file. Treat the attestation gate as **unverified**; `require_review` in `review_gate.py` checks it at run time, and ticket 08 lists `pools attest-review` as a separate required gate.
- Ticket 08's scope estimates the embedding rebuild at about 0.05 USD, and its B-Fix comment records the `setup --plan` figure of 0.0335 USD. Both differ from the Owner-reported actual (0.01878 USD). Not reconciled.

## Not verified

- That checkpoints B, B-Fix and C were independently approved, and what the reviewers said: only the Owner's report exists.
- The 0.01878 USD figure and that no other paid call has happened since. No spend log is committed; use the provider's billing page.
- That a vector is the embedding of its chunk's text (needs a paid call; the verifier says so).
- A real held-out run has never been made. Held-out file contents and the attestation were not read, so whether the attestation is valid is unknown.
- That the skill and reviewer load on the **annual** account: verified only on the account used for the 2026-11-23 setup. Run the handoff guide's section 12 checklist there once.

## Restrictions in force

- **No paid retrieval or answer evaluation is authorized** [owner; the repository records no authorization, and ticket 08 requires separate Owner gates before spend: the review of the sheet (done, 36 of 36, ticket 07), the Owner's `pools attest-review` binding that review to the sealed file (a local file exists; not verified, see "Known drift"), and approval of the `--plan` estimate and cap (not recorded)].
- Held-out material is closed to ordinary sessions (hook `.claude/hooks/guard.py`; Owner opts in with `DRIVEMIND_PRIVATE_REVIEW=1`). Never tune on it.
- No push, deploy, Railway or destructive database operation without explicit approval. `attest-review` is Owner-only.
- Never let the provider balance go negative; spend only on runs that can change a decision, and state the estimated cost before each paid step. Ask the Owner for the balance; it is not recorded here.

## Next step

1. Read `docs/tickets/m1-rag-evaluation/08-retrieval-measurement-on-the-new-corpus.md` (checkpoint table, "M1-08-E findings", the two correction sections, the D findings) and `docs/specs/m1-rag-evaluation.md`.
2. **M1-08-F (free, not started):** reconcile the drift listed above, record the rebuild, the price-table date and the `--plan` figures, check the other `load_cases` callers (`cli`, `runner`), add the missing integration and P3 tests, and confirm every gate end to end with disposable stores.
3. **M1-08-G (paid, blocked on Owner gates):** needs the attestation, the Owner's approval of the estimate and a cap, and the held-out items in ticket 08. Everything before the Owner's approval of a cost estimate is free. Stop at that gate.

## Specification and ticket paths

- Spec: `docs/specs/m1-rag-evaluation.md`; also `docs/specs/drivemind-v1-product-definition.md` (the M9 gate before any redeploy with sign-in on).
- Tickets: `docs/tickets/m1-rag-evaluation/` (08 open, 09 to 13 open), `docs/tickets/m0-sec-security-hardening/`, `docs/tickets/m0-system-audit/`.
- Decisions and history: `docs/DECISIONS.md`; open defects: `docs/KNOWN_ISSUES.md`; how to run evaluation: `docs/guides/EVALUATION.md`; how to continue with Claude Code: `docs/guides/CLAUDE_CODE_HANDOFF.md`.

# DriveMind AI — Git Workflow

Commit discipline and branch rules for maintaining a clean, portfolio-quality repository.

---

## Principles

1. **Small, meaningful commits** — one logical change per commit
2. **Review before commit** — always check `git status` and `git diff`
3. **Never commit secrets** — `.env`, tokens, credentials, downloaded files
4. **Phase-aligned commits** — group work by roadmap phase
5. **Approval before commit** — show diff summary and get approval before committing

---

## Branch Strategy

### Main Branch

- `main` — stable, working code
- Protected: only merge reviewed, tested work
- Each phase should leave `main` in a runnable (or clearly documented) state

### Feature Branches (Optional)

For larger phases, use feature branches:

```
main
  └── feat/phase-1-backend-foundation
  └── feat/phase-3-drive-integration
```

Branch naming:

```
feat/<short-description>    # new feature
fix/<short-description>     # bug fix
docs/<short-description>    # documentation only
chore/<short-description>   # tooling, config, deps
test/<short-description>    # tests only
```

Merge via pull request or direct merge after phase approval.

---

## Commit Message Format

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short description>

[optional body]
```

### Types

| Type | When to use |
|------|-------------|
| `feat` | New feature or capability |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `chore` | Tooling, config, scaffolding |
| `test` | Adding or updating tests |
| `refactor` | Code change without behavior change |
| `perf` | Performance improvement |

### Scopes

Use module names: `backend`, `frontend`, `db`, `drive`, `ingestion`, `retrieval`, `agent`, `eval`

### Examples

```
chore: initialize DriveMind repository
docs: add project context and architecture
feat(backend): add FastAPI application foundation
feat(db): add drive file and chunk models
feat(drive): add read-only Google Drive client
feat(ingestion): add PDF text extraction
feat(retrieval): add hybrid result merging
feat(agent): add LangGraph citation verification node
test(backend): add health endpoint tests
fix(retrieval): deduplicate chunks in merge step
```

### Rules

- Subject line: imperative mood, lowercase, no period, max ~72 chars
- Body: explain **why**, not just what (when needed)
- One concern per commit — do not mix unrelated changes

---

## Phase Commit Checklist

Before each commit during a phase:

- [ ] Changes match the approved phase scope only
- [ ] No secrets, `.env`, or local data files staged
- [ ] No unrelated formatting or drive-by refactors
- [ ] Tests pass (when tests exist for that phase)
- [ ] `git diff` reviewed
- [ ] Commit message follows format above
- [ ] User approved the commit

---

## What Never Goes in Git

| Item | Reason |
|------|--------|
| `.env` | Contains secrets |
| `credentials.json` / `token.json` | Google OAuth tokens |
| Downloaded Drive files | User data, not source code |
| `postgres_data/`, `qdrant_data/` | Local database volumes |
| `node_modules/`, `.venv/` | Dependencies (reinstall from lockfiles) |
| API keys in code | Use environment variables |

---

## Recommended Phase 0 Commits

When initializing the repository:

```bash
# Commit 1: Structure and config
git add .gitignore .env.example README.md infra/ backend/ frontend/ scripts/
git commit -m "chore: initialize DriveMind repository structure"

# Commit 2: Documentation
git add docs/
git commit -m "docs: add project context, roadmap, and architecture"

# Commit 3: Cursor rules
git add .cursor/
git commit -m "chore: add DriveMind Cursor project rules"
```

---

## Workflow Per Phase

```
1. Propose implementation plan for the phase
2. User approves scope
3. Implement approved changes only
4. Run checks (lint, tests, manual smoke test)
5. Show git diff summary to user
6. User approves commit
7. Create commit with conventional message
8. Update ROADMAP.md phase status if applicable
9. Move to next phase
```

---

## Approval Workflow with Cursor

- Use **Plan Mode** for architecture decisions and phase planning
- Switch to **Agent Mode** only after plan approval
- Agent should **not commit** unless explicitly asked
- Agent should show diff summary before any commit
- User reviews and approves each commit message

---

## Tags (Later)

After major milestones:

```
v0.1.0  — Phase 1 complete (backend foundation)
v0.2.0  — Phase 3 complete (Drive integration)
v0.5.0  — Phase 6 complete (basic RAG working)
v1.0.0  — MVP complete (LangGraph + frontend)
```

---

## Pull Requests (When Using Feature Branches)

PR title: same format as commit messages

PR body template:

```markdown
## Summary
- Bullet points of what changed

## Phase
Phase X: <name>

## Test plan
- [ ] Health endpoint returns 200
- [ ] Drive sync lists files
- [ ] Chat returns cited answer
```

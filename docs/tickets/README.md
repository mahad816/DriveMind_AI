# Tickets

Version-controlled Markdown tickets, organised by feature: `docs/tickets/<feature-slug>/NN-<slug>.md`, numbered from `01` in dependency order (blockers first). One ticket per file, never a combined file. Written by `/to-tickets` from a spec in `docs/specs/<feature-slug>.md`.

Each ticket is a vertical slice (a narrow but complete path through every layer that can be demonstrated or verified on its own, sized for one fresh context window):

```md
# NN: Title

**Spec:** docs/specs/<feature-slug>.md
**What to build:** the end-to-end behaviour this ticket makes work, from the user's perspective.
**Blocked by:** ticket numbers/titles, or "None (can start immediately)".
**Status:** a triage role from docs/agents/triage-labels.md (what the ticket is for)
**Progress:** open | claimed | resolved (what is happening to it)

- [ ] Acceptance criterion
- [ ] Acceptance criterion

## Comments
```

- A ticket is ready to start when every ticket in its `Blocked by:` line has `Progress: resolved`. Work the first unblocked ticket by number. A missing `Progress:` line means `open`.
- Set `Progress: claimed` before starting work and `Progress: resolved` when the work is finished and reviewed. `Status:` (triage) and `Progress:` (execution) are separate; see `docs/agents/issue-tracker.md`, which also overrides any `.scratch/` paths in the skills.
- Comments and progress append to the bottom under `## Comments`.
- Acceptance criteria are measurable; where a retrieval or answer-quality claim is made, name the frozen question set (see `docs/DECISIONS.md`, "a fix is only called fixed after a held-out question set and the full suite").

**This repository is public.** Never put secrets, credentials, private Google Drive contents, real file names or text from a user's Drive, or any sensitive user information in a ticket. Use invented examples.

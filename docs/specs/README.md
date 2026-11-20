# Specifications

One Markdown file per feature or product area: `docs/specs/<feature-slug>.md`. Written by `/to-spec` (or by hand) after a product-definition interview, and used by `/to-tickets`, `/implement` and the Spec axis of `/code-review`.

- Use the sections `/to-spec` produces: Problem Statement, Solution, User Stories, Implementation Decisions, Testing Decisions, Out of Scope, Further Notes. No file paths or code snippets in Implementation Decisions (they go stale).
- Use the vocabulary in `GLOSSARY.md` once it exists, and respect ADRs in `docs/adr/`.
- A spec may start with an optional `Status:` line holding a triage role from `docs/agents/triage-labels.md` (for example `ready-for-agent`, which `/to-spec` applies). Leave it out while the spec is a draft. Specs have no `Progress:` line; progress is tracked on their tickets.
- Tickets for a spec live in `docs/tickets/<feature-slug>/` (see `docs/tickets/README.md`). Link the spec from each ticket.
- Engineering and evaluation history stays in `docs/DECISIONS.md`; hard-to-reverse architectural or product decisions go in `docs/adr/`.

**This repository is public.** Never put secrets, credentials, private Google Drive contents, real file names or text from a user's Drive, or any sensitive user information in a spec. Use invented examples (the evaluation corpus is synthetic or public).
